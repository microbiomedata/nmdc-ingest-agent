---
name: ncbi-to-nmdc
description: Translate an NCBI BioProject (with BioSamples + SRA runs) into an NMDC-schema-compliant Database JSON file, then hand off curation to the nmdc-env-triad, nmdc-taxon-resolution, and nmdc-schema-reference skills.
---

# NCBI BioProject → NMDC JSON Translation

Given a BioProject accession (e.g. `PRJNA1452545`), fetch linked BioSample and SRA data from NCBI and produce an NMDC-schema-compliant `nmdc.Database` JSON file. This skill owns the source-specific transport (fetch, generate, validate, report). Curation steps that are not NCBI-specific are handled by sibling skills:

- `.claude/skills/nmdc-curation-rules.md` — evidence-first rules every commit must satisfy (cross-skill)
- `.claude/skills/nmdc-env-triad.md` — ENVO term selection / inference for `env_broad_scale` / `env_local_scale` / `env_medium`
- `.claude/skills/nmdc-taxon-resolution.md` — NCBITaxon resolution for host / `samp_taxon`
- `.claude/skills/nmdc-target-gene.md` — amplicon `LibraryPreparation` curation: `description` (from the design text) on every amplicon library, plus `TargetGeneEnum` `target_gene` selection where the pipeline left it unset
- `.claude/skills/nmdc-schema-reference.md` — LinkML slot ranges, value-type wrappers, enum traps

## Prerequisites

This skill assumes the working directory is inside a checkout of `nmdc-ingest-agent` that has been synced with `uv`:

```bash
# from the repo root
uv sync --extra ontology
```

