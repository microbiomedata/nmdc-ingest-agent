# Decisions for next run

Human-authored. The ingest skill reads this at Step 0; the agent never overwrites it.

- MFD env-triad is resolved deterministically from the v2 MFDO crosswalk — do not re-curate those slots by hand.
- Keep the two rRNA-operon amplicon designs' `target_gene` **unset** (operons span two genes); only the single-gene 16S design carries a `target_gene`.
- (add further directives here, e.g. "exclude project P17", "commit env_medium ENVO:00001998 for soil-package samples")
