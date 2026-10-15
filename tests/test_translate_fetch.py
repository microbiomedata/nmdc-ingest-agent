"""Tests for BioSample fetching by accession, the --biosamples roster, and the
ENA split latitude/longitude attributes in the NCBI translator."""

from datetime import datetime, timezone

import pytest

from nmdc_ingest_agent.sources.ncbi import translate as T


def _record(accession, **attrs):
    return {
        "accession": accession,
        "title": "wastewater metagenome",
        "sample_name": accession,
        "organism": "wastewater metagenome",
        "taxonomy_id": "527639",
        "package": "Generic.1.0",
        "models": ["Generic"],
        "attributes": attrs,
    }


# ---------------------------------------------------------------------------
# fetch_biosamples: accession -> UID via esearch, never efetch-by-accession
# ---------------------------------------------------------------------------

def test_fetch_biosamples_resolves_accessions_through_esearch(monkeypatch):
    searched = []

    def fake_esearch(db, term, batch=9999):
        searched.append((db, term))
        return ["10890343", "10890344"]

    fetched = []

    def fake_fetch(ids):
        fetched.append(list(ids))
        return [_record("SAMEA4527675"), _record("SAMEA4527676")]

    monkeypatch.setattr(T, "esearch", fake_esearch)
    monkeypatch.setattr(T, "_fetch_biosample_records", fake_fetch)

    out = T.fetch_biosamples(["SAMEA4527675", "SAMEA4527676"])

    assert [r["accession"] for r in out] == ["SAMEA4527675", "SAMEA4527676"]
    assert searched == [("biosample", "SAMEA4527675[Accession] OR SAMEA4527676[Accession]")]
    # efetch sees only UIDs — the accession strings must never reach it.
    assert fetched == [["10890343", "10890344"]]


def test_fetch_biosamples_batches_esearch_terms(monkeypatch):
    accessions = [f"SAMN{i:08d}" for i in range(T.ACCESSION_ESEARCH_BATCH + 1)]
    terms = []
    monkeypatch.setattr(T, "esearch", lambda db, term, batch=9999: terms.append(term) or [])
    monkeypatch.setattr(T, "_fetch_biosample_records", lambda ids: [])

    T.fetch_biosamples(accessions)

    assert len(terms) == 2
    assert terms[0].count("[Accession]") == T.ACCESSION_ESEARCH_BATCH
    assert terms[1].count("[Accession]") == 1


def test_fetch_biosamples_drops_unrequested_and_reports_missing(monkeypatch, capsys):
    monkeypatch.setattr(T, "esearch", lambda db, term, batch=9999: ["1", "2"])
    # NCBI hands back a record we did not ask for (the efetch-by-accession
    # failure mode) and omits one we did.
    monkeypatch.setattr(
        T, "_fetch_biosample_records",
        lambda ids: [_record("SAMEA4527675"), _record("SAMEA3597051")],
    )

    out = T.fetch_biosamples(["SAMEA4527675", "SAMEA4527676"])

    assert [r["accession"] for r in out] == ["SAMEA4527675"]
    err = capsys.readouterr().out
    assert "not requested: ['SAMEA3597051']" in err
    assert "not found in NCBI: ['SAMEA4527676']" in err


def test_fetch_biosamples_empty_is_noop(monkeypatch):
    monkeypatch.setattr(T, "esearch", lambda *a, **k: pytest.fail("should not search"))
    assert T.fetch_biosamples([]) == []


# ---------------------------------------------------------------------------
# --biosamples roster file
# ---------------------------------------------------------------------------

def test_load_biosample_subset_plain_list(tmp_path):
    p = tmp_path / "roster.txt"
    p.write_text("# one per line\nSAMEA4527610\nSAMN39874936\n\nSAMEA4527610\nSAMD00000001\n")
    assert T.load_biosample_subset(p) == ["SAMEA4527610", "SAMN39874936", "SAMD00000001"]


def test_load_biosample_subset_from_sample_sheet_csv(tmp_path):
    p = tmp_path / "sheet.csv"
    p.write_text(
        "specimen_collector_sample_id,bioproject_accession,biosample_accession,organism\n"
        "CAN.22c,PRJEB13831,SAMEA4527610,wastewater metagenome\n"
        "CHN.64,PRJEB13831,SAMEA4527612,wastewater metagenome\n"
        "blank,PRJEB13831,,wastewater metagenome\n"
    )
    assert T.load_biosample_subset(p) == ["SAMEA4527610", "SAMEA4527612"]


