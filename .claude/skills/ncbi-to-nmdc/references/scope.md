# Record modeling — what `ncbi-to-nmdc` produces

This skill produces `Study`, `Biosample`, `LibraryPreparation`, `ProcessedSample`, `DataGeneration`, `DataObject`, and (for poolable replicate runs) `Manifest` records.

The pipeline reconstructs the NMDC material-processing chain so a `NucleotideSequencing` consumes a `ProcessedSample` rather than the `Biosample` directly, and emits **one `NucleotideSequencing` + one `DataObject` per SRA run**:

```
Biosample
  --LibraryPreparation--> ProcessedSample (sequencing library)
  --NucleotideSequencing--> DataObject        (one chain per run)
```

**No `Extraction` record.** NCBI/SRA gives enough information to assert the library prep but **not** the nucleic-acid extraction (an `Extraction` is most likely 1:1 with the `Biosample`, but that cannot be confirmed). So the `LibraryPreparation` consumes the `Biosample` directly (`has_input = [biosample]`) and there is no extracted-nucleic-acid `ProcessedSample` — only the sequencing-library one.

**Per unique library — not per experiment.** Several SRA experiments can re-sequence one library (same `LIBRARY_NAME` + descriptor under distinct experiment accessions), so the chain is keyed on the unique library `(biosample, library_name, strategy, source, selection, layout)`: one `LibraryPreparation` (into `material_processing_set`) with one `ProcessedSample` output (into `processed_sample_set`), per unique library. Per-run: one `NucleotideSequencing` (into `data_generation_set`) and one `DataObject` (into `data_object_set`). When a library's runs **share an instrument** — i.e. ≥2 runs sharing `(biosample, library_name, instrument)` — a `Manifest` (`manifest_category: poolable_replicates`, into `manifest_set`) groups those run `DataObject`s via `in_manifest`. (MicroFlora Danica has one library/run per experiment, so it produces no `Manifest`s; a project like [`SAMEA7724300`](https://www.ncbi.nlm.nih.gov/Traces/study/?acc=SAMEA7724300) with 4 WGS experiments sharing one library yields 1 library chain, 4 data-generations, and 1 manifest.) NCBI/SRA does not record wet-lab dates/mass/institution, so those stay unset; the fields it *does* supply are populated:

- **LibraryPreparation** — `has_input` is the `Biosample`; `library_strategy`, `library_source`, `library_selection`, `lib_layout` (from the SRA library descriptor). `protocol_link` is parsed from a DOI in the `DESIGN_DESCRIPTION` (e.g. MFD's WGS "…see https://doi.org/…"). `target_gene` is committed by the pipeline only when the design names **one explicit rRNA gene** (e.g. "amplify bacterial 16S rRNA genes" → `16S_rRNA`); whole-operon amplicons are **left unset** — `target_gene` is single-valued with no whole-operon value (a bacterial operon spans 16S *and* 23S). The amplicon `description` (e.g. "Amplicon library preparation targeting bacterial rRNA operons using 8F and 2490R primers") is **not** parsed by the pipeline — the `nmdc-target-gene` curation skill (Step 5) writes it from the design text, and for operons it carries the target the omitted `target_gene` cannot.
- **ProcessedSample** — one per library, named after the SRA library name (e.g. `ilm_MFD00001`) with a descriptive `description`; it is the `LibraryPreparation`'s output and the `NucleotideSequencing`'s input.
- **DataObject** — `data_object_type: "SRA toolkit-accessible sequence data"`, `insdc_run_identifiers`, `was_generated_by` (the run's NucleotideSequencing); **no** URL.
- **NucleotideSequencing** — `insdc_experiment_identifiers` + `insdc_bioproject_identifiers`; named `Run <SRR> for experiment <SRX> - <samp_name>`.

Do **not** create `Extraction` or `Pooling` records — NCBI supports neither, so the `LibraryPreparation` consumes the `Biosample` directly.

> **Schema dependency:** the `LibraryPreparation` library-descriptor slots and the `SRA toolkit-accessible sequence data` data-object type were added in [nmdc-schema #3214](https://github.com/microbiomedata/nmdc-schema/pull/3214), released in **nmdc-schema 11.21.0**; `pyproject.toml` requires `nmdc-schema>=11.21.0`.
