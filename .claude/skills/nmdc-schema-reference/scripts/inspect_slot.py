#!/usr/bin/env python3
"""Introspect an NMDC LinkML slot (or class) against the *installed* nmdc-schema.

Authoritative for the version actually installed — prefer this over the published
docs when they disagree.

Usage:
    uv run python .claude/skills/nmdc-schema-reference/scripts/inspect_slot.py depth Biosample
    uv run python .claude/skills/nmdc-schema-reference/scripts/inspect_slot.py --class QuantityValue

Prints the induced slot definition (range, required, pattern, multivalued, ...) for a
slot in a class, or the slots of a class when given --class.
"""
from __future__ import annotations

import argparse
import pathlib

import nmdc_schema
from linkml_runtime.utils.schemaview import SchemaView


def _schema_view() -> SchemaView:
    """SchemaView over the installed nmdc-schema materialized definition."""
    path = pathlib.Path(nmdc_schema.__file__).parent / "nmdc_materialized_patterns.yaml"
    if not path.exists():
        raise SystemExit(f"nmdc-schema definition not found at {path}")
    return SchemaView(str(path))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("slot", nargs="?", help="slot name, e.g. depth")
    ap.add_argument("cls", nargs="?", help="class the slot belongs to, e.g. Biosample")
    ap.add_argument("--class", dest="only_class", metavar="CLASS",
                    help="instead of a slot, dump the slots of this class")
    args = ap.parse_args()

    sv = _schema_view()

    if args.only_class:
        cls = sv.get_class(args.only_class)
        if cls is None:
            raise SystemExit(f"No such class: {args.only_class}")
        print(f"class {cls.name}: {cls.description or ''}")
        for slot in sv.class_induced_slots(cls.name):
            print(f"  {slot.name}: range={slot.range} required={slot.required} "
                  f"multivalued={slot.multivalued}")
        return

    if not (args.slot and args.cls):
        raise SystemExit("usage: inspect_slot.py <slot> <class>   |   inspect_slot.py --class <Class>")

    print(sv.induced_slot(args.slot, args.cls))


if __name__ == "__main__":
    main()
