# Package value sets (soil, water, sediment, plant-associated)

The NMDC submission schema restricts each env-triad slot to a curated value set for four MIxS packages — `SoilInterface`, `WaterInterface`, `SedimentInterface`, `PlantAssociatedInterface` (`EnvBroadScaleSoilEnum`, `EnvMediumWaterEnum`, …). Every other interface (hydrocarbon reservoirs, air, built environment, host-associated, biofilm, wastewater, miscellaneous) accepts any string, so there is nothing to enforce there and the honest report line is "no NMDC value set for `<interface>`".

The value sets are **vendored** in `src/nmdc_ingest_agent/validators/env_triad_valuesets.tsv` (columns `interface`, `slot`, `enum`, `curie`, `label`, `text`; `#` header comments record the `nmdc-submission-schema` version and generation date). You never need to import `nmdc-submission-schema` in the agent environment — its `rdflib<7` pin would downgrade the whole project. To list the allowed terms for a package + slot while curating:

```bash
# soil-package env_medium candidates (CURIE + label); awk is portable across macOS/Linux
awk -F'\t' '$1=="SoilInterface" && $2=="env_medium" {print $4"\t"$5}' \
    src/nmdc_ingest_agent/validators/env_triad_valuesets.tsv
```

The batch validator (`nmdc-ingest-validate-terms`, `SKILL.md` §2) infers the interface from the biosample's `env_package.has_raw_value` (e.g. `MIMS.me.soil.6.0` → `SoilInterface`) and writes `valueset_ok` per row: `true` / `false` for the four packages, `null` with a "no NMDC value set" note otherwise.

## Using the value sets while resolving

- **Package with a value set**: intersect the anchor-class descendants (`SKILL.md` § Slot anchor classes) with the value set and prefer candidates inside it. A scientifically correct term *outside* the set is allowed — the sets are curated but incomplete — but commit it knowingly: `valueset_ok` will come back `false` (warning), and the report row's `evidence` should say why the term is right anyway.
- **Package without a value set (or no package)**: resolve against the anchor class alone, **and tell the source skill's report step** so the run summary says "no NMDC value set for `<interface or package>`; value-set constraint not applicable" rather than implying the term was checked against one.

## Keeping the vendored sets current

When `nmdc-submission-schema` publishes a new release, regenerate the TSV in a throwaway overlay (the schema package never enters the project environment) and commit the diff:

```bash
uv run --with "nmdc-submission-schema>=11.24" python -m nmdc_ingest_agent.validators.generate_valuesets
```

> **Future seam.** This reference will grow into its own per-package curation skill the first time package-specific *guidance* (beyond the value sets) lands for water, sediment, host-associated or built-environment samples. Until then, additions for other packages live alongside this section so the future split stays mechanical.
