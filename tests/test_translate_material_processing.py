"""Tests for the LibraryPreparation/ProcessedSample chain that links each
Biosample to its NucleotideSequencing in the NCBI translator (no Extraction
record — the LibraryPreparation consumes the Biosample directly)."""

from nmdc_schema import nmdc
from linkml_runtime.dumpers import json_dumper
from linkml_runtime.loaders import json_loader

from nmdc_ingest_agent.minting import PlaceholderMinter
from nmdc_ingest_agent.sources.ncbi import translate as T


class _FakeResolver:
    """Resolve any non-empty instrument model to a fixed existing Instrument id."""

    def resolve(self, model):
        return "nmdc:inst-14-mr4r2w09" if model else None


def _experiment(exp_acc, bs_acc, source, strategy, *, selection="RANDOM",
                layout="PAIRED", library_name="", design_description="",
                instrument="Illumina NovaSeq 6000", runs=None):
    if runs is None:
        runs = [f"SRR{exp_acc[-3:]}"]
    return {
        "experiment_accession": exp_acc,
        "biosample_accession": bs_acc,
        "sample_title": f"{exp_acc} title",
        "instrument_model": instrument,
        "platform_type": "ILLUMINA",
        "library_strategy": strategy,
        "library_source": source,
        "library_selection": selection,
        "library_layout": layout,
        "library_name": library_name,
        "design_description": design_description,
        "runs": [{"accession": r, "total_bases": "1", "total_spots": "1"} for r in runs],
    }


# Representative SRA design descriptions (verbatim shapes from PRJNA1071982).
_WGS_DESIGN = "Miniaturized metagenome DNA preps see https://doi.org/10.1101/2023.09.04.556179"
_AMPLICON_16S_DESIGN = "amplicon sequencing using 8F and 1391R to amplify bacterial 16S rRNA genes"
_AMPLICON_BACOPERON_DESIGN = "amplicon sequencing using 8F and 2490R to amplify bacterial rRNA operons"
_AMPLICON_EUKOPERON_DESIGN = "amplicon sequencing using 3NDF and 21R to amplify eukaryotic rRNA operons"


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


def _build(experiments, biosamples=None, mfd_resolver=None):
    return T.build_nmdc_database(
        _data(experiments, biosamples), PlaceholderMinter(), _FakeResolver(),
        mfd_resolver,
    )


def test_chain_validates_against_schema():
    db = _build([_experiment("SRX111", "SAMN001", "METAGENOMIC", "WGS")])
    # Round-trips through the NMDC schema loader without validation error.
    loaded = json_loader.loads(json_dumper.dumps(db), target_class=nmdc.Database)
    # One LibraryPreparation + one ProcessedSample (the library); no Extraction.
    assert len(loaded.material_processing_set) == 1
    assert len(loaded.processed_sample_set) == 1


def test_chain_wiring_links_biosample_to_sequencing():
    db = _build([_experiment("SRX111", "SAMN001", "METAGENOMIC", "WGS")])

    biosample_id = db.biosample_set[0].id
    libprep = next(m for m in db.material_processing_set if m.type == "nmdc:LibraryPreparation")
    nuc_seq = db.data_generation_set[0]

    # Biosample -> LibraryPreparation -> ProcessedSample -> NucleotideSequencing
    # (no Extraction; the LibraryPreparation consumes the Biosample directly).
    assert not any(m.type == "nmdc:Extraction" for m in db.material_processing_set)
    assert libprep.has_input == [biosample_id]
    assert libprep.has_output == nuc_seq.has_input
    assert biosample_id not in nuc_seq.has_input
    ps_ids = {p.id for p in db.processed_sample_set}
    assert ps_ids == {libprep.has_output[0]}


def test_no_extraction_records():
    db = _build([_experiment("SRX111", "SAMN001", "METAGENOMIC", "WGS")])
    assert all(m.type == "nmdc:LibraryPreparation" for m in db.material_processing_set)
    assert not any(p.id.startswith("nmdc:extrp-") for p in db.processed_sample_set)


def test_record_names_follow_example_conventions():
    # samp_name "MFD00001" from the fixture; experiment/run accessions must not
    # appear in the material-processing / processed-sample names.
    db = _build([_experiment("SRX111", "SAMN001", "METAGENOMIC", "WGS",
                             library_name="ilm_MFD00001")])
    libprep = next(m for m in db.material_processing_set if m.type == "nmdc:LibraryPreparation")
    library_ps = next(p for p in db.processed_sample_set if p.id == libprep.has_output[0])

    assert libprep.name == "Library preparation process for MFD00001"
    # Library ProcessedSample is named after the SRA library name; prose -> description.
    assert library_ps.name == "ilm_MFD00001"
    assert library_ps.description == "Library for sequencing for MFD00001"
    assert db.data_generation_set[0].name == "Run SRR111 for experiment SRX111 - MFD00001"


