# nmdc-ingest-agent — skills refactor plan

Authority order (per Sujay, 2026-07-09): **Anthropic's Complete Guide to Building Skills for Claude** > Chris Mungall's ai4curation *author-skills* how-to (additive) > Olivia's PR #91 (precedent only).

Evidence: all three sources retrieved and read in full. 16 load-bearing rules adversarially re-checked against the primary text; 16 confirmed, 0 refuted.

> **Revision (2026-07-10):** the mapping-artifact design in §4 was reworked after review. The original bespoke 12-column TSV assumed every source has an MFD-like closed vocabulary; it now branches on a **regime decision** and emits **SSSOM** (the OBO/Monarch mapping standard, already a transitive dependency) instead of a repo-local format. See §4.

---

## 0. The headline: the skills are probably dead code today

Anthropic's guide, p.5: *"A skill is a folder containing: **SKILL.md (required)** … scripts/ (optional) … references/ (optional) … assets/ (optional)."* Chris's page agrees, and Olivia's PR #91 converts to exactly that.

This repo has **seven flat files** at `.claude/skills/*.md`. There is no `SKILL.md` anywhere. So:

- `README.md:76` — *"The skills in `.claude/skills/` are loaded automatically when you run `claude` inside this repo"* — is very likely false.
- `README.md:71` — `/ncbi-to-nmdc PRJNA1452545` — that command almost certainly does not exist.
- `README.md:79` — `cp .claude/skills/*.md ~/.claude/skills/` — copies files that will be ignored there too.

Everything else in this plan is downstream of fixing that. **This is a correctness fix, not a tidiness refactor.**

---

## 1. Constraint compliance (your six, restated and answered)

| # | Constraint | How it is satisfied |
|---|---|---|
| 1 | No project-specific skills | `mfd-project-vocabulary` is **retired**. All 8 surviving skills are source/project agnostic. |
| 2 | Project info as assets | MFD lives in `examples/microflora-danica/` (records + crosswalk bundle) and as worked-example `references/` files inside general skills. |
| 3 | Encourage agent-authored mapping artifacts | New **`nmdc-ontology-mapping`** skill: makes a **regime decision** (§4), and where a mapping set is warranted emits **SSSOM** (validated with the already-installed `sssom` tooling), **triggered inside `ncbi-to-nmdc` Step 3**. Where it isn't, it routes back to per-record curation. |
| 4 | Surface high-level run notes | New **`ingest-run-notes`** skill + `src/nmdc_ingest_agent/run_notes.py` writing `runs/<source>_<ACC>/RUN_NOTES.md`. |
| 5 | Only multi-purpose tools at root | `instruments.py`, `minting.py`, `validation.py`, `run_notes.py` stay at `src/` root. Single-skill scripts move into skill `scripts/`. Nothing packaged as MCP/function tools. |
| 6 | Respect Chris's direction | Directory-per-skill, explicit `name:`, strict YAML, bundled scripts over prose, dual-verified id+label. **With one documented divergence — see §6.** |

---

## 2. The three real coupling defects (verified first-hand)

1. **`translate.py:31` imports `mfd.py` unconditionally**, and `translate.py:1576` calls `MfdEnvTriadResolver.from_tsv()` at the CLI entry point. One pilot project is hardwired into the general NCBI translator. This is the deepest violation of constraint 1 and nobody had named it.
2. **`mfd-project-vocabulary.md`** is a project-specific skill by name and content.
3. **`nmdc-env-triad.md` and `nmdc-target-gene.md` leak MFD inline** (the "MFD expected outcome" section, the 8F/2490R design table), so even the general skills carry the pilot.

Fix for (1): generalize `mfd.py` → `env_triad_crosswalk.py` with `CrosswalkEnvTriadResolver`, key column / regex / slots as constructor args, **no MFD default**. Supply the TSV via `--env-triad-crosswalk PATH` (primary, discoverable) or `NMDC_ENV_TRIAD_CROSSWALK_TSV` (fallback). MFD becomes *data*, not code.

---

## 3. Target layout

