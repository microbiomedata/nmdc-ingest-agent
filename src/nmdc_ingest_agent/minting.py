"""ID minting backends for NMDC ingest.

Two implementations of the :class:`Minter` protocol:

- :class:`PlaceholderMinter` — emits ``nmdc:<typecode>-99-<random>`` IDs for
  offline development. Output is not ingest-ready.
- :class:`RuntimeMinter` — calls the production NMDC runtime API via
  ``nmdc_api_utilities.Minter`` and returns real, persistent identifiers.

The translator selects a backend at run time; builders only see the
``Minter`` protocol.
"""

from __future__ import annotations

import os
import secrets
from typing import Optional, Protocol


_TYPECODE_BY_CLASS: dict[str, str] = {
    "nmdc:Study": "sty",
    "nmdc:Biosample": "bsm",
    "nmdc:NucleotideSequencing": "dgns",
    "nmdc:DataObject": "dobj",
    "nmdc:Instrument": "inst",
    "nmdc:LibraryPreparation": "libprp",
    "nmdc:ProcessedSample": "procsm",
    "nmdc:Manifest": "manif",
}


class Minter(Protocol):
    def mint(self, schema_class: str, count: int = 1) -> list[str]: ...


class PlaceholderMinter:
    """Emit ``nmdc:<typecode>-99-<random>`` IDs. Offline use only.

    IDs are guaranteed unique across the lifetime of the instance: a 5-byte
    (40-bit) random blade makes collisions vanishingly unlikely, and a record of
    every issued id rejects any that does collide. (A 4-byte blade hit the
    birthday bound around ~12k ids of one type — e.g. one ProcessedSample per
    library for a large BioProject — and produced duplicate ids.)
    """

    def __init__(self) -> None:
        self._issued: set[str] = set()

    def mint(self, schema_class: str, count: int = 1) -> list[str]:
        try:
            typecode = _TYPECODE_BY_CLASS[schema_class]
        except KeyError as exc:
            raise ValueError(
                f"PlaceholderMinter has no typecode mapping for {schema_class!r}"
            ) from exc
        out: list[str] = []
        while len(out) < count:
            candidate = f"nmdc:{typecode}-99-{secrets.token_hex(5)}"
            if candidate in self._issued:
                continue
            self._issued.add(candidate)
            out.append(candidate)
        return out


class RuntimeMinter:
    """Adapt :class:`nmdc_api_utilities.minter.Minter` to the local protocol.

    Upstream returns ``str`` for ``count == 1`` and ``list[str]`` otherwise;
    this wrapper always returns ``list[str]`` so call sites stay uniform.
    """

    def __init__(self, client) -> None:
        self._client = client

    def mint(self, schema_class: str, count: int = 1) -> list[str]:
        result = self._client.mint(nmdc_type=schema_class, count=count)
        return [result] if isinstance(result, str) else list(result)


def runtime_minter_from_env(env: Optional[str] = None) -> RuntimeMinter:
    """Build a :class:`RuntimeMinter` from environment credentials.

    Required:
      - ``NMDC_RUNTIME_CLIENT_ID``
      - ``NMDC_RUNTIME_CLIENT_SECRET``

    The runtime environment is taken from ``env`` when given, else the
    ``NMDC_RUNTIME_ENV`` variable, else ``dev``. dev-minted IDs are valid in
    both environments, so dev is the safe default.
    """
    client_id = os.environ.get("NMDC_RUNTIME_CLIENT_ID")
    client_secret = os.environ.get("NMDC_RUNTIME_CLIENT_SECRET")
    missing = [
        name
        for name, value in (
            ("NMDC_RUNTIME_CLIENT_ID", client_id),
            ("NMDC_RUNTIME_CLIENT_SECRET", client_secret),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Real ID minting requires environment variable(s): "
            + ", ".join(missing)
        )

    from nmdc_api_utilities.auth import NMDCAuth
    from nmdc_api_utilities.minter import Minter as _UpstreamMinter

    env = env or os.environ.get("NMDC_RUNTIME_ENV") or "dev"
    auth = NMDCAuth(
        client_id=client_id,
        client_secret=client_secret,
        env=env,
    )
    return RuntimeMinter(_UpstreamMinter(env=env, auth=auth))
