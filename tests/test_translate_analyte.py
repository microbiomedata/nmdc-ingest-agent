"""Tests for analyte_category resolution (issue #46).

The SRA library_source/library_strategy pair must map to a NucleotideSequencingEnum
permissible value (amplicon_sequencing_assay / metagenome / metatranscriptome) or
raise — never silently default to metagenome.
"""

import pytest

from nmdc_ingest_agent.minting import PlaceholderMinter
from nmdc_ingest_agent.sources.ncbi import translate as T
from nmdc_ingest_agent.sources.ncbi.translate import _resolve_analyte_category


class _FakeResolver:
    def resolve(self, model):
        return "nmdc:inst-14-mr4r2w09" if model else None


@pytest.mark.parametrize(
    "source,strategy,expected",
    [
        ("METAGENOMIC", "AMPLICON", "amplicon_sequencing_assay"),
        ("METAGENOMIC", "WGS", "metagenome"),
        ("METATRANSCRIPTOMIC", "RNA-Seq", "metatranscriptome"),
        # Case-insensitive on both inputs.
        ("metagenomic", "amplicon", "amplicon_sequencing_assay"),
        ("Metagenomic", "wgs", "metagenome"),
        ("metatranscriptomic", "rna-seq", "metatranscriptome"),
    ],
)
def test_documented_mappings(source, strategy, expected):
    assert _resolve_analyte_category(source, strategy) == expected


@pytest.mark.parametrize(
    "source,strategy",
    [
        ("GENOMIC", "WGS"),           # genomic source is not metagenomic
        ("METAGENOMIC", "WXS"),       # unhandled strategy
        ("METATRANSCRIPTOMIC", "WGS"),  # mismatched pair
        ("TRANSCRIPTOMIC", "RNA-Seq"),  # not metatranscriptomic
        ("", ""),                     # missing
        ("METAGENOMIC", ""),
    ],
)
def test_unmappable_pairs_raise(source, strategy):
    with pytest.raises(ValueError):
        _resolve_analyte_category(source, strategy)


def _experiment(exp_acc, source, strategy):
    return {
        "experiment_accession": exp_acc,
        "biosample_accession": "SAMN001",
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


def _build(experiments):
    data = {
        "bioproject": {
            "accession": "PRJNA1071982", "uid": "1", "title": "MFD",
            "description": "d", "name": "n", "organism": "", "publications": [],
        },
        "biosamples": [{
            "accession": "SAMN001", "title": "soil A", "sample_name": "MFD00001",
            "organism": "soil metagenome", "taxonomy_id": "410658",
            "package": "MIMS.me.soil.6.0", "models": [], "attributes": {},
        }],
        "sra_experiments": experiments,
    }
    return T.build_nmdc_database(data, PlaceholderMinter(), _FakeResolver(), None)


def test_amplicon_experiment_labeled_amplicon_not_metagenome():
    # Regression for the mislabel: METAGENOMIC + AMPLICON used to fall through
    # to the metagenome branch.
    db = _build([_experiment("SRX111", "METAGENOMIC", "AMPLICON")])
    assert [ns.analyte_category for ns in db.data_generation_set] == [
        "amplicon_sequencing_assay"
    ]


def test_wgs_and_amplicon_get_distinct_categories():
    db = _build([
        _experiment("SRX111", "METAGENOMIC", "WGS"),
        _experiment("SRX222", "METAGENOMIC", "AMPLICON"),
    ])
    cats = sorted(ns.analyte_category for ns in db.data_generation_set)
    assert cats == ["amplicon_sequencing_assay", "metagenome"]


def test_unmappable_experiment_excluded_biosample_kept():
    db = _build([_experiment("SRX111", "GENOMIC", "WXS")])
    # No DataGeneration emitted, but the Biosample (and nothing downstream) remains.
    assert len(db.data_generation_set) == 0
    assert len(db.material_processing_set) == 0
    assert len(db.processed_sample_set) == 0
    assert len(db.biosample_set) == 1
