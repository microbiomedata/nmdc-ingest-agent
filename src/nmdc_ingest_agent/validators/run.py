"""Drive ``linkml-term-validator`` over a projection and normalize its findings.

:func:`run_term_validation` takes the instance produced by
:func:`~nmdc_ingest_agent.validators.extract.extract_observed_terms`, runs
``BindingValidationPlugin`` in-process against ``term_validation.yaml``, layers
the checks the plugin does not express declaratively (obsolescence, the
negative "env_local_scale is not a biome" rule, submission-schema value sets),
and returns one report dict with

* ``status`` — ``ok`` | ``skipped`` (extra not installed) | ``unavailable``
  (ontology service unreachable) | ``error`` (anything else, e.g. the first-run
  ENVO download failing offline). It never raises: an ingest must not abort
  because optional QC could not run (PR #28 review).
* ``terms`` — one entry per observed term with the four curation-report flags
  (``info_ok``, ``label_ok``, ``anchor_ok``, ``valueset_ok``; ``None`` = not
  checked) and human-readable ``notes``.
* ``findings`` — one entry per problem, with the severity from the issue-#8
  table (existence/obsolete/label = error, anchor/valueset = warning),
  independent of the ``Severity`` the upstream plugin assigns.

:func:`merge_into_curation_report` folds the flags into the curation report
without ever contradicting a curator's differing commit.
"""

from __future__ import annotations

import importlib.metadata as _md
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

import yaml

from nmdc_ingest_agent.validators.extract import iter_terms
from nmdc_ingest_agent.validators.valuesets import (
    DEFAULT_VALUESETS_PATH,
    ENV_TRIAD_SLOTS,
    ValueSets,
    infer_interface,
    load_valuesets,
)

logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_SCHEMA_PATH = PACKAGE_DIR / "term_validation.yaml"
DEFAULT_OAK_CONFIG_PATH = PACKAGE_DIR / "oak_config.yaml"
TARGET_CLASS = "TermValidationSet"

#: ``PREFIX=adapter,PREFIX=adapter`` overrides/additions to oak_config.yaml.
ADAPTERS_ENV_VAR = "NMDC_TERM_VALIDATION_ADAPTERS"
#: Overrides the default label/enum cache location.
CACHE_DIR_ENV_VAR = "NMDC_TERM_VALIDATION_CACHE_DIR"

STATUS_OK = "ok"
STATUS_SKIPPED = "skipped"
STATUS_UNAVAILABLE = "unavailable"
STATUS_ERROR = "error"

FLAGS: tuple[str, ...] = ("info_ok", "label_ok", "anchor_ok", "valueset_ok")

# Level -> severity in this report (issue #8, "Layer the checks").
LEVEL_SEVERITY: dict[str, str] = {
    "existence": "error",
    "obsolete": "error",
    "label": "error",
    "anchor": "warning",
    "valueset": "warning",
    "other": "warning",
}

# Slot -> (enum in term_validation.yaml, membership required?, anchor label).
# env_local_scale has no single ENVO subtree (see term_validation.yaml), so its
# rule is negative: the term must NOT be a biome.
ANCHORS: dict[str, tuple[str, bool, str]] = {
    "env_broad_scale": ("BiomeEnum", True, "biome (ENVO:00000428)"),
    "env_medium": ("EnvironmentalMaterialEnum", True, "environmental material (ENVO:00010483)"),
    "env_local_scale": ("BiomeEnum", False, "biome (ENVO:00000428)"),
}

_PATH_RE = re.compile(r"^(?P<slot>\w+)\[(?P<index>\d+)\]\.term$")


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def default_cache_dir() -> Path:
    """``$NMDC_TERM_VALIDATION_CACHE_DIR``, else ``~/.cache/nmdc-ingest-agent/term-validator``
    (honouring ``$XDG_CACHE_HOME``) so label/enum caches survive across runs."""
    override = os.environ.get(CACHE_DIR_ENV_VAR)
    if override:
        return Path(override).expanduser()
    root = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(root) / "nmdc-ingest-agent" / "term-validator"


