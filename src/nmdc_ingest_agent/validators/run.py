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
  checked, never a guess) and human-readable ``notes``.
* ``findings`` — one entry per problem, with the severity from the issue-#8
  table (existence/obsolete/label = error, anchor/valueset = warning),
  independent of the ``Severity`` the upstream plugin assigns.

:func:`merge_into_curation_report` folds the flags into the curation report
without ever contradicting a curator's differing commit or hand-set flag.
"""

from __future__ import annotations

import importlib.metadata as _md
import json
import logging
import os
import re
import shutil
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
#: Marker file under the cache dir recording which ontology release each
#: prefix's caches were built from.
VERSION_MARKER = "ontology_versions.json"

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

# Slot -> (enum in term_validation.yaml, anchor CURIE, membership required?, anchor label).
# env_local_scale has no single ENVO subtree (see term_validation.yaml), so its
# rule is negative: the term must NOT be a biome.
ANCHORS: dict[str, tuple[str, str, bool, str]] = {
    "env_broad_scale": ("BiomeEnum", "ENVO:00000428", True, "biome (ENVO:00000428)"),
    "env_medium": ("EnvironmentalMaterialEnum", "ENVO:00010483", True, "environmental material (ENVO:00010483)"),
    "env_local_scale": ("BiomeEnum", "ENVO:00000428", False, "biome (ENVO:00000428)"),
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


def tool_versions() -> dict[str, Any]:
    return {
        "nmdc_ingest_agent": _version("nmdc-ingest-agent"),
        "linkml_term_validator": _version("linkml-term-validator"),
        "oaklib": _version("oaklib"),
        "linkml": _version("linkml"),
        "ontology_versions": {},
    }


def ontology_versions(plugin: Any, prefixes: set[str]) -> dict[str, Optional[str]]:
    """Best-effort ``{prefix: release}`` (e.g. ``{"ENVO": "2025-10-20"}``) for the
    prefixes whose adapters are already built, read from the adapter's
    ``owl:versionInfo`` / ``owl:versionIRI``. A curator reading the report later
    needs to know which ontology snapshot judged the terms. Never raises and
    never builds an adapter."""
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


def refresh_caches_for_versions(cache_dir: Path, versions: dict[str, Optional[str]]) -> list[str]:
    """Drop label / enum caches built from a different ontology release.

    linkml-term-validator's file caches (``<cache_dir>/<prefix>/terms.csv`` and
    ``<cache_dir>/enums/*.csv``) are not keyed by ontology version, so after an
    ENVO release a relabelled or re-parented term would keep validating against
    the old snapshot. ``ontology_versions.json`` in the cache dir records the
    release each prefix's cache was built from; when a prefix's release changes
    its label cache and every enum closure are removed. Returns the prefixes
    whose caches were cleared. A first run (no marker) clears nothing.
    """
    marker = cache_dir / VERSION_MARKER
    previous: dict[str, Any] = {}
    if marker.exists():
        try:
            previous = json.loads(marker.read_text()) or {}
        except (ValueError, OSError):
            previous = {}
    cleared: list[str] = []
    for prefix, version in versions.items():
        if not version:
            continue
        old = previous.get(prefix)
        if old and old != version:
            shutil.rmtree(cache_dir / prefix.lower(), ignore_errors=True)
            shutil.rmtree(cache_dir / "enums", ignore_errors=True)
            cleared.append(prefix)
    merged = {**previous, **{p: v for p, v in versions.items() if v}}
    if merged != previous:
        cache_dir.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(merged, indent=1, sort_keys=True) + "\n")
    return cleared


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
        # Offline with no materialized closure, the plugin says it *cannot*
        # validate; that is not a violation.
        if _context_dict(result).get("validation", "").startswith("offline"):
            return "anchor_unavailable"
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
        "prefix": _prefix(str(term.get("id") or "")),
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


def _base_config(schema: Path, oak_config: Path, offline: bool, lenient: bool) -> dict[str, Any]:
    return {
        "schema": str(schema),
        "oak_config": str(oak_config),
        "adapters": {},
        "adapter_failures": {},
        "cache_dir": None,
        "caches_cleared_for": [],
        "offline": offline,
        "lenient": lenient,
        "valuesets": None,
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
    An adapter that cannot be built (e.g. an opt-in NCBITaxon sqlite that fails
    to download) only disables checks for its own prefix; the run degrades to
    ``status: unavailable`` / ``error`` only when *no* adapter could be built.
    ``lenient`` downgrades unresolvable CURIEs to warnings (label/anchor checks
    still run). ``offline`` forbids building OAK adapters: only the file cache
    is consulted, anything not cached is reported as not found, and anchor
    checks that need an unmaterialized enum closure come back ``None``.
    ``valuesets_path=None`` disables the level-4 check.
    """
    config = _base_config(schema, oak_config, offline, lenient)
    try:
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
            return _run(
                instance, config, Validator, BindingValidationPlugin, OntologyServiceUnavailableError,
                schema=Path(schema), oak_config=Path(oak_config), cache_dir=cache_dir,
                adapters=adapters, lenient=lenient, offline=offline, valuesets_path=valuesets_path,
            )
        except OntologyServiceUnavailableError as exc:
            return _base_report(
                instance,
                status=STATUS_UNAVAILABLE,
                reason=f"ontology service unavailable; terms could not be checked ({exc})",
                config=config,
            )
    except Exception as exc:  # noqa: BLE001 — optional QC must never abort an ingest
        logger.debug("term validation failed", exc_info=True)
        reason = f"{type(exc).__name__}: {exc}"
        try:
            return _base_report(instance, status=STATUS_ERROR, reason=reason, config=config)
        except Exception:  # noqa: BLE001 — even the projection may be malformed
            return {
                "status": STATUS_ERROR, "reason": reason, "tool": tool_versions(),
                "config": config, "summary": _empty_summary(), "findings": [], "terms": [],
            }


def _run(
    instance: dict,
    config: dict,
    Validator: Any,
    BindingValidationPlugin: Any,
    OntologyServiceUnavailableError: type,
    *,
    schema: Path,
    oak_config: Path,
    cache_dir: Optional[Path],
    adapters: Optional[dict[str, str]],
    lenient: bool,
    offline: bool,
    valuesets_path: Optional[Path],
) -> dict:
    """The guarded body of :func:`run_term_validation`."""
    cache_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    config["cache_dir"] = str(cache_dir)

    if adapters is None:
        try:
            adapters = parse_adapter_spec(os.environ.get(ADAPTERS_ENV_VAR))
        except ValueError as exc:
            adapters = {}
            logger.warning("Ignoring malformed %s: %s", ADAPTERS_ENV_VAR, exc)

    # Level 4 data is optional: a missing or corrupt TSV disables the level
    # with a note rather than failing the whole pass.
    valuesets: Optional[ValueSets] = None
    if valuesets_path:
        try:
            valuesets = load_valuesets(valuesets_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("value sets unavailable (%s: %s)", type(exc).__name__, exc)
            config["valuesets"] = {"path": str(valuesets_path), "error": f"{type(exc).__name__}: {exc}"}
        if valuesets is not None:
            config["valuesets"] = {
                "path": str(valuesets_path),
                "nmdc_submission_schema_version": valuesets.schema_version,
                "generated": valuesets.generated,
            }
        elif config["valuesets"] is None:
            config["valuesets"] = {"path": str(valuesets_path), "error": "file not found"}

    config_path, effective = effective_oak_config(oak_config, adapters, cache_dir)
    config["adapters"] = effective
    configured = {p for p, a in effective.items() if a}

    plugin = BindingValidationPlugin(
        validate_labels=True,
        strict=not lenient,
        cache_dir=cache_dir,
        oak_config_path=config_path,
        offline=offline,
    )

    # Pre-flight: build the adapter for every configured prefix that actually
    # occurs in the data, so one failing opt-in adapter (a multi-GB NCBITaxon
    # download, a typo'd path) disables only its own prefix instead of taking
    # the whole run down with it. A connectivity failure is still fatal-for-
    # the-run, as upstream intends (status "unavailable").
    present = {_prefix(str((rec.get("term") or {}).get("id") or "")) for _s, _i, rec in iter_terms(instance)}
    failures: dict[str, str] = {}
    if not offline:
        for prefix in sorted(configured & present):
            try:
                if plugin.ontology.get_adapter(prefix) is None:
                    failures[prefix] = "adapter could not be built"
            except OntologyServiceUnavailableError:
                raise
            except Exception as exc:  # noqa: BLE001 — adapters raise varied errors
                failures[prefix] = f"{type(exc).__name__}: {exc}"
        for prefix in failures:
            plugin.ontology.oak_config[prefix] = ""  # explicit skip from here on
            plugin.ontology._adapter_cache.pop(prefix, None)
            configured.discard(prefix)
        config["adapter_failures"] = failures
        if failures and not (configured & present):
            raise RuntimeError(
                "no ontology adapter could be built: "
                + "; ".join(f"{p}: {why}" for p, why in failures.items())
            )

    # Ontology releases in play, and cache hygiene when a release changed.
    versions = ontology_versions(plugin, configured & present) if not offline else {}
    if versions:
        config["caches_cleared_for"] = refresh_caches_for_versions(cache_dir, versions)
    elif offline:
        marker = cache_dir / VERSION_MARKER
        if marker.exists():
            try:
                versions = {k: v for k, v in (json.loads(marker.read_text()) or {}).items()}
                config["ontology_versions_source"] = "cache marker (offline)"
            except (ValueError, OSError):
                versions = {}

    validator = Validator(schema=str(schema), validation_plugins=[plugin])
    data = {k: v for k, v in instance.items() if not k.startswith("_")}
    upstream = validator.validate(data, target_class=TARGET_CLASS)

    report = _base_report(instance, status=STATUS_OK, reason=None, config=config)
    _normalize(
        instance, upstream.results, plugin, configured, valuesets, report,
        offline=offline, lenient=lenient, adapter_failures=failures,
    )
    report["tool"]["ontology_versions"] = versions
    return report


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
    adapter_failures: Optional[dict[str, str]] = None,
) -> None:
    """Fold upstream results plus the Python-side checks into ``report``."""
    adapter_failures = adapter_failures or {}
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
            cached = {"label": plugin.get_ontology_label(term_id), "obsolete": "?", "in_biome": "?"}
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
    # Offline, membership in a dynamic enum is only decidable from a
    # materialized (.complete) closure; otherwise the answer is "unknown".
    unmaterialized = getattr(plugin, "_offline_dynamic_enum_unmaterialized", None)
    biome_undecidable = bool(
        offline and biome_enum is not None and callable(unmaterialized) and unmaterialized(biome_enum)
    )

    findings: list[dict] = []
    unchecked_prefixes: set[str] = set()

    for key, entry in entries.items():
        term_id = entry["term_id"]
        prefix = entry["prefix"]
        levels = upstream.get(key, {})

        # No prefix at all: not a CURIE, nothing to look up.
        if not prefix:
            entry["notes"].append("not a CURIE (no prefix); ontology checks skipped")
            _check_valueset(entry, valuesets, findings)
            continue

        # Unconfigured (or failed) prefix (offline mode checks every prefix
        # from the cache): no ontology-backed check is possible, but the
        # value-set check (level 4) needs no adapter, so it still runs.
        if prefix not in configured and not offline:
            unchecked_prefixes.add(prefix)
            if prefix in adapter_failures:
                entry["notes"].append(f"adapter for {prefix!r} failed ({adapter_failures[prefix]}); ontology checks skipped")
            else:
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

        # Level 1b: obsolescence. The plugin's label check would only surface
        # it indirectly as an "obsolete ..." label mismatch. is_obsolete()
        # answers None when it cannot tell (offline, or an adapter without
        # obsolescence data); OBO ontologies prefix obsolete labels with
        # "obsolete ", which is used as a fallback signal but never as proof
        # of non-obsolescence.
        if fact["obsolete"] == "?":
            verdict = plugin.is_obsolete(term_id)
            if verdict is None and str(label).lower().startswith("obsolete"):
                verdict = True
            fact["obsolete"] = verdict
        entry["obsolete"] = fact["obsolete"]
        if fact["obsolete"] is True:
            entry["info_ok"] = False
            findings.append(_finding("obsolete", entry, f"Term {term_id} ({label}) is obsolete in the ontology"))
            continue
        if fact["obsolete"] is None:
            entry["notes"].append("obsolescence could not be determined (no adapter); label carries no 'obsolete' marker")
        entry["info_ok"] = True

        # Level 2: label concordance.
        if "label" in levels:
            entry["label_ok"] = False
            upstream_label = levels["label"][0]
            if getattr(upstream_label, "type", "") == "binding_label_invalid":
                findings.append(_finding("label", entry, upstream_label.message))
            else:
                findings.append(_finding(
                    "label", entry,
                    f"Label mismatch for {term_id}: committed {entry['term_label']!r}, ontology says {label!r}",
                ))
        else:
            entry["label_ok"] = True

        # Level 3: anchor class.
        anchor = ANCHORS.get(entry["slot"])
        if anchor is not None:
            enum_name, anchor_curie, positive, anchor_label = anchor
            if positive:
                if "anchor_unavailable" in levels:
                    entry["notes"].append("anchor not checkable offline (enum closure not materialized in cache)")
                elif "anchor" in levels:
                    entry["anchor_ok"] = False
                    if term_id == anchor_curie:
                        message = (f"{term_id} ({label}) is the anchor class itself; "
                                   f"{entry['slot']} needs a more specific subclass of {anchor_label}")
                    else:
                        message = (f"{term_id} ({label}) is not a subclass of {anchor_label}, "
                                   f"which {entry['slot']} requires")
                    findings.append(_finding("anchor", entry, message))
                else:
                    entry["anchor_ok"] = True
            else:
                if term_id == anchor_curie:
                    fact["in_biome"] = True
                elif biome_undecidable:
                    fact["in_biome"] = None
                elif fact["in_biome"] == "?":
                    fact["in_biome"] = bool(
                        biome_enum is not None
                        and plugin.is_value_in_enum(term_id, biome_enum, schema_view)
                    )
                in_biome = fact["in_biome"]
                if in_biome is None:
                    entry["notes"].append("anchor not checkable offline (enum closure not materialized in cache)")
                else:
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
    """Copy the validator's verdicts into ``rows[*].validator`` for rows whose
    ``committed_curie`` is exactly the term that was validated. Returns the
    number of rows updated.

    The flags describe a specific term, never the row, so: rows with no
    validated term (sentinels, unset slots) are left alone; rows whose
    ``committed_curie`` is missing or differs from the deliverable (a curator
    rejected or re-committed the term) are left alone; and a ``None`` verdict
    ("not checked") never overwrites a value a curator set by hand (e.g. an
    NCBITaxon ``info_ok`` recorded from a ``runoak`` lookup). Nothing happens
    unless ``validation["status"] == "ok"``.
    """
    if validation.get("status") != STATUS_OK:
        return 0
    by_key = {(t["biosample_id"], t["slot"]): t for t in validation.get("terms", [])}
    updated = 0
    for row in curation_report.get("rows", []):
        term = by_key.get((row.get("biosample_id"), row.get("slot")))
        if term is None:
            continue
        if row.get("committed_curie") != term["term_id"]:
            continue
        validator = row.get("validator")
        if not isinstance(validator, dict):
            validator = {}
            row["validator"] = validator
        touched = False
        for flag in FLAGS:
            value = term.get(flag)
            if value is None and validator.get(flag) is not None:
                continue  # keep the curator's hand-set verdict
            if validator.get(flag) != value or flag not in validator:
                validator[flag] = value
                touched = True
        if touched:
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
        prefixes = ", ".join(summary.get("unchecked_prefixes") or []) or "no prefix"
        parts.append(f"{summary['unchecked']} unchecked ({prefixes} not configured)")
    if summary.get("skipped_sentinels"):
        parts.append(f"{summary['skipped_sentinels']} ENVO:00000000 sentinel(s) skipped")
    versions = (validation.get("tool") or {}).get("ontology_versions") or {}
    if any(versions.values()):
        parts.append("against " + ", ".join(f"{p} {v}" for p, v in versions.items() if v))
    lines.append("Term validation: " + "; ".join(parts))
    failures = (validation.get("config") or {}).get("adapter_failures") or {}
    for prefix, why in failures.items():
        lines.append(f"  adapter for {prefix} failed, its terms are unchecked: {why}")
    cleared = (validation.get("config") or {}).get("caches_cleared_for") or []
    if cleared:
        lines.append(f"  caches rebuilt for a new ontology release: {', '.join(cleared)}")
    by_level = {k: v for k, v in (summary.get("by_level") or {}).items() if v}
    if by_level:
        lines.append("  by level: " + ", ".join(f"{k}={v}" for k, v in by_level.items()))
    findings = validation.get("findings") or []
    for f in findings[:max_findings]:
        lines.append(f"  [{f['severity']}/{f['level']}] {f['biosample_id']} {f['slot']} {f['term_id']}: {f['message']}")
    if len(findings) > max_findings:
        lines.append(f"  … {len(findings) - max_findings} more finding(s) in the report file")
    return "\n".join(lines)
