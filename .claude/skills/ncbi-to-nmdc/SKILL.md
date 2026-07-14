---
name: ncbi-to-nmdc
description: "Use this skill to translate an NCBI BioProject (BioSamples plus SRA runs) into an NMDC-schema Database JSON, then hand curation to the nmdc-env-triad, nmdc-taxon-resolution, nmdc-target-gene and nmdc-schema-reference skills, validate, and emit run notes via the ingest-run-notes skill. Trigger on a BioProject accession like PRJNA1452545, on the /ncbi-to-nmdc command, or on requests to ingest, translate, or convert an NCBI project or BioSample into NMDC."
---

# NCBI BioProject → NMDC JSON Translation

Given a BioProject accession (e.g. `PRJNA1452545`), fetch linked BioSample and SRA data from NCBI and produce an NMDC-schema-compliant `nmdc.Database` JSON file. This skill owns the source-specific transport (fetch, generate, validate, report). Curation steps that are not NCBI-specific are handled by sibling skills:

- `nmdc-curation-rules` — evidence-first rules every commit must satisfy (cross-skill)
- `nmdc-env-triad` — ENVO term selection / inference for `env_broad_scale` / `env_local_scale` / `env_medium`
- `nmdc-taxon-resolution` — NCBITaxon resolution for host / `samp_taxon`
- `nmdc-target-gene` — amplicon `LibraryPreparation` curation: `description` (from the design text) on every amplicon library, plus `TargetGeneEnum` `target_gene` selection where the pipeline left it unset
- `nmdc-schema-reference` — LinkML slot ranges, value-type wrappers, enum traps

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

Read `nmdc-curation-rules` and `nmdc-env-triad`. Apply the per-placeholder workflow to every `ENVO:00000000` sentinel in the generated JSON, choosing the resolution branch (§1a, when `has_raw_value` is non-empty) or the inference branch (§1b, when the value was genuinely missing). Update the curation-report row for each (biosample, slot) per the outcome you reach. Validate every committed CURIE per § Validate every committed CURIE.

**MicroFlora Danica biosamples are already resolved.** For MFD BioProjects (e.g. PRJNA1071982), the pipeline resolves the env-triad in code from the v2 MFDO crosswalk (`src/nmdc_ingest_agent/sources/ncbi/mfd.py`, keyed on `samp_name`/`MFDID`), so those rows arrive `resolved_at_pipeline` with no env-triad sentinels — there is nothing to curate by hand here. See `.claude/skills/mfd-project-vocabulary.md`. This Step 3 manual pass applies only to remaining sentinels (non-MFD biosamples, other sources, or an MFD biosample missing from the crosswalk's annotated file).

### Step 4: Resolve host / `samp_taxon` if needed

If the BioProject implies a host organism (e.g. host-associated samples, rhizosphere studies that name the plant) or a `samp_taxon` value needs lifting from free text, read `nmdc-taxon-resolution` and follow its lookup + disambiguation pattern. Apply the unambiguous-intent rule: leave host fields unset and flag for PI follow-up rather than guessing.

### Step 5: Curate amplicon `description` + `target_gene`

The pipeline carries the SRA library descriptor but does not parse the free-text `DESIGN_DESCRIPTION`; every amplicon library is listed in the `amplicon_curation` section of the curation-inputs sidecar (grouped by distinct design, with the design text and the pipeline's current `target_gene`). Read `nmdc-target-gene` and, per design: (1) set `LibraryPreparation.description` on **every** amplicon library, restating the target + primers from the design text in the skill's fixed template; (2) for `target_gene`, commit a single `TargetGeneEnum` value for a single-gene design, leave the pipeline's value as-is when already set, or **leave it unset** for a whole-operon amplicon (the slot is single-valued with no whole-operon value — the operon's target lives in `description`). Patch the listed `LibraryPreparation` records in the generated JSON accordingly. For MFD both operon designs (bacterial `8F`/`2490R`, eukaryotic `3NDF`/`21R`) get a description and **no `target_gene`** — see [nmdc-schema #3238](https://github.com/microbiomedata/nmdc-schema/pull/3238).

### Step 6: Verify instrument records

The script stores SRA `instrument_model` strings verbatim and assigns an instrument ID — placeholder shoulder (`-99-`) by default, or a real minted ID when `--mint-real-ids` was passed. Leave the ID in place — real Instrument records are resolved at ingest. But verify the string is sensible (e.g. `Illumina NovaSeq X`, `Illumina NovaSeq 6000`, `Illumina HiSeq 2500`, `Illumina MiSeq`).

### Step 7: Validate

Validate in two passes. Run this step **after** the env-triad (Step 3) and amplicon `description`/`target_gene` (Step 5) curation so the validated artifact is the *final* one.

**7a — Local linkml load (fast, offline first pass).** Schema-only; catches structural and enum problems without a network round-trip:

```bash
uv run python .claude/skills/ncbi-to-nmdc/scripts/validate_local.py results/ncbi_<ACCESSION>_nmdc.json
```

When a validation failure points at a non-trivial slot value (nested wrappers, enum ranges, range/scalar confusion), read `nmdc-schema-reference` before guessing at the fix.

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
- For soil-package biosamples, whether the MIxS soil-package valueset constraint was enforced (see `nmdc-env-triad` § Soil package). If `nmdc-submission-schema` was not importable, surface this explicitly as a known gap in the report — never silent fall-back.
- Any host / taxon fields left unset and flagged for PI follow-up
- The three output file paths: NMDC JSON, curation inputs sidecar, curation report
- If the run did not use `--mint-real-ids`, remind the user that IDs are placeholders (shoulder `99`) and that the ingest-ready output requires re-running with `--mint-real-ids` (set `NMDC_RUNTIME_CLIENT_ID` and `NMDC_RUNTIME_CLIENT_SECRET` first)

## Output

The final JSON file is written to `results/ncbi_<ACCESSION>_nmdc.json` relative to the current working directory.

## Scope

This skill produces `Study`, `Biosample`, `LibraryPreparation`, `ProcessedSample`, `DataGeneration`, `DataObject`, and (for poolable replicate runs) `Manifest` records. The chain is `Biosample → LibraryPreparation → ProcessedSample → NucleotideSequencing → DataObject`, one library chain per unique library and one NucleotideSequencing + DataObject per SRA run. There is **no `Extraction` or `Pooling`** record — NCBI cannot confirm them, so the `LibraryPreparation` consumes the `Biosample` directly.

For the full record-by-record modeling contract (per-library vs per-run keys, `Manifest` grouping, which slots each record populates, the nmdc-schema 11.21.0 dependency), see [`references/scope.md`](references/scope.md).

## Reference patterns

The Dagster-orchestrated translators in [microbiomedata/nmdc-runtime](https://github.com/microbiomedata/nmdc-runtime) are a useful reference for NMDC object construction — see [`references/reference-patterns.md`](references/reference-patterns.md) for the specific files.
