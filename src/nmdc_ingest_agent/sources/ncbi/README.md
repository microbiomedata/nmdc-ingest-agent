# NCBI BioProject source

Translates an NCBI BioProject — along with its linked BioSamples and SRA runs — into an NMDC `Database` JSON artifact.

## What gets produced

For a given BioProject accession (e.g. `PRJNA1452545`), the script emits:

- **Study** — one record, derived from the BioProject title/description
- **Biosample** — one per linked BioSample (discovered via both SRA and E-utils `elink`)
- **MaterialProcessing** — `Extraction` and `LibraryPreparation` records, where the SRA experiment metadata supports it
- **DataGeneration** — one `NucleotideSequencing` per SRA experiment
- **DataObject** — one per SRA run

All IDs use the shoulder `99` and are placeholders; they must be re-minted via the NMDC Runtime API before ingest.

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
