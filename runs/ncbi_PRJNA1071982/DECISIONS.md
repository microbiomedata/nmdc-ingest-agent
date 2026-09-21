# Decisions for next run

Human-authored. The ingest skill reads this at Step 0; the agent never overwrites it.

- MFD env-triad is resolved deterministically from the v2 MFDO crosswalk. **Run Step 2 with** `--env-triad-crosswalk examples/microflora-danica/crosswalk/mfd_biosamples_annotated.tsv`. Do not hand-curate or build a new mapping for those slots — reuse the crosswalk.
- Keep the two rRNA-operon amplicon designs' `target_gene` **unset** (operons span two genes); only the single-gene 16S design carries a `target_gene`.
- (add further directives here, e.g. "exclude project P17", "commit env_medium ENVO:00001998 for soil-package samples")
