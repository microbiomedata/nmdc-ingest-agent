"""Apply the MFDO-NMDC crosswalk + GEE land-cover enrichment to MFD biosamples.

Implements the join recipe documented in JOIN_RECIPE.md.

Inputs (all in --data-dir unless overridden):
  mfdo_nmdc_crosswalk.tsv       per-leaf NMDC slot mappings (284 rows, total join)
  mfd_gee_landcover.tsv         per-coordinate ESA WorldCover + CORINE land cover
  corine_envo_map.tsv           CORINE class -> ENVO ELS (preferred for EU coordinates)
  worldcover_envo_map.tsv       WorldCover class -> ENVO ELS (global fallback)

Biosample input TSV columns (from mfd_db_to_tsv.py or the cmc-aau db xlsx):
  fieldsample_barcode  mfd_sampletype  mfd_areatype
  mfd_hab1_code  mfd_hab1  mfd_hab2_code  mfd_hab2  mfd_hab3_code  mfd_hab3
  latitude  longitude  coords_reliable

GEE ELS refinement fires only when:
  - coords_reliable == 'Yes'
  - the crosswalk env_local_scale is a root-class placeholder
  - CORINE label is checked first (EU coverage, more specific);
    WorldCover used as fallback when CORINE is absent

Usage:
  python3 apply_crosswalk.py biosamples.tsv
  python3 apply_crosswalk.py biosamples.tsv --out annotated.tsv
  python3 apply_crosswalk.py --help
"""

import csv
import sys
from pathlib import Path

import click

DEFAULT_CROSSWALK = "mfdo_nmdc_crosswalk.tsv"
DEFAULT_GEE = "mfd_gee_landcover.tsv"
DEFAULT_CORINE_MAP = "corine_envo_map.tsv"
DEFAULT_WORLDCOVER_MAP = "worldcover_envo_map.tsv"

_PROVENANCE_SUFFIXES = ("_provenance",)
_INTERNAL_COLS = frozenset(("row_type", "n_samples", "Natura2000", "EUNIS", "EMPO",
                             "mfd_hab1_code", "mfd_hab2_code", "mfd_hab3_code"))

# ELS values vague enough that a GEE satellite signal is allowed to refine them.
# "astronomical body part" was the original root-class placeholder; the crosswalk
# now uses "environmental zone" as the preferred fallback per NCBI Import Squad
# decision (2026-06-04). Both are included so the refinement fires correctly
# regardless of which placeholder a crosswalk row carries.
_VAGUE_ELS = frozenset({
    "astronomical body part [ENVO:01000813]",
    "environmental zone [ENVO:01000408]",
    "",
})


def _coord_key(lat: str, lon: str, decimals: int = 4) -> str:
    try:
        return f"{round(float(lat), decimals)},{round(float(lon), decimals)}"
    except (ValueError, TypeError):
        return ""


def _load_tsv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _crosswalk_key(row: dict) -> tuple:
    # strip() removes ASCII whitespace AND Unicode non-breaking space (\xa0), which
    # appears as a trailing character on some MFD db hab3 values (e.g. Beetroot).
    return tuple((row.get(c) or "").strip() for c in
                 ("mfd_sampletype", "mfd_areatype", "mfd_hab1", "mfd_hab2", "mfd_hab3"))


def _strip_internal(d: dict) -> dict:
    return {
        k: v for k, v in d.items()
        if k not in _INTERNAL_COLS
        and not any(k.endswith(s) for s in _PROVENANCE_SUFFIXES)
    }


def _load_els_map(path: Path, label_col: str) -> dict[str, str]:
    """Load a land-cover->EnvO ELS map from a TSV.

    Returns {land_cover_label: envo_els_string} for ols_verified=yes rows only.
    """
    if not path.exists():
        return {}
    els_map = {}
    for row in _load_tsv(path):
        if row.get("ols_verified", "") != "yes":
            continue
        label = (row.get(label_col) or "").strip()
        els = (row.get("env_local_scale") or "").strip()
        if label and els:
            els_map[label] = els
    return els_map


