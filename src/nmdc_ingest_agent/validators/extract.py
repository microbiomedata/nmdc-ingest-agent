"""Project an ``nmdc.Database`` onto the term-validation schema.

One :class:`ObservedTerm` record is emitted per (Biosample, ontology-bearing
slot) whose value is a ``ControlledIdentifiedTermValue`` carrying a real
CURIE. Records are grouped under the root slot named after the NMDC slot, so
``term_validation.yaml`` can bind each group to its own anchor enum.

The pipeline's refuse sentinel ``ENVO:00000000`` is skipped. Note that this
CURIE is a *real* ENVO class ("geographic feature"): the validator cannot tell
the sentinel from a genuine commit, so exclusion is by convention here and the
count of skipped sentinels is surfaced in the report instead.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

# Biosample slots ranged over ControlledIdentifiedTermValue whose term we QC.
# Order matters only for report readability. Each name must also be a root
# slot of TermValidationSet in term_validation.yaml.
BIOSAMPLE_TERM_SLOTS: tuple[str, ...] = (
    "env_broad_scale",
    "env_local_scale",
    "env_medium",
    "samp_taxon_id",
    "host_taxid",
)

# Deterministic-pipeline refuse sentinel (see translate._parse_envo_term).
SENTINEL_CURIES: frozenset[str] = frozenset({"ENVO:00000000"})


def _get(obj: Any, name: str) -> Any:
    """Attribute-or-key access so both nmdc dataclasses and plain dicts work."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def observed_term_for_slot(biosample: Any, slot: str) -> Optional[dict]:
    """Build one ObservedTerm dict for ``biosample.<slot>``, or None if the slot
    is unset, carries no CURIE, or holds the refuse sentinel."""
    value = _get(biosample, slot)
    if value is None:
        return None
    term = _get(value, "term")
    if term is None:
        return None
    term_id = _get(term, "id")
    if not term_id or term_id in SENTINEL_CURIES:
        return None

    env_package = _get(biosample, "env_package")
    package_raw = _get(env_package, "has_raw_value") if env_package is not None else None

    return {
        "id": f"{_get(biosample, 'id')}:{slot}",
        "biosample_id": _get(biosample, "id"),
        "slot": slot,
        "raw_value": _get(value, "has_raw_value") or "",
        "env_package": package_raw or "",
        "term": {
            "id": str(term_id),
            "label": _get(term, "name") or "",
        },
    }


def _iter_biosamples(database: Any) -> Iterable[Any]:
    biosamples = _get(database, "biosample_set") or []
    return biosamples


def extract_observed_terms(database: Any, slots: Iterable[str] = BIOSAMPLE_TERM_SLOTS) -> dict:
    """Walk ``biosample_set`` and return the TermValidationSet instance.

    Accepts an ``nmdc.Database`` object or the equivalent JSON dict. Returns
    ``{"<slot>": [ObservedTerm, ...], ...}`` (only non-empty slots) plus a
    ``_skipped_sentinels`` count under the ``_meta`` key, which run.py strips
    before validation.
    """
    slots = tuple(slots)
    grouped: dict[str, list[dict]] = {slot: [] for slot in slots}
    skipped_sentinels = 0
    for biosample in _iter_biosamples(database):
        for slot in slots:
            value = _get(biosample, slot)
            term = _get(value, "term") if value is not None else None
            if term is not None and _get(term, "id") in SENTINEL_CURIES:
                skipped_sentinels += 1
                continue
            record = observed_term_for_slot(biosample, slot)
            if record is not None:
                grouped[slot].append(record)
    instance = {slot: rows for slot, rows in grouped.items() if rows}
    instance["_meta"] = {"skipped_sentinels": skipped_sentinels}
    return instance


def iter_terms(instance: dict) -> Iterable[tuple[str, int, dict]]:
    """Yield ``(slot, index, record)`` for every ObservedTerm in a projection."""
    for slot, rows in instance.items():
        if slot.startswith("_"):
            continue
        for index, record in enumerate(rows):
            yield slot, index, record
