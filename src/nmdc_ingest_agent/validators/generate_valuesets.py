"""Regenerate ``env_triad_valuesets.tsv`` from ``nmdc-submission-schema``.

Run in a throwaway overlay so the schema package's ``rdflib<7`` pin never
touches the project environment::

    uv run --with "nmdc-submission-schema>=11.24" \\
        python -m nmdc_ingest_agent.validators.generate_valuesets

or point it at a checkout::

    uv run python -m nmdc_ingest_agent.validators.generate_valuesets \\
        --schema ../submission-schema/src/nmdc_submission_schema/schema/nmdc_submission_schema.yaml \\
        --version 11.24.0

Output is sorted and deterministic so a regeneration diff shows only real
value-set changes. Every permissible value must parse as ``label [CURIE]``;
anything else aborts loudly rather than being silently dropped.
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

import yaml

from nmdc_ingest_agent.validators.valuesets import (
    DEFAULT_VALUESETS_PATH,
    ENV_TRIAD_SLOTS,
    parse_permissible_value,
)

_ENUM_RE = re.compile(r"^Env(BroadScale|LocalScale|Medium)\w+Enum$")


def _installed_schema() -> tuple[Path, str]:
    import importlib.metadata as md

    import nmdc_submission_schema  # type: ignore[import-not-found]

    path = Path(nmdc_submission_schema.__file__).parent / "schema" / "nmdc_submission_schema.yaml"
    return path, md.version("nmdc-submission-schema")


def build_rows(schema: dict) -> list[dict]:
    """Rows of (interface, slot, enum, curie, label, text) for every interface
    whose env-triad slot_usage ranges over an Env*Enum."""
    rows: list[dict] = []
    classes = schema.get("classes") or {}
    enums = schema.get("enums") or {}
    for cname in sorted(classes):
        if not cname.endswith("Interface"):
            continue
        slot_usage = classes[cname].get("slot_usage") or {}
        for slot in ENV_TRIAD_SLOTS:
            usage = slot_usage.get(slot) or {}
            ranges = [a.get("range") for a in (usage.get("any_of") or [])]
            if usage.get("range"):
                ranges.append(usage["range"])
            enum_names = [r for r in ranges if r and _ENUM_RE.match(r)]
            if not enum_names:
                continue
            if len(enum_names) > 1:
                raise SystemExit(f"{cname}.{slot}: more than one Env*Enum range: {enum_names}")
            enum = enum_names[0]
            pvs = (enums.get(enum) or {}).get("permissible_values") or {}
            for text in sorted(pvs):
                parsed = parse_permissible_value(text)
                if parsed is None:
                    raise SystemExit(f"{enum}: permissible value not of the form 'label [CURIE]': {text!r}")
                label, curie = parsed
                rows.append({
                    "interface": cname, "slot": slot, "enum": enum,
                    "curie": curie, "label": label, "text": text,
                })
    return rows


def write_tsv(rows: list[dict], out: Path, version: str, generated: str) -> None:
    lines = [
        "# NMDC submission-schema env-triad value sets, vendored for the term validator",
        "# (nmdc_ingest_agent.validators.valuesets). Do not hand-edit: regenerate with",
        "#   uv run --with nmdc-submission-schema python -m nmdc_ingest_agent.validators.generate_valuesets",
        f"# nmdc_submission_schema_version: {version}",
        f"# generated: {generated}",
        "interface\tslot\tenum\tcurie\tlabel\ttext",
    ]
    for r in rows:
        for k in ("interface", "slot", "enum", "curie", "label", "text"):
            if "\t" in r[k] or "\n" in r[k]:
                raise SystemExit(f"tab/newline in value: {r}")
        lines.append("\t".join(r[k] for k in ("interface", "slot", "enum", "curie", "label", "text")))
    out.write_text("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--schema", help="nmdc_submission_schema.yaml (default: the installed package's copy)")
    ap.add_argument("--version", help="schema version to stamp (required with --schema)")
    ap.add_argument("--out", default=str(DEFAULT_VALUESETS_PATH))
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    args = ap.parse_args(argv)

    if args.schema:
        if not args.version:
            ap.error("--version is required with --schema")
        schema_path, version = Path(args.schema), args.version
    else:
        try:
            schema_path, version = _installed_schema()
        except ImportError:
            sys.exit(
                "nmdc-submission-schema is not installed; run with\n"
                "  uv run --with 'nmdc-submission-schema>=11.24' python -m "
                "nmdc_ingest_agent.validators.generate_valuesets"
            )

    try:
        loader = yaml.CSafeLoader
    except AttributeError:  # pragma: no cover - no libyaml
        loader = yaml.SafeLoader
    schema = yaml.load(schema_path.read_text(), Loader=loader)
    rows = build_rows(schema)
    write_tsv(rows, Path(args.out), version, args.date)
    by_enum: dict[str, int] = {}
    for r in rows:
        by_enum[r["enum"]] = by_enum.get(r["enum"], 0) + 1
    print(f"Wrote {len(rows)} rows across {len(by_enum)} enums (schema {version}) to {args.out}")
    for enum, n in sorted(by_enum.items()):
        print(f"  {enum}: {n}")


if __name__ == "__main__":
    main()
