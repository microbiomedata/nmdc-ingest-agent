# nmdc-ingest-agent

AI-agent-assisted workflows for translating external metadata sources into NMDC-schema-compliant JSON.

## What this is

A different approach to ingesting external metadata into NMDC. Rather than writing bespoke Dagster-orchestrated ETL pipelines in [nmdc-runtime](https://github.com/microbiomedata/nmdc-runtime), this repo pairs:

- **Python helper/harness methods** that do the deterministic, mechanical work — calling external APIs (e.g. NCBI E-utilities), traversing source-side links (e.g. BioProject → BioSample / SRA), assembling the `nmdc.Database` object, and running schema + deterministic integrity checks on the result.
- **Claude Code skills** (checked-in skill directories at `.claude/skills/<name>/SKILL.md`) that guide an AI agent through the harmonization a curator has historically done: parsing and normalizing free-text field values, inferring implicit values from study-level descriptions, and mapping to the right ontology or database fields (e.g. ENVO terms for the MIxS env triad, NCBITaxon for host taxa). Ambiguous cases are flagged for human follow-up rather than silently guessed. Skills are **general-purpose and composable** — a per-source skill (`ncbi-to-nmdc`) hands off to shared curation skills (`nmdc-curation-rules`, `nmdc-env-triad`, `nmdc-taxon-resolution`, `nmdc-target-gene`, `nmdc-schema-reference`), builds validated SSSOM mappings via `nmdc-ontology-mapping`, and emits a human-readable summary via `ingest-run-notes`. Project-specific material (e.g. MicroFlora Danica) lives under `examples/`, never as its own skill.

Every generated JSON artifact is validated against the NMDC LinkML schema, alongside additional deterministic checks, before being considered complete. Every ontology term it carries is also QC'd against the ontology itself — CURIE existence, canonical label, MIxS anchor class, NMDC value set — via [linkml-term-validator](https://linkml.io/linkml-term-validator/) (see *Ontology term QC* below).

## Sources

| Source | Skill | Module |
|---|---|---|
| NCBI BioProject | [`.claude/skills/ncbi-to-nmdc/`](.claude/skills/ncbi-to-nmdc/SKILL.md) | [`src/nmdc_ingest_agent/sources/ncbi/`](src/nmdc_ingest_agent/sources/ncbi/) |

More sources (GOLD, NEON, EMSL, JGI …) will be added as separate subpackages under `src/nmdc_ingest_agent/sources/`.

## Installation

This project uses [`uv`](https://docs.astral.sh/uv/) for environment and command management. From a fresh checkout:

```bash
uv sync
# or, with ontology tooling for the skill workflow (oaklib/runoak, sssom, linkml-term-validator):
uv sync --extra ontology
```

`uv sync` creates `.venv/` and installs the project from the committed `uv.lock`, so every contributor and CI run resolves the same dependency versions. Console scripts (e.g. `nmdc-ingest-ncbi`) are then run via `uv run` — see Usage below.

## Configuration

Real NMDC IDs are minted via the NMDC Runtime API, which authenticates with an API site client ID and secret. Set these in your shell before running with `--mint-real-ids`:

```bash
export NMDC_RUNTIME_CLIENT_ID=<your client id>
export NMDC_RUNTIME_CLIENT_SECRET=<your client secret>
# Optional: target the dev API instance instead of prod
# export NMDC_RUNTIME_ENV=dev
```

A template lives at [`.env.example`](.env.example). Site-client credentials are issued by the NMDC team — request them via the [contact form](https://microbiomedata.org/contact/) or your existing NMDC point of contact.

Without `--mint-real-ids`, the translator emits placeholder IDs of the form `nmdc:<typecode>-99-<random>`. Placeholder output is suitable for local review and schema validation, but **must not be ingested**.

Two optional variables tune the ontology term QC pass (see below):

```bash
# Check NCBITaxon terms too (not on by default: sqlite:obo:ncbitaxon is a multi-GB download;
# ols:ncbitaxon is one HTTP request per distinct taxon). Comma-separated PREFIX=adapter pairs.
# export NMDC_TERM_VALIDATION_ADAPTERS="NCBITaxon=sqlite:obo:ncbitaxon"
# Where label / anchor caches live (default: ~/.cache/nmdc-ingest-agent/term-validator).
# export NMDC_TERM_VALIDATION_CACHE_DIR=/some/shared/cache
```

## Usage

### NCBI BioProject → NMDC

```bash
# Fetch and inspect the raw NCBI data first
uv run nmdc-ingest-ncbi PRJNA1452545 --fetch-only

# Produce an NMDC-schema-compliant JSON Database (placeholder IDs)
uv run nmdc-ingest-ncbi PRJNA1452545

# Mint real persistent IDs via the NMDC Runtime API
uv run nmdc-ingest-ncbi PRJNA1452545 --mint-real-ids

# Resolve env-triad deterministically from a per-biosample crosswalk (e.g. MicroFlora Danica)
uv run nmdc-ingest-ncbi PRJNA1071982 \
    --env-triad-crosswalk examples/microflora-danica/crosswalk/mfd_biosamples_annotated.tsv
```

Output lands in `results/ncbi_<ACCESSION>_nmdc.json` relative to your current working directory (the translator creates `results/` if needed), with three sidecars next to it: `*_curation_inputs.json`, `*_curation_report.json` and `*_term_validation_report.json`. A run-notes summary for a curator lands in `runs/ncbi_<ACCESSION>/RUN_NOTES.md` (see the `ingest-run-notes` skill).

### Ontology term QC

`nmdc-ingest-ncbi` finishes by running every ontology term in the deliverable (`env_broad_scale` / `env_local_scale` / `env_medium` / `samp_taxon_id` / `host_taxid`) through [linkml-term-validator](https://linkml.io/linkml-term-validator/). The same pass can be re-run on any deliverable — typically after the curation skills have committed terms — and fold its verdicts into the curation report:

```bash
uv run nmdc-ingest-validate-terms results/ncbi_PRJNA1452545_nmdc.json \
    --curation-report results/ncbi_PRJNA1452545_nmdc_curation_report.json
```

| Level | Check | Severity | Curation-report flag |
|---|---|---|---|
| 1 | CURIE exists in ENVO and is not obsolete | error | `info_ok` |
| 2 | committed `name` is the ontology's label (case/punctuation-insensitive) | error | `label_ok` |
| 3 | `env_broad_scale` is a biome; `env_medium` an environmental material; `env_local_scale` *not* a biome | warning | `anchor_ok` |
| 4 | term is in the NMDC submission-schema value set for the sample's MIxS package (soil / water / sediment / plant-associated) | warning | `valueset_ok` |

Each flag is `true` / `false` / `null` (= not checked: the pipeline's `ENVO:00000000` sentinels; a prefix with no adapter configured — by default only ENVO is, so NCBITaxon rows stay `null`; `anchor_ok` on taxon slots, which have no anchor; `valueset_ok` when the package has no NMDC value set; and downstream flags once a term is missing or obsolete). Levels 1–3 use oaklib's cached `sqlite:obo:envo` database (`~/.data/oaklib/`), which oaklib refreshes by default once it is older than a month, so an occasional run re-downloads it; the validator's own label / anchor caches are dropped automatically when the ENVO release changes. Levels 1–3 run against a small projection schema (`src/nmdc_ingest_agent/validators/term_validation.yaml`) because nmdc-schema does not yet declare `OntologyClass.name` as `rdfs:label`; level 4 uses value sets vendored from `nmdc-submission-schema` (`env_triad_valuesets.tsv`, regenerated with `generate_valuesets.py`). The pass needs the `ontology` extra and downloads ENVO (~15 MB) once; it is skipped with a note when unavailable and never aborts an ingest (`--skip-term-validation` turns it off). Exit codes of the standalone command: 0 clean, 1 findings at or above `--fail-on` (default `error`), 2 could not run.

For the full semantic workflow (ontology resolution, validation, curator review), use the Claude Code skill:

```bash
claude
# then within the session:
/ncbi-to-nmdc PRJNA1452545
```

### Using the skills from anywhere

The skills in `.claude/skills/` are loaded automatically when you run `claude` inside this repo. Each skill is a directory containing a `SKILL.md` (plus any `references/`, `scripts/`, `assets/`). To use them from any working directory, copy the skill directories into your user-level skills directory:

```bash
cp -r .claude/skills/*/ ~/.claude/skills/
```

The skill steps invoke `uv run nmdc-ingest-ncbi` and `uv run --extra ontology runoak`, which expect to be executed from inside a `uv sync`'d checkout of this repo. To run the console script outside a checkout, install the package globally (`uv pip install nmdc-ingest-agent` into an active environment) and drop the `uv run` prefix.

## License

BSD-3-Clause. See [LICENSE](LICENSE).
