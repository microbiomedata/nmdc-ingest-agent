# MicroFlora Danica record examples

Single-record JSON files extracted from the NMDC ingest output for NCBI BioProject [PRJNA1071982](https://www.ncbi.nlm.nih.gov/bioproject/?term=PRJNA1071982) — *MicroFlora Danica* ([Sereika et al., Nature 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC12823411/)). Useful as reference when reading the NMDC LinkML schema, designing downstream tooling, or sanity-checking ingest output.

**Source.** All examples were extracted verbatim from `results/ncbi_PRJNA1071982_nmdc.json` using `jq`. Record content is unedited.

**Env-triad resolved at pipeline (v2 crosswalk).** For MFD biosamples the env-triad is resolved **deterministically in code** during the build: `MfdEnvTriadResolver` (`src/nmdc_ingest_agent/sources/ncbi/mfd.py`) joins each biosample's `samp_name`/`MFDID` to `data/mfdo-crosswalk-v2/mfd_biosamples_annotated.tsv` and commits `env_broad_scale`, `env_local_scale`, and `env_medium`, so the curation report records `outcome: "resolved_at_pipeline"` for all three slots. Every MFD biosample gets all three slots — **100% coverage, no `ENVO:00000000` sentinels**. The v2 mapping draws on the full five-level MFD habitat hierarchy plus GEE land-cover refinement, so it is finer-grained than NCBI's coarse `isolation_source` (e.g. `02_forest` resolves to `temperate broadleaf forest biome` / `temperate freshwater swamp forest`, not a generic `forest biome`). The former two-stage "emit sentinels → agent curation pass" flow still applies to non-MFD sources; for MFD it is superseded.

**Scope.** Database collections only (`study_set`, `biosample_set`, `data_generation_set`, `data_object_set`). The curation sidecars are not represented here.

**ID note.** Every example uses placeholder NMDC IDs (`-99-` shoulder) **except** `instrument_used`. Real ingest requires re-running with `--mint-real-ids`. Placeholder IDs are randomly minted each run, so re-extracting from a fresh ingest will produce different ids matching the same criteria.

`instrument_used` is the exception: instruments are **resolved**, not minted. The pipeline matches each SRA `INSTRUMENT_MODEL` string against the live NMDC `instrument_set` (by instrument `name`, falling back to `InstrumentModelEnum` aliases) and asserts the existing `nmdc:inst-…` id. These ids are stable real identifiers, identical across runs and independent of `--mint-real-ids`. Resolution defaults to the **dev** runtime environment (`--env`/`NMDC_RUNTIME_ENV`); the ids above (`nmdc:inst-14-mr4r2w09`, `nmdc:inst-15-qkz3d028`) come from dev, where this BioProject's three sequencers all have `instrument_set` entries. A model with no `instrument_set` match resolves to nothing and leaves `instrument_used` empty.

**These are reference documents, not test fixtures.** They illustrate the variation that shows up in pipeline output; they are not asserted-against by any automated test.

## study_set/

| File | Source id | Demonstrates |
|---|---|---|
| `01_research_study.json` | `nmdc:sty-99-ebd80220` | NMDC `Study` for the MicroFlora Danica BioProject — id, name, description (NCBI-provided, mentions the project scope and metadata GitHub repo), type. |

## biosample_set/

Eight examples spanning the v2-resolved MFDO categories, including a sample-type axis (sediment), a built-environment case, and a missing-geolocation case. All three env-triad slots are populated (`resolved_at_pipeline`).

| File | Source id | env_broad_scale | env_local_scale | env_medium | samp_taxon_id | Notes |
|---|---|---|---|---|---|---|
| `01_cropland_agricultural_field.json` | `nmdc:bsm-99-887a8403` | `ENVO:01000245` cropland biome | `ENVO:00000114` agricultural field | `ENVO:00002259` agricultural soil | soil metagenome | The **modal** MFDO mapping — every slot has a precise ENVO term. 3,002 biosamples (~28%) follow this pattern. Gold-standard for a clean resolved record. |
| `02_forest.json` | `nmdc:bsm-99-af4c110f` | `ENVO:01000202` temperate broadleaf forest biome | `ENVO:01000398` temperate freshwater swamp forest | `ENVO:00001998` soil | soil metagenome | Forest sample (MFD00001). Shows v2 specificity: the hab2/hab3 levels (Temperate forests → Alluvial woodland) plus GEE refinement drive a precise `temperate freshwater swamp forest` feature, not the generic `forest ecosystem` v1 produced. |
| `03_grassland.json` | `nmdc:bsm-99-2a58f2d5` | `ENVO:01000177` grassland biome | `ENVO:01001811` temperate grassland | `ENVO:00001998` soil | soil metagenome | Grassland sample — 852 records (~8%) share this triple. v2 maps the local feature to `temperate grassland` (Denmark context) rather than a generic grassland ecosystem. |
| `04_urban_park.json` | `nmdc:bsm-99-dd788642` | `ENVO:01000249` urban biome | `ENVO:00000562` park | `ENVO:00001998` soil | soil metagenome | Urban green-space sample — 628 records (~6%). Demonstrates the `urban biome` + park feature mapping. |
| `05_marine_coast_sediment.json` | `nmdc:bsm-99-f38c5859` | `ENVO:00000447` marine biome | `ENVO:00000016` sea | `ENVO:03000033` marine sediment | sediment metagenome | Marine sediment sample — 320 records (~3%). Different sample-type axis (Sediment, not Soil) → different env_medium (`marine sediment`). |
| `06_wastewater_treatment.json` | `nmdc:bsm-99-9dad485e` | `ENVO:01000249` urban biome | `ENVO:00002043` wastewater treatment plant | `ENVO:00002001` waste water | wastewater metagenome | Built-environment sample. `env_medium` is `waste water` (not soil/sediment) and `samp_taxon_id` reflects the environment. |
| `07_coastal_dune.json` | `nmdc:bsm-99-b45076d3` | `ENVO:01000215` temperate shrubland biome | `ENVO:00000416` coastal dune | `ENVO:00001998` soil | soil metagenome | **v1→v2 improvement.** Natural Dunes had no clean broad-biome term under v1, so v1 left `env_broad_scale` an `ENVO:00000000` sentinel. v2 resolves all three slots (`temperate shrubland biome` / `coastal dune` / `soil`). 457 records (~4%). |
| `08_no_lat_lon.json` | `nmdc:bsm-99-f9719dce` | `ENVO:01000245` cropland biome | `ENVO:00000114` agricultural field | `ENVO:00002259` agricultural soil | soil metagenome | Same env triad as `01` but `lat_lon` is null. The env-triad is resolved from the MFD habitat barcode, independent of coordinates — ~26% of biosamples lack `lat_lon`. |

## data_generation_set/

The pilot is uniform in analyte category (`metagenome`) and library shape — every record has one `has_input` biosample and one `has_output` data object. Variation is the choice of one of three sequencers.

| File | Source id | Instrument id | Demonstrates |
|---|---|---|---|
| `01_metagenome_nucleotide_sequencing.json` | `nmdc:dgns-99-e09088eb` | `nmdc:inst-14-mr4r2w09` — Illumina NovaSeq 6000 (~89%) | Modal `NucleotideSequencing` record: metagenome analyte, single input biosample, single output data object, INSDC SRA experiment identifier. `instrument_used` is a **real** resolved Instrument id (matched on `name` against the live `instrument_set`), not a minted placeholder. |
| `02_metagenome_alternate_instrument.json` | `nmdc:dgns-99-1a94df50` | `nmdc:inst-15-qkz3d028` — Sequel IIe (~7%) | Same shape, different instrument — documents that this BioProject uses three distinct sequencers (NovaSeq 6000, Sequel IIe, PromethION). `instrument_used` is likewise a real resolved Instrument id. |

## data_object_set/

One data-object type, one example.

| File | Source id | Demonstrates |
|---|---|---|
| `01_metagenome_raw_reads.json` | `nmdc:dobj-99-01c27f0a` | `data_object_type="Metagenome Raw Reads"`, `data_category="instrument_data"`, NCBI SRA URL. This is the `has_output` of `data_generation_set/01`. **Caveat:** `md5_checksum` and `file_size_bytes` are null — NCBI's source-side metadata does not expose these for SRA runs; they need to be filled when files are actually retrieved/staged for ingest. |

## Validation snippet

```bash
uv run python -c "
from nmdc_schema import nmdc
from linkml_runtime.loaders import json_loader
import pathlib
target = {'study_set': nmdc.Study,
          'biosample_set': nmdc.Biosample,
          'data_generation_set': nmdc.NucleotideSequencing,
          'data_object_set': nmdc.DataObject}
for col, cls in target.items():
    for p in sorted(pathlib.Path(f'examples/microflora-danica/{col}').glob('*.json')):
        json_loader.loads(p.read_text(), target_class=cls)
        print(f'OK  {p}')
"
```

## Regenerating from a fresh ingest

Placeholder ids are random each run.

1. `uv run nmdc-ingest-ncbi PRJNA1071982` — the pipeline resolves the MFD env-triad in code from the v2 crosswalk (`mfd_biosamples_annotated.tsv` must be present under `data/mfdo-crosswalk-v2/`), so `results/ncbi_PRJNA1071982_nmdc.json` already carries fully populated triad slots — no separate curation pass.
2. For each example file, re-extract the record matching its criterion via `jq` against `results/ncbi_PRJNA1071982_nmdc.json`. The criteria are encoded in each row's term IDs in the tables above.
3. Update the `Source id` column above with the new ids.
4. Run the validation snippet.
5. Do not hand-edit record content — these are extracted-as-is examples.

## Adding a new example to this project

1. Identify the axis of variation it covers that isn't already represented.
2. Pick a representative from a pipeline output via `jq`.
3. Extract: `jq '.<collection>[] | select(.id=="<id>")' results/<output>.json > examples/microflora-danica/<collection>/NN_<short_label>.json` (next available number prefix).
4. Run the validation snippet.
5. Add a row to the matching table above.

For examples from a different project (new accession, new source), create a sibling project folder under `examples/` instead — see the top-level [`examples/README.md`](../README.md) for the convention.
