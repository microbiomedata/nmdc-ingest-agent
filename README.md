# nmdc-ingest-agent

AI-agent-assisted workflows for translating external metadata sources into NMDC-schema-compliant JSON.

## What this is

A different approach to ingesting external metadata into NMDC. Rather than writing bespoke Dagster-orchestrated ETL pipelines in [nmdc-runtime](https://github.com/microbiomedata/nmdc-runtime), this repo pairs:

- **Python helper/harness methods** that do the deterministic, mechanical work — calling external APIs (e.g. NCBI E-utilities), traversing source-side links (e.g. BioProject → BioSample / SRA), assembling the `nmdc.Database` object, and running schema + deterministic integrity checks on the result.
- **Claude Code skills** (checked-in Markdown files at `.claude/skills/`) that guide an AI agent through the project-specific harmonization a curator has historically done: parsing and normalizing free-text field values, inferring implicit values from project-level descriptions, and mapping to the right ontology or database fields (e.g. ENVO terms for the MIxS env triad, NCBITaxon for host taxa). Ambiguous cases are flagged for human follow-up rather than silently guessed. Skills are composable — per-source skills (e.g. `ncbi-to-nmdc`) hand off to shared curation skills (`nmdc-env-triad`, `nmdc-taxon-resolution`, `nmdc-schema-reference`) so curation logic stays reusable across sources.

Every generated JSON artifact is validated against the NMDC LinkML schema, alongside additional deterministic checks, before being considered complete.

## Sources

| Source | Skill | Module |
|---|---|---|
| NCBI BioProject | [`.claude/skills/ncbi-to-nmdc.md`](.claude/skills/ncbi-to-nmdc.md) | [`src/nmdc_ingest_agent/sources/ncbi/`](src/nmdc_ingest_agent/sources/ncbi/) |

More sources (GOLD, NEON, EMSL, JGI …) will be added as separate subpackages under `src/nmdc_ingest_agent/sources/`.

## Installation

This project uses [`uv`](https://docs.astral.sh/uv/) for environment and command management. From a fresh checkout:

```bash
uv sync
# or, with ontology tooling for the skill workflow:
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

## Usage

### NCBI BioProject → NMDC

```bash
# Fetch and inspect the raw NCBI data first
uv run nmdc-ingest-ncbi PRJNA1452545 --fetch-only

# Produce an NMDC-schema-compliant JSON Database (placeholder IDs)
uv run nmdc-ingest-ncbi PRJNA1452545

# Mint real persistent IDs via the NMDC Runtime API
uv run nmdc-ingest-ncbi PRJNA1452545 --mint-real-ids
```

Output lands in `results/ncbi_<ACCESSION>_nmdc.json` relative to your current working directory. The translator creates the `results/` directory if it does not exist.

For the full semantic workflow (ontology resolution, validation, curator review), use the Claude Code skill:

```bash
claude
# then within the session:
/ncbi-to-nmdc PRJNA1452545
```

### Using the skills from anywhere

The skills in `.claude/skills/` are loaded automatically when you run `claude` inside this repo. To use them from any working directory, copy them into your user-level skills directory:

```bash
cp .claude/skills/*.md ~/.claude/skills/
```

The skill steps invoke `uv run nmdc-ingest-ncbi` and `uv run --extra ontology runoak`, which expect to be executed from inside a `uv sync`'d checkout of this repo. To run the console script outside a checkout, install the package globally (`uv pip install nmdc-ingest-agent` into an active environment) and drop the `uv run` prefix.

## License

BSD-3-Clause. See [LICENSE](LICENSE).
