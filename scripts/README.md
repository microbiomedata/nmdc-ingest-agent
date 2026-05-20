# Scripts

Standalone tooling for the Microflora Danica (PRJNA1071982) env-triad curation.
These are **not** part of the `nmdc_ingest_agent` package — run them directly with
`python3`. They require `openpyxl` and (for ontology validation) `oaklib`/`runoak`;
both are in the `ontology` optional-dependency group (`uv sync --extra ontology`).

## The MFD env-triad pipeline

Run in order:

| # | Script | Builds / does | Reads | Writes |
|---|---|---|---|---|
| 1 | `build_mfd_habitat_table.py` | Normalizes per-project MFD metadata into one barcode-keyed habitat table | cmc-aau/mfd_metadata @ `b1b17d4` (downloaded to the gitignored `data/mfd_metadata_cache/`) | `data/mfd_habitat_per_sample.tsv`, `results/mfd_habitat_coverage_report.json` |
| 2 | `build_mfd_envo_crosswalk_l2.py` | Builds the Level-2/3 habitat → ENVO crosswalk: carry-forward from L1 + a runoak-validated `CURATION` table | `data/mfd_habitat_ontology.xlsx`, `data/mfd_envo_crosswalk_l1.tsv` | `data/mfd_envo_crosswalk_l2.tsv` |
| 3 | `apply_mfd_env_triad.py` | Applies the two-tier crosswalk to a curation run (MFDID → L2 primary, isolation_source → L1 fallback) | the two crosswalks + `data/mfd_habitat_per_sample.tsv` + `results/ncbi_PRJNA1071982_nmdc*.json` | `results/ncbi_PRJNA1071982_nmdc.json` and `…_curation_report.json` (in place) |

Step 1's habitat table and step 2's L2 crosswalk are committed to `data/`, so a normal
curation run only needs step 3. Re-run steps 1–2 to refresh against a new
cmc-aau/mfd_metadata commit or after editing the `CURATION` table.

See [`data/README.md`](../data/README.md) for the crosswalk schemas and the two-tier
design, and [`.claude/skills/mfd-project-vocabulary.md`](../.claude/skills/mfd-project-vocabulary.md)
for the resolution logic.
