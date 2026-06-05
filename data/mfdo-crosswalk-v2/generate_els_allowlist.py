"""Generate the ELS allow-list and verify ENVO CURIEs in land-cover mapping TSVs.

The ELS allow-list is the set of ENVO classes valid as env_local_scale values:
descendants of five anchor roots minus biomes and materials.

Anchor roots:
  ENVO:01000813  astronomical body part
  ENVO:01001209  wetland ecosystem
  ENVO:01001790  terrestrial ecosystem
  ENVO:01000408  environmental zone
  ENVO:01000355  vegetation layer

Excluded (overlap with env_broad_scale / env_medium):
  ENVO:00000428  biome
  ENVO:00010483  environmental material

Usage:
  uv run --extra ontology python3 generate_els_allowlist.py
  uv run --extra ontology python3 generate_els_allowlist.py --no-update
  uv run --extra ontology python3 generate_els_allowlist.py --data-dir /path/to/dir
"""

import csv
import sys
from pathlib import Path

import click

ELS_ROOTS = {
    "ENVO:01000813": "astronomical body part",
    "ENVO:01001209": "wetland ecosystem",
    "ENVO:01001790": "terrestrial ecosystem",
    "ENVO:01000408": "environmental zone",
    "ENVO:01000355": "vegetation layer",
}
EXCLUDE_ROOTS = {
    "ENVO:00000428": "biome",
    "ENVO:00010483": "environmental material",
}
MAPPING_FILES = ["corine_envo_map.tsv", "worldcover_envo_map.tsv"]


def build_allowlist() -> tuple[dict[str, dict], set[str]]:
    from oaklib import get_adapter
    adapter = get_adapter("sqlite:obo:envo")
    allowlist: dict[str, dict] = {}
    for root_curie, root_label in ELS_ROOTS.items():
        click.echo(f"  descendants of {root_curie} ({root_label})...", err=True)
        for curie in adapter.descendants(root_curie, predicates=["rdfs:subClassOf"]):
            if curie not in allowlist:
                allowlist[curie] = {"label": adapter.label(curie) or "", "anchor_roots": set()}
            allowlist[curie]["anchor_roots"].add(root_label)
    exclude: set[str] = set()
    for root_curie, root_label in EXCLUDE_ROOTS.items():
        click.echo(f"  excluding descendants of {root_curie} ({root_label})...", err=True)
        for curie in adapter.descendants(root_curie, predicates=["rdfs:subClassOf"]):
            exclude.add(curie)
        exclude.add(root_curie)
    before = len(allowlist)
    for curie in list(allowlist):
        if curie in exclude:
            del allowlist[curie]
    click.echo(f"  {before} before exclusion -> {len(allowlist)} after", err=True)
    return allowlist, exclude


def _detect_col(cols: list[str], suffix: str) -> str:
    for c in cols:
        if c.endswith(suffix):
            return c
    click.echo(f"Cannot detect column with suffix {suffix!r} in {cols}", err=True)
    sys.exit(1)


def verify_mapping_file(path: Path, allowlist: dict, exclude: set,
                        code_col: str, label_col: str) -> int:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    fieldnames = list(rows[0].keys()) if rows else []
    updated = 0
    for row in rows:
        status = row.get("ols_verified", "")
        els = (row.get("env_local_scale") or "").strip()
        if not els:
            continue
        curie, stated_label = None, ""
        if "[" in els and "]" in els:
            curie = els[els.rfind("[") + 1:els.rfind("]")].strip()
            stated_label = els[:els.rfind("[")].strip()
        if not curie:
            continue

        # Determine the verdict from scratch for every row that carries a CURIE, so an
        # already-'yes' row with a wrong CURIE or a mislabeled CURIE is downgraded.
        # ols_verified=yes requires BOTH: anchor-valid AND the stated label matches the
        # ENVO official label. Label concordance is what catches a fabricated CURIE whose
        # term happens to sit under a valid anchor (e.g. 'coastal lagoon [ENVO:00000399]'
        # where ENVO:00000399 is actually 'ash cone').
        if curie not in allowlist:
            verdict = "fails_anchor:excluded" if curie in exclude else "fails_anchor:not_in_envo"
        else:
            official = (allowlist[curie]["label"] or "").strip()
            if stated_label.casefold() != official.casefold():
                verdict = f"fails_label:is_{official!r}"
            else:
                verdict = "yes"

        if status in ("needs_verification", "yes") and row.get("ols_verified") != verdict:
            row["ols_verified"] = verdict
            updated += 1
            click.echo(f"    {row[code_col]} {row[label_col][:40]:40} -> {verdict} ({curie})", err=True)
        elif status == "needs_verification":
            row["ols_verified"] = verdict
            updated += 1
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return updated


@click.command()
@click.option("--data-dir", default=None, type=click.Path(exists=True, file_okay=False),
              help="Directory with mapping TSVs and where els_allowlist.tsv is written. "
                   "Default: same directory as this script.")
@click.option("--no-update", is_flag=True,
              help="Generate the allow-list only; do not update mapping TSVs.")
@click.option("--mapping-files", default=",".join(MAPPING_FILES),
              help=f"Comma-separated mapping TSV filenames to verify. "
                   f"Default: {','.join(MAPPING_FILES)}")
def main(data_dir, no_update, mapping_files):
    """Generate the ELS allow-list from ENVO and verify land-cover mapping TSVs."""
    data_dir = Path(data_dir) if data_dir else Path(__file__).parent
    click.echo("Building ELS allow-list from ENVO...", err=True)
    allowlist, exclude = build_allowlist()

    allowlist_path = data_dir / "els_allowlist.tsv"
    with allowlist_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["envo_curie", "envo_label", "anchor_roots"],
                           delimiter="\t")
        w.writeheader()
        for curie, info in sorted(allowlist.items()):
            w.writerow({"envo_curie": curie, "envo_label": info["label"],
                        "anchor_roots": "|".join(sorted(info["anchor_roots"]))})
    click.echo(f"Wrote {len(allowlist)} rows to {allowlist_path}", err=True)

    if no_update:
        return

    for fname in mapping_files.split(","):
        fname = fname.strip()
        path = data_dir / fname
        if not path.exists():
            click.echo(f"Skipping {fname} (not found)", err=True)
            continue
        with path.open(newline="", encoding="utf-8") as f:
            cols = list(csv.DictReader(f, delimiter="\t").fieldnames or [])
        code_col = _detect_col(cols, "_code")
        label_col = _detect_col(cols, "_label")
        click.echo(f"\nVerifying {fname}...", err=True)
        n = verify_mapping_file(path, allowlist, exclude, code_col, label_col)
        click.echo(f"  Updated {n} rows", err=True)

    click.echo("\nDone.", err=True)


if __name__ == "__main__":
    main()
