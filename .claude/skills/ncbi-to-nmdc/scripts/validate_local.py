#!/usr/bin/env python3
"""Offline schema validation of an NMDC Database JSON (Step 7a, fast first pass).

Loads the file with the linkml runtime against ``nmdc.Database`` — schema-only, no
network. Catches structural and enum problems before the authoritative runtime
``/metadata/json:validate`` pass (Step 7b, ``nmdc_ingest_agent.validation.validate_runtime``).

Usage:
    uv run python .claude/skills/ncbi-to-nmdc/scripts/validate_local.py results/ncbi_<ACC>_nmdc.json

Exits non-zero on failure so it can gate a workflow.
"""
from __future__ import annotations

import sys

from linkml_runtime.loaders import json_loader
from nmdc_schema import nmdc


def validate_local(path: str) -> None:
    db = json_loader.load(path, target_class=nmdc.Database)
    print(
        f"Loaded: {len(db.study_set)} studies, {len(db.biosample_set)} biosamples, "
        f"{len(db.material_processing_set)} material processings, "
        f"{len(db.processed_sample_set)} processed samples, "
        f"{len(db.data_generation_set)} data generations"
    )
    print("Validation passed!")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    if len(sys.argv) != 2:
        sys.exit("usage: validate_local.py <nmdc_database.json>")
    try:
        validate_local(sys.argv[1])
    except Exception as exc:  # noqa: BLE001 — surface the linkml error clearly and fail
        sys.exit(f"Local schema validation FAILED: {exc}")
