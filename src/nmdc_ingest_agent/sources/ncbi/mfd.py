"""Resolve MicroFlora Danica (MFD) env-triad slots from the v2 MFDO crosswalk.

MFD biosamples (BioProject PRJNA1071982) carry no usable MIxS env-triad values
in NCBI — the submitter encoded habitat only in a coarse ``isolation_source``
string (e.g. ``"Soil from Natural Forests"``). The richer mapping lives in the
v2 crosswalk at ``data/mfdo-crosswalk-v2/``, whose per-biosample deliverable
``mfd_biosamples_annotated.tsv`` is keyed by ``fieldsample_barcode`` (e.g.
``MFD00001``) — the same identifier NCBI exposes as ``sample_name`` and the
``MFDID`` attribute. Each triad cell holds a combined ``"<label> [<CURIE>]"``
string (e.g. ``"temperate broadleaf forest biome [ENVO:01000202]"``) that
already reflects the full 5-level MFD habitat hierarchy plus GEE land-cover
refinement — detail absent from ``isolation_source``.

This resolver loads that file into a barcode → {slot: (curie, label)} index and
hands the deterministic env-triad values to the NCBI translator, which commits
them at build time (curation report ``outcome="resolved_at_pipeline"``). Samples
without a matching barcode resolve to ``None`` so the translator keeps its
ordinary ``ENVO:00000000`` sentinel path.
"""

from __future__ import annotations

import csv
import os
import re
from pathlib import Path
from typing import Optional

from nmdc_schema import nmdc

# Triad slots, in the order the annotated TSV and the NMDC Biosample expose them.
_TRIAD_SLOTS = ("env_broad_scale", "env_local_scale", "env_medium")

_FIELDSAMPLE_COL = "fieldsample_barcode"

# MFD field-sample barcodes look like ``MFD00001``.
_MFD_BARCODE_RE = re.compile(r"^MFD\d+$", re.IGNORECASE)

# A combined cell: ``temperate broadleaf forest biome [ENVO:01000202]`` ->
# label ``temperate broadleaf forest biome``, CURIE ``ENVO:01000202``.
_COMBINED_RE = re.compile(r"^(?P<label>.*?)\s*\[(?P<curie>[A-Za-z]+:\d+)\]\s*$")

# Repo-relative default. This module is
# ``src/nmdc_ingest_agent/sources/ncbi/mfd.py`` and the data dir is not packaged
# in the wheel, so walk up to the repo root rather than the install dir.
#   parents[0]=ncbi parents[1]=sources parents[2]=nmdc_ingest_agent
#   parents[3]=src  parents[4]=<repo root>
_DEFAULT_TSV = (
    Path(__file__).resolve().parents[4]
    / "data"
    / "mfdo-crosswalk-v2"
    / "mfd_biosamples_annotated.tsv"
)


def _parse_combined(value: str) -> Optional[tuple[str, str]]:
    """Split ``"<label> [<CURIE>]"`` into ``(curie, label)``.

    Returns ``None`` for empty or malformed cells so the caller can skip that
    slot (leaving its sentinel) rather than committing a bad term.
    """
    match = _COMBINED_RE.match((value or "").strip())
    if not match:
        return None
    return match.group("curie"), match.group("label").strip()


class MfdEnvTriadResolver:
    """Look up v2-crosswalk env-triad terms for an MFD biosample by barcode."""

    def __init__(self, by_barcode: dict[str, dict[str, tuple[str, str]]]) -> None:
        # barcode -> {slot: (curie, label)}; only slots whose cell parsed are kept.
        self._by_barcode = by_barcode

    @classmethod
    def from_tsv(cls, path: Optional[Path] = None) -> Optional["MfdEnvTriadResolver"]:
        """Build a resolver from ``mfd_biosamples_annotated.tsv``.

        Path precedence: explicit ``path`` > ``NMDC_MFD_CROSSWALK_TSV`` env var >
        the repo-relative default. Returns ``None`` when the file is absent, so
        non-MFD BioProjects and environments without the data dir (e.g. CI)
        run unchanged.
        """
        if path is None:
            override = os.environ.get("NMDC_MFD_CROSSWALK_TSV", "").strip()
            path = Path(override) if override else _DEFAULT_TSV
        if not path.exists():
            return None

        by_barcode: dict[str, dict[str, tuple[str, str]]] = {}
        with open(path, newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                barcode = (row.get(_FIELDSAMPLE_COL) or "").strip().upper()
                if not barcode:
                    continue
                slots: dict[str, tuple[str, str]] = {}
                for slot in _TRIAD_SLOTS:
                    parsed = _parse_combined(row.get(slot, ""))
                    if parsed:
                        slots[slot] = parsed
                if slots:
                    by_barcode[barcode] = slots
        return cls(by_barcode)

    @staticmethod
    def _barcode_for(sample_data: dict) -> Optional[str]:
        """Derive the MFD barcode for a raw NCBI biosample record, or ``None``."""
        name = (sample_data.get("sample_name") or "").strip()
        if _MFD_BARCODE_RE.match(name):
            return name.upper()
        mfdid = (sample_data.get("attributes", {}).get("MFDID") or "").strip()
        if _MFD_BARCODE_RE.match(mfdid):
            return mfdid.upper()
        return None

    def resolve(
        self, sample_data: dict
    ) -> Optional[dict[str, nmdc.ControlledIdentifiedTermValue]]:
        """Return ``{slot: ControlledIdentifiedTermValue}`` for a matched MFD
        biosample, else ``None``.

        Only slots present (and parseable) in the crosswalk row are included; a
        missing slot is left for the translator's sentinel path. ``has_raw_value``
        is intentionally unset — the NCBI env-triad fields were empty, so there
        is no submitter string to preserve.
        """
        barcode = self._barcode_for(sample_data)
        if barcode is None:
            return None
        slots = self._by_barcode.get(barcode)
        if not slots:
            return None
        resolved: dict[str, nmdc.ControlledIdentifiedTermValue] = {}
        for slot, (curie, label) in slots.items():
            resolved[slot] = nmdc.ControlledIdentifiedTermValue(
                term=nmdc.OntologyClass(
                    id=curie, name=label, type="nmdc:OntologyClass"
                ),
                type="nmdc:ControlledIdentifiedTermValue",
            )
        return resolved
