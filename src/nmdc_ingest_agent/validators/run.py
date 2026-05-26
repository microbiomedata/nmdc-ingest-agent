"""Drive linkml-term-validator against an ObservedTerm projection and merge
findings back into the curation report.

Phase 1 wires only the BindingValidationPlugin: per-CURIE existence checks
(when the prefix is configured in oak_config.yaml) and label-concordance
checks against the rdfs:label-implementing slot. Dynamic enum validation is
out of scope for Phase 1.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_SCHEMA_PATH = PACKAGE_DIR / "term_validation.yaml"
DEFAULT_OAK_CONFIG_PATH = PACKAGE_DIR / "oak_config.yaml"
DEFAULT_TARGET_CLASS = "TermValidationSet"


def _default_cache_dir() -> Path:
    """User-level cache so ENVO sqlite downloads are reused across ingest runs."""
    root = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(root) / "nmdc-ingest-agent" / "ontology"


def run_term_validation(
    observed_terms: dict,
    *,
    work_dir: Path,
    schema: Path = DEFAULT_SCHEMA_PATH,
    oak_config: Path = DEFAULT_OAK_CONFIG_PATH,
    cache_dir: Path | None = None,
    lenient: bool = False,
) -> dict:
    """Run the binding validator against an observed-terms projection.

    Writes `observed_terms.yaml` into ``work_dir`` (linkml.validator's loaders
    work file-based), invokes the validator in-process, and returns a result
    dict with per-finding records plus a summary. If linkml-term-validator is
    not importable, returns ``{"skipped": True, "reason": ...}`` so callers can
    degrade gracefully.
    """
    try:
        from linkml.validator import Validator
        from linkml.validator.loaders import default_loader_for_file
        from linkml_term_validator.plugins import BindingValidationPlugin
    except ImportError as exc:
        return {
            "skipped": True,
            "reason": f"linkml-term-validator not installed ({exc})",
            "findings": [],
            "summary": {"errors": 0, "warnings": 0, "checked": 0},
        }

    work_dir.mkdir(parents=True, exist_ok=True)
    data_path = work_dir / "_term_validation_input.yaml"
    with open(data_path, "w") as fh:
        yaml.safe_dump(observed_terms, fh, sort_keys=False)

    if cache_dir is None:
        cache_dir = _default_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    plugin = BindingValidationPlugin(
        validate_labels=True,
        strict=not lenient,
        cache_dir=cache_dir,
        oak_config_path=oak_config,
    )
    validator = Validator(
        schema=str(schema),
        validation_plugins=[plugin],
    )

    loader = default_loader_for_file(data_path)
    report = validator.validate_source(loader, target_class=DEFAULT_TARGET_CLASS)

    terms = observed_terms.get("observed_terms", [])
    findings = [_finding_from_result(r, terms) for r in report.results]
    summary = {
        "errors": sum(1 for f in findings if f["severity"] == "error"),
        "warnings": sum(1 for f in findings if f["severity"] == "warning"),
        "checked": len(observed_terms.get("observed_terms", [])),
    }
    return {
        "skipped": False,
        "findings": findings,
        "summary": summary,
    }


def _finding_from_result(result: Any, observed_terms: list[dict]) -> dict:
    """Normalize a linkml.validator.report.ValidationResult into a dict.

    Coordinates (sample_id, slot, term_id) are recovered by parsing the index
    out of the path (e.g. ``observed_terms[3].term``) and looking up the
    original term record. Falls back to the context-provided ``curie:`` field
    used by label findings when the index path is unparseable.
    """
    context = {}
    for item in (result.context or []):
        if ":" in item:
            k, _, v = item.partition(":")
            context[k.strip()] = v.strip()

    severity = result.severity.name.lower() if hasattr(result.severity, "name") else str(result.severity).lower()
    severity = {"warn": "warning", "warning": "warning", "error": "error"}.get(severity, severity)

    finding_type = getattr(result, "type", "") or ""
    if finding_type == "term_not_found":
        level = "existence"
    elif finding_type == "binding_label_mismatch":
        level = "label"
    else:
        level = finding_type or "unknown"

    path = context.get("path", "")
    index = _index_from_path(path)
    term_record = observed_terms[index] if (index is not None and 0 <= index < len(observed_terms)) else None

    if term_record is not None:
        term_id = term_record["term"]["id"]
        sample_id = term_record["sample_id"]
        slot = term_record["slot"]
    else:
        term_id = context.get("curie", "")
        sample_id = ""
        slot = ""

    return {
        "level": level,
        "severity": severity,
        "message": result.message,
        "term_id": term_id,
        "sample_id": sample_id,
        "slot": slot,
        "index": index,
        "path": path,
        "context": context,
    }


def _index_from_path(path: str) -> int | None:
    """Pull the integer index out of a path like 'observed_terms[3].term'."""
    if not path:
        return None
    lb = path.find("[")
    rb = path.find("]", lb + 1)
    if lb == -1 or rb == -1:
        return None
    try:
        return int(path[lb + 1 : rb])
    except ValueError:
        return None


def merge_into_curation_report(
    curation_report: dict,
    validator_result: dict,
    observed_terms: dict,
) -> dict:
    """Fold validator findings into the curation_report's per-row validator stub.

    For each curation_report row matching (biosample_id, slot):
      * validator.info_ok  = True if no existence finding, False if there is
                             one, None if validation was skipped.
      * validator.label_ok = same logic for label findings.

    Rows whose (biosample_id, slot) was not validated (e.g. the row was a
    sentinel and was filtered out, or its prefix is not configured in
    oak_config) keep ``None`` so curators can distinguish "checked and clean"
    from "not checked".
    """
    if validator_result.get("skipped"):
        return curation_report

    terms = observed_terms.get("observed_terms", [])
    findings_by_key: dict[tuple[str, str], dict[str, bool]] = {}

    for finding in validator_result.get("findings", []):
        idx = finding.get("index")
        if idx is None or idx >= len(terms):
            continue
        term = terms[idx]
        key = (term["sample_id"], term["slot"])
        bucket = findings_by_key.setdefault(key, {"existence": False, "label": False})
        if finding["level"] in bucket:
            bucket[finding["level"]] = True

    validated_keys = {(t["sample_id"], t["slot"]) for t in terms}

    for row in curation_report.get("rows", []):
        key = (row["biosample_id"], row["slot"])
        if key not in validated_keys:
            continue
        bad = findings_by_key.get(key, {"existence": False, "label": False})
        row.setdefault("validator", {})
        row["validator"]["info_ok"] = not bad["existence"]
        row["validator"]["label_ok"] = not bad["label"]

    return curation_report
