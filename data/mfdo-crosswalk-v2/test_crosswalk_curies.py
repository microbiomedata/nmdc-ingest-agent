"""Anchor-class validation for every ENVO CURIE that can reach a biosample triad.

Guards against the failure mode behind
https://github.com/microbiomedata/nmdc-ingest-agent/issues/42 (a wrong CURIE in
the committed crosswalk) and the fabricated CURIEs found during review: each
env_broad_scale / env_local_scale / env_medium value must sit under the correct
ENVO anchor class for its slot.

Covers:
- every triad CURIE in mfdo_nmdc_crosswalk.tsv
- every ols_verified=yes ELS CURIE in the land-cover map TSVs (these are the
  values GEE refinement can substitute into env_local_scale)

Requires the `ontology` extra (oaklib + ENVO). Run:
    uv run --extra ontology python3 -m pytest data/mfdo-crosswalk-v2/test_crosswalk_curies.py -v

oaklib downloads and caches the ENVO sqlite on first run. The test skips
cleanly if oaklib is not installed.
"""

import csv
from pathlib import Path

import pytest

pytest.importorskip("oaklib", reason="requires the 'ontology' extra (oaklib + ENVO)")
from oaklib import get_adapter  # noqa: E402

HERE = Path(__file__).parent
SUBCLASS = ["rdfs:subClassOf"]

# ENVO anchor classes per triad slot (see build_ontology_crosswalk.py / README ELS allow-list).
EBS_ANCHOR = "ENVO:00000428"   # biome
EM_ANCHOR = "ENVO:00010483"    # environmental material
ELS_ROOTS = [
    "ENVO:01000813",  # astronomical body part
    "ENVO:01001209",  # wetland ecosystem
    "ENVO:01001790",  # terrestrial ecosystem
    "ENVO:01000408",  # environmental zone
    "ENVO:01000355",  # vegetation layer
]
ELS_EXCLUDE_ROOTS = [EBS_ANCHOR, EM_ANCHOR]  # biomes and materials are not ELS values


def _curie(cell: str) -> str:
    """Extract the CURIE from a 'label [CURIE]' cell; '' if none."""
    cell = (cell or "").strip()
    if "[" in cell and "]" in cell:
        return cell[cell.rfind("[") + 1:cell.rfind("]")].strip()
    return ""


def _label_curie(cell: str):
    """Return (stated_label, curie) from a 'label [CURIE]' cell; ('', '') if none."""
    cell = (cell or "").strip()
    if "[" in cell and "]" in cell:
        return cell[:cell.rfind("[")].strip(), cell[cell.rfind("[") + 1:cell.rfind("]")].strip()
    return "", ""


def _all_label_curie_cells():
    """Yield (source, label, curie) for every 'label [CURIE]' triad/ELS cell in the
    committed artifacts: crosswalk triad columns and the land-cover map ELS columns."""
    for row in _crosswalk_rows():
        for col in ("env_broad_scale", "env_local_scale", "env_medium"):
            lbl, cur = _label_curie(row[col])
            if cur:
                yield f"crosswalk {col} ({_row_label(row)})", lbl, cur
    for map_file in ("corine_envo_map.tsv", "worldcover_envo_map.tsv"):
        with (HERE / map_file).open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                lbl, cur = _label_curie(row.get("env_local_scale", ""))
                if cur:
                    yield f"{map_file} ({row.get(list(row)[1])})", lbl, cur


@pytest.fixture(scope="module")
def adapter():
    return get_adapter("sqlite:obo:envo")


@pytest.fixture(scope="module")
def allowed(adapter):
    """Return {'ebs': set, 'els': set, 'em': set} of valid CURIEs per slot."""
    def desc(curie):
        return set(adapter.descendants(curie, predicates=SUBCLASS)) | {curie}

    ebs = desc(EBS_ANCHOR)
    em = desc(EM_ANCHOR)
    els_pos = set().union(*(desc(r) for r in ELS_ROOTS))
    els_neg = set().union(*(desc(r) for r in ELS_EXCLUDE_ROOTS))
    els = els_pos - els_neg
    return {"ebs": ebs, "els": els, "em": em}


def _crosswalk_rows():
    with (HERE / "mfdo_nmdc_crosswalk.tsv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _row_label(row):
    return "/".join(row.get(lv, "") for lv in
                    ("mfd_sampletype", "mfd_areatype", "mfd_hab1", "mfd_hab2", "mfd_hab3"))


def test_env_broad_scale_under_biome(allowed):
    bad = []
    for row in _crosswalk_rows():
        c = _curie(row["env_broad_scale"])
        if not c or c not in allowed["ebs"]:
            bad.append(f"{_row_label(row)}: env_broad_scale={row['env_broad_scale']!r}")
    assert not bad, "env_broad_scale CURIEs not under biome [ENVO:00000428]:\n" + "\n".join(bad)


def test_env_local_scale_in_allowlist(allowed):
    bad = []
    for row in _crosswalk_rows():
        c = _curie(row["env_local_scale"])
        if not c or c not in allowed["els"]:
            bad.append(f"{_row_label(row)}: env_local_scale={row['env_local_scale']!r}")
    assert not bad, "env_local_scale CURIEs not in the ELS allow-list:\n" + "\n".join(bad)


def test_env_medium_under_material(allowed):
    bad = []
    for row in _crosswalk_rows():
        c = _curie(row["env_medium"])
        if not c or c not in allowed["em"]:
            bad.append(f"{_row_label(row)}: env_medium={row['env_medium']!r}")
    assert not bad, "env_medium CURIEs not under environmental material [ENVO:00010483]:\n" + "\n".join(bad)


@pytest.mark.parametrize("map_file,label_col", [
    ("corine_envo_map.tsv", "corine_label"),
    ("worldcover_envo_map.tsv", "worldcover_label"),
])
def test_landcover_map_verified_els_in_allowlist(allowed, map_file, label_col):
    """Every ols_verified=yes ELS term in a land-cover map must be allow-list valid,
    since GEE refinement substitutes these into env_local_scale."""
    path = HERE / map_file
    bad = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if (row.get("ols_verified") or "").strip() != "yes":
                continue
            c = _curie(row.get("env_local_scale", ""))
            if not c or c not in allowed["els"]:
                bad.append(f"{row.get(label_col)}: env_local_scale={row.get('env_local_scale')!r}")
    assert not bad, f"{map_file} ols_verified=yes ELS not in allow-list:\n" + "\n".join(bad)


def test_label_curie_concordance(adapter):
    """Every 'label [CURIE]' cell must state the CURIE's official ENVO label.

    This is the gate that catches a CURIE typed from memory whose term happens to sit
    under a valid anchor (so the anchor checks above pass) but is not the term named --
    e.g. 'coastal lagoon [ENVO:00000399]' where ENVO:00000399 is actually 'ash cone'.
    """
    bad = []
    for source, stated, curie in _all_label_curie_cells():
        official = (adapter.label(curie) or "").strip()
        if stated.casefold() != official.casefold():
            bad.append(f"{source}: states {stated!r} but {curie} is {official!r}")
    assert not bad, "label/CURIE mismatches (CURIE is not the term named):\n" + "\n".join(bad)
