"""Apply the two-tier MFD->ENVO env-triad crosswalk to PRJNA1071982.

The NCBI biosamples for the Microflora Danica project encode habitat in the
free-text `isolation_source` field at MFD Level 1 only (e.g. "Soil from Natural
Dunes"). This script resolves the three MIxS env-triad slots from two tiers:

  PRIMARY (L2)  -- biosample `MFDID` -> data/mfd_habitat_per_sample.tsv ->
                   habitat 5-tuple (sampletype, areatype, hab1, hab2, hab3) ->
                   data/mfd_envo_crosswalk_l2.tsv, matched at the deepest
                   available habitat depth.
  FALLBACK (L1) -- biosample `isolation_source` -> data/mfd_envo_crosswalk_l1.tsv,
                   for biosamples that do not join the per-sample habitat table.

Both crosswalks are TSV (no hardcoded mapping). Every ENVO CURIE in them was
runoak-validated when the crosswalk was built.

Resolution is deterministic: a mapped biosample has all three slots (re)set
from the crosswalk -- a CURIE where the crosswalk has one, or the
`ENVO:00000000` sentinel where it refuses. `has_raw_value` is never touched.

Reads:
  - results/ncbi_PRJNA1071982_nmdc.json
  - results/ncbi_PRJNA1071982_nmdc_curation_inputs.json
  - results/ncbi_PRJNA1071982_nmdc_curation_report.json
  - data/mfd_habitat_per_sample.tsv   (run scripts/build_mfd_habitat_table.py first)
  - data/mfd_envo_crosswalk_l2.tsv
  - data/mfd_envo_crosswalk_l1.tsv

Writes (in place):
  - results/ncbi_PRJNA1071982_nmdc.json
  - results/ncbi_PRJNA1071982_nmdc_curation_report.json
"""

import csv
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RESULTS = REPO / "results"
DATA = REPO / "data"

NMDC_JSON = RESULTS / "ncbi_PRJNA1071982_nmdc.json"
INPUTS = RESULTS / "ncbi_PRJNA1071982_nmdc_curation_inputs.json"
REPORT = RESULTS / "ncbi_PRJNA1071982_nmdc_curation_report.json"
HABITAT_TSV = DATA / "mfd_habitat_per_sample.tsv"
L2_TSV = DATA / "mfd_envo_crosswalk_l2.tsv"
L1_TSV = DATA / "mfd_envo_crosswalk_l1.tsv"

SENTINEL = "ENVO:00000000"
SENTINEL_NAME = "(not provided)"
SLOTS = ("env_broad_scale", "env_local_scale", "env_medium")
# crosswalk column prefix per env-triad slot
SLOT_COL = {
    "env_broad_scale": "env_broad",
    "env_local_scale": "env_local",
    "env_medium": "env_medium",
}

_BARCODE_RE = re.compile(r"^MFD\d{4,6}$")


def norm_barcode(value) -> str:
    """Normalize an MFD barcode (uppercase, fix the MDF->MFD typo).

    Copied from scripts/build_mfd_habitat_table.py -- scripts/ is not a package.
    """
    s = ("" if value is None else str(value)).strip().upper().replace(" ", "")
    if s.startswith("MDF"):
        s = "MFD" + s[3:]
    return s if _BARCODE_RE.match(s) else ""


# --------------------------------------------------------------------------
# Crosswalk + habitat-table loaders
# --------------------------------------------------------------------------


def load_l2() -> dict:
    """L2 crosswalk indexed by (sample_type, area_type, hab1, hab2, hab3)."""
    index = {}
    with L2_TSV.open() as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            key = (r["sample_type"], r["area_type"],
                   r["hab1"], r["hab2"], r["hab3"])
            index[key] = r
    return index


def load_l1() -> dict:
    """L1 crosswalk indexed by (sample_type, area_mfdo1_label)."""
    index = {}
    with L1_TSV.open() as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            index[(r["sample_type"], r["area_mfdo1_label"])] = r
    return index


def load_habitat() -> dict:
    """Per-sample habitat table indexed by normalized barcode."""
    index = {}
    with HABITAT_TSV.open() as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            bc = norm_barcode(r["fieldsample_barcode"])
            if bc:
                index[bc] = r
    return index


# --------------------------------------------------------------------------
# Two-tier resolution
# --------------------------------------------------------------------------


def resolve(bsm_id, mfdid_by_bsm, iso_by_bsm, habitat, l2, l1) -> dict | None:
    """Resolve a biosample to a crosswalk row.

    Returns a dict {tier, ident, key_desc, row} or None when unmapped.
    PRIMARY: MFDID -> habitat 5-tuple -> L2, deepest depth first.
    FALLBACK: isolation_source -> L1.
    """
    mfdid = mfdid_by_bsm.get(bsm_id, "")
    hab = habitat.get(mfdid) if mfdid else None
    if hab:
        st, at = hab["mfd_sampletype"].strip(), hab["mfd_areatype"].strip()
        h1 = hab["mfd_hab1"].strip()
        h2 = hab["mfd_hab2"].strip()
        h3 = hab["mfd_hab3"].strip()
        if h1:  # an L2 row always has hab1; sampletype-only habitat rows skip
            for depth, key in ((3, (st, at, h1, h2, h3)),
                               (2, (st, at, h1, h2, "")),
                               (1, (st, at, h1, "", ""))):
                row = l2.get(key)
                if row:
                    desc = "/".join(p for p in key if p) + f" (depth {depth})"
                    return {"tier": "l2", "ident": mfdid,
                            "key_desc": desc, "row": row}

    iso = iso_by_bsm.get(bsm_id, "")
    if " from " in iso:
        stype, area = iso.split(" from ", 1)
        row = l1.get((stype.strip(), area.strip()))
        if row:
            return {"tier": "l1", "ident": iso,
                    "key_desc": f"{stype.strip()} / {area.strip()}", "row": row}
    return None


