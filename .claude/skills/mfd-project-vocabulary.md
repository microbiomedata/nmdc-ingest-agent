---
name: mfd-project-vocabulary
description: MFDO (Microflora Danica Ontology) → ENVO crosswalk for biosamples from BioProjects using the MFD habitat classification. Read this when env-triad raws match MFDO patterns — env_broad_scale ∈ {Soil, Water, Sediment} AND env_local_scale starts with one of {Natural, Urban, Subterranean, Agriculture} — typically signalled by geo_loc_name="Denmark" and samp_name matching `^MFD\d+`.
---

# Microflora Danica habitat ontology (MFDO) ⇄ ENVO crosswalk

The MicroFlora Danica project ([Sereika et al., Nature 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC12823411/)) sampled 15,306 biosamples across Denmark using a custom 5-level habitat classification (MFDO). The submitter encoded MFDO labels in NCBI BioSample env-triad fields, mapping to **EMPO / Natura 2000 / EUNIS** but **not** to ENVO. This skill provides the ENVO crosswalk so the agent can resolve MFDO labels to canonical ENVO CURIEs without re-deriving the mapping per run.

## When to use

The source skill (e.g. `ncbi-to-nmdc.md`) hands off here when **all four** signals match on a biosample:

1. `geo_loc_name.has_raw_value == "Denmark"`
2. `samp_name` matches `^MFD\d+` (or `^MFD\d+_`)
3. `env_broad_scale.has_raw_value` ∈ {`Soil`, `Water`, `Sediment`}
4. `env_local_scale.has_raw_value` starts with one of {`Natural`, `Urban`, `Subterranean`, `Agriculture`}

Skip this skill if any signal fails — the biosample may share words with MFDO labels coincidentally.

## MFDO ⇄ MIxS slot misalignment

The submitter mis-slotted MFDO into MIxS:

| MIxS slot | What's actually stored | What MIxS expects |
|---|---|---|
| `env_broad_scale.has_raw_value` | MFDO **Level 1 — Sample type** (`Soil` / `Water` / `Sediment`) — a *material* | a biome |
| `env_local_scale.has_raw_value` | MFDO **Level 2 + Level 3** concatenated (`"Natural Forests"`, `"Urban Wastewater"`, …) | an environmental feature |
| `env_medium.has_raw_value` | Same string as `env_local_scale` (duplicated) | the actual material |

The crosswalk below maps each `(Sample Type, Area+MFDO1)` tuple to candidate CURIEs for **all three MIxS slots** independently — the candidates account for the swap. Do NOT carry the raw strings forward as `term.name` (per `nmdc-curation-rules.md` Rule 5, the official ENVO label belongs in `term.name`; the submitter string stays in `has_raw_value`).

## Crosswalk

Each row lists candidate CURIEs (with labels) for the three MIxS slots, plus a Notes column. The agent **must validate every candidate** with `runoak info <CURIE>` and `runoak ancestors -p i <CURIE>` per `nmdc-env-triad.md` §2 before committing — these are starting points, not authoritative picks. `(refuse via §1b)` means no good ENVO term exists for that slot under the slot's anchor class; the agent leaves the sentinel and proceeds to the §1b inference path for that slot only.

Sample counts come from PRJNA1071982's pre-MIMAG-exclusion dataset.

### Soil sample type

