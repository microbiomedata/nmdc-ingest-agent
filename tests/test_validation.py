"""Tests for nmdc_ingest_agent.validation.validate_runtime.

The runtime ``/metadata/json:validate`` endpoint is mocked (no live network): we
monkeypatch the ``Metadata`` client the module imports so the tests assert the
wiring (right path + env), the success path, and the error translation for
validation failures, network errors, HTTP 5xx, and the placeholder guard.
"""

import json

import pytest
import requests

from nmdc_ingest_agent import validation
from nmdc_ingest_agent.validation import RuntimeValidationError, validate_runtime


def _patch_metadata(monkeypatch, behavior, recorder=None):
    """Replace validation.Metadata with a fake whose validate_json runs ``behavior``
    (called with the path) and records the constructed env + posted path."""

    class _FakeMetadata:
        def __init__(self, env="prod", auth=None):
            self.env = env
            self.base_url = f"https://api-{env}.microbiomedata.org"
            if recorder is not None:
                recorder["env"] = env

        def validate_json(self, path):
            if recorder is not None:
                recorder["path"] = path
            return behavior(path)

    monkeypatch.setattr(validation, "Metadata", _FakeMetadata)


def _client_failure(status: int, body: str) -> Exception:
    """Reproduce the exact Exception shape the real client raises on failure."""
    return Exception(
        "Validation failed with the following information:\n"
        f"Status Code: {status}\n"
        f"Response: {body}"
    )


def test_success_returns_none_with_right_path_and_env(monkeypatch, tmp_path):
    f = tmp_path / "db.json"
    f.write_text("{}")
    rec: dict = {}
    _patch_metadata(monkeypatch, lambda p: 200, rec)

    assert validate_runtime(str(f), env="dev") is None
    assert rec["path"] == str(f)
    assert rec["env"] == "dev"


def test_missing_file_raises(tmp_path):
    with pytest.raises(RuntimeValidationError, match="File not found"):
        validate_runtime(str(tmp_path / "nope.json"), env="dev")


def test_validation_errors_surface_per_collection_detail(monkeypatch, tmp_path):
    f = tmp_path / "db.json"
    f.write_text("{}")
    body = json.dumps({
        "result": "errors",
        "detail": {
            "biosample_set": [
                "QuantityValue at /biosample_set/0/depth has unit 'cm' which is "
                "not allowed for slot 'depth' (allowed: m)"
            ]
        },
    })
    _patch_metadata(monkeypatch, lambda p: (_ for _ in ()).throw(_client_failure(200, body)))

    with pytest.raises(RuntimeValidationError) as ei:
        validate_runtime(str(f), env="dev")
    msg = str(ei.value)
    assert "biosample_set" in msg
    assert "depth" in msg
    assert "allowed: m" in msg


def test_network_error_is_friendly(monkeypatch, tmp_path):
    f = tmp_path / "db.json"
    f.write_text("{}")

    def boom(_path):
        raise requests.exceptions.ConnectionError("no route to host")

    _patch_metadata(monkeypatch, boom)

    with pytest.raises(RuntimeValidationError) as ei:
        validate_runtime(str(f), env="dev")
    assert "Could not reach" in str(ei.value)


def test_server_5xx_is_friendly(monkeypatch, tmp_path):
    f = tmp_path / "db.json"
    f.write_text("{}")
    body = json.dumps({"title": "Error 502: Bad gateway", "status": 502})
    _patch_metadata(monkeypatch, lambda p: (_ for _ in ()).throw(_client_failure(502, body)))

    with pytest.raises(RuntimeValidationError) as ei:
        validate_runtime(str(f), env="dev")
    msg = str(ei.value)
    assert "502" in msg
    assert "Large deliverables" in msg


def test_placeholder_guard_is_friendly(monkeypatch, tmp_path):
    f = tmp_path / "db.json"
    f.write_text("{}")

    def boom(_path):
        raise Exception("Placeholder values found in json!")

    _patch_metadata(monkeypatch, boom)

    with pytest.raises(RuntimeValidationError) as ei:
        validate_runtime(str(f), env="dev")
    assert "placeholder" in str(ei.value).lower()
