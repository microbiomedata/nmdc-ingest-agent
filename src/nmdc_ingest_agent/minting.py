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
from typing import Protocol


_TYPECODE_BY_CLASS: dict[str, str] = {
    "nmdc:Study": "sty",
    "nmdc:Biosample": "bsm",
    "nmdc:NucleotideSequencing": "dgns",
    "nmdc:DataObject": "dobj",
    "nmdc:Instrument": "inst",
}


class Minter(Protocol):
    def mint(self, schema_class: str, count: int = 1) -> list[str]: ...


class PlaceholderMinter:
    """Emit ``nmdc:<typecode>-99-<random8>`` IDs. Offline use only."""

    def mint(self, schema_class: str, count: int = 1) -> list[str]:
        try:
            typecode = _TYPECODE_BY_CLASS[schema_class]
        except KeyError as exc:
            raise ValueError(
                f"PlaceholderMinter has no typecode mapping for {schema_class!r}"
            ) from exc
        return [f"nmdc:{typecode}-99-{secrets.token_hex(4)}" for _ in range(count)]


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


def runtime_minter_from_env() -> RuntimeMinter:
    """Build a :class:`RuntimeMinter` from environment credentials.

    Required:
      - ``NMDC_RUNTIME_CLIENT_ID``
      - ``NMDC_RUNTIME_CLIENT_SECRET``

    Optional:
      - ``NMDC_RUNTIME_ENV`` — ``prod`` (default) or ``dev``.
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

    env = os.environ.get("NMDC_RUNTIME_ENV", "prod")
    auth = NMDCAuth(
        client_id=client_id,
        client_secret=client_secret,
        env=env,
    )
    return RuntimeMinter(_UpstreamMinter(env=env, auth=auth))
