"""Tests for the Extraction/LibraryPreparation/ProcessedSample chain that links
each Biosample to its NucleotideSequencing in the NCBI translator."""

from nmdc_schema import nmdc
from linkml_runtime.dumpers import json_dumper
from linkml_runtime.loaders import json_loader

from nmdc_ingest_agent.minting import PlaceholderMinter
from nmdc_ingest_agent.sources.ncbi import translate as T


class _FakeResolver:
    """Resolve any non-empty instrument model to a fixed existing Instrument id."""

    def resolve(self, model):
        return "nmdc:inst-14-mr4r2w09" if model else None


def _experiment(exp_acc, bs_acc, source, strategy):
    return {
        "experiment_accession": exp_acc,
        "biosample_accession": bs_acc,
        "sample_title": f"{exp_acc} title",
        "instrument_model": "Illumina NovaSeq 6000",
        "platform_type": "ILLUMINA",
        "library_strategy": strategy,
        "library_source": source,
        "library_selection": "RANDOM",
        "library_layout": "PAIRED",
        "library_name": "",
        "runs": [{"accession": f"SRR{exp_acc[-3:]}", "total_bases": "1", "total_spots": "1"}],
    }


def _data(experiments, biosamples=None):
    if biosamples is None:
        biosamples = [
            {
                "accession": "SAMN001",
                "title": "soil A",
                "sample_name": "MFD00001",
                "organism": "soil metagenome",
                "taxonomy_id": "410658",
                "package": "MIMS.me.soil.6.0",
                "models": [],
                "attributes": {},
            }
        ]
    return {
        "bioproject": {
            "accession": "PRJNA1071982",
            "uid": "1",
            "title": "MFD",
            "description": "d",
            "name": "n",
            "organism": "",
            "publications": [],
        },
        "biosamples": biosamples,
        "sra_experiments": experiments,
    }


def _build(experiments, biosamples=None):
    return T.build_nmdc_database(
        _data(experiments, biosamples), PlaceholderMinter(), _FakeResolver(), None
    )


def test_chain_validates_against_schema():
    db = _build([_experiment("SRX111", "SAMN001", "METAGENOMIC", "WGS")])
    # Round-trips through the NMDC schema loader without validation error.
    loaded = json_loader.loads(json_dumper.dumps(db), target_class=nmdc.Database)
    assert len(loaded.material_processing_set) == 2
    assert len(loaded.processed_sample_set) == 2


def test_chain_wiring_links_biosample_to_sequencing():
    db = _build([_experiment("SRX111", "SAMN001", "METAGENOMIC", "WGS")])

    biosample_id = db.biosample_set[0].id
    extraction = next(m for m in db.material_processing_set if m.type == "nmdc:Extraction")
    libprep = next(m for m in db.material_processing_set if m.type == "nmdc:LibraryPreparation")
    nuc_seq = db.data_generation_set[0]

    # Biosample -> Extraction -> ProcessedSample -> LibraryPreparation -> ProcessedSample -> NucleotideSequencing
    assert extraction.has_input == [biosample_id]
    assert extraction.has_output == libprep.has_input
    assert libprep.has_output == nuc_seq.has_input
    # The sequencing no longer consumes the Biosample directly.
    assert biosample_id not in nuc_seq.has_input
    # Both ProcessedSamples are the ones emitted by the two processes.
    ps_ids = {p.id for p in db.processed_sample_set}
    assert ps_ids == {extraction.has_output[0], libprep.has_output[0]}


def test_dna_vs_rna_target_inference():
    db = _build(
        [
            _experiment("SRX111", "SAMN001", "METAGENOMIC", "WGS"),
            _experiment("SRX222", "SAMN001", "METATRANSCRIPTOMIC", "RNA-Seq"),
        ]
    )
    extractions = [m for m in db.material_processing_set if m.type == "nmdc:Extraction"]
    libpreps = [m for m in db.material_processing_set if m.type == "nmdc:LibraryPreparation"]

    targets = {str(t) for e in extractions for t in e.extraction_targets}
    lib_types = {str(lp.library_type) for lp in libpreps}
    assert targets == {"DNA", "RNA"}
    assert lib_types == {"DNA", "RNA"}


def test_records_named_after_biosample_not_experiment():
    # samp_name "MFD00001" comes from the default biosample fixture; the SRA
    # experiment accession "SRX111" must NOT appear in any chain record name.
    db = _build([_experiment("SRX111", "SAMN001", "METAGENOMIC", "WGS")])
    names = [m.name for m in db.material_processing_set] + [
        p.name for p in db.processed_sample_set
    ]
    assert all("MFD00001" in n for n in names)
    assert all("SRX111" not in n for n in names)
    assert "Extraction for MFD00001" in names
    assert "DNA extracted from MFD00001" in names
    assert "Library preparation for MFD00001" in names
    assert "sequencing library prepared for MFD00001" in names


def test_processed_sample_ids_use_procsm_typecode():
    db = _build([_experiment("SRX111", "SAMN001", "METAGENOMIC", "WGS")])
    assert all(p.id.startswith("nmdc:procsm-") for p in db.processed_sample_set)
    extraction = next(m for m in db.material_processing_set if m.type == "nmdc:Extraction")
    libprep = next(m for m in db.material_processing_set if m.type == "nmdc:LibraryPreparation")
    assert extraction.id.startswith("nmdc:extrp-")
    assert libprep.id.startswith("nmdc:libprp-")
