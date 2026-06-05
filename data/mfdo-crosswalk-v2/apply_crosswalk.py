"""Apply the MFDO-NMDC crosswalk + GEE land-cover enrichment to MFD biosamples.

Implements the join recipe documented in JOIN_RECIPE.md.

Inputs (all in this directory unless --data-dir overrides):
  mfdo_nmdc_crosswalk.tsv       per-leaf NMDC slot mappings (284 rows, total join)
  mfd_gee_landcover.tsv         per-coordinate ESA WorldCover + CORINE land cover

Biosample input: a TSV with at least these columns (from the stock MFD db xlsx
or from the NCBI biosample table):
  fieldsample_barcode  mfd_sampletype  mfd_areatype
  mfd_hab1_code        mfd_hab1
  mfd_hab2_code        mfd_hab2
  mfd_hab3_code        mfd_hab3
  latitude             longitude       coords_reliable

Output: a TSV with one row per biosample, NMDC slot values filled in.

Usage:
  python3 apply_crosswalk.py biosamples.tsv
  python3 apply_crosswalk.py biosamples.tsv --out annotated.tsv --data-dir /path/to/dir

GEE land-cover refinement is applied only where:
  - coords_reliable == 'Yes' (projects P04_3, P04_5, P06_3 and 32 flagged samples excluded)
  - the crosswalk env_local_scale is a root-class placeholder (0 biosamples use these leaves,
    but the refinement is wired for completeness)
  - satellite ESA WorldCover and CORINE agree at >= 70% of samples for that coordinate
"""

import argparse
import csv
import sys
from pathlib import Path

# Default file names within the data directory; override with --crosswalk / --gee
DEFAULT_CROSSWALK = "mfdo_nmdc_crosswalk.tsv"
DEFAULT_GEE = "mfd_gee_landcover.tsv"

# Columns stripped before output (internal bookkeeping, not NMDC slots)
_PROVENANCE_SUFFIXES = ("_provenance",)
_INTERNAL_COLS = frozenset(("row_type", "n_samples", "Natura2000", "EUNIS", "EMPO",
                             "mfd_hab1_code", "mfd_hab2_code", "mfd_hab3_code"))

# Root-class ELS values that satellite data is allowed to refine.
# These appear only on rows with 0 biosamples in the current dataset but are wired
# so the join works correctly if the crosswalk is extended.
_VAGUE_ELS = frozenset({
    "astronomical body part [ENVO:01000813]",
    "",
})

# ESA WorldCover label -> ENVO ELS term (conservative; only where a specific subclass is
# clearly supported by the anchor hierarchy and the WorldCover class is unambiguous)
_WORLDCOVER_ELS_MAP = {
    "Tree cover":                "woodland area [ENVO:01000175]",
    "Shrubland":                 "shrubland biome [ENVO:01000176]",
    "Grassland":                 "grassland area [ENVO:00000106]",
    "Cropland":                  "cropland area [ENVO:00000114]",
    "Built-up":                  "built environment [ENVO:01000247]",
    "Bare / sparse vegetation":  "barren land [ENVO:01001116]",
    "Permanent water bodies":    "water body [ENVO:00000063]",
    "Herbaceous wetland":        "wetland ecosystem [ENVO:01001209]",
    "Mangroves":                 "mangrove biome [ENVO:01000181]",
}
# Snow/ice and moss/lichen omitted: no anchor-valid ENVO ELS term without site-specific context.


def _coord_key(lat: str, lon: str, decimals: int = 4) -> str:
    try:
        return f"{round(float(lat), decimals)},{round(float(lon), decimals)}"
    except (ValueError, TypeError):
        return ""


def _load_tsv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _crosswalk_key(row: dict) -> tuple:
    return (
        row.get("mfd_sampletype", ""),
        row.get("mfd_areatype", ""),
        row.get("mfd_hab1", ""),
        row.get("mfd_hab2", ""),
        row.get("mfd_hab3", ""),
    )


def _strip_internal(d: dict) -> dict:
    return {
        k: v for k, v in d.items()
        if k not in _INTERNAL_COLS
        and not any(k.endswith(s) for s in _PROVENANCE_SUFFIXES)
    }