def test_load_biosample_subset_from_tsv(tmp_path):
    p = tmp_path / "sheet.tsv"
    p.write_text("biosample_accession\tnote\nSAMN00000001\tx\n")
    assert T.load_biosample_subset(p) == ["SAMN00000001"]


def test_load_biosample_subset_rejects_non_accessions(tmp_path):
    p = tmp_path / "roster.txt"
    p.write_text("SAMEA4527610\nERR1713342\n")
    with pytest.raises(ValueError, match="ERR1713342"):
        T.load_biosample_subset(p)


def test_load_biosample_subset_empty_is_error(tmp_path):
    p = tmp_path / "roster.txt"
    p.write_text("# nothing here\n")
    with pytest.raises(ValueError):
        T.load_biosample_subset(p)


def test_fetch_all_with_subset_filters_discovered_set(monkeypatch, capsys):
    monkeypatch.setattr(
        T, "fetch_bioproject",
        lambda acc: {"accession": acc, "uid": "518785", "title": "Global sewage"},
    )
    monkeypatch.setattr(
        T, "fetch_sra_experiments",
        lambda acc: [
            {"experiment_accession": "ERX1", "biosample_accession": "SAMEA1"},
            {"experiment_accession": "ERX2", "biosample_accession": "SAMEA2"},
            {"experiment_accession": "ERX3", "biosample_accession": "SAMEA3"},
        ],
    )
    # Discovery runs as usual: elink lists the BioProject's own BioSamples.
    monkeypatch.setattr(T, "fetch_linked_biosample_uids", lambda uid: ["1", "2", "3"])
    monkeypatch.setattr(
        T, "_fetch_biosample_records",
        lambda uids: [_record("SAMEA1"), _record("SAMEA2"), _record("SAMEA3")],
    )
    monkeypatch.setattr(
        T, "fetch_biosamples",
        lambda accs: pytest.fail("a roster must never fetch samples by accession"),
    )

    data = T.fetch_all("PRJEB13831", ["SAMEA2", "SAMEA9"])

    assert [b["accession"] for b in data["biosamples"]] == ["SAMEA2"]
    assert [e["experiment_accession"] for e in data["sra_experiments"]] == ["ERX2"]
    out = capsys.readouterr().out
    assert "not linked to PRJEB13831 and were dropped: ['SAMEA9']" in out
    assert "kept 1 of 3 BioSample(s) and 1 SRA experiment(s)" in out


# ---------------------------------------------------------------------------
# ENA split latitude / longitude attributes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "lat, lon, expected",
    [
        ("10.8231° N", "106.6297° E", (10.8231, 106.6297)),
        ("10.8231� N", "106.6297� E", (10.8231, 106.6297)),  # mangled degree sign
        ("39.8714085 N", "104.2701374 W", (39.8714085, -104.2701374)),
        ("3.3439° S", "37.3293° E", (-3.3439, 37.3293)),
        ("45.8788 S", "170.5028 E", (-45.8788, 170.5028)),
        ("-12.0464", "-77.0428", (-12.0464, -77.0428)),
        ("42.6629° N", "42.6629° N,", None),  # longitude holds a copy of the latitude
        ("95.0 N", "10.0 E", None),  # out of range
        ("not collected", "not collected", None),
        ("10.5 N", "", None),
    ],
)
def test_parse_split_lat_lon(lat, lon, expected):
    assert T.parse_split_lat_lon(lat, lon) == expected


def _biosample(**attrs):
    return T.build_biosample(
        _record("SAMEA4527675", **attrs), "nmdc:sty-99-x", "nmdc:bsm-99-x",
        datetime.now(tz=timezone.utc),
    )


def test_build_biosample_uses_ena_split_coordinates():
    bs = _biosample(**{
        T.ENA_LATITUDE_ATTR: "10.8231� N",
        T.ENA_LONGITUDE_ATTR: "106.6297� E",
    })
    assert (bs.lat_lon.latitude, bs.lat_lon.longitude) == (10.8231, 106.6297)


def test_build_biosample_omits_corrupt_ena_coordinates():
    bs = _biosample(**{
        T.ENA_LATITUDE_ATTR: "42.6629� N",
        T.ENA_LONGITUDE_ATTR: "42.6629� N,",
    })
    assert bs.lat_lon is None


