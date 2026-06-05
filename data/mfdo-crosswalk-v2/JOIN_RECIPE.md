# Annotating MFD biosamples from this crosswalk (lookup recipe)

The crosswalk and the two coordinate tables are kept small and reusable; you join them to the
stock MFD biosample table on demand. **No materialized per-biosample file is needed**, every
per-biosample value below is derivable by a join, so a precomputed file would only duplicate it.

Inputs:
- `mfdo_nmdc_crosswalk.tsv` — per-leaf NMDC slot mappings (this directory)
- `mfd_gee_landcover.tsv` — per-coordinate ESA WorldCover + CORINE land cover (this directory)
- `corine_envo_map.tsv`, `worldcover_envo_map.tsv` — land-cover class → ENVO ELS lookup (this directory)
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
- `biosample_reconciliation` (5 rows): biosample 5-tuples not in the ontology, added so the join
  is total. Examples: biogas biosamples (db types `Other`, ontology types `Water`) and
  under-specified bare soil/sediment. All carry `biosample_reconciliation:*` provenance values.
  Note: Superasterids crop types (Beetroot, Sugar beet, etc.) appear as `ontology_leaf` rows --
  they are in the MFDO xlsx even though they read as taxonomic rather than habitat classifications.

## 2. geo_loc_name (per biosample) — out of scope

`geo_loc_name` is not enriched here. All MFD biosamples carry bare "Denmark" from NCBI.
Deriving a finer locality from coordinates would change a submitter-provided field, so it
is parked pending an NMDC policy decision. No coordinate-to-locality table is included.

## 3. ELS refinement for under-specified samples (optional) — reliable coordinates only

Crosswalk rows with `env_local_scale = "environmental zone [ENVO:01000408]"` carry the
fallback placeholder used when no specific ELS is supportable from the habitat signal.
For these rows, refine from satellite land cover when `coords_reliable == 'Yes'`:

```
coord_key -> mfd_gee_landcover.tsv -> corine_label (preferred) / worldcover_label (fallback)
corine_label  -> corine_envo_map.tsv  -> env_local_scale  (EU coverage, 44 classes)
worldcover_label -> worldcover_envo_map.tsv -> env_local_scale  (global, 11 classes)
```

Only rows with `ols_verified=yes` in the map files are used. **Do not** override a leaf's
already-specific ELS. `apply_crosswalk.py` notes the refinement source internally for its
run summary; the committed `mfd_biosamples_annotated.tsv` carries the refined
`env_local_scale` value itself, without a separate provenance column (all `*_provenance`
columns are stripped before output).

Note: the previous fallback was `astronomical body part [ENVO:01000813]`; it was
replaced by `environmental zone [ENVO:01000408]` per NCBI Import Squad decision 2026-06-04.
`apply_crosswalk.py` recognises both so it handles any crosswalk rows that still carry the
old value.

## coords_reliable

Projects **P04_3, P04_5, P06_3** plus 32 individually flagged samples have unreliable
coordinates (`coords_reliable == 'No'`). Do **not** apply GEE-based ELS refinement for
those; fall back to the crosswalk's leaf-level values.

## Notes

- `coord_key` rounding is **4 decimal places** (the precision of the coordinate tables).
- `*_provenance` columns document which input drove each value and are stripped before NMDC
  submission.
- `underspecified_slots` flags any triad slot left at a coarse root value (bare `biome`,
  `environmental zone`, or `environmental material`). In the crosswalk it reflects the leaf-level
  value; in the joined output (`mfd_biosamples_annotated.tsv`) it is recomputed on the final
  post-GEE values, so a refined `env_local_scale` correctly drops out of the flag.
- The crosswalk is sorted by `n_samples` descending (highest-impact mappings first).
- To rebuild the crosswalk: `python3 build_ontology_crosswalk.py` (fetches the two source xlsx
  from a pinned `cmc-aau/mfd_metadata` commit; `--ref` to override).
- To regenerate the joined per-biosample output:
  `python3 mfd_db_to_tsv.py --out biosamples.tsv` then
  `python3 apply_crosswalk.py biosamples.tsv --out mfd_biosamples_annotated.tsv`
  (both scripts accept `--help`).
</content>
