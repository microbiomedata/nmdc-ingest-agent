---
name: nmdc-ontology-mapping
description: "Use this skill to decide whether a source vocabulary warrants a reusable mapping artifact and, when it does, author a validated SSSOM mapping set (subject/predicate/object with provenance) from a source controlled vocabulary (land-cover classes, habitat ontologies, GOLD ecosystem paths, EMPO, sample-type codes) to NMDC ENVO/NCBITaxon slot values. Trigger when many biosamples share a source vocabulary you want to resolve once instead of record-by-record, or when building or extending an ontology mapping. Not for a handful of one-off term lookups; use nmdc-env-triad or nmdc-taxon-resolution for those."
---

# Ontology mapping (SSSOM)

Build a **reusable, validated mapping** from a source controlled vocabulary to NMDC slot
values (ENVO for the env triad, NCBITaxon for taxa, …), so that many records sharing the
same source term are resolved by **one** curated decision instead of one at a time.

Read `nmdc-curation-rules` first — no CURIE from memory, evidence for every commit, omit
rather than guess. Those rules govern every row you write here.

## Step 1 — Decide the regime (do this before writing any rows)

A mapping table is only worth building when the source terms form a **closed, recurring**
set. Pick the regime; record the choice in the run notes.

| Regime | Signal | What to do |
|---|---|---|
| **A — reusable vocabulary exists** | source terms come from a closed set with stable ids (CORINE, WorldCover, GOLD ecosystem paths, EMPO, a project habitat ontology) | Build an SSSOM set. High leverage: one row resolves many records; the artifact is shareable across future ingests. |
| **B — recurs but must be derived** | free-text values with meaningful repetition (many biosamples share the same `isolation_source` string) | Distill the distinct values into a normalized source-term list, mint local subject ids, then map that list as SSSOM. |
| **C — long-tail / near-unique** | distinct-value count approaches record count | **Do not build a set.** Resolve per record via `nmdc-env-triad` / `nmdc-taxon-resolution`; the durable artifact is the run notes + curation report. |

See [`references/regimes.md`](references/regimes.md) for how to measure this and worked signals.

## Step 2 — Author the SSSOM set (regimes A/B)

The artifact is [SSSOM](https://mapping-commons.github.io/sssom/) — a LinkML-schema'd,
validator-backed mapping TSV standard. Copy the template and fill one row per source term:

```bash
cp .claude/skills/nmdc-ontology-mapping/assets/mapping_set_template.sssom.tsv  <name>.sssom.tsv
```

Per row, the load-bearing columns and how to fill them:

- `subject_id` / `subject_label` — the source term's id and human label (mint a local
  prefix for a derived Regime-B vocabulary; declare it in the file's `curie_map` header).
- `predicate_id` — the **mapping relationship**, not just "maps to": `skos:exactMatch`,
  `skos:broadMatch`, `skos:narrowMatch`, `skos:closeMatch`, `skos:relatedMatch`. A CORINE
  class → an ENVO term is usually a `broadMatch`, not exact. Choose deliberately.
- `object_id` / `object_label` — the NMDC/ENVO/NCBITaxon CURIE **and** its official label,
  both from a `runoak` lookup this run (see `nmdc-env-triad` § Runoak setup). The id+label
  pair is the hallucination guard — the validator rejects a mismatch.
- `mapping_justification` — a `semapv:` value (`semapv:ManualMappingCuration`,
  `semapv:LexicalMatching`, …).
- `confidence` (0–1), `subject_source`, `object_source`, `author_id` (e.g. `orcid:…` or an
  agent id), `mapping_date`, `comment`.

Sort rows by impact (most-affected records first) so the highest-leverage mappings are
reviewed first. Full column reference and the ENVO anchor-per-slot table:
[`references/sssom-profile.md`](references/sssom-profile.md).

## Step 3 — Validate (the gate — must pass before committing)

```bash
uv run --extra ontology python .claude/skills/nmdc-ontology-mapping/scripts/validate_mapping_set.py \
    <name>.sssom.tsv --anchor <ENVO anchor for the target slot>
```

This runs `sssom validate` (structural) **and** checks every `object_id` exists, is not
deprecated, matches its stated `object_label`, and (with `--anchor`) sits under the slot's
anchor class. A failure blocks the commit — fix the row and re-run. Do not commit a set the
validator rejects.

## Where mapping sets live

- **Reusable across projects** (land-cover, GOLD ecosystem, EMPO) → `data/land-cover/` or a
  sibling `data/<vocabulary>/`. Single source of truth; other ingests import it.
- **Project-specific** → the project's `examples/<project>/` folder, never as a skill.

## Bundled scripts

- `scripts/search_envo_candidates.py` — query OLS4 for ENVO candidates for each row of a
  `*_code`/`*_label` source TSV (a curation aid; its output is not committed).
- `scripts/generate_els_allowlist.py` — regenerate the ENVO env_local_scale allow-list and
  batch-verify CURIEs after an ENVO release.
- `scripts/validate_mapping_set.py` — the Step 3 acceptance gate.
