"""``nmdc-ingest-validate-terms``: ontology-term QC for an existing NMDC JSON.

Re-runs the same extract -> validate pipeline ``nmdc-ingest-ncbi`` runs
automatically, so it can be pointed at a deliverable *after* the curation
skills have committed terms (the machine version of the env-triad skill's
"validate every committed CURIE" step), and optionally folds the per-row
flags into the curation report.

Exit codes: 0 clean (or only warnings, unless ``--fail-on warning``), 1 findings
at or above ``--fail-on``, 2 validation could not run (extra not installed,
ontology service unreachable, or an unexpected error — never a data problem).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from nmdc_ingest_agent.validators.extract import extract_observed_terms
from nmdc_ingest_agent.validators.valuesets import DEFAULT_VALUESETS_PATH
from nmdc_ingest_agent.validators.run import (
    ADAPTERS_ENV_VAR,
    STATUS_OK,
    default_cache_dir,
    format_summary,
    merge_into_curation_report,
    parse_adapter_spec,
    run_term_validation,
)

EXIT_CLEAN = 0
EXIT_FINDINGS = 1
EXIT_NOT_RUN = 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nmdc-ingest-validate-terms",
        description="Validate ontology terms (existence, label, anchor class, NMDC value set) "
        "in an NMDC Database JSON via linkml-term-validator.",
        epilog=(
            "Examples:\n"
            "  nmdc-ingest-validate-terms results/ncbi_PRJNA1452545_nmdc.json\n"
            "  nmdc-ingest-validate-terms results/ncbi_X_nmdc.json "
            "--curation-report results/ncbi_X_nmdc_curation_report.json\n"
            "  nmdc-ingest-validate-terms results/ncbi_X_nmdc.json --adapter NCBITaxon=sqlite:obo:ncbitaxon\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("nmdc_json", help="An NMDC Database JSON (e.g. results/ncbi_<ACC>_nmdc.json).")
    p.add_argument("--out", help="Report path (default: <input stem>_term_validation_report.json).")
    p.add_argument(
        "--curation-report",
        help="Curation report to update in place: per-row validator.{info_ok,label_ok,anchor_ok,valueset_ok}.",
    )
    p.add_argument(
        "--adapter",
        action="append",
        default=[],
        metavar="PREFIX=ADAPTER",
        help="Add/override an OAK adapter, e.g. NCBITaxon=sqlite:obo:ncbitaxon or PO=sqlite:obo:po. "
        "Repeatable; also read from $NMDC_TERM_VALIDATION_ADAPTERS.",
    )
    p.add_argument("--cache-dir", help="Label/enum cache directory (default: $NMDC_TERM_VALIDATION_CACHE_DIR or ~/.cache/nmdc-ingest-agent/term-validator).")
    p.add_argument("--lenient", action="store_true", help="Do not report unresolvable CURIEs as errors.")
    p.add_argument("--offline", action="store_true", help="Never build OAK adapters; resolve only from the cache.")
    p.add_argument("--no-valuesets", action="store_true", help="Skip the NMDC submission-schema value-set check.")
    p.add_argument(
        "--fail-on",
        choices=("error", "warning", "never"),
        default="error",
        help="Lowest severity that makes the exit code 1 (default: error).",
    )
    p.add_argument("--max-findings", type=int, default=20, help="Findings to print (all are in the report file).")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    in_path = Path(args.nmdc_json)
    if not in_path.exists():
        print(f"ERROR: input file not found: {in_path}", file=sys.stderr)
        return EXIT_NOT_RUN
    out_path = Path(args.out) if args.out else in_path.with_name(in_path.stem + "_term_validation_report.json")

    try:
        adapters = parse_adapter_spec(args.adapter)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_NOT_RUN
    # CLI --adapter adds to (and wins over) the environment variable.
    try:
        env_adapters = parse_adapter_spec(os.environ.get(ADAPTERS_ENV_VAR))
    except ValueError as exc:
        print(f"WARNING: ignoring malformed ${ADAPTERS_ENV_VAR}: {exc}", file=sys.stderr)
        env_adapters = {}
    adapters = {**env_adapters, **adapters}

    try:
        database = json.loads(in_path.read_text())
        instance = extract_observed_terms(database)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        print(f"ERROR: could not read an NMDC Database from {in_path}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_NOT_RUN

    validation = run_term_validation(
        instance,
        cache_dir=Path(args.cache_dir) if args.cache_dir else default_cache_dir(),
        adapters=adapters,
        lenient=args.lenient,
        offline=args.offline,
        valuesets_path=None if args.no_valuesets else DEFAULT_VALUESETS_PATH,
    )
    validation["input"] = str(in_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(validation, indent=2, default=str) + "\n")

    print(format_summary(validation, max_findings=args.max_findings))
    print(f"Term validation report written to {out_path}")

    if args.curation_report:
        report_path = Path(args.curation_report)
        if not report_path.exists():
            print(f"WARNING: curation report not found, nothing merged: {report_path}", file=sys.stderr)
        else:
            report = json.loads(report_path.read_text())
            updated = merge_into_curation_report(report, validation)
            report_path.write_text(json.dumps(report, indent=2, default=str) + "\n")
            print(f"Curation report updated: {updated} row(s) received validator flags ({report_path})")

    if validation.get("status") != STATUS_OK:
        return EXIT_NOT_RUN
    summary = validation["summary"]
    if args.fail_on == "error" and summary["errors"]:
        return EXIT_FINDINGS
    if args.fail_on == "warning" and (summary["errors"] or summary["warnings"]):
        return EXIT_FINDINGS
    return EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
