"""Search OLS4 for ENVO candidates for each row in a land-cover mapping TSV.

Tries the OLS4 LLM embeddings endpoint first; falls back to lexical search
if embeddings are unavailable (e.g. pgvector outage).

Input TSV must have columns ending in _code and _label
(e.g. corine_envo_map.tsv, worldcover_envo_map.tsv).

Output TSV columns: source_code, source_label, candidate_curie,
candidate_label, candidate_score, candidate_def, search_method

OLS4 endpoints:
  Embeddings: GET https://www.ebi.ac.uk/ols4/api/v2/classes/llm_search
              ?q=<label>&model=llama-embed-nemotron-8b_pca512&size=20
  Lexical:    GET https://www.ebi.ac.uk/ols4/api/v2/entities
              ?search=<label>&size=10&ontologyId=envo

Post-filter: only ENVO hits kept. Embeddings hits below 0.78 omitted.

Important: candidates are suggestions only. Every CURIE must be verified
with runoak ancestors before being written to a mapping file. Never copy
a CURIE from this output without checking it against the ELS allow-list.
"""

import csv
import sys
import time
import urllib.parse
import urllib.request
import json
from pathlib import Path

import click

OLS4_BASE = "https://www.ebi.ac.uk/ols4/api/v2"
EMBED_MODEL = "llama-embed-nemotron-8b_pca512"
EMBED_SCORE_FLOOR = 0.78
RATE_DELAY = 0.5


def _get(url: str, timeout: int = 20) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def search_embeddings(label: str, n: int = 20) -> list[dict]:
    q = urllib.parse.quote(label)
    url = f"{OLS4_BASE}/classes/llm_search?q={q}&model={EMBED_MODEL}&size={n}"
    d = _get(url)
    if d.get("status") and str(d["status"]).startswith("5"):
        raise RuntimeError(d.get("message", "OLS4 embeddings error"))
    return [
        {"curie": e.get("curie", ""), "label": e.get("label", ""),
         "score": round(float(e.get("score", 0)), 4),
         "def": (e.get("description") or [""])[0][:120], "method": "embeddings"}
        for e in d.get("elements", [])
        if e.get("ontologyId") == "envo" and float(e.get("score", 0)) >= EMBED_SCORE_FLOOR
    ]


def search_lexical(label: str, n: int = 10) -> list[dict]:
    q = urllib.parse.quote(label)
    url = f"{OLS4_BASE}/entities?search={q}&size={n}&ontologyId=envo&exactMatch=false"
    d = _get(url)
    elements = d.get("elements") or d.get("_embedded", {}).get("terms", [])
    return [
        {"curie": e.get("curie", e.get("short_form", "")), "label": e.get("label", ""),
         "score": None, "def": (e.get("description") or [""])[0][:120], "method": "lexical"}
        for e in elements
        if e.get("ontologyId", e.get("ontology_name", "")) == "envo"
    ]


def search(label: str, n: int = 5) -> list[dict]:
    try:
        hits = search_embeddings(label, n=max(n * 4, 20))
        if not hits:
            raise RuntimeError("empty result")
        return hits[:n]
    except Exception as e:
        click.echo(f"  [embeddings unavailable: {e}; using lexical]", err=True)
    return search_lexical(label, n=n)[:n]


def _detect_col(cols: list[str], suffix: str) -> str | None:
    for c in cols:
        if c.endswith(suffix):
            return c
    return None


@click.command()
@click.argument("input_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--out", default="-", help="Output TSV path (default: stdout)")
@click.option("--top", default=3, show_default=True,
              help="Max candidates per row")
@click.option("--code-col", default=None,
              help="Column name for source code (auto-detected if omitted)")
@click.option("--label-col", default=None,
              help="Column name for source label (auto-detected if omitted)")
@click.option("--skip-verified", is_flag=True,
              help="Skip rows already marked ols_verified=yes")
def main(input_file, out, top, code_col, label_col, skip_verified):
    """Search OLS4 for ENVO ELS candidates for each row in a land-cover mapping TSV.

    INPUT_FILE: TSV with *_code and *_label columns (e.g. corine_envo_map.tsv).

    Candidates are suggestions only -- verify every CURIE with runoak ancestors
    before writing to a mapping file.
    """
    with open(input_file, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    if not rows:
        click.echo("No rows in input", err=True)
        sys.exit(1)

    cols = list(rows[0].keys())
    code_col = code_col or _detect_col(cols, "_code")
    label_col = label_col or _detect_col(cols, "_label")
    if not code_col or not label_col:
        click.echo(f"Cannot detect code/label columns in {cols}; use --code-col / --label-col",
                   err=True)
        sys.exit(1)
    click.echo(f"code={code_col!r}  label={label_col!r}", err=True)

    out_fields = ["source_code", "source_label", "candidate_curie", "candidate_label",
                  "candidate_score", "candidate_def", "search_method"]

    fh = open(out, "w", newline="", encoding="utf-8") if out != "-" else sys.stdout
    try:
        writer = csv.DictWriter(fh, fieldnames=out_fields, delimiter="\t",
                                extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            code = (row.get(code_col) or "").strip()
            label = (row.get(label_col) or "").strip()
            notes = (row.get("notes") or "").strip()
            verified = (row.get("ols_verified") or "").strip()

            if not label:
                continue
            if skip_verified and verified == "yes":
                continue
            if "no anchor-valid" in notes or "env_medium territory" in notes:
                click.echo(f"  skip {code} {label!r}", err=True)
                continue

            click.echo(f"  searching: {code} {label!r}", err=True)
            hits = search(label, n=top)
            time.sleep(RATE_DELAY)

            if not hits:
                writer.writerow({"source_code": code, "source_label": label,
                                 "candidate_curie": "", "candidate_label": "(no hits)",
                                 "candidate_score": "", "candidate_def": "",
                                 "search_method": "none"})
                continue
            for hit in hits:
                writer.writerow({"source_code": code, "source_label": label,
                                 "candidate_curie": hit["curie"],
                                 "candidate_label": hit["label"],
                                 "candidate_score": hit["score"] if hit["score"] is not None else "",
                                 "candidate_def": hit["def"],
                                 "search_method": hit["method"]})
    finally:
        if fh is not sys.stdout:
            fh.close()
    click.echo("Done.", err=True)


if __name__ == "__main__":
    main()