def test_build_biosample_prefers_harmonized_lat_lon():
    bs = _biosample(**{
        "lat_lon": "1.5 N 2.5 E",
        T.ENA_LATITUDE_ATTR: "10.0 N",
        T.ENA_LONGITUDE_ATTR: "20.0 E",
    })
    assert (bs.lat_lon.latitude, bs.lat_lon.longitude) == (1.5, 2.5)


# ---------------------------------------------------------------------------
# ENA-brokered records: sample name and biosample name
# ---------------------------------------------------------------------------

_ENA_BIOSAMPLE_XML = b"""<?xml version="1.0"?>
<BioSampleSet><BioSample access="public" id="10890343" accession="SAMEA4527675">
  <Ids><Id db="BioSample" is_primary="1">SAMEA4527675</Id><Id db="SRA">ERS1426854</Id></Ids>
  <Description><Title>wastewater metagenome</Title>
    <Organism taxonomy_id="527639" taxonomy_name="wastewater metagenome"><OrganismName>wastewater metagenome</OrganismName></Organism>
  </Description>
  <Models><Model>Generic</Model></Models><Package display_name="Generic">Generic.1.0</Package>
  <Attributes>
    <Attribute attribute_name="Submitter Id">VNM.48</Attribute>
    <Attribute attribute_name="sample name" harmonized_name="sample_name" display_name="sample name">VNM.48</Attribute>
    <Attribute attribute_name="sewage_type">colletion tank of wastewater treatment plant</Attribute>
  </Attributes>
</BioSample></BioSampleSet>"""


def test_sample_name_ids_takes_precedence(monkeypatch):
    """NCBI's own submissions (e.g. MFD) promote the value to
    <Ids><Id db_label="Sample name">; that wins when both renderings exist."""
    from lxml import etree
    xml = _ENA_BIOSAMPLE_XML.replace(
        b'<Id db="SRA">ERS1426854</Id>', b'<Id db="SRA">ERS1426854</Id><Id db_label="Sample name">MFD00001</Id>'
    )
    monkeypatch.setattr(T, "efetch_xml", lambda db, ids: [etree.fromstring(xml)])
    [rec] = T._fetch_biosample_records(["10890343"])
    assert rec["sample_name"] == "MFD00001"


def test_ena_record_sample_name_falls_back_to_attribute(monkeypatch):
    """ENA-brokered records have no "Sample name" Id — only the attribute."""
    from lxml import etree
    monkeypatch.setattr(T, "efetch_xml", lambda db, ids: [etree.fromstring(_ENA_BIOSAMPLE_XML)])
    [rec] = T._fetch_biosample_records(["10890343"])
    assert rec["accession"] == "SAMEA4527675"
    assert rec["sample_name"] == "VNM.48"
    assert rec["organism"] == "wastewater metagenome"


def test_ena_record_sample_name_falls_back_to_submitter_id(monkeypatch):
    from lxml import etree
    xml = _ENA_BIOSAMPLE_XML.replace(
        b'<Attribute attribute_name="sample name" harmonized_name="sample_name" display_name="sample name">VNM.48</Attribute>', b"")
    monkeypatch.setattr(T, "efetch_xml", lambda db, ids: [etree.fromstring(xml)])
    [rec] = T._fetch_biosample_records(["10890343"])
    assert rec["sample_name"] == "VNM.48"


def _named(title, sample_name, organism="wastewater metagenome"):
    rec = _record("SAMEA4527675")
    rec.update(title=title, sample_name=sample_name, organism=organism)
    return T.build_biosample(rec, "nmdc:sty-99-x", "nmdc:bsm-99-x", datetime.now(tz=timezone.utc))


def test_biosample_name_prefers_sample_name_over_organism_title():
    bs = _named("wastewater metagenome", "VNM.48")
    assert bs.name == "VNM.48"
    assert bs.samp_name == "VNM.48"


def test_biosample_name_keeps_informative_title():
    assert _named("Sewage, Ho Chi Minh City inlet", "VNM.48").name == "Sewage, Ho Chi Minh City inlet"


def test_biosample_name_organism_title_without_sample_name_stays():
    assert _named("wastewater metagenome", "").name == "wastewater metagenome"


def test_biosample_carries_sewage_type_verbatim():
    bs = _biosample(sewage_type="open sewer line")
    assert bs.sewage_type.has_raw_value == "open sewer line"
    assert _biosample(sewage_type="not provided").sewage_type is None
