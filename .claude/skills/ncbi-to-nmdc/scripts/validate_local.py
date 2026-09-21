#!/usr/bin/env python3
"""Offline validation of an NMDC Database JSON (Step 7a, fast first pass).

Runs the LinkML validation framework (``linkml.validator.validate_file``, the same
engine as the ``linkml validate`` CLL) against the installed nmdc-schema, no network.
This is stricter than a plain ``json_loader.load``: it enforces jsonschema
``pattern`` / range / enum constraints on slot values (e.g. a malformed
``insdc_bioproject_identifiers`` CURIE), which the load-based check silently passes.
It is the local first pass before the authoritative runtime ``/metadata/json:validate``
(Step 7b, ``nmdc_ingest_agent.validation.validate_runtime``).

Usage:
    uv run python .claude/skills/ncbi-to-nmdc/scripts/validate_local.py results/ncbi_<ACC>_nmdc.json

Exits non-zero on any validation ERROR so it can gate a workflow.
"""
from __future__ import annotations

import json
import pathlib
import sys

import nmdc_schema
from linkml.validator import validate_file

_COLLECTIONS = (
    "study_set", "biosample_set", "material_processing_set", "processed_sample_set",
    "data_generation_set", "data_object_set", "manifest_set",
)


def _schema_path() -> str:
    """Path to the installed nmdc-schema materialized definition."""
    path = pathlib.Path(nmdc_schema.__file__).parent / "nmdc_materialized_patterns.yaml"
    if not path.exists():
        raise SystemExit(f"nmdc-schema definition not found at {path}")
    return str(path)


def validate_local(path: str) -> int:
    """Validate the deliverable; return the number of ERROR-severity results."""
    # Record-count summary (cheap; helps the human read the run at a glance).
    data = json.loads(pathlib.Path(path).read_text())
    counts = ", ".join(f"{len(data.get(c) or [])} {c}" for c in _COLLECTIONS if data.get(c))
    print(f"Loaded: {counts}")

    report = validate_file(path, _schema_path(), "Database")
    errors = [r for r in report.results if str(r.severity).endswith("ERROR")]
    warnings = [r for r in report.results if r not in errors]

    for r in warnings[:50]:
        print(f"[WARN] {r.message}")
    for r in errors[:200]:
        print(f"[ERROR] {r.message}")

    if errors:
        print(f"Validation FAILED: {len(errors)} error(s)"
              + (f", {len(warnings)} warning(s)" if warnings else ""))
    else:
        print("Validation passed!" + (f" ({len(warnings)} warning(s))" if warnings else ""))
    return len(errors)


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    if len(sys.argv) != 2:
        sys.exit("usage: validate_local.py <nmdc_database.json>")
    try:
        n_errors = validate_local(sys.argv[1])
    except Exception as exc:  # noqa: BLE001 — surface the linkml error clearly and fail
        sys.exit(f"Local validation FAILED to run: {exc}")
    sys.exit(1 if n_errors else 0)
