---
name: nmdc-env-triad
description: "Use this skill to resolve MIxS env_broad_scale, env_local_scale, and env_medium to ENVO CURIEs via runoak, constrained to the correct anchor classes and the MIxS soil-package valueset. Trigger when an ingest leaves ENVO:00000000 sentinels on biosample env-triad slots, when free-text environment strings need lifting to ENVO, or when land-cover coordinates can refine env_local_scale. Not for taxon or non-environment slots."
---

# NMDC env triad curation

Resolve or predict ENVO CURIEs for the MIxS env triad (`env_broad_scale`, `env_local_scale`, `env_medium`). A source skill (e.g. `ncbi-to-nmdc`) hands off here once the deterministic pipeline has emitted `ENVO:00000000` sentinels — either with the submitter's original free text in `has_raw_value` (resolution branch, §1a) or with a genuinely missing value (inference branch, §1b).

Before committing any value, **read `nmdc-curation-rules`** — its evidence-first / no-tautology / omit-rather-than-guess rules govern every commit you make in this skill.

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

For each `ENVO:00000000` sentinel in the source-pipeline output, choose the branch:

- **§1a Resolution** — the placeholder's `has_raw_value` is non-empty (a submitter string to lift to a CURIE).
- **§1b Inference** — `has_raw_value` is empty AND `name` is `"(not provided)"` (genuinely missing data; predict from context).

Then run **§2 Validate every committed CURIE** before flipping the curation-report row off `left_sentinel`.

### §1a Resolution (free-text → CURIE)

1. Read the original free-text value from the placeholder's `has_raw_value` (or its `name` field when `has_raw_value` is the same string).
2. Search ENVO: `uv run --extra ontology runoak -i sqlite:obo:envo search "<raw value>"`
3. Filter hits to descendants of the correct anchor class. For each candidate run `uv run --extra ontology runoak -i sqlite:obo:envo ancestors -p i <CURIE>` and confirm the slot's anchor class (from the table above) appears in the ancestor list. Reject candidates that do not.
4. Pick the closest match; record its CURIE and label.
5. If no good match exists, leave the `ENVO:00000000` placeholder in place. Per `nmdc-curation-rules` Rule 4, write `outcome: "left_sentinel"` to the report — do not guess.

Edit the output JSON to replace each resolved sentinel with the correct CURIE and the **ENVO-official label** (use `runoak info <curie>`). Per `nmdc-curation-rules` Rule 5, do **not** copy the raw submitter string into `term.name` — the official label belongs there; the raw string stays in `has_raw_value`.

Set the report row to `outcome: "resolved_from_raw"`, evidence sourced to `biosample.env_<slot>.has_raw_value`.

### §1b Inference (missing → prediction)

When `has_raw_value` is empty and `name` is `"(not provided)"`, the source pipeline had nothing to lift. Predict from context, refusing if evidence is thin (per `nmdc-curation-rules` Rule 4). This branch gathers per-sample / study / consensus signals, generates and filters `runoak` candidates against the anchor class, and applies refuse thresholds before committing.

For the full inputs list, prediction workflow, and refuse thresholds, see [`references/inference.md`](references/inference.md).

## §2 Validate every committed CURIE

Applies to **both** §1a and §1b commits. Run before flipping a report row off `left_sentinel`.

1. **Term exists, label correct, not deprecated.** `uv run --extra ontology runoak -i sqlite:obo:envo info <CURIE>`. Confirm:
   - The CURIE returns a record (not "no such term").
   - The label matches what you intend to record. The ENVO-official label goes in `term.name`.
   - The term is not deprecated/obsolete (look for `IAO:0000231 has_obsolescence_reason` or `obsolete` markers in info output).
2. **Anchor class membership.** `uv run --extra ontology runoak -i sqlite:obo:envo ancestors -p i <CURIE>`. The slot's anchor class (`ENVO:00000428` for `env_broad_scale`, `ENVO:01000813` for `env_local_scale`, `ENVO:00010483` for `env_medium`) must appear in the ancestor list.
3. **Package valueset (when soil + `nmdc-submission-schema` importable).** Confirm CURIE is in the soil package's allowed list for this slot.

On any failure: revert the slot to sentinel, set `outcome: "validator_rejected"` in the report, and populate the `validator` dict to record which check failed (`info_ok: false`, `anchor_ok: false`, or `valueset_ok: false`). Do not commit.

## Slot value shape

The triad slots range over `ControlledIdentifiedTermValue`, which wraps an `OntologyClass` (`id`: CURIE, `name`: official label). For nested-value-type details and the contrast with `ControlledTermValue` (used when only free text is available), see `nmdc-schema-reference`.

## Writing the curation report

The source pipeline (`nmdc-ingest-ncbi`) writes a skeleton at `results/ncbi_<ACC>_nmdc_curation_report.json` with one row per (biosample_id, slot) for the three triad slots, all initialized to `outcome: "left_sentinel"` (or `"resolved_at_pipeline"` for slots the pipeline already committed a real CURIE for).

As you process each slot, update its row in place. Required fields per row:

- `outcome`: one of the values defined in `nmdc-curation-rules` § Recording outcomes.
- `committed_curie`, `committed_label`: set when committing; null when leaving sentinel or rejecting.
- `evidence`: list of `{source, quote_or_paraphrase}` rows per `nmdc-curation-rules` Rule 1. Required for every commit; can be empty for `left_sentinel`.
- `candidates_considered`: list of `{curie, label, reason_rejected}` for runoak hits you considered but rejected — useful for the curator to see what was tried.
- `validator`: dict with `info_ok`, `anchor_ok`, `valueset_ok` (true / false / null).

The curation report is the deliverable to the curator. Step 7 in `ncbi-to-nmdc` summarizes it.

## Soil package

For **soil** biosamples (MIxS `soil` or `MIMS.me.soil.*` package), the submission schema further restricts each slot to a package-specific value set. Check whether `nmdc-submission-schema` is importable; if present, prefer matches inside the soil valueset, and if absent (the current default), fall back to anchor-class descendants **and** tell the source skill's report step that the valueset constraint was not enforced — silent fall-back is a bug.

For the importability check and the exact report-gap wording, see [`references/soil-package.md`](references/soil-package.md).
