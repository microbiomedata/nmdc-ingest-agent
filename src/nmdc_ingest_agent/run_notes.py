"""Render a human-readable RUN_NOTES.md from an ingest run's artifacts.

Source-agnostic: it consumes the generic curation-report shape (``{"rows": [{slot,
outcome, biosample_id, ...}]}``) and an NMDC ``Database`` JSON deliverable (for record
counts), and writes a small, PR-reviewable notes file a curator can act on — replacing
the multi-MB machine ``curation_report.json`` that no human reads.

The generated ``RUN_NOTES.md`` is overwritten every run. The human's steering input lives
in sibling files this module **creates-if-absent but never overwrites**:

- ``DECISIONS.md``  — free-form directives the next run reads (Step 0 of the ingest skill).
- ``overrides.tsv`` — machine-readable term overrides (an SSSOM mapping set; see the
  ``nmdc-ontology-mapping`` skill).

CLI:
    uv run python -m nmdc_ingest_agent.run_notes \
        --deliverable results/ncbi_<ACC>_nmdc.json \
        --curation-report results/ncbi_<ACC>_nmdc_curation_report.json \
        --source ncbi --accession <ACC> --env dev \
        --command "uv run nmdc-ingest-ncbi <ACC>" --mint-mode placeholder \
        --out-dir runs/ncbi_<ACC>
"""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
from typing import Optional

# Curation-report outcome buckets (the contract shared with the curation skills).
_RESOLVED = {"resolved_at_pipeline", "resolved_from_raw", "predicted"}
_DEFERRED = {"left_sentinel"}
_FLAGGED = {"validator_rejected"}

_COLLECTIONS = [
    "study_set", "biosample_set", "material_processing_set", "processed_sample_set",
    "data_generation_set", "data_object_set", "manifest_set",
]
_MAX_LISTED = 15  # cap per-slot id lists so notes stay readable


def summarize_report(report: dict) -> dict:
    """Per-slot outcome counts and the deferred/flagged biosample ids.

    Works on any ``{"rows": [{"slot", "outcome", "biosample_id"}]}`` report.
    """
    slots: dict[str, dict] = {}
    for row in report.get("rows", []):
        slot = row.get("slot")
        outcome = row.get("outcome")
        s = slots.setdefault(slot, {"counts": {}, "deferred": [], "flagged": []})
        s["counts"][outcome] = s["counts"].get(outcome, 0) + 1
        if outcome in _DEFERRED:
            s["deferred"].append(row.get("biosample_id"))
        elif outcome in _FLAGGED:
            s["flagged"].append(row.get("biosample_id"))
    return slots


def count_records(deliverable: dict) -> dict:
    """Record count per NMDC collection present in the deliverable."""
    return {c: len(deliverable.get(c, []) or []) for c in _COLLECTIONS
            if deliverable.get(c)}


def _fmt_ids(ids: list) -> str:
    ids = [i for i in ids if i]
    if not ids:
        return ""
    shown = ", ".join(ids[:_MAX_LISTED])
    if len(ids) > _MAX_LISTED:
        shown += f", … (+{len(ids) - _MAX_LISTED} more)"
    return shown