```
CLAUDE.md                                  # NEW — repo conventions + skill index
.claude/
  settings.json                            # NEW — permission allowlist
  skills/
    ncbi-to-nmdc/          SKILL.md  references/{scope,reference-patterns}.md  scripts/validate_local.py
    nmdc-curation-rules/   SKILL.md  references/outcomes.md
    nmdc-env-triad/        SKILL.md  references/{runoak,inference,soil-package}.md  assets/anchor_classes.tsv
    nmdc-taxon-resolution/ SKILL.md
    nmdc-schema-reference/ SKILL.md  scripts/inspect_slot.py
    nmdc-target-gene/      SKILL.md  references/worked-examples.md  assets/target_gene_enum.tsv
    nmdc-ontology-mapping/ SKILL.md  references/{regimes,sssom-profile}.md  assets/mapping_set_template.sssom.tsv
                                     scripts/{search_envo_candidates,generate_els_allowlist,validate_mapping_set}.py
    ingest-run-notes/      SKILL.md  assets/run_notes_template.md
src/nmdc_ingest_agent/
  instruments.py  minting.py  validation.py        # unchanged, multi-purpose
  run_notes.py                                     # NEW, source-agnostic notes writer
  sources/ncbi/
    translate.py                                   # MFD import severed
    env_triad_crosswalk.py                         # was mfd.py, generalized
data/
  land-cover/{corine_envo_map,worldcover_envo_map}.tsv   # reusable, NOT MFD-specific
examples/microflora-danica/
  <collection>_set/*.json                          # unchanged
  crosswalk/                                       # was data/mfdo-crosswalk-v2/ (MFD parts, all 14 files)
runs/ncbi_PRJNA1071982/
  RUN_NOTES.md        # machine-generated, overwritten each run
  DECISIONS.md        # human-authored, agent READS only, never writes
  overrides.tsv       # human decisions, SSSOM mapping set (§4)
results/              # gitignored artifacts (unchanged)
```

### Where I deviate from the workflow's own proposal

- **Land-cover maps go to `data/land-cover/`, not a skill's `assets/`.** Anthropic defines `assets/` as *"templates, fonts, icons used in output"*. `corine_envo_map.tsv` is repo data consumed by `apply_crosswalk.py` **and** `test_crosswalk_curies.py`. Burying it in `.claude/skills/…/assets/` forces both to reach cross-tree. `assets/` gets `mapping_set_template.sssom.tsv` (a genuine template). These maps are also *not* MFD-specific, so `data/` is their correct home.
- **`run_notes.py` at `src/` root, not `sources/ncbi/notes.py`.** Run notes are source-agnostic; constraint 5 puts multi-purpose tools at root. Otherwise the "general" run-notes skill would have no general producer.

---

## 4. The mapping-artifact convention (`nmdc-ontology-mapping`)

MFD is the *easy* case and the plan must not generalize from it. MFD came with MFDO — a closed, enumerable habitat vocabulary whose ~284 leaves each recur across many biosamples (**284 crosswalk rows resolve ~10,689 biosamples — 37× amortization**). A mapping table is high-value there precisely because it is a *closed, recurring, reusable* vocabulary. You cannot assume that artifact exists. So the skill's first job is not to build a table — it is to decide **which regime it is in**.

### 4a. The regime decision (do this before writing any rows)

| Regime | Signal | Artifact |
|---|---|---|
| **A — reusable vocabulary exists** | source terms come from a closed set with stable ids (MFDO, CORINE, WorldCover, GOLD ecosystem paths, EMPO) | **Build an SSSOM mapping set.** One row resolves many records; the artifact outlives the run and is shareable across future ingests. |
| **B — vocabulary recurs but must be derived** | free-text values with meaningful repetition (many biosamples share the same `isolation_source` string) | **Distill first, then map.** The agent normalizes the distinct values into a synthetic source-term list, mints local subject ids for them, then maps that list as SSSOM. Still amortizing, subject side is agent-manufactured. |
| **C — long-tail / near-unique free text** | distinct-value count approaches record count; a "mapping" would be one row per record | **No mapping set.** Resolve per record via `nmdc-env-triad`; the durable artifact is the **run notes + curation report**, not a table. The skill declines and hands back. |

The decision is recorded in the run notes ("Regime B: 412 distinct isolation_source values across 10,689 biosamples → derived vocabulary"). This is Chris's *"consider not writing a skill"* restraint applied one level down: **consider not writing a mapping.** The old §4 treated the trigger as a bare count threshold; it is really this three-way decision.

