# Data files

Computable data files consumed by the skills under [`.claude/skills/`](../.claude/skills/) and by downstream tooling. These are deliberate curation artifacts, **not** outputs of the deterministic pipeline (`nmdc-ingest-ncbi`). Each file is intended to be:

- **Single source of truth** — referenced from skills rather than duplicated inline.
- **Shareable** — easy to cite, import into other curation projects, or load with standard tools (`pandas.read_csv`, `csv.DictReader`, `jq` after JSON conversion, etc.).
- **Validatable** — every ontology CURIE in any file here passes `runoak info` + `runoak ancestors -p i` against its slot's anchor class.

This directory holds only **reusable, cross-project** computable data. Project-specific
mapping artifacts live with their project instead — e.g. the MicroFlora Danica MFDO→NMDC
crosswalk is at [`examples/microflora-danica/crosswalk/`](../examples/microflora-danica/crosswalk/),
and the NCBI ingest loads it only when pointed there via `--env-triad-crosswalk`.

## Files

| Path | Purpose |
|---|---|
| [`land-cover/`](land-cover/) | Reusable land-cover → ENVO env_local_scale lookups: `corine_envo_map.tsv` (44 CORINE Level-3 classes) and `worldcover_envo_map.tsv` (11 ESA WorldCover 2020 classes). Not tied to any project — any ingest that has coordinates + land-cover can reuse them. Each ENVO term is `ols_verified` against its slot's anchor class. Authored/validated via the `nmdc-ontology-mapping` skill. |

## Conventions

- **`ENVO:00000000` is the deterministic pipeline's refuse sentinel** — `translate.py` emits it for any env-triad slot it cannot resolve, flagging the slot for curation (`nmdc-env-triad` §1b inference).
- **CURIE format** — `^ENVO:\d{8}$` for every ENVO term (regex-checkable). Other ontologies (NCBITaxon, etc.) follow `<prefix>:<id>` where `<prefix>` matches the ontology's canonical short form.
- **Integer counts** — when a column reports record counts (e.g. `count_observed`), the value is the integer count from a named source dataset. The file or top-level README documents which dataset.
- **Sort order** — TSVs are sorted by their dominant count column descending so the highest-impact rows appear first.

## Maintainer rules

1. **No CURIEs from memory.** Every ENVO CURIE must come from a `runoak search` lookup that you've validated with `runoak info <CURIE>` (exists, label correct, not deprecated) and `runoak ancestors -p i <CURIE>` (the slot's anchor class appears in the ancestor list). This mirrors `nmdc-curation-rules.md` Rule 6.
2. **Regenerate/verify, don't hand-edit CURIEs.** The land-cover maps' `ols_verified` column is set by `generate_els_allowlist.py` (in the `nmdc-ontology-mapping` skill's `scripts/`); re-run it after an ENVO release rather than editing CURIEs by hand. Project-specific derived TSVs (e.g. MFD's annotated crosswalk) are rebuilt by that project's own scripts — see [`examples/microflora-danica/crosswalk/README.md`](../examples/microflora-danica/crosswalk/README.md).
3. **Schema bumps require re-validation.** When ENVO publishes a new release, re-run the validators on every CURIE. Deprecations and label changes become bugs to fix here.
4. **No tabs in field values.** TSVs are unforgiving — keep notes and labels free of tab characters. Use spaces.

## Loading examples

```python
# Python
import csv, pathlib
with pathlib.Path("data/land-cover/corine_envo_map.tsv").open() as f:
    rows = list(csv.DictReader(f, delimiter="\t"))
# rows[0] is a dict keyed by column name (corine_code, corine_label, env_local_scale, ...)
```

```bash
# shell — look up one CORINE class's ENVO ELS term
awk -F'\t' 'NR==1 || $1=="111"' data/land-cover/corine_envo_map.tsv
```

```python
# pandas
import pandas as pd
df = pd.read_csv("data/land-cover/worldcover_envo_map.tsv", sep="\t")
```