| Area + MFDO1 | n | `env_broad_scale` | `env_local_scale` | `env_medium` | Notes |
|---|---:|---|---|---|---|
| Natural Forests | 648 | `ENVO:01000174` forest biome | `ENVO:01001243` forest ecosystem | `ENVO:00001998` soil | Clean — all three candidates pass anchor checks. |
| Natural Bogs, mires and fens | 295 | `ENVO:01000190` flooded savanna biome | (refuse via §1b) | `ENVO:00005774` peat soil | No ENVO wetland-feature term under `ENVO:01000813`; `peatland` / `wetland ecosystem` / `fen` / `marsh` all fail the anchor. Broad pick is approximate. |
| Natural Dunes | 263 | (refuse via §1b) | `ENVO:00000170` dune | `ENVO:00001998` soil | No specific "dune biome" in ENVO; coastal/desert too broad. Defer broad to §1b. |
| Natural Temperate heath and scrub | 229 | `ENVO:01000176` shrubland biome | `ENVO:00000107` heath | `ENVO:00001998` soil | Reasonable mapping. |
| Natural Grassland formations | 207 | `ENVO:01000177` grassland biome | `ENVO:01001206` grassland ecosystem | `ENVO:00001998` soil | Clean. **Caveat:** `grassland biome` IS-A `grassland ecosystem` per ENVO `is-a` graph — broad is more specific than local. Common MIxS submitter pattern; reviewers see this as expected. |
| Natural Coastal | 160 | `ENVO:00000447` marine biome | `ENVO:00000303` sea coast | `ENVO:00001998` soil | Reasonable; could also use `ENVO:00000485` sea shore for local. |
| Subterranean Urban | 205 | `ENVO:01000249` urban biome | `ENVO:00000067` cave | `ENVO:00001998` soil | Subterranean urban likely means tunnels / basements / underground urban features — `cave` is the closest ENVO term under the feature anchor. Flag for curator review on important records. |
| Urban Greenspaces | 78 | `ENVO:01000249` urban biome | `ENVO:00000562` park | `ENVO:00001998` soil | Clean. |
| Urban Other | 2 | `ENVO:01000219` anthropogenic terrestrial biome | (refuse via §1b) | `ENVO:00001998` soil | "Other" is intentionally non-specific — local feature unknown. |
| Agriculture Fields | 180 | `ENVO:01000245` cropland biome | `ENVO:00000114` agricultural field | `ENVO:00002259` agricultural soil | Gold-standard MFDO ⇄ ENVO mapping — every slot has a precise term. |
| Natural Sclerophyllous scrub | 17 | `ENVO:01000176` shrubland biome | `ENVO:00000300` scrubland area | `ENVO:00001998` soil | Reasonable. |
| Natural Rocky habitats and caves | 1 | (refuse via §1b) | `ENVO:00000067` cave | `ENVO:00001998` soil | No "rocky biome" in ENVO. Only 1 sample; flag for curator review. |
| Natural NA | 28 | (refuse via §1b) | (refuse via §1b) | `ENVO:00001998` soil | `NA` = submitter did not provide MFDO Level 2+3. Only the material is known. |

### Water sample type

| Area + MFDO1 | n | `env_broad_scale` | `env_local_scale` | `env_medium` | Notes |
|---|---:|---|---|---|---|
| Urban Wastewater | 622 | `ENVO:01000219` anthropogenic terrestrial biome | `ENVO:00002043` wastewater treatment plant | `ENVO:00002001` waste water | Clean. |
| Urban Biogas | 453 | `ENVO:01000219` anthropogenic terrestrial biome | (refuse via §1b) | `ENVO:01000556` biogas | ENVO has `biogas` as material but no canonical biogas-reactor feature term. |
| Urban Drinking water | 111 | `ENVO:01000219` anthropogenic terrestrial biome | (refuse via §1b) | `ENVO:00003064` drinking water | No specific feature term for drinking-water infrastructure. |
| Natural Saltwater | 57 | `ENVO:00000447` marine biome | `ENVO:00000485` sea shore | `ENVO:00002006` liquid water | Note: `marine pelagic biome` (`ENVO:01000023`) is also a reasonable broad pick if the sample was open-ocean rather than coastal. |
| Subterranean Freshwater | 84 | (refuse via §1b) | `ENVO:00000067` cave | `ENVO:00002006` liquid water | No "subterranean freshwater biome" in ENVO; cave is the closest feature. |
| Urban Sandfilter | 12 | `ENVO:01000219` anthropogenic terrestrial biome | (refuse via §1b) | `ENVO:00002006` liquid water | Sand filter — no specific ENVO term. |

### Sediment sample type