def test_library_preparation_carries_sra_descriptor():
    db = _build([_experiment("SRX111", "SAMN001", "METAGENOMIC", "WGS",
                             selection="size fractionation", layout="PAIRED")])
    lp = next(m for m in db.material_processing_set if m.type == "nmdc:LibraryPreparation")
    assert str(lp.library_strategy) == "WGS"
    assert str(lp.library_source) == "METAGENOMIC"
    assert str(lp.library_selection) == "size fractionation"
    assert str(lp.lib_layout) == "paired"  # SRA PAIRED -> LibLayoutEnum paired


def test_pipeline_commits_only_explicit_target_gene():
    # The pipeline commits target_gene only for the design naming one explicit
    # gene (the 16S amplicon); operons + WGS are left unset for the curation skill.
    db = _build([
        _experiment("SRX111", "SAMN001", "METAGENOMIC", "WGS",
                    design_description=_WGS_DESIGN),
        _experiment("SRX222", "SAMN001", "METAGENOMIC", "AMPLICON",
                    library_name="npumi_16SrRNA_MFD00001", selection="PCR",
                    layout="SINGLE", design_description=_AMPLICON_16S_DESIGN),
        _experiment("SRX333", "SAMN001", "METAGENOMIC", "AMPLICON",
                    library_name="pb_bacoperon_MFD00001", selection="PCR",
                    layout="SINGLE", design_description=_AMPLICON_BACOPERON_DESIGN),
        _experiment("SRX444", "SAMN001", "METAGENOMIC", "AMPLICON",
                    library_name="pb_eukoperon_MFD00001", selection="PCR",
                    layout="SINGLE", design_description=_AMPLICON_EUKOPERON_DESIGN),
    ])
    libs = [m for m in db.material_processing_set if m.type == "nmdc:LibraryPreparation"]
    genes = sorted(str(m.target_gene) for m in libs if m.target_gene)
    assert genes == ["16S_rRNA"]  # only the explicit-gene amplicon; operons unset


def test_extract_target_gene_only_explicit_single_gene():
    # Explicit single gene token -> that gene.
    assert T._extract_target_gene(_AMPLICON_16S_DESIGN) == "16S_rRNA"
    assert T._extract_target_gene("amplify 23S rRNA") == "23S_rRNA"
    # Operons name no single gene -> unset (deferred to the nmdc-target-gene skill);
    # the pipeline does not guess bacterial->16S / eukaryotic->18S.
    assert T._extract_target_gene(_AMPLICON_BACOPERON_DESIGN) is None
    assert T._extract_target_gene(_AMPLICON_EUKOPERON_DESIGN) is None
    assert T._extract_target_gene("amplify rRNA operons") is None
    # More than one explicit gene -> ambiguous -> unset.
    assert T._extract_target_gene("targeting both 16S and 23S rRNA") is None
    assert T._extract_target_gene(_WGS_DESIGN) is None
    assert T._extract_target_gene("") is None


def test_all_amplicon_designs_surfaced_for_curation():
    # Every amplicon library is listed in the curation-inputs sidecar, grouped by
    # distinct design — both the operons (target_gene unset) AND the explicit-gene
    # amplicon (target_gene already set). Descriptions are written by the skill for
    # all of them, so all must be present; the row's target_gene records the
    # pipeline's current value so the skill knows which still need resolving.
    data = _data([
        _experiment("SRX222", "SAMN001", "METAGENOMIC", "AMPLICON",
                    library_name="npumi_16SrRNA_MFD00001", selection="PCR",
                    layout="SINGLE", design_description=_AMPLICON_16S_DESIGN),
        _experiment("SRX333", "SAMN001", "METAGENOMIC", "AMPLICON",
                    library_name="pb_bacoperon_MFD00001", selection="PCR",
                    layout="SINGLE", design_description=_AMPLICON_BACOPERON_DESIGN),
        _experiment("SRX444", "SAMN001", "METAGENOMIC", "AMPLICON",
                    library_name="pb_eukoperon_MFD00001", selection="PCR",
                    layout="SINGLE", design_description=_AMPLICON_EUKOPERON_DESIGN),
    ])
    db = T.build_nmdc_database(data, PlaceholderMinter(), _FakeResolver(), None)
    sidecar = T.build_curation_inputs_sidecar(data, db)
    rows = sidecar["amplicon_curation"]
    tg_by_design = {r["design_description"]: r["target_gene"] for r in rows}
    # All three amplicon designs are present (so each gets a description).
    assert set(tg_by_design) == {
        _AMPLICON_16S_DESIGN, _AMPLICON_BACOPERON_DESIGN, _AMPLICON_EUKOPERON_DESIGN
    }
    # The pipeline resolved the explicit-gene design; the operons stay unset.
    assert tg_by_design[_AMPLICON_16S_DESIGN] == "16S_rRNA"
    assert tg_by_design[_AMPLICON_BACOPERON_DESIGN] is None
    assert tg_by_design[_AMPLICON_EUKOPERON_DESIGN] is None
    # Each row carries the libprep ids to patch.
    assert all(r["count"] == len(r["library_preparation_ids"]) >= 1 for r in rows)


