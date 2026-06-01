# Annotating MFD biosamples from this crosswalk (lookup recipe)

The crosswalk and the two coordinate tables are kept small and reusable; you join them to the
stock MFD biosample table on demand. **No materialized per-biosample file is needed**, every
per-biosample value below is derivable by a join, so a precomputed file would only duplicate it.

Inputs:
- `mfdo_nmdc_crosswalk.tsv` — per-leaf NMDC slot mappings (this directory)
- `mfd_gee_landcover.tsv`, `mfd_nominatim_geocode.tsv` — per-coordinate enrichments (this directory)
- the stock biosample table: `analysis/releases/<date>_mfd_db.xlsx` in
  [cmc-aau/mfd_metadata](https://github.com/cmc-aau/mfd_metadata) (one row per biosample)

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
- `biosample_reconciliation` (5 rows): biosample 5-tuples that are not ontology leaves, added so
  the join is total. These are flagged in `row_type` **and** in the `*_provenance` columns
  (`biosample_reconciliation:sampletype` for biogas, which the db types `Other` vs the ontology's
  `Water`; `biosample_reconciliation:floor` for under-specified bare soil/sediment).

## 2. geo_loc_name (per biosample) — reliable coordinates only

Only when `coords_reliable == 'Yes'`:

```
coord_key = f"{round(latitude,4)},{round(longitude,4)}"     # e.g. "55.6771,9.2778"
join coord_key -> mfd_nominatim_geocode.tsv
```

Gives `country / state / municipality / town / display_name`; compose an INSDC-style
`geo_loc_name` (e.g. `Denmark: Region Sjælland, Gedser`). All MFD biosamples carry bare
"Denmark" from NCBI; this refines it.

## 3. ELS refinement for under-specified samples (optional) — reliable coordinates only

For samples whose crosswalk `env_local_scale` is coarse/placeholder (notably the bare-soil
reconciliation rows, where `env_local_scale = astronomical body part`), refine from satellite
land cover:

```
coord_key -> mfd_gee_landcover.tsv -> worldcover_label / corine_label
```

Apply where it adds specificity and mark provenance `from_gee`. **Do not** override a leaf's
already-specific ELS with satellite data.

## coords_reliable

Projects **P04_3, P04_5, P06_3** plus 32 individually flagged samples have unreliable
coordinates (`coords_reliable == 'No'`). Do **not** derive `geo_loc_name` or GEE-based ELS for
those; fall back to the crosswalk's leaf-level values.

## Notes

- `coord_key` rounding is **4 decimal places** (the precision of the coordinate tables).
- `*_provenance` columns document which input drove each value and are stripped before NMDC
  submission.
- To rebuild the crosswalk: `python3 build_ontology_crosswalk.py` (fetches the two source xlsx
  from a pinned `cmc-aau/mfd_metadata` commit; `--ref` to override).
</content>
