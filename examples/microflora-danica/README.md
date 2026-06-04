# MicroFlora Danica record examples

Single-record JSON files extracted from the NMDC ingest output for NCBI BioProject [PRJNA1071982](https://www.ncbi.nlm.nih.gov/bioproject/?term=PRJNA1071982) — *MicroFlora Danica* ([Sereika et al., Nature 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC12823411/)). Useful as reference when reading the NMDC LinkML schema, designing downstream tooling, or sanity-checking ingest output.

**Source.** All examples were extracted verbatim from `results/ncbi_PRJNA1071982_nmdc.json` using `jq`. The only post-extraction update is to `instrument_used` on the two `data_generation_set` records, which now carry the **real** Instrument ids the current pipeline resolves (see ID note) rather than the placeholder ids the older minting path emitted; record content is otherwise unedited.

**Post-curation snapshot.** These records reflect the state of the NMDC JSON **after** an agent curation pass resolved env-triad sentinels. The two-stage architecture is:

1. **Deterministic pipeline** (`nmdc-ingest-ncbi`) emits records with `ENVO:00000000` sentinels in every env-triad slot, plus `curation_inputs.json` and `curation_report.json` sidecars.
2. **Agent curation pass** (driven by `.claude/skills/nmdc-env-triad.md` §1a Resolution and §1b Inference, with project-specific guidance from `.claude/skills/mfd-project-vocabulary.md`) replaces sentinels with resolved ENVO CURIEs and updates the curation-report rows.

For PRJNA1071982 specifically, after MIMAG/MISAG exclusion (10,689 surviving biosamples), the curation pass produced:
- **76.6% all-three-slots resolved** (8,182 biosamples)
- **13.8% broad+medium resolved, local sentinel** (1,474)
- **8.9% local+medium resolved, broad sentinel** (955)
- **0.7% medium-only resolved** (77)
- **<0.1% all-three-sentinel** (1)

The examples below mostly cover the all-resolved case (most common); one example (`07_partial_sentinel_broad`) demonstrates the partial-resolution outcome.

**Scope.** Database collections only (`study_set`, `biosample_set`, `data_generation_set`, `data_object_set`). The curation sidecars are not represented here.

**ID note.** Every example uses placeholder NMDC IDs (`-99-` shoulder) **except** `instrument_used`. Real ingest requires re-running with `--mint-real-ids`. Placeholder IDs are randomly minted each run, so re-extracting from a fresh ingest will produce different ids matching the same criteria.

`instrument_used` is the exception: instruments are **resolved**, not minted. The pipeline matches each SRA `INSTRUMENT_MODEL` string against the live NMDC `instrument_set` (by instrument `name`, falling back to `InstrumentModelEnum` aliases) and asserts the existing `nmdc:inst-…` id. These ids are stable real identifiers, identical across runs and independent of `--mint-real-ids`. Resolution defaults to the **dev** runtime environment (`--env`/`NMDC_RUNTIME_ENV`); the ids above (`nmdc:inst-14-mr4r2w09`, `nmdc:inst-15-qkz3d028`) come from dev, where this BioProject's three sequencers all have `instrument_set` entries. A model with no `instrument_set` match resolves to nothing and leaves `instrument_used` empty.

**These are reference documents, not test fixtures.** They illustrate the variation that shows up in pipeline output; they are not asserted-against by any automated test.

## study_set/

| File | Source id | Demonstrates |
|---|---|---|
| `01_research_study.json` | `nmdc:sty-99-1e6aca8f` | NMDC `Study` for the MicroFlora Danica BioProject — id, name, description (NCBI-provided, mentions the project scope and metadata GitHub repo), type. |

## biosample_set/

Eight examples spanning the resolved MFDO categories the curation pass populated, plus one partial-resolution case and one missing-geolocation case.

| File | Source id | env_broad_scale | env_local_scale | env_medium | samp_taxon_id | Notes |
|---|---|---|---|---|---|---|
| `01_cropland_agricultural_field.json` | `nmdc:bsm-99-c9045404` | `ENVO:01000245` cropland biome | `ENVO:00000114` agricultural field | `ENVO:00002259` agricultural soil | soil metagenome | The **modal** MFDO mapping — every slot has a precise ENVO term. 3,002 biosamples (~28%) follow this pattern. Gold-standard for what a clean post-curation record looks like. |
| `02_forest.json` | `nmdc:bsm-99-39be023e` | `ENVO:01000174` forest biome | `ENVO:01001243` forest ecosystem | `ENVO:00001998` soil | soil metagenome | Forest sample — 1,328 records (~12%) follow this triple. |
| `03_grassland.json` | `nmdc:bsm-99-e9974aa5` | `ENVO:01000177` grassland biome | `ENVO:01001206` grassland ecosystem | `ENVO:00001998` soil | soil metagenome | Grassland sample — 1,393 records (~13%). **Caveat:** `grassland biome` IS-A `grassland ecosystem` per ENVO's `is-a` graph (broad is more specific than local). Common MIxS submitter pattern; reviewers should expect this. |
| `04_urban_park.json` | `nmdc:bsm-99-9df69346` | `ENVO:01000249` urban biome | `ENVO:00000562` park | `ENVO:00001998` soil | soil metagenome | Urban green-space sample. Demonstrates the `urban biome` + park feature mapping. |
| `05_marine_coast_sediment.json` | `nmdc:bsm-99-94d1161b` | `ENVO:00000447` marine biome | `ENVO:00000485` sea shore | `ENVO:03000033` marine sediment | sediment metagenome | Coastal sediment sample. Different sample-type axis (Sediment, not Soil) → different env_medium (marine sediment). |
| `06_wastewater_treatment.json` | `nmdc:bsm-99-0e0ee33e` | `ENVO:01000219` anthropogenic terrestrial biome | `ENVO:00002043` wastewater treatment plant | `ENVO:00002001` waste water | wastewater metagenome | Built-environment sample. Different from the natural/agricultural categories above. `samp_taxon_id` also reflects the environment. |
| `07_partial_sentinel_broad.json` | `nmdc:bsm-99-ca7f4f52` | `ENVO:00000000` (sentinel) | `ENVO:00000170` dune | `ENVO:00001998` soil | soil metagenome | **Partial resolution** — agent couldn't commit a broad biome (no clean ENVO term under the biome anchor for the Natural Dunes MFDO context), so left that slot as sentinel. Local and medium did resolve. ~9% of records have this shape (broad sentinel, local+medium resolved). The curation-report row for this biosample's broad slot is `left_sentinel` — curator follow-up territory. |
| `08_no_lat_lon.json` | `nmdc:bsm-99-c3cb9c21` | `ENVO:01000245` cropland biome | `ENVO:00000114` agricultural field | `ENVO:00002259` agricultural soil | soil metagenome | Same env triad as `01` but `lat_lon` is null. Demonstrates that geolocation is independently sparse — the curation pass populated the triad based on the MFDO label even without coordinates. |

## data_generation_set/

The pilot is uniform in analyte category (`metagenome`) and library shape — every record has one `has_input` biosample and one `has_output` data object. Variation is the choice of one of three sequencers.

| File | Source id | Instrument id | Demonstrates |
|---|---|---|---|
| `01_metagenome_nucleotide_sequencing.json` | `nmdc:dgns-99-f45fec84` | `nmdc:inst-14-mr4r2w09` — Illumina NovaSeq 6000 (~89%) | Modal `NucleotideSequencing` record: metagenome analyte, single input biosample, single output data object, INSDC SRA experiment identifier. `instrument_used` is a **real** resolved Instrument id (matched on `name` against the live `instrument_set`), not a minted placeholder. |
| `02_metagenome_alternate_instrument.json` | `nmdc:dgns-99-a2ff7d7f` | `nmdc:inst-15-qkz3d028` — Sequel IIe (~7%) | Same shape, different instrument — documents that this BioProject uses three distinct sequencers (NovaSeq 6000, Sequel IIe, PromethION). `instrument_used` is likewise a real resolved Instrument id. |

## data_object_set/

One data-object type, one example.

| File | Source id | Demonstrates |
|---|---|---|
| `01_metagenome_raw_reads.json` | `nmdc:dobj-99-7bc50732` | `data_object_type="Metagenome Raw Reads"`, `data_category="instrument_data"`, NCBI SRA URL. **Caveat:** `md5_checksum` and `file_size_bytes` are null — NCBI's source-side metadata does not expose these for SRA runs; they need to be filled when files are actually retrieved/staged for ingest. |

## Validation snippet

```bash
uv run python -c "
from nmdc_schema import nmdc
from linkml_runtime.loaders import json_loader
import pathlib
target = {'study_set': nmdc.Study,
          'biosample_set': nmdc.Biosample,
          'data_generation_set': nmdc.NucleotideSequencing,
          'data_object_set': nmdc.DataObject}
for col, cls in target.items():
    for p in sorted(pathlib.Path(f'examples/microflora-danica/{col}').glob('*.json')):
        json_loader.loads(p.read_text(), target_class=cls)
        print(f'OK  {p}')
"
```

## Regenerating from a fresh ingest + curation pass

Placeholder ids are random each run.

1. `uv run nmdc-ingest-ncbi PRJNA1071982` — deterministic pipeline. Produces JSON with all triad slots as sentinels.
2. Run the agent curation pass (interactive `/ncbi-to-nmdc PRJNA1071982` in `claude`, or programmatic equivalent like `scripts/apply_mfd_env_triad.py`) — resolves sentinels per the env-triad skill.
3. For each example file, re-extract the record matching its criterion via `jq` against the curated `results/ncbi_PRJNA1071982_nmdc.json`. The criteria are encoded in each row's term IDs in the tables above.
4. Update the `Source id` column above with the new ids.
5. Run the validation snippet.
6. Do not hand-edit record content — these are extracted-as-is examples.

## Adding a new example to this project

1. Identify the axis of variation it covers that isn't already represented.
2. Pick a representative from a pipeline output via `jq`.
3. Extract: `jq '.<collection>[] | select(.id=="<id>")' results/<output>.json > examples/microflora-danica/<collection>/NN_<short_label>.json` (next available number prefix).
4. Run the validation snippet.
5. Add a row to the matching table above.

For examples from a different project (new accession, new source), create a sibling project folder under `examples/` instead — see the top-level [`examples/README.md`](../README.md) for the convention.
