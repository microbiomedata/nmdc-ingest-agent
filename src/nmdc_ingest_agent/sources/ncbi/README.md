# NCBI BioProject source

Translates an NCBI BioProject — along with its linked BioSamples and SRA runs — into an NMDC `Database` JSON artifact.

## What gets produced

For a given BioProject accession (e.g. `PRJNA1452545`), the script emits:

- **Study** — one record, derived from the BioProject title/description
- **Biosample** — one per linked BioSample (discovered via both SRA and E-utils `elink`)
- **MaterialProcessing** — one `Extraction` and one `LibraryPreparation` **per unique library** (keyed on `(biosample, library_name, strategy, source, selection, layout)`, *not* per experiment — several experiments can re-sequence one library), reconstructing the chain `Biosample → Extraction → ProcessedSample → LibraryPreparation → ProcessedSample → NucleotideSequencing`. The `LibraryPreparation` carries the SRA library descriptor (`library_strategy`, `library_source`, `library_selection`, `lib_layout`); `target_gene` and `protocol_link` are **parsed from the SRA `DESIGN_DESCRIPTION`** (an rRNA-gene mention → `TargetGeneEnum`; a DOI in the text → `protocol_link`), not hardcoded.
- **ProcessedSample** — two per unique library: the extracted nucleic acid (`Extracted DNA for <samp>`) and the sequencing library (named after the SRA library name, e.g. `ilm_MFD00001`).
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
```

For the full curator-quality workflow (ontology resolution, validation, review), use the `ncbi-to-nmdc` Claude Code skill at the repo root.