| Area + MFDO1 | n | `env_broad_scale` | `env_local_scale` | `env_medium` | Notes |
|---|---:|---|---|---|---|
| Urban Saltwater | 210 | `ENVO:01000219` anthropogenic terrestrial biome | (refuse via §1b) | `ENVO:03000033` marine sediment | Constructed saltwater (harbour, marina) — no specific feature term. |
| Natural Saltwater | 171 | `ENVO:00000447` marine biome | `ENVO:00000485` sea shore | `ENVO:03000033` marine sediment | Clean. |
| Subterranean Saltwater | 163 | (refuse via §1b) | `ENVO:00000067` cave | `ENVO:00002007` sediment | No "subterranean marine biome" in ENVO; cave is the closest feature. |
| Natural Freshwater | 160 | `ENVO:00000873` freshwater biome | `ENVO:00000020` lake | `ENVO:00002007` sediment | Lake is the modal water body in Denmark — could also be `ENVO:00000022` river or `ENVO:00000033` pond; check per-sample context if available. |
| Urban Freshwater | 139 | `ENVO:01000219` anthropogenic terrestrial biome | (refuse via §1b) | `ENVO:00002007` sediment | Constructed freshwater (stormwater pond, retention basin) — no clean feature term. |
| Urban Other | 122 | `ENVO:01000219` anthropogenic terrestrial biome | (refuse via §1b) | `ENVO:00002007` sediment | "Other" is intentionally non-specific. |

## Validation rules

1. **Validate every candidate.** Per `nmdc-env-triad.md` §2, run `runoak -i sqlite:obo:envo info <CURIE>` and `runoak -i sqlite:obo:envo ancestors -p i <CURIE>` against every CURIE you commit. Anchor class membership for each slot:
   - `env_broad_scale` → must descend from `ENVO:00000428` (biome)
   - `env_local_scale` → must descend from `ENVO:01000813` (astronomical body part)
   - `env_medium` → must descend from `ENVO:00010483` (environmental material)
2. **A crosswalk row is a candidate, not a commit.** All entries above passed runoak validation when the table was last refreshed, but ENVO evolves — if the validator fails today, treat the row as a bug to fix in this skill, not as a reason to bypass validation.
3. **Refuse rather than guess.** Rows with `(refuse via §1b)` indicate no ENVO term exists under the slot's anchor class. Leave the sentinel for that slot and proceed to the `nmdc-env-triad.md` §1b Inference path for that slot only (the other slots in the same biosample can still commit if their crosswalk picks validate).
4. **Evidence anchor.** Per `nmdc-curation-rules.md` Rule 1, every commit derived from this crosswalk records the source as `"mfd-project-vocabulary crosswalk: <Sample Type> / <Area+MFDO1 label>"` in the curation report's `evidence` list, plus a quote from the biosample's `env_broad_scale.has_raw_value` and `env_local_scale.has_raw_value`.

## Caveat: post-MIMAG-exclusion

The pipeline filter `_is_mag_package` in `translate.py` (merged in PR #15) excludes `MIMAG.6.0` / `MISAG.6.0` biosamples — the **only** records in PRJNA1071982 that carry MFDO labels. Surviving Metagenome.environmental.1.0 biosamples have empty env-triad raws and hit the §1b inference path, not §1a — so this crosswalk does not currently apply to that pilot's ingest output.

This skill remains useful for:
- Future BioProjects that reuse the MFDO vocabulary on non-MAG biosamples.
- Re-import paths that keep MAG records (e.g. a future `MetagenomeAssembly` extension).
- Manual curation of historical MFD records.

## Maintaining this crosswalk

When adding a new (Sample Type, Area+MFDO1) tuple or refreshing CURIE picks:

1. Confirm the tuple appears in real data via `jq` on an MFD ingest output (with MIMAG biosamples preserved).
2. Run `runoak search "<query terms from the label>"` to surface candidate CURIEs.
3. For each candidate, run `runoak ancestors -p i <CURIE>` and verify the slot's anchor class appears.
4. Run `runoak info <CURIE>` to confirm exists + label correct + not deprecated.
5. Add the row; record any ambiguity in Notes; default to `(refuse via §1b)` rather than a low-confidence pick.

See `nmdc-curation-rules.md` Rule 6 — no CURIE picked from memory.
