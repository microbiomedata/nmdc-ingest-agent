---
name: nmdc-curation-rules
description: Evidence-first curation rules shared across NMDC value-completion skills (env triad, taxon, future). Read this before committing any predicted or resolved value.
---

# NMDC curation rules

These rules govern every value an agent commits to an NMDC record on behalf of a curator. They apply equally to slots resolved from submitter-provided text and slots predicted from inference inputs (see `nmdc-env-triad.md` § Inference path). Adapted from the NMDC metadata suggestor's evidence-first prompt rubric and tightened for agentic use.

A "committed" value is one the agent writes into the output JSON or the curation-report sidecar with an outcome other than `left_sentinel`. Sentinels are not commits — they are the explicit no-evidence outcome.

## Rules

1. **Evidence anchor.** Every commit carries one or more `evidence` rows of the shape `{"source": "<labeled source>", "quote_or_paraphrase": "<≤12 words>"}`. Sources are explicit labels — never bare quotes. Examples:
   - `"BioProject.description"`
   - `"BioProject.title"`
   - `"biosample.attributes.isol_growth_condt"`
   - `"biosample.attributes.geo_loc_name"`
   - `"biosample.title"` (NCBI sample title)
   - `"biosample.env_package"` (the MIxS package, e.g. `MIMS.me.soil.6.0`)
   - `"sibling consensus N=12"` (number of agreeing siblings — see Rule 6)
   - `"runoak info"` (when the evidence is the term's official label or definition)

2. **No tautology.** Domain-general statements ("soils contain organic matter", "rhizosphere is plant-associated", "metagenomes come from microbial communities") do not justify a slot value without a per-sample anchor. If the only justification you can write is generic ecology or generic microbiology, refuse — leave the sentinel.

3. **No schema names in evidence.** Don't write "AirInterface", "MIMS.me.soil", "ControlledIdentifiedTermValue" inside `quote_or_paraphrase`. Cite the user-facing field that named the value (e.g. the `env_package` text value rather than the slot's range type).

4. **Omit-rather-than-guess.** If you cannot satisfy Rules 1 and 2, write `outcome: "left_sentinel"` to the curation report and move on. The report is the deliverable; an empty triad row is a valid outcome that surfaces work for the curator. Do **not** fabricate evidence to satisfy the rules.

5. **Exact-text constraint for `has_raw_value` echoes.** When a placeholder carries `has_raw_value` from the source, do not paraphrase that field — preserve the submitter string exactly. The ENVO-official label belongs in `term.name`; the original string stays in `has_raw_value`.

6. **No CURIE fabrication.** Every committed CURIE must come from a `runoak` lookup in this run. Do not pull CURIEs from memory, from prior conversations, or from the NMDC published docs. Cross-biosample consensus (Rule 6 in `nmdc-env-triad.md`) is a *ranking* signal that elevates an already-runoak-found candidate; it never substitutes for a fresh lookup.

7. **Validate before commit.** For ontology-bearing slots (env triad, taxon, etc.), the slot-specific skill (`nmdc-env-triad.md`, `nmdc-taxon-resolution.md`) names the validators that must pass before a commit. Validator failure means revert to sentinel and write `outcome: "validator_rejected"` to the report — never silently downgrade.

8. **One reason per commit, terse.** The `quote_or_paraphrase` field is ≤12 words. If you cannot say it in 12 words, the evidence is too thin or you are reaching for a justification rather than reading one. Refuse.

## Recording outcomes

The curation-report skeleton (`results/ncbi_<ACC>_nmdc_curation_report.json`) has one row per (biosample_id, slot) for each curated slot. Update the row in place. Outcome values:

- `predicted` — committed via inference (no submitter text); evidence rows cite per-sample / study / consensus signals.
- `resolved_from_raw` — committed by lifting a submitter-provided free-text value to a CURIE.
- `resolved_at_pipeline` — the deterministic source pipeline already committed a real CURIE (e.g. `samp_taxon_id` populated by NCBI's `taxonomy_id`); leave alone unless validation fails.
- `left_sentinel` — explicit refusal under Rule 4. The deliverable for the curator.
- `validator_rejected` — Rule 7 failed; sentinel restored, validator dict records which check.

If a slot in the source pipeline is in `resolved_at_pipeline` state but you have reason to doubt it, run the same validators (Rule 7); if they fail, flip the outcome to `validator_rejected` and explain.
