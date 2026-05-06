---
name: nmdc-env-triad
description: Resolve MIxS env_broad_scale, env_local_scale, and env_medium values to ENVO CURIEs constrained to the correct anchor classes (and the MIxS soil package valueset where applicable) using runoak.
---

# NMDC env triad curation

Resolve free-text environment descriptions into ENVO CURIEs for the MIxS env triad. A source skill (e.g. `ncbi-to-nmdc`) typically hands off here once the deterministic pipeline has emitted `ENVO:00000000` sentinels and stashed the original free text in `has_raw_value`.

## Runoak setup

Use `runoak` (the oaklib CLI) for **all** ontology lookups. Do not hand-pick CURIEs from memory; look them up. This setup block is the canonical reference for runoak invocation across the curation skills — `nmdc-taxon-resolution` and any future ontology-using skill points back here.

The repo's `ontology` extra installs oaklib:

```bash
uv sync --extra ontology
```

Common adapters:
- `sqlite:obo:envo` — ENVO (first invocation downloads `envo.db.gz` (~14MB); subsequent calls are cached and fast)
- `sqlite:obo:ncbitaxon` — NCBITaxon (used by `nmdc-taxon-resolution`; first call downloads a larger dump)
- `ols:envo` / `ols:ncbitaxon` — live OLS API (slower per call, no install footprint)

Useful runoak subcommands:

```bash
# Fuzzy search for a label
uv run --extra ontology runoak -i sqlite:obo:envo search "forest floor"

# Fetch label + definition + synonyms for a known CURIE
uv run --extra ontology runoak -i sqlite:obo:envo info ENVO:00002042

# Check ancestry (e.g. is this term under biome?)
uv run --extra ontology runoak -i sqlite:obo:envo ancestors -p i ENVO:01000174

# List all descendants of an anchor class (used to constrain env triad — see below)
uv run --extra ontology runoak -i sqlite:obo:envo descendants -p i ENVO:00000428
```

## Slot anchor classes

The NMDC schema inherits MIxS env-triad semantics: each of the three slots must point into a specific ENVO subtree. Constrain `runoak search` output to these subtrees — **do not** pick arbitrary ENVO terms.

| Slot | Anchor class | MIxS intent |
|---|---|---|
| `env_broad_scale` | `ENVO:00000428` (biome) | The coarse biome containing the sample |
| `env_local_scale` | `ENVO:01000813` (astronomical body part) — practically, environmental features | Causal environmental entity at the sample's vicinity |
| `env_medium` | `ENVO:00010483` (environmental material) | The material the sample is composed of |

## Per-placeholder workflow

For each `ENVO:00000000` sentinel in the source-pipeline output:

1. Read the original free-text value from the placeholder's `has_raw_value` (or its `name` field).
2. Search ENVO: `uv run --extra ontology runoak -i sqlite:obo:envo search "<raw value>"`
3. Filter hits to descendants of the correct anchor class. For each candidate run `uv run --extra ontology runoak -i sqlite:obo:envo ancestors -p i <CURIE>` and confirm the slot's anchor class (from the table above) appears in the ancestor list. Reject candidates that do not.
4. Pick the closest match; record its CURIE and label.
5. If no good match exists, leave the `ENVO:00000000` placeholder in place and flag it in the run report for human review. Do not guess — the source skill's report step exists to capture these.

Edit the output JSON to replace each resolved sentinel with the correct CURIE and the **ENVO-official label** (use `runoak info <curie>`). Do **not** copy the raw submitter string into the `name` field — that is a source-pipeline artifact, not the schema's canonical label.

## Slot value shape

The triad slots range over `ControlledIdentifiedTermValue`, which wraps an `OntologyClass` (`id`: CURIE, `name`: official label). For nested-value-type details and the contrast with `ControlledTermValue` (used when only free text is available), see `.claude/skills/nmdc-schema-reference.md`.

## Soil package

For **soil** biosamples (MIxS `soil` or `MIMS.me.soil.*` package), the submission schema further restricts each slot to a package-specific value set (a small curated list of ENVO terms).

Before resolving any sentinel on a soil-package biosample, check whether `nmdc-submission-schema` is importable in the active environment:

```bash
uv run python -c "import nmdc_submission_schema" 2>&1 || echo "MISSING"
```

- **If present**: pull the allowed values from the soil package and prefer matches inside that valueset.
- **If absent (current default)**: fall back to the anchor-class descendants above. **You must explicitly tell the source skill's report step** that the soil-package valueset constraint was not enforced, so the run summary calls it out as a known gap. Every soil-package run without `nmdc-submission-schema` should produce a "valueset constraint not enforced" line in the report — silent fall-back is a bug.

> **Future seam.** This subsection will be promoted to its own `nmdc-soil-curation.md` the first time a second package's guidance lands here (water, sediment, host-associated, built-environment). Until then, additions for non-soil packages should live alongside this section in matching subsections so the future split stays mechanical.
