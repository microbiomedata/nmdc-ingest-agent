# NMDC record examples

Single-record JSON files demonstrating the shapes of records this repo produces for each NMDC `Database` collection. Useful as reference when reading the NMDC LinkML schema, designing downstream tooling, or sanity-checking ingest output.

**Source.** All examples were extracted verbatim from `results/ncbi_PRJNA1071982_nmdc.json` (NCBI BioProject [PRJNA1071982](https://www.ncbi.nlm.nih.gov/bioproject/?term=PRJNA1071982) — *MicroFlora Danica*) using `jq`. No record was hand-edited.

**Scope.** Database collections only (`study_set`, `biosample_set`, `data_generation_set`, `data_object_set`). The curation sidecars (`*_curation_inputs.json`, `*_curation_report.json`) are not represented here.

**ID note.** Every example uses placeholder NMDC IDs (`-99-` shoulder). Real ingest requires re-running the pipeline with `--mint-real-ids` against the NMDC Runtime API.

**These are reference documents, not test fixtures.** They illustrate the variation that actually shows up in pipeline output; they are not asserted-against by any automated test.

## study_set/

| File | Source id | Demonstrates |
|---|---|---|
| `01_research_study.json` | `nmdc:sty-99-3a8ddf78` | Minimal NMDC `Study` shape — id, name, type. Most other slots (PI, abstract, associated files) are absent because NCBI's BioProject record had nothing to populate them with. |

## biosample_set/

Seven examples spanning the axes that vary in the pilot output: MIxS package, env-triad completeness, geolocation presence, and resolved-vs-sentinel CURIE patterns.

| File | Source id | env_package | env_broad_scale | env_local_scale | env_medium | Notes |
|---|---|---|---|---|---|---|
| `01_mimag_fully_resolved_envtriad.json` | `nmdc:bsm-99-6b29577f` | `MIMAG.6.0` | `ENVO:01000177` (grassland biome) | `ENVO:01001206` (grassland ecosystem) | `ENVO:00001998` (soil) | "Clean" triad: all three slots have non-sentinel CURIEs. **Caveat:** `grassland biome` is-a `grassland ecosystem` per ENVO's `is-a` graph, so the broad slot is more specific than the local slot — a hierarchy inversion. Common in pipeline output; flag for curator review. |
| `02_mimag_local_sentinel.json` | `nmdc:bsm-99-771dfcb1` | `MIMAG.6.0` | `ENVO:01000249` (urban biome) | `ENVO:00000000` (Subterranean Urban) | `ENVO:00001998` (soil) | Submitter's `env_local_scale` raw text didn't lift to a CURIE. The sentinel preserves the raw string in `term.name` and `has_raw_value`. |
| `03_mimag_broad_sentinel.json` | `nmdc:bsm-99-16ebbf45` | `MIMAG.6.0` | `ENVO:00000000` (Soil) | `ENVO:01000687` (coast) | `ENVO:00001998` (soil) | Mirror case: broad is the sentinel, local resolved. The raw `"Soil"` in `env_broad_scale` is itself a *material* — a swap pattern where the submitter put a medium value in the broad slot. |
| `04_mimag_both_envtriad_sentinels.json` | `nmdc:bsm-99-6f38c172` | `MIMAG.6.0` | `ENVO:00000000` (Soil) | `ENVO:00000000` (Natural NA) | `ENVO:00001998` (soil) | Heavy curator-follow-up case: neither broad nor local lifted. Note the raw `"Natural NA"` — NCBI's `"NA"` missing-value placeholder bleeding through. |
| `05_metagenome_environmental_package.json` | `nmdc:bsm-99-10d49338` | `Metagenome.environmental.1.0` | `ENVO:00000000` ((not provided)) | `ENVO:00000000` ((not provided)) | `ENVO:00000000` ((not provided)) | Distinct MIxS package from MIMAG (~70% of records in this BioProject use this package). All three triad slots are *genuinely missing* (empty `has_raw_value`, `term.name = "(not provided)"`), not just unlifted — the inference branch of the env-triad skill applies. |
| `06_mimag_no_lat_lon.json` | `nmdc:bsm-99-0b60380b` | `MIMAG.6.0` | `ENVO:01000177` (grassland biome) | `ENVO:01001206` (grassland ecosystem) | `ENVO:00001998` (soil) | Same env-triad shape as example #1, but `lat_lon` is null. Demonstrates the no-geolocation case (~20% of biosamples in this pilot). |
| `07_cropland_agricultural_field.json` | `nmdc:bsm-99-642bf9ca` | `MIMAG.6.0` | `ENVO:01000245` (cropland biome) | `ENVO:00000114` (agricultural field) | `ENVO:00002259` (agricultural soil) | A coherent broad/local/medium triple (cropland biome → agricultural field → agricultural soil) that contrasts with example #1's inversion. Also the only example whose medium is more specific than generic `soil`. |

## data_generation_set/

The pilot BioProject is uniform in analyte category (`metagenome`) and library shape — every record has one `has_input` biosample and one `has_output` data object. The only variation is which of three instruments was used.

| File | Source id | Instrument | Demonstrates |
|---|---|---|---|
| `01_metagenome_nucleotide_sequencing.json` | `nmdc:dgns-99-b2309df4` | `nmdc:inst-99-dca36248` (~89% of records) | The modal `NucleotideSequencing` record: metagenome analyte, single input biosample, single output data object, INSDC SRA experiment identifier. |
| `02_metagenome_alternate_instrument.json` | `nmdc:dgns-99-829d7843` | `nmdc:inst-99-815feee8` (~7% of records) | Same shape, different instrument — documents that this BioProject uses three distinct sequencers without scanning the full record set. |

## data_object_set/

The pilot has only one data-object type, so a single example suffices.

| File | Source id | Demonstrates |
|---|---|---|
| `01_metagenome_raw_reads.json` | `nmdc:dobj-99-1820725d` | `data_object_type="Metagenome Raw Reads"`, `data_category="instrument_data"`, NCBI SRA URL. **Caveat:** `md5_checksum` and `file_size_bytes` are null — NCBI's source-side metadata does not expose these for SRA runs, so they cannot be populated at this layer. They would need to be filled when files are actually retrieved/staged for ingest. |

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

If an example fails validation after a schema bump, **do not edit the record content** — pick a fresh representative from a current `results/ncbi_<ACC>_nmdc.json` output using a `jq` filter that captures the same axis (the criteria are in commit history / the original PR description).

## Adding a new example

1. Identify the axis of variation it covers that isn't already represented in this folder.
2. Pick a representative from a pipeline output via `jq`.
3. Extract with `jq '.<collection>[] | select(.id=="<id>")' results/<output>.json > examples/<collection>/NN_<short_label>.json` (next available number prefix).
4. Run the validation snippet.
5. Add a row to the table above with the new file's name, source id, and what it demonstrates.
