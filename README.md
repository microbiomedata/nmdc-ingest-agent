# nmdc-ingest-agent

AI-agent-assisted workflows for translating external metadata sources into NMDC-schema-compliant JSON.

## What this is

A different approach to ingesting external metadata into NMDC. Rather than writing bespoke Dagster-orchestrated ETL pipelines in [nmdc-runtime](https://github.com/microbiomedata/nmdc-runtime), this repo pairs:

- **Python helper scripts** that do the deterministic, mechanical work (API calls, link traversal, assembling `nmdc.Database` objects), and
- **Claude Code skills** (checked-in Markdown files at `.claude/skills/`) that guide an AI agent through the semantic work a curator has historically done — picking the right ENVO terms for the MIxS env triad, resolving host taxa in NCBITaxon, flagging ambiguous cases for human follow-up.

Every generated JSON artifact is validated against the NMDC LinkML schema before being considered complete.

## Sources

| Source | Skill | Module |
|---|---|---|
| NCBI BioProject | [`.claude/skills/ncbi-to-nmdc.md`](.claude/skills/ncbi-to-nmdc.md) | [`src/nmdc_ingest_agent/sources/ncbi/`](src/nmdc_ingest_agent/sources/ncbi/) |

More sources (GOLD, NEON, EMSL, JGI …) will be added as separate subpackages under `src/nmdc_ingest_agent/sources/`.

## Installation

```bash
pip install -e .
# or, with ontology tooling for the skill workflow:
pip install -e ".[ontology]"
```

This installs the package and registers console scripts (e.g. `nmdc-ingest-ncbi`) on your `PATH`.

## Usage

### NCBI BioProject → NMDC

```bash
# Fetch and inspect the raw NCBI data first
nmdc-ingest-ncbi PRJNA1452545 --fetch-only

# Produce an NMDC-schema-compliant JSON Database
nmdc-ingest-ncbi PRJNA1452545
```

Output lands in `results/ncbi_<ACCESSION>_nmdc.json` relative to your current working directory.

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

The skills invoke the console scripts by name (e.g. `nmdc-ingest-ncbi`), so as long as the package is installed in the active Python environment, they work regardless of CWD.

## License

BSD-3-Clause. See [LICENSE](LICENSE).
