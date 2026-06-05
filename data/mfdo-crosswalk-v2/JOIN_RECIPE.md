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

## 2. geo_loc_name (per biosample) — under discussion

`mfd_nominatim_geocode.tsv` provides reverse-geocoded locality strings derived from
coordinates. Enriching the submitter-provided `geo_loc_name` from this table is under
discussion (see [#34](https://github.com/microbiomedata/nmdc-ingest-agent/issues/34))
pending an NMDC policy decision on whether coordinate-derived locality strings may
supplement submitter-provided text fields. Do not apply this enrichment until that
question is settled.

## 3. ELS refinement for under-specified samples (optional) — reliable coordinates only

For samples whose crosswalk `env_local_scale` is a root-class placeholder (notably the
bare-soil reconciliation rows), refine from satellite land cover:

```
coord_key -> mfd_gee_landcover.tsv -> corine_label (preferred) / worldcover_label (fallback)
```

Prefer `corine_label` when non-empty (EU coverage, 44 classes). Fall back to
`worldcover_label` (global, 11 classes) for coordinates outside EU coverage.
Apply a CORINE->EnvO or WorldCover->EnvO lookup table (see
[#36](https://github.com/microbiomedata/nmdc-ingest-agent/issues/36)) and mark
provenance `from_corine` or `from_worldcover`. **Do not** override a leaf's already-specific
ELS with satellite data.

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
- To apply the crosswalk to a biosample TSV: `python3 apply_crosswalk.py biosamples.tsv`
  (see that script's `--help` for options). It implements the recipe above.
</content>
