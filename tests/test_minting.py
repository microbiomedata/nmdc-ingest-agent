"""Tests for the placeholder ID minter."""

from nmdc_ingest_agent.minting import PlaceholderMinter


def test_placeholder_ids_are_unique_at_scale():
    # Regression: a 4-byte blade collided around ~12k ids of one type. Mint well
    # past that and assert no duplicates, within and across calls/types.
    m = PlaceholderMinter()
    ps = m.mint("nmdc:ProcessedSample", 30000)
    assert len(set(ps)) == len(ps) == 30000
    # No cross-call collisions for the same type either.
    more = m.mint("nmdc:ProcessedSample", 5000)
    assert set(ps).isdisjoint(more)
    # Different types use different typecodes.
    lp = m.mint("nmdc:LibraryPreparation", 100)
    assert all(i.startswith("nmdc:procsm-") for i in ps)
    assert all(i.startswith("nmdc:libprp-") for i in lp)


def test_unknown_typecode_raises():
    import pytest

    with pytest.raises(ValueError):
        PlaceholderMinter().mint("nmdc:NotAThing", 1)