def evidence_for(res: dict, committed: bool, slot: str) -> list[dict]:
    """Tier-aware evidence rows for the curation report."""
    if res["tier"] == "l2":
        src_a = ("biosample.attributes.MFDID", res["ident"])
        src_b = ("data/mfd_envo_crosswalk_l2.tsv", res["key_desc"])
    else:
        src_a = ("biosample.attributes.isolation_source", res["ident"][:80])
        src_b = ("data/mfd_envo_crosswalk_l1.tsv", res["key_desc"])
    note = (f"{slot} from MFD habitat crosswalk" if committed
            else f"no anchor-valid ENVO term for {slot} at this habitat")
    return [
        {"source": src_a[0], "quote_or_paraphrase": src_a[1]},
        {"source": src_b[0], "quote_or_paraphrase": f"{src_b[1]} — {note}"},
    ]


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main() -> None:
    nmdc = json.loads(NMDC_JSON.read_text())
    inputs = json.loads(INPUTS.read_text())
    report = json.loads(REPORT.read_text())

    l2, l1, habitat = load_l2(), load_l1(), load_habitat()

    mfdid_by_bsm, iso_by_bsm = {}, {}
    for bsm_id, payload in inputs["biosamples"].items():
        attrs = payload.get("attributes", {}) or {}
        mfdid_by_bsm[bsm_id] = norm_barcode(attrs.get("MFDID")
                                            or attrs.get("isolate") or "")
        iso_by_bsm[bsm_id] = attrs.get("isolation_source") or ""

    row_index = {(r["biosample_id"], r["slot"]): r for r in report["rows"]}

    tier_counts = {"l2": 0, "l1": 0, "unmapped": 0}
    depth_counts = {1: 0, 2: 0, 3: 0}
    committed = {s: 0 for s in SLOTS}
    sentinel = {s: 0 for s in SLOTS}

    for bsm in nmdc["biosample_set"]:
        bsm_id = bsm["id"]
        res = resolve(bsm_id, mfdid_by_bsm, iso_by_bsm, habitat, l2, l1)
        if res is None:
            # Unmapped: no habitat join and no L1 match. Leave the JSON slots
            # untouched but make the report rows consistent (clears any stale
            # evidence from a prior run).
            tier_counts["unmapped"] += 1
            for slot in SLOTS:
                row = row_index.get((bsm_id, slot))
                if row is None:
                    continue
                row["outcome"] = "left_sentinel"
                row["committed_curie"] = None
                row["committed_label"] = None
                row["candidates_considered"] = []
                row["evidence"] = [
                    {"source": "biosample.attributes.isolation_source",
                     "quote_or_paraphrase":
                         (iso_by_bsm.get(bsm_id) or "")[:80] or "(none)"},
                    {"source": "mfd-env-triad two-tier crosswalk",
                     "quote_or_paraphrase":
                         "no L2 habitat join and no L1 isolation_source match"},
                ]
                row["validator"] = {"info_ok": None, "anchor_ok": None,
                                    "valueset_ok": None}
            continue
        tier_counts[res["tier"]] += 1
        if res["tier"] == "l2":
            depth_counts[int(res["key_desc"].rsplit("depth ", 1)[1].rstrip(")"))] += 1

        for slot in SLOTS:
            col = SLOT_COL[slot]
            curie = res["row"][f"{col}_curie"]
            label = res["row"][f"{col}_label"]
            row = row_index.get((bsm_id, slot))
            is_commit = bool(curie) and curie != SENTINEL

            if is_commit:
                bsm[slot]["term"]["id"] = curie
                bsm[slot]["term"]["name"] = label
                committed[slot] += 1
            else:
                # deterministic: reset to sentinel even if a prior run committed
                bsm[slot]["term"]["id"] = SENTINEL
                bsm[slot]["term"]["name"] = SENTINEL_NAME
                sentinel[slot] += 1

            if row is None:
                continue
            row["evidence"] = evidence_for(res, is_commit, slot)
            row["candidates_considered"] = []
            if is_commit:
                row["outcome"] = "predicted"
                row["committed_curie"] = curie
                row["committed_label"] = label
                row["validator"] = {"info_ok": True, "anchor_ok": True,
                                    "valueset_ok": None}
            else:
                row["outcome"] = "left_sentinel"
                row["committed_curie"] = None
                row["committed_label"] = None
                row["validator"] = {"info_ok": None, "anchor_ok": None,
                                    "valueset_ok": None}

    NMDC_JSON.write_text(json.dumps(nmdc, indent=2))
    REPORT.write_text(json.dumps(report, indent=2))

    total = sum(tier_counts.values())
    print(f"Resolved {total} biosamples:")
    print(f"  tier L2 (MFDID -> habitat -> L2 crosswalk): {tier_counts['l2']}"
          f"   (depth1={depth_counts[1]} depth2={depth_counts[2]} "
          f"depth3={depth_counts[3]})")
    print(f"  tier L1 (isolation_source -> L1 crosswalk): {tier_counts['l1']}")
    print(f"  unmapped (untouched)                      : {tier_counts['unmapped']}")
    print("Per-slot outcome (committed / left sentinel):")
    for slot in SLOTS:
        print(f"  {slot:16s}: {committed[slot]:6d} / {sentinel[slot]}")


if __name__ == "__main__":
    main()
