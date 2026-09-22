"""Ontology-term QC over an NMDC ``Database`` via ``linkml-term-validator``.

The NMDC LinkML schema validates the *shape* of an ontology-bearing slot
(``ControlledIdentifiedTermValue`` wrapping an ``OntologyClass`` with ``id`` +
``name``) but says nothing about whether the CURIE exists, whether the label
is the ontology's canonical label, or whether the term sits in the right
part of ENVO for its MIxS slot. This package closes that gap, layered per
microbiomedata/nmdc-ingest-agent#8:

======  =================================================  =========  ==============
level   check                                              severity   report flag
======  =================================================  =========  ==============
1       CURIE exists in the configured ontology            error      ``info_ok``
1       CURIE is not obsolete                              error      ``info_ok``
2       committed label == ontology label (normalized)     error      ``label_ok``
3       env_broad_scale is a biome; env_medium is an       warning    ``anchor_ok``
        environmental material; env_local_scale is NOT a
        biome
4       term is in the NMDC submission-schema value set    warning    ``valueset_ok``
        for the sample's inferred MIxS package interface
======  =================================================  =========  ==============

Levels 1-3 run through ``linkml-term-validator``'s ``BindingValidationPlugin``
against a small local *projection* schema (``term_validation.yaml``) rather than
the NMDC schema itself, because nmdc-schema does not (yet) mark
``OntologyClass.name`` as ``rdfs:label`` nor bind the env-triad slots to
anchor enums. Level 4 is a plain set-membership check against value sets
vendored from ``nmdc-submission-schema`` (``env_triad_valuesets.tsv``).

Entry points:

* :func:`nmdc_ingest_agent.validators.extract.extract_observed_terms` —
  ``nmdc.Database`` → projection instance.
* :func:`nmdc_ingest_agent.validators.run.run_term_validation` — projection →
  report dict (never raises; degrades to ``status`` = ``skipped`` /
  ``unavailable`` / ``error``).
* :func:`nmdc_ingest_agent.validators.run.merge_into_curation_report` — fold
  per-term flags into the curation report's per-row ``validator`` dict.
* ``nmdc-ingest-validate-terms`` console script (:mod:`.cli`) for re-running
  against an existing deliverable, e.g. after the curation skills commit terms.
"""
