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

## Two-tier crosswalk

The MFD habitat → ENVO mapping is **two tiers**. Resolve a biosample primary-first:

**Primary — Level 2/3, per-sample habitat.** The biosample's `MFDID` attribute (the MFD
field-sample barcode, e.g. `MFD00001`) joins to [`data/mfd_habitat_per_sample.tsv`](../../data/mfd_habitat_per_sample.tsv),
which carries the full MFD habitat classification `(mfd_sampletype, mfd_areatype, hab1,
hab2, hab3)`. That 5-tuple looks up [`data/mfd_envo_crosswalk_l2.tsv`](../../data/mfd_envo_crosswalk_l2.tsv)
(one row per MFD habitat-ontology combo), matched at the **deepest available depth**:
try `(st,at,h1,h2,h3)`, then `(st,at,h1,h2)`, then `(st,at,h1)`.

**Fallback — Level 1, isolation_source.** When the biosample has no `MFDID` join (barcode
absent from the habitat table), split `isolation_source` ("Soil from Natural Dunes") on
`" from "` into `(sample_type, area_mfdo1_label)` and look up [`data/mfd_envo_crosswalk_l1.tsv`](../../data/mfd_envo_crosswalk_l1.tsv).

Why two tiers: `isolation_source` is a lossy MFD **Level-1** projection — "Soil from
Natural Dunes" cannot distinguish Sea vs Inland dunes, and "Subterranean Saltwater"
actually means open-sea benthic sediment. The per-sample habitat table recovers hab2/hab3
detail for the ~77% of biosamples that carry a joinable `MFDID`. L1 and the depth-1 rows
of L2 are kept mutually consistent.

`ENVO:00000000` in any `*_curie` column (with an empty `*_label`) is the **refuse
sentinel**: no ENVO term passes that slot's anchor class. Leave the sentinel and proceed
to `nmdc-env-triad.md` §1b inference for that slot only — other slots can still commit.

### Example L2 rows

| sample_type / area_type / hab1 / hab2 | `env_broad_scale` | `env_local_scale` | `env_medium` |
|---|---|---|---|
| Soil / Natural / Forests / Temperate forests | `ENVO:01000174` forest biome | `ENVO:01001243` forest ecosystem | `ENVO:00001998` soil |
| Sediment / Subterranean / Saltwater / Fjords | `ENVO:00000447` marine biome | `ENVO:00000039` fjord | `ENVO:03000033` marine sediment |
| Sediment / Urban / Freshwater / Standing freshwater | `ENVO:01000219` anthropogenic terrestrial biome | `ENVO:00000033` pond | `ENVO:00002007` sediment |
| Soil / Natural / Bogs, mires and fens / Calcareous fens | `ENVO:01000190` flooded savanna biome | `ENVO:00000000` (refuse) | `ENVO:00005774` peat soil |

### Loading the crosswalks

```python
import csv, pathlib

def load(name):
    with pathlib.Path(f"data/{name}").open() as f:
        return list(csv.DictReader(f, delimiter="\t"))

l2 = {(r["sample_type"], r["area_type"], r["hab1"], r["hab2"], r["hab3"]): r
      for r in load("mfd_envo_crosswalk_l2.tsv")}
l1 = {(r["sample_type"], r["area_mfdo1_label"]): r
      for r in load("mfd_envo_crosswalk_l1.tsv")}
habitat = {r["fieldsample_barcode"]: r
           for r in load("mfd_habitat_per_sample.tsv")}

def resolve(mfdid, isolation_source):
    h = habitat.get(mfdid)
    if h and h["mfd_hab1"]:
        st, at, h1 = h["mfd_sampletype"], h["mfd_areatype"], h["mfd_hab1"]
        h2, h3 = h["mfd_hab2"], h["mfd_hab3"]
        for key in ((st,at,h1,h2,h3), (st,at,h1,h2,""), (st,at,h1,"","")):
            if key in l2:
                return l2[key]                       # primary
    if " from " in isolation_source:
        st, area = isolation_source.split(" from ", 1)
        return l1.get((st.strip(), area.strip()))    # fallback
    return None
# Skip slots where r[f"env_{slot}_curie"] == "ENVO:00000000" — refuse via §1b.
```

