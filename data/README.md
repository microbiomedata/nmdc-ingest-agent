# Data files

Computable data files consumed by the skills under [`.claude/skills/`](../.claude/skills/) and by downstream tooling. These are deliberate curation artifacts, **not** outputs of the deterministic pipeline (`nmdc-ingest-ncbi`). Each file is intended to be:

- **Single source of truth** — referenced from skills rather than duplicated inline.
- **Shareable** — easy to cite, import into other curation projects, or load with standard tools (`pandas.read_csv`, `csv.DictReader`, `jq` after JSON conversion, etc.).
- **Validatable** — every ontology CURIE in any file here passes `runoak info` + `runoak ancestors -p i` against its slot's anchor class.

## Files

| File | Rows | Cols | Purpose |
|---|---:|---:|---|
| [`mfd_envo_crosswalk.tsv`](mfd_envo_crosswalk.tsv) | 25 | 10 | MFDO (Microflora Danica Ontology) → ENVO crosswalk. Each row maps a `(sample_type, area_mfdo1_label)` tuple to candidate ENVO CURIEs for the three MIxS env-triad slots. Consumed by [`mfd-project-vocabulary.md`](../.claude/skills/mfd-project-vocabulary.md). |

## Conventions

- **`ENVO:00000000` is the refuse sentinel** — any `*_curie` column with this value indicates "no ENVO term exists under the slot's anchor class for this row; the agent should leave the sentinel and proceed to `nmdc-env-triad.md` §1b inference for that slot." Mirrors the deterministic pipeline's sentinel convention in `translate.py`. The corresponding `*_label` column is empty.
- **CURIE format** — `^ENVO:\d{8}$` for every ENVO term (regex-checkable). Other ontologies (NCBITaxon, etc.) follow `<prefix>:<id>` where `<prefix>` matches the ontology's canonical short form.
- **Integer counts** — when a column reports record counts (e.g. `count_observed`), the value is the integer count from a named source dataset. The file or top-level README documents which dataset.
- **Sort order** — TSVs are sorted by their dominant count column descending so the highest-impact rows appear first.

## Maintainer rules

1. **No CURIEs from memory.** Every ENVO CURIE must come from a `runoak search` lookup that you've validated with `runoak info <CURIE>` (exists, label correct, not deprecated) and `runoak ancestors -p i <CURIE>` (the slot's anchor class appears in the ancestor list). This mirrors `nmdc-curation-rules.md` Rule 6.
2. **Edits go to the TSV first.** If a skill references the TSV, the TSV is the source of truth — update the TSV and let the skill's quoted examples be refreshed from it, not the other way around.
3. **Schema bumps require re-validation.** When ENVO publishes a new release, re-run the validators on every CURIE. Deprecations and label changes become bugs to fix here.
4. **No tabs in field values.** TSVs are unforgiving — keep notes and labels free of tab characters. Use spaces.

## Loading examples

```python
# Python
import csv, pathlib
with pathlib.Path("data/mfd_envo_crosswalk.tsv").open() as f:
    rows = list(csv.DictReader(f, delimiter="\t"))
# rows[0] is a dict keyed by column name
```

```bash
# shell — pick rows for one Sample Type
awk -F'\t' 'NR==1 || $1=="Soil"' data/mfd_envo_crosswalk.tsv
```

```python
# pandas
import pandas as pd
df = pd.read_csv("data/mfd_envo_crosswalk.tsv", sep="\t")
```