def load_tables(data_dir: Path,
                crosswalk_name: str = DEFAULT_CROSSWALK,
                gee_name: str = DEFAULT_GEE,
                corine_map_name: str = DEFAULT_CORINE_MAP,
                worldcover_map_name: str = DEFAULT_WORLDCOVER_MAP,
                ) -> tuple[dict, dict, dict, dict]:
    crosswalk = {_crosswalk_key(r): r for r in _load_tsv(data_dir / crosswalk_name)}

    gee_path = data_dir / gee_name
    if gee_path.exists():
        gee = {r["coord_key"]: r for r in _load_tsv(gee_path)}
    else:
        click.echo(f"Warning: {gee_path} not found; GEE ELS refinement disabled", err=True)
        gee = {}

    corine_map = _load_els_map(data_dir / corine_map_name, "corine_label")
    worldcover_map = _load_els_map(data_dir / worldcover_map_name, "worldcover_label")

    click.echo(
        f"Loaded: {len(crosswalk)} crosswalk rows, {len(gee)} GEE coordinates, "
        f"{len(corine_map)} CORINE ELS entries, {len(worldcover_map)} WorldCover ELS entries",
        err=True,
    )
    return crosswalk, gee, corine_map, worldcover_map


def annotate_biosample(bs: dict, crosswalk: dict, gee: dict,
                       corine_map: dict, worldcover_map: dict) -> dict:
    out = dict(bs)
    key = _crosswalk_key(bs)

    cw_row = crosswalk.get(key)
    if cw_row is None:
        out["_crosswalk_match"] = "MISS"
        return out

    out["_crosswalk_match"] = cw_row.get("row_type", "ok")
    out.update(_strip_internal(cw_row))

    coords_reliable = bs.get("coords_reliable", "").strip().lower() in ("yes", "true", "1")
    ck = _coord_key(bs.get("latitude", ""), bs.get("longitude", "")) if coords_reliable else ""

    current_els = out.get("env_local_scale", "")
    if ck and current_els in _VAGUE_ELS and ck in gee:
        gee_row = gee[ck]
        corine_label = gee_row.get("corine_label", "").strip()
        wc_label = gee_row.get("worldcover_label", "").strip()

        # Prefer CORINE (EU coverage, 44 classes) over WorldCover (global, 11 classes)
        refined = corine_map.get(corine_label) or worldcover_map.get(wc_label)
        source = "corine" if corine_map.get(corine_label) else "worldcover"
        if refined:
            out["env_local_scale"] = refined
            out["_els_refined_from_gee"] = f"{source}:{corine_label or wc_label}"

    return out


@click.command()
@click.argument("biosamples", type=click.Path(exists=True, dir_okay=False))
@click.option("--out", default="-", help="Output TSV (default: stdout)")
@click.option("--data-dir", default=None, type=click.Path(exists=True, file_okay=False),
              help="Directory containing crosswalk + GEE + map TSVs "
                   "(default: same directory as this script)")
@click.option("--crosswalk", default=DEFAULT_CROSSWALK, show_default=True)
@click.option("--gee", default=DEFAULT_GEE, show_default=True)
@click.option("--corine-map", default=DEFAULT_CORINE_MAP, show_default=True)
@click.option("--worldcover-map", default=DEFAULT_WORLDCOVER_MAP, show_default=True)
def main(biosamples, out, data_dir, crosswalk, gee, corine_map, worldcover_map):
    """Apply the MFDO-NMDC crosswalk + GEE ELS refinement to a MFD biosample TSV."""
    data_dir = Path(data_dir) if data_dir else Path(__file__).parent
    cw, gee_tbl, corine, worldcover = load_tables(
        data_dir, crosswalk, gee, corine_map, worldcover_map)

    rows = _load_tsv(Path(biosamples))
    if not rows:
        click.echo("No rows in input TSV", err=True)
        sys.exit(1)

    annotated = [annotate_biosample(r, cw, gee_tbl, corine, worldcover) for r in rows]

    base_cols = list(rows[0].keys())
    internal = {"_crosswalk_match", "_els_refined_from_gee"}
    new_cols = [k for k in annotated[0] if k not in base_cols and k not in internal]

    fh = open(out, "w", newline="", encoding="utf-8") if out != "-" else sys.stdout
    try:
        writer = csv.DictWriter(fh, fieldnames=base_cols + new_cols,
                                delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(annotated)
    finally:
        if fh is not sys.stdout:
            fh.close()

    misses = sum(1 for r in annotated if r.get("_crosswalk_match") == "MISS")
    recon = sum(1 for r in annotated if r.get("_crosswalk_match") == "biosample_reconciliation")
    gee_refined = sum(1 for r in annotated if r.get("_els_refined_from_gee"))
    click.echo(
        f"Annotated {len(annotated)} biosamples: "
        f"{misses} crosswalk misses, {recon} reconciliation rows, "
        f"{gee_refined} GEE ELS refinements",
        err=True,
    )


if __name__ == "__main__":
    main()