The crispest form of the Regime-A test is **"does a closed valueset already exist for this slot?"** The group's agentic-curation vision doc frames the same fork from the schema side: NMDC's `SoilInterface` enumerates 52 allowed `env_broad_scale` / 83 `env_local_scale` / 85 `env_medium` values, and where such a valueset exists the selection task is easy and closed (Regime A); where it does not — NCBITaxon, GOLD-derived host-associated or marine environments with no pre-enumerated set — you must fall back to open-ontology `runoak` lookup plus a term validator (Regime B/C). This is external corroboration of the same three regimes, and it is exactly what `nmdc-env-triad`'s soil-package valueset handling already does for the one package it covers.

### 4b. The format: SSSOM, not a bespoke TSV

Where a mapping set is warranted (A/B), emit **[SSSOM](https://mapping-commons.github.io/sssom/)** — the OBO/Monarch *Simple Standard for Sharing Ontological Mappings*. It is **already a transitive dependency** (`sssom` 0.4.17 + `sssom-schema` in `uv.lock`, via oaklib, which the `ontology` extra installs), with a real CLI: `sssom validate | parse | convert | diff`.

SSSOM is a *LinkML-schema'd TSV*, which is why it beats the hand-rolled 12-column contract on every axis that matters here:

| Bespoke column (old §4) | SSSOM slot | Why SSSOM's is better |
|---|---|---|
| `source_id` / `source_label` | `subject_id` / `subject_label` | standard names; id+label dual-verify is native |
| *(missing!)* | **`predicate_id`** | captures `skos:exactMatch` vs `broadMatch` vs `narrowMatch` — the mapping *relationship* the flat contract silently dropped |
| `target_curie` / `target_label` | `object_id` / `object_label` | same dual-verify, standard names |
| `method` | `mapping_justification` | standardized `semapv:` vocabulary (`ManualMappingCuration`, `LexicalMatching`, …) |
| `confidence` (ad-hoc enum) | `confidence` | SSSOM float 0–1, plus `subject_source` / `object_source` |
| `curator` / `date` | `author_id` / `mapping_date` | standard provenance |
| `notes` | `comment` | — |

The `predicate_id` gain is not cosmetic: mapping `Continuous urban fabric → populated place` is a `skos:broadMatch`, not an exact match, and that distinction is load-bearing downstream. The bespoke `target_curie` column threw it away.

Adopting SSSOM also **resolves the §6 tension with Chris**: he prefers schema-validated artifacts over free-form TSV, and SSSOM *is* a validated TSV — so this stops being an override and becomes conformance.

**Caveat that ties back to the regime question:** SSSOM wants `subject_id` to be a real CURIE/IRI. CORINE classes have ids (so `corine_envo_map.tsv` is near-SSSOM-ready today); MFDO leaves and free-text strings do not — which is *itself* the tell that you are in Regime B (mint local subject ids) or C (don't build a set at all).

### 4c. What makes it operational, not decorative

- **Trigger:** `ncbi-to-nmdc` Step 3 invokes `nmdc-ontology-mapping`, which runs the §4a regime decision; only A/B produce a set.
- **Gate:** `sssom validate` (wrapped by `scripts/validate_mapping_set.py`, generalized from the current `test_crosswalk_curies.py`) must pass — plus the runoak anchor-class check per `nmdc-env-triad` — before any mapping is committed. Failure blocks. (`worldcover_envo_map.tsv:6` literally carries the note *"corrected from an earlier wrong CURIE"* — this gate has already caught a real bug.) The bespoke anchor check is swapped for the group's `linkml-term-validator` (term exists / not deprecated / within an allowed ontology **branch**) in a **separate follow-up PR** (§8, PR-2), so the new dependency lands on its own. Until then `validate_mapping_set.py` uses the generalized runoak anchor logic.
- **Reuse:** the existing `data/land-cover/*.tsv` maps are converted to SSSOM once and become shareable inputs, not per-run rework.

---

## 5. The run-notes convention (`ingest-run-notes`)

Replaces the 13 MB `curation_report.json` no human reads. `results/_live_run_2026-06-29.log` is the prototype; this makes it durable and structured.

**Three files, and the generated/human split is the whole point:**

- `runs/<source>_<ACC>/RUN_NOTES.md` — machine-generated, **overwritten every run**. Sections: run metadata (command line, env, git sha, mint mode) · record counts · exclusions and why · resolved deterministically · resolved by LLM judgment (with example evidence) · deferred backlog with refuse reasons · ambiguous cases phrased as questions for the PI · validation results.
- `runs/<source>_<ACC>/DECISIONS.md` — **human-authored. The agent reads it at Step 0 and never writes it.**
- `runs/<source>_<ACC>/overrides.tsv` — machine-readable human decisions, as an SSSOM mapping set (§4) when they are term mappings, so they pass the same validator.

The workflow's original design put the human's "Decisions for next run" section *inside* the regenerated `RUN_NOTES.md`, which the next run would clobber — destroying the steering loop it exists to enable. Splitting generated from hand-authored fixes that.

This is Chris's *"Keep a Human Driving the Loop"* step 6 — *"the human reviews the scientific judgment, decides which feedback matters, and asks the agent for another iteration"* — made concrete.

---

## 6. Honest divergence from Chris's guide

The plan should not claim his direction is "honored throughout." His docs point two ways worth naming:

- He routes provenance through **ai-blame + the PR/CI trail**, not agent-authored notes files.
- He prefers **schema-validated LinkML/YAML with id+label Term objects**, with TSV as a *generated export*; he warns against *"making agents edit graph serialization directly."*

Adopting **SSSOM for the mapping artifact (§4) turns the second point from an override into conformance** — SSSOM is exactly a LinkML-schema'd, validator-backed mapping standard from his own ecosystem, id+label native, so we are now *following* his preference rather than diverging from it. That leaves one genuine divergence: the human-readable `RUN_NOTES.md` (§5) is an agent-generated notes file, which his ai-blame/PR model does not call for. The reconciliation:

- Both artifacts are **script-generated and script-validated**, not free-form agent prose. `run_notes.py` writes `RUN_NOTES.md` from computed counts; `sssom validate` gates every mapping row.
- The **PR remains the review surface**, exactly as he prescribes.

So: one deliberate, documented owner choice (a human-facing notes file, your constraint 4) — not an oversight, and no longer a conflict on the mapping format.

Even that lone divergence is softer than it first looked. The group's own agentic-curation vision doc describes the ingest agent approvingly with *"a summary report flags items that still need human review"* and lists run output as *"complete records OR diffs (optionally with sidecar suggestions, evals, questions)"* including *"questions you would ask the PI about implicit missing data."* That is exactly what `RUN_NOTES.md` is. So the notes file is endorsed by the group's ingest-agent direction; the only genuinely open nuance is format (a markdown notes file vs a structured sidecar) — see §10.

---

## 7. Defects found in review, and their fixes

| Defect | Fix |
|---|---|
| `test_crosswalk_curies.py` reads land-cover maps via `HERE / "corine_envo_map.tsv"` at 6 sites — moving maps into skill `assets/` breaks it, so "pytest green" would be false | Maps go to `data/land-cover/`; test and `apply_crosswalk.py` share one path helper |
| `data/mfdo-crosswalk-v2/README.md` (the 14th tracked file) had no move — dir could not be "empty and removed" | Merge it into `examples/microflora-danica/crosswalk/README.md` together with the retired `mfd-project-vocabulary.md` body |
| The mapping skill was never wired into the pipeline | Trigger added to `ncbi-to-nmdc` Step 3, running the §4a regime decision |
| Mapping validator bundled but never required | `sssom validate` + anchor-class check made a failure-blocking acceptance gate |
| Bespoke TSV assumed an MFD-like closed vocabulary always exists | Replaced with the §4a regime decision + SSSOM; Regime C produces no mapping set |
| Human's steering block clobbered on next run | Split `DECISIONS.md` from `RUN_NOTES.md` |
| Dropping the MFD default silently yields ~10,689 sentinels | `--env-triad-crosswalk` flag + legacy env var; RUN_NOTES emits a loud "no crosswalk configured" line |
| ~30 skill-to-skill refs by filename **and** section anchor (`§1a`, `§ Soil package`, and a mislabeled "Step 6" that is really Step 7) | Rewrite refs to bold kebab-case skill names; grep gate in the final PR |
| `settings.local.json` never gitignored | Added in PR1 |

---

## 8. Delivery: PR-0 (safety) → PR-1 (refactor) → PR-2 (validators)

**PR-1 is the refactor**, delivered as one PR with the eight commits below. These steps form a **dependent stack**, not independent units — splitting them into separate PRs would just add 8× the merge/CI/rebase overhead for sequencing a single branch already gives for free. And because the skills are broken today, every intermediate PR would merge a still-broken state to `main`; there's no point in the chain worth stopping to ship. Reviewability, green-at-each-step, and bisectability all come from **commit hygiene**, not PR boundaries. So: one PR, one commit per step, with a description mapping commits to this plan.

**PR-0 (optional, first):** the gitignore safety net (commit 1 below) — worth carving off not for review but because it's urgent and independent (`submissions/` + `data/mfd_metadata_cache/` are ~46 MB untracked, one `git add .` from disaster). Land it as a 1-file PR now, or leave it as commit 1 of PR-1.

**PR-2 (fast-follow, after PR-1 merges):** adopt `linkml-term-validator` + `linkml-data-qc` (§10). Kept separate at your call, so the new-dependency decision doesn't bloat the refactor. Scope: add both to the `ontology` extra (neither is in `uv.lock` today); replace the runoak anchor logic inside `validate_mapping_set.py` and `nmdc-env-triad`'s validation with `linkml-term-validator` (exists / not deprecated / in-branch); add a `linkml-data-qc` cross-field pass (e.g. GOLD-quintuple all-or-nothing); update the two skills' validation steps and the `ncbi-to-nmdc` Step 7 wording. The seam is clean because PR-1 already isolates all term validation behind `validate_mapping_set.py` + the env-triad `§ Validate` step.

1. **Safety net, zero code.** `.gitignore` += `submissions/`, `data/mfd_metadata_cache/`, `settings.local.json`. Add `runs/.gitkeep`. *(Own tiny PR, or commit 1.)*
2. **Directory-ize the 6 general skills**, names unchanged: `git mv X.md → X/SKILL.md`. Add `name:` + `Use this skill to …` descriptions (verified <1024 chars, no angle brackets). Rewrite cross-refs to skill names. Fix `README.md` (lines 10/18/71/76-79) and `translate.py` print strings (1633/1653). **Verify all 6 appear in `/skills`.**
3. **Progressive-disclosure split.** Extract into `references/`, `assets/`, `scripts/`. Add root `CLAUDE.md` + `.claude/settings.json`.
4. **New `nmdc-ontology-mapping` skill (SSSOM).** Author `SKILL.md` + `references/{regimes,sssom-profile}.md` + `assets/mapping_set_template.sssom.tsv`. `git mv` the two vocabulary-agnostic scripts into its `scripts/`; add `validate_mapping_set.py` (wraps `sssom validate` + anchor check, generalized from `test_crosswalk_curies.py`). Move land-cover maps to `data/land-cover/` and convert them to SSSOM; repoint `apply_crosswalk.py` **and** the test. Add `sssom` as an explicit dep of the `ontology` extra (currently only transitive via oaklib).
5. **New `ingest-run-notes` skill** + `src/nmdc_ingest_agent/run_notes.py` + `tests/test_run_notes.py`. Seed `runs/ncbi_PRJNA1071982/`.
6. **Sever MFD from the connector** — *the one behavioral-risk commit.* `git mv mfd.py → env_triad_crosswalk.py`; drop the hardcoded default; add the CLI flag. `git mv test_mfd.py → test_env_triad_crosswalk.py` with a synthetic fixture **plus** the verified parity assertion `MFD00001 → temperate broadleaf forest biome [ENVO:01000202]`. Put the before/after parity check in the PR description so a bisect localizes any regression here.
7. **Relocate MFD data + retire the project skill.** All 14 files → `examples/microflora-danica/crosswalk/`. Merge `mfd-project-vocabulary.md` into its README. `/skills` now shows **8 skills, zero project-specific.**
8. **Docs + verification.** Grep for stale `.claude/skills/*.md`, `data/mfdo-crosswalk-v2/`, `MfdEnvTriadResolver`. Fix `data/README.md` (lines 13/17/25/34/41/47). End-to-end smoke: `--fetch-only` + one build, confirming entry point, resolver, and RUN_NOTES emission.

**Acceptance for the whole refactor:** a before/after run of PRJNA1071982 produces identical `resolved_at_pipeline` counts, and a non-MFD BioProject produces byte-identical output.

---

## 9. Calls I made for you (say the word to flip any)

- **`references/`, not `refs/`** — your ruling: Anthropic's guide beats PR #91.
- **Land-cover maps → `data/land-cover/`**, not skill `assets/` (see §3).
- **`run_notes.py` at `src/` root**, not under `sources/ncbi/`.
- **`mfd_biosamples_annotated.tsv` (2.5 MB) stays committed** under `examples/` — preserves determinism.
- **MFD crosswalk becomes opt-in** via `--env-triad-crosswalk`; no project default in `src/`.
- **Add `.agents -> .claude` symlink** (Chris's cross-harness portability). Cheap; skip if you dislike symlinks.
- **`results/` pruning is out of scope** — it's gitignored; a local-disk chore, not a refactor step.
- **Mapping artifact = SSSOM, gated by a regime decision** (§4). Adds `sssom` as an explicit `ontology`-extra dep; it's already in `uv.lock` transitively, so no new resolution.

Open, genuinely yours to decide: whether `ingest-run-notes` should be renamed `nmdc-run-notes` for family grouping in `/skills`. It's the one skill that isn't NMDC-specific.

---

## 10. Notes from the group's agentic-curation vision (lower-weight source)

From *"From One-Shot Prompts to Agentic Metadata Curation"* (Mungall-group strategy doc, weighted below the authoritative sources per your instruction). It is mostly vision that **confirms** this plan's direction — skills as pluggable/composable Markdown, deterministic Python tools the agent *calls* rather than pipeline stages, evidence-first anti-over-extrapolation, sentinel-and-defer over guessing, a summary report for human review. Three items sharpen the plan; two I deliberately left out.

**Folded in (above):**
- **Regime test = "does a closed valueset exist?"** (§4a). The doc's `SoilInterface` example (52/83/85 enumerated ENVO values) is the schema-side statement of the same A/B/C fork, and cross-validates it.
- **Divergence from Chris is smaller than §6 first claimed.** The doc endorses the ingest agent's "summary report flags items for human review" and "questions for the PI" — i.e. `RUN_NOTES.md`.

**Scheduled as its own follow-up PR (§8, PR-2) to keep the refactor PR reviewable:**
- **`linkml-term-validator` / `linkml-data-qc`.** The doc names these as the group's established guardrails: term-validator checks a term exists, isn't deprecated, and falls **within an allowed ontology branch** — which *replaces* the bespoke anchor-class check in `validate_mapping_set.py` and `nmdc-env-triad`, aligning us with the ecosystem the way SSSOM did. `data-qc` adds cross-field consistency (e.g. "GOLD ecosystem quintuple filled completely or not at all"). **Unlike SSSOM, neither is in `uv.lock`** — adopting them is a real dependency decision, so it lands in a dedicated PR *after* the refactor merges, not among the eight commits. The framing worth keeping regardless: *every time the agent makes a class of mistake, engineer a guardrail so it cannot make it again* — that is the "why" behind the failure-blocking gates in §4c and §7.
- **Domain/environment-specific curation skills** (a "soil curator" vs "water curator" skill: peatland → peat, not generic soil) are an explicitly endorsed axis. This is **not** a constraint-1 violation — an *environment* is not a *project* — and it is exactly the "future seam" already noted inside `nmdc-env-triad`'s soil-package section. I'd keep that seam as-is and split per-MIxS-package only when a second package's guidance actually lands, rather than pre-building empty skills now.

**Deliberately left out (out of scope for a skills refactor):**
- **Diff-style output** ("complete records OR diffs, with sidecar evals") and **spreadsheet-upload normalization** are the *suggestor's* Q4+ agentic roadmap, not this repo's ingest path. Worth tracking as future direction; nothing to change here now. Noted so the omission is a choice, not an oversight.
