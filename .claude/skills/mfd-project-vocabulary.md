---
name: mfd-project-vocabulary
description: How the MicroFlora Danica (MFD) env-triad is resolved. The NCBI ingest now resolves it deterministically in code from the v2 MFDO→NMDC crosswalk; this skill is a pointer plus a manual-fallback recipe for other sources or ad-hoc curation.
---

# Microflora Danica habitat ontology (MFDO) → NMDC env triad

The MicroFlora Danica project ([Sereika et al., Nature 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC12823411/))
sampled ~10,875 biosamples across Denmark using a custom 5-level habitat classification (MFDO).
NCBI carries only a coarse `isolation_source` string (e.g. `"Soil from Natural Forests"`); the full
habitat hierarchy and its ENVO mapping live in the **v2 crosswalk** at
[`data/mfdo-crosswalk-v2/`](../../data/mfdo-crosswalk-v2/).

## How MFD biosamples are resolved (NCBI ingest)

**This is automatic — no agent action is required.** `uv run nmdc-ingest-ncbi` resolves the MFD
env-triad in code:

- `src/nmdc_ingest_agent/sources/ncbi/mfd.py` (`MfdEnvTriadResolver`) loads the per-biosample
  deliverable [`data/mfdo-crosswalk-v2/mfd_biosamples_annotated.tsv`](../../data/mfdo-crosswalk-v2/mfd_biosamples_annotated.tsv),
  keyed by `fieldsample_barcode` (= NCBI `samp_name` / the `MFDID` attribute, e.g. `MFD00001`).
- For each matched biosample it commits `env_broad_scale`, `env_local_scale`, and `env_medium`
  directly, so the curation report records `outcome: "resolved_at_pipeline"` for those slots —
  there are no `ENVO:00000000` sentinels left for the env-triad on MFD biosamples.

The v2 mapping is richer than NCBI's `isolation_source`: it draws on all five MFD habitat levels
plus Natura 2000 / EUNIS / EMPO signals and GEE land-cover refinement, all CURIEs OLS-verified. It
carries no refuse sentinels — where no specific ENVO term is supportable it uses the
`environmental zone [ENVO:01000408]` ELS fallback. See
[`mfdo-crosswalk-v2/README.md`](../../data/mfdo-crosswalk-v2/README.md) for derivation and
[`JOIN_RECIPE.md`](../../data/mfdo-crosswalk-v2/JOIN_RECIPE.md) for the join.

Because the env-triad arrives pre-resolved, the `nmdc-env-triad.md` §1a/§1b manual curation pass
does **not** apply to MFD biosamples from the NCBI source. It still applies to non-MFD biosamples
and other sources.

## Manual / other-source fallback

When you need the mapping outside the pipeline — a different source that reuses MFDO, ad-hoc
curation, or a biosample missing from the annotated file — join by the MFD barcode:

```python
import csv, pathlib

path = pathlib.Path("data/mfdo-crosswalk-v2/mfd_biosamples_annotated.tsv")
with path.open(newline="") as f:
    by_barcode = {r["fieldsample_barcode"]: r for r in csv.DictReader(f, delimiter="\t")}

row = by_barcode["MFD00001"]
# row["env_broad_scale"] == "temperate broadleaf forest biome [ENVO:01000202]"
```

Each triad cell is a combined `"<label> [<CURIE>]"` string; split on the trailing `[...]` to get the
ENVO CURIE and its official label. Per `nmdc-curation-rules.md` Rule 5, the official label belongs in
`term.name` (the NCBI env-triad fields are empty, so there is no `has_raw_value` to preserve).

If a biosample has no row in the annotated file, leave the slot's `ENVO:00000000` sentinel and follow
`nmdc-env-triad.md` §1b inference.

## Maintaining the crosswalk

All edits go to the scripts in [`data/mfdo-crosswalk-v2/`](../../data/mfdo-crosswalk-v2/), not to the
TSVs by hand. Rebuild the crosswalk with `build_ontology_crosswalk.py`, then regenerate the
per-biosample file with `mfd_db_to_tsv.py` + `apply_crosswalk.py`. See that directory's `README.md`
for the build steps, the ELS allow-list, and re-validation after an ENVO release.