def test_pipeline_leaves_amplicon_description_for_curation():
    # The pipeline does not parse the free-text design into a description — that
    # is delegated to the nmdc-target-gene skill. So amplicon LibraryPreparations
    # come out of the build with no description (the design text rides along in the
    # amplicon_curation sidecar instead).
    data = _data([
        _experiment("SRX333", "SAMN001", "METAGENOMIC", "AMPLICON",
                    library_name="pb_bacoperon_MFD00001", selection="PCR",
                    layout="SINGLE", design_description=_AMPLICON_BACOPERON_DESIGN),
    ])
    db = T.build_nmdc_database(data, PlaceholderMinter(), _FakeResolver(), None)
    lp = next(m for m in db.material_processing_set if m.type == "nmdc:LibraryPreparation")
    assert lp.description is None
    assert lp.target_gene is None
    # The design text the skill needs is carried in the sidecar.
    row = T.build_curation_inputs_sidecar(data, db)["amplicon_curation"][0]
    assert row["design_description"] == _AMPLICON_BACOPERON_DESIGN


def test_lib_layout_values_come_from_schema_enum():
    from nmdc_schema import nmdc
    assert T._LIB_LAYOUT_VALUES == T._enum_value_texts(nmdc.LibLayoutEnum)
    assert "paired" in T._LIB_LAYOUT_VALUES and "single" in T._LIB_LAYOUT_VALUES
    assert "MissingRequiredField" not in T._LIB_LAYOUT_VALUES


def test_protocol_link_parsed_from_design_description():
    # The WGS design cites a protocol DOI; the amplicon design does not.
    db = _build([
        _experiment("SRX111", "SAMN001", "METAGENOMIC", "WGS",
                    design_description=_WGS_DESIGN),
        _experiment("SRX222", "SAMN001", "METAGENOMIC", "AMPLICON",
                    selection="PCR", layout="SINGLE",
                    design_description=_AMPLICON_16S_DESIGN),
    ])
    libs = {str(m.library_strategy): m for m in db.material_processing_set
            if m.type == "nmdc:LibraryPreparation"}
    assert libs["WGS"].protocol_link is not None
    assert libs["WGS"].protocol_link.url == "https://doi.org/10.1101/2023.09.04.556179"
    # Amplicon design names primers but cites no DOI -> no protocol_link.
    assert libs["AMPLICON"].protocol_link is None


def test_extract_protocol_url_unit():
    assert T._extract_protocol_url(_WGS_DESIGN) == "https://doi.org/10.1101/2023.09.04.556179"
    assert T._extract_protocol_url("see doi: 10.1234/abc.def") == "https://doi.org/10.1234/abc.def"
    assert T._extract_protocol_url(_AMPLICON_16S_DESIGN) is None
    assert T._extract_protocol_url("") is None


def test_no_design_description_leaves_protocol_and_target_gene_unset():
    db = _build([_experiment("SRX111", "SAMN001", "METAGENOMIC", "WGS")])
    lp = next(m for m in db.material_processing_set if m.type == "nmdc:LibraryPreparation")
    assert lp.protocol_link is None
    assert lp.target_gene is None
    assert lp.description is None


def test_data_object_is_sra_toolkit_shape():
    db = _build([_experiment("SRX111", "SAMN001", "METAGENOMIC", "WGS")])
    do = db.data_object_set[0]
    ns = db.data_generation_set[0]
    assert str(do.data_object_type) == "SRA toolkit-accessible sequence data"
    assert do.url is None
    assert do.insdc_run_identifiers == ["insdc.run:SRR111"]
    assert do.was_generated_by == ns.id
    assert do.name == "Data file for run accession SRR111"


