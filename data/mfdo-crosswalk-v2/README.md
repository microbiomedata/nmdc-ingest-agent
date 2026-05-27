# MFDO-to-NMDC Biosample Slot Crosswalk (v2)

Maps all 279 Microflora Danica (MFD) habitat ontology leaves to nmdc-schema Biosample slots, covering 10,875 biosamples from PRJNA1071982.

Addresses [#31](https://github.com/microbiomedata/nmdc-ingest-agent/issues/31) (env triad curation) and [#32](https://github.com/microbiomedata/nmdc-ingest-agent/issues/32) (non-triad slot enrichment).

## Primary file

**`mfdo_nmdc_crosswalk.tsv`**: one row per MFDO ontology leaf (279 rows).

### nmdc-schema Biosample slots

| Slot | Coverage | Placeholders | Validated against |
|---|---|---|---|
| env_broad_scale | 279/279 | 0 | ControlledIdentifiedTermValue; ENVO CURIEs verified via OLS4 |
| env_local_scale | 278/279 | 1 (unused leaf, 0 biosamples) | ControlledIdentifiedTermValue; all CURIEs in ELS allow-list |
| env_medium | 277/279 | 2 (unused leaves, 0 biosamples) | ControlledIdentifiedTermValue; ENVO CURIEs verified via OLS4 |
| cur_vegetation | 164/279 | n/a | TextValue; MFDO hab3/hab2 value as-is |
| cur_land_use | 182/279 | n/a | CurLandUseEnum; all values valid |
| misc_param | 60/279 | n/a | PropertyAssertion JSON |

Zero placeholders affect any of the 10,875 biosamples.

### ELS allow-list

`els_v5.txt`: 1,533 ENVO classes. Subclasses of (astronomical body part + vegetation layer + environmental zone + terrestrial ecosystem + wetland ecosystem) minus (biomes + materials).

### Provenance columns

Columns ending in `_provenance` record which MFDO levels determined each mapping:
- `from_mfdo:sampletype` -- sampletype level alone
- `from_mfdo:sampletype+areatype` -- sampletype + areatype combination
- `from_mfdo:areatype+hab1` -- areatype + hab1
- `from_mfdo:hab1`, `from_mfdo:hab2`, `from_mfdo:hab3` -- specific MFDO level
- `from_mfdo:hab3+gee_corine` -- hab3 confirmed by CORINE satellite land cover (>=70% agreement)
- `envo_root_class` -- no specific ENVO term available

These are documentation columns, not nmdc-schema Biosample slots. They would be stripped before NMDC submission.

### geo_loc_name

Not in the crosswalk. All MFD NCBI biosamples have bare "Denmark" as geo_loc_name. Nominatim reverse geocoding has produced per-coordinate locality values (e.g., "Danmark: Region Sjaelland, Gedser") but the provenance model for enriching submitter-provided values is under discussion.

## Supporting files

| File | Description |
|---|---|
| `mfdo_misc_param_mappings.tsv` | misc_param PropertyAssertion mappings (55 rows, stringified JSON) |
| `mfdo_decomposed.json` | Structural decomposition of 223 MFDO facet values (Ollama qwen2.5:14b) |
| `mfd_gee_landcover.tsv` | ESA WorldCover + CORINE land cover at all 7,602 unique coordinates |
| `els_v5.txt` | Expanded ELS allow-list (1,533 ENVO classes) |

## Methodology

1. Per-facet-value ENVO mapping via OLS4 embedding + lexical search
2. Structural decomposition of composite values via local LLM
3. Composed-expression context rules using full (sampletype, areatype, hab1, hab2, hab3) hierarchy
4. Adversarial self-review: found and fixed 1,188 samples with ELS terms not in allow-list
5. GEE satellite validation at all 7,602 coordinates; 3 refinements applied where CORINE >= 70%
6. OSM Overpass validation at 1,011 coordinates; confirmed landscape mosaic pattern
7. Non-triad routing: cur_vegetation (MFDO as-is), cur_land_use (CurLandUseEnum), misc_param (PropertyAssertion JSON)

## Comparison with v1 crosswalk

| Metric | v1 (data/mfd_envo_crosswalk.tsv) | v2 (this directory) |
|---|---|---|
| EBS sentinels | 26 | 0 |
| ELS sentinels | 44 | 1 (0 biosamples) |
| EM sentinels | 9 | 2 (0 biosamples) |
| Granularity | 26 L1 rows | 279 leaves, hab2/hab3 resolution |
| Non-triad slots | none | cur_vegetation, cur_land_use, misc_param |
| Satellite validation | none | GEE WorldCover + CORINE at all coordinates |

## Related

- [#31](https://github.com/microbiomedata/nmdc-ingest-agent/issues/31): env triad curation
- [#32](https://github.com/microbiomedata/nmdc-ingest-agent/issues/32): non-triad slot enrichment
- [nmdc-schema#3105](https://github.com/microbiomedata/nmdc-schema/issues/3105): qualitative pollution values
- [envo#1658](https://github.com/EnvironmentOntology/envo/issues/1658): NTR wetland biome
