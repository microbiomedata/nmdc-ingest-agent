"""Tests for the MFD env-triad resolver (v2 MFDO crosswalk)."""

from pathlib import Path

import pytest

from nmdc_ingest_agent.sources.ncbi.mfd import MfdEnvTriadResolver, _parse_combined


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
    path = tmp_path / "mfd_biosamples_annotated.tsv"
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
    assert MfdEnvTriadResolver.from_tsv(tmp_path / "nope.tsv") is None


def test_resolve_full_row(crosswalk_tsv):
    resolver = MfdEnvTriadResolver.from_tsv(crosswalk_tsv)
    assert resolver is not None

    terms = resolver.resolve(
        {"sample_name": "MFD00001", "attributes": {"MFDID": "MFD00001"}}
    )
    assert terms is not None
    assert terms["env_broad_scale"].term.id == "ENVO:01000202"
    assert terms["env_broad_scale"].term.name == "temperate broadleaf forest biome"
    assert terms["env_local_scale"].term.id == "ENVO:01000398"
    assert terms["env_medium"].term.id == "ENVO:00001998"
    # No NCBI raw value to preserve.
    assert not terms["env_broad_scale"].has_raw_value


def test_resolve_falls_back_to_mfdid_attribute(crosswalk_tsv):
    resolver = MfdEnvTriadResolver.from_tsv(crosswalk_tsv)
    # sample_name is not an MFD barcode, but the MFDID attribute is.
    terms = resolver.resolve(
        {"sample_name": "Soil sample 1", "attributes": {"MFDID": "MFD00001"}}
    )
    assert terms is not None
    assert terms["env_medium"].term.id == "ENVO:00001998"


def test_resolve_partial_row_skips_unparseable_slot(crosswalk_tsv):
    resolver = MfdEnvTriadResolver.from_tsv(crosswalk_tsv)
    terms = resolver.resolve({"sample_name": "MFD09999", "attributes": {}})
    assert terms is not None
    assert "env_broad_scale" in terms
    assert "env_medium" in terms
    # Empty cell -> slot omitted so the translator keeps its sentinel.
    assert "env_local_scale" not in terms


def test_resolve_non_mfd_sample_returns_none(crosswalk_tsv):
    resolver = MfdEnvTriadResolver.from_tsv(crosswalk_tsv)
    assert resolver.resolve({"sample_name": "SRS123", "attributes": {}}) is None


def test_resolve_unknown_barcode_returns_none(crosswalk_tsv):
    resolver = MfdEnvTriadResolver.from_tsv(crosswalk_tsv)
    assert resolver.resolve({"sample_name": "MFD55555", "attributes": {}}) is None
