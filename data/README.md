# Data files

Computable data files consumed by the skills under [`.claude/skills/`](../.claude/skills/) and by downstream tooling. These are deliberate curation artifacts, **not** outputs of the deterministic pipeline (`nmdc-ingest-ncbi`). Each file is intended to be:

- **Single source of truth** — referenced from skills rather than duplicated inline.
- **Shareable** — easy to cite, import into other curation projects, or load with standard tools (`pandas.read_csv`, `csv.DictReader`, `jq` after JSON conversion, etc.).
- **Validatable** — every ontology CURIE in any file here passes `runoak info` + `runoak ancestors -p i` against its slot's anchor class.

## Files

| Path | Purpose |
|---|---|
| [`mfdo-crosswalk-v2/`](mfdo-crosswalk-v2/) | MFDO (Microflora Danica Ontology) → NMDC crosswalk (v2). Maps all 279 MFD habitat-ontology leaves to NMDC Biosample env-triad slots and ships a per-biosample deliverable, [`mfd_biosamples_annotated.tsv`](mfdo-crosswalk-v2/mfd_biosamples_annotated.tsv), keyed by `fieldsample_barcode` (= NCBI `samp_name`/`MFDID`). The NCBI ingest resolves the MFD env-triad **in code** from this file (`sources/ncbi/mfd.py`), so MFD biosamples arrive `resolved_at_pipeline`. See [`mfdo-crosswalk-v2/README.md`](mfdo-crosswalk-v2/README.md) and [`JOIN_RECIPE.md`](mfdo-crosswalk-v2/JOIN_RECIPE.md) for schema, provenance, and regeneration. Replaces the former 25-row `mfd_envo_crosswalk.tsv`. |

## Conventions

- **`ENVO:00000000` is the deterministic pipeline's refuse sentinel** — `translate.py` emits it for any env-triad slot it cannot resolve, flagging the slot for curation (`nmdc-env-triad.md` §1b inference). The v2 crosswalk carries no sentinels: where no specific ENVO term is supportable it uses the `environmental zone [ENVO:01000408]` ELS fallback instead (see `mfdo-crosswalk-v2/README.md`).
- **CURIE format** — `^ENVO:\d{8}$` for every ENVO term (regex-checkable). Other ontologies (NCBITaxon, etc.) follow `<prefix>:<id>` where `<prefix>` matches the ontology's canonical short form.
- **Integer counts** — when a column reports record counts (e.g. `count_observed`), the value is the integer count from a named source dataset. The file or top-level README documents which dataset.
- **Sort order** — TSVs are sorted by their dominant count column descending so the highest-impact rows appear first.

## Maintainer rules

1. **No CURIEs from memory.** Every ENVO CURIE must come from a `runoak search` lookup that you've validated with `runoak info <CURIE>` (exists, label correct, not deprecated) and `runoak ancestors -p i <CURIE>` (the slot's anchor class appears in the ancestor list). This mirrors `nmdc-curation-rules.md` Rule 6.
2. **Regenerate, don't hand-edit derived TSVs.** The v2 crosswalk and its annotated per-biosample file are built by the scripts in `mfdo-crosswalk-v2/` (`build_ontology_crosswalk.py`, then `mfd_db_to_tsv.py` + `apply_crosswalk.py`). Change the curation logic there and rebuild; see that directory's README. Skills and quoted examples are refreshed from the regenerated files, not the other way around.
3. **Schema bumps require re-validation.** When ENVO publishes a new release, re-run the validators on every CURIE. Deprecations and label changes become bugs to fix here.
4. **No tabs in field values.** TSVs are unforgiving — keep notes and labels free of tab characters. Use spaces.

## Loading examples

```python
# Python
import csv, pathlib
with pathlib.Path("data/mfdo-crosswalk-v2/mfd_biosamples_annotated.tsv").open() as f:
    rows = list(csv.DictReader(f, delimiter="\t"))
# rows[0] is a dict keyed by column name; key on `fieldsample_barcode`
```

```bash
# shell — look up one biosample by its MFD barcode
awk -F'\t' 'NR==1 || $1=="MFD00001"' data/mfdo-crosswalk-v2/mfd_biosamples_annotated.tsv
```

```python
# pandas
import pandas as pd
df = pd.read_csv("data/mfdo-crosswalk-v2/mfd_biosamples_annotated.tsv", sep="\t")
```
