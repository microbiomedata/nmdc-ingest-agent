---
name: ingest-run-notes
description: "Use this skill at the end of an ingest or curation run to write a short human-readable RUN_NOTES.md a curator can review and act on: record counts, what resolved deterministically vs by LLM judgment, what was deferred and why, ambiguous cases needing a human decision, and validation results. It also seeds a DECISIONS.md the human edits and the next run reads back. Trigger at the end of any ncbi-to-nmdc or curation run, instead of leaving only machine-only JSON reports."
---

# Ingest run notes

At the end of an ingest/curation run, write a small, PR-reviewable **`RUN_NOTES.md`** so a
human can see what happened and steer the next run. This replaces reading the multi-MB
`curation_report.json` / `curation_inputs.json` (which stay in gitignored `results/` for
machines) with one page a curator actually reads.

## Files (per run)

Everything for a run lives in `runs/<source>_<accession>/` (committed):

- `RUN_NOTES.md` — **machine-generated, overwritten every run.** The summary below.
- `DECISIONS.md` — **human-authored. The agent reads it (ingest Step 0) and never writes it.**
  Seeded once with a stub; after that it is the human's steering file.
- `overrides.tsv` — machine-readable term overrides as an SSSOM set (see
  `nmdc-ontology-mapping`). Seeded empty; the human/agent adds rows to force specific
  resolutions on the next run.

The generated/hand-authored split is deliberate: regenerating `RUN_NOTES.md` must never
clobber the human's `DECISIONS.md`. `write_run_notes` creates the two human files only if
they are absent.

## Generate the notes

Most of `RUN_NOTES.md` is computed from artifacts the pipeline already wrote:

```bash
uv run python -m nmdc_ingest_agent.run_notes \
    --deliverable results/ncbi_<ACC>_nmdc.json \
    --curation-report results/ncbi_<ACC>_nmdc_curation_report.json \
    --out-dir runs/ncbi_<ACC> \
    --source ncbi --accession <ACC> --env <dev|prod> \
    --command "uv run nmdc-ingest-ncbi <ACC>" --mint-mode <placeholder|real>
```

That fills: run metadata, record counts (per collection), a per-slot resolution table
(resolved / deferred / flagged), and the deferred + flagged biosample backlogs.

## Then annotate the judgment sections

The generator leaves two sections as HTML-comment placeholders because they need run context
only you have — fill them in:

- **Exclusions** — what was dropped and why (e.g. "4,617 MAG-only biosamples excluded: no SRA
  run"). Never leave a silent drop unexplained.
- **Validation** — the local linkml load result and the runtime `json:validate` result, plus
  any known failures (elink flakiness, a 502 on a very large payload).

Also phrase each genuinely **ambiguous** case as a specific question for the PI (a
mixed-environment consensus break, a primer in no database, an ambiguous host) so the human
can answer it directly.

## The steering loop

1. Agent writes `RUN_NOTES.md` and seeds `DECISIONS.md` / `overrides.tsv`.
2. Human reviews `RUN_NOTES.md`, then edits `DECISIONS.md` (free-form directives) and/or adds
   `overrides.tsv` rows.
3. Next run: the ingest skill reads `DECISIONS.md` at Step 0 and applies `overrides.tsv`
   before curating, then regenerates `RUN_NOTES.md`.

A blank template of the generated file is in
[`assets/run_notes_template.md`](assets/run_notes_template.md) for reference.
