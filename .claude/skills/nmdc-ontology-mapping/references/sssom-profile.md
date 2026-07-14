# SSSOM profile for NMDC mappings

[SSSOM](https://mapping-commons.github.io/sssom/) (Simple Standard for Sharing Ontological
Mappings) is the OBO/Monarch mapping standard: a LinkML-schema'd TSV with a validator
(`sssom validate | parse | convert`), already installed via the `ontology` extra. Prefer it
over any bespoke column layout — it gives you standard slot names, a mapping *predicate*, and
schema validation for free.

## File shape

A `#`-commented YAML metadata header (prefixes + set metadata), then the mapping table:

```
# curie_map:
#   ENVO: http://purl.obolibrary.org/obo/ENVO_
#   skos: http://www.w3.org/2004/02/skos/core#
#   semapv: https://w3id.org/semapv/vocab/
#   CORINE: https://w3id.org/nmdc/vocab/corine/
# mapping_set_id: https://w3id.org/nmdc/mappings/<name>
# license: https://creativecommons.org/publicdomain/zero/1.0/
subject_id  subject_label  predicate_id  object_id  object_label  mapping_justification  ...
```

Every prefix used by any id (subject, object, predicate, justification, author) must be
declared in `curie_map`, or the set fails to parse. Start from
[`../assets/mapping_set_template.sssom.tsv`](../assets/mapping_set_template.sssom.tsv).

## Columns

| Column | Meaning |
|---|---|
| `subject_id` | source-vocabulary term id (a real CURIE, or a minted local prefix for a derived Regime-B vocabulary) |
| `subject_label` | source term's human label |
| `predicate_id` | the mapping relationship: `skos:exactMatch` / `broadMatch` / `narrowMatch` / `closeMatch` / `relatedMatch` |
| `object_id` | the NMDC target CURIE (ENVO / NCBITaxon), from a `runoak` lookup this run |
| `object_label` | the target's **official** ontology label (from `runoak info`), not the source label |
| `mapping_justification` | a `semapv:` value — `ManualMappingCuration`, `LexicalMatching`, `CompositeMatching`, … |
| `confidence` | 0–1 float |
| `subject_source` / `object_source` | e.g. `CORINE` / `ENVO` |
| `author_id` | `orcid:…` for a human, or an agent id |
| `mapping_date` | ISO `YYYY-MM-DD` |
| `comment` | free text |

`object_id` + `object_label` together are the hallucination guard (Chris Mungall's
id+label rule): `validate_mapping_set.py` rejects a row whose stated label disagrees with the
ontology's official label, or whose id does not resolve.

## Picking `predicate_id`

Do not default everything to `exactMatch`. A coarse source class mapping to a more specific
ENVO term (or vice-versa) is a `broadMatch` / `narrowMatch`. Example: CORINE `111 Continuous
urban fabric` → `ENVO:00000062 populated place` is a `skos:broadMatch`. Getting this right is
the main thing a flat "source → target" table throws away.

## Anchor classes per env-triad slot

Pass the slot's anchor to `validate_mapping_set.py --anchor` so every mapped ENVO term is
verified to sit in the right subtree:

| Target slot | Anchor class | `--anchor` |
|---|---|---|
| `env_broad_scale` | biome | `ENVO:00000428` |
| `env_local_scale` | astronomical body part / environmental features | `ENVO:01000813` (plus `ENVO:01001209 ENVO:01001790 ENVO:01000408 ENVO:01000355` roots) |
| `env_medium` | environmental material | `ENVO:00010483` |

## Existing land-cover maps (legacy format — conversion is a follow-up)

`data/land-cover/corine_envo_map.tsv` and `worldcover_envo_map.tsv` predate this profile and
use a simpler layout (`<vocab>_code`, `<vocab>_label`, `env_local_scale` as a `label [CURIE]`
cell, `ols_verified`, `notes`). They are still read in that form by the MFD build tool
`apply_crosswalk.py`, so converting them to SSSOM is a **coordinated follow-up** (update the
maps and the parser together, then re-verify the MFD crosswalk rebuild) — not done here to
keep this refactor from touching MFD pipeline output. New mapping sets should be authored as
SSSOM from the start.
