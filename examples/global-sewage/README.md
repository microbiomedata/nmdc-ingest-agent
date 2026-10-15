# Global Sewage record examples

Single-record JSON files, the env-triad crosswalk, and the cited source table for NCBI BioProject [PRJEB13831](https://www.ncbi.nlm.nih.gov/bioproject/518785) — *Global surveillance of infectious diseases and antimicrobial resistance from sewage* ([Hendriksen et al., Nat Commun 2019](https://doi.org/10.1038/s41467-019-08853-3)). The crosswalk covers the whole BioProject (97 BioSamples, 251 runs); the record examples come from an 18-sample subset — the roster of a partner's demo sample sheet, whose reads were reanalysed for bacteriophages in [Sci Rep 2021](https://doi.org/10.1038/s41598-021-80990-6).

This project is the reference case for an **ENA-brokered** BioProject (`PRJEB…` / `SAMEA…`) and for a source with **no env-triad in NCBI at all** — see *Quirks* in [`src/nmdc_ingest_agent/sources/ncbi/README.md`](../../src/nmdc_ingest_agent/sources/ncbi/README.md).

## Layout

```
global-sewage/
├── sources/hendriksen2019_suppdata1_extract.tsv   # cited per-sample evidence (all 81 survey rows)
├── sources/phage_demo_roster.csv                  # the 18-sample demo subset (biosample_accession, sample_name)
├── crosswalk/global_sewage_env_triad.tsv          # sample_name -> env triad, all 97 BioSamples
├── study_set/01_research_study.json
└── biosample_set/01…03_*.json
```

## `sources/` — the cited evidence

`hendriksen2019_suppdata1_extract.tsv` is the paper's **Supplementary Data 1** (`41467_2019_8853_MOESM4_ESM.txt`), all 81 rows, values verbatim (decimal commas, `NA`, and a mangled `Lom?` included). Only the un-prefixed sample-survey columns are kept; the World Bank (`wba_`), residue (`resi_`), ECDC (`ecdc_`), IMS (`ims_`) and `dia_freq` columns are dropped. `sample_ID` equals the NCBI `sample_name` (e.g. `CAN.22c`) with two exceptions handled in the crosswalk: the paper's `AUT.70` is NCBI's `AUS.70` (Vienna), and the 16 NCBI `DTU_2016_…_MG_Reproduce_<N>_<k>` samples have no row of their own — they are re-sequencings of sample `<N>`. `USA.74*`, `MDA.65` and the three `DNK.71_*` plants have no `site.characteristic` and/or no GPS in the published table.

The columns the curation relies on: `city`, `site.characteristic` (what the sampling site is), `latitude` / `longitude` (surveyed site GPS).

`phage_demo_roster.csv` lists the 18 BioSamples of the partner's demo sheet; pass it as `--biosamples` to rebuild that subset.

## `crosswalk/` — env triad per sample

`global_sewage_env_triad.tsv` has one row per BioSample (97), keyed by `fieldsample_barcode` (= NCBI `sample_name`), with triad cells as `label [CURIE]`, in the format `--env-triad-crosswalk` reads. It also carries the two source strings each row was derived from (`sewage_type` from NCBI, `site_characteristic` from the paper), the Supplementary Data 1 row used (`supp_sample_id`), and a `note` for the rows that needed one (the `AUS.70`/`AUT.70` rename; which parent each `Reproduce_<N>` sample takes its triad from, justified by the sample name and by NCBI coordinates that land in the parent's city; the sewer pipe with no ENVO term).

| Site type (`sewage_type`, or the parent's for `Reproduce_<N>`) | n | `env_broad_scale` | `env_local_scale` | `env_medium` |
|---|---|---|---|---|
| wastewater treatment plant (incl. its collection tank / inlet pipe, "city sewer treatment") | 79 | urban biome [ENVO:01000249] | wastewater treatment plant [ENVO:00002043] | sewage [ENVO:00002018] |
| river | 2 | urban biome | river [ENVO:00000022] | sewage |
| stream (sewage of the city drained into a natural stream) | 1 | urban biome | stream [ENVO:00000023] | sewage |
| open sewer line, covered sewer line, manholes of sewage system | 13 | urban biome | *blank — left as sentinel* | sewage |
| waste water pipe before the plant inlet (GEO.59) | 1 | urban biome | *blank — left as sentinel* | sewage |
| not provided (MDA.65) | 1 | urban biome | *blank — left as sentinel* | sewage |

The 15 blank `env_local_scale` cells are deliberate (`underspecified_slots` names them): ENVO has no `sewer`, `manhole` or `sewer pipe` term, and the nearest candidates (`plumbing drain`, `drainage ditch`, `pipeline network`) were rejected. Unlike MicroFlora Danica's crosswalk, this one was authored by curation inference rather than supplied by the data provider, so the curation report records these slots as `predicted` with evidence rows, not `resolved_at_pipeline`. Every CURIE and label was looked up in ENVO and checked against its slot's anchor class when the file was built.

## Records

Extracted verbatim from one pipeline build of the 18-sample subset (ids are placeholders and cross-reference).

| File | Sample | Demonstrates |
|---|---|---|
| `study_set/01_research_study.json` | — | `Study` from the ENA-brokered BioProject. |
| `biosample_set/01_wastewater_treatment_plant.json` | `CAN.22c` (Ottawa) | All three triad slots committed; `name` / `samp_name` from the submitter's `sample_name` (ENA's `Title` is just the organism name); `lat_lon` parsed from ENA's split latitude / longitude attributes; `sewage_type` carried verbatim. |
| `biosample_set/02_river_outlet.json` | `ECU.14` (Quito) | Sewage sampled at its outlet to a river: `env_local_scale` = river, `env_medium` = sewage. |
| `biosample_set/03_sewer_local_scale_sentinel.json` | `XK.60` (Prishtina) | `env_local_scale` left as the `ENVO:00000000` sentinel; `lat_lon` taken from Supplementary Data 1 because NCBI's longitude for this sample is a copy of its latitude. |

There are no `material_processing_set` / `processed_sample_set` / `data_generation_set` / `data_object_set` examples here yet. These records were extracted before NMDC had an `instrument_set` record for the `Illumina HiSeq 3000` every run uses, when the build excluded those records rather than emit them without `instrument_used`. The record now exists (`nmdc:inst-11-ezdsdp06`), so a current build emits the full chain — one LibraryPreparation → ProcessedSample → NucleotideSequencing → DataObject per SRA experiment.

## Regenerating

```bash
# whole BioProject (97 BioSamples, 251 runs)
uv run nmdc-ingest-ncbi PRJEB13831 \
    --env-triad-crosswalk examples/global-sewage/crosswalk/global_sewage_env_triad.tsv

# the 18-sample demo subset
uv run nmdc-ingest-ncbi PRJEB13831 \
    --biosamples examples/global-sewage/sources/phage_demo_roster.csv \
    --env-triad-crosswalk examples/global-sewage/crosswalk/global_sewage_env_triad.tsv
```

Two things are post-build curation edits (recorded in the curation report and in `runs/ncbi_PRJEB13831*/RUN_NOTES.md`), so a fresh build omits them until they are reapplied: `XK.60`'s `lat_lon` (from Supplementary Data 1), and the 16 `Reproduce_<N>` samples' `lat_lon` (NCBI holds their latitude and longitude in swapped attributes with decimal commas, which the build cannot parse; swapped back they land in the parent's city).
