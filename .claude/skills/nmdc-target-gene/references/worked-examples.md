# Worked examples (MicroFlora Danica)

Concrete `design_description` → `description` mappings and the expected `target_gene`
outcome for the three MFD amplicon designs (PRJNA1071982). These illustrate the general
decision logic in `SKILL.md`; other BioProjects phrase their designs differently, so read
for meaning rather than matching these strings.

## `description` from `design_description`

| `design_description` | `description` |
|---|---|
| amplicon sequencing using 8F and 1391R to amplify bacterial 16S rRNA genes | Amplicon library preparation targeting bacterial 16S rRNA genes using 8F and 1391R primers |
| amplicon sequencing using 8F and 2490R to amplify bacterial rRNA operons | Amplicon library preparation targeting bacterial rRNA operons using 8F and 2490R primers |
| amplicon sequencing using 3NDF and 21R to amplify eukaryotic rRNA operons | Amplicon library preparation targeting eukaryotic rRNA operons using 3NDF and 21R primers |

## `target_gene` expected outcome

For PRJNA1071982 the two operon designs are left **unset**: the bacterial operon
(`8F`/`2490R`, "bacterial rRNA operons") and the eukaryotic operon (`3NDF`/`21R`,
"eukaryotic rRNA operons"). Both get a `description` (naming target + primers) and
**no `target_gene`**. Single-gene amplicons (e.g. an `npumi_16SrRNA_*` design naming
"bacterial 16S rRNA genes") arrive with `target_gene` already set by the pipeline —
leave it and just add the description.
