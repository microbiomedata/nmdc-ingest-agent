---
name: nmdc-env-triad
description: Resolve MIxS env_broad_scale, env_local_scale, and env_medium values to ENVO CURIEs constrained to the correct anchor classes (and the MIxS soil package valueset where applicable) using runoak.
---

# NMDC env triad curation

Resolve or predict ENVO CURIEs for the MIxS env triad (`env_broad_scale`, `env_local_scale`, `env_medium`). A source skill (e.g. `ncbi-to-nmdc`) hands off here once the deterministic pipeline has emitted `ENVO:00000000` sentinels — either with the submitter's original free text in `has_raw_value` (resolution branch, §1a) or with a genuinely missing value (inference branch, §1b).

Before committing any value, **read `.claude/skills/nmdc-curation-rules.md`** — its evidence-first / no-tautology / omit-rather-than-guess rules govern every commit you make in this skill.

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
5. If no good match exists, leave the `ENVO:00000000` placeholder in place. Per `nmdc-curation-rules.md` Rule 4, write `outcome: "left_sentinel"` to the report — do not guess.

Edit the output JSON to replace each resolved sentinel with the correct CURIE and the **ENVO-official label** (use `runoak info <curie>`). Per `nmdc-curation-rules.md` Rule 5, do **not** copy the raw submitter string into `term.name` — the official label belongs there; the raw string stays in `has_raw_value`.

Set the report row to `outcome: "resolved_from_raw"`, evidence sourced to `biosample.env_<slot>.has_raw_value`.

### §1b Inference (missing → prediction)

When `has_raw_value` is empty and `name` is `"(not provided)"`, the source pipeline had nothing to lift. Predict from context, refusing if evidence is thin (per `nmdc-curation-rules.md` Rule 4).

**Inputs to gather** — from the curation inputs sidecar at `results/ncbi_<ACC>_nmdc_curation_inputs.json`, keyed by NMDC biosample id:

