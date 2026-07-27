# Run notes — <source> <accession>

## Run metadata

- **Source:** <source>
- **Accession:** <accession>
- **Run date:** <YYYY-MM-DD>
- **Env:** <dev|prod>
- **Mint mode:** <placeholder|real>
- **Command:** <exact command line>

## Record counts

- study_set: <n>
- biosample_set: <n>
- material_processing_set: <n>
- processed_sample_set: <n>
- data_generation_set: <n>
- data_object_set: <n>

## Resolution summary

| slot | resolved | deferred | flagged |
|---|---|---|---|
| env_broad_scale | <n> | <n> | <n> |
| env_local_scale | <n> | <n> | <n> |
| env_medium | <n> | <n> | <n> |

## Deferred — needs a human decision

- **<slot>** (<n>): <biosample ids…>

## Exclusions

<!-- what was dropped and why (e.g. MAG-only biosamples with no SRA run) -->

## Validation

<!-- local linkml load result; runtime json:validate result; known failures -->

## Decisions for next run

Human steering lives in `DECISIONS.md` (free-form) and `overrides.tsv` (term overrides).
This file is regenerated each run and does not read them back — the ingest skill's Step 0
reads `DECISIONS.md`.
