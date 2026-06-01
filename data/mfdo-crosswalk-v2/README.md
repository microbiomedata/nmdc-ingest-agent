# MFDO-to-NMDC Biosample Slot Crosswalk (v2)

Maps all 279 Microflora Danica (MFD) habitat ontology leaves to nmdc-schema Biosample slots, covering the ~10,875 environmental biosamples from PRJNA1071982.

Addresses [#31](https://github.com/microbiomedata/nmdc-ingest-agent/issues/31) (env triad curation) and [#32](https://github.com/microbiomedata/nmdc-ingest-agent/issues/32) (non-triad slot enrichment).

## Files

- **`mfdo_nmdc_crosswalk.tsv`**: primary output, one row per MFDO ontology leaf (279 rows).
- **`build_ontology_crosswalk.py`**: self-contained, reproducible builder (Python 3 standard library only).

## Reproducing the crosswalk

```bash
python3 build_ontology_crosswalk.py            # default: pinned cmc-aau/mfd_metadata commit
python3 build_ontology_crosswalk.py --ref main # latest upstream release
```

The builder fetches its two source spreadsheets from the public [cmc-aau/mfd_metadata](https://github.com/cmc-aau/mfd_metadata) repo (`data/ontology/latest_mfd-habitat-ontology.xlsx` and `analysis/releases/2025-05-28_mfd_db.xlsx`), pinned to a commit for reproducibility (falls back to same-named files in the working directory if offline). All mapping rules and curated term lists are inlined in the script, so no other inputs are required.

## nmdc-schema Biosample slots

| Slot | Coverage | Validated against |
|---|---|---|
| env_broad_scale | 279/279 | ControlledIdentifiedTermValue; ENVO CURIEs verified via OLS |
| env_local_scale | 278/279 specific (1 root fallback, 0 biosamples) | ControlledIdentifiedTermValue; all CURIEs in the ELS allow-list |
| env_medium | 279/279 | ControlledIdentifiedTermValue; ENVO CURIEs verified via OLS |
| cur_vegetation | 164/279 | TextValue; MFDO hab3/hab2 value as-is |
| cur_land_use | 181/279 | MIxS cur_land_use controlled list; all values valid |
| misc_param | 60/279 | PropertyAssertion JSON |

All **84 distinct env-triad CURIEs** are verified in ENVO via OLS (present, non-obsolete, exact label match).

## How mappings are derived

The leaf is identified by the five MFD levels (sampletype, areatype, hab1–hab3), but mappings draw on **all** available leaf-level signal: the five levels and their substrings plus the ontology's `Natura2000`, `EUNIS`, and `EMPO` columns.

- **Natura2000 (Annex I) codes → specific ELS.** Full Annex I habitat names (e.g. 3150 "Natural eutrophic lakes", 7220 "Petrifying springs with tufa formation") are matched to ENVO via an embedding index built over ENVO **labels + definitions + synonyms**, then each chosen CURIE is OLS-verified and confirmed in the ELS allow-list.
- **EMPO → env_medium / salinity** (e.g. saline free water → sea water).
- **Composed-context rules** over the full level hierarchy for specificity; GEE WorldCover/CORINE refinements applied where satellite agreement ≥ 70%.

### Provenance columns

Columns ending in `_provenance` record which input determined each mapping (`from_natura2000`, `from_empo`, `from_mfdo:hab1/2/3`, `from_mfdo:hab3+gee_corine`, `envo_root_class`, …). They are documentation, not nmdc-schema slots, and are stripped before NMDC submission.

### ELS allow-list

1,533 ENVO classes: subclasses of (astronomical body part + vegetation layer + environmental zone + terrestrial ecosystem + wetland ecosystem) minus (biomes + materials). Note: `wetland ecosystem` [ENVO:01001209] is added as a separate root (it is not under `terrestrial ecosystem` in ENVO) to access fen, peatland, sphagnum bog, raised mire, and marsh. See [envo#1659](https://github.com/EnvironmentOntology/envo/issues/1659).

### geo_loc_name

Not in the crosswalk. All MFD NCBI biosamples carry bare "Denmark". Per-coordinate locality enrichment (Nominatim) is a per-biosample step under discussion, not a per-leaf value.

## Data-quality changes in this revision

- **OOXML parse fix.** The reader now places cells by their column reference (Excel omits empty cells from sheet XML); a prior positional parser had shifted hab2/hab3 labels. This corrected the labels and raised biosamples correctly attributed to leaves from 8,696 to **10,759** of 10,875.
- **ELS/EBS/EM refinements** using the multi-system signal above (forest types; grasslands → temperate grassland; humid meadows → wet meadow ecosystem; seabed substrate → sea grass bed / rocky reef; lake trophic state; raised mire; Annex-I-driven eutrophic lake, lagoon, mineral spring, sea cave).
- **Over-assertions removed / realigned** (systematic audit across all leaves). A few leaves were **deliberately backed off to more-general terms** where the prior specific term was unsupported by the inputs — a slight specificity decrease but an accuracy increase:
  - rocky-habitat EBS `temperate shrubland biome` → `terrestrial biome` (23 biosamples)
  - rainwater basins ELS `pond` → `water body` (453)
  - subterranean urban soil ELS `tunnel` → `subsurface landform` (155)
  - non-park urban greenspace ELS `park` → `area of developed open space` (83)
  - petrifying springs EM `peat soil` → `soil` (80; sampletype is Soil, not the deposited tufa)
  - `harbour` is now asserted only where the label says so.

## Comparison with v1 crosswalk

| Metric | v1 (`data/mfd_envo_crosswalk.tsv`) | v2 (this directory) |
|---|---|---|
| EBS sentinels | 26 | 0 |
| ELS sentinels | 44 | 1 (0 biosamples) |
| EM sentinels | 9 | 0 |
| Granularity | 26 L1 rows | 279 leaves, hab2/hab3 resolution |
| Non-triad slots | none | cur_vegetation, cur_land_use, misc_param |
| Validation | runoak | OLS + GEE + OSM; all triad CURIEs OLS-verified |

## Related

- [#31](https://github.com/microbiomedata/nmdc-ingest-agent/issues/31): env triad curation
- [#32](https://github.com/microbiomedata/nmdc-ingest-agent/issues/32): non-triad slot enrichment
- [nmdc-schema#3105](https://github.com/microbiomedata/nmdc-schema/issues/3105): qualitative pollution values
- [cmc-aau/mfd_metadata](https://github.com/cmc-aau/mfd_metadata): upstream MFD ontology + metadata
</content>