- **MIxS package** (`biosamples.<id>.package`, also exposed on the NMDC biosample's `env_package.has_raw_value`) — picks the package valueset and constrains candidates. E.g. `MIMS.me.soil.6.0` → soil branch; `MIMS.me.water.6.0` → water branch; built-environment, host-associated, plant-associated, and others as defined.
- **Per-sample structured slots already on the NMDC biosample**: `geo_loc_name`, `lat_lon`, `depth`, `elev`, `samp_taxon_id`, `collection_date`, `habitat`, `host_name`, `samp_name`.
- **Per-sample raw NCBI attributes from the sidecar's `attributes` dict** (anything not on the NMDC biosample): `isol_growth_condt`, `ecosystem`, `ecosystem_type`, `ecosystem_subtype`, `specific_ecosystem`, sample-title text from `ncbi_title`.
- **Study-level context from the sidecar's `study` block**: `title`, `description`, any abstracts.
- **Cross-biosample consensus** (gated, ranking signal only): if ≥3 sibling biosamples in the same study have already-resolved (non-sentinel) values that agree on a CURIE for this slot, treat that as a *prior* — but still require per-sample anchor evidence per `nmdc-curation-rules.md` Rule 1. Consensus alone never commits a value. Mixed-environment studies (soil cores + adjacent water; host-associated + bulk soil) commonly break consensus assumptions; if you use consensus and it disagrees with the per-sample evidence, do not commit.

**Prediction workflow:**

1. Pick the **anchor class** for the slot (table above).
2. Pick the **package valueset** if the MIxS package is known. If `nmdc-submission-schema` is importable (see § Soil package check below), intersect the runoak ancestor-descendants of the anchor class with the package's allowed list. If not, fall back to anchor-class descendants and surface the gap per the existing soil-package rule.
3. Generate candidate ENVO terms by searching `runoak` with phrases drawn from the gathered inputs. Examples:
   - `geo_loc_name="USA: Oregon"` + `attributes.habitat="Rhizosphere soil"` → search "rhizosphere", "rhizosphere soil", "forest" (per geographic context).
   - `attributes.specific_ecosystem="Soil"` + `attributes.ecosystem_subtype="Rhizosphere"` → "rhizosphere" first.
   - `BioProject.description` mentioning "montane forest soil" → search "temperate coniferous forest biome".
4. Filter candidates: must be a descendant of the slot's anchor class (`runoak ancestors -p i <CURIE>`), and (when applicable) inside the package valueset.
5. Rank by per-sample anchor strength > study-level evidence > sibling-consensus tiebreaker.
6. Apply the **refuse thresholds** below. If they fire, leave sentinel; write `outcome: "left_sentinel"` to the report.
7. Otherwise commit, run § Validate every committed CURIE, write the report row with `outcome: "predicted"`, and include evidence rows + candidates considered.

**Refuse thresholds** (the agent must check before committing a prediction):

- No package known AND no per-sample text-bearing slot → leave sentinel.
- Package known but per-sample slots are all empty/sentinel AND siblings disagree → leave sentinel.
- Package known + at least one concrete per-sample slot from this list (`geo_loc_name`, `habitat`, `attributes.isol_growth_condt`, `attributes.ecosystem*`, NCBI sample title containing material/feature words, depth+elev+samp_taxon together) → commit a prediction with cited evidence.
- For `env_medium` specifically: require evidence of the actual sampled material. Pure geographic info alone is not enough (it speaks to biome / feature, not material). Soil package + depth strongly supports a soil-material descendant; water package + lat_lon over ocean supports a water-material descendant.

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

The triad slots range over `ControlledIdentifiedTermValue`, which wraps an `OntologyClass` (`id`: CURIE, `name`: official label). For nested-value-type details and the contrast with `ControlledTermValue` (used when only free text is available), see `.claude/skills/nmdc-schema-reference.md`.

## Writing the curation report

The source pipeline (`nmdc-ingest-ncbi`) writes a skeleton at `results/ncbi_<ACC>_nmdc_curation_report.json` with one row per (biosample_id, slot) for the three triad slots, all initialized to `outcome: "left_sentinel"` (or `"resolved_at_pipeline"` for slots the pipeline already committed a real CURIE for).

As you process each slot, update its row in place. Required fields per row:

- `outcome`: one of the values defined in `nmdc-curation-rules.md` § Recording outcomes.
- `committed_curie`, `committed_label`: set when committing; null when leaving sentinel or rejecting.
- `evidence`: list of `{source, quote_or_paraphrase}` rows per `nmdc-curation-rules.md` Rule 1. Required for every commit; can be empty for `left_sentinel`.
- `candidates_considered`: list of `{curie, label, reason_rejected}` for runoak hits you considered but rejected — useful for the curator to see what was tried.
- `validator`: dict with `info_ok`, `anchor_ok`, `valueset_ok` (true / false / null).

The curation report is the deliverable to the curator. Step 7 in `ncbi-to-nmdc.md` summarizes it.

## Soil package

For **soil** biosamples (MIxS `soil` or `MIMS.me.soil.*` package), the submission schema further restricts each slot to a package-specific value set (a small curated list of ENVO terms).

Before resolving any sentinel on a soil-package biosample, check whether `nmdc-submission-schema` is importable in the active environment:

```bash
uv run python -c "import nmdc_submission_schema" 2>&1 || echo "MISSING"
```

- **If present**: pull the allowed values from the soil package and prefer matches inside that valueset.
- **If absent (current default)**: fall back to the anchor-class descendants above. **You must explicitly tell the source skill's report step** that the soil-package valueset constraint was not enforced, so the run summary calls it out as a known gap. Every soil-package run without `nmdc-submission-schema` should produce a "valueset constraint not enforced" line in the report — silent fall-back is a bug.

> **Future seam.** This subsection will be promoted to its own `nmdc-soil-curation.md` the first time a second package's guidance lands here (water, sediment, host-associated, built-environment). Until then, additions for non-soil packages should live alongside this section in matching subsections so the future split stays mechanical.
