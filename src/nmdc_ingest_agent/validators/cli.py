"""Standalone CLI for term validation.

Reads an NMDC JSON file produced by `nmdc-ingest-ncbi`, rebuilds the
nmdc.Database, runs the same extract → validate pipeline that translate.main
invokes, and writes `<basename>_term_validation_report.json` next to the input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from linkml_runtime.loaders import json_loader
from nmdc_schema import nmdc

from nmdc_ingest_agent.validators.extract import extract_observed_terms
from nmdc_ingest_agent.validators.run import run_term_validation


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate ontology terms in an NMDC JSON file produced by nmdc-ingest-ncbi.",
    )
    parser.add_argument(
        "nmdc_json",
        help="Path to an *_nmdc.json file (output of nmdc-ingest-ncbi).",
    )
    parser.add_argument(
        "--out",
        help="Path for the validation report (default: <input>_term_validation_report.json).",
    )
    parser.add_argument(
        "--lenient",
        action="store_true",
        help="Do not report missing terms as errors (label checks still run).",
    )
    args = parser.parse_args()

    in_path = Path(args.nmdc_json)
    if not in_path.exists():
        sys.exit(f"ERROR: input file not found: {in_path}")

    out_path = Path(args.out) if args.out else in_path.with_name(
        in_path.stem + "_term_validation_report.json"
    )

    database = json_loader.load(str(in_path), target_class=nmdc.Database)
    observed = extract_observed_terms(database)

    result = run_term_validation(
        observed,
        work_dir=out_path.parent,
        lenient=args.lenient,
    )

    payload = {
        "input": str(in_path),
        "observed_terms": observed["observed_terms"],
        **result,
    }
    with open(out_path, "w") as fh:
        json.dump(payload, fh, indent=2, default=str)

    if result.get("skipped"):
        print(f"Term validation skipped: {result['reason']}", file=sys.stderr)
    else:
        summary = result["summary"]
        print(
            f"Term validation: {summary['errors']} errors, {summary['warnings']} warnings "
            f"({summary['checked']} terms checked)",
            file=sys.stderr,
        )
    print(f"Report written to {out_path}")


if __name__ == "__main__":
    main()
