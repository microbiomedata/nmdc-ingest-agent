"""Tests for the source-agnostic run-notes writer."""
from nmdc_ingest_agent.run_notes import (
    count_records,
    render_run_notes,
    summarize_report,
    write_run_notes,
)

REPORT = {
    "rows": [
        {"slot": "env_broad_scale", "outcome": "resolved_at_pipeline", "biosample_id": "b1"},
        {"slot": "env_broad_scale", "outcome": "left_sentinel", "biosample_id": "b2"},
        {"slot": "env_medium", "outcome": "predicted", "biosample_id": "b1"},
        {"slot": "env_medium", "outcome": "validator_rejected", "biosample_id": "b3"},
    ]
}
DELIVERABLE = {
    "study_set": [{"id": "s1"}],
    "biosample_set": [{"id": "b1"}, {"id": "b2"}, {"id": "b3"}],
    "data_object_set": [],  # empty -> omitted from counts
}
META = {"source": "ncbi", "accession": "PRJNATEST", "env": "dev", "date": "2026-07-13"}


def test_summarize_report_buckets():
    slots = summarize_report(REPORT)
    assert slots["env_broad_scale"]["counts"]["resolved_at_pipeline"] == 1
    assert slots["env_broad_scale"]["deferred"] == ["b2"]
    assert slots["env_medium"]["flagged"] == ["b3"]


def test_count_records_omits_empty():
    counts = count_records(DELIVERABLE)
    assert counts == {"study_set": 1, "biosample_set": 3}  # empty data_object_set dropped


def test_render_has_required_sections():
    md = render_run_notes(META, count_records(DELIVERABLE), summarize_report(REPORT))
    for heading in ["## Run metadata", "## Record counts", "## Resolution summary",
                    "## Deferred", "## Validation", "## Decisions for next run"]:
        assert heading in md
    assert "PRJNATEST" in md
    assert "| env_broad_scale | 1 | 1 | 0 |" in md  # resolved / deferred / flagged


def test_write_creates_files_and_preserves_decisions(tmp_path):
    out = tmp_path / "ncbi_PRJNATEST"
    # Pre-existing human-authored DECISIONS.md must NOT be overwritten.
    out.mkdir()
    (out / "DECISIONS.md").write_text("KEEP ME")

    notes = write_run_notes(out, META, count_records(DELIVERABLE), summarize_report(REPORT))

    assert notes.exists() and notes.name == "RUN_NOTES.md"
    assert (out / "DECISIONS.md").read_text() == "KEEP ME"  # preserved
    assert (out / "overrides.tsv").exists()  # seeded because absent

    # Regenerating overwrites RUN_NOTES.md but still preserves DECISIONS.md.
    write_run_notes(out, META, {}, {})
    assert (out / "DECISIONS.md").read_text() == "KEEP ME"
