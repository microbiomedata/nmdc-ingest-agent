# Run notes — ncbi PRJNA1071982

## Run metadata

- **Source:** ncbi
- **Accession:** PRJNA1071982
- **Run date:** 2026-06-30
- **Env:** dev
- **Mint mode:** placeholder
- **Command:** uv run nmdc-ingest-ncbi PRJNA1071982

## Record counts

- study_set: 1
- biosample_set: 10689
- material_processing_set: 11995
- processed_sample_set: 11995
- data_generation_set: 11995
- data_object_set: 11995

## Resolution summary

| slot | resolved | deferred | flagged |
|---|---|---|---|
| env_broad_scale | 10689 | 0 | 0 |
| env_local_scale | 10689 | 0 | 0 |
| env_medium | 10689 | 0 | 0 |

## Deferred — needs a human decision

- none

## Exclusions

- 4,617 BioSample(s) using MAG-only MIxS packages (`MIMAG.6.0`) excluded — NMDC `Biosample` is for environmental samples, not assembled genomes.
- env-triad resolved deterministically at the pipeline from the v2 MFDO crosswalk (barcode join), so all 10,689 arrive `resolved_at_pipeline` — no manual env-triad curation needed here.

## Validation

- Local linkml schema load: passed.
- Runtime `json:validate` (dev): a full-payload POST can 502 (tens of thousands of records); validate against the same `--env` instruments were resolved in.
- Amplicon `target_gene`: the two operon designs (`8F`/`2490R`, `3NDF`/`21R`) are deliberately left unset; single-gene `16S` design set by the pipeline (see `nmdc-target-gene`).

## Decisions for next run

Human steering lives in `DECISIONS.md` (free-form) and `overrides.tsv` (term overrides). This file is regenerated each run and does not read them back — the ingest skill's Step 0 reads `DECISIONS.md`.
