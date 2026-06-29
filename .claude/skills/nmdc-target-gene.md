---
name: nmdc-target-gene
description: Curate amplicon LibraryPreparation records the NCBI pipeline could not finish — write a description from the SRA DESIGN_DESCRIPTION (target + primers) for every amplicon library, and select a TargetGeneEnum target_gene value for single-gene amplicons while leaving whole-operon amplicons unset.
---

# Amplicon LibraryPreparation curation (description + target_gene)

The NCBI pipeline carries the SRA library descriptor verbatim but deliberately does
**not** parse the free-text `DESIGN_DESCRIPTION` — restating it as prose is a
natural-language task, not a regex job. Two slots are left for you, the running
agent, both read from the same `DESIGN_DESCRIPTION` and written to the same records:

1. **`description`** — set on **every** amplicon LibraryPreparation, restating what
   was amplified (target + primers). See *Set the description* below.
2. **`target_gene`** — the pipeline already committed it for designs naming **one
   explicit rRNA gene** (e.g. *"...amplify bacterial 16S rRNA genes"* → `16S_rRNA`);
   you resolve the rest, leaving whole-operon amplicons unset. See *How to decide
   target_gene* below.

The decisive distinction is **single gene vs. whole operon**:

- A design that targets **one rRNA gene** (the design text or primers name a single
  SSU or LSU gene) → commit that `TargetGeneEnum` value.
