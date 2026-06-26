# NCBI BioProject source

Translates an NCBI BioProject — along with its linked BioSamples and SRA runs — into an NMDC `Database` JSON artifact.

## What gets produced

For a given BioProject accession (e.g. `PRJNA1452545`), the script emits:

- **Study** — one record, derived from the BioProject title/description
- **Biosample** — one per linked BioSample (discovered via both SRA and E-utils `elink`)
- **MaterialProcessing** — one `LibraryPreparation` **per unique library** (keyed on `(biosample, library_name, strategy, source, selection, layout)`, *not* per experiment — several experiments can re-sequence one library), forming the chain `Biosample → LibraryPreparation → ProcessedSample → NucleotideSequencing`. **No `Extraction` record** — NCBI supports asserting the library prep but not the extraction (likely 1:1 with the Biosample, but unconfirmable), so the `LibraryPreparation`'s `has_input` is the `Biosample` directly. It carries the SRA library descriptor (`library_strategy`, `library_source`, `library_selection`, `lib_layout`); `protocol_link` is parsed from a DOI in the `DESIGN_DESCRIPTION`. `target_gene` is committed only when the design names one **explicit** rRNA gene; amplicon designs needing inference (rRNA operons) are left unset and resolved by the model-agnostic `nmdc-target-gene` curation skill (the pipeline does not guess — a bacterial operon spans 16S *and* 23S).
- **ProcessedSample** — one per unique library: the sequencing library (named after the SRA library name, e.g. `ilm_MFD00001`), output of the `LibraryPreparation` and input of the per-run `NucleotideSequencing`.
- **DataGeneration** — one `NucleotideSequencing` **per SRA run**, consuming the library `ProcessedSample`; carries `insdc_experiment_identifiers` and `insdc_bioproject_identifiers`.
- **DataObject** — one per SRA run (`data_object_type = "SRA toolkit-accessible sequence data"`, `insdc_run_identifiers`, `was_generated_by` the run's NucleotideSequencing; no URL).
- **Manifest** — one per group of **poolable replicate runs** sharing `(biosample, library_name, instrument)` with ≥2 runs, grouping their `DataObject`s via `DataObject.in_manifest` (`poolable_replicates`). MicroFlora Danica has one run per library, so it produces none; a project like `SAMEA7724300` (4 WGS experiments sharing one library) yields 1 library chain, 4 data-generations, and 1 manifest.

All IDs use the shoulder `99` and are placeholders; they must be re-minted via the NMDC Runtime API before ingest.

> **Schema dependency:** the `LibraryPreparation` library-descriptor slots and the `SRA toolkit-accessible sequence data` data-object type were added in [nmdc-schema #3214](https://github.com/microbiomedata/nmdc-schema/pull/3214), released in **nmdc-schema 11.21.0** (`pyproject.toml` requires `nmdc-schema>=11.21.0`).

## Quirks worth knowing

- **BioSample discovery path.** BioSamples are discovered via two routes: (1) walking SRA experiments and (2) calling E-utils `elink` directly on the BioProject. The `elink` route catches BioSamples that exist in the BioProject but have no SRA runs yet.
- **env triad.** The script leaves `env_broad_scale` / `env_local_scale` / `env_medium` as free-text placeholders with a sentinel ENVO CURIE. The skill workflow uses `runoak` to resolve each one to the correct ENVO term within the appropriate MIxS anchor subtree.
- **Instrument.** SRA's `instrument_model` strings are stored verbatim on the generated record with a placeholder `nmdc:inst-99-*` ID. Real Instrument records are resolved at ingest time against the NMDC Runtime.
- **Host / samp_taxon.** Not inferred automatically. The skill flags ambiguous cases for PI follow-up rather than guessing.

## Standalone invocation

```bash
nmdc-ingest-ncbi PRJNA1452545 --fetch-only   # dump raw NCBI data for review
nmdc-ingest-ncbi PRJNA1452545                # produce NMDC JSON
nmdc-ingest-ncbi PRJNA1452545 --validate     # produce, then runtime-validate the JSON
```

### Runtime validation (`--validate`)

`--validate` POSTs the written deliverable to the NMDC runtime `/metadata/json:validate` endpoint after the file and sidecars are written. This is stronger than the local linkml schema load: on top of per-collection schema validation the endpoint enforces **referential integrity** (every `has_input` / `has_output` / `associated_studies` / `instrument_used` / `was_generated_by` / `in_manifest` reference must resolve), **biosample-name-uniqueness-per-study**, and **id-uniqueness**. No auth is required. On failure the per-collection `detail` is printed and the process exits non-zero (the file is preserved).

- **The env must match instrument resolution.** Validation runs against the same `--env` (default `dev`, else `NMDC_RUNTIME_ENV`) used to resolve `instrument_used`. Those ids exist only in that env's `instrument_set`, so validating against the other env fails referential integrity.
- The deliverable carries **no** top-level `@type: Database`. The pipeline serializes with `json_dumper.to_dict` (then `json.dump`) to match the canonical nmdc-runtime ETL (`RuntimeApiUserClient.{validate,submit}_metadata` both POST `json_dumper.to_dict(database)`), which omits `@type`; `json_dumper.dumps` would have injected it. (The endpoint ignores unknown / `@`-prefixed top-level keys regardless, so it isn't load-bearing either way.)
- Placeholder `-99-` ids validate fine. Network errors or an HTTP 5xx (a very large deliverable — tens of thousands of records — can 502 the endpoint) report a friendly message; the offline linkml load is the fallback.
- The reusable helper is `nmdc_ingest_agent.validation.validate_runtime(json_path, env)`.

For the full curator-quality workflow (ontology resolution, validation, review), use the `ncbi-to-nmdc` Claude Code skill at the repo root.
