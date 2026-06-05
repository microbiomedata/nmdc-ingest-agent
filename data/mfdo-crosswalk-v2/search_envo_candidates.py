"""Search OLS4 for ENVO candidates for each row in a land-cover mapping TSV.

Tries the OLS4 LLM embeddings endpoint first; falls back to lexical search
if the embeddings endpoint is unavailable (e.g. pgvector outage).

Input TSV must have columns: source_code, source_label
(i.e. the format of corine_envo_map.tsv and worldcover_envo_map.tsv).

Output TSV: source_code, source_label, candidate_curie, candidate_label,
            candidate_score, candidate_def, search_method

Usage:
  python3 search_envo_candidates.py corine_envo_map.tsv --out corine_candidates.tsv
  python3 search_envo_candidates.py worldcover_envo_map.tsv --out worldcover_candidates.tsv
  python3 search_envo_candidates.py corine_envo_map.tsv --top 5  # keep top-5 per row

The curator reviews the output, picks the best anchor-valid ELS term per row
(check against ENVO ELS allow-list), and updates the source mapping TSV.

OLS4 endpoints used:
  Embeddings: GET https://www.ebi.ac.uk/ols4/api/v2/classes/llm_search
              ?q=<label>&model=llama-embed-nemotron-8b_pca512&size=20
  Lexical:    GET https://www.ebi.ac.uk/ols4/api/v2/entities
              ?search=<label>&size=10&ontologyId=envo

Post-filtering: only ENVO hits are kept (ontologyId == 'envo').
Score threshold: embeddings hits below 0.78 are omitted as likely noise.
"""

import argparse
import csv
import sys
import time
import urllib.parse
import urllib.request
import json
from pathlib import Path

OLS4_BASE = "https://www.ebi.ac.uk/ols4/api/v2"
EMBED_MODEL = "llama-embed-nemotron-8b_pca512"
EMBED_SCORE_FLOOR = 0.78
RATE_DELAY = 0.5  # seconds between requests


def _get(url: str, timeout: int = 20) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def search_embeddings(label: str, n: int = 20) -> tuple[list[dict], str]:
    """Return (hits, method). Raises on server error so caller can fall back."""
    q = urllib.parse.quote(label)
    url = f"{OLS4_BASE}/classes/llm_search?q={q}&model={EMBED_MODEL}&size={n}"
    d = _get(url)
    if d.get("status") and str(d["status"]).startswith("5"):
        raise RuntimeError(d.get("message", "OLS4 embeddings error"))
    elements = d.get("elements", [])
    hits = [
        {
            "curie": e.get("curie", ""),
            "label": e.get("label", ""),
            "score": round(float(e.get("score", 0)), 4),
            "def": (e.get("description") or [""])[0][:120],
            "method": "embeddings",
        }
        for e in elements
        if e.get("ontologyId") == "envo"
        and float(e.get("score", 0)) >= EMBED_SCORE_FLOOR
    ]
    return hits, "embeddings"


def search_lexical(label: str, n: int = 10) -> tuple[list[dict], str]:
    q = urllib.parse.quote(label)
    url = f"{OLS4_BASE}/entities?search={q}&size={n}&ontologyId=envo&exactMatch=false"
    d = _get(url)
    elements = (d.get("elements") or
                d.get("_embedded", {}).get("terms", []))
    hits = [
        {
            "curie": e.get("curie", e.get("short_form", "")),
            "label": e.get("label", ""),
            "score": None,
            "def": (e.get("description") or [""])[0][:120],
            "method": "lexical",
        }
        for e in elements
        if e.get("ontologyId", e.get("ontology_name", "")) == "envo"
    ]
    return hits, "lexical"


def search(label: str, n: int = 5) -> list[dict]:
    try:
        hits, method = search_embeddings(label, n=max(n * 4, 20))
        if not hits:
            raise RuntimeError("empty embeddings result; falling back")
        return hits[:n]
    except Exception as e:
        print(f"  [embeddings unavailable: {e}; using lexical]", file=sys.stderr)
    hits, method = search_lexical(label, n=n)
    return hits[:n]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="TSV with source_code, source_label columns")
    ap.add_argument("--out", default="-", help="Output TSV (default: stdout)")
    ap.add_argument("--top", type=int, default=3,
                    help="Max candidates to emit per row (default: 3)")
    ap.add_argument("--code-col", default=None,
                    help="Column name for the source code (auto-detected if omitted)")
    ap.add_argument("--label-col", default=None,
                    help="Column name for the source label (auto-detected if omitted)")
    ap.add_argument("--skip-no-ols-needed", action="store_true",
                    help="Skip rows where env_local_scale is already filled and "
                         "ols_verified is 'yes'")
    args = ap.parse_args()

    rows = []
    with open(args.input, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    if not rows:
        sys.exit("No rows in input")

    # Auto-detect code and label columns: prefer source_code/source_label,
    # then any column ending in _code/_label.
    cols = list(rows[0].keys())
    def _pick(explicit, suffixes):
        if explicit and explicit in cols:
            return explicit
        if "source_code" in cols and "code" in suffixes:
            return "source_code"
        if "source_label" in cols and "label" in suffixes:
            return "source_label"
        for c in cols:
            if any(c.endswith(s) for s in suffixes):
                return c
        sys.exit(f"Cannot auto-detect column for {suffixes}; pass --code-col or --label-col")

    code_col = _pick(args.code_col, ("_code",))
    label_col = _pick(args.label_col, ("_label",))
    print(f"Using columns: code={code_col!r}  label={label_col!r}", file=sys.stderr)

    out_fields = ["source_code", "source_label", "candidate_curie",
                  "candidate_label", "candidate_score", "candidate_def", "search_method"]

    fh = open(args.out, "w", newline="", encoding="utf-8") if args.out != "-" else sys.stdout
    try:
        writer = csv.DictWriter(fh, fieldnames=out_fields, delimiter="\t",
                                extrasaction="ignore")
        writer.writeheader()

        for row in rows:
            code = (row.get(code_col) or "").strip()
            label = (row.get(label_col) or "").strip()
            verified = (row.get("ols_verified") or "").strip()
            notes = (row.get("notes") or "").strip()

            if not label:
                continue
            if args.skip_no_ols_needed and verified == "yes":
                continue
            if "no anchor-valid" in notes or "env_medium territory" in notes:
                print(f"  skip {code} {label!r} (no ELS expected)", file=sys.stderr)
                continue

            print(f"  searching: {code} {label!r}", file=sys.stderr)
            hits = search(label, n=args.top)
            time.sleep(RATE_DELAY)

            if not hits:
                writer.writerow({
                    "source_code": code, "source_label": label,
                    "candidate_curie": "", "candidate_label": "(no hits)",
                    "candidate_score": "", "candidate_def": "", "search_method": "none",
                })
                continue
            for hit in hits:
                writer.writerow({
                    "source_code": code,
                    "source_label": label,
                    "candidate_curie": hit["curie"],
                    "candidate_label": hit["label"],
                    "candidate_score": hit["score"] if hit["score"] is not None else "",
                    "candidate_def": hit["def"],
                    "search_method": hit["method"],
                })
    finally:
        if fh is not sys.stdout:
            fh.close()

    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