def parse_adapter_spec(spec: Any) -> dict[str, str]:
    """Parse ``PREFIX=adapter`` items (a comma-separated string, or a list of
    such strings) into a dict. Empty input -> ``{}``. Malformed -> ValueError."""
    if not spec:
        return {}
    items: list[str] = []
    for chunk in spec if isinstance(spec, (list, tuple)) else [spec]:
        items.extend(part for part in str(chunk).split(",") if part.strip())
    out: dict[str, str] = {}
    for item in items:
        prefix, sep, adapter = item.partition("=")
        if not sep or not prefix.strip() or not adapter.strip():
            raise ValueError(f"adapter spec must look like PREFIX=adapter, got {item!r}")
        out[prefix.strip()] = adapter.strip()
    return out


def load_adapters(oak_config_path: Path) -> dict[str, Optional[str]]:
    """The ``ontology_adapters`` mapping of an oak_config.yaml (empty values kept
    as None so callers can tell "explicitly skipped" from "absent")."""
    with open(oak_config_path) as fh:
        config = yaml.safe_load(fh) or {}
    return dict(config.get("ontology_adapters") or {})


def effective_oak_config(
    oak_config_path: Path,
    overrides: Optional[dict[str, str]],
    cache_dir: Path,
) -> tuple[Path, dict[str, Optional[str]]]:
    """Resolve the oak config to hand to the plugin.

    With no overrides the packaged file is used as-is. With overrides (CLI
    ``--adapter`` / ``$NMDC_TERM_VALIDATION_ADAPTERS``) a merged copy is written
    under ``cache_dir`` because the plugin only reads adapters from a file.
    Returns ``(path, effective_adapters)``.
    """
    with open(oak_config_path) as fh:
        config = yaml.safe_load(fh) or {}
    adapters: dict[str, Optional[str]] = dict(config.get("ontology_adapters") or {})
    if not overrides:
        return Path(oak_config_path), adapters
    adapters.update(overrides)
    config["ontology_adapters"] = adapters
    cache_dir.mkdir(parents=True, exist_ok=True)
    merged = cache_dir / "oak_config.effective.yaml"
    with open(merged, "w") as fh:
        yaml.safe_dump(config, fh, sort_keys=False)
    return merged, adapters


def _version(dist: str) -> Optional[str]:
    try:
        return _md.version(dist)
    except _md.PackageNotFoundError:
        return None


def tool_versions() -> dict[str, Optional[str]]:
    return {
        "nmdc_ingest_agent": _version("nmdc-ingest-agent"),
        "linkml_term_validator": _version("linkml-term-validator"),
        "oaklib": _version("oaklib"),
        "linkml": _version("linkml"),
    }


def ontology_versions(plugin: Any, prefixes: set[str]) -> dict[str, Optional[str]]:
    """Best-effort ``{prefix: release}`` (e.g. ``{"ENVO": "2025-10-20"}``) for the
    prefixes whose adapters this run actually used, read from the adapter's
    ``owl:versionInfo`` / ``owl:versionIRI``. A curator reading the report later
    needs to know which ontology snapshot judged the terms. Never raises and
    never builds an adapter that was not already built."""
    versions: dict[str, Optional[str]] = {}
    access = getattr(plugin, "ontology", None)
    cache = getattr(access, "_adapter_cache", None) or {}
    for prefix in sorted(prefixes):
        adapter = cache.get(prefix)
        if adapter is None:
            continue
        version: Optional[str] = None
        try:
            for ontology in list(adapter.ontologies())[:5]:
                meta = adapter.ontology_metadata_map(ontology) or {}
                info = meta.get("owl:versionInfo") or meta.get("owl:versionIRI") or []
                if isinstance(info, str):
                    info = [info]
                if info:
                    version = str(info[0])
                    break
        except Exception:  # noqa: BLE001 — metadata is a nicety, never a failure
            logger.debug("could not read ontology version for %s", prefix, exc_info=True)
        versions[prefix] = version
    return versions


# ---------------------------------------------------------------------------
# Result normalization
# ---------------------------------------------------------------------------