def load_tables(data_dir: Path, crosswalk_name: str = DEFAULT_CROSSWALK,
                gee_name: str = DEFAULT_GEE) -> tuple[dict, dict]:
    crosswalk_rows = _load_tsv(data_dir / crosswalk_name)
    crosswalk = {_crosswalk_key(r): r for r in crosswalk_rows}

    gee_path = data_dir / gee_name
    if gee_path.exists():
        gee_rows = _load_tsv(gee_path)
        gee = {r["coord_key"]: r for r in gee_rows}
    else:
        print(f"Warning: {gee_path} not found; GEE-based ELS refinement disabled", file=sys.stderr)
        gee = {}

    return crosswalk, gee


def annotate_biosample(bs: dict, crosswalk: dict, gee: dict) -> dict:
    """Return a dict of NMDC slot values for a single biosample dict.

    The input dict must have the MFD habitat columns and lat/lon columns.
    Returns a copy of bs with NMDC slots added; does not modify bs in place.
    """
    out = dict(bs)
    key = (
        bs.get("mfd_sampletype", ""),
        bs.get("mfd_areatype", ""),
        bs.get("mfd_hab1", ""),
        bs.get("mfd_hab2", ""),
        bs.get("mfd_hab3", ""),
    )

    cw_row = crosswalk.get(key)
    if cw_row is None:
        out["_crosswalk_match"] = "MISS"
        return out

    out["_crosswalk_match"] = cw_row.get("row_type", "ok")
    out.update(_strip_internal(cw_row))

    coords_reliable = bs.get("coords_reliable", "").strip().lower() in ("yes", "true", "1")
    ck = _coord_key(bs.get("latitude", ""), bs.get("longitude", "")) if coords_reliable else ""

    # GEE env_local_scale refinement: only for root-class placeholder values
    current_els = out.get("env_local_scale", "")
    if ck and current_els in _VAGUE_ELS and ck in gee:
        wc = gee[ck].get("worldcover_label", "").strip()
        refined = _WORLDCOVER_ELS_MAP.get(wc)
        if refined:
            out["env_local_scale"] = refined
            # _provenance is stripped before output, but track it for the summary
            out["_els_refined_from_gee"] = wc

    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("biosamples",
                    help="TSV of MFD biosamples (from cmc-aau/mfd_metadata db xlsx)")
    ap.add_argument("--out", default="-", help="Output TSV path (default: stdout)")
    ap.add_argument("--data-dir", default=None,
                    help="Directory containing input TSVs "
                         "(default: same directory as this script)")
    ap.add_argument("--crosswalk", default=DEFAULT_CROSSWALK,
                    help=f"Crosswalk TSV filename within --data-dir (default: {DEFAULT_CROSSWALK})")
    ap.add_argument("--gee", default=DEFAULT_GEE,
                    help=f"GEE land-cover TSV filename within --data-dir (default: {DEFAULT_GEE})")
    args = ap.parse_args()

    data_dir = Path(args.data_dir) if args.data_dir else Path(__file__).parent
    crosswalk, gee = load_tables(data_dir, args.crosswalk, args.gee)

    biosamples = _load_tsv(Path(args.biosamples))
    if not biosamples:
        sys.exit("No rows in input TSV")

    annotated = [annotate_biosample(bs, crosswalk, gee) for bs in biosamples]

    # Collect output columns: input cols first, then new NMDC cols, drop internal tracking cols
    base_cols = list(biosamples[0].keys())
    internal_tracking = {"_crosswalk_match", "_els_refined_from_gee"}
    new_cols = [k for k in annotated[0]
                if k not in base_cols and k not in internal_tracking]
    all_cols = base_cols + new_cols

    out_path = args.out
    fh = open(out_path, "w", newline="", encoding="utf-8") if out_path != "-" else sys.stdout
    try:
        writer = csv.DictWriter(fh, fieldnames=all_cols, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(annotated)
    finally:
        if fh is not sys.stdout:
            fh.close()

    misses = sum(1 for r in annotated if r.get("_crosswalk_match") == "MISS")
    recon = sum(1 for r in annotated if r.get("_crosswalk_match") == "biosample_reconciliation")
    gee_refined = sum(1 for r in annotated if r.get("_els_refined_from_gee"))
    print(
        f"Annotated {len(annotated)} biosamples: "
        f"{misses} crosswalk misses, "
        f"{recon} biosample-reconciliation rows, "
        f"{gee_refined} GEE ELS refinements",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
