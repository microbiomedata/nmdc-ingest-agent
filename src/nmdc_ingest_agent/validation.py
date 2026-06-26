"""Runtime validation against the NMDC ``/metadata/json:validate`` endpoint.

The pipeline's local check (``linkml json_loader.load(target_class=nmdc.Database)``)
is schema-only. The NMDC runtime endpoint is the *authoritative* validator: on top
of per-collection schema validation it also enforces **referential integrity**
(every ``has_input`` / ``has_output`` / ``associated_studies`` / ``instrument_used``
/ ``was_generated_by`` / ``in_manifest`` reference must resolve in the payload or
the runtime DB), **biosample-name-uniqueness-per-study**, and **id-uniqueness**.

We reuse the existing client ``nmdc_api_utilities.metadata.Metadata(env).validate_json``
(no auth; constructs without credentials; ``Metadata("dev")`` targets
``https://api-dev.microbiomedata.org``) and translate its raised ``Exception`` into a
clear, multi-line :class:`RuntimeValidationError` that surfaces the endpoint's
per-collection ``detail``. Network failures and HTTP 5xx (a large deliverable can
exceed the endpoint's limits and return a 502) are mapped to friendly messages
rather than stack traces, so callers can fall back to the offline linkml load.

The top-level ``@type: Database`` that the linkml ``json_dumper`` injects does **not**
need to be stripped: the endpoint ignores unknown / ``@``-prefixed top-level keys and
validates only the known ``*_set`` collections.
"""

import json
import re
from pathlib import Path
from typing import Union

import requests
from nmdc_api_utilities.metadata import Metadata

# The runtime client embeds the HTTP status and raw response body in its raised
# Exception message ("...Status Code: <n>\nResponse: <body>"); parse them back out.
_STATUS_RE = re.compile(r"Status Code:\s*(\d+)")
_RESPONSE_MARKER = "Response:"


class RuntimeValidationError(Exception):
    """The NMDC runtime ``json:validate`` endpoint rejected the file, or could
    not be reached. Carries a human-readable, multi-line message (per-collection
    ``detail`` on a validation failure; a friendly hint on a network/5xx error)."""


def _format_detail(detail: object) -> str:
    """Render the endpoint's ``detail`` map ({collection: [errors]}) as indented
    ``[collection] message`` lines."""
    if isinstance(detail, dict):
        lines: list[str] = []
        for collection, errors in detail.items():
            if isinstance(errors, list):
                for err in errors:
                    lines.append(f"  [{collection}] {err}")
            else:
                lines.append(f"  [{collection}] {errors}")
        return "\n".join(lines)
    return f"  {detail}"


def _parse_error_detail(body: Union[str, None]) -> object:
    """Return the ``detail`` payload from a ``{"result":"errors","detail":{...}}``
    response body, or None if the body is missing / not that shape."""
    if not body:
        return None
    try:
        parsed = json.loads(body)
    except (ValueError, TypeError):
        return None
    if isinstance(parsed, dict) and parsed.get("result") == "errors":
        return parsed.get("detail")
    return None


def _interpret(exc: Exception, env: str, base_url: str) -> RuntimeValidationError:
    """Translate the runtime client's raised Exception into a clear error."""
    msg = str(exc)

    # The client refuses to POST any file containing the literal word "placeholder"
    # (our "-99-" placeholder shoulder does not trigger this).
    if "Placeholder values found" in msg:
        return RuntimeValidationError(
            "The JSON contains the literal word 'placeholder', which the runtime "
            "client refuses to submit. Placeholder NMDC ids use the '-99-' shoulder "
            "and do not trigger this — check for a stray 'placeholder' string in the data."
        )

    status_match = _STATUS_RE.search(msg)
    status = int(status_match.group(1)) if status_match else None
    body = msg.split(_RESPONSE_MARKER, 1)[1].strip() if _RESPONSE_MARKER in msg else None

    # HTTP 5xx — origin overloaded or payload too large. A ~45 MB / ~58k-record MFD
    # deliverable consistently returns a Cloudflare 502 from this endpoint.
    if (status is not None and status >= 500) or (body and "Bad gateway" in body):
        return RuntimeValidationError(
            f"The NMDC {env} runtime returned HTTP {status or '5xx'} (server error) for "
            f"{base_url}/metadata/json:validate. Large deliverables (tens of thousands "
            f"of records) can exceed the endpoint's limits; try a smaller BioProject or "
            f"retry later. The offline linkml schema load remains a fallback.\n"
            f"Original response: {body or msg}"
        )

    detail = _parse_error_detail(body)
    if detail is not None:
        return RuntimeValidationError(
            f"NMDC {env} runtime validation failed (HTTP {status}). "
            f"Per-collection detail:\n{_format_detail(detail)}"
        )

    return RuntimeValidationError(
        f"NMDC {env} runtime validation failed (HTTP {status}).\n{body or msg}"
    )


def validate_runtime(json_path: Union[str, Path], env: str = "dev") -> None:
    """Validate an NMDC Database JSON file against the runtime ``json:validate``
    endpoint for ``env``.

    Returns None on success. Raises :class:`RuntimeValidationError` with a clear,
    multi-line message on a validation failure (carrying the endpoint's
    per-collection ``detail``), a network error, or an HTTP 5xx.

    ``env`` **must match** the environment instruments were resolved against
    (``InstrumentResolver.from_api(env)``); otherwise ``instrument_used`` references
    fail referential integrity. ``dev`` is the default because the dev
    ``instrument_set`` is a superset of prod and the endpoint needs no auth there.
    """
    path = Path(json_path)
    if not path.exists():
        raise RuntimeValidationError(f"File not found: {path}")

    client = Metadata(env)
    try:
        client.validate_json(str(path))
    except requests.exceptions.RequestException as e:
        raise RuntimeValidationError(
            f"Could not reach the NMDC {env} runtime at {client.base_url} "
            f"({e.__class__.__name__}: {e}). Endpoint validation needs network access; "
            f"the local linkml schema load is the offline fallback."
        ) from e
    except RuntimeValidationError:
        raise
    except Exception as e:
        raise _interpret(e, env, client.base_url) from e
