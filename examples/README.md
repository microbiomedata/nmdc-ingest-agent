# NMDC record examples

Single-record JSON files demonstrating the shapes of records this repo produces for each NMDC `Database` collection. Useful as reference when reading the NMDC LinkML schema, designing downstream tooling, or sanity-checking ingest output.

**Source.** All examples were extracted verbatim from `results/ncbi_PRJNA1071982_nmdc.json` (NCBI BioProject [PRJNA1071982](https://www.ncbi.nlm.nih.gov/bioproject/?term=PRJNA1071982) — *MicroFlora Danica*) using `jq`. No record was hand-edited.

**Pre-curation snapshot.** These records are the output of the **deterministic pipeline** (`nmdc-ingest-ncbi`) only — no agent curation has run on them. That means:

- Every biosample's `env_broad_scale`, `env_local_scale`, and `env_medium` carries the `ENVO:00000000` sentinel CURIE. The submitter's free-text string is preserved in `has_raw_value` and echoed into `term.name` so the agent can resolve it via the `nmdc-env-triad` skill. Resolved CURIEs (e.g. `grassland biome`, `forest ecosystem`) appear only after that downstream curation pass — they are not visible here.
- `name` and `samp_name` are populated from NCBI's `<Ids>/<Id db_label="Sample name">` element with a `title → sample_name → accession` fallback (no `name: "NA"` here).

**Scope.** Database collections only (`study_set`, `biosample_set`, `data_generation_set`, `data_object_set`). The curation sidecars (`*_curation_inputs.json`, `*_curation_report.json`) are not represented here.

**ID note.** Every example uses placeholder NMDC IDs (`-99-` shoulder). Real ingest requires re-running the pipeline with `--mint-real-ids` against the NMDC Runtime API. Placeholder IDs are randomly minted each run, so re-extracting from a fresh `results/ncbi_PRJNA1071982_nmdc.json` will produce different ids matching the same criteria.

**These are reference documents, not test fixtures.** They illustrate the variation that shows up in pipeline output; they are not asserted-against by any automated test.

## study_set/

| File | Source id | Demonstrates |
|---|---|---|
| `01_research_study.json` | `nmdc:sty-99-87ca4b51` | Minimal NMDC `Study` shape for an NCBI BioProject — id, name (`"MicroFlora Danica"`), description, type. PI / abstract / associated files are absent because NCBI's BioProject record had nothing to populate them with. |

## biosample_set/

Six examples spanning the axes that actually vary in deterministic pipeline output: **MIxS package** (MIMAG.6.0 vs Metagenome.environmental.1.0), **env-triad raw text** (Soil / Water / Sediment / empty), **`lat_lon` presence**, and **`samp_taxon_id`** (NCBI metagenome taxa vs cultured/Candidatus taxa).

| File | Source id | Package | env_broad_scale raw | lat_lon | samp_taxon_id |
|---|---|---|---|---|---|
| `01_mimag_soil.json` | `nmdc:bsm-99-c8f1bc5b` | `MIMAG.6.0` | `"Soil"` | 56.90, 10.26 | `NCBITaxon:2283092` *Pyrinomonadaceae bacterium* |
| `02_mimag_water.json` | `nmdc:bsm-99-d0a0168c` | `MIMAG.6.0` | `"Water"` | 56.62, 8.90 | `NCBITaxon:28263` *Arcanobacterium sp.* |
| `03_mimag_sediment.json` | `nmdc:bsm-99-69dc0e32` | `MIMAG.6.0` | `"Sediment"` | 56.33, 9.64 | *Thermoplasmata archaeon* — also an archaeal taxon, not a bacterium |
| `04_mimag_no_lat_lon.json` | `nmdc:bsm-99-30e8a056` | `MIMAG.6.0` | `"Soil"` | **null** | *Pseudolabrys sp.* — geolocation-missing case |
| `05_metagenome_environmental_with_lat_lon.json` | `nmdc:bsm-99-03b31ff5` | `Metagenome.environmental.1.0` | `""` (empty) | 56.10, 10.46 | `NCBITaxon:749907` sediment metagenome — all three env-triad raws are empty (the `nmdc-env-triad` skill's §1b inference path applies) |
| `06_metagenome_environmental_no_lat_lon.json` | `nmdc:bsm-99-d9d5e434` | `Metagenome.environmental.1.0` | `""` (empty) | **null** | `NCBITaxon:256318` metagenome (generic) — env-triad empty AND no geolocation: the hardest case for inference |

**Notes:**

- All MIMAG biosamples in this BioProject have non-empty submitter strings in env-triad raws (`Soil` / `Water` / `Sediment` for broad, more specific phrases like `"Natural Grassland formations"` / `"Urban Biogas"` / `"Natural Freshwater"` for local/medium). All Metagenome.environmental biosamples have empty triad raws — the source provided no per-sample environment text. This drives which §1a/§1b path the env-triad skill takes per biosample.
- All biosamples in this BioProject have `geo_loc_name = "Denmark"` and Denmark-area `lat_lon` when present; geographic variation does not appear within this pilot.

## data_generation_set/

The pilot is uniform in analyte category (`metagenome`) and library shape — every record has one `has_input` biosample and one `has_output` data object. The only variation is which of three instruments was used.

| File | Source id | Instrument id | Demonstrates |
|---|---|---|---|
| `01_metagenome_nucleotide_sequencing.json` | `nmdc:dgns-99-9073f69d` | `nmdc:inst-99-6ee135f8` (~89%) | Modal `NucleotideSequencing` record: metagenome analyte, single input biosample, single output data object, INSDC SRA experiment identifier. |
| `02_metagenome_alternate_instrument.json` | `nmdc:dgns-99-45c24320` | `nmdc:inst-99-2607284e` (~7%) | Same shape, different instrument — documents that this BioProject uses three distinct sequencers without scanning the full record set. |

## data_object_set/

The pilot has only one data-object type, so a single example suffices.

| File | Source id | Demonstrates |
|---|---|---|
| `01_metagenome_raw_reads.json` | `nmdc:dobj-99-9d0a191d` | `data_object_type="Metagenome Raw Reads"`, `data_category="instrument_data"`, NCBI SRA URL. **Caveat:** `md5_checksum` and `file_size_bytes` are null — NCBI's source-side metadata does not expose these for SRA runs, so they cannot be populated at this layer. They would need to be filled when files are actually retrieved/staged for ingest. |

## Validation snippet

To confirm every example still validates against the installed NMDC schema:

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

Placeholder ids are random each run, so a fresh ingest produces records with different ids matching the same criteria. To refresh:

1. `uv run nmdc-ingest-ncbi PRJNA1071982` (note: NCBI's elink endpoint is occasionally flaky; the script retries 5 times per the fix in `fetch_linked_biosample_uids`).
2. For each example file, re-extract the record matching its criterion via `jq` against `results/ncbi_PRJNA1071982_nmdc.json`. The criteria are encoded in each row of the tables above.
3. Update the `Source id` column above with the new ids.
4. Run the validation snippet.
5. Do not hand-edit record content — these are extracted-as-is examples.

## Adding a new example

1. Identify the axis of variation it covers that isn't already represented.
2. Pick a representative from a pipeline output via `jq`.
3. Extract: `jq '.<collection>[] | select(.id=="<id>")' results/<output>.json > examples/<collection>/NN_<short_label>.json` (next available number prefix).
4. Run the validation snippet.
5. Add a row to the matching table above.
