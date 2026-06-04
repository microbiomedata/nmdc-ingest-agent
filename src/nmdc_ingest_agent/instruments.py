"""Resolve instrument-model strings to existing NMDC Instrument IDs.

External sources (NCBI SRA, GOLD, ...) record a free-text sequencer/MS model
string per run (e.g. ``"Illumina NovaSeq 6000"``). NMDC models instruments as
first-class records in the ``instrument_set`` collection, each carrying a
stable ``nmdc:inst-...`` id, a human ``name``, and a ``model`` that is a key of
the schema's ``InstrumentModelEnum``. DataGeneration records reference an
instrument by that id on ``instrument_used`` — so ingest must point at an
*existing* Instrument rather than minting a new one per source string.

Resolution tries, in order:

1. Exact (case-insensitive) match against an instrument ``name``.
2. Match against the ``aliases`` declared on an ``InstrumentModelEnum``
   permissible value, then look up the instrument whose ``model`` equals that
   enum key.

Unresolved strings return ``None`` so the caller can leave ``instrument_used``
empty and flag the gap for curation rather than inventing an id.
"""

from __future__ import annotations

import json
import os
from typing import Optional

import requests

# nmdcschema query endpoint per runtime environment, mirroring the env
# selection used by :mod:`nmdc_ingest_agent.minting`.
_API_BASE_BY_ENV: dict[str, str] = {
    "prod": "https://api.microbiomedata.org",
    "dev": "https://api-dev.microbiomedata.org",
}

_PAGE_SIZE = 200


def _api_base(env: str) -> str:
    try:
        return _API_BASE_BY_ENV[env]
    except KeyError as exc:
        raise ValueError(
            f"Unknown NMDC runtime env {env!r}; expected one of "
            f"{sorted(_API_BASE_BY_ENV)}"
        ) from exc


def fetch_instrument_set(env: str = "dev") -> list[dict]:
    """Return every record in the NMDC ``instrument_set`` collection.

    Pages through the runtime ``/nmdcschema/instrument_set`` endpoint until no
    ``next_page_token`` is returned. The collection is small (tens of records),
    so this is a couple of requests at most.
    """
    url = f"{_api_base(env)}/nmdcschema/instrument_set"
    resources: list[dict] = []
    page_token: Optional[str] = None
    while True:
        params: dict = {"max_page_size": _PAGE_SIZE}
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(
            url, params=params, headers={"accept": "application/json"}, timeout=60
        )
        resp.raise_for_status()
        body = resp.json()
        resources.extend(body.get("resources", []))
        page_token = body.get("next_page_token")
        if not page_token:
            break
    return resources


def load_instrument_model_aliases() -> dict[str, str]:
    """Map each ``InstrumentModelEnum`` alias (lowercased) to its enum key.

    Read from the materialized schema shipped with the installed
    ``nmdc_schema`` package, so the alias set always matches the schema version
    this ingest is pinned to.
    """
    import nmdc_schema

    path = os.path.join(
        os.path.dirname(nmdc_schema.__file__), "nmdc_materialized_patterns.json"
    )
    with open(path) as f:
        schema = json.load(f)

    pvs = schema["enums"]["InstrumentModelEnum"]["permissible_values"]
    index: dict[str, str] = {}
    for key, pv in pvs.items():
        for alias in pv.get("aliases") or []:
            normalized = alias.strip().lower()
            if normalized:
                # First enum key wins; aliases are expected to be unique, but
                # guard against an accidental collision rather than silently
                # remapping.
                index.setdefault(normalized, key)
    return index


class InstrumentResolver:
    """Look up existing NMDC Instrument IDs for source model strings."""

    def __init__(self, instruments: list[dict], alias_to_model: dict[str, str]) -> None:
        self._name_to_id: dict[str, str] = {}
        self._model_to_id: dict[str, str] = {}
        for inst in instruments:
            inst_id = inst.get("id")
            if not inst_id:
                continue
            name = (inst.get("name") or "").strip().lower()
            if name:
                self._name_to_id.setdefault(name, inst_id)
            model = (inst.get("model") or "").strip()
            if model:
                self._model_to_id.setdefault(model, inst_id)
        self._alias_to_model = alias_to_model

    def resolve(self, source_model: Optional[str]) -> Optional[str]:
        """Return the NMDC Instrument id for ``source_model``, or ``None``.

        ``None`` means neither an instrument ``name`` nor any enum alias matched
        a known instrument — the caller should leave ``instrument_used`` empty.
        """
        if not source_model:
            return None
        key = source_model.strip().lower()
        if not key:
            return None

        # 1. Exact instrument-name match.
        name_hit = self._name_to_id.get(key)
        if name_hit:
            return name_hit

        # 2. Alias -> enum model key -> instrument with that model.
        model = self._alias_to_model.get(key)
        if model:
            return self._model_to_id.get(model)

        return None

    @classmethod
    def from_api(cls, env: str = "dev") -> "InstrumentResolver":
        """Build a resolver from the live ``instrument_set`` and the schema's
        ``InstrumentModelEnum`` aliases."""
        return cls(fetch_instrument_set(env), load_instrument_model_aliases())
