# §1b Inference (missing → prediction)

The inference branch of the env-triad per-placeholder workflow. Reached when a sentinel's `has_raw_value` is empty and `name` is `"(not provided)"` — the source pipeline had nothing to lift, so predict from context, refusing if evidence is thin (per `nmdc-curation-rules` Rule 4).

Anchor classes and the `runoak` invocation pattern are in the skill body (`SKILL.md` § Slot anchor classes, § Runoak setup); the soil-package valueset check is in [`soil-package.md`](soil-package.md).

**Inputs to gather** — from the curation inputs sidecar at `results/ncbi_<ACC>_nmdc_curation_inputs.json`, keyed by NMDC biosample id:

- **MIxS package** (`biosamples.<id>.package`, also exposed on the NMDC biosample's `env_package.has_raw_value`) — picks the package valueset and constrains candidates. E.g. `MIMS.me.soil.6.0` → soil branch; `MIMS.me.water.6.0` → water branch; built-environment, host-associated, plant-associated, and others as defined.
- **Per-sample structured slots already on the NMDC biosample**: `geo_loc_name`, `lat_lon`, `depth`, `elev`, `samp_taxon_id`, `collection_date`, `habitat`, `host_name`, `samp_name`.
- **Per-sample raw NCBI attributes from the sidecar's `attributes` dict** (anything not on the NMDC biosample): `isol_growth_condt`, `ecosystem`, `ecosystem_type`, `ecosystem_subtype`, `specific_ecosystem`, sample-title text from `ncbi_title`.
- **Study-level context from the sidecar's `study` block**: `title`, `description`, any abstracts.
- **Cross-biosample consensus** (gated, ranking signal only): if ≥3 sibling biosamples in the same study have already-resolved (non-sentinel) values that agree on a CURIE for this slot, treat that as a *prior* — but still require per-sample anchor evidence per `nmdc-curation-rules` Rule 1. Consensus alone never commits a value. Mixed-environment studies (soil cores + adjacent water; host-associated + bulk soil) commonly break consensus assumptions; if you use consensus and it disagrees with the per-sample evidence, do not commit.

**Prediction workflow:**

1. Pick the **anchor class** for the slot (the anchor-class table in `SKILL.md` § Slot anchor classes).
2. Pick the **package valueset** if the MIxS package is known. If `nmdc-submission-schema` is importable (see [`soil-package.md`](soil-package.md)), intersect the runoak ancestor-descendants of the anchor class with the package's allowed list. If not, fall back to anchor-class descendants and surface the gap per the soil-package rule.
3. Generate candidate ENVO terms by searching `runoak` with phrases drawn from the gathered inputs. Examples:
   - `geo_loc_name="USA: Oregon"` + `attributes.habitat="Rhizosphere soil"` → search "rhizosphere", "rhizosphere soil", "forest" (per geographic context).
   - `attributes.specific_ecosystem="Soil"` + `attributes.ecosystem_subtype="Rhizosphere"` → "rhizosphere" first.
   - `BioProject.description` mentioning "montane forest soil" → search "temperate coniferous forest biome".
4. Filter candidates: must be a descendant of the slot's anchor class (`runoak ancestors -p i <CURIE>`), and (when applicable) inside the package valueset.
5. Rank by per-sample anchor strength > study-level evidence > sibling-consensus tiebreaker.
6. Apply the **refuse thresholds** below. If they fire, leave sentinel; write `outcome: "left_sentinel"` to the report.
7. Otherwise commit, run `SKILL.md` § Validate every committed CURIE, write the report row with `outcome: "predicted"`, and include evidence rows + candidates considered.

**Refuse thresholds** (the agent must check before committing a prediction):

- No package known AND no per-sample text-bearing slot → leave sentinel.
- Package known but per-sample slots are all empty/sentinel AND siblings disagree → leave sentinel.
- Package known + at least one concrete per-sample slot from this list (`geo_loc_name`, `habitat`, `attributes.isol_growth_condt`, `attributes.ecosystem*`, NCBI sample title containing material/feature words, depth+elev+samp_taxon together) → commit a prediction with cited evidence.
- For `env_medium` specifically: require evidence of the actual sampled material. Pure geographic info alone is not enough (it speaks to biome / feature, not material). Soil package + depth strongly supports a soil-material descendant; water package + lat_lon over ocean supports a water-material descendant.
