---
name: nmdc-taxon-resolution
description: "Use this skill to resolve organism names to NCBITaxon CURIEs via runoak for samp_taxon, host_taxid, and host_name, applying NMDC's unambiguous-intent rule for host assignment. Trigger when a host or taxon slot is unset or holds free-text needing lifting to a CURIE. Do not infer a host from rhizosphere or host-associated context alone; leave it unset and flag for PI follow-up."
---

# NCBITaxon resolution for NMDC

Resolve organism names to NCBITaxon CURIEs for `samp_taxon`, `host_taxid`, and related slots. Source skills hand off here when the deterministic pipeline has either left a host slot unset or recorded a free-text organism string that needs lifting to a CURIE.

Before committing any value, **read `nmdc-curation-rules`** — its evidence-first / no-tautology / omit-rather-than-guess rules govern every commit you make in this skill. The host-disambiguation rule below is a slot-specific application of those general rules.

## Runoak setup

See **Runoak setup** in `nmdc-env-triad` — the same `uv sync --extra ontology` install and the same `runoak` invocation pattern apply here. Use the `sqlite:obo:ncbitaxon` adapter (or `ols:ncbitaxon` for the live API).

## Lookup pattern

```bash
# Fuzzy search for a scientific name
uv run --extra ontology runoak -i sqlite:obo:ncbitaxon search "Phallus rugulosus"

# Confirm a known taxid
uv run --extra ontology runoak -i sqlite:obo:ncbitaxon info NCBITaxon:5260
```

For each organism string to resolve:
1. Search by scientific name. Prefer exact matches over fuzzy hits.
2. Verify the hit with `info` — check the label and rank match the source's intent.
3. Record the `NCBITaxon:<id>` CURIE and the official label.

## Host disambiguation rule

Only set `host_name` / `host_taxid` when the submitter's intent is unambiguous. A BioProject title that names a host species, a BioSample with an explicit `host` attribute, or a study description that calls out a single host taxon all qualify.

Do **not** infer a host from rhizosphere or host-associated context alone (e.g. "tree-associated soil samples" does not justify guessing the tree species). When intent is ambiguous, leave the host slots unset and flag for PI follow-up in the source skill's run report — this is the omit-rather-than-guess rule (`nmdc-curation-rules` Rule 4) applied to host fields.

## Slot value shape

Taxon slots typically range over `ControlledIdentifiedTermValue`, which wraps an `OntologyClass` (`id`: NCBITaxon CURIE, `name`: official label). When the submitter only supplied free text and no taxid resolves cleanly, use `ControlledTermValue` with `has_raw_value`. See `nmdc-schema-reference` for the full trap-and-shape reference.
