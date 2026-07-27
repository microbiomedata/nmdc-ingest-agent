"""Tests for the generalized env-triad crosswalk resolver.

Covers the synthetic-fixture behavior of CrosswalkEnvTriadResolver plus a parity
check against the real MicroFlora Danica annotated crosswalk (skipped when that
data file is not present, e.g. CI without the data dir).
"""

from pathlib import Path

import pytest

from nmdc_ingest_agent.sources.ncbi.env_triad_crosswalk import (
    CrosswalkEnvTriadResolver,
    _parse_combined,
)


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        if (parent / "pyproject.toml").exists():
            return parent
    return here.parent


def test_parse_combined_good_cell():
    assert _parse_combined("temperate broadleaf forest biome [ENVO:01000202]") == (
        "ENVO:01000202",
        "temperate broadleaf forest biome",
    )


@pytest.mark.parametrize("value", ["", "   ", "soil with no curie", "soil [not-a-curie]"])
def test_parse_combined_rejects_bad_cells(value):
    assert _parse_combined(value) is None


@pytest.fixture
def crosswalk_tsv(tmp_path) -> Path:
    """A tiny annotated-crosswalk TSV with one full row and one partial row."""
    path = tmp_path / "biosamples_annotated.tsv"
    header = "\t".join(
        ["fieldsample_barcode", "env_broad_scale", "env_local_scale", "env_medium"]
    )
    rows = [
        header,
        "\t".join(
            [
                "MFD00001",
                "temperate broadleaf forest biome [ENVO:01000202]",
                "temperate freshwater swamp forest [ENVO:01000398]",
                "soil [ENVO:00001998]",
            ]
        ),
        # Partial row: env_local_scale cell is empty -> that slot is skipped.
        "\t".join(
            ["MFD09999", "marine biome [ENVO:00000447]", "", "sediment [ENVO:00002007]"]
        ),
    ]
    path.write_text("\n".join(rows) + "\n")
    return path


def test_from_tsv_missing_file_returns_none(tmp_path):
    assert CrosswalkEnvTriadResolver.from_tsv(tmp_path / "nope.tsv") is None


def test_from_tsv_no_path_no_env_returns_none(monkeypatch):
    # No built-in default file: without a path or env var, there is no resolver.
    monkeypatch.delenv("NMDC_ENV_TRIAD_CROSSWALK_TSV", raising=False)
    monkeypatch.delenv("NMDC_MFD_CROSSWALK_TSV", raising=False)
    assert CrosswalkEnvTriadResolver.from_tsv() is None


def test_from_tsv_reads_env_var(crosswalk_tsv, monkeypatch):
    monkeypatch.setenv("NMDC_ENV_TRIAD_CROSSWALK_TSV", str(crosswalk_tsv))
    resolver = CrosswalkEnvTriadResolver.from_tsv()
    assert resolver is not None
    assert resolver.resolve({"sample_name": "MFD00001"})["env_medium"].term.id == "ENVO:00001998"


def test_from_tsv_reads_legacy_env_var(crosswalk_tsv, monkeypatch):
    monkeypatch.delenv("NMDC_ENV_TRIAD_CROSSWALK_TSV", raising=False)
    monkeypatch.setenv("NMDC_MFD_CROSSWALK_TSV", str(crosswalk_tsv))  # back-compat name
    assert CrosswalkEnvTriadResolver.from_tsv() is not None


def test_resolve_full_row_by_sample_name(crosswalk_tsv):
    resolver = CrosswalkEnvTriadResolver.from_tsv(crosswalk_tsv)
    assert resolver is not None

    terms = resolver.resolve({"sample_name": "MFD00001", "attributes": {}})
    assert terms is not None
    assert terms["env_broad_scale"].term.id == "ENVO:01000202"
    assert terms["env_broad_scale"].term.name == "temperate broadleaf forest biome"
    assert terms["env_local_scale"].term.id == "ENVO:01000398"
    assert terms["env_medium"].term.id == "ENVO:00001998"
    # No NCBI raw value to preserve.
    assert not terms["env_broad_scale"].has_raw_value


def test_resolve_falls_back_to_configured_attribute(crosswalk_tsv):
    # The attribute fallback is opt-in: only used when key_attribute is configured.
    resolver = CrosswalkEnvTriadResolver.from_tsv(crosswalk_tsv, key_attribute="MFDID")
    terms = resolver.resolve(
        {"sample_name": "Soil sample 1", "attributes": {"MFDID": "MFD00001"}}
    )
    assert terms is not None
    assert terms["env_medium"].term.id == "ENVO:00001998"


def test_attribute_fallback_off_by_default(crosswalk_tsv):
    # Without key_attribute, a non-matching sample_name does not consult attributes.
    resolver = CrosswalkEnvTriadResolver.from_tsv(crosswalk_tsv)
    assert resolver.resolve(
        {"sample_name": "Soil sample 1", "attributes": {"MFDID": "MFD00001"}}
    ) is None


def test_resolve_partial_row_skips_unparseable_slot(crosswalk_tsv):
    resolver = CrosswalkEnvTriadResolver.from_tsv(crosswalk_tsv)
    terms = resolver.resolve({"sample_name": "MFD09999", "attributes": {}})
    assert terms is not None
    assert "env_broad_scale" in terms and "env_medium" in terms
    # Empty cell -> slot omitted so the translator keeps its sentinel.
    assert "env_local_scale" not in terms


def test_resolve_unknown_key_returns_none(crosswalk_tsv):
    resolver = CrosswalkEnvTriadResolver.from_tsv(crosswalk_tsv)
    assert resolver.resolve({"sample_name": "SRS123", "attributes": {}}) is None
    assert resolver.resolve({"sample_name": "MFD55555", "attributes": {}}) is None


# --- Parity: the real MFD crosswalk resolves MFD00001 via sample_name -----------

def _mfd_annotated_tsv() -> Path | None:
    p = _repo_root() / "examples/microflora-danica/crosswalk/mfd_biosamples_annotated.tsv"
    return p if p.exists() else None


def test_mfd_parity_first_barcode():
    """The real annotated crosswalk resolves MFD00001's env_broad_scale to the
    documented ENVO:01000202 via sample_name alone (byte-for-byte parity with the
    pre-refactor MfdEnvTriadResolver, which keyed on the same barcode)."""
    tsv = _mfd_annotated_tsv()
    if tsv is None:
        pytest.skip("MFD annotated crosswalk not present")
    resolver = CrosswalkEnvTriadResolver.from_tsv(tsv)
    assert resolver is not None
    terms = resolver.resolve({"sample_name": "MFD00001", "attributes": {}})
    assert terms is not None
    assert terms["env_broad_scale"].term.id == "ENVO:01000202"
    assert terms["env_broad_scale"].term.name == "temperate broadleaf forest biome"
