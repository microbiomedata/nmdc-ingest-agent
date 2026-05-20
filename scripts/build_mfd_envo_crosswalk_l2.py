"""Generate the Level-2/3 MFD habitat -> ENVO env-triad crosswalk.

The Level-1 crosswalk (`data/mfd_envo_crosswalk_l1.tsv`) maps at MFD area-level
granularity -- `(sample_type, area_mfdo1_label)` -- which is too coarse to
resolve ~2,586 env-triad sentinels. This script builds the finer
`data/mfd_envo_crosswalk_l2.tsv`, one row per MFD habitat-ontology combo
`(sample_type, area_type, hab1, hab2, hab3)`.

Two stages, both reproducible from this script:

  1. CARRY-FORWARD -- each L2 row inherits the already-runoak-validated
     hab1-level ENVO triple from the matching L1 row (`curation_status`
     `carried_l1`). Combos with no L1 match start all-sentinel (`new`).

  2. CURATION -- the `CURATION` table below applies hab2/hab3-specific
     refinements. Every ENVO CURIE in it was validated in a runoak session
     (ENVO via `sqlite:obo:envo`) on 2026-05-19 with `runoak info` (exists,
     label, not deprecated) and `runoak ancestors -p i` (the slot anchor
     appears): env_broad_scale ENVO:00000428, env_local_scale ENVO:01000813,
     env_medium ENVO:00010483. Slots with no anchor-valid term stay
     `ENVO:00000000` -- refuse rather than guess (nmdc-curation-rules Rule 4).

Inputs (read-only):
  - data/mfd_habitat_ontology.xlsx     (vendored; cmc-aau/mfd_metadata @ b1b17d4)
  - data/mfd_envo_crosswalk_l1.tsv     (the renamed Level-1 crosswalk)

Writes:
  - data/mfd_envo_crosswalk_l2.tsv

Requires: openpyxl (stdlib otherwise).
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import openpyxl

REPO = Path(__file__).resolve().parent.parent
ONTOLOGY = REPO / "data" / "mfd_habitat_ontology.xlsx"
L1_TSV = REPO / "data" / "mfd_envo_crosswalk_l1.tsv"
OUT_TSV = REPO / "data" / "mfd_envo_crosswalk_l2.tsv"

SENTINEL = "ENVO:00000000"
AREA_TYPES = {"Natural", "Urban", "Subterranean", "Agriculture"}
# L1 rows with no habitat-ontology combo: fallback-only buckets for samples
# whose MFD habitat (hab1) is unknown.
EXPECTED_UNMATCHED_L1 = {"NA", "Natural"}

COLUMNS = [
    "sample_type", "area_type", "hab1", "hab2", "hab3", "hab_depth",
    "env_broad_curie", "env_broad_label",
    "env_local_curie", "env_local_label",
    "env_medium_curie", "env_medium_label",
    "curation_status", "notes",
]

# --------------------------------------------------------------------------
# CURATION TABLE -- hab2/hab3 refinements, keyed by (sample_type, area_type,
# hab1). Every CURIE runoak-validated 2026-05-19 (see module docstring).
# Per-key fields (all optional): broad / local / medium = (curie, label);
# local_by_hab2 = {hab2_label: (curie, label)} overriding `local`; note.
# --------------------------------------------------------------------------
ANTHRO_BIOME = ("ENVO:01000219", "anthropogenic terrestrial biome")

CURATION: dict[tuple, dict] = {
    # Marine sediment mislabelled "Subterranean" by MFD -- hab2 (Open sea /
    # Fjords / Oceanic) shows it is open-sea benthic, not subterranean.
    # Corrects the L1 "cave" local pick and the broad sentinel.
    ("Sediment", "Subterranean", "Saltwater"): {
        "broad": ("ENVO:00000447", "marine biome"),
        "medium": ("ENVO:03000033", "marine sediment"),
        "local": ("ENVO:00000016", "sea"),
        "local_by_hab2": {"Fjords": ("ENVO:00000039", "fjord")},
        "note": "hab2 (Open sea/Fjords/Oceanic) = open-sea benthic sediment; "
                "corrects L1 'cave'. marine biome/sea/fjord/marine sediment "
                "runoak-validated.",
    },
    # Constructed freshwater -- rainwater/retention basins = ponds.
    ("Sediment", "Urban", "Freshwater"): {
        "local": ("ENVO:00000033", "pond"),
        "note": "hab3 rainwater/retention basins -> pond (runoak-validated). "
                "Resolves the L1 env_local sentinel.",
    },
    # Constructed saltwater -- harbours / marinas.
    ("Sediment", "Urban", "Saltwater"): {
        "local": ("ENVO:00000463", "harbour"),
        "note": "hab3 'Harbour, marina' -> harbour (runoak-validated). "
                "Resolves the L1 env_local sentinel.",
    },
    # Groundwater -- not a cave. No anchor-valid env_local feature term
    # (groundwater & aquifer both fail ENVO:01000813); refuse env_local
    # rather than keep the wrong 'cave'. groundwater is the medium.
    ("Water", "Subterranean", "Freshwater"): {
        "local": (SENTINEL, ""),
        "medium": ("ENVO:01001004", "groundwater"),
        "note": "hab2 Groundwater: corrects L1 'cave' (groundwater/aquifer "
                "fail the env_local anchor -> refuse); env_medium refined to "
                "groundwater (runoak-validated).",
    },
    # Rocky slopes -> cliff; caves keep 'cave'.
    ("Soil", "Natural", "Rocky habitats and caves"): {
        "local_by_hab2": {
            "Rocky slopes with vegetation": ("ENVO:00000087", "cliff"),
        },
        "note": "hab2 'Rocky slopes with vegetation' -> cliff "
                "(runoak-validated); 'Other rocky habitats' keeps cave.",
    },
    # Wetland family -- runoak re-confirmed there is NO anchor-valid env_local
    # feature term (fen / bog / mire / peatland / marsh all fail ENVO:01000813).
    ("Soil", "Natural", "Bogs, mires and fens"): {
        "note": "env_local stays sentinel: runoak re-confirmed fen/bog/mire/"
                "peatland/marsh all fail the env_local anchor ENVO:01000813.",
    },
    # --- combos absent from L1 (curation_status was 'new') ---
    ("Soil", "Urban", "Landfill"): {
        "broad": ANTHRO_BIOME, "local": ("ENVO:00000533", "landfill"),
        "medium": ("ENVO:00001998", "soil"),
        "note": "Urban landfill; landfill/anthropogenic terrestrial biome "
                "runoak-validated. Not present in L1.",
    },
    ("Water", "Urban", "Landfill"): {
        "broad": ANTHRO_BIOME, "local": ("ENVO:00000533", "landfill"),
        "medium": ("ENVO:00002141", "leachate"),
        "note": "hab2 Leachate -> leachate medium; landfill local. "
                "All runoak-validated. Not present in L1.",
    },
    ("Other", "Urban", "Landfill"): {
        "broad": ANTHRO_BIOME, "local": ("ENVO:00000533", "landfill"),
        "note": "Urban landfill; sample_type 'Other' -> env_medium left "
                "sentinel. Not present in L1.",
    },
    ("Soil", "Urban", "Industrial"): {
        "broad": ANTHRO_BIOME, "medium": ("ENVO:00001998", "soil"),
        "note": "Urban industrial soil; no hab2 -> env_local sentinel. "
                "Not present in L1.",
    },
    ("Other", "Urban", "Industrial"): {
        "broad": ANTHRO_BIOME,
        "local_by_hab2": {
            "High chalk concentration (limestone quarry)":
                ("ENVO:00000284", "quarry"),
            "High salinity (saltworks)":
                ("ENVO:00000055", "saline evaporation pond"),
        },
        "note": "hab2 limestone quarry -> quarry, saltworks -> saline "
                "evaporation pond (runoak-validated). Not present in L1.",
    },
    ("Soil", "Urban", "Other"): {
        "note": "'Other' is intentionally non-specific; env_local sentinel "
                "kept (carried from L1).",
    },
    ("Water", "Urban", "Other"): {
        "broad": ANTHRO_BIOME, "medium": ("ENVO:00002006", "liquid water"),
        "note": "'Other' urban water; env_local sentinel. Not present in L1.",
    },
    ("Other", "Urban", "Other"): {
        "broad": ANTHRO_BIOME,
        "note": "'Other' is intentionally non-specific. Not present in L1.",
    },
    ("Other", "Urban", "Saltwater"): {
        "broad": ANTHRO_BIOME, "local": ("ENVO:00000463", "harbour"),
        "note": "hab3 'Harbour, marina' -> harbour (runoak-validated). "
                "Not present in L1.",
    },
    ("Other", "Urban", "Drinking water"): {
        "broad": ANTHRO_BIOME, "medium": ("ENVO:00003064", "drinking water"),
        "note": "Drinking-water infrastructure; no anchor-valid env_local "
                "feature term. Not present in L1.",
    },
}


def clean(value) -> str:
    return "" if value is None else str(value).strip()


def area_key(area_type: str) -> str:
    """Normalize an area type for L1 matching ('Agriculture (reclaimed lowland)'
    carries forward from the plain 'Agriculture' L1 row)."""
    return area_type.split(" (")[0].strip()


def load_ontology_combos() -> list[tuple]:
    """Return the distinct (sample_type, area_type, hab1, hab2, hab3) combos."""
    wb = openpyxl.load_workbook(ONTOLOGY, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    seen: set[tuple] = set()
    combos: list[tuple] = []
    for row in list(ws.iter_rows(values_only=True))[1:]:
        if not row or not clean(row[0]):
            continue
        combo = (clean(row[0]), clean(row[1]), clean(row[3]),
                 clean(row[5]), clean(row[7]))
        if combo not in seen:
            seen.add(combo)
            combos.append(combo)
    return combos


def load_l1_index() -> tuple[dict, list]:
    """Index the L1 crosswalk by (sample_type, area_type, hab1)."""
    index: dict[tuple, dict] = {}
    l1_rows: list[dict] = []
    with L1_TSV.open() as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            l1_rows.append(r)
            parts = r["area_mfdo1_label"].split(None, 1)
            area_type = parts[0] if parts else ""
            hab1 = parts[1] if len(parts) > 1 else ""
            if area_type not in AREA_TYPES:
                continue
            index[(r["sample_type"], area_type, hab1)] = r
    return index, l1_rows


def apply_curation(row: dict) -> bool:
    """Apply a CURATION entry to `row` in place. Returns True if a slot changed."""
    entry = CURATION.get((row["sample_type"], row["area_type"], row["hab1"]))
    if entry is None:
        return False
    changed = False
    for slot in ("broad", "local", "medium"):
        pick = entry.get(slot)
        if slot == "local" and entry.get("local_by_hab2", {}).get(row["hab2"]):
            pick = entry["local_by_hab2"][row["hab2"]]
        if pick is None:
            continue
        curie, label = pick
        if row[f"env_{slot}_curie"] != curie:
            changed = True
        row[f"env_{slot}_curie"] = curie
        row[f"env_{slot}_label"] = label
    if "note" in entry:
        row["notes"] = entry["note"]
    return changed


def main() -> None:
    combos = load_ontology_combos()
    l1_index, l1_rows = load_l1_index()

    rows: list[dict] = []
    carried = new = refined = 0
    matched_l1_keys: set[tuple] = set()

    for sample_type, area_type, hab1, hab2, hab3 in combos:
        depth = 3 if hab3 else (2 if hab2 else 1)
        l1_key = (sample_type, area_key(area_type), hab1)
        l1 = l1_index.get(l1_key)
        if l1:
            matched_l1_keys.add(l1_key)
            triple = {f"env_{s}_{k}": l1[f"env_{s}_{k}"]
                      for s in ("broad", "local", "medium")
                      for k in ("curie", "label")}
            status = "carried_l1"
            note = f"Inherited hab1-level triple from L1 ({sample_type} {l1['area_mfdo1_label']})."
        else:
            triple = {f"env_{s}_{k}": (SENTINEL if k == "curie" else "")
                      for s in ("broad", "local", "medium")
                      for k in ("curie", "label")}
            status = "new"
            note = "No L1 match — needs curation."
        row = {
            "sample_type": sample_type, "area_type": area_type,
            "hab1": hab1, "hab2": hab2, "hab3": hab3, "hab_depth": depth,
            **triple, "curation_status": status, "notes": note,
        }
        if apply_curation(row):
            row["curation_status"] = "refined"
            refined += 1
        elif status == "carried_l1":
            carried += 1
        else:
            new += 1
        rows.append(row)

    rows.sort(key=lambda r: (r["sample_type"], r["area_type"],
                             r["hab1"], r["hab2"], r["hab3"]))

    with OUT_TSV.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, delimiter="\t",
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    # ----- report -----
    depth_hist = {1: 0, 2: 0, 3: 0}
    sentinel_slots = {"broad": 0, "local": 0, "medium": 0}
    for r in rows:
        depth_hist[r["hab_depth"]] += 1
        for s in ("broad", "local", "medium"):
            if r[f"env_{s}_curie"] == SENTINEL:
                sentinel_slots[s] += 1
    print(f"Wrote {len(rows)} L2 rows -> {OUT_TSV.relative_to(REPO)}")
    print(f"  carried_l1: {carried}   refined: {refined}   new (uncurated): {new}")
    print(f"  hab_depth histogram: depth1={depth_hist[1]} "
          f"depth2={depth_hist[2]} depth3={depth_hist[3]}")
    print(f"  rows still sentinel per slot: broad={sentinel_slots['broad']} "
          f"local={sentinel_slots['local']} medium={sentinel_slots['medium']}")

    unmatched = [
        r["area_mfdo1_label"] for r in l1_rows
        if r["area_mfdo1_label"] not in EXPECTED_UNMATCHED_L1
        and (lambda p: (r["sample_type"], p[0] if p else "",
                        p[1] if len(p) > 1 else ""))(
            r["area_mfdo1_label"].split(None, 1)) not in matched_l1_keys
    ]
    if unmatched:
        print("  WARNING — L1 rows that matched zero ontology combos:")
        for label in unmatched:
            print(f"    - {label!r}")
    else:
        print("  OK — every habitat-bearing L1 row carried forward.")


if __name__ == "__main__":
    sys.exit(main())
