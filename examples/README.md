# NMDC record examples

Reference JSON files showing the shapes of records this repo produces for each NMDC `Database` collection. Examples are organised **by source project** so that records from different BioProjects (with different MIxS packages, env-triad patterns, MFD-style or other custom ontologies, etc.) can coexist without conflating their per-collection variation.

## Layout

```
examples/
├── README.md                # this file — project index
└── <project>/
    ├── README.md            # project-specific framing, source links, per-collection tables
    ├── study_set/
    ├── biosample_set/
    ├── data_generation_set/
    └── data_object_set/
```

Each project subfolder is self-contained: extracted-verbatim single-record JSON files (no hand-edits), a README explaining the project's framing and what each example demonstrates, and a validation snippet scoped to that subfolder.

## Projects

| Folder | Source | Records |
|---|---|---|
| [`microflora-danica/`](microflora-danica/) | NCBI BioProject [PRJNA1071982](https://www.ncbi.nlm.nih.gov/bioproject/?term=PRJNA1071982) — *MicroFlora Danica* ([Sereika et al., Nature 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC12823411/)) | 1 study · 8 biosamples · 2 data_generations · 1 data_object |

## Conventions

- **Projects are named by human-readable label**, not by accession (e.g. `microflora-danica/`, not `PRJNA1071982/`). When a project name overlaps with another source, suffix with the source (e.g. `microflora-danica-ncbi/` vs `microflora-danica-gold/`).
- **Files are named `NN_<short-label>.json`** within each collection — numeric prefixes give a canonical sort and let a reader skim the most representative cases first.
- **Records are extracted verbatim** from real pipeline output. No hand-edits. If a record can't be regenerated under current pipeline logic, the README documents why.
- **Placeholder NMDC IDs** (`-99-` shoulder) — real ingest requires `--mint-real-ids`. Ids are randomly minted each run, so regenerating produces different ids matching the same criteria.

## Adding a new project

1. Create `examples/<project>/` with the four collection subfolders (`study_set/`, `biosample_set/`, `data_generation_set/`, `data_object_set/`) and a `README.md` describing the source.
2. Extract representative records via `jq` from the ingest output.
3. Validate every file (snippet below).
4. Add a row to the **Projects** table above linking to the new subfolder.

## Validation snippet (all projects)

```bash
uv run python -c "
from nmdc_schema import nmdc
from linkml_runtime.loaders import json_loader
import pathlib
target = {'study_set': nmdc.Study,
          'biosample_set': nmdc.Biosample,
          'data_generation_set': nmdc.NucleotideSequencing,
          'data_object_set': nmdc.DataObject}
for project_dir in sorted(pathlib.Path('examples').iterdir()):
    if not project_dir.is_dir():
        continue
    for col, cls in target.items():
        for p in sorted((project_dir / col).glob('*.json')):
            json_loader.loads(p.read_text(), target_class=cls)
            print(f'OK  {p}')
"
```

For project-scoped validation, each project's own README has a snippet limited to that subfolder.