def test_nucleotide_sequencing_has_bioproject_identifier():
    db = _build([_experiment("SRX111", "SAMN001", "METAGENOMIC", "WGS")])
    assert db.data_generation_set[0].insdc_bioproject_identifiers == [
        "bioproject:PRJNA1071982"
    ]


def test_per_run_data_generation_and_manifest():
    # One multi-run experiment -> one chain, two NucleotideSequencings + two
    # DataObjects + one Manifest grouping the run DataObjects.
    db = _build([_experiment("SRX111", "SAMN001", "METAGENOMIC", "WGS",
                             library_name="ilm_MFD00001",
                             runs=["SRR1", "SRR2"])])
    assert len(db.material_processing_set) == 1  # one LibraryPreparation
    assert len(db.data_generation_set) == 2      # one per run
    assert len(db.data_object_set) == 2
    assert len(db.manifest_set) == 1
    manifest = db.manifest_set[0]
    assert str(manifest.manifest_category) == "poolable_replicates"
    assert manifest.id.startswith("nmdc:manif-")
    # Both run DataObjects reference the manifest.
    assert all(d.in_manifest == [manifest.id] for d in db.data_object_set)


def test_single_run_experiment_has_no_manifest():
    db = _build([_experiment("SRX111", "SAMN001", "METAGENOMIC", "WGS")])
    assert db.manifest_set == []
    assert db.data_object_set[0].in_manifest in (None, [])


def test_experiments_sharing_library_dedup_with_manifest():
    # SAMEA7724300-shaped: 4 separate WGS experiments (1 run each) share one
    # library name + instrument; a 5th amplicon experiment reuses the name on a
    # different instrument/descriptor. Expect: dedup to 2 library chains (not 5),
    # one data-generation per run, and a Manifest over the 4 poolable WGS runs.
    exps = [
        _experiment(f"ERX{i}", "SAMN001", "METAGENOMIC", "WGS",
                    library_name="shared.lib.s004", selection="size fractionation",
                    instrument="Illumina NovaSeq 6000", runs=[f"ERR{i}"])
        for i in range(1, 5)
    ] + [
        _experiment("ERX5", "SAMN001", "METAGENOMIC", "AMPLICON",
                    library_name="shared.lib.s004", selection="PCR", layout="SINGLE",
                    instrument="Illumina MiSeq", runs=["ERR5"]),
    ]
    db = _build(exps)
    libpreps = [m for m in db.material_processing_set if m.type == "nmdc:LibraryPreparation"]

    assert len(db.material_processing_set) == 2  # WGS library + amplicon library, not 5
    assert len(libpreps) == 2                     # all LibraryPreparation (no Extraction)
    assert len(db.processed_sample_set) == 2      # one library ProcessedSample each
    assert len(db.data_generation_set) == 5   # one NucleotideSequencing per run
    assert len(db.data_object_set) == 5
    assert len(db.manifest_set) == 1          # the 4 NovaSeq WGS runs

    manifest = db.manifest_set[0]
    assert str(manifest.manifest_category) == "poolable_replicates"
    in_manifest = [d for d in db.data_object_set if d.in_manifest]
    assert len(in_manifest) == 4
    assert all(d.in_manifest == [manifest.id] for d in in_manifest)

    # The 4 WGS NucleotideSequencings all consume the same WGS library ProcessedSample.
    wgs_lib = next(m for m in libpreps if str(m.library_strategy) == "WGS")
    wgs_ns = [ns for ns in db.data_generation_set if ns.has_input == wgs_lib.has_output]
    assert len(wgs_ns) == 4


def test_distinct_library_names_are_not_merged():
    # One biosample, two distinct library names (e.g. WGS + amplicon) -> two
    # independent library chains.
    db = _build([
        _experiment("SRX1", "SAMN001", "METAGENOMIC", "WGS", library_name="ilm_X"),
        _experiment("SRX2", "SAMN001", "METAGENOMIC", "AMPLICON",
                    library_name="pb_X", selection="PCR", layout="SINGLE"),
    ])
    assert len([m for m in db.material_processing_set if m.type == "nmdc:LibraryPreparation"]) == 2
    assert len(db.material_processing_set) == 2  # no Extraction records
    assert db.manifest_set == []


def test_processed_sample_and_libprep_typecodes():
    db = _build([_experiment("SRX111", "SAMN001", "METAGENOMIC", "WGS")])
    assert all(p.id.startswith("nmdc:procsm-") for p in db.processed_sample_set)
    libprep = next(m for m in db.material_processing_set if m.type == "nmdc:LibraryPreparation")
    assert libprep.id.startswith("nmdc:libprp-")
