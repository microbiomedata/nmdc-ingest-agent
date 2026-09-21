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
        --term-validation-report results/ncbi_<ACC>_nmdc_term_validation_report.json \
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


def summarize_term_validation(validation: dict) -> dict:
    """Condense a ``*_term_validation_report.json`` (see
    ``nmdc_ingest_agent.validators``) into what a curator needs: status, counts
    and the findings grouped by level (capped per level)."""
    status = validation.get("status") or "unknown"
    summary = validation.get("summary") or {}
    grouped: dict[str, list[str]] = {}
    for f in validation.get("findings") or []:
        grouped.setdefault(f.get("level", "other"), []).append(
            f"{f.get('biosample_id')} {f.get('slot')} {f.get('term_id')} — {f.get('message')}"
        )
    # Hard failures first, then the advisory levels.
    order = ["existence", "obsolete", "label", "anchor", "valueset", "other"]
    grouped = {k: grouped[k] for k in sorted(grouped, key=lambda k: order.index(k) if k in order else len(order))}
    return {
        "status": status,
        "reason": validation.get("reason"),
        "tool": (validation.get("tool") or {}).get("linkml_term_validator"),
        "ontology_versions": {k: v for k, v in ((validation.get("tool") or {}).get("ontology_versions") or {}).items() if v},
        "checked": summary.get("checked", 0),
        "terms": summary.get("terms", 0),
        "errors": summary.get("errors", 0),
        "warnings": summary.get("warnings", 0),
        "unchecked_prefixes": summary.get("unchecked_prefixes") or [],
        "skipped_sentinels": summary.get("skipped_sentinels", 0),
        "by_level": {k: v for k, v in (summary.get("by_level") or {}).items() if v},
        "findings": grouped,
    }


def _fmt_ids(ids: list) -> str:
    ids = [i for i in ids if i]
    if not ids:
        return ""
    shown = ", ".join(ids[:_MAX_LISTED])
    if len(ids) > _MAX_LISTED:
        shown += f", … (+{len(ids) - _MAX_LISTED} more)"
    return shown


def render_run_notes(meta: dict, counts: dict, slots: dict,
                     term_validation: Optional[dict] = None) -> str:
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
    L += ["## Validation", ""]
    if term_validation:
        L += _render_term_validation(term_validation)
    L += ["<!-- local linkml load result; runtime json:validate result; known failures -->", ""]
    L += ["## Decisions for next run", "",
          "Human steering lives in `DECISIONS.md` (free-form) and `overrides.tsv` "
          "(term overrides). This file is regenerated each run and does not read them back — "
          "the ingest skill's Step 0 reads `DECISIONS.md`.", ""]
    return "\n".join(L)


def _render_term_validation(tv: dict) -> list[str]:
    """Markdown lines for the ontology-term QC block of the Validation section."""
    L: list[str] = []
    tool = f" (linkml-term-validator {tv['tool']})" if tv.get("tool") else ""
    if tv.get("status") != "ok":
        L.append(f"- Ontology term QC{tool}: **{tv.get('status')}** — {tv.get('reason')}. "
                 f"{tv.get('terms', 0)} term(s) were not checked.")
        L.append("")
        return L
    line = (f"- Ontology term QC{tool}: {tv['checked']} term(s) checked, "
            f"**{tv['errors']} error(s)**, {tv['warnings']} warning(s)")
    extras = []
    if tv.get("ontology_versions"):
        extras.append("against " + ", ".join(f"{p} {v}" for p, v in tv["ontology_versions"].items()))
    if tv.get("unchecked_prefixes"):
        extras.append(f"{', '.join(tv['unchecked_prefixes'])} terms unchecked (adapter not configured)")
    if tv.get("skipped_sentinels"):
        extras.append(f"{tv['skipped_sentinels']} ENVO:00000000 sentinel(s) skipped")
    if extras:
        line += "; " + "; ".join(extras)
    L.append(line + ".")
    for level, items in (tv.get("findings") or {}).items():
        shown = items[:_MAX_LISTED]
        L.append(f"  - {level} ({len(items)}):")
        L += [f"    - {item}" for item in shown]
        if len(items) > _MAX_LISTED:
            L.append(f"    - … (+{len(items) - _MAX_LISTED} more in the term validation report)")
    L.append("")
    return L


def write_run_notes(out_dir: Path, meta: dict, counts: dict, slots: dict,
                    term_validation: Optional[dict] = None) -> Path:
    """Write RUN_NOTES.md (overwrite) and seed DECISIONS.md / overrides.tsv if absent."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    notes_path = out_dir / "RUN_NOTES.md"
    notes_path.write_text(render_run_notes(meta, counts, slots, term_validation))

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
    ap.add_argument("--term-validation-report",
                    help="term_validation_report.json written by nmdc-ingest-ncbi / "
                         "nmdc-ingest-validate-terms (ontology term QC block)")
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
    term_validation = (summarize_term_validation(_load(args.term_validation_report))
                       if args.term_validation_report else None)
    path = write_run_notes(Path(args.out_dir), meta, counts, slots, term_validation)
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
