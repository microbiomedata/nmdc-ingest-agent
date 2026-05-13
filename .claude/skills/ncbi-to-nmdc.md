---
name: ncbi-to-nmdc
description: Translate an NCBI BioProject (with BioSamples + SRA runs) into an NMDC-schema-compliant Database JSON file, then hand off curation to the nmdc-env-triad, nmdc-taxon-resolution, and nmdc-schema-reference skills.
---

# NCBI BioProject → NMDC JSON Translation

Given a BioProject accession (e.g. `PRJNA1452545`), fetch linked BioSample and SRA data from NCBI and produce an NMDC-schema-compliant `nmdc.Database` JSON file. This skill owns the source-specific transport (fetch, generate, validate, report). Curation steps that are not NCBI-specific are handled by sibling skills:

- `.claude/skills/nmdc-curation-rules.md` — evidence-first rules every commit must satisfy (cross-skill)
- `.claude/skills/nmdc-env-triad.md` — ENVO term selection / inference for `env_broad_scale` / `env_local_scale` / `env_medium`
- `.claude/skills/nmdc-taxon-resolution.md` — NCBITaxon resolution for host / `samp_taxon`
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

**Project-specific vocabulary check.** Before applying §1a to each biosample, check whether all four of these signals match: `geo_loc_name.has_raw_value == "Denmark"` AND `samp_name` matches `^MFD\d+` AND `env_broad_scale.has_raw_value` ∈ {`Soil`, `Water`, `Sediment`} AND `env_local_scale.has_raw_value` starts with one of {`Natural`, `Urban`, `Subterranean`, `Agriculture`}. If they all match, the biosample is from the **MicroFlora Danica** project, which uses a custom habitat ontology (MFDO) rather than ENVO-shaped submitter strings — read `.claude/skills/mfd-project-vocabulary.md` for the MFDO→ENVO crosswalk and use those candidates in §1a instead of free-form runoak search. (Note: after MIMAG/MISAG records are excluded per `_is_mag_package` in `translate.py`, the surviving MFD biosamples have empty env-triad raws and hit §1b inference instead — this pointer applies when MFDO labels do appear in the env triad, e.g. on pre-exclusion data or other BioProjects reusing the MFDO vocabulary.)

### Step 4: Resolve host / `samp_taxon` if needed

If the BioProject implies a host organism (e.g. host-associated samples, rhizosphere studies that name the plant) or a `samp_taxon` value needs lifting from free text, read `.claude/skills/nmdc-taxon-resolution.md` and follow its lookup + disambiguation pattern. Apply the unambiguous-intent rule: leave host fields unset and flag for PI follow-up rather than guessing.

### Step 5: Verify instrument records

The script stores SRA `instrument_model` strings verbatim and assigns an instrument ID — placeholder shoulder (`-99-`) by default, or a real minted ID when `--mint-real-ids` was passed. Leave the ID in place — real Instrument records are resolved at ingest. But verify the string is sensible (e.g. `Illumina NovaSeq X`, `Illumina NovaSeq 6000`, `Illumina HiSeq 2500`, `Illumina MiSeq`).

### Step 6: Validate

Validate the output JSON against the NMDC schema:

```bash
uv run python -c "
from nmdc_schema import nmdc
from linkml_runtime.loaders import json_loader
db = json_loader.load('results/ncbi_<ACCESSION>_nmdc.json', target_class=nmdc.Database)
print(f'Loaded: {len(db.study_set)} studies, {len(db.biosample_set)} biosamples, {len(db.data_generation_set)} data generations')
print('Validation passed!')
"
```

When a validation failure points at a non-trivial slot value (nested wrappers, enum ranges, range/scalar confusion), read `.claude/skills/nmdc-schema-reference.md` before guessing at the fix.

### Step 7: Report summary

Report to the user:
- Study name and accession
- Number of Biosamples, DataGenerations, DataObjects
- **Per-slot curation summary** computed from `results/ncbi_<ACCESSION>_nmdc_curation_report.json`. For each of `env_broad_scale`, `env_local_scale`, `env_medium`, count outcomes: `predicted`, `resolved_from_raw`, `resolved_at_pipeline`, `left_sentinel`, `validator_rejected`. The `left_sentinel` count is the curator-follow-up backlog.
- For soil-package biosamples, whether the MIxS soil-package valueset constraint was enforced (see `nmdc-env-triad.md` § Soil package). If `nmdc-submission-schema` was not importable, surface this explicitly as a known gap in the report — never silent fall-back.
- Any host / taxon fields left unset and flagged for PI follow-up
- The three output file paths: NMDC JSON, curation inputs sidecar, curation report
- If the run did not use `--mint-real-ids`, remind the user that IDs are placeholders (shoulder `99`) and that the ingest-ready output requires re-running with `--mint-real-ids` (set `NMDC_RUNTIME_CLIENT_ID` and `NMDC_RUNTIME_CLIENT_SECRET` first)

## Output

The final JSON file is written to `results/ncbi_<ACCESSION>_nmdc.json` relative to the current working directory.

## Scope

This skill produces **only** `Study`, `Biosample`, `DataGeneration`, and `DataObject` records. Do **not** create `Pooling`, `Extraction`, `LibraryPreparation`, or other process/material-transformation records — those are out of scope for NCBI-sourced ingest.

## Reference patterns

The traditional Dagster-orchestrated translators in [microbiomedata/nmdc-runtime](https://github.com/microbiomedata/nmdc-runtime) are still a useful reference for NMDC object construction, but **only** for the four record types in scope above:

- `nmdc_runtime/site/translation/translator.py` — base Translator class
- `nmdc_runtime/site/translation/gold_translator.py` — Study/Biosample/DataGeneration patterns
- `nmdc_runtime/site/translation/neon_utils.py` — helper functions for NMDC value types

Ignore patterns from `neon_soil_translator.py` (and any other translator) that construct `Extraction`, `LibraryPreparation`, or related process records — those do not apply to NCBI ingest.
