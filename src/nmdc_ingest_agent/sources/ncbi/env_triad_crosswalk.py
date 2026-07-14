"""Resolve env-triad slots from a per-biosample crosswalk TSV, keyed by sample id.

Some sources carry no usable MIxS env-triad in NCBI but *do* have a richer external
mapping — e.g. MicroFlora Danica (BioProject PRJNA1071982) encodes habitat only in a
coarse ``isolation_source`` string, while the v2 MFDO crosswalk deliverable
``mfd_biosamples_annotated.tsv`` holds the full env triad keyed by ``fieldsample_barcode``
(``MFD00001``). This resolver loads any such TSV into a ``key -> {slot: (curie, label)}``
index and hands the deterministic values to the NCBI translator, which commits them at
build time (curation report ``outcome="resolved_at_pipeline"``). Biosamples with no matching
key resolve to ``None`` so the translator keeps its ordinary ``ENVO:00000000`` sentinel path.

The crosswalk is **not** built in — supply one per run with ``--env-triad-crosswalk PATH``
or ``NMDC_ENV_TRIAD_CROSSWALK_TSV``. Without one, this resolver is absent and no biosample
is pre-resolved (so a plain run yields sentinels for every env-triad slot). Each triad cell
in the TSV is a combined ``"<label> [<CURIE>]"`` string
(e.g. ``"temperate broadleaf forest biome [ENVO:01000202]"``).
"""

from __future__ import annotations

import csv
import os
import re
from pathlib import Path
from typing import Iterator, Optional

from nmdc_schema import nmdc

# Triad slots, in the order the annotated TSV and the NMDC Biosample expose them.
_TRIAD_SLOTS = ("env_broad_scale", "env_local_scale", "env_medium")

# Default column in the crosswalk that holds the per-biosample join key. Overridable.
_DEFAULT_KEY_COLUMN = "fieldsample_barcode"

# A combined cell: ``temperate broadleaf forest biome [ENVO:01000202]`` ->
# label ``temperate broadleaf forest biome``, CURIE ``ENVO:01000202``.
_COMBINED_RE = re.compile(r"^(?P<label>.*?)\s*\[(?P<curie>[A-Za-z]+:\d+)\]\s*$")

# Env vars that can point at a crosswalk TSV. The first is canonical; the second is
# the legacy MFD-specific name kept for back-compat.
_ENV_VARS = ("NMDC_ENV_TRIAD_CROSSWALK_TSV", "NMDC_MFD_CROSSWALK_TSV")


def _parse_combined(value: str) -> Optional[tuple[str, str]]:
    """Split ``"<label> [<CURIE>]"`` into ``(curie, label)``.

    Returns ``None`` for empty or malformed cells so the caller can skip that slot
    (leaving its sentinel) rather than committing a bad term.
    """
    match = _COMBINED_RE.match((value or "").strip())
    if not match:
        return None
    return match.group("curie"), match.group("label").strip()


class CrosswalkEnvTriadResolver:
    """Look up crosswalk env-triad terms for a biosample by its join key."""

    def __init__(
        self,
        by_key: dict[str, dict[str, tuple[str, str]]],
        key_attribute: Optional[str] = None,
    ) -> None:
        # key -> {slot: (curie, label)}; only slots whose cell parsed are kept.
        self._by_key = by_key
        # Optional NCBI attribute to try as a fallback join key (besides sample_name).
        self._key_attribute = key_attribute

    @classmethod
    def from_tsv(
        cls,
        path: Optional[Path] = None,
        *,
        key_column: str = _DEFAULT_KEY_COLUMN,
        key_attribute: Optional[str] = None,
        slots: tuple[str, ...] = _TRIAD_SLOTS,
    ) -> Optional["CrosswalkEnvTriadResolver"]:
        """Build a resolver from a per-biosample crosswalk TSV.

        Path precedence: explicit ``path`` > ``$NMDC_ENV_TRIAD_CROSSWALK_TSV`` >
        ``$NMDC_MFD_CROSSWALK_TSV`` (legacy). There is **no built-in default file** —
        returns ``None`` when no path is configured or the file is absent, so runs
        without a crosswalk (and non-matching biosamples) fall through to the
        translator's sentinel path unchanged.
        """
        if path is None:
            for var in _ENV_VARS:
                override = os.environ.get(var, "").strip()
                # Fall through to the next var if a set path does not exist, so a
                # stale canonical var does not mask a valid legacy one.
                if override and Path(override).exists():
                    path = Path(override)
                    break
        if path is None or not Path(path).exists():
            return None

        by_key: dict[str, dict[str, tuple[str, str]]] = {}
        with open(path, newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                key = (row.get(key_column) or "").strip().upper()
                if not key:
                    continue
                parsed_slots: dict[str, tuple[str, str]] = {}
                for slot in slots:
                    parsed = _parse_combined(row.get(slot, ""))
                    if parsed:
                        parsed_slots[slot] = parsed
                if parsed_slots:
                    by_key[key] = parsed_slots
        return cls(by_key, key_attribute=key_attribute)

    def _candidate_keys(self, sample_data: dict) -> Iterator[str]:
        """Yield uppercased candidate join keys for a raw NCBI biosample record:
        its ``sample_name``, then the configured fallback attribute if any."""
        candidates = [sample_data.get("sample_name")]
        if self._key_attribute:
            candidates.append(sample_data.get("attributes", {}).get(self._key_attribute))
        for cand in candidates:
            s = (cand or "").strip()
            if s:
                yield s.upper()

    def resolve(
        self, sample_data: dict
    ) -> Optional[dict[str, nmdc.ControlledIdentifiedTermValue]]:
        """Return ``{slot: ControlledIdentifiedTermValue}`` for a matched biosample,
        else ``None``.

        Tries each candidate key in order and uses the first present in the crosswalk.
        Only slots present (and parseable) in that row are included; a missing slot is
        left for the translator's sentinel path. ``has_raw_value`` is intentionally
        unset — the NCBI env-triad fields were empty, so there is no submitter string
        to preserve.
        """
        for key in self._candidate_keys(sample_data):
            slots = self._by_key.get(key)
            if not slots:
                continue
            return {
                slot: nmdc.ControlledIdentifiedTermValue(
                    term=nmdc.OntologyClass(id=curie, name=label, type="nmdc:OntologyClass"),
                    type="nmdc:ControlledIdentifiedTermValue",
                )
                for slot, (curie, label) in slots.items()
            }
        return None
