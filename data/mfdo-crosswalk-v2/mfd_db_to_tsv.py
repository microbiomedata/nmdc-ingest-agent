"""Extract biosample rows from the MFD database xlsx for use with apply_crosswalk.py.

Fetches (or reads locally) the MFD biosample database from cmc-aau/mfd_metadata
and writes a TSV with the columns apply_crosswalk.py expects.

Usage:
  python3 mfd_db_to_tsv.py                          # fetch from pinned commit
  python3 mfd_db_to_tsv.py --ref main               # fetch latest
  python3 mfd_db_to_tsv.py --local db.xlsx          # use a local xlsx file
  python3 mfd_db_to_tsv.py --out biosamples.tsv     # write to file
"""

import csv
import io
import os
import sys
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import click

MFD_RAW_BASE = "https://raw.githubusercontent.com/cmc-aau/mfd_metadata"
MFD_DEFAULT_REF = "b1b17d4b4e8e289c4380d878c8bf1516eb107791"
DB_REPO_PATH = "analysis/releases/2025-05-28_mfd_db.xlsx"

# Columns to extract from the db xlsx (in output order)
# These match the column names apply_crosswalk.py expects
OUTPUT_COLS = [
    "fieldsample_barcode",
    "mfd_sampletype", "mfd_areatype",
    "mfd_hab1_code", "mfd_hab1",
    "mfd_hab2_code", "mfd_hab2",
    "mfd_hab3_code", "mfd_hab3",
    "latitude", "longitude", "coords_reliable",
]

NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _col_letter_to_index(col: str) -> int:
    result = 0
    for ch in col.upper():
        result = result * 26 + (ord(ch) - ord("A") + 1)
    return result - 1


def _parse_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        with zf.open("xl/sharedStrings.xml") as f:
            root = ET.parse(f).getroot()
    except KeyError:
        return []
    strings = []
    for si in root.findall("a:si", NS):
        parts = [t.text or "" for t in si.findall(".//a:t", NS)]
        strings.append("".join(parts))
    return strings


def _parse_sheet(zf: zipfile.ZipFile, sheet_path: str,
                 shared: list[str]) -> tuple[list[str], list[list[str]]]:
    with zf.open(sheet_path) as f:
        root = ET.parse(f).getroot()
    rows_xml = root.findall(".//a:sheetData/a:row", NS)
    header: list[str] = []
    data_rows: list[list[str]] = []
    for row_xml in rows_xml:
        cells_by_col: dict[int, str] = {}
        for cell in row_xml.findall("a:c", NS):
            ref = cell.get("r", "")
            col_str = "".join(ch for ch in ref if ch.isalpha())
            col_idx = _col_letter_to_index(col_str)
            t = cell.get("t", "")
            v_el = cell.find("a:v", NS)
            value = ""
            if v_el is not None and v_el.text is not None:
                if t == "s":
                    try:
                        value = shared[int(v_el.text)]
                    except (IndexError, ValueError):
                        value = v_el.text
                else:
                    value = v_el.text
            cells_by_col[col_idx] = value
        if not cells_by_col:
            continue
        max_col = max(cells_by_col) + 1
        row_vals = [cells_by_col.get(i, "") for i in range(max_col)]
        if not header:
            header = row_vals
        else:
            data_rows.append(row_vals)
    return header, data_rows


def extract_biosamples(xlsx_bytes: bytes) -> list[dict]:
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as zf:
        shared = _parse_shared_strings(zf)
        # Find the first sheet
        sheet_path = "xl/worksheets/sheet1.xml"
        if sheet_path not in zf.namelist():
            for name in zf.namelist():
                if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
                    sheet_path = name
                    break
        header, data_rows = _parse_sheet(zf, sheet_path, shared)

    col_index = {name: i for i, name in enumerate(header)}
    missing = [c for c in OUTPUT_COLS if c not in col_index]
    if missing:
        click.echo(f"Warning: columns not found in db xlsx: {missing}", err=True)

    results = []
    for row in data_rows:
        record: dict[str, str] = {}
        for col in OUTPUT_COLS:
            idx = col_index.get(col)
            record[col] = row[idx] if idx is not None and idx < len(row) else ""
        results.append(record)
    return results


@click.command()
@click.option("--ref", default=MFD_DEFAULT_REF, show_default=True,
              help="cmc-aau/mfd_metadata git ref to fetch the db xlsx from")
@click.option("--local", "local_path", default=None,
              type=click.Path(exists=True, dir_okay=False),
              help="Use a local xlsx file instead of fetching from GitHub")
@click.option("--out", default="-", help="Output TSV path (default: stdout)")
def main(ref, local_path, out):
    """Extract MFD biosample rows from the database xlsx for use with apply_crosswalk.py."""
    if local_path:
        click.echo(f"Reading {local_path}", err=True)
        xlsx_bytes = Path(local_path).read_bytes()
    else:
        url = f"{MFD_RAW_BASE}/{ref}/{DB_REPO_PATH}"
        click.echo(f"Fetching {url}", err=True)
        with urllib.request.urlopen(url, timeout=120) as r:
            xlsx_bytes = r.read()

    click.echo("Parsing xlsx...", err=True)
    rows = extract_biosamples(xlsx_bytes)
    click.echo(f"Extracted {len(rows)} biosample rows", err=True)

    fh = open(out, "w", newline="", encoding="utf-8") if out != "-" else sys.stdout
    try:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_COLS, delimiter="\t",
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    finally:
        if fh is not sys.stdout:
            fh.close()


if __name__ == "__main__":
    main()