`uv sync` provisions `.venv/` from the committed `uv.lock`. The steps below invoke `uv run nmdc-ingest-ncbi` (and the curation skills' `uv run --extra ontology runoak` commands), which use that environment without requiring an active shell venv.

## Arguments

The user provides an NCBI BioProject accession as the argument (e.g. `/ncbi-to-nmdc PRJNA1452545`).

## Workflow

### Step 1: Fetch and review intermediate data

Run the helper script in fetch-only mode to see the raw NCBI data:

```bash
uv run nmdc-ingest-ncbi <ACCESSION> --fetch-only
```

Read the intermediate JSON file and review:
- **BioProject**: Does the title/description make sense? What `StudyCategoryEnum` fits? (Options: `research_study`, `consortium`)
- **BioSamples**: Do the `env_broad_scale`, `env_local_scale`, `env_medium` attributes have proper ENVO CURIEs or just free text?
- **SRA experiments**: What instrument models are used? What library strategies?

### Step 2: Generate NMDC JSON

Run the script without `--fetch-only`:

```bash
uv run nmdc-ingest-ncbi <ACCESSION>
```

The script always emits `ENVO:00000000` sentinels for the env triad (preserving the raw submitter string in `has_raw_value` when one was provided, or empty + `name="(not provided)"` when the source had nothing) and only forwards taxon information that NCBI itself supplied. Resolving sentinels and disambiguating hosts is the next two steps' job.

The script also writes two sidecar files alongside the NMDC JSON:

- `results/ncbi_<ACCESSION>_nmdc_curation_inputs.json` — BioProject context + full NCBI attributes per biosample (the inputs the env-triad skill reads when filling gaps).
- `results/ncbi_<ACCESSION>_nmdc_curation_report.json` — skeleton with one row per (biosample, slot), all initialized to `outcome: "left_sentinel"`. The agent updates this in place.

### Step 3: Resolve env-triad sentinels

Read `.claude/skills/nmdc-curation-rules.md` and `.claude/skills/nmdc-env-triad.md`. Apply the per-placeholder workflow to every `ENVO:00000000` sentinel in the generated JSON, choosing the resolution branch (§1a, when `has_raw_value` is non-empty) or the inference branch (§1b, when the value was genuinely missing). Update the curation-report row for each (biosample, slot) per the outcome you reach. Validate every committed CURIE per § Validate every committed CURIE.

**MicroFlora Danica biosamples are already resolved.** For MFD BioProjects (e.g. PRJNA1071982), the pipeline resolves the env-triad in code from the v2 MFDO crosswalk (`src/nmdc_ingest_agent/sources/ncbi/mfd.py`, keyed on `samp_name`/`MFDID`), so those rows arrive `resolved_at_pipeline` with no env-triad sentinels — there is nothing to curate by hand here. See `.claude/skills/mfd-project-vocabulary.md`. This Step 3 manual pass applies only to remaining sentinels (non-MFD biosamples, other sources, or an MFD biosample missing from the crosswalk's annotated file).

### Step 4: Resolve host / `samp_taxon` if needed

If the BioProject implies a host organism (e.g. host-associated samples, rhizosphere studies that name the plant) or a `samp_taxon` value needs lifting from free text, read `.claude/skills/nmdc-taxon-resolution.md` and follow its lookup + disambiguation pattern. Apply the unambiguous-intent rule: leave host fields unset and flag for PI follow-up rather than guessing.

### Step 5: Curate amplicon `description` + `target_gene`

The pipeline carries the SRA library descriptor but does not parse the free-text `DESIGN_DESCRIPTION`; every amplicon library is listed in the `amplicon_curation` section of the curation-inputs sidecar (grouped by distinct design, with the design text and the pipeline's current `target_gene`). Read `.claude/skills/nmdc-target-gene.md` and, per design: (1) set `LibraryPreparation.description` on **every** amplicon library, restating the target + primers from the design text in the skill's fixed template; (2) for `target_gene`, commit a single `TargetGeneEnum` value for a single-gene design, leave the pipeline's value as-is when already set, or **leave it unset** for a whole-operon amplicon (the slot is single-valued with no whole-operon value — the operon's target lives in `description`). Patch the listed `LibraryPreparation` records in the generated JSON accordingly. For MFD both operon designs (bacterial `8F`/`2490R`, eukaryotic `3NDF`/`21R`) get a description and **no `target_gene`** — see [nmdc-schema #3238](https://github.com/microbiomedata/nmdc-schema/pull/3238).

### Step 6: Verify instrument records

The script stores SRA `instrument_model` strings verbatim and assigns an instrument ID — placeholder shoulder (`-99-`) by default, or a real minted ID when `--mint-real-ids` was passed. Leave the ID in place — real Instrument records are resolved at ingest. But verify the string is sensible (e.g. `Illumina NovaSeq X`, `Illumina NovaSeq 6000`, `Illumina HiSeq 2500`, `Illumina MiSeq`).

### Step 7: Validate

Validate in two passes. Run this step **after** the env-triad (Step 3) and amplicon `description`/`target_gene` (Step 5) curation so the validated artifact is the *final* one.

**7a — Local linkml load (fast, offline first pass).** Schema-only; catches structural and enum problems without a network round-trip:

```bash
uv run python -c "
from nmdc_schema import nmdc
from linkml_runtime.loaders import json_loader
db = json_loader.load('results/ncbi_<ACCESSION>_nmdc.json', target_class=nmdc.Database)
print(f'Loaded: {len(db.study_set)} studies, {len(db.biosample_set)} biosamples, '
      f'{len(db.material_processing_set)} material processings, {len(db.processed_sample_set)} processed samples, '
      f'{len(db.data_generation_set)} data generations')
print('Validation passed!')
"
```

When a validation failure points at a non-trivial slot value (nested wrappers, enum ranges, range/scalar confusion), read `.claude/skills/nmdc-schema-reference.md` before guessing at the fix.

**7b — Runtime endpoint (authoritative).** The NMDC runtime `POST /metadata/json:validate` enforces, on top of per-collection schema validation, **referential integrity** (every `has_input` / `has_output` / `associated_studies` / `instrument_used` / `was_generated_by` / `in_manifest` reference must resolve in the payload or the runtime DB), **biosample-name-uniqueness-per-study**, and **id-uniqueness**:

```bash
uv run python -c "
from nmdc_ingest_agent.validation import validate_runtime
validate_runtime('results/ncbi_<ACCESSION>_nmdc.json', env='<ENV>')
print('Runtime validation passed (All Okay!).')
"
```

- **`<ENV>` must match the env instruments were resolved against** (the `--env` used for the run, default `dev`). `instrument_used` ids exist only in that env's `instrument_set`, so validating against the wrong env fails referential integrity. No auth is needed.
- The deliverable carries **no** top-level `@type: Database`: the pipeline serializes with `json_dumper.to_dict` to match the canonical nmdc-runtime ETL (`RuntimeApiUserClient.{validate,submit}_metadata`), which omits it. (The endpoint also ignores unknown / `@`-prefixed top-level keys, so a stray `@type` would validate too — but our output simply doesn't include one.)
- On failure the error carries the endpoint's **per-collection `detail`**; fix the flagged records and re-run 7b. A network error or HTTP 5xx (a very large deliverable — tens of thousands of records — can 502 the endpoint) reports a friendly message; in that case the local 7a pass is the fallback.

### Step 8: Report summary

Report to the user:
- Study name and accession
- Number of Biosamples, LibraryPreparations (`material_processing_set`), ProcessedSamples, DataGenerations, DataObjects
- **Per-slot curation summary** computed from `results/ncbi_<ACCESSION>_nmdc_curation_report.json`. For each of `env_broad_scale`, `env_local_scale`, `env_medium`, count outcomes: `predicted`, `resolved_from_raw`, `resolved_at_pipeline`, `left_sentinel`, `validator_rejected`. The `left_sentinel` count is the curator-follow-up backlog.
- For soil-package biosamples, whether the MIxS soil-package valueset constraint was enforced (see `nmdc-env-triad.md` § Soil package). If `nmdc-submission-schema` was not importable, surface this explicitly as a known gap in the report — never silent fall-back.
- Any host / taxon fields left unset and flagged for PI follow-up
- The three output file paths: NMDC JSON, curation inputs sidecar, curation report
- If the run did not use `--mint-real-ids`, remind the user that IDs are placeholders (shoulder `99`) and that the ingest-ready output requires re-running with `--mint-real-ids` (set `NMDC_RUNTIME_CLIENT_ID` and `NMDC_RUNTIME_CLIENT_SECRET` first)

## Output

The final JSON file is written to `results/ncbi_<ACCESSION>_nmdc.json` relative to the current working directory.

## Scope

This skill produces `Study`, `Biosample`, `LibraryPreparation`, `ProcessedSample`, `DataGeneration`, `DataObject`, and (for poolable replicate runs) `Manifest` records.

The pipeline reconstructs the NMDC material-processing chain so a `NucleotideSequencing` consumes a `ProcessedSample` rather than the `Biosample` directly, and emits **one `NucleotideSequencing` + one `DataObject` per SRA run**:

```
Biosample
  --LibraryPreparation--> ProcessedSample (sequencing library)
  --NucleotideSequencing--> DataObject        (one chain per run)
```

**No `Extraction` record.** NCBI/SRA gives enough information to assert the library prep but **not** the nucleic-acid extraction (an `Extraction` is most likely 1:1 with the `Biosample`, but that cannot be confirmed). So the `LibraryPreparation` consumes the `Biosample` directly (`has_input = [biosample]`) and there is no extracted-nucleic-acid `ProcessedSample` — only the sequencing-library one.

**Per unique library — not per experiment.** Several SRA experiments can re-sequence one library (same `LIBRARY_NAME` + descriptor under distinct experiment accessions), so the chain is keyed on the unique library `(biosample, library_name, strategy, source, selection, layout)`: one `LibraryPreparation` (into `material_processing_set`) with one `ProcessedSample` output (into `processed_sample_set`), per unique library. Per-run: one `NucleotideSequencing` (into `data_generation_set`) and one `DataObject` (into `data_object_set`). When a library's runs **share an instrument** — i.e. ≥2 runs sharing `(biosample, library_name, instrument)` — a `Manifest` (`manifest_category: poolable_replicates`, into `manifest_set`) groups those run `DataObject`s via `in_manifest`. (MicroFlora Danica has one library/run per experiment, so it produces no `Manifest`s; a project like [`SAMEA7724300`](https://www.ncbi.nlm.nih.gov/Traces/study/?acc=SAMEA7724300) with 4 WGS experiments sharing one library yields 1 library chain, 4 data-generations, and 1 manifest.) NCBI/SRA does not record wet-lab dates/mass/institution, so those stay unset; the fields it *does* supply are populated:

- **LibraryPreparation** — `has_input` is the `Biosample`; `library_strategy`, `library_source`, `library_selection`, `lib_layout` (from the SRA library descriptor). `protocol_link` is parsed from a DOI in the `DESIGN_DESCRIPTION` (e.g. MFD's WGS "…see https://doi.org/…"). `target_gene` is committed by the pipeline only when the design names **one explicit rRNA gene** (e.g. "amplify bacterial 16S rRNA genes" → `16S_rRNA`); whole-operon amplicons are **left unset** — `target_gene` is single-valued with no whole-operon value (a bacterial operon spans 16S *and* 23S). The amplicon `description` (e.g. "Amplicon library preparation targeting bacterial rRNA operons using 8F and 2490R primers") is **not** parsed by the pipeline — the `nmdc-target-gene` curation skill (Step 5) writes it from the design text, and for operons it carries the target the omitted `target_gene` cannot.
- **ProcessedSample** — one per library, named after the SRA library name (e.g. `ilm_MFD00001`) with a descriptive `description`; it is the `LibraryPreparation`'s output and the `NucleotideSequencing`'s input.
- **DataObject** — `data_object_type: "SRA toolkit-accessible sequence data"`, `insdc_run_identifiers`, `was_generated_by` (the run's NucleotideSequencing); **no** URL.
- **NucleotideSequencing** — `insdc_experiment_identifiers` + `insdc_bioproject_identifiers`; named `Run <SRR> for experiment <SRX> - <samp_name>`.

Do **not** create `Extraction` or `Pooling` records — NCBI supports neither, so the `LibraryPreparation` consumes the `Biosample` directly.

> **Schema dependency:** the `LibraryPreparation` library-descriptor slots and the `SRA toolkit-accessible sequence data` data-object type were added in [nmdc-schema #3214](https://github.com/microbiomedata/nmdc-schema/pull/3214), released in **nmdc-schema 11.21.0**; `pyproject.toml` requires `nmdc-schema>=11.21.0`.

## Reference patterns

The traditional Dagster-orchestrated translators in [microbiomedata/nmdc-runtime](https://github.com/microbiomedata/nmdc-runtime) are a useful reference for NMDC object construction:

- `nmdc_runtime/site/translation/translator.py` — base Translator class
- `nmdc_runtime/site/translation/gold_translator.py` — Study/Biosample/DataGeneration patterns
- `nmdc_runtime/site/translation/neon_utils.py` — helper functions for NMDC value types
- `nmdc_runtime/site/translation/neon_soil_translator.py` — the `_translate_library_preparation` and `_translate_processed_sample` helpers are a reference for the `Biosample → LibraryPreparation → ProcessedSample → NucleotideSequencing` wiring (see `build_library_records` in `translate.py`).

Ignore the `Extraction` and `Pooling` patterns from `neon_soil_translator.py` — NCBI supports neither, so the `LibraryPreparation` consumes the `Biosample` directly rather than an extracted-nucleic-acid or pooling `ProcessedSample`.
