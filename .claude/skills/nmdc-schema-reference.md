---
name: nmdc-schema-reference
description: Look up NMDC LinkML slot ranges, value-type wrappers (QuantityValue, ControlledIdentifiedTermValue, etc.), and enums via SchemaView before shaping any non-trivial slot value.
---

# NMDC LinkML schema reference

Use this skill when shaping a slot value whose range is not a plain string — nested value-type wrappers, enums with strict allowed values, slots with min/max/range semantics. Curation skills (`nmdc-env-triad`, `nmdc-taxon-resolution`) point here for the canonical value-shape rules; source skills point here from their validate step.

## Common traps

- `QuantityValue` uses `has_numeric_value` for scalars but `has_minimum_numeric_value` / `has_maximum_numeric_value` for range strings like `"0.2 - 0.3 m"`. Never put a range into `has_numeric_value`.
- `ControlledIdentifiedTermValue` wraps an `OntologyClass` with `id` (the CURIE) and `name` (the official ontology label). If you only have free text and no resolvable CURIE, use `ControlledTermValue` with `has_raw_value` instead.
- Slot names use snake_case and often have strict enum value ranges (e.g. `study_category`, `analyte_category`, `data_category`, `data_object_type`). Pulling an enum value from memory is a common source of validation failures — check the schema.

## How to check the schema

Two ways, in order of preference:

1. **Local package (authoritative for the installed version)** — `nmdc-schema` is a project dependency, so the Python classes are importable and introspectable via `linkml_runtime`:

   ```python
   from nmdc_schema import nmdc
   from linkml_runtime.utils.schemaview import SchemaView
   import nmdc_schema

   # Inspect a slot's range, required flag, pattern, etc.
   sv = SchemaView(nmdc_schema.get_nmdc_schema_definition())
   print(sv.induced_slot("depth", "Biosample"))

   # Or just look at a class's expected shape
   help(nmdc.QuantityValue)
   ```

2. **Published docs (useful for browsing and cross-referencing)** — https://microbiomedata.github.io/nmdc-schema/. Handy for skimming class hierarchies and allowed enum values, but may be ahead of or behind the installed version — treat the local package as source of truth when they disagree.
