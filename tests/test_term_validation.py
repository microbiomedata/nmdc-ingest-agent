"""Tests for the ontology-term QC layer (``nmdc_ingest_agent.validators``).

Everything but the last class runs offline against fakes: a stub plugin plus
hand-built ``linkml.validator`` results exercise the normalization rules
(which upstream finding feeds which flag, what is dropped for unconfigured
prefixes / missing / obsolete terms, curator-safe merging). The real
``linkml-term-validator`` + ENVO path is exercised only when oaklib's ENVO
sqlite is already cached locally (it is never downloaded by the tests).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from linkml.validator.report import Severity, ValidationResult

from nmdc_ingest_agent import run_notes
from nmdc_ingest_agent.validators import cli, run
from nmdc_ingest_agent.validators.extract import (
    BIOSAMPLE_TERM_SLOTS,
    SENTINEL_CURIES,
    extract_observed_terms,
    iter_terms,
)
from nmdc_ingest_agent.validators.run import (
    FLAGS,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_SKIPPED,
    STATUS_UNAVAILABLE,
    _normalize,
    effective_oak_config,
    format_summary,
    load_adapters,
    merge_into_curation_report,
    parse_adapter_spec,
    run_term_validation,
)
from nmdc_ingest_agent.validators.valuesets import (
    DEFAULT_VALUESETS_PATH,
    infer_interface,
    load_valuesets,
    parse_permissible_value,
)

ENVO_DB = Path.home() / ".data" / "oaklib" / "envo.db"

# --------------------------------------------------------------------------
# Fixture helpers
# --------------------------------------------------------------------------


def civ(curie, name, raw=None):
    d = {"type": "nmdc:ControlledIdentifiedTermValue",
         "term": {"id": curie, "type": "nmdc:OntologyClass", "name": name}}
    if raw is not None:
        d["has_raw_value"] = raw
    return d


def biosample(i, package, broad, local, medium, taxon=("NCBITaxon:410658", "soil metagenome")):
    b = {"id": f"nmdc:bsm-99-{i:08d}", "type": "nmdc:Biosample", "name": f"s{i}",
         "associated_studies": ["nmdc:sty-99-1"],
         "env_broad_scale": civ(*broad), "env_local_scale": civ(*local), "env_medium": civ(*medium),
         "samp_taxon_id": civ(*taxon)}
    if package:
        b["env_package"] = {"type": "nmdc:TextValue", "has_raw_value": package}
    return b


def database():
    """Six biosamples covering every check (see the per-row comments)."""
    return {"study_set": [{"id": "nmdc:sty-99-1", "type": "nmdc:Study"}], "biosample_set": [
        # all clean, all inside the soil value sets
        biosample(1, "MIMS.me.soil.6.0", ("ENVO:01000202", "temperate broadleaf forest biome"),
                  ("ENVO:00000114", "agricultural field"), ("ENVO:00001998", "soil")),
        # PRJNA1414893-style label mismatch + wrong anchor (a material as broad scale);
        # sentinel local scale; case-only label difference on medium (allowed)
        biosample(2, "MIMS.me.soil.6.0", ("ENVO:00002006", "brine"),
                  ("ENVO:00000000", "(not provided)", ""), ("ENVO:00001998", "Soil")),
        # nonexistent CURIE; a biome in local scale; an obsolete term
        biosample(3, "MIMS.me.water.6.0", ("ENVO:99999999", "nonexistent"),
                  ("ENVO:01000202", "temperate broadleaf forest biome"), ("ENVO:00000018", "dry river")),
        # HCR package: no NMDC value set exists
        biosample(4, "MIMS.me.hydrocarbon-cores.6.0", ("ENVO:00000447", "marine biome"),
                  ("ENVO:00000114", "agricultural field"), ("ENVO:00002006", "liquid water")),
        # plant-associated: PO medium term (prefix unconfigured) that IS in the value set
        biosample(5, "MIMS.me.plant-associated.6.0", ("ENVO:01000174", "forest biome"),
                  ("ENVO:01000335", "understory"), ("PO:0025034", "leaf")),
        # no package at all
        biosample(6, None, ("ENVO:00000447", "marine biome"),
                  ("ENVO:00000447", "marine biome"), ("ENVO:00001998", "soil")),
    ]}


def curation_report_for(db):
    rows = []
    for b in db["biosample_set"]:
        for slot in ("env_broad_scale", "env_local_scale", "env_medium"):
            t = b[slot]["term"]
            sentinel = t["id"] in SENTINEL_CURIES
            rows.append({
                "biosample_id": b["id"], "slot": slot,
                "outcome": "left_sentinel" if sentinel else "resolved_at_pipeline",
                "raw_input": b[slot].get("has_raw_value", ""),
                "committed_curie": None if sentinel else t["id"],
                "committed_label": None if sentinel else t["name"],
                "evidence": [], "candidates_considered": [],
                "validator": {flag: None for flag in FLAGS},
            })
    return {"rows": rows}


def term(slot, biosample_id, curie, label, package=""):
    return {"id": f"{biosample_id}:{slot}", "biosample_id": biosample_id, "slot": slot,
            "raw_value": "", "env_package": package, "term": {"id": curie, "label": label}}


def upstream(kind, slot, index, message, **ctx):
    """A linkml ValidationResult shaped like BindingValidationPlugin emits."""
    context = [f"path: {slot}[{index}].term", "slot: term"] + [f"{k}: {v}" for k, v in ctx.items()]
    return ValidationResult(type=kind, severity=Severity.ERROR, message=message,
                            instance={}, instantiates="TermValidationSet", context=context)


class FakeSchemaView:
    def get_enum(self, name):
        return name  # opaque token; FakePlugin only compares it


class FakePlugin:
    """Stands in for BindingValidationPlugin after a run: label lookup,
    obsolescence, and biome membership from small dicts."""

    def __init__(self, labels, obsolete=(), biomes=()):
        self.labels = labels
        self.obsolete = set(obsolete)
        self.biomes = set(biomes)
        self.schema_view = FakeSchemaView()
        self.calls = {"label": 0, "obsolete": 0, "enum": 0}

    def get_ontology_label(self, curie):
        self.calls["label"] += 1
        return self.labels.get(curie)

    def is_obsolete(self, curie):
        self.calls["obsolete"] += 1
        return curie in self.obsolete

    def is_value_in_enum(self, value, enum_def, schema_view=None):
        self.calls["enum"] += 1
        assert enum_def == "BiomeEnum"
        return value in self.biomes


def normalize(instance, results, plugin, *, configured=("ENVO",), valuesets=None, offline=False, lenient=False):
    report = run._base_report(instance, status=STATUS_OK, reason=None, config={})
    _normalize(instance, results, plugin, set(configured), valuesets, report, offline=offline, lenient=lenient)
    return report


def by_key(report):
    return {(t["biosample_id"], t["slot"]): t for t in report["terms"]}


# --------------------------------------------------------------------------
# extract
# --------------------------------------------------------------------------


def test_extract_groups_by_slot_and_skips_sentinels():
    inst = extract_observed_terms(database())
    assert set(inst) - {"_meta"} == {"env_broad_scale", "env_local_scale", "env_medium", "samp_taxon_id"}
    assert len(inst["env_broad_scale"]) == 6
    assert len(inst["env_local_scale"]) == 5  # one sentinel skipped
    assert inst["_meta"]["skipped_sentinels"] == 1
    first = inst["env_broad_scale"][0]
    assert first == {
        "id": "nmdc:bsm-99-00000001:env_broad_scale", "biosample_id": "nmdc:bsm-99-00000001",
        "slot": "env_broad_scale", "raw_value": "", "env_package": "MIMS.me.soil.6.0",
        "term": {"id": "ENVO:01000202", "label": "temperate broadleaf forest biome"},
    }
    assert all(r["term"]["id"] not in SENTINEL_CURIES for _s, _i, r in iter_terms(inst))
    assert sum(1 for _ in iter_terms(inst)) == 23


def test_extract_accepts_nmdc_objects_and_missing_slots():
    from nmdc_schema import nmdc

    def civ_obj(curie, name, raw=None):
        return nmdc.ControlledIdentifiedTermValue(
            term=nmdc.OntologyClass(id=curie, name=name, type="nmdc:OntologyClass"),
            has_raw_value=raw, type="nmdc:ControlledIdentifiedTermValue")

    # The three triad slots are schema-required; the taxon slots are left unset.
    bs = nmdc.Biosample(
        id="nmdc:bsm-99-1", name="s", type="nmdc:Biosample", associated_studies=["nmdc:sty-99-1"],
        env_broad_scale=civ_obj("ENVO:00000447", "marine biome"),
        env_local_scale=civ_obj("ENVO:00000000", "(not provided)", ""),
        env_medium=civ_obj("ENVO:00001998", "soil"),
    )
    db = nmdc.Database(biosample_set=[bs])
    inst = extract_observed_terms(db)
    assert [s for s in inst if not s.startswith("_")] == ["env_broad_scale", "env_medium"]
    assert inst["env_medium"][0]["env_package"] == ""
    assert inst["_meta"]["skipped_sentinels"] == 1
    assert "samp_taxon_id" in BIOSAMPLE_TERM_SLOTS and "host_taxid" in BIOSAMPLE_TERM_SLOTS


def test_extract_empty_database():
    inst = extract_observed_terms({"biosample_set": []})
    assert inst == {"_meta": {"skipped_sentinels": 0}}
    assert extract_observed_terms({}) == {"_meta": {"skipped_sentinels": 0}}


# --------------------------------------------------------------------------
# valuesets
# --------------------------------------------------------------------------


@pytest.mark.parametrize("text,expected", [
    ("soil [ENVO:00001998]", ("soil", "ENVO:00001998")),
    ("leaf [PO:0025034]", ("leaf", "PO:0025034")),
    ("mixed forest biome  [ENVO:01000198] ", ("mixed forest biome", "ENVO:01000198")),
    ("soil", None), ("[ENVO:1]", ("", "ENVO:1")), ("", None), ("soil [not a curie]", None),
])
def test_parse_permissible_value(text, expected):
    assert parse_permissible_value(text) == expected


@pytest.mark.parametrize("package,expected", [
    ("MIMS.me.soil.6.0", "SoilInterface"),
    ("MIMARKS.survey.water.6.0", "WaterInterface"),
    ("MIGS.ba.sediment.6.0", "SedimentInterface"),
    ("MIMS.me.plant-associated.6.0", "PlantAssociatedInterface"),
    ("MIMS.me.hydrocarbon-fluids.swabs.6.0", "HcrFluidsSwabsInterface"),
    ("MIMS.me.hydrocarbon-cores.6.0", "HcrCoresInterface"),
    ("MIMS.me.air.6.0", "AirInterface"),
    ("MIMS.me.wastewater.6.0", "WastewaterSludgeInterface"),
    ("MIMS.me.human-gut.6.0", None),   # no NMDC interface for human packages
    ("MIMAG.6.0", None), ("Metagenome.environmental.1.0", None), ("", None), (None, None),
])
def test_infer_interface(package, expected):
    assert infer_interface(package) == expected


def test_vendored_valuesets_are_well_formed():
    vs = load_valuesets()
    assert vs is not None
    assert vs.schema_version.startswith("11.")
    assert vs.generated
    assert vs.interfaces == {"SoilInterface", "WaterInterface", "SedimentInterface", "PlantAssociatedInterface"}
    assert len(vs.members) == 12
    for enum, members in vs.members.items():
        assert enum.startswith("Env") and enum.endswith("Enum")
        assert members, enum
        for curie, label in members.items():
            assert ":" in curie and label, (enum, curie, label)
    # the twelve (interface, slot) pairs are exactly the product
    assert {slot for _i, slot in vs.enum_for} == {"env_broad_scale", "env_local_scale", "env_medium"}
    assert len(vs.enum_for) == 12
    # a few known members from nmdc-submission-schema
    assert vs.contains("SoilInterface", "env_medium", "ENVO:00001998") is True
    assert vs.contains("SoilInterface", "env_broad_scale", "ENVO:00000447") is False   # marine biome
    assert vs.contains("HcrCoresInterface", "env_medium", "ENVO:00001998") is None      # no value set
    assert vs.contains(None, "env_medium", "ENVO:00001998") is None
    assert vs.enum_name("WaterInterface", "env_local_scale") == "EnvLocalScaleWaterEnum"


def test_load_valuesets_missing_file_returns_none(tmp_path):
    assert load_valuesets(tmp_path / "nope.tsv") is None


def test_valuesets_tsv_header_is_parsed(tmp_path):
    tsv = tmp_path / "vs.tsv"
    tsv.write_text(
        "# comment\n# nmdc_submission_schema_version: 9.9.9\n# generated: 2026-01-01\n"
        "interface\tslot\tenum\tcurie\tlabel\ttext\n"
        "SoilInterface\tenv_medium\tEnvMediumSoilEnum\tENVO:1\tsoil\tsoil [ENVO:1]\n"
    )
    vs = load_valuesets(tsv)
    assert (vs.schema_version, vs.generated) == ("9.9.9", "2026-01-01")
    assert vs.contains("SoilInterface", "env_medium", "ENVO:1") is True
    assert vs.contains("SoilInterface", "env_broad_scale", "ENVO:1") is None


# --------------------------------------------------------------------------
# run: configuration helpers
# --------------------------------------------------------------------------


def test_parse_adapter_spec():
    assert parse_adapter_spec(None) == {}
    assert parse_adapter_spec("") == {}
    assert parse_adapter_spec("NCBITaxon=sqlite:obo:ncbitaxon, PO=ols:po") == {
        "NCBITaxon": "sqlite:obo:ncbitaxon", "PO": "ols:po"}
    assert parse_adapter_spec(["A=b", "C=d,E=f"]) == {"A": "b", "C": "d", "E": "f"}
    with pytest.raises(ValueError):
        parse_adapter_spec("bad")
    with pytest.raises(ValueError):
        parse_adapter_spec("=x")


def test_packaged_oak_config_configures_envo_only():
    adapters = load_adapters(run.DEFAULT_OAK_CONFIG_PATH)
    assert adapters["ENVO"] == "sqlite:obo:envo"
    assert not adapters.get("NCBITaxon")
    assert not adapters.get("PO")


def test_effective_oak_config_merges_overrides_under_cache_dir(tmp_path):
    path, adapters = effective_oak_config(run.DEFAULT_OAK_CONFIG_PATH, None, tmp_path)
    assert path == run.DEFAULT_OAK_CONFIG_PATH and adapters["ENVO"] == "sqlite:obo:envo"
    path, adapters = effective_oak_config(
        run.DEFAULT_OAK_CONFIG_PATH, {"NCBITaxon": "ols:ncbitaxon", "ENVO": "sqlite:obo:envo"}, tmp_path)
    assert path == tmp_path / "oak_config.effective.yaml"
    assert adapters["NCBITaxon"] == "ols:ncbitaxon"
    assert load_adapters(path)["NCBITaxon"] == "ols:ncbitaxon"
    assert "cache_strategy" in path.read_text()  # non-adapter keys preserved


def test_default_cache_dir_honours_env(monkeypatch, tmp_path):
    monkeypatch.setenv(run.CACHE_DIR_ENV_VAR, str(tmp_path / "x"))
    assert run.default_cache_dir() == tmp_path / "x"
    monkeypatch.delenv(run.CACHE_DIR_ENV_VAR)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert run.default_cache_dir() == tmp_path / "xdg" / "nmdc-ingest-agent" / "term-validator"


# --------------------------------------------------------------------------
# run: normalization rules (fake plugin, hand-built upstream results)
# --------------------------------------------------------------------------

LABELS = {
    "ENVO:01000202": "temperate broadleaf forest biome", "ENVO:00001998": "soil",
    "ENVO:00002006": "liquid water", "ENVO:00000018": "obsolete dry river",
    "ENVO:00000447": "marine biome", "ENVO:00000114": "agricultural field",
}


def test_clean_terms_get_all_true_flags():
    inst = {"env_broad_scale": [term("env_broad_scale", "b1", "ENVO:01000202", "temperate broadleaf forest biome", "MIMS.me.soil.6.0")],
            "env_medium": [term("env_medium", "b1", "ENVO:00001998", "soil", "MIMS.me.soil.6.0")],
            "env_local_scale": [term("env_local_scale", "b1", "ENVO:00000114", "agricultural field", "MIMS.me.soil.6.0")],
            "_meta": {"skipped_sentinels": 3}}
    plugin = FakePlugin(LABELS, biomes={"ENVO:01000202", "ENVO:00000447"})
    rep = normalize(inst, [], plugin, valuesets=load_valuesets())
    assert rep["findings"] == []
    for t in rep["terms"]:
        assert t["checked"] and t["info_ok"] and t["label_ok"] and t["anchor_ok"] and t["valueset_ok"] is True
        assert t["inferred_interface"] == "SoilInterface"
    s = rep["summary"]
    assert (s["terms"], s["checked"], s["errors"], s["warnings"], s["skipped_sentinels"]) == (3, 3, 0, 0, 3)
    assert s["by_slot"]["env_medium"] == {"terms": 1, "checked": 1, "errors": 0, "warnings": 0}


def test_label_mismatch_and_anchor_violation_feed_separate_flags():
    inst = {"env_broad_scale": [term("env_broad_scale", "b2", "ENVO:00002006", "brine", "MIMS.me.soil.6.0")], "_meta": {}}
    results = [
        upstream("binding_validation", "env_broad_scale", 0,
                 "Value 'ENVO:00002006' not in dynamic enum 'BiomeEnum' (expanded from ontology)", field="id"),
        upstream("binding_label_mismatch", "env_broad_scale", 0,
                 "Label mismatch for 'ENVO:00002006': expected 'liquid water', got 'brine'", curie="ENVO:00002006"),
    ]
    rep = normalize(inst, results, FakePlugin(LABELS), valuesets=load_valuesets())
    t = rep["terms"][0]
    assert (t["info_ok"], t["label_ok"], t["anchor_ok"], t["valueset_ok"]) == (True, False, False, False)
    levels = {f["level"]: f["severity"] for f in rep["findings"]}
    assert levels == {"label": "error", "anchor": "warning", "valueset": "warning"}
    label_finding = next(f for f in rep["findings"] if f["level"] == "label")
    assert "'brine'" in label_finding["message"] and "'liquid water'" in label_finding["message"]
    assert rep["summary"]["errors"] == 1 and rep["summary"]["warnings"] == 2


def test_nonexistent_term_is_one_existence_error_and_other_flags_stay_none():
    inst = {"env_broad_scale": [term("env_broad_scale", "b3", "ENVO:99999999", "x", "MIMS.me.soil.6.0")], "_meta": {}}
    results = [  # the plugin emits both an anchor violation and term_not_found
        upstream("binding_validation", "env_broad_scale", 0, "Value 'ENVO:99999999' not in dynamic enum 'BiomeEnum' (expanded from ontology)"),
        upstream("term_not_found", "env_broad_scale", 0, "Term 'ENVO:99999999' not found in ontology"),
    ]
    rep = normalize(inst, results, FakePlugin(LABELS), valuesets=load_valuesets())
    t = rep["terms"][0]
    assert t["checked"] and (t["info_ok"], t["label_ok"], t["anchor_ok"], t["valueset_ok"]) == (False, None, None, None)
    assert [(f["level"], f["severity"]) for f in rep["findings"]] == [("existence", "error")]


def test_lenient_downgrades_unresolvable_terms_to_warnings():
    inst = {"env_medium": [term("env_medium", "b3", "ENVO:99999999", "x")], "_meta": {}}
    rep = normalize(inst, [], FakePlugin(LABELS), lenient=True)  # plugin silent in lenient mode
    t = rep["terms"][0]
    assert t["info_ok"] is None and "lenient" in t["notes"][0]
    assert [(f["level"], f["severity"]) for f in rep["findings"]] == [("existence", "warning")]
    assert rep["summary"]["errors"] == 0


def test_obsolete_term_is_a_single_error_and_hides_its_label_symptom():
    inst = {"env_medium": [term("env_medium", "b3", "ENVO:00000018", "dry river", "MIMS.me.water.6.0")], "_meta": {}}
    results = [upstream("binding_label_mismatch", "env_medium", 0,
                        "Label mismatch for 'ENVO:00000018': expected 'obsolete dry river', got 'dry river'"),
               upstream("binding_validation", "env_medium", 0, "Value 'ENVO:00000018' not in dynamic enum 'EnvironmentalMaterialEnum' (expanded from ontology)")]
    rep = normalize(inst, results, FakePlugin(LABELS, obsolete={"ENVO:00000018"}), valuesets=load_valuesets())
    t = rep["terms"][0]
    assert t["obsolete"] is True
    assert (t["info_ok"], t["label_ok"], t["anchor_ok"], t["valueset_ok"]) == (False, None, None, None)
    assert [(f["level"], f["severity"]) for f in rep["findings"]] == [("obsolete", "error")]


def test_local_scale_negative_biome_rule():
    inst = {"env_local_scale": [term("env_local_scale", "b3", "ENVO:01000202", "temperate broadleaf forest biome", "MIMS.me.water.6.0"),
                                term("env_local_scale", "b1", "ENVO:00000114", "agricultural field", "MIMS.me.soil.6.0")], "_meta": {}}
    plugin = FakePlugin(LABELS, biomes={"ENVO:01000202"})
    rep = normalize(inst, [], plugin, valuesets=load_valuesets())
    t = by_key(rep)
    assert t[("b3", "env_local_scale")]["anchor_ok"] is False
    assert t[("b1", "env_local_scale")]["anchor_ok"] is True
    anchor = [f for f in rep["findings"] if f["level"] == "anchor"]
    assert len(anchor) == 1 and "biomes belong in env_broad_scale" in anchor[0]["message"]
    assert anchor[0]["severity"] == "warning"


def test_per_curie_facts_are_memoized_across_biosamples():
    rows = [term("env_local_scale", f"b{i}", "ENVO:00000114", "agricultural field") for i in range(50)]
    plugin = FakePlugin(LABELS)
    rep = normalize({"env_local_scale": rows, "_meta": {}}, [], plugin)
    assert rep["summary"]["checked"] == 50
    assert plugin.calls == {"label": 1, "obsolete": 1, "enum": 1}


def test_unconfigured_prefix_is_unchecked_but_still_valueset_checked():
    inst = {"env_medium": [term("env_medium", "b5", "PO:0025034", "leaf", "MIMS.me.plant-associated.6.0"),
                           term("env_medium", "b6", "PO:0000000", "nope", "MIMS.me.plant-associated.6.0")],
            "samp_taxon_id": [term("samp_taxon_id", "b5", "NCBITaxon:410658", "soil metagenome")], "_meta": {}}
    # the plugin emits a bogus anchor violation for a prefix it has no adapter for; it must be dropped
    results = [upstream("binding_validation", "env_medium", 0, "Value 'PO:0025034' not in dynamic enum 'EnvironmentalMaterialEnum' (expanded from ontology)")]
    rep = normalize(inst, results, FakePlugin({}), valuesets=load_valuesets())
    t = by_key(rep)
    leaf, nope, taxon = t[("b5", "env_medium")], t[("b6", "env_medium")], t[("b5", "samp_taxon_id")]
    assert not leaf["checked"] and (leaf["info_ok"], leaf["label_ok"], leaf["anchor_ok"]) == (None, None, None)
    assert leaf["valueset_ok"] is True and nope["valueset_ok"] is False
    assert taxon["valueset_ok"] is None and "not configured" in taxon["notes"][0]
    assert [f["level"] for f in rep["findings"]] == ["valueset"]
    assert rep["summary"]["unchecked_prefixes"] == ["NCBITaxon", "PO"]
    assert rep["summary"]["unchecked"] == 3 and rep["summary"]["checked"] == 0


def test_offline_mode_checks_every_prefix_from_cache():
    inst = {"samp_taxon_id": [term("samp_taxon_id", "b5", "NCBITaxon:410658", "soil metagenome")], "_meta": {}}
    rep = normalize(inst, [], FakePlugin({}), offline=True)
    t = rep["terms"][0]
    assert t["checked"] and t["info_ok"] is False
    assert "offline cache" in rep["findings"][0]["message"]


def test_valueset_not_applicable_is_none_with_a_note():
    inst = {"env_medium": [term("env_medium", "b4", "ENVO:00002006", "liquid water", "MIMS.me.hydrocarbon-cores.6.0"),
                           term("env_medium", "b6", "ENVO:00001998", "soil", "")], "_meta": {}}
    rep = normalize(inst, [], FakePlugin(LABELS), valuesets=load_valuesets())
    t = by_key(rep)
    assert t[("b4", "env_medium")]["valueset_ok"] is None
    assert t[("b4", "env_medium")]["inferred_interface"] == "HcrCoresInterface"
    assert "no NMDC value set for HcrCoresInterface" in t[("b4", "env_medium")]["notes"][0]
    assert t[("b6", "env_medium")]["valueset_ok"] is None
    assert "unknown package" in t[("b6", "env_medium")]["notes"][0]
    assert rep["findings"] == []


def test_unlocatable_upstream_result_is_dropped_not_fatal():
    inst = {"env_medium": [term("env_medium", "b1", "ENVO:00001998", "soil")], "_meta": {}}
    stray = ValidationResult(type="binding_validation", severity=Severity.ERROR, message="?", instance={},
                             instantiates="X", context=["path: nowhere"])
    rep = normalize(inst, [stray], FakePlugin(LABELS))
    assert rep["findings"] == [] and rep["terms"][0]["info_ok"] is True


# --------------------------------------------------------------------------
# run_term_validation: failure modes never raise
# --------------------------------------------------------------------------

INST = {"env_medium": [term("env_medium", "b1", "ENVO:00001998", "soil")], "_meta": {"skipped_sentinels": 2}}


def test_missing_extra_is_reported_as_skipped(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "linkml_term_validator", None)
    monkeypatch.setitem(sys.modules, "linkml_term_validator.plugins", None)
    rep = run_term_validation(INST, cache_dir=tmp_path)
    assert rep["status"] == STATUS_SKIPPED
    assert "uv sync --extra ontology" in rep["reason"]
    assert rep["summary"]["terms"] == 1 and rep["summary"]["skipped_sentinels"] == 2
    assert rep["terms"] == [] and rep["findings"] == []
    assert rep["config"]["valuesets"]["nmdc_submission_schema_version"]


def test_unexpected_exception_is_reported_as_error(monkeypatch, tmp_path):
    pytest.importorskip("linkml_term_validator")
    from linkml.validator import Validator

    def boom(self, *a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(Validator, "validate", boom)
    rep = run_term_validation(INST, cache_dir=tmp_path)
    assert rep["status"] == STATUS_ERROR and "RuntimeError: disk on fire" in rep["reason"]


def test_service_outage_is_reported_as_unavailable(monkeypatch, tmp_path):
    pytest.importorskip("linkml_term_validator")
    from linkml.validator import Validator
    from linkml_term_validator.utils import OntologyServiceUnavailableError

    def outage(self, *a, **k):
        raise OntologyServiceUnavailableError("ENVO:1", ConnectionError("dns"))

    monkeypatch.setattr(Validator, "validate", outage)
    rep = run_term_validation(INST, cache_dir=tmp_path)
    assert rep["status"] == STATUS_UNAVAILABLE and "ENVO:1" in rep["reason"]


def test_bogus_adapter_is_reported_as_error_not_raised(tmp_path):
    pytest.importorskip("linkml_term_validator")
    rep = run_term_validation(INST, cache_dir=tmp_path, adapters={"ENVO": "sqlite:/nonexistent/x.db"})
    assert rep["status"] == STATUS_ERROR
    assert rep["config"]["adapters"]["ENVO"] == "sqlite:/nonexistent/x.db"


def test_env_var_adapters_are_read_and_malformed_ignored(monkeypatch, tmp_path):
    pytest.importorskip("linkml_term_validator")
    monkeypatch.setenv(run.ADAPTERS_ENV_VAR, "garbage")
    rep = run_term_validation(INST, cache_dir=tmp_path, offline=True)
    assert rep["config"]["adapters"]["ENVO"] == "sqlite:obo:envo"
    monkeypatch.setenv(run.ADAPTERS_ENV_VAR, "PO=sqlite:obo:po")
    rep = run_term_validation(INST, cache_dir=tmp_path, offline=True)
    assert rep["config"]["adapters"]["PO"] == "sqlite:obo:po"
    assert (tmp_path / "oak_config.effective.yaml").exists()


def test_offline_with_empty_cache_reports_not_found_without_network(tmp_path):
    pytest.importorskip("linkml_term_validator")
    rep = run_term_validation(INST, cache_dir=tmp_path, offline=True)
    assert rep["status"] == STATUS_OK
    assert rep["terms"][0]["info_ok"] is False
    assert "offline cache" in rep["findings"][0]["message"]


# --------------------------------------------------------------------------
# merge + summary
# --------------------------------------------------------------------------


def validation_ok(terms, **summary):
    base = {"status": STATUS_OK, "reason": None, "summary": {"terms": len(terms), "checked": len(terms),
            "unchecked": 0, "unchecked_prefixes": [], "skipped_sentinels": 0, "errors": 0, "warnings": 0,
            "by_level": {}, "by_slot": {}}, "findings": [], "terms": terms, "tool": {"linkml_term_validator": "0.4.5"}}
    base["summary"].update(summary)
    return base


def entry(bs, slot, curie, **flags):
    e = {"biosample_id": bs, "slot": slot, "term_id": curie, "term_label": "", "prefix": "ENVO",
         "checked": True, "ontology_label": "", "obsolete": False, "env_package": None,
         "inferred_interface": None, "valueset_enum": None, "notes": [],
         "info_ok": True, "label_ok": True, "anchor_ok": True, "valueset_ok": None}
    e.update(flags)
    return e


def test_merge_sets_flags_only_for_matching_committed_curie():
    report = {"rows": [
        {"biosample_id": "b1", "slot": "env_medium", "committed_curie": "ENVO:00001998", "validator": {f: None for f in FLAGS}},
        {"biosample_id": "b2", "slot": "env_medium", "committed_curie": "ENVO:00000447", "validator": {f: None for f in FLAGS}},  # curator changed it
        {"biosample_id": "b3", "slot": "env_medium", "committed_curie": None, "outcome": "left_sentinel", "validator": {f: None for f in FLAGS}},
        {"biosample_id": "b4", "slot": "env_medium", "committed_curie": None, "outcome": "predicted"},  # no validator dict at all
    ]}
    validation = validation_ok([
        entry("b1", "env_medium", "ENVO:00001998", label_ok=False),
        entry("b2", "env_medium", "ENVO:00001998"),
        entry("b4", "env_medium", "ENVO:00001998", valueset_ok=True),
    ])
    assert merge_into_curation_report(report, validation) == 2
    rows = {r["biosample_id"]: r for r in report["rows"]}
    assert rows["b1"]["validator"] == {"info_ok": True, "label_ok": False, "anchor_ok": True, "valueset_ok": None}
    assert rows["b2"]["validator"] == {f: None for f in FLAGS}                       # untouched
    assert rows["b3"]["validator"] == {f: None for f in FLAGS}                       # sentinel untouched
    assert rows["b4"]["validator"]["valueset_ok"] is True                             # dict created


def test_merge_is_a_noop_unless_status_ok():
    report = {"rows": [{"biosample_id": "b1", "slot": "env_medium", "committed_curie": "ENVO:00001998", "validator": {}}]}
    for status in (STATUS_SKIPPED, STATUS_ERROR, STATUS_UNAVAILABLE):
        v = validation_ok([entry("b1", "env_medium", "ENVO:00001998")])
        v["status"] = status
        assert merge_into_curation_report(report, v) == 0
    assert report["rows"][0]["validator"] == {}


def test_format_summary_ok_and_not_ok():
    v = validation_ok([entry("b1", "env_medium", "ENVO:00001998")], errors=1, warnings=2, unchecked=3,
                      unchecked_prefixes=["NCBITaxon"], skipped_sentinels=4, by_level={"label": 1, "anchor": 2})
    v["findings"] = [{"level": "label", "severity": "error", "biosample_id": "b1", "slot": "env_medium",
                      "term_id": "ENVO:00001998", "message": "m"}] * 3
    text = format_summary(v, max_findings=2)
    assert "1 term(s) checked; 1 error(s); 2 warning(s); 3 unchecked (NCBITaxon not configured); 4 ENVO:00000000 sentinel(s) skipped" in text
    assert "by level: label=1, anchor=2" in text
    assert text.count("[error/label]") == 2 and "1 more finding(s)" in text
    v["status"] = STATUS_UNAVAILABLE
    v["reason"] = "dns"
    text = format_summary(v)
    assert text.startswith("Term validation unavailable: dns") and "NOT checked" in text


# --------------------------------------------------------------------------
# CLI (validator stubbed) and pipeline step
# --------------------------------------------------------------------------


def _stub_run(monkeypatch, validation):
    calls = {}

    def fake(instance, **kwargs):
        calls["instance"] = instance
        calls["kwargs"] = kwargs
        return json.loads(json.dumps(validation))

    monkeypatch.setattr(cli, "run_term_validation", fake)
    return calls


def test_cli_writes_report_merges_and_exit_codes(monkeypatch, tmp_path):
    db = database()
    db_path = tmp_path / "x_nmdc.json"
    db_path.write_text(json.dumps(db))
    report_path = tmp_path / "x_nmdc_curation_report.json"
    report_path.write_text(json.dumps(curation_report_for(db)))
    v = validation_ok([entry("nmdc:bsm-99-00000001", "env_medium", "ENVO:00001998")], warnings=1)
    calls = _stub_run(monkeypatch, v)

    rc = cli.main([str(db_path), "--curation-report", str(report_path), "--adapter", "PO=sqlite:obo:po",
                   "--cache-dir", str(tmp_path / "cache"), "--no-valuesets", "--lenient", "--offline"])
    assert rc == cli.EXIT_CLEAN
    out = json.loads((tmp_path / "x_nmdc_term_validation_report.json").read_text())
    assert out["status"] == "ok" and out["input"] == str(db_path)
    assert calls["instance"]["_meta"]["skipped_sentinels"] == 1
    assert calls["kwargs"] == {"cache_dir": tmp_path / "cache", "adapters": {"PO": "sqlite:obo:po"},
                               "lenient": True, "offline": True, "valuesets_path": None}
    merged = json.loads(report_path.read_text())
    row = next(r for r in merged["rows"] if r["biosample_id"].endswith("01") and r["slot"] == "env_medium")
    assert row["validator"]["info_ok"] is True

    assert cli.main([str(db_path), "--fail-on", "warning"]) == cli.EXIT_FINDINGS
    v["summary"]["errors"] = 1
    assert cli.main([str(db_path)]) == cli.EXIT_FINDINGS
    assert cli.main([str(db_path), "--fail-on", "never"]) == cli.EXIT_CLEAN
    v["status"] = STATUS_SKIPPED
    assert cli.main([str(db_path), "--fail-on", "never"]) == cli.EXIT_NOT_RUN
    assert cli.main([str(tmp_path / "missing.json")]) == cli.EXIT_NOT_RUN
    assert cli.main([str(db_path), "--adapter", "bad"]) == cli.EXIT_NOT_RUN


def test_cli_default_valuesets_and_env_adapters(monkeypatch, tmp_path):
    db_path = tmp_path / "x_nmdc.json"
    db_path.write_text(json.dumps(database()))
    calls = _stub_run(monkeypatch, validation_ok([]))
    monkeypatch.setenv(run.ADAPTERS_ENV_VAR, "NCBITaxon=ols:ncbitaxon,PO=ols:po")
    assert cli.main([str(db_path), "--adapter", "PO=sqlite:obo:po"]) == cli.EXIT_CLEAN
    assert calls["kwargs"]["valuesets_path"] == DEFAULT_VALUESETS_PATH
    assert calls["kwargs"]["adapters"] == {"NCBITaxon": "ols:ncbitaxon", "PO": "sqlite:obo:po"}  # CLI wins


def test_pipeline_step_never_raises_and_merges(monkeypatch, tmp_path, capsys):
    from nmdc_ingest_agent.sources.ncbi import translate as T

    db = database()
    out = tmp_path / "ncbi_X_nmdc.json"
    out.write_text(json.dumps(db))
    report = curation_report_for(db)
    report_path = tmp_path / "ncbi_X_nmdc_curation_report.json"
    report_path.write_text(json.dumps(report))

    def explode(instance, **kw):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(T, "run_term_validation", explode)
    assert T.run_term_validation_step(db, str(out), report, str(report_path)) is None
    assert "Term validation skipped: RuntimeError: kaboom" in capsys.readouterr().err
    assert not (tmp_path / "ncbi_X_nmdc_term_validation_report.json").exists()

    v = validation_ok([entry("nmdc:bsm-99-00000001", "env_medium", "ENVO:00001998", anchor_ok=False)])
    monkeypatch.setattr(T, "run_term_validation", lambda instance, **kw: v)
    result = T.run_term_validation_step(db, str(out), report, str(report_path))
    assert result["status"] == "ok"
    assert (tmp_path / "ncbi_X_nmdc_term_validation_report.json").exists()
    saved = json.loads(report_path.read_text())
    row = next(r for r in saved["rows"] if r["biosample_id"].endswith("01") and r["slot"] == "env_medium")
    assert row["validator"] == {"info_ok": True, "label_ok": True, "anchor_ok": False, "valueset_ok": None}
    captured = capsys.readouterr().out
    assert "Term validation: 1 term(s) checked" in captured and "1 row(s) received validator flags" in captured

    v["status"] = STATUS_UNAVAILABLE
    v["reason"] = "dns"
    assert T.run_term_validation_step(db, str(out), report, str(report_path))["status"] == "unavailable"
    assert "Term validation unavailable: dns" in capsys.readouterr().out


def test_curation_report_skeleton_has_label_ok():
    from nmdc_schema import nmdc
    from nmdc_ingest_agent.sources.ncbi import translate as T

    def civ_obj(curie, name):
        return nmdc.ControlledIdentifiedTermValue(
            term=nmdc.OntologyClass(id=curie, name=name, type="nmdc:OntologyClass"),
            type="nmdc:ControlledIdentifiedTermValue")

    bs = nmdc.Biosample(id="nmdc:bsm-99-1", name="s", type="nmdc:Biosample", associated_studies=["nmdc:sty-99-1"],
                        env_broad_scale=civ_obj("ENVO:00000447", "marine biome"),
                        env_local_scale=civ_obj("ENVO:00000000", "(not provided)"),
                        env_medium=civ_obj("ENVO:00001998", "soil"))
    skeleton = T.build_curation_report_skeleton(nmdc.Database(biosample_set=[bs]))
    assert len(skeleton["rows"]) == 3
    for row in skeleton["rows"]:
        assert row["validator"] == {"info_ok": None, "label_ok": None, "anchor_ok": None, "valueset_ok": None}
    assert skeleton["rows"][1]["outcome"] == "left_sentinel"


# --------------------------------------------------------------------------
# run notes block
# --------------------------------------------------------------------------


def test_run_notes_term_validation_block(tmp_path):
    v = validation_ok([entry("b1", "env_medium", "ENVO:00001998")], errors=1, warnings=1,
                      unchecked_prefixes=["NCBITaxon"], skipped_sentinels=2)
    v["findings"] = [
        {"level": "valueset", "severity": "warning", "biosample_id": "b1", "slot": "env_medium", "term_id": "ENVO:1", "message": "outside"},
        {"level": "existence", "severity": "error", "biosample_id": "b2", "slot": "env_medium", "term_id": "ENVO:2", "message": "missing"},
    ]
    v["tool"]["ontology_versions"] = {"ENVO": "2025-10-20", "PO": None}
    tv = run_notes.summarize_term_validation(v)
    assert tv["ontology_versions"] == {"ENVO": "2025-10-20"}
    assert list(tv["findings"]) == ["existence", "valueset"]  # hard failures first
    md = run_notes.render_run_notes({"source": "ncbi", "accession": "X"}, {}, {}, tv)
    block = md.split("## Validation")[1].split("## Decisions")[0]
    assert "linkml-term-validator 0.4.5" in block and "**1 error(s)**" in block
    assert "against ENVO 2025-10-20" in block
    assert "NCBITaxon terms unchecked" in block and "2 ENVO:00000000 sentinel(s) skipped" in block
    assert block.index("existence (1)") < block.index("valueset (1)")
    assert "<!-- local linkml load result" in block  # agent placeholder kept

    v["status"] = "skipped"
    v["reason"] = "not installed"
    md = run_notes.render_run_notes({}, {}, {}, run_notes.summarize_term_validation(v))
    assert "**skipped** — not installed" in md
    # no term validation -> section unchanged
    assert "Ontology term QC" not in run_notes.render_run_notes({}, {}, {})

    out = run_notes.write_run_notes(tmp_path, {}, {}, {}, tv)
    assert "Ontology term QC" in out.read_text()


# --------------------------------------------------------------------------
# Real linkml-term-validator + cached ENVO (skipped when ENVO is not cached)
# --------------------------------------------------------------------------


@pytest.mark.skipif(not ENVO_DB.exists(), reason="oaklib ENVO sqlite not cached locally")
def test_end_to_end_against_cached_envo(tmp_path):
    pytest.importorskip("linkml_term_validator")
    db = database()
    validation = run_term_validation(extract_observed_terms(db), cache_dir=tmp_path / "cache")
    assert validation["status"] == STATUS_OK, validation["reason"]
    t = by_key(validation)
    b = lambda i: f"nmdc:bsm-99-{i:08d}"  # noqa: E731

    clean = t[(b(1), "env_broad_scale")]
    assert (clean["info_ok"], clean["label_ok"], clean["anchor_ok"], clean["valueset_ok"]) == (True, True, True, True)
    assert clean["ontology_label"] == "temperate broadleaf forest biome"
    brine = t[(b(2), "env_broad_scale")]
    assert (brine["info_ok"], brine["label_ok"], brine["anchor_ok"], brine["valueset_ok"]) == (True, False, False, False)
    assert brine["ontology_label"] == "liquid water"
    assert t[(b(2), "env_medium")]["label_ok"] is True            # "Soil" vs "soil": case-insensitive
    assert (b(2), "env_local_scale") not in t                       # sentinel skipped
    assert t[(b(3), "env_broad_scale")]["info_ok"] is False         # ENVO:99999999
    assert t[(b(3), "env_local_scale")]["anchor_ok"] is False       # biome in local scale
    obsolete = t[(b(3), "env_medium")]
    assert obsolete["obsolete"] is True and obsolete["info_ok"] is False
    hcr = t[(b(4), "env_medium")]
    assert hcr["valueset_ok"] is None and hcr["inferred_interface"] == "HcrCoresInterface"
    leaf = t[(b(5), "env_medium")]
    assert leaf["checked"] is False and leaf["valueset_ok"] is True  # PO unchecked, but in the value set
    assert t[(b(5), "env_local_scale")]["anchor_ok"] is True       # understory: not a biome
    assert t[(b(6), "env_local_scale")]["anchor_ok"] is False      # marine biome in local scale
    assert t[(b(1), "samp_taxon_id")]["checked"] is False

    assert validation["tool"]["ontology_versions"].get("ENVO")  # e.g. "2025-10-20"
    assert "against ENVO" in format_summary(validation)
    s = validation["summary"]
    assert s["skipped_sentinels"] == 1 and s["unchecked_prefixes"] == ["NCBITaxon", "PO"]
    assert s["by_level"]["existence"] == 1 and s["by_level"]["obsolete"] == 1 and s["by_level"]["label"] == 1
    assert s["by_level"]["anchor"] == 3 and s["errors"] == 3
    # caches landed under our cache dir, never in the working directory
    assert (tmp_path / "cache" / "envo" / "terms.csv").exists()
    assert not Path("cache").exists()
    # running the CLI on the same data reproduces the report and exits 1 on errors
    db_path = tmp_path / "x_nmdc.json"
    db_path.write_text(json.dumps(db))
    assert cli.main([str(db_path), "--cache-dir", str(tmp_path / "cache")]) == cli.EXIT_FINDINGS
    rerun = json.loads((tmp_path / "x_nmdc_term_validation_report.json").read_text())
    assert rerun["summary"] == s
