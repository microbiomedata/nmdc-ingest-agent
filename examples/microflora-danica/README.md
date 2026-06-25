# MicroFlora Danica record examples

Single-record JSON files extracted from the NMDC ingest output for NCBI BioProject [PRJNA1071982](https://www.ncbi.nlm.nih.gov/bioproject/?term=PRJNA1071982) — *MicroFlora Danica* ([Sereika et al., Nature 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC12823411/)). Useful as reference when reading the NMDC LinkML schema, designing downstream tooling, or sanity-checking ingest output.

**Source.** All examples were extracted verbatim from a **single pipeline build** — one run of `uv run nmdc-ingest-ncbi PRJNA1071982` (default output `results/ncbi_PRJNA1071982_nmdc.json`, which is gitignored and not checked in). Record content is unedited. Because every example comes from the same run, the placeholder ids cross-reference: the `material_processing_set`, `processed_sample_set`, `data_generation_set/01`, and `data_object_set/01` examples form **one connected chain** rooted at the `02_forest` biosample (MFD00001), and every biosample's `associated_studies` matches the `study_set/01` id. (Regenerating produces a fresh run with new ids — see *Regenerating from a fresh ingest* below.)

**Material-processing chain.** Each sequenced experiment is modeled as the canonical NMDC chain rather than wiring the `NucleotideSequencing` straight to the `Biosample`, with **one `NucleotideSequencing` + one `DataObject` per SRA run**:

```
Biosample
  --Extraction-->          ProcessedSample (extracted nucleic acid)
  --LibraryPreparation-->  ProcessedSample (sequencing library)
  --NucleotideSequencing--> DataObject        (one chain per run)
```

NCBI/SRA does not record wet-lab dates/mass/institution (left unset), but the SRA library descriptor *is* carried on the `LibraryPreparation` (`library_strategy`, `library_source`, `library_selection`, `lib_layout`). `protocol_link` is parsed from a DOI in the `DESIGN_DESCRIPTION` (MFD's WGS designs cite the methods DOI; amplicon designs cite none). `target_gene` is committed by the pipeline only when the design names one **explicit** rRNA gene; the **operon** amplicons (which name no single gene) are resolved by the model-agnostic `nmdc-target-gene` curation skill — bacterial → `16S_rRNA`, eukaryotic → `18S_rRNA`. (These examples show the post-curation values.) Record names follow the schema-PR example conventions (e.g. `DNA extraction process for MFD00001`; the library `ProcessedSample` is named after the SRA library name like `ilm_MFD00001`). The example chain links `02_forest` → `material_processing_set/01_extraction` → `processed_sample_set/01_extracted_dna` → `material_processing_set/02_library_preparation` → `processed_sample_set/02_sequencing_library` → `data_generation_set/01` → `data_object_set/01`.

> **Manifest.** The chain is built **per unique library** (keyed on SRA library name + descriptor), not per experiment, and a `Manifest` (`manifest_category: poolable_replicates`) groups via `in_manifest` the `DataObject`s of any library whose runs share an instrument (≥2 runs sharing `(biosample, library_name, instrument)`). **MicroFlora Danica has one library/run per experiment, so it produces no `Manifest` records** — none appear in these examples (the behavior is covered by unit tests instead).

**Env-triad resolved at pipeline (v2 crosswalk).** For MFD biosamples the env-triad is resolved **deterministically in code** during the build: `MfdEnvTriadResolver` (`src/nmdc_ingest_agent/sources/ncbi/mfd.py`) joins each biosample's `samp_name`/`MFDID` to `data/mfdo-crosswalk-v2/mfd_biosamples_annotated.tsv` and commits `env_broad_scale`, `env_local_scale`, and `env_medium`, so the curation report records `outcome: "resolved_at_pipeline"` for all three slots. Every MFD biosample gets all three slots — **100% coverage, no `ENVO:00000000` sentinels**. The v2 mapping draws on the full five-level MFD habitat hierarchy plus GEE land-cover refinement, so it is finer-grained than NCBI's coarse `isolation_source` (e.g. `02_forest` resolves to `temperate broadleaf forest biome` / `temperate freshwater swamp forest`, not a generic `forest biome`). The former two-stage "emit sentinels → agent curation pass" flow still applies to non-MFD sources; for MFD it is superseded.

**Scope.** Database collections only (`study_set`, `biosample_set`, `material_processing_set`, `processed_sample_set`, `data_generation_set`, `data_object_set`). The curation sidecars are not represented here.

**ID note.** Every example uses placeholder NMDC IDs (`-99-` shoulder) **except** `instrument_used`. Real ingest requires re-running with `--mint-real-ids`. Placeholder IDs are randomly minted each run, so re-extracting from a fresh ingest will produce different ids matching the same criteria.

`instrument_used` is the exception: instruments are **resolved**, not minted. The pipeline matches each SRA `INSTRUMENT_MODEL` string against the live NMDC `instrument_set` (by instrument `name`, falling back to `InstrumentModelEnum` aliases) and asserts the existing `nmdc:inst-…` id. These ids are stable real identifiers, identical across runs and independent of `--mint-real-ids`. Resolution defaults to the **dev** runtime environment (`--env`/`NMDC_RUNTIME_ENV`); the ids above (`nmdc:inst-14-mr4r2w09`, `nmdc:inst-15-qkz3d028`) come from dev, where this BioProject's three sequencers all have `instrument_set` entries. A model with no `instrument_set` match resolves to nothing and leaves `instrument_used` empty.

**These are reference documents, not test fixtures.** They illustrate the variation that shows up in pipeline output; they are not asserted-against by any automated test.

**Schema version.** The `LibraryPreparation` library-descriptor slots and the `SRA toolkit-accessible sequence data` data-object type require **nmdc-schema 11.21.0** ([nmdc-schema #3214](https://github.com/microbiomedata/nmdc-schema/pull/3214)); `pyproject.toml` requires `nmdc-schema>=11.21.0`.

## study_set/

| File | Source id | Demonstrates |
|---|---|---|
| `01_research_study.json` | `nmdc:sty-99-e87ce5df` | NMDC `Study` for the MicroFlora Danica BioProject — id, name, description (NCBI-provided, mentions the project scope and metadata GitHub repo), type. All biosample/data-generation examples reference this id via `associated_studies`. |

## biosample_set/

Eight examples spanning the v2-resolved MFDO categories, including a sample-type axis (sediment), a built-environment case, and a missing-geolocation case. All three env-triad slots are populated (`resolved_at_pipeline`).

| File | Source id | env_broad_scale | env_local_scale | env_medium | samp_taxon_id | Notes |
|---|---|---|---|---|---|---|
| `01_cropland_agricultural_field.json` | `nmdc:bsm-99-c45da6f8` | `ENVO:01000245` cropland biome | `ENVO:00000114` agricultural field | `ENVO:00002259` agricultural soil | soil metagenome | The **modal** MFDO mapping — every slot has a precise ENVO term. 3,002 biosamples (~28%) follow this pattern. Gold-standard for a clean resolved record. |
| `02_forest.json` | `nmdc:bsm-99-3e9c63b0` | `ENVO:01000202` temperate broadleaf forest biome | `ENVO:01000398` temperate freshwater swamp forest | `ENVO:00001998` soil | soil metagenome | Forest sample (MFD00001). Shows v2 specificity: the hab2/hab3 levels (Temperate forests → Alluvial woodland) plus GEE refinement drive a precise `temperate freshwater swamp forest` feature, not the generic `forest ecosystem` v1 produced. **This is the biosample at the head of the example material-processing chain.** |
| `03_grassland.json` | `nmdc:bsm-99-c8e0c58a` | `ENVO:01000177` grassland biome | `ENVO:01001811` temperate grassland | `ENVO:00001998` soil | soil metagenome | Grassland sample — 852 records (~8%) share this triple. v2 maps the local feature to `temperate grassland` (Denmark context) rather than a generic grassland ecosystem. |
| `04_urban_park.json` | `nmdc:bsm-99-8eda989f` | `ENVO:01000249` urban biome | `ENVO:00000562` park | `ENVO:00001998` soil | soil metagenome | Urban green-space sample — 628 records (~6%). Demonstrates the `urban biome` + park feature mapping. |
| `05_marine_coast_sediment.json` | `nmdc:bsm-99-49231047` | `ENVO:00000447` marine biome | `ENVO:00000016` sea | `ENVO:03000033` marine sediment | sediment metagenome | Marine sediment sample — 320 records (~3%). Different sample-type axis (Sediment, not Soil) → different env_medium (`marine sediment`). |
| `06_wastewater_treatment.json` | `nmdc:bsm-99-cb37cb00` | `ENVO:01000249` urban biome | `ENVO:00002043` wastewater treatment plant | `ENVO:00002001` waste water | wastewater metagenome | Built-environment sample. `env_medium` is `waste water` (not soil/sediment) and `samp_taxon_id` reflects the environment. |
| `07_coastal_dune.json` | `nmdc:bsm-99-51cd6712` | `ENVO:01000215` temperate shrubland biome | `ENVO:00000416` coastal dune | `ENVO:00001998` soil | soil metagenome | **v1→v2 improvement.** Natural Dunes had no clean broad-biome term under v1, so v1 left `env_broad_scale` an `ENVO:00000000` sentinel. v2 resolves all three slots (`temperate shrubland biome` / `coastal dune` / `soil`). 457 records (~4%). |
| `08_no_lat_lon.json` | `nmdc:bsm-99-e30df33c` | `ENVO:01000245` cropland biome | `ENVO:00000114` agricultural field | `ENVO:00002259` agricultural soil | soil metagenome | Same env triad as `01` but `lat_lon` is null. The env-triad is resolved from the MFD habitat barcode, independent of coordinates — ~26% of biosamples lack `lat_lon`. |

## material_processing_set/

The `Extraction` and `LibraryPreparation` steps of the chain (see **Material-processing chain** above) — both in this collection. `01`/`02` are the consecutive steps of the `02_forest` (MFD00001) WGS chain; `03`/`04` are amplicon `LibraryPreparation`s whose **`target_gene`** was resolved by the `nmdc-target-gene` curation skill (operons name no single gene, so the pipeline leaves them unset) — a bacterial operon → `16S_rRNA`, a eukaryotic operon → `18S_rRNA`.

| File | Source id | `has_input` → `has_output` | Demonstrates |
|---|---|---|---|
| `01_extraction.json` | `nmdc:extrp-99-a1ffa734` | Biosample `02_forest` → extracted-DNA ProcessedSample (`01_extracted_dna`) | `Extraction` consuming the Biosample directly. `extraction_targets=["DNA"]`; named `DNA extraction process for MFD00001`. Dates / input mass / processing institution are unset (not in NCBI). |
| `02_library_preparation.json` | `nmdc:libprp-99-c39986fb` | extracted-DNA ProcessedSample (`01_extracted_dna`) → library ProcessedSample (`02_sequencing_library`) | WGS metagenome `LibraryPreparation` for MFD00001. Carries the SRA descriptor (`library_strategy=WGS`, `library_source=METAGENOMIC`, `library_selection="size fractionation"`, `lib_layout=paired`) and a `protocol_link` (the DOI parsed from its `DESIGN_DESCRIPTION`). No `target_gene` (the WGS design names no rRNA target). |
| `03_amplicon_library_preparation.json` | `nmdc:libprp-99-2c37e48b` | extracted-DNA ProcessedSample → library ProcessedSample (consumed by `data_generation_set/02`) | **Bacterial amplicon** `LibraryPreparation`: `library_strategy=AMPLICON`, `library_selection=PCR`, `lib_layout=single`, and **`target_gene="16S_rRNA"`** — the design "...amplify bacterial rRNA operons" names no single gene, so this was set by the `nmdc-target-gene` curation skill (bacterial SSU = 16S). No `protocol_link` (the amplicon design cites no DOI) — the inverse of `02`. |
| `04_amplicon_eukaryotic_library_preparation.json` | `nmdc:libprp-99-654373f2` | extracted-DNA ProcessedSample → library ProcessedSample | **Eukaryotic amplicon** `LibraryPreparation` (MFD's `pb_eukoperon` libraries): **`target_gene="18S_rRNA"`** — design "...amplify eukaryotic rRNA operons" → eukaryotic SSU = 18S (*not* 16S), set by the `nmdc-target-gene` curation skill. 450 MFD libraries are 18S; this is the case the LLM-judgment curation gets right. |

## processed_sample_set/

The two `ProcessedSample` outputs threaded through the `02_forest` chain — the extracted nucleic acid and the sequencing library. NCBI supplies no concentration/purity detail.

| File | Source id | Role | Demonstrates |
|---|---|---|---|
| `01_extracted_dna.json` | `nmdc:procsm-99-18499525` | output of `01_extraction`, input of `02_library_preparation` | `ProcessedSample` named `Extracted DNA for MFD00001`. |
| `02_sequencing_library.json` | `nmdc:procsm-99-7cb3bc6c` | output of `02_library_preparation`, input of `data_generation_set/01` | `ProcessedSample` named after the SRA library name (`ilm_MFD00001`), with `description = "Library for sequencing for MFD00001"`. This is what the `NucleotideSequencing` consumes (its `has_input`), **not** the Biosample. |

## data_generation_set/

**One `NucleotideSequencing` per SRA run** (MFD has one run per experiment). Each record has a single `has_input` (the library `ProcessedSample`, never the Biosample directly), a single `has_output` `DataObject`, `insdc_experiment_identifiers` + `insdc_bioproject_identifiers`, and a name like `Run <SRR> for experiment <SRX> - <samp_name>`. Variation is along two correlated axes — sequencer and analyte category:

- **NovaSeq 6000 → `metagenome`** (10,683 experiments, ~89%) — the WGS shotgun libraries.
- **Sequel IIe / PromethION → `amplicon_sequencing_assay`** (900 + 412, ~11%) — long-read amplicon libraries.

The `analyte_category` is derived from the SRA `LIBRARY_SOURCE`/`LIBRARY_STRATEGY` pair (issue #46): `WGS`+`METAGENOMIC`→`metagenome`, `AMPLICON`+`METAGENOMIC`→`amplicon_sequencing_assay`.

| File | Source id | Instrument id | analyte_category | Demonstrates |
|---|---|---|---|---|
| `01_metagenome_nucleotide_sequencing.json` | `nmdc:dgns-99-3ae01571` | `nmdc:inst-14-mr4r2w09` — Illumina NovaSeq 6000 | `metagenome` | Modal record and terminal step of the example chain: `has_input` is the library `ProcessedSample` (`02_sequencing_library`), `has_output` is `data_object_set/01`. `instrument_used` is a **real** resolved Instrument id (matched on `name` against the live `instrument_set`), not a minted placeholder. |
| `02_amplicon_sequencing_sequel.json` | `nmdc:dgns-99-b9e11006` | `nmdc:inst-15-qkz3d028` — Sequel IIe | `amplicon_sequencing_assay` | Long-read amplicon assay (its library is `material_processing_set/03`). This is exactly the case the old analyte logic mislabeled `metagenome`; it now resolves to `amplicon_sequencing_assay`. |
| `03_amplicon_sequencing_promethion.json` | `nmdc:dgns-99-75b33b27` | `nmdc:inst-15-pc5b4k98` — PromethION | `amplicon_sequencing_assay` | Same analyte on the third sequencer — documents that this BioProject uses three distinct instruments (NovaSeq 6000, Sequel IIe, PromethION). |

## data_object_set/

One data-object type, one example (one per SRA run).

| File | Source id | Demonstrates |
|---|---|---|
| `01_sra_sequence_data.json` | `nmdc:dobj-99-193daaf1` | `data_object_type="SRA toolkit-accessible sequence data"`, `data_category="instrument_data"`, `insdc_run_identifiers=["insdc.run:SRR…"]`, and `was_generated_by` pointing back at the run's `NucleotideSequencing` (`data_generation_set/01`). There is **no** `url` — the file is reached via the SRA toolkit and the INSDC run accession. **Caveat:** `md5_checksum` and `file_size_bytes` are null — NCBI's source-side metadata does not expose these for SRA runs; they are filled when files are actually retrieved/staged for ingest. |

## Validation snippet

`material_processing_set` mixes `Extraction` and `LibraryPreparation`, so this snippet validates each file against the class named by its own `type`:

```bash
uv run python -c "
import json, pathlib
from nmdc_schema import nmdc
from linkml_runtime.loaders import json_loader
type2cls = {'nmdc:Study': nmdc.Study,
            'nmdc:Biosample': nmdc.Biosample,
            'nmdc:Extraction': nmdc.Extraction,
            'nmdc:LibraryPreparation': nmdc.LibraryPreparation,
            'nmdc:ProcessedSample': nmdc.ProcessedSample,
            'nmdc:NucleotideSequencing': nmdc.NucleotideSequencing,
            'nmdc:DataObject': nmdc.DataObject}
for p in sorted(pathlib.Path('examples/microflora-danica').rglob('*.json')):
    rec = json.loads(p.read_text())
    json_loader.loads(p.read_text(), target_class=type2cls[rec['type']])
    print(f'OK  {p}')
"
```

## Regenerating from a fresh ingest

Placeholder ids are random each run, so re-extract **every** example from one fresh build to keep the connected chain consistent (the `02_forest` → extraction → … → data object wiring depends on all records sharing a single minting run).

1. `uv run nmdc-ingest-ncbi PRJNA1071982` — the pipeline resolves the MFD env-triad in code from the v2 crosswalk (`mfd_biosamples_annotated.tsv` must be present under `data/mfdo-crosswalk-v2/`), so the output already carries fully populated triad slots — no separate curation pass.
2. Re-extract each example from that single output file. Biosamples are matched by the env-triad CURIEs in their table rows (and `02_forest` by `samp_name == "MFD00001"`); the chain records are obtained by walking from the chosen biosample: `Extraction` (`has_input` = biosample) → its `has_output` `ProcessedSample` → `LibraryPreparation` (`has_input` = that ProcessedSample) → its `has_output` `ProcessedSample` → `NucleotideSequencing` (`has_input` = that ProcessedSample) → its `has_output` `DataObject`. The `data_generation_set` examples additionally span the three instruments / two analyte categories.
3. Update the `Source id` columns above with the new ids.
4. Run the validation snippet.
5. Do not hand-edit record content — these are extracted-as-is examples.

## Adding a new example to this project

1. Identify the axis of variation it covers that isn't already represented.
2. Pick a representative from a pipeline output via `jq`.
3. Extract: `jq '.<collection>[] | select(.id=="<id>")' results/<output>.json > examples/microflora-danica/<collection>/NN_<short_label>.json` (next available number prefix).
4. Run the validation snippet.
5. Add a row to the matching table above.

For examples from a different project (new accession, new source), create a sibling project folder under `examples/` instead — see the top-level [`examples/README.md`](../README.md) for the convention.
