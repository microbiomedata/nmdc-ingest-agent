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

The full 25-row crosswalk lives at [`data/mfd_envo_crosswalk.tsv`](../../data/mfd_envo_crosswalk.tsv) — that file is the single source of truth and the artifact downstream tooling consumes. The agent **must** load that TSV when curating an MFD biosample; the examples below are just enough to show the shape.

`(refuse via §1b)` is encoded as `ENVO:00000000` in any of the three `*_curie` columns, with the matching `*_label` left empty. This means no good ENVO term exists for that slot under the slot's anchor class — the agent leaves the sentinel and proceeds to `nmdc-env-triad.md` §1b inference for that slot only (other slots in the same biosample can still commit if their crosswalk picks validate).

Every CURIE in the TSV is a *candidate*, not a commit. Per `nmdc-env-triad.md` §2, run `runoak info <CURIE>` and `runoak ancestors -p i <CURIE>` against each pick before flipping the curation-report row off `left_sentinel`.

### Example rows (5 of 25)

Sample counts come from PRJNA1071982's pre-MIMAG-exclusion dataset; see the TSV for all rows.

| Sample Type | Area + MFDO1 | n | `env_broad_scale` | `env_local_scale` | `env_medium` | Pattern |
|---|---|---:|---|---|---|---|
| Soil | Agriculture Fields | 180 | `ENVO:01000245` cropland biome | `ENVO:00000114` agricultural field | `ENVO:00002259` agricultural soil | Gold-standard — every slot has a precise term. |
| Soil | Natural Forests | 648 | `ENVO:01000174` forest biome | `ENVO:01001243` forest ecosystem | `ENVO:00001998` soil | Clean — modal soil case. |
| Water | Urban Wastewater | 622 | `ENVO:01000219` anthropogenic terrestrial biome | `ENVO:00002043` wastewater treatment plant | `ENVO:00002001` waste water | Built-environment, water sample type. |
| Sediment | Natural Saltwater | 171 | `ENVO:00000447` marine biome | `ENVO:00000485` sea shore | `ENVO:03000033` marine sediment | Sediment sample type → different env_medium. |
| Soil | Natural Dunes | 263 | `ENVO:00000000` (refuse) | `ENVO:00000170` dune | `ENVO:00001998` soil | Partial — no "dune biome" in ENVO. Defer broad to §1b. |

### Loading the full crosswalk

```python
import csv, pathlib
with pathlib.Path("data/mfd_envo_crosswalk.tsv").open() as f:
    rows = list(csv.DictReader(f, delimiter="\t"))

def lookup(sample_type: str, area_mfdo1: str) -> dict | None:
    for r in rows:
        if r["sample_type"] == sample_type and r["area_mfdo1_label"] == area_mfdo1:
            return r
    return None

row = lookup("Soil", "Agriculture Fields")
# row["env_broad_curie"] == "ENVO:01000245", etc.
# Skip slots where r[f"env_{slot}_curie"] == "ENVO:00000000" — refuse via §1b.
```

For shell pipelines: `awk -F'\t' 'NR==1 || ($1=="<Sample Type>" && $2=="<label>")' data/mfd_envo_crosswalk.tsv`.

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

Edits go to [`data/mfd_envo_crosswalk.tsv`](../../data/mfd_envo_crosswalk.tsv) — that file is the single source of truth. When the TSV changes meaningfully (new rows, CURIE corrections), refresh the **Example rows** table above by hand-picking 3–5 representative rows from the new TSV. Do not duplicate the entire table here.

When adding a new (Sample Type, Area+MFDO1) tuple to the TSV:

1. Confirm the tuple appears in real data via `jq` on an MFD ingest output (with MIMAG biosamples preserved). Record the integer count as `count_observed`.
2. Run `runoak search "<query terms from the label>"` to surface candidate CURIEs.
3. For each candidate, run `runoak ancestors -p i <CURIE>` and verify the slot's anchor class appears (`ENVO:00000428` for broad, `ENVO:01000813` for local, `ENVO:00010483` for medium).
4. Run `runoak info <CURIE>` to confirm exists + label correct + not deprecated.
5. Add the row to the TSV; record any ambiguity in `notes`; default to `ENVO:00000000` (with an empty label column) rather than a low-confidence pick.
6. Re-sort the TSV by `count_observed` descending.

See [`data/README.md`](../../data/README.md) for the TSV's schema conventions and `nmdc-curation-rules.md` Rule 6 (no CURIEs from memory).
