# Annotating MFD biosamples from this crosswalk (lookup recipe)

The crosswalk and the two coordinate tables are kept small and reusable; you join them to the
stock MFD biosample table on demand. **No materialized per-biosample file is needed**, every
per-biosample value below is derivable by a join, so a precomputed file would only duplicate it.

Inputs:
- `mfdo_nmdc_crosswalk.tsv` — per-leaf NMDC slot mappings (this directory)
- `mfd_gee_landcover.tsv` — per-coordinate ESA WorldCover + CORINE land cover (this directory)
- `corine_envo_map.tsv`, `worldcover_envo_map.tsv` — land-cover class → ENVO ELS lookup (this directory)
- `mfd_nominatim_geocode.tsv` — per-coordinate Nominatim geocoding (this directory; use under discussion, see [#34](https://github.com/microbiomedata/nmdc-ingest-agent/issues/34))
- the stock biosample table: fetch with `mfd_db_to_tsv.py` (this directory), which reads
  `analysis/releases/<date>_mfd_db.xlsx` from [cmc-aau/mfd_metadata](https://github.com/cmc-aau/mfd_metadata)

## 1. Triad + non-triad slots (per biosample)

Join the biosample's five MFD habitat levels to `mfdo_nmdc_crosswalk.tsv`:

```
key = (mfd_sampletype, mfd_areatype, mfd_hab1, mfd_hab2, mfd_hab3)
```

Yields `env_broad_scale`, `env_local_scale`, `env_medium` (+ each `*_provenance`),
`cur_vegetation`, `cur_land_use`, `misc_param_json`.

**The join is total** — every one of the 10,875 biosamples matches exactly one crosswalk row.
The `row_type` column distinguishes them:
- `ontology_leaf` (279 rows): a genuine MFD ontology leaf.
- `biosample_reconciliation` (9 rows): biosample 5-tuples not in the ontology, added so the join
  is total. Examples: biogas biosamples (db types `Other`, ontology types `Water`),
  under-specified bare soil/sediment, and Superasterids crop types (Beetroot, Sugar beet, etc.)
  added to the db after the ontology was finalized. All reconciliation rows carry
  `biosample_reconciliation:*` provenance values.

## 2. geo_loc_name (per biosample) — under discussion

`mfd_nominatim_geocode.tsv` provides reverse-geocoded locality strings derived from
coordinates. Enriching the submitter-provided `geo_loc_name` from this table is under
discussion (see [#34](https://github.com/microbiomedata/nmdc-ingest-agent/issues/34))
pending an NMDC policy decision on whether coordinate-derived locality strings may
supplement submitter-provided text fields. Do not apply this enrichment until that
question is settled.

## 3. ELS refinement for under-specified samples (optional) — reliable coordinates only

Crosswalk rows with `env_local_scale = "environmental zone [ENVO:01000408]"` carry the
fallback placeholder used when no specific ELS is supportable from the habitat signal.
For these rows, refine from satellite land cover when `coords_reliable == 'Yes'`:

```
coord_key -> mfd_gee_landcover.tsv -> corine_label (preferred) / worldcover_label (fallback)
corine_label  -> corine_envo_map.tsv  -> env_local_scale  (EU coverage, 44 classes)
worldcover_label -> worldcover_envo_map.tsv -> env_local_scale  (global, 11 classes)
```

Only rows with `ols_verified=yes` in the map files are used. Provenance is set to
`from_corine` or `from_worldcover`. **Do not** override a leaf's already-specific ELS.

Note: the previous fallback was `astronomical body part [ENVO:01000813]`; it was
replaced by `environmental zone [ENVO:01000408]` per NCBI Import Squad decision 2026-06-04.
`apply_crosswalk.py` recognises both so it handles any crosswalk rows that still carry the
old value.

## coords_reliable

Projects **P04_3, P04_5, P06_3** plus 32 individually flagged samples have unreliable
coordinates (`coords_reliable == 'No'`). Do **not** derive `geo_loc_name` or GEE-based ELS for
those; fall back to the crosswalk's leaf-level values.

## Notes

- `coord_key` rounding is **4 decimal places** (the precision of the coordinate tables).
- `*_provenance` columns document which input drove each value and are stripped before NMDC
  submission.
- To rebuild the crosswalk: `python3 build_ontology_crosswalk.py` (fetches the two source xlsx
  from a pinned `cmc-aau/mfd_metadata` commit; `--ref` to override). Note: the 9 `biosample_reconciliation` rows for Superasterids crops are currently in the TSV only, not yet in the build script ([#43](https://github.com/microbiomedata/nmdc-ingest-agent/issues/43)).
- To extract biosamples from the MFD db xlsx: `python3 mfd_db_to_tsv.py --out biosamples.tsv`
- To apply the crosswalk: `python3 apply_crosswalk.py biosamples.tsv --out annotated.tsv`
  (both scripts accept `--help`).
</content>
