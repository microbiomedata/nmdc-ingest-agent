"""Level-4 check: NMDC submission-schema env-triad value sets per MIxS package.

``nmdc-submission-schema`` publishes, per DataHarmonizer interface, a curated
static list of ENVO terms for each env-triad slot (``EnvBroadScaleSoilEnum``,
``EnvMediumWaterEnum``, ...). Only the Soil, Water, Sediment and
PlantAssociated interfaces carry them; the others (HCR, air, built
environment, host-associated, ...) accept any string, so for those the honest
answer is "no package-specific value set", never a pass or a fail.

The value sets are vendored in ``env_triad_valuesets.tsv`` (regenerate with
``generate_valuesets.py``) rather than imported at runtime because the
``nmdc-submission-schema`` wheel pins ``rdflib<7`` and would downgrade rdflib
for the whole project. The TSV header records the schema version it came from.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_VALUESETS_PATH = PACKAGE_DIR / "env_triad_valuesets.tsv"

ENV_TRIAD_SLOTS: tuple[str, ...] = ("env_broad_scale", "env_local_scale", "env_medium")

# MIxS environmental-package token (as it appears in an NCBI BioSample package
# name such as ``MIMS.me.soil.6.0`` or ``MIMARKS.survey.water.6.0``) -> NMDC
# submission-schema interface. Interfaces absent from the vendored TSV have no
# env-triad value set; they are still named so the report can say so.
PACKAGE_TOKEN_TO_INTERFACE: dict[str, str] = {
    "soil": "SoilInterface",
    "water": "WaterInterface",
    "sediment": "SedimentInterface",
    "plant-associated": "PlantAssociatedInterface",
    "host-associated": "HostAssociatedInterface",
    "air": "AirInterface",
    "built": "BuiltEnvInterface",
    "hydrocarbon-cores": "HcrCoresInterface",
    "hydrocarbon-fluids": "HcrFluidsSwabsInterface",
    "microbial": "BiofilmInterface",
    "miscellaneous": "MiscEnvsInterface",
    "wastewater": "WastewaterSludgeInterface",
}

_PV_RE = re.compile(r"^(?P<label>.*?)\s*\[(?P<curie>[A-Za-z][\w.-]*:[\w.-]+)\]\s*$")


def parse_permissible_value(text: str) -> Optional[tuple[str, str]]:
    """Split a DataHarmonizer-style ``label [CURIE]`` value into (label, CURIE)."""
    match = _PV_RE.match(text or "")
    if not match:
        return None
    return match.group("label").strip(), match.group("curie")


def infer_interface(env_package: Optional[str]) -> Optional[str]:
    """Map an NCBI/MIxS package string to a submission-schema interface name.

    Tokenizes on ``.`` so ``air`` cannot match inside another token, and
    returns None for packages NMDC has no interface for (e.g. ``MIMAG.6.0``,
    ``Metagenome.environmental.1.0``, human-* packages).
    """
    if not env_package:
        return None
    tokens = [t.strip().lower() for t in env_package.split(".")]
    for token in tokens:
        if token in PACKAGE_TOKEN_TO_INTERFACE:
            return PACKAGE_TOKEN_TO_INTERFACE[token]
    return None


@dataclass
class ValueSets:
    """Interface x slot -> {CURIE: label} with the source schema version."""

    schema_version: str = ""
    generated: str = ""
    # (interface, slot) -> enum name
    enum_for: dict[tuple[str, str], str] = field(default_factory=dict)
    # enum name -> {curie: label}
    members: dict[str, dict[str, str]] = field(default_factory=dict)

    def enum_name(self, interface: Optional[str], slot: str) -> Optional[str]:
        if interface is None:
            return None
        return self.enum_for.get((interface, slot))

    def contains(self, interface: Optional[str], slot: str, curie: str) -> Optional[bool]:
        """True/False for membership; None when the interface has no value set
        for this slot (or the interface is unknown)."""
        enum = self.enum_name(interface, slot)
        if enum is None:
            return None
        return curie in self.members.get(enum, {})

    @property
    def interfaces(self) -> set[str]:
        return {iface for iface, _slot in self.enum_for}


def load_valuesets(path: Path = DEFAULT_VALUESETS_PATH) -> Optional[ValueSets]:
    """Load the vendored TSV. Returns None (not an exception) if it is missing,
    so the validator can report the level as unavailable."""
    path = Path(path)
    if not path.exists():
        return None
    return _load_valuesets_cached(str(path))


@lru_cache(maxsize=4)
def _load_valuesets_cached(path_str: str) -> ValueSets:
    vs = ValueSets()
    header_meta: dict[str, str] = {}
    with open(path_str, newline="") as fh:
        body: list[str] = []
        for line in fh:
            if line.startswith("#"):
                key, _, value = line[1:].strip().partition(":")
                if value:
                    header_meta[key.strip()] = value.strip()
                continue
            body.append(line)
    vs.schema_version = header_meta.get("nmdc_submission_schema_version", "")
    vs.generated = header_meta.get("generated", "")
    for row in csv.DictReader(body, delimiter="\t"):
        key = (row["interface"], row["slot"])
        vs.enum_for[key] = row["enum"]
        vs.members.setdefault(row["enum"], {})[row["curie"]] = row["label"]
    return vs
