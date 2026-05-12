# NMDC record examples

Single-record JSON files demonstrating the shapes of records this repo produces for each NMDC `Database` collection. Useful as reference when reading the NMDC LinkML schema, designing downstream tooling, or sanity-checking ingest output.

**Source.** All examples were extracted verbatim from `results/ncbi_PRJNA1071982_nmdc.json` (NCBI BioProject [PRJNA1071982](https://www.ncbi.nlm.nih.gov/bioproject/?term=PRJNA1071982) — *MicroFlora Danica*) using `jq`. No record was hand-edited.

**MIMAG records excluded.** As of this branch the pipeline drops MIxS `MIMAG.6.0` / `MISAG.6.0` biosamples (4,617 of the 15,306 elink-discovered records for this pilot). Those packages describe single-organism genome assemblies, not environmental samples, and don't fit the NMDC `Biosample` model. The remaining 10,689 records all use `Metagenome.environmental.1.0`.

**Pre-curation snapshot.** These records are the output of the **deterministic pipeline** (`nmdc-ingest-ncbi`) only — no agent curation has run on them:

- Every biosample's `env_broad_scale`, `env_local_scale`, and `env_medium` carries the `ENVO:00000000` sentinel CURIE with empty `has_raw_value` (the source didn't provide per-sample env-triad text for this BioProject's Metagenome.environmental records). The `nmdc-env-triad` skill's **§1b inference path** is what eventually resolves these.
- `name` / `samp_name` are populated from NCBI's `<Ids>/<Id db_label="Sample name">` (MFD ids like `MFD13535`).

**Scope.** Database collections only (`study_set`, `biosample_set`, `data_generation_set`, `data_object_set`). The curation sidecars (`*_curation_inputs.json`, `*_curation_report.json`) are not represented here.

**ID note.** Every example uses placeholder NMDC IDs (`-99-` shoulder). Real ingest requires re-running with `--mint-real-ids`. Placeholder IDs are randomly minted each run, so re-extracting from a fresh ingest will produce different ids matching the same criteria.

**These are reference documents, not test fixtures.** They illustrate the variation that shows up in pipeline output; they are not asserted-against by any automated test.

## study_set/

| File | Source id | Demonstrates |
|---|---|---|
| `01_research_study.json` | `nmdc:sty-99-8716b7b8` | Minimal NMDC `Study` for an NCBI BioProject — id, name (`"MicroFlora Danica"`), description, type. PI / abstract / associated files are absent because NCBI's BioProject record had nothing to populate them with. |

## biosample_set/

Three examples spanning the axes that actually vary in deterministic pipeline output *after MIMAG exclusion*: **`lat_lon` presence** and **`samp_taxon_id`** (different NCBI metagenome taxa). All surviving records use `env_package = Metagenome.environmental.1.0` with all-empty env-triad raws — the inference path applies uniformly.

| File | Source id | `samp_name` | lat_lon | `samp_taxon_id` |
|---|---|---|---|---|
| `01_typical_with_lat_lon.json` | `nmdc:bsm-99-485c0f3f` | `MFD13535` | 56.something, 9.something | `NCBITaxon:410658` soil metagenome — the modal case (~78% of records) |
| `02_no_lat_lon.json` | `nmdc:bsm-99-ab2a60dc` | `MFD10339` | **null** | `NCBITaxon:408169` metagenome (generic) — geolocation-missing case (~26% of records) |
| `03_alternate_metagenome_taxon.json` | `nmdc:bsm-99-b73617f0` | `MFD13439` | populated | `NCBITaxon:527639` wastewater metagenome — covers a non-soil taxon assignment; this BioProject also includes `freshwater sediment metagenome`, `sediment metagenome`, `drinking water metagenome`, `biogas fermenter metagenome`, `freshwater metagenome`, and `marine metagenome` |

**Notes:**

- All biosamples in this pilot have `geo_loc_name = "Denmark"` and (when present) Denmark-area `lat_lon`. There is no geographic variation within this BioProject.
- All `env_broad_scale` / `env_local_scale` / `env_medium` raws are empty (`has_raw_value = ""`) on every record. The deterministic pipeline emits `ENVO:00000000` sentinels with `term.name = "(not provided)"`. The `nmdc-env-triad` skill's §1b inference path uses `env_package`, `samp_taxon_id`, `geo_loc_name`, BioProject context, and sibling consensus to fill these in.

## data_generation_set/

Uniform analyte category (`metagenome`) and library shape — every record has one `has_input` biosample and one `has_output` data object. Variation is the choice of one of three sequencers.

| File | Source id | Instrument id | Demonstrates |
|---|---|---|---|
| `01_metagenome_nucleotide_sequencing.json` | `nmdc:dgns-99-70e3c133` | `nmdc:inst-99-54a48998` (~89%) | Modal `NucleotideSequencing` record: metagenome analyte, single input biosample, single output data object, INSDC SRA experiment identifier. |
| `02_metagenome_alternate_instrument.json` | `nmdc:dgns-99-b659a93c` | `nmdc:inst-99-3c28c19a` (~7%) | Same shape, different instrument — documents that this BioProject uses three distinct sequencers without scanning the full record set. |

## data_object_set/

One data-object type, one example.

| File | Source id | Demonstrates |
|---|---|---|
| `01_metagenome_raw_reads.json` | `nmdc:dobj-99-192d0b0d` | `data_object_type="Metagenome Raw Reads"`, `data_category="instrument_data"`, NCBI SRA URL. **Caveat:** `md5_checksum` and `file_size_bytes` are null — NCBI's source-side metadata does not expose these for SRA runs; they need to be filled when files are actually retrieved/staged for ingest. |

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
    for p in sorted(pathlib.Path(f'examples/{col}').glob('*.json')):
        json_loader.loads(p.read_text(), target_class=cls)
        print(f'OK  {p}')
"
```

## Regenerating from a fresh ingest

Placeholder ids are random each run.

1. `uv run nmdc-ingest-ncbi PRJNA1071982` (note: NCBI's bp→biosample elink endpoint is intermittently flaky; the script retries 5 times. If all 5 fail, falls back to SRA-only — which produces the same 10,689 biosamples here since MIMAG records have no SRA runs and would have been excluded anyway).
2. For each example file, re-extract the record matching its criterion via `jq` against `results/ncbi_PRJNA1071982_nmdc.json`.
3. Update the `Source id` column above with the new ids.
4. Run the validation snippet.
5. Do not hand-edit record content — these are extracted-as-is examples.

## Adding a new example

1. Identify the axis of variation it covers that isn't already represented.
2. Pick a representative from a pipeline output via `jq`.
3. Extract: `jq '.<collection>[] | select(.id=="<id>")' results/<output>.json > examples/<collection>/NN_<short_label>.json` (next available number prefix).
4. Run the validation snippet.
5. Add a row to the matching table above.
