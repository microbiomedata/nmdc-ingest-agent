---
name: nmdc-target-gene
description: Resolve LibraryPreparation.target_gene for amplicon libraries the NCBI pipeline left unset, by reasoning over the SRA DESIGN_DESCRIPTION + primer names to select a TargetGeneEnum permissible value.
---

# target_gene resolution for amplicon libraries

The NCBI pipeline only commits `LibraryPreparation.target_gene` when the SRA
`DESIGN_DESCRIPTION` names **one explicit rRNA gene** (e.g. *"...amplify bacterial
16S rRNA genes"* → `16S_rRNA`). Anything that needs inference — most importantly
an **"rRNA operon"** amplicon — is deliberately left unset for this skill, because
a fixed rule cannot do it correctly: a bacterial rRNA operon spans **both 16S and
23S**, and the right value depends on the primers and the organismal domain.

This is a **judgment task delegated to you, the running agent** — there is no
hardcoded mapping and no LLM API call in the pipeline. Use whatever model you are
running; the biology guidance below makes the decision reproducible across models.

Before committing any value, **read `.claude/skills/nmdc-curation-rules.md`** —
its evidence-first / omit-rather-than-guess rules govern every commit here.

## Inputs

The pipeline writes the work-list to the curation-inputs sidecar
`results/ncbi_<ACCESSION>_nmdc_curation_inputs.json` under the
`target_gene_curation` key — a list grouped by **distinct `DESIGN_DESCRIPTION`**:

```json
{
  "design_description": "amplicon sequencing using 3NDF and 21R to amplify eukaryotic rRNA operons",
  "example_library_name": "pb_eukoperon_MFD09597",
  "library_preparation_ids": ["nmdc:libprp-99-...", "..."],
  "count": 450
}
```

Resolve **once per design** (not per library), then apply the result to every
`library_preparation_ids` entry for that design.

## How to decide target_gene

For each design, weigh three pieces of evidence — the design text, the primer
names, and the library name — and select a permissible value of
[`TargetGeneEnum`](https://microbiomedata.github.io/nmdc-schema/TargetGeneEnum/)
(`16S_rRNA`, `18S_rRNA`, `23S_rRNA`, `28S_rRNA`):

1. **Domain excludes the other domain's rRNA genes.** A *prokaryotic*
   (bacterial/archaeal) target is one of `16S_rRNA` (SSU) or `23S_rRNA` (LSU); a
   *eukaryotic* target is one of `18S_rRNA` (SSU) or `28S_rRNA` (LSU). So the
   domain narrows the choice to a pair and **rules out the other domain's pair** —
   it does not by itself pick SSU vs LSU (a whole "rRNA operon" spans both).
2. **Primer names select within the pair.** The forward primer's binding region
   picks SSU vs LSU — e.g. `8F`/`1391R` and `8F`/`27F` are bacterial 16S (SSU)
   primers → `16S_rRNA`; `3NDF`/`21R` (a.k.a. NS-style euk primers) anchor the
   eukaryotic 18S → `18S_rRNA`; `2490R` reads into the 23S/28S large subunit. If
   you are unsure of a primer, check a primer database / the literature rather
   than guessing.
3. **Library name corroborates the domain (as an exclusion).** MFD encodes it:
   `npumi_16SrRNA_*` names the gene outright (`16S_rRNA`); `pb_bacoperon_*` is a
   *bacterial* operon (spans 16S **and** 23S) → **excludes** `18S_rRNA` and
   `28S_rRNA`; `pb_eukoperon_*` is a *eukaryotic* operon (spans 18S **and** 28S) →
   **excludes** `16S_rRNA` and `23S_rRNA`. Combine with the primer evidence
   (item 2) — the SSU forward primer then selects the small subunit (`16S`/`18S`)
   within the remaining pair.

**When the evidence genuinely does not resolve to one SSU gene, leave it unset**
(omit-rather-than-guess). Do not assert `23S_rRNA`/`28S_rRNA` for a whole-operon
amplicon just because the operon contains them — report the gene the amplicon is
*named/primed for* (the SSU), or nothing.

### MFD expected outcome

For PRJNA1071982 the two unresolved designs are the bacterial operon
(`8F`/`2490R`, "bacterial rRNA operons") → **`16S_rRNA`** and the eukaryotic operon
(`3NDF`/`21R`, "eukaryotic rRNA operons") → **`18S_rRNA`** — so the final library
counts are 862 × `16S_rRNA`, 450 × `18S_rRNA`, the rest (WGS) unset.

## Patch the output

For each resolved design, set `target_gene` (a `TargetGeneEnum` value, e.g.
`"16S_rRNA"`) on every listed LibraryPreparation in the generated
`results/ncbi_<ACCESSION>_nmdc.json`. Patch programmatically keyed on the
`library_preparation_ids` — do not hand-edit hundreds of records. Re-validate the
file against the schema afterward (see `ncbi-to-nmdc.md` § Step 6), then note the
per-gene counts in the run report.