def _context_dict(result: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in getattr(result, "context", None) or []:
        key, sep, value = str(item).partition(":")
        if sep:
            out[key.strip()] = value.strip()
    return out


def _locate(result: Any) -> Optional[tuple[str, int]]:
    """``(slot, index)`` from a ``path: env_medium[3].term`` context entry."""
    match = _PATH_RE.match(_context_dict(result).get("path", ""))
    if not match:
        return None
    return match.group("slot"), int(match.group("index"))


def _level_for(result: Any) -> str:
    kind = getattr(result, "type", "") or ""
    if kind == "term_not_found":
        return "existence"
    if kind in ("binding_label_mismatch", "binding_label_invalid"):
        return "label"
    if kind == "binding_validation" and "dynamic enum" in (result.message or ""):
        return "anchor"
    return "other"


def _prefix(curie: str) -> str:
    return curie.split(":", 1)[0] if ":" in curie else ""


def _new_term_entry(record: dict) -> dict:
    term = record.get("term") or {}
    return {
        "biosample_id": record.get("biosample_id"),
        "slot": record.get("slot"),
        "term_id": term.get("id"),
        "term_label": term.get("label"),
        "prefix": _prefix(term.get("id") or ""),
        "checked": False,
        "ontology_label": None,
        "obsolete": None,
        "env_package": record.get("env_package") or None,
        "inferred_interface": None,
        "valueset_enum": None,
        "info_ok": None,
        "label_ok": None,
        "anchor_ok": None,
        "valueset_ok": None,
        "notes": [],
    }


def _finding(level: str, entry: dict, message: str) -> dict:
    return {
        "level": level,
        "severity": LEVEL_SEVERITY.get(level, "warning"),
        "biosample_id": entry["biosample_id"],
        "slot": entry["slot"],
        "term_id": entry["term_id"],
        "term_label": entry["term_label"],
        "ontology_label": entry.get("ontology_label"),
        "inferred_interface": entry.get("inferred_interface"),
        "valueset_enum": entry.get("valueset_enum"),
        "message": message,
    }


def _empty_summary() -> dict:
    return {
        "terms": 0,
        "checked": 0,
        "unchecked": 0,
        "unchecked_prefixes": [],
        "skipped_sentinels": 0,
        "errors": 0,
        "warnings": 0,
        "by_level": {level: 0 for level in LEVEL_SEVERITY},
        "by_slot": {},
    }


def _base_report(instance: dict, *, status: str, reason: Optional[str], config: dict) -> dict:
    meta = instance.get("_meta") or {}
    summary = _empty_summary()
    summary["terms"] = sum(1 for _ in iter_terms(instance))
    summary["skipped_sentinels"] = int(meta.get("skipped_sentinels") or 0)
    return {
        "status": status,
        "reason": reason,
        "tool": tool_versions(),
        "config": config,
        "summary": summary,
        "findings": [],
        "terms": [],
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_term_validation(
    instance: dict,
    *,
    schema: Path = DEFAULT_SCHEMA_PATH,
    oak_config: Path = DEFAULT_OAK_CONFIG_PATH,
    cache_dir: Optional[Path] = None,
    adapters: Optional[dict[str, str]] = None,
    lenient: bool = False,
    offline: bool = False,
    valuesets_path: Optional[Path] = DEFAULT_VALUESETS_PATH,
) -> dict:
    """Validate a projection instance; return the report dict described in the
    module docstring. Never raises.

    ``adapters`` adds/overrides per-prefix OAK adapters on top of
    ``oak_config``; when None, ``$NMDC_TERM_VALIDATION_ADAPTERS`` is consulted.
    ``lenient`` stops missing terms being reported (label/anchor checks still
    run). ``offline`` forbids building OAK adapters: only the file cache is
    consulted, and anything not cached is reported as not found.
    ``valuesets_path=None`` disables the level-4 check.
    """
    cache_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    if adapters is None:
        try:
            adapters = parse_adapter_spec(os.environ.get(ADAPTERS_ENV_VAR))
        except ValueError as exc:
            adapters = {}
            logger.warning("Ignoring malformed %s: %s", ADAPTERS_ENV_VAR, exc)

    valuesets: Optional[ValueSets] = load_valuesets(valuesets_path) if valuesets_path else None
    config: dict[str, Any] = {
        "schema": str(schema),
        "oak_config": str(oak_config),
        "adapters": {},
        "cache_dir": str(cache_dir),
        "offline": offline,
        "lenient": lenient,
        "valuesets": (
            {
                "path": str(valuesets_path),
                "nmdc_submission_schema_version": valuesets.schema_version,
                "generated": valuesets.generated,
            }
            if valuesets is not None
            else None
        ),
    }

    try:
        from linkml.validator import Validator
        from linkml_term_validator.plugins import BindingValidationPlugin
        from linkml_term_validator.utils import OntologyServiceUnavailableError
    except ImportError as exc:
        return _base_report(
            instance,
            status=STATUS_SKIPPED,
            reason=f"linkml-term-validator is not installed ({exc}); run `uv sync --extra ontology`",
            config=config,
        )

    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        config_path, effective = effective_oak_config(Path(oak_config), adapters, cache_dir)
        config["adapters"] = effective
        configured = {p for p, a in effective.items() if a}

        plugin = BindingValidationPlugin(
            validate_labels=True,
            strict=not lenient,
            cache_dir=cache_dir,
            oak_config_path=config_path,
            offline=offline,
        )
        validator = Validator(schema=str(schema), validation_plugins=[plugin])
        data = {k: v for k, v in instance.items() if not k.startswith("_")}
        upstream = validator.validate(data, target_class=TARGET_CLASS)

        report = _base_report(instance, status=STATUS_OK, reason=None, config=config)
        _normalize(
            instance, upstream.results, plugin, configured, valuesets, report,
            offline=offline, lenient=lenient,
        )
        used = {t["prefix"] for t in report["terms"] if t["checked"]}
        report["tool"]["ontology_versions"] = ontology_versions(plugin, used)
        return report
    except OntologyServiceUnavailableError as exc:
        return _base_report(
            instance,
            status=STATUS_UNAVAILABLE,
            reason=f"ontology service unavailable; terms could not be checked ({exc})",
            config=config,
        )
    except Exception as exc:  # noqa: BLE001 — optional QC must never abort an ingest
        logger.debug("term validation failed", exc_info=True)
        return _base_report(
            instance,
            status=STATUS_ERROR,
            reason=f"{type(exc).__name__}: {exc}",
            config=config,
        )


def _check_valueset(entry: dict, valuesets: Optional[ValueSets], findings: list[dict]) -> None:
    """Level 4 for one term: pure set membership against the vendored NMDC
    value set of the sample's inferred package interface (no ontology access)."""
    if valuesets is None or entry["slot"] not in ENV_TRIAD_SLOTS:
        return
    interface = infer_interface(entry.get("env_package"))
    entry["inferred_interface"] = interface
    enum = valuesets.enum_name(interface, entry["slot"])
    entry["valueset_enum"] = enum
    if enum is None:
        who = interface or (
            f"package {entry['env_package']!r}" if entry.get("env_package") else "unknown package"
        )
        entry["notes"].append(f"no NMDC value set for {who} / {entry['slot']}; valueset check not applicable")
        return
    member = valuesets.contains(interface, entry["slot"], entry["term_id"])
    entry["valueset_ok"] = bool(member)
    if not member:
        label = entry.get("ontology_label") or entry.get("term_label") or ""
        findings.append(_finding(
            "valueset", entry,
            f"{entry['term_id']} ({label}) is outside {enum} "
            f"(nmdc-submission-schema {valuesets.schema_version}) for {interface}",
        ))


def _normalize(
    instance: dict,
    results: list,
    plugin: Any,
    configured: set[str],
    valuesets: Optional[ValueSets],
    report: dict,
    *,
    offline: bool,
    lenient: bool = False,
) -> None:
    """Fold upstream results plus the Python-side checks into ``report``."""
    entries: dict[tuple[str, int], dict] = {}
    for slot, index, record in iter_terms(instance):
        entries[(slot, index)] = _new_term_entry(record)

    # Per-CURIE facts are memoized: an ingest repeats the same few hundred
    # CURIEs across thousands of biosamples, and the plugin does not cache
    # negative enum-membership answers.
    facts: dict[str, dict[str, Any]] = {}

    def _facts(term_id: str) -> dict[str, Any]:
        cached = facts.get(term_id)
        if cached is None:
            cached = {"label": plugin.get_ontology_label(term_id), "obsolete": None, "in_biome": None}
            facts[term_id] = cached
        return cached

    # 1. Bucket upstream results by (slot, index) and level.
    upstream: dict[tuple[str, int], dict[str, list]] = {}
    for result in results:
        where = _locate(result)
        if where is None or where not in entries:
            logger.warning("Unlocatable validator result dropped: %s", result.message)
            continue
        upstream.setdefault(where, {}).setdefault(_level_for(result), []).append(result)

    schema_view = getattr(plugin, "schema_view", None)
    biome_enum = schema_view.get_enum("BiomeEnum") if schema_view is not None else None

    findings: list[dict] = []
    unchecked_prefixes: set[str] = set()

    for key, entry in entries.items():
        term_id = entry["term_id"]
        prefix = entry["prefix"]
        levels = upstream.get(key, {})

        # Unconfigured prefix (offline mode checks every prefix from the cache):
        # no ontology-backed check is possible, but the value-set check (level
        # 4) needs no adapter, so it still runs below.
        if prefix not in configured and not offline:
            unchecked_prefixes.add(prefix)
            entry["notes"].append(f"prefix {prefix!r} not configured in oak_config; ontology checks skipped")
            _check_valueset(entry, valuesets, findings)
            continue
        entry["checked"] = True

        fact = _facts(term_id)
        label = fact["label"]
        entry["ontology_label"] = label

        # Level 1a: existence.
        if label is None or "existence" in levels:
            if lenient:
                # The plugin stays silent in lenient mode; record the gap as a
                # warning and leave info_ok undetermined rather than False.
                entry["notes"].append("unresolvable CURIE (lenient mode)")
                finding = _finding("existence", entry, f"Term {term_id} could not be resolved (lenient mode)")
                finding["severity"] = "warning"
                findings.append(finding)
            else:
                entry["info_ok"] = False
                where = "the offline cache" if offline else "ontology"
                findings.append(_finding("existence", entry, f"Term {term_id} not found in {where}"))
            continue

        # Level 1b: obsolescence (the plugin's label check would only surface it
        # indirectly as an "obsolete ..." label mismatch).
        if fact["obsolete"] is None:
            fact["obsolete"] = bool(plugin.is_obsolete(term_id))
        entry["obsolete"] = fact["obsolete"]
        if fact["obsolete"]:
            entry["info_ok"] = False
            findings.append(_finding("obsolete", entry, f"Term {term_id} ({label}) is obsolete in the ontology"))
            continue
        entry["info_ok"] = True

        # Level 2: label concordance.
        if "label" in levels:
            entry["label_ok"] = False
            findings.append(_finding(
                "label", entry,
                f"Label mismatch for {term_id}: committed {entry['term_label']!r}, ontology says {label!r}",
            ))
        else:
            entry["label_ok"] = True

        # Level 3: anchor class.
        anchor = ANCHORS.get(entry["slot"])
        if anchor is not None:
            enum_name, positive, anchor_label = anchor
            if positive:
                if "anchor" in levels:
                    entry["anchor_ok"] = False
                    findings.append(_finding(
                        "anchor", entry,
                        f"{term_id} ({label}) is not a subclass of {anchor_label}, "
                        f"which {entry['slot']} requires",
                    ))
                else:
                    entry["anchor_ok"] = True
            else:
                if fact["in_biome"] is None:
                    fact["in_biome"] = bool(
                        biome_enum is not None
                        and plugin.is_value_in_enum(term_id, biome_enum, schema_view)
                    )
                in_biome = fact["in_biome"]
                entry["anchor_ok"] = not in_biome
                if in_biome:
                    findings.append(_finding(
                        "anchor", entry,
                        f"{term_id} ({label}) is a {anchor_label}; biomes belong in "
                        f"env_broad_scale, env_local_scale should be finer-grained",
                    ))
        elif "anchor" in levels:  # binding without ANCHORS entry: keep upstream verdict
            entry["anchor_ok"] = False
            findings.append(_finding("anchor", entry, levels["anchor"][0].message))

        # Level 4: submission-schema value set for the inferred package interface.
        _check_valueset(entry, valuesets, findings)

        for level, results_ in levels.items():
            if level == "other":
                for r in results_:
                    findings.append(_finding("other", entry, r.message))

    # Summary.
    summary = report["summary"]
    summary["checked"] = sum(1 for e in entries.values() if e["checked"])
    summary["unchecked"] = summary["terms"] - summary["checked"]
    summary["unchecked_prefixes"] = sorted(unchecked_prefixes)
    summary["errors"] = sum(1 for f in findings if f["severity"] == "error")
    summary["warnings"] = sum(1 for f in findings if f["severity"] == "warning")
    for f in findings:
        summary["by_level"][f["level"]] = summary["by_level"].get(f["level"], 0) + 1
    by_slot: dict[str, dict[str, int]] = {}
    for e in entries.values():
        s = by_slot.setdefault(e["slot"], {"terms": 0, "checked": 0, "errors": 0, "warnings": 0})
        s["terms"] += 1
        s["checked"] += int(e["checked"])
    for f in findings:
        by_slot[f["slot"]][f["severity"] + "s"] += 1
    summary["by_slot"] = by_slot

    report["findings"] = findings
    report["terms"] = list(entries.values())


# ---------------------------------------------------------------------------
# Curation-report merge and human summary
# ---------------------------------------------------------------------------


def merge_into_curation_report(curation_report: dict, validation: dict) -> int:
    """Copy the four flags into ``rows[*].validator`` for rows whose committed
    CURIE is the one that was validated. Returns the number of rows updated.

    Rows with no validated term (sentinels, unset slots) are left untouched, as
    are rows where a curator has since committed a *different* CURIE than the
    deliverable carried — the flags describe a specific term, never the row.
    Nothing happens unless ``validation["status"] == "ok"``.
    """
    if validation.get("status") != STATUS_OK:
        return 0
    by_key = {(t["biosample_id"], t["slot"]): t for t in validation.get("terms", [])}
    updated = 0
    for row in curation_report.get("rows", []):
        term = by_key.get((row.get("biosample_id"), row.get("slot")))
        if term is None:
            continue
        committed = row.get("committed_curie")
        if committed and committed != term["term_id"]:
            continue
        validator = row.get("validator")
        if not isinstance(validator, dict):
            validator = {}
            row["validator"] = validator
        for flag in FLAGS:
            validator[flag] = term[flag]
        updated += 1
    return updated


def format_summary(validation: dict, *, max_findings: int = 20) -> str:
    """Multi-line, human-readable summary (shared by the CLI and the pipeline)."""
    status = validation.get("status")
    summary = validation.get("summary") or {}
    lines: list[str] = []
    if status != STATUS_OK:
        lines.append(f"Term validation {status}: {validation.get('reason')}")
        if summary.get("terms"):
            lines.append(f"  {summary['terms']} term(s) were NOT checked.")
        return "\n".join(lines)

    parts = [
        f"{summary['checked']} term(s) checked",
        f"{summary['errors']} error(s)",
        f"{summary['warnings']} warning(s)",
    ]
    if summary.get("unchecked"):
        prefixes = ", ".join(summary.get("unchecked_prefixes") or []) or "unconfigured prefix"
        parts.append(f"{summary['unchecked']} unchecked ({prefixes} not configured)")
    if summary.get("skipped_sentinels"):
        parts.append(f"{summary['skipped_sentinels']} ENVO:00000000 sentinel(s) skipped")
    versions = (validation.get("tool") or {}).get("ontology_versions") or {}
    if any(versions.values()):
        parts.append("against " + ", ".join(f"{p} {v}" for p, v in versions.items() if v))
    lines.append("Term validation: " + "; ".join(parts))
    by_level = {k: v for k, v in (summary.get("by_level") or {}).items() if v}
    if by_level:
        lines.append("  by level: " + ", ".join(f"{k}={v}" for k, v in by_level.items()))
    findings = validation.get("findings") or []
    for f in findings[:max_findings]:
        lines.append(f"  [{f['severity']}/{f['level']}] {f['biosample_id']} {f['slot']} {f['term_id']}: {f['message']}")
    if len(findings) > max_findings:
        lines.append(f"  … {len(findings) - max_findings} more finding(s) in the report file")
    return "\n".join(lines)
