# Reference patterns for NMDC object construction

The traditional Dagster-orchestrated translators in [microbiomedata/nmdc-runtime](https://github.com/microbiomedata/nmdc-runtime) are a useful reference for NMDC object construction:

- `nmdc_runtime/site/translation/translator.py` — base Translator class
- `nmdc_runtime/site/translation/gold_translator.py` — Study/Biosample/DataGeneration patterns
- `nmdc_runtime/site/translation/neon_utils.py` — helper functions for NMDC value types
- `nmdc_runtime/site/translation/neon_soil_translator.py` — the `_translate_library_preparation` and `_translate_processed_sample` helpers are a reference for the `Biosample → LibraryPreparation → ProcessedSample → NucleotideSequencing` wiring (see `build_library_records` in `translate.py`).

Ignore the `Extraction` and `Pooling` patterns from `neon_soil_translator.py` — NCBI supports neither, so the `LibraryPreparation` consumes the `Biosample` directly rather than an extracted-nucleic-acid or pooling `ProcessedSample`.
