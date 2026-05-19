"""Extract ObservedTerm records from an nmdc.Database for term validation.

The output dict conforms to the local TermValidationSet schema in
term_validation.yaml and is fed straight into linkml-term-validator.
"""

from __future__ import annotations

from typing import Iterable

from nmdc_schema import nmdc

# Slots whose value is a ControlledIdentifiedTermValue and whose term should be
# validated. env_package is a TextValue today; samp_taxon_id carries NCBITaxon
# CURIEs but Phase 1's oak_config configures ENVO only, so NCBITaxon terms
# appear in the report and get skipped at validation time.
_BIOSAMPLE_TERM_SLOTS = (
    "env_broad_scale",
    "env_local_scale",
    "env_medium",
    "samp_taxon_id",
)

# Sentinel CURIE that translate._parse_envo_term emits when no ENVO term could
# be resolved. Skip these so the validator does not produce noisy
# "term not found" errors for data already flagged for human curation.
_SENTINEL_CURIES = {"ENVO:00000000"}


def extract_observed_terms(database: nmdc.Database) -> dict:
    """Walk biosample_set and emit one ObservedTerm per ontology-bearing slot.

    Returns a dict ready to serialize as the validator's input data file.
    """
    return {"observed_terms": list(_iter_observed_terms(database))}


def _iter_observed_terms(database: nmdc.Database) -> Iterable[dict]:
    for biosample in database.biosample_set or []:
        for slot in _BIOSAMPLE_TERM_SLOTS:
            record = _observed_term_for_slot(biosample, slot)
            if record is not None:
                yield record


def _observed_term_for_slot(biosample: nmdc.Biosample, slot: str) -> dict | None:
    value = getattr(biosample, slot, None)
    if value is None:
        return None

    term = getattr(value, "term", None)
    if term is None:
        return None

    term_id = getattr(term, "id", None)
    if not term_id or term_id in _SENTINEL_CURIES:
        return None

    return {
        "id": f"{biosample.id}:{slot}",
        "sample_id": biosample.id,
        "slot": slot,
        "raw_value": getattr(value, "has_raw_value", "") or "",
        "term": {
            "id": term_id,
            "label": getattr(term, "name", "") or "",
        },
    }
