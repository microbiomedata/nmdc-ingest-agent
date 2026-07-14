#!/usr/bin/env python3
"""Validate an SSSOM mapping set before its rows are committed.

The acceptance gate for `nmdc-ontology-mapping`. Three checks, any failure exits non-zero:

1. **Structural** — the file parses as SSSOM (`sssom.parsers.parse_sssom_table`).
2. **Term existence + not deprecated** — every ``object_id`` resolves to a real,
   non-obsolete class in its ontology (via oaklib), and its ``object_label`` matches
   the ontology's official label (the id+label dual-verification that makes a
   hallucinated term hard to slip through).
3. **Anchor class (optional)** — with ``--anchor CURIE`` (repeatable), every
   ``object_id`` must be a descendant of at least one anchor. This is how the env
   triad constrains a slot (e.g. ``--anchor ENVO:00000428`` for env_broad_scale).

Ontology is inferred from each object_id prefix (ENVO -> envo, NCBITaxon -> ncbitaxon);
override with ``--ontology``. Requires the ``ontology`` extra (oaklib + sssom).

Usage:
    uv run --extra ontology python .claude/skills/nmdc-ontology-mapping/scripts/validate_mapping_set.py \
        my_mappings.sssom.tsv --anchor ENVO:01000813 --anchor ENVO:01000408
"""
from __future__ import annotations

import argparse
import sys

IS_A = ["rdfs:subClassOf"]
_ONTOLOGY_BY_PREFIX = {"ENVO": "envo", "NCBITAXON": "ncbitaxon", "UBERON": "uberon", "PO": "po"}


def _ontology_for(curie: str, override: str | None) -> str:
    if override:
        return override
    prefix = curie.split(":", 1)[0].upper()
    return _ONTOLOGY_BY_PREFIX.get(prefix, prefix.lower())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mapping_set", help="path to an .sssom.tsv file")
    ap.add_argument("--anchor", action="append", default=[], metavar="CURIE",
                    help="require every object_id to be under this class (repeatable)")
    ap.add_argument("--ontology", default=None,
                    help="oaklib ontology selector (default: inferred per object_id prefix)")
    args = ap.parse_args()

    # 1. Structural SSSOM validity.
    from sssom.parsers import parse_sssom_table

    try:
        msdf = parse_sssom_table(args.mapping_set)
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"STRUCTURAL: not a valid SSSOM table: {exc}")
    df = msdf.df
    if df is None or not len(df):
        sys.exit("STRUCTURAL: no mappings found")

    from oaklib import get_adapter

    adapters: dict[str, object] = {}

    def adapter_for(curie: str):
        onto = _ontology_for(curie, args.ontology)
        if onto not in adapters:
            adapters[onto] = get_adapter(f"sqlite:obo:{onto}")
        return adapters[onto]

    failures: list[str] = []
    for _, row in df.iterrows():
        obj = str(row["object_id"]).strip()
        stated = str(row.get("object_label") or "").strip()
        if not obj:
            failures.append("row with empty object_id")
            continue
        adapter = adapter_for(obj)

        # 2. Existence + not deprecated + label concordance.
        label = adapter.label(obj)
        if label is None:
            failures.append(f"{obj}: no such term in ontology")
            continue
        meta = dict(adapter.entity_metadata_map(obj) or {})
        if meta.get("owl:deprecated") in (True, "true", "True"):
            failures.append(f"{obj}: deprecated/obsolete term")
        if stated and label and stated.strip().lower() != label.strip().lower():
            failures.append(f"{obj}: object_label {stated!r} != official {label!r}")

        # 3. Optional anchor-class membership.
        if args.anchor:
            ancestors = set(adapter.ancestors(obj, predicates=IS_A))
            if not (set(args.anchor) & ancestors):
                failures.append(f"{obj}: not under any anchor {args.anchor}")

    if failures:
        print(f"Mapping set FAILED validation ({len(failures)} issue(s)):", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        sys.exit(1)
    print(f"Mapping set OK: {len(df)} mappings, all object terms verified"
          + (f" under {args.anchor}" if args.anchor else ""))


if __name__ == "__main__":
    main()
