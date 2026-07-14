# nmdc-ingest-agent — repo guide for agents

AI-agent-assisted translation of external metadata sources (currently NCBI BioProjects)
into NMDC-schema-compliant `Database` JSON. The design pattern: **deterministic Python
tools do the mechanical work; Claude Code skills carry the curation judgment.** The Python
package is *not* an AI tool — the agent calls it (fetch, build, validate) and reasons over
the results using the skills.

## Running an ingest

```bash
uv sync --extra ontology                       # provisions .venv from uv.lock (+ oaklib/runoak)
uv run nmdc-ingest-ncbi PRJNA1452545 --fetch-only   # inspect raw NCBI data
uv run nmdc-ingest-ncbi PRJNA1452545                # produce NMDC JSON (placeholder IDs)
uv run nmdc-ingest-ncbi PRJNA1452545 --mint-real-ids   # real IDs via NMDC Runtime API
uv run pytest -q                               # tests
```

Output lands in `results/` (gitignored). For the full curator-quality workflow, drive it
through the `ncbi-to-nmdc` skill (`/ncbi-to-nmdc <ACCESSION>`).

## Skills

Skills live under `.claude/skills/<name>/SKILL.md` (a **directory per skill** — a flat
`.claude/skills/<name>.md` is NOT discovered). Bulky reference material sits in
`references/`, runnable helpers in `scripts/`, lookup data in `assets/`. Skills are
general-purpose; project-specific material (e.g. MicroFlora Danica) lives in `examples/`
or as a skill's assets, never as its own skill.

| Skill | Use it to |
|---|---|
| `ncbi-to-nmdc` | translate an NCBI BioProject into NMDC JSON; orchestrates the curation skills below |
| `nmdc-curation-rules` | evidence-first rules every committed value must satisfy (read before committing anything) |
| `nmdc-env-triad` | resolve MIxS env_broad_scale / env_local_scale / env_medium to ENVO CURIEs via runoak |
| `nmdc-taxon-resolution` | resolve organism names to NCBITaxon CURIEs (samp_taxon, host) |
| `nmdc-target-gene` | curate amplicon LibraryPreparation description + target_gene |
| `nmdc-schema-reference` | look up NMDC LinkML slot ranges / value-type wrappers / enums via SchemaView |
| `nmdc-ontology-mapping` | decide whether a source vocabulary warrants a mapping, and author a validated SSSOM mapping set when it does |
| `ingest-run-notes` | write a human-readable `runs/<source>_<ACC>/RUN_NOTES.md` summarizing a run so a curator can steer the next one |

## Conventions

- **Evidence-first curation.** Never commit a value without a per-sample labeled source.
  Never write a CURIE from memory — every ontology term comes from a `runoak` lookup this
  run, verified to exist / not be deprecated / sit under the right anchor class. Omit rather
  than guess; a left sentinel is a valid, honest outcome. See `nmdc-curation-rules`.
- **Validation in the loop.** Generated JSON is validated against the NMDC LinkML schema
  (offline) and the runtime `/metadata/json:validate` endpoint (referential integrity).
  Fix failures and re-validate; don't silently downgrade.
- **Tool placement.** Multi-purpose, source-agnostic tools live at `src/nmdc_ingest_agent/`
  (`instruments.py`, `minting.py`, `validation.py`). Source-specific code lives under
  `sources/<source>/`. Single-skill helpers live in that skill's `scripts/`.
- **ID + label together.** Ontology-valued slots carry both the CURIE and its official label
  (`ControlledIdentifiedTermValue`), which makes hallucinated terms far harder to slip
  through — validate both.

## Layout

```
src/nmdc_ingest_agent/       deterministic tools (instruments, minting, validation) + sources/ncbi/
.claude/skills/<name>/       skills (SKILL.md + references/ scripts/ assets/)
data/                        reusable computable data (ontology maps)
examples/<project>/          per-project reference records + project-specific assets
results/                     generated deliverables (gitignored)
docs/skills-refactor-plan.md the refactor design doc
```