- A design that targets an **rRNA operon** → **leave `target_gene` unset.** An rRNA
  operon spans *two* genes (a bacterial operon covers 16S **and** 23S; a eukaryotic
  operon covers 18S **and** 28S), and `target_gene` is **single-valued** with no
  whole-operon permissible value. There is no honest single value, so the slot is
  omitted rather than reduced to one of the genes the operon happens to contain.
  Carry what was amplified in `LibraryPreparation.description` instead (the pipeline
  already writes e.g. *"Amplicon library preparation targeting bacterial rRNA operons
  using 8F and 2490R primers"* there) — do **not** invent a `target_gene`.

> This reflects [nmdc-schema #3238](https://github.com/microbiomedata/nmdc-schema/pull/3238):
> the MFD PacBio/Nanopore amplicons sequence the full 16S–ITS–23S (or 18S–ITS–28S)
> operon, which the schema cannot represent as a `target_gene`, so those records
> carry a `description` and **no** `target_gene`.

This is a **judgment task delegated to you, the running agent** — there is no
hardcoded mapping and no LLM API call in the pipeline. Use whatever model you are
running; the biology guidance below makes the decision reproducible across models.

Before committing (or deliberately omitting) any value, **read
`.claude/skills/nmdc-curation-rules.md`** — its evidence-first / omit-rather-than-guess
rules govern every commit here.

## Inputs

The pipeline writes the work-list to the curation-inputs sidecar
`results/ncbi_<ACCESSION>_nmdc_curation_inputs.json` under the `amplicon_curation`
key — **every** amplicon LibraryPreparation, grouped by **distinct
`DESIGN_DESCRIPTION`**:

```json
{
  "design_description": "amplicon sequencing using 3NDF and 21R to amplify eukaryotic rRNA operons",
  "example_library_name": "pb_eukoperon_MFD09597",
  "target_gene": null,
  "library_preparation_ids": ["nmdc:libprp-99-...", "..."],
  "count": 450
}
```

`target_gene` is the value the **pipeline** already set: a gene string (e.g.
`"16S_rRNA"`) means it is resolved — leave it as-is and only add the description;
`null` means you must decide it (and, for an operon, deliberately leave it unset).

Work **once per design** (not per library): derive the description (always) and the
target_gene (when `null`), then apply both to every `library_preparation_ids` entry
for that design.

## Set the description

Set `LibraryPreparation.description` on **every** amplicon library in the work-list.
Read the two facts out of the `design_description` free text — there is no fixed
format across BioProjects, so read for meaning rather than matching a pattern:

- **target** — what the design says it amplifies, e.g. *"bacterial rRNA operons"*,
  *"bacterial 16S rRNA genes"*, *"eukaryotic rRNA operons"*.
- **primers** — the primer pair named in the design, e.g. *"8F and 2490R"*,
  *"8F and 1391R"*, *"3NDF and 21R"*.

MFD designs follow the shape *"amplicon sequencing using **\<primers\>** to amplify
**\<target\>**"* (see `mfd-project-vocabulary.md`), but other projects phrase it
differently — extract the same two facts however the design is worded. If a design
genuinely names no target or no primers, omit `description` rather than inventing
text (omit-rather-than-guess).

Then write the description in this fixed template so phrasing is consistent:

> `Amplicon library preparation targeting <target> using <primers> primers`

Worked examples (the three MFD designs):

| `design_description` | `description` |
|---|---|
| amplicon sequencing using 8F and 1391R to amplify bacterial 16S rRNA genes | Amplicon library preparation targeting bacterial 16S rRNA genes using 8F and 1391R primers |
| amplicon sequencing using 8F and 2490R to amplify bacterial rRNA operons | Amplicon library preparation targeting bacterial rRNA operons using 8F and 2490R primers |
| amplicon sequencing using 3NDF and 21R to amplify eukaryotic rRNA operons | Amplicon library preparation targeting eukaryotic rRNA operons using 3NDF and 21R primers |

## How to decide target_gene

For each design, weigh three pieces of evidence — the design text, the primer
names, and the library name:

1. **Operon vs. gene is the first question.** If the design text says *"rRNA
   operon(s)"*, or the library name encodes an operon (`pb_bacoperon_*`,
   `pb_eukoperon_*`), or the primers span both subunits (a forward SSU primer paired
   with a reverse primer that reads into the LSU — e.g. `8F`/`2490R`, where `2490R`
   reads into the 23S), then the amplicon is a **whole operon → leave `target_gene`
   unset.** Stop here; do not pick a gene.
2. **Single-gene amplicons select one `TargetGeneEnum` value.** Only when the design
   targets a *single* rRNA gene, pick a permissible value of
   [`TargetGeneEnum`](https://microbiomedata.github.io/nmdc-schema/TargetGeneEnum/)
   (`16S_rRNA`, `18S_rRNA`, `23S_rRNA`, `28S_rRNA`):
   - **Domain** narrows the choice to a pair and rules out the other domain's pair:
     prokaryotic (bacterial/archaeal) → `16S_rRNA` (SSU) or `23S_rRNA` (LSU);
     eukaryotic → `18S_rRNA` (SSU) or `28S_rRNA` (LSU).
   - **Primer names** select within the pair — e.g. `8F`/`1391R` and `8F`/`27F` are
     bacterial 16S (SSU) primers → `16S_rRNA`; `3NDF`/`21R` anchor the eukaryotic 18S
     → `18S_rRNA`. If you are unsure of a primer, check a primer database / the
     literature rather than guessing.
   - **Library name** corroborates the domain: `npumi_16SrRNA_*` names the gene
     outright (`16S_rRNA`).

**When the evidence does not resolve to exactly one gene — most importantly any
whole-operon amplicon — leave it unset** (omit-rather-than-guess). Do **not** assert
`16S_rRNA`/`18S_rRNA`/`23S_rRNA`/`28S_rRNA` for an operon just because the operon
contains that gene.

### MFD expected outcome

For PRJNA1071982 the two operon designs are left **unset**: the bacterial operon
(`8F`/`2490R`, "bacterial rRNA operons") and the eukaryotic operon (`3NDF`/`21R`,
"eukaryotic rRNA operons"). Both get a `description` (naming target + primers) and
**no `target_gene`**. Single-gene amplicons (e.g. an `npumi_16SrRNA_*` design naming
"bacterial 16S rRNA genes") arrive with `target_gene` already set by the pipeline —
leave it and just add the description.

## Patch the output

Patch the generated `results/ncbi_<ACCESSION>_nmdc.json` programmatically, keyed on
each design's `library_preparation_ids` — do not hand-edit hundreds of records. Per
design:

- **`description`** — set it on every listed LibraryPreparation (always).
- **`target_gene`** — if the sidecar row's `target_gene` is already a gene string,
  leave the record's value as-is. If it is `null`, set a `TargetGeneEnum` value for a
  single-gene design, or **leave it absent** for an operon (the `description` carries
  the target).

Re-validate the file against the schema afterward (see `ncbi-to-nmdc.md` § Step 6),
then note in the run report, per design, the description set and whether `target_gene`
was set (and to what) or deliberately omitted (operon), with counts.