`scripts/apply_mfd_env_triad.py` is the programmatic implementation of exactly this.

## Validation rules

1. **Validate every candidate.** Per `nmdc-env-triad.md` §2, run `runoak -i sqlite:obo:envo info <CURIE>` and `runoak -i sqlite:obo:envo ancestors -p i <CURIE>` against every CURIE you commit. Anchor class membership for each slot:
   - `env_broad_scale` → must descend from `ENVO:00000428` (biome)
   - `env_local_scale` → must descend from `ENVO:01000813` (astronomical body part)
   - `env_medium` → must descend from `ENVO:00010483` (environmental material)
2. **A crosswalk row is a candidate, not a commit.** All entries passed runoak validation when the table was last refreshed, but ENVO evolves — if the validator fails today, treat the row as a bug to fix, not as a reason to bypass validation.
3. **Refuse rather than guess.** `ENVO:00000000` indicates no ENVO term exists under the slot's anchor class. Leave the sentinel for that slot and proceed to the `nmdc-env-triad.md` §1b Inference path for that slot only (the other slots in the same biosample can still commit if their crosswalk picks validate).
4. **Evidence anchor.** Per `nmdc-curation-rules.md` Rule 1, every commit records its tier in the curation report's `evidence` list — primary: `biosample.attributes.MFDID` + `data/mfd_envo_crosswalk_l2.tsv` with the habitat key and matched depth; fallback: `biosample.attributes.isolation_source` + `data/mfd_envo_crosswalk_l1.tsv`.

## Caveat: post-MIMAG-exclusion

The pipeline filter `_is_mag_package` in `translate.py` (merged in PR #15) excludes `MIMAG.6.0` / `MISAG.6.0` biosamples — the **only** records in PRJNA1071982 that carry MFDO labels. Surviving Metagenome.environmental.1.0 biosamples have empty env-triad raws and hit the §1b inference path, not §1a — so this crosswalk does not currently apply to that pilot's ingest output.

This skill remains useful for:
- Future BioProjects that reuse the MFDO vocabulary on non-MAG biosamples.
- Re-import paths that keep MAG records (e.g. a future `MetagenomeAssembly` extension).
- Manual curation of historical MFD records.

## Maintaining the crosswalks

The build pipeline (run in order — see [`scripts/README.md`](../../scripts/README.md)):

1. `scripts/build_mfd_habitat_table.py` → `data/mfd_habitat_per_sample.tsv` — normalizes
   the per-project MFD metadata (cmc-aau/mfd_metadata, pinned commit) into one
   barcode-keyed habitat table.
2. `scripts/build_mfd_envo_crosswalk_l2.py` → `data/mfd_envo_crosswalk_l2.tsv` — enumerates
   the habitat-ontology combos, carries forward the validated hab1-level ENVO triples from
   L1, then applies the `CURATION` table (hab2/hab3 refinements).
3. `scripts/apply_mfd_env_triad.py` — applies the two-tier crosswalk to a curation run.

**Where edits go:**

- **L2 hab2/hab3 refinements** → the `CURATION` dict in `build_mfd_envo_crosswalk_l2.py`,
  then regenerate. Every CURIE there is runoak-validated; the dict comments record it.
- **L1 rows** → `data/mfd_envo_crosswalk_l1.tsv` directly (hand-maintained).
- **L1 ⇄ L2 consistency:** the depth-1 (hab1-level) rows of L2 must agree with L1. When a
  curation establishes a better hab1-level term, update *both*.

When adding or refining an ENVO CURIE (either file):

1. Run `runoak -i sqlite:obo:envo search "<head noun>"` to surface candidates.
2. For each, run `runoak ancestors -p i <CURIE>` and verify the slot anchor appears
   (`ENVO:00000428` broad, `ENVO:01000813` local, `ENVO:00010483` medium).
3. Run `runoak info <CURIE>` — exists, label correct, not deprecated.
4. Commit the finer term only if it is strictly more specific and both checks pass;
   otherwise leave `ENVO:00000000` (refuse rather than guess).

See [`data/README.md`](../../data/README.md) for the TSV schema conventions and
`nmdc-curation-rules.md` Rule 6 (no CURIEs from memory).