def render_run_notes(meta: dict, counts: dict, slots: dict) -> str:
    """Render the RUN_NOTES.md markdown from computed data."""
    L: list[str] = []
    title = f"{meta.get('source', 'ingest')} {meta.get('accession', '')}".strip()
    L += [f"# Run notes — {title}", ""]

    L += ["## Run metadata", ""]
    for label, key in [("Source", "source"), ("Accession", "accession"),
                       ("Run date", "date"), ("Env", "env"),
                       ("Mint mode", "mint_mode"), ("Command", "command")]:
        if meta.get(key):
            L.append(f"- **{label}:** {meta[key]}")
    L.append("")

    L += ["## Record counts", ""]
    if counts:
        for c, n in counts.items():
            L.append(f"- {c}: {n}")
    else:
        L.append("- (no deliverable provided)")
    L.append("")

    # Split slot outcomes into resolved vs needs-attention.
    L += ["## Resolution summary", ""]
    if slots:
        L.append("| slot | resolved | deferred | flagged |")
        L.append("|---|---|---|---|")
        for slot, s in slots.items():
            resolved = sum(v for k, v in s["counts"].items() if k in _RESOLVED)
            deferred = sum(v for k, v in s["counts"].items() if k in _DEFERRED)
            flagged = sum(v for k, v in s["counts"].items() if k in _FLAGGED)
            L.append(f"| {slot} | {resolved} | {deferred} | {flagged} |")
    else:
        L.append("- (no curation report provided)")
    L.append("")

    # Deferred backlog + flagged — the curator's to-do list.
    deferred_any = any(s["deferred"] for s in slots.values())
    flagged_any = any(s["flagged"] for s in slots.values())
    L += ["## Deferred — needs a human decision", ""]
    if deferred_any:
        for slot, s in slots.items():
            if s["deferred"]:
                L.append(f"- **{slot}** ({len(s['deferred'])}): {_fmt_ids(s['deferred'])}")
    else:
        L.append("- none")
    L.append("")
    if flagged_any:
        L += ["## Flagged — validator rejected", ""]
        for slot, s in slots.items():
            if s["flagged"]:
                L.append(f"- **{slot}** ({len(s['flagged'])}): {_fmt_ids(s['flagged'])}")
        L.append("")

    # Sections the agent annotates from run context (not derivable from artifacts).
    L += ["## Exclusions", "",
          "<!-- what was dropped and why (e.g. MAG-only biosamples with no SRA run) -->", ""]
    L += ["## Validation", "",
          "<!-- local linkml load result; runtime json:validate result; known failures -->", ""]
    L += ["## Decisions for next run", "",
          "Human steering lives in `DECISIONS.md` (free-form) and `overrides.tsv` "
          "(term overrides). This file is regenerated each run and does not read them back — "
          "the ingest skill's Step 0 reads `DECISIONS.md`.", ""]
    return "\n".join(L)


def write_run_notes(out_dir: Path, meta: dict, counts: dict, slots: dict) -> Path:
    """Write RUN_NOTES.md (overwrite) and seed DECISIONS.md / overrides.tsv if absent."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    notes_path = out_dir / "RUN_NOTES.md"
    notes_path.write_text(render_run_notes(meta, counts, slots))

    decisions = out_dir / "DECISIONS.md"
    if not decisions.exists():  # never clobber human-authored steering
        decisions.write_text(
            "# Decisions for next run\n\n"
            "Human-authored. The ingest skill reads this at Step 0; the agent never "
            "overwrites it.\n\n"
            "- (add directives here, e.g. \"exclude project P17\", "
            "\"commit env_medium ENVO:00001998 for soil-package samples\")\n"
        )
    overrides = out_dir / "overrides.tsv"
    if not overrides.exists():
        overrides.write_text(
            "# Term overrides as an SSSOM mapping set (see the nmdc-ontology-mapping skill).\n"
            "# curie_map:\n"
            "#   ENVO: http://purl.obolibrary.org/obo/ENVO_\n"
            "#   skos: http://www.w3.org/2004/02/skos/core#\n"
            "#   semapv: https://w3id.org/semapv/vocab/\n"
            "# mapping_set_id: https://w3id.org/nmdc/overrides/PLACEHOLDER\n"
            "# license: https://creativecommons.org/publicdomain/zero/1.0/\n"
            "subject_id\tsubject_label\tpredicate_id\tobject_id\tobject_label\t"
            "mapping_justification\n"
        )
    return notes_path


def _load(path: Optional[str]) -> dict:
    return json.loads(Path(path).read_text()) if path else {}


def main() -> None:
    ap = argparse.ArgumentParser(description="Write a human-readable RUN_NOTES.md.")
    ap.add_argument("--deliverable", help="NMDC Database JSON (for record counts)")
    ap.add_argument("--curation-report", help="curation_report.json")
    ap.add_argument("--out-dir", required=True, help="runs/<source>_<accession>/")
    ap.add_argument("--source", default="ingest")
    ap.add_argument("--accession", default="")
    ap.add_argument("--env", default="")
    ap.add_argument("--command", default="")
    ap.add_argument("--mint-mode", default="")
    ap.add_argument("--date", default=None, help="override run date (default: today)")
    args = ap.parse_args()

    meta = {
        "source": args.source, "accession": args.accession, "env": args.env,
        "command": args.command, "mint_mode": args.mint_mode,
        "date": args.date or datetime.date.today().isoformat(),
    }
    counts = count_records(_load(args.deliverable)) if args.deliverable else {}
    slots = summarize_report(_load(args.curation_report)) if args.curation_report else {}
    path = write_run_notes(Path(args.out_dir), meta, counts, slots)
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
