# NMDC → PHA4GE with linkml-map

A minimal, runnable demonstration that an NMDC-schema `Database` JSON (what `nmdc-ingest-ncbi`
produces) can be transformed into PHA4GE Wastewater Contextual Data Specification rows
(`WastewaterPathogenAgnostic`, template 4.4.4) with a declarative
[linkml-map](https://linkml.io/linkml-map/) TransformationSpecification.

```bash
./run.sh          # needs uv and network once (fetches the pinned PHA4GE schema)
```

| File | Role |
|---|---|
| `gssp_samples_nmdc.json` | input: three samples of the Global Sewage pilot (PRJEB13831) — a treatment plant, a river outlet and a sewer line — with their library / sequencing / data-object chain, the study, and the Instrument record. Placeholder ids (`-99-`). |
| `prepare_nmdc_samples_for_linkml_map.py` | re-serialises the Database into one table per class (`out/tables/`), the shape linkml-map joins over |
| `nmdc_to_pha4ge.transform.yaml` | **the mapping** — read this one |
| `run.sh` | prepare → `linkml-map map-data` → validate every row against the PHA4GE schema |

Output: `out/pha4ge_rows.json` and `out/pha4ge_rows.tsv` (one row per sequencing event, 24 PHA4GE slots).

## What the spec shows

- A graph (`Biosample` → `LibraryPreparation` → `ProcessedSample` → `NucleotideSequencing` → `DataObject`,
  plus `Study` and `Instrument`) flattened to one row with `joins:`.
- NMDC value objects unwrapped (`collection_date.has_raw_value`, `lat_lon.latitude`,
  `samp_taxon_id.term.id`), identifier prefixes stripped, enums re-coded to PHA4GE picklist strings
  with `case()`, required-but-unknowable fields filled from PHA4GE's null menu.
- Where the two models genuinely differ, the spec says so in comments: PHA4GE pins "Wastewater
  treatment plant" to ENVO:00002272 (NMDC uses ENVO:00002043), has no term for sewage (→ broader
  waste water), and codes sewers with a GENEPIO id — so CURIEs are mapped to template strings, not
  copied.

## Why `prepare_nmdc_samples_for_linkml_map.py` exists

linkml-map 0.5.x joins one hop from the primary table on scalar keys. NMDC stores references as
lists and the sample→sequencing link in the inverse direction, so the pre-pass flattens one-element
lists and adds `sequencing` / `data_object` / `instrument` foreign-key columns to each Biosample row
(declared to linkml-map via `source_schema_patches`). The Biosample table is written as YAML because
joined JSON tables are read through DuckDB as text and would lose nested values.

## Expected validation result

Every row validates against the PHA4GE schema except `read_mapping_software_name` /
`read_mapping_software_version`: PHA4GE requires them with no null option, and no INSDC or NMDC
ingest record carries them — they can only be filled from an analysis step (e.g. an NMDC
`ReadBasedTaxonomyAnalysis`).

## Scope

The GAZ-country and instrument `case()` tables cover this input; extend them (or generate them
from the PHA4GE enums) for another study. Once slot-level mappings land in nmdc-schema
(microbiomedata/nmdc-schema#3533), the `populated_from` half of this spec can be generated from the
schema; the value conversions stay hand-written.
