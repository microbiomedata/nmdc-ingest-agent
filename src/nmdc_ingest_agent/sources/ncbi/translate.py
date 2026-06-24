"""
Translate an NCBI BioProject (with linked BioSamples and SRA runs)
into an NMDC-schema-compliant Database JSON file.

Usage:
    nmdc-ingest-ncbi PRJNA1452545
    nmdc-ingest-ncbi PRJNA1452545 --fetch-only
    nmdc-ingest-ncbi PRJNA1452545 --out results/my_study.json

Or as a module:
    python -m nmdc_ingest_agent.sources.ncbi PRJNA1452545
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import requests
from lxml import etree
from nmdc_schema import nmdc
from linkml_runtime.dumpers import json_dumper

from nmdc_ingest_agent import GIT_URL as INGEST_AGENT_GIT_URL, __version__ as INGEST_AGENT_VERSION
from nmdc_ingest_agent.instruments import InstrumentResolver
from nmdc_ingest_agent.sources.ncbi.mfd import MfdEnvTriadResolver
from nmdc_ingest_agent.minting import (
    Minter,
    PlaceholderMinter,
    runtime_minter_from_env,
)

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
RATE_LIMIT_DELAY = 0.35
BATCH_SIZE = 200
MAX_HTTP_ATTEMPTS = 6


def _is_missing(value: str) -> bool:
    """Treat empty strings and NCBI 'NA'/'N/A' placeholders (any case) as missing."""
    if not value:
        return True
    return value.strip().upper() in {"NA", "N/A"}


# ---------------------------------------------------------------------------
# E-utils helpers
# ---------------------------------------------------------------------------

def _eutils_get(endpoint: str, params: dict) -> bytes:
    """GET an E-utils endpoint, retrying transient network failures.

    NCBI intermittently drops connections mid-response (``ChunkedEncodingError:
    Response ended prematurely``) or returns transient 5xx, which previously
    killed an entire multi-thousand-record run. Retry up to ``MAX_HTTP_ATTEMPTS``
    times with linear backoff. Reading ``resp.content`` is inside the try because
    that is where the premature-EOF error surfaces."""
    url = f"{EUTILS_BASE}/{endpoint}"
    last_error: Optional[Exception] = None
    for attempt in range(1, MAX_HTTP_ATTEMPTS + 1):
        time.sleep(RATE_LIMIT_DELAY)
        try:
            resp = requests.get(url, params=params, timeout=120)
            resp.raise_for_status()
            return resp.content
        except requests.exceptions.RequestException as e:
            last_error = e
            if attempt < MAX_HTTP_ATTEMPTS:
                wait = 2.0 * attempt
                print(
                    f"  WARNING: NCBI {endpoint} request failed on attempt "
                    f"{attempt}/{MAX_HTTP_ATTEMPTS} ({e.__class__.__name__}); "
                    f"retrying in {wait:.0f}s"
                )
                time.sleep(wait)
                continue
            break
    raise last_error


def esearch(db: str, term: str, batch: int = 9999) -> List[str]:
    """Return all NCBI UIDs matching ``term`` in ``db``, paginating as needed.

    NCBI caps a single esearch response at ``retmax`` records (9999 is the
    practical upper bound for the JSON-free XML response we use). Earlier
    versions of this helper hardcoded ``retmax=9999`` with no pagination,
    which silently truncated results for BioProjects with more than ~10k
    matching records. Observed truncation: PRJNA1071982 has 11,995 SRA
    experiments but we were only fetching 9,999.

    Iterates ``retstart`` over the ``<Count>`` total reported by the first
    response. Each page is at most ``batch`` records.
    """
    ids: List[str] = []
    retstart = 0
    total: Optional[int] = None
    while True:
        raw = _eutils_get("esearch.fcgi", {
            "db": db,
            "term": term,
            "retmax": batch,
            "retstart": retstart,
        })
        root = etree.fromstring(raw)
        page = [el.text for el in root.findall(".//IdList/Id") if el.text]
        ids.extend(page)
        if total is None:
            count_el = root.find(".//Count")
            try:
                total = int(count_el.text) if count_el is not None and count_el.text else len(page)
            except ValueError:
                total = len(page)
        if not page or len(ids) >= total:
            break
        retstart += batch
    return ids


def efetch_xml(db: str, ids: List[str]) -> List[etree._Element]:
    """Fetch records in batches, return list of parsed XML roots."""
    roots = []
    for i in range(0, len(ids), BATCH_SIZE):
        batch = ids[i : i + BATCH_SIZE]
        raw = _eutils_get("efetch.fcgi", {
            "db": db,
            "id": ",".join(batch),
            "rettype": "xml",
            "retmode": "xml",
        })
        roots.append(etree.fromstring(raw))
    return roots


# ---------------------------------------------------------------------------
# XML parsing: BioProject
# ---------------------------------------------------------------------------

def fetch_bioproject(accession: str) -> dict:
    ids = esearch("bioproject", f"{accession}[Project Accession]")
    if not ids:
        ids = esearch("bioproject", accession)
    if not ids:
        sys.exit(f"ERROR: BioProject {accession} not found in NCBI.")

    roots = efetch_xml("bioproject", ids[:1])
    root = roots[0]
    proj = root.find(".//Project")
    if proj is None:
        proj = root.find(".//DocumentSummary")
    if proj is None:
        sys.exit(f"ERROR: Could not parse BioProject XML for {accession}.")

    title_el = proj.find(".//ProjectDescr/Title")
    desc_el = proj.find(".//ProjectDescr/Description")
    name_el = proj.find(".//ProjectDescr/Name")
    organism_el = proj.find(".//ProjectType/ProjectTypeSubmission/Target/Organism")
    target_el = proj.find(".//ProjectType/ProjectTypeSubmission/Target")

    publications = []
    for pub in proj.findall(".//ProjectDescr/Publication"):
        dbtype = pub.get("dbtype", "")
        pub_id = pub.get("id", "")
        if dbtype.lower() == "pubmed" and pub_id:
            publications.append(f"PMID:{pub_id}")
        doi_el = pub.find(".//Reference")
        if doi_el is not None and doi_el.text:
            publications.append(doi_el.text)

    org_name = ""
    if target_el is not None:
        org_name = target_el.get("organism", "")
    if organism_el is not None:
        org_label = organism_el.find("OrganismName")
        if org_label is not None and org_label.text:
            org_name = org_label.text

    return {
        "accession": accession,
        "uid": ids[0],
        "title": title_el.text if title_el is not None else "",
        "description": desc_el.text if desc_el is not None else "",
        "name": name_el.text if name_el is not None else "",
        "organism": org_name,
        "publications": publications,
    }


# ---------------------------------------------------------------------------
# XML parsing: SRA experiments + runs
# ---------------------------------------------------------------------------

def fetch_sra_experiments(bioproject_accession: str) -> List[dict]:
    ids = esearch("sra", f"{bioproject_accession}[BioProject]")
    if not ids:
        print(f"WARNING: No SRA records found for {bioproject_accession}.")
        return []

    print(f"  Found {len(ids)} SRA records.")
    roots = efetch_xml("sra", ids)

    experiments = []
    for root in roots:
        for pkg in root.findall(".//EXPERIMENT_PACKAGE"):
            exp = pkg.find("EXPERIMENT")
            run_set = pkg.find("RUN_SET")
            sample = pkg.find("SAMPLE")

            exp_accession = exp.get("accession", "") if exp is not None else ""

            instrument_el = exp.find(".//INSTRUMENT_MODEL") if exp is not None else None
            platform_el = exp.find(".//PLATFORM/*/INSTRUMENT_MODEL") if exp is not None else None
            platform_type_el = None
            if exp is not None:
                platform_parent = exp.find(".//PLATFORM")
                if platform_parent is not None and len(platform_parent) > 0:
                    platform_type_el = platform_parent[0]

            instrument_model = ""
            if instrument_el is not None and instrument_el.text:
                instrument_model = instrument_el.text
            elif platform_el is not None and platform_el.text:
                instrument_model = platform_el.text

            platform_type = ""
            if platform_type_el is not None:
                platform_type = platform_type_el.tag

            lib_desc = exp.find(".//LIBRARY_DESCRIPTOR") if exp is not None else None
            library_strategy = ""
            library_source = ""
            library_selection = ""
            library_layout = ""
            library_name = ""
            if lib_desc is not None:
                ls = lib_desc.find("LIBRARY_STRATEGY")
                library_strategy = ls.text if ls is not None else ""
                lsrc = lib_desc.find("LIBRARY_SOURCE")
                library_source = lsrc.text if lsrc is not None else ""
                lsel = lib_desc.find("LIBRARY_SELECTION")
                library_selection = lsel.text if lsel is not None else ""
                ll = lib_desc.find("LIBRARY_LAYOUT")
                if ll is not None and len(ll) > 0:
                    library_layout = ll[0].tag
                ln = lib_desc.find("LIBRARY_NAME")
                library_name = ln.text if ln is not None and ln.text else ""

            # Free-text DESIGN_DESCRIPTION; MFD encodes the protocol DOI and the
            # amplicon target gene here (see _extract_protocol_url / _extract_target_gene).
            design_el = exp.find(".//DESIGN/DESIGN_DESCRIPTION") if exp is not None else None
            design_description = (
                design_el.text if design_el is not None and design_el.text else ""
            )

            biosample_accession = ""
            if sample is not None:
                for xref in sample.findall(".//EXTERNAL_ID"):
                    if xref.get("namespace", "").upper() == "BIOSAMPLE":
                        biosample_accession = xref.text or ""
                        break
                if not biosample_accession:
                    for sid in sample.findall(".//IDENTIFIERS/EXTERNAL_ID"):
                        if sid.get("namespace", "").upper() == "BIOSAMPLE":
                            biosample_accession = sid.text or ""
                            break

            runs = []
            if run_set is not None:
                for run_el in run_set.findall("RUN"):
                    run_acc = run_el.get("accession", "")
                    total_bases = run_el.get("total_bases", "")
                    total_spots = run_el.get("total_spots", "")
                    runs.append({
                        "accession": run_acc,
                        "total_bases": total_bases,
                        "total_spots": total_spots,
                    })

            sample_title = ""
            if sample is not None:
                t = sample.find("TITLE")
                sample_title = t.text if t is not None else ""

            experiments.append({
                "experiment_accession": exp_accession,
                "biosample_accession": biosample_accession,
                "sample_title": sample_title,
                "instrument_model": instrument_model,
                "platform_type": platform_type,
                "library_strategy": library_strategy,
                "library_source": library_source,
                "library_selection": library_selection,
                "library_layout": library_layout,
                "library_name": library_name,
                "design_description": design_description,
                "runs": runs,
            })

    return experiments


# ---------------------------------------------------------------------------
# XML parsing: BioSamples
# ---------------------------------------------------------------------------

def fetch_linked_biosample_uids(
    bioproject_uid: str, max_attempts: int = 5
) -> Optional[List[str]]:
    """Return BioSample UIDs linked to a BioProject via elink.

    NCBI's bp→biosample elink endpoint intermittently returns HTTP 200 with a
    ``<ERROR>`` body containing ``TXCLIENT(CException::eUnknown) ... readAll()``
    failures — observed flapping at ~50% rate on large BioProjects. Empirically
    retrying with a short backoff recovers quickly, so attempt up to
    ``max_attempts`` times before giving up. Returns None if every attempt
    fails so callers can distinguish 'no biosamples' from 'lookup failed' and
    fall back to the SRA-derived BioSample set.
    """
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        try:
            raw = _eutils_get("elink.fcgi", {
                "dbfrom": "bioproject",
                "db": "biosample",
                "id": bioproject_uid,
                "linkname": "bioproject_biosample_all",
            })
            root = etree.fromstring(raw)
            err_el = root.find(".//ERROR")
            if err_el is not None and err_el.text:
                last_error = err_el.text.strip().splitlines()[0]
                if attempt < max_attempts:
                    time.sleep(2.0 * attempt)
                    continue
                print(
                    f"  WARNING: elink bioproject→biosample returned error "
                    f"after {attempt} attempts: {last_error}"
                )
                return None
            uids = [el.text for el in root.findall(".//LinkSetDb/Link/Id") if el.text]
            if attempt > 1:
                print(f"  elink bioproject→biosample recovered on attempt {attempt}")
            return uids
        except Exception as e:
            last_error = str(e)
            if attempt < max_attempts:
                time.sleep(2.0 * attempt)
                continue
            print(
                f"  WARNING: elink bioproject→biosample call failed after "
                f"{attempt} attempts: {last_error}"
            )
            return None
    return None


def _fetch_biosample_records(ids: List[str]) -> List[dict]:
    """Fetch and parse BioSample records for the given UIDs or accessions."""
    if not ids:
        return []

    print(f"  Fetching {len(ids)} BioSample records...")
    roots = efetch_xml("biosample", ids)

    samples = []
    for root in roots:
        for bs in root.findall(".//BioSample"):
            accession = bs.get("accession", "")
            attrs = {}
            for attr in bs.findall(".//Attribute"):
                key = attr.get("harmonized_name") or attr.get("attribute_name", "")
                if key:
                    attrs[key] = attr.text or ""

            sample_name = ""
            for id_el in bs.findall(".//Ids/Id"):
                if id_el.get("db_label") == "Sample name" and id_el.text:
                    sample_name = id_el.text.strip()
                    break

            title_el = bs.find(".//Description/Title")
            organism_el = bs.find(".//Description/Organism")
            org_name = ""
            taxonomy_id = ""
            if organism_el is not None:
                org_name = organism_el.get("taxonomy_name", "")
                taxonomy_id = organism_el.get("taxonomy_id", "")

            package_el = bs.find(".//Package")
            package = package_el.text if package_el is not None else ""

            model_els = bs.findall(".//Model")
            models = [m.text for m in model_els if m.text]

            samples.append({
                "accession": accession,
                "title": title_el.text if title_el is not None else "",
                "sample_name": sample_name,
                "organism": org_name,
                "taxonomy_id": taxonomy_id,
                "package": package,
                "models": models,
                "attributes": attrs,
            })

    return samples


def fetch_biosamples(accessions: List[str]) -> List[dict]:
    """Fetch BioSample records by accession (e.g. SAMN*).

    Passes accessions directly to efetch (db=biosample accepts accession
    strings as ids). Earlier versions used an esearch round-trip to
    translate accessions to internal UIDs, but that built ``OR``-joined
    query strings that NCBI rejects with HTTP 414 for BioProjects with
    >~150 linked BioSamples. ``efetch_xml`` already batches the id list,
    so the comma-joined ``id=`` URL stays well under NCBI's limit.
    """
    if not accessions:
        return []
    return _fetch_biosample_records(list(accessions))


# ---------------------------------------------------------------------------
# Lat/lon parsing
# ---------------------------------------------------------------------------

_MISSING_VALUES = {"", "missing", "not collected", "not applicable", "not provided", "n/a", "na", "unknown"}


def _parse_quantity(raw: str, default_unit: Optional[str] = None) -> Optional["nmdc.QuantityValue"]:
    """Parse a string like '0.2 - 0.3 m', '12.5 cm', or '0 m' into an NMDC QuantityValue.

    Range values populate has_minimum_numeric_value/has_maximum_numeric_value;
    scalar values populate has_numeric_value. Missing-value sentinels return None.
    """
    if not raw:
        return None
    stripped = raw.strip()
    if stripped.lower() in _MISSING_VALUES:
        return None

    unit_match = re.search(r"([A-Za-zµ°%][A-Za-zµ°%/^0-9\-\.]*)\s*$", stripped)
    unit = unit_match.group(1) if unit_match else default_unit
    numeric_part = stripped[: unit_match.start()].strip() if unit_match else stripped

    range_match = re.match(
        r"([+-]?\d+\.?\d*)\s*(?:-|–|to)\s*([+-]?\d+\.?\d*)\s*$",
        numeric_part,
    )
    if range_match:
        return nmdc.QuantityValue(
            has_raw_value=stripped,
            has_unit=unit,
            has_minimum_numeric_value=float(range_match.group(1)),
            has_maximum_numeric_value=float(range_match.group(2)),
            type="nmdc:QuantityValue",
        )

    scalar_match = re.match(r"([+-]?\d+\.?\d*)\s*$", numeric_part)
    if scalar_match:
        return nmdc.QuantityValue(
            has_raw_value=stripped,
            has_unit=unit,
            has_numeric_value=float(scalar_match.group(1)),
            type="nmdc:QuantityValue",
        )

    return nmdc.QuantityValue(
        has_raw_value=stripped,
        type="nmdc:QuantityValue",
    )


def parse_lat_lon(raw: str) -> Optional[Tuple[float, float]]:
    """Parse lat/lon strings like '34.27 N 108.08 E' or '34.27, -108.08'."""
    m = re.match(
        r"([+-]?\d+\.?\d*)\s*([NSns])[\s,]+([+-]?\d+\.?\d*)\s*([EWew])",
        raw.strip(),
    )
    if m:
        lat = float(m.group(1))
        if m.group(2).upper() == "S":
            lat = -lat
        lon = float(m.group(3))
        if m.group(4).upper() == "W":
            lon = -lon
        return (lat, lon)

    m2 = re.match(r"([+-]?\d+\.?\d*)[\s,]+([+-]?\d+\.?\d*)", raw.strip())
    if m2:
        return (float(m2.group(1)), float(m2.group(2)))

    return None


# ---------------------------------------------------------------------------
# NMDC object builders
# ---------------------------------------------------------------------------

_DOI_PREFIX_RE = re.compile(r"^(?:doi:|https?://(?:dx\.)?doi\.org/)", re.IGNORECASE)


def _to_doi_curie(raw: str) -> Optional[str]:
    """Normalize a DOI string into ``doi:<value>`` CURIE form.

    NCBI's BioProject ``<Publication>/<Reference>`` element returns DOIs in
    various shapes — bare (``10.1038/...``), prefixed (``doi:10.1038/...``),
    or as full URLs (``https://doi.org/10.1038/...``). All forms collapse
    to the CURIE form ``doi:<bare-value>`` required by the NMDC schema's
    ``Doi.doi_value`` slot. Returns None if the input does not contain a
    DOI-shaped value (e.g. PMID strings, which the caller filters out).
    """
    if not raw:
        return None
    stripped = raw.strip()
    bare = _DOI_PREFIX_RE.sub("", stripped)
    # DOIs start with "10." per the DOI handbook
    if not bare.startswith("10."):
        return None
    return f"doi:{bare}"


def _build_provenance_metadata(now: datetime) -> nmdc.ProvenanceMetadata:
    return nmdc.ProvenanceMetadata(
        add_date=now,
        mod_date=now,
        source_system_of_record=nmdc.SourceSystemEnum.NCBI.text,
        git_url=INGEST_AGENT_GIT_URL,
        version=INGEST_AGENT_VERSION,
        type="nmdc:ProvenanceMetadata",
    )


def build_study(project_data: dict, study_id: str, now: datetime) -> nmdc.Study:
    accession = project_data["accession"]

    # NCBI BioProject <Publication> elements emit either PMID strings or
    # DOI strings (see fetch_bioproject). Map the DOI-shaped entries onto
    # NMDC's associated_dois slot. PMIDs aren't DOIs; a separate curation
    # step would have to PMID->DOI resolve via NCBI's API, out of scope here.
    associated_dois: list[nmdc.Doi] = []
    seen: set[str] = set()
    for pub in project_data.get("publications") or []:
        curie = _to_doi_curie(pub)
        if curie is None or curie in seen:
            continue
        seen.add(curie)
        associated_dois.append(nmdc.Doi(
            doi_value=curie,
            doi_category=nmdc.DoiCategoryEnum.publication_doi.text,
            type="nmdc:Doi",
        ))

    return nmdc.Study(
        id=study_id,
        name=project_data["title"],
        title=project_data["title"],
        description=project_data["description"],
        study_category=nmdc.StudyCategoryEnum.research_study.text,
        insdc_bioproject_identifiers=[f"bioproject:{accession}"],
        associated_dois=associated_dois or None,
        type="nmdc:Study",
        provenance_metadata=_build_provenance_metadata(now),
    )


def build_biosample(
    sample_data: dict,
    study_id: str,
    biosample_id: str,
    now: datetime,
    mfd_resolver: Optional[MfdEnvTriadResolver] = None,
) -> nmdc.Biosample:
    accession = sample_data["accession"]
    attrs = sample_data["attributes"]

    env_broad = None
    env_local = None
    env_medium = None

    raw_broad = attrs.get("env_broad_scale", "")
    raw_local = attrs.get("env_local_scale", "")
    raw_medium = attrs.get("env_medium", "")

    def _parse_envo_term(raw: str) -> nmdc.ControlledIdentifiedTermValue:
        """Always returns a schema-valid term. Missing values and unrecognized
        free text produce an ENVO:00000000 placeholder that flags the slot for
        manual curation; has_raw_value preserves the submitter string when one
        was provided."""
        stripped = (raw or "").strip()
        if not stripped or stripped.lower() in _MISSING_VALUES:
            return nmdc.ControlledIdentifiedTermValue(
                term=nmdc.OntologyClass(
                    id="ENVO:00000000",
                    name="(not provided)",
                    type="nmdc:OntologyClass",
                ),
                has_raw_value=stripped,
                type="nmdc:ControlledIdentifiedTermValue",
            )
        envo_match = re.search(r"(ENVO[:\s_]+\d+)", stripped, re.IGNORECASE)
        if envo_match:
            curie = envo_match.group(1).replace(" ", ":").replace("_", ":")
            curie = re.sub(r"ENVO(\d)", r"ENVO:\1", curie)
            label = re.sub(r"\s*\[.*?\]\s*", "", stripped).strip() or stripped
            return nmdc.ControlledIdentifiedTermValue(
                term=nmdc.OntologyClass(id=curie, name=label, type="nmdc:OntologyClass"),
                type="nmdc:ControlledIdentifiedTermValue",
            )
        return nmdc.ControlledIdentifiedTermValue(
            term=nmdc.OntologyClass(
                id="ENVO:00000000",
                name=stripped,
                type="nmdc:OntologyClass",
            ),
            has_raw_value=stripped,
            type="nmdc:ControlledIdentifiedTermValue",
        )

    env_broad = _parse_envo_term(raw_broad)
    env_local = _parse_envo_term(raw_local)
    env_medium = _parse_envo_term(raw_medium)

    # MicroFlora Danica biosamples carry no usable env-triad in NCBI; resolve
    # them from the v2 MFDO crosswalk by barcode. Only matched slots override the
    # sentinel; non-MFD samples and unmatched slots keep the placeholder above.
    if mfd_resolver is not None:
        resolved = mfd_resolver.resolve(sample_data)
        if resolved:
            if "env_broad_scale" in resolved:
                env_broad = resolved["env_broad_scale"]
            if "env_local_scale" in resolved:
                env_local = resolved["env_local_scale"]
            if "env_medium" in resolved:
                env_medium = resolved["env_medium"]

    lat_lon = None
    raw_latlon = attrs.get("lat_lon", "")
    parsed = parse_lat_lon(raw_latlon) if raw_latlon else None
    if parsed:
        lat_lon = nmdc.GeolocationValue(
            latitude=nmdc.DecimalDegree(parsed[0]),
            longitude=nmdc.DecimalDegree(parsed[1]),
            type="nmdc:GeolocationValue",
        )

    collection_date = None
    raw_date = attrs.get("collection_date", "")
    if raw_date:
        collection_date = nmdc.TimestampValue(
            has_raw_value=raw_date, type="nmdc:TimestampValue"
        )

    depth = _parse_quantity(attrs.get("depth", ""), default_unit="m")

    elev = None
    raw_elev = attrs.get("elev", "")
    if raw_elev:
        elev_match = re.match(r"([+-]?\d+\.?\d*)", raw_elev)
        if elev_match:
            elev = float(elev_match.group(1))

    geo_loc_name = None
    raw_geo = attrs.get("geo_loc_name", "")
    if raw_geo:
        geo_loc_name = nmdc.TextValue(has_raw_value=raw_geo, type="nmdc:TextValue")

    organism_name = sample_data.get("organism", "")
    taxonomy_id = sample_data.get("taxonomy_id", "")
    samp_taxon_id = None
    if taxonomy_id:
        samp_taxon_id = nmdc.ControlledIdentifiedTermValue(
            term=nmdc.OntologyClass(
                id=f"NCBITaxon:{taxonomy_id}",
                name=organism_name,
                type="nmdc:OntologyClass",
            ),
            type="nmdc:ControlledIdentifiedTermValue",
        )

    env_package = None
    raw_package = (sample_data.get("package") or "").strip()
    if raw_package and raw_package.lower() not in _MISSING_VALUES:
        env_package = nmdc.TextValue(
            has_raw_value=raw_package, type="nmdc:TextValue"
        )

    def _clean_str_attr(name: str) -> Optional[str]:
        raw = (attrs.get(name, "") or "").strip()
        if not raw or raw.lower() in _MISSING_VALUES:
            return None
        return raw

    habitat = _clean_str_attr("habitat")
    host_name = _clean_str_attr("host")

    title = sample_data.get("title", "")
    sample_name = sample_data.get("sample_name", "")
    if not _is_missing(title):
        biosample_name = title
    elif sample_name:
        biosample_name = sample_name
    else:
        biosample_name = accession

    biosample = nmdc.Biosample(
        id=biosample_id,
        name=biosample_name,
        samp_name=sample_name or None,
        env_broad_scale=env_broad,
        env_local_scale=env_local,
        env_medium=env_medium,
        env_package=env_package,
        lat_lon=lat_lon,
        collection_date=collection_date,
        depth=depth,
        elev=elev,
        geo_loc_name=geo_loc_name,
        habitat=habitat,
        host_name=host_name,
        samp_taxon_id=samp_taxon_id,
        associated_studies=[study_id],
        insdc_biosample_identifiers=[f"biosample:{accession}"],
        type="nmdc:Biosample",
        provenance_metadata=_build_provenance_metadata(now),
    )

    return biosample


def _resolve_analyte_category(library_source: str, library_strategy: str) -> str:
    """Map an SRA ``LIBRARY_SOURCE`` / ``LIBRARY_STRATEGY`` pair to an NMDC
    ``analyte_category`` (a ``NucleotideSequencingEnum`` permissible value).

    Only the combinations NMDC can map unambiguously are accepted; any other
    pair raises ``ValueError`` so the caller can exclude the experiment rather
    than silently mislabel it. The previous implementation defaulted unmatched
    pairs to ``metagenome`` and, worse, ordered its checks so that AMPLICON +
    METAGENOMIC experiments matched the metagenome branch first — mislabeling
    all amplicon data as metagenome (issue #46). It also emitted ``metabarcode``,
    which is not a permissible ``analyte_category`` value.

    Mappings (case-insensitive on both inputs):
      - AMPLICON + METAGENOMIC      -> amplicon_sequencing_assay
      - WGS + METAGENOMIC           -> metagenome
      - RNA-Seq + METATRANSCRIPTOMIC -> metatranscriptome
    """
    source = (library_source or "").strip().upper()
    strategy = (library_strategy or "").strip().upper()
    if strategy == "AMPLICON" and source == "METAGENOMIC":
        return "amplicon_sequencing_assay"
    if strategy == "WGS" and source == "METAGENOMIC":
        return "metagenome"
    if strategy == "RNA-SEQ" and source == "METATRANSCRIPTOMIC":
        return "metatranscriptome"
    raise ValueError(
        f"No analyte_category mapping for SRA library_source="
        f"{library_source!r} / library_strategy={library_strategy!r}"
    )


def _enum_value_texts(enum_cls) -> set:
    """Permissible-value texts of a generated LinkML enum (excludes the
    MissingRequiredField sentinel). Used so the valid value sets come from the
    schema enumeration rather than being hardcoded."""
    return {
        v.text
        for v in vars(enum_cls).values()
        if getattr(v, "text", None) and v.text != "MissingRequiredField"
    }


_LIB_LAYOUT_VALUES = _enum_value_texts(nmdc.LibLayoutEnum)


def _lib_layout(library_layout: str) -> Optional[str]:
    """Map an SRA LIBRARY_LAYOUT tag (PAIRED/SINGLE) to a LibLayoutEnum value."""
    v = (library_layout or "").strip().lower()
    return v if v in _LIB_LAYOUT_VALUES else None


# A DOI embedded in the SRA DESIGN_DESCRIPTION free text — MFD's WGS designs read
# "Miniaturized metagenome DNA preps see https://doi.org/10.1101/2023.09.04.556179".
_DESIGN_DOI_RE = re.compile(
    r"(?:https?://(?:dx\.)?doi\.org/|\bdoi:\s*)(10\.\d{4,}/\S+)", re.IGNORECASE
)


def _extract_protocol_url(design_description: str) -> Optional[str]:
    """Return a protocol DOI URL parsed from the SRA DESIGN_DESCRIPTION, if any.

    The submitter records the library-prep protocol as a DOI in the free-text
    design description; we surface it as a ``protocol_link`` rather than
    hardcoding a project-specific URL. None when no DOI is present (e.g. MFD's
    amplicon designs, which describe primers but cite no DOI)."""
    if not design_description:
        return None
    m = _DESIGN_DOI_RE.search(design_description)
    if not m:
        return None
    bare = m.group(1).rstrip(".,;)")
    return f"https://doi.org/{bare}"


# Explicit rRNA-gene tokens in the DESIGN_DESCRIPTION; "<n>S" maps to "<n>S_rRNA".
_GENE_TOKEN_RE = re.compile(r"\b(16S|18S|23S|28S)\b", re.IGNORECASE)
# An "rRNA operon" amplicon names no explicit gene number; the small-subunit (SSU)
# rRNA its forward primer anchors on is domain-specific — 16S for bacteria/archaea,
# 18S for eukaryotes (e.g. MFD's pb_bacoperon vs pb_eukoperon designs).
_RRNA_OPERON_RE = re.compile(r"rRNA\s+operon", re.IGNORECASE)
_PROKARYOTIC_RE = re.compile(r"\b(?:bacterial|archaeal|prokaryotic)\b", re.IGNORECASE)
_EUKARYOTIC_RE = re.compile(r"\beukaryotic\b", re.IGNORECASE)
_TARGET_GENE_VALUES = _enum_value_texts(nmdc.TargetGeneEnum)


def _extract_target_gene(design_description: str) -> Optional[str]:
    """Map an rRNA target named in the SRA DESIGN_DESCRIPTION to a TargetGeneEnum
    value.

    An explicit gene token ("16S"/"18S"/"23S"/"28S") wins. Otherwise, a
    non-specific "rRNA operon" resolves to the domain's SSU rRNA gene — 16S for
    bacterial/archaeal, 18S for eukaryotic. Returns None when no rRNA target is
    named (e.g. shotgun WGS), and also when more than one distinct gene is named
    or an operon's domain is unstated — in those ambiguous cases we warn (for the
    multi-gene case) and leave ``target_gene`` unset rather than guessing."""
    if not design_description:
        return None
    found = {
        f"{m.group(1).upper()}_rRNA" for m in _GENE_TOKEN_RE.finditer(design_description)
    }
    if not found and _RRNA_OPERON_RE.search(design_description):
        if _EUKARYOTIC_RE.search(design_description):
            found = {"18S_rRNA"}
        elif _PROKARYOTIC_RE.search(design_description):
            found = {"16S_rRNA"}
    found &= _TARGET_GENE_VALUES
    if len(found) == 1:
        return next(iter(found))
    if len(found) > 1:
        print(
            f"  WARNING: DESIGN_DESCRIPTION names multiple target genes "
            f"{sorted(found)}; leaving target_gene unset: {design_description!r}"
        )
    return None


def _library_key(experiment: dict) -> tuple:
    """Identity of the *unique library* an SRA experiment represents.

    Multiple SRA experiments can describe the same physical library (e.g. one
    library re-sequenced across runs/lanes under distinct experiment
    accessions). They share the SRA library name *and* descriptor, so we key on
    ``(biosample, library_name, strategy, source, selection, layout)`` and build
    one Extraction/LibraryPreparation chain per key rather than per experiment.

    The descriptor is part of the key so two genuinely different preps that
    happen to reuse one library-name string (e.g. a WGS and an amplicon library
    both named after the sample) are not merged. When the SRA record has no
    library name we cannot dedup, so we fall back to the experiment accession to
    keep each experiment its own library."""
    lib = (experiment.get("library_name") or "").strip()
    lib_or_exp = lib or f"__exp__{experiment['experiment_accession']}"
    return (
        experiment["biosample_accession"],
        lib_or_exp,
        experiment.get("library_strategy", ""),
        experiment.get("library_source", ""),
        experiment.get("library_selection", ""),
        experiment.get("library_layout", ""),
    )


def build_library_records(
    library_experiments: List[dict],
    study_id: str,
    biosample_id: str,
    biosample_name: str,
    bioproject_accession: str,
    run_units: List[dict],
    extraction_id: str,
    extraction_output_id: str,
    library_preparation_id: str,
    library_output_id: str,
    manifest_ids: List[str],
    now: datetime,
) -> dict:
    """Build the material-processing chain + per-run sequencing records for one
    *unique library* (a group of SRA experiments sharing a ``_library_key``).

    NCBI does not record the wet-lab steps, but the NMDC model requires a
    NucleotideSequencing to consume a ProcessedSample rather than the Biosample
    directly. We reconstruct the canonical chain — **one Extraction and one
    LibraryPreparation per unique library** (each emitting a ProcessedSample) —
    and then emit **one NucleotideSequencing + one DataObject per SRA run**
    across all of the library's experiments:

        Biosample
          -> Extraction          (has_output: extracted-nucleic-acid ProcessedSample)
          -> LibraryPreparation   (has_output: sequencing-library ProcessedSample)
          -> NucleotideSequencing  (one per run; has_output: that run's DataObject)

    ``run_units`` is one dict per run — ``{run_acc, exp_acc, instrument_model,
    instrument_id, ns_id, do_id}`` — already minted by the caller. Runs of this
    library that share an instrument (so they share biosample + library name +
    instrument) are poolable replicates: each such group of >1 run is bound by a
    Manifest via ``DataObject.in_manifest``. ``manifest_ids`` supplies one minted
    id per such group, consumed in instrument-sorted order.

    Record names follow the MFD example-data conventions; the LibraryPreparation
    carries the SRA descriptor (strategy/source/selection/layout) and the library
    ProcessedSample is named after the SRA library name."""

    rep = library_experiments[0]

    # Transcriptomic libraries extract RNA; everything else DNA. NCBI's SRA
    # data_object_type is uniform ("SRA toolkit-accessible sequence data");
    # the nucleic acid only drives extraction_targets and the record names.
    source_upper = (rep.get("library_source") or "").upper()
    nucleic_acid = "RNA" if "TRANSCRIPTOMIC" in source_upper else "DNA"

    # Eligibility (in build_nmdc_database) has already verified this pair maps.
    analyte_category = _resolve_analyte_category(
        rep.get("library_source", ""), rep.get("library_strategy", "")
    )
    # protocol DOI and amplicon target gene are parsed from the SRA
    # DESIGN_DESCRIPTION (not hardcoded); both None when the design names neither.
    design_description = rep.get("design_description", "")
    target_gene = _extract_target_gene(design_description)
    protocol_url = _extract_protocol_url(design_description)

    # --- Extraction: Biosample -> extracted nucleic-acid ProcessedSample -------
    extraction = nmdc.Extraction(
        id=extraction_id,
        name=f"{nucleic_acid} extraction process for {biosample_name}",
        has_input=[biosample_id],
        has_output=[extraction_output_id],
        extraction_targets=[nucleic_acid],
        type="nmdc:Extraction",
    )
    extraction_output = nmdc.ProcessedSample(
        id=extraction_output_id,
        name=f"Extracted {nucleic_acid} for {biosample_name}",
        type="nmdc:ProcessedSample",
    )

    # --- LibraryPreparation: extracted nucleic acid -> library ProcessedSample --
    protocol_link = (
        nmdc.Protocol(url=protocol_url, type="nmdc:Protocol") if protocol_url else None
    )
    library_preparation = nmdc.LibraryPreparation(
        id=library_preparation_id,
        name=f"Library preparation process for {biosample_name}",
        has_input=[extraction_output_id],
        has_output=[library_output_id],
        library_strategy=(rep.get("library_strategy") or None),
        library_source=(rep.get("library_source") or None),
        library_selection=(rep.get("library_selection") or None),
        lib_layout=_lib_layout(rep.get("library_layout", "")),
        target_gene=target_gene,
        protocol_link=protocol_link,
        type="nmdc:LibraryPreparation",
    )
    library_name = (rep.get("library_name") or "").strip()
    library_output = nmdc.ProcessedSample(
        id=library_output_id,
        name=library_name or f"Sequencing library for {biosample_name}",
        description=f"Library for sequencing for {biosample_name}",
        type="nmdc:ProcessedSample",
    )

    # --- Manifests: group this library's runs by instrument; >1 run = poolable
    #     replicates sharing (biosample, library name, instrument) -------------
    runs_by_instrument: dict[str, list] = {}
    for ru in run_units:
        runs_by_instrument.setdefault(ru["instrument_model"], []).append(ru)
    manifest_id_iter = iter(manifest_ids)
    do_manifest: dict[str, str] = {}
    manifests = []
    label = library_name or biosample_name
    for instrument in sorted(runs_by_instrument):
        group = runs_by_instrument[instrument]
        if len(group) > 1:
            mid = next(manifest_id_iter)
            manifests.append(nmdc.Manifest(
                id=mid,
                name=f"Sequencing runs for {label} on {instrument}",
                manifest_category=nmdc.ManifestCategoryEnum.poolable_replicates.text,
                type="nmdc:Manifest",
            ))
            for ru in group:
                do_manifest[ru["do_id"]] = mid

    # --- Per-run NucleotideSequencing + DataObject -----------------------------
    nuc_seqs = []
    data_objects = []
    for ru in run_units:
        run_acc, exp_acc = ru["run_acc"], ru["exp_acc"]
        ns_id, do_id = ru["ns_id"], ru["do_id"]
        mid = do_manifest.get(do_id)
        data_objects.append(nmdc.DataObject(
            id=do_id,
            name=f"Data file for run accession {run_acc}",
            description=f"Data file for run accession {run_acc}",
            data_category=nmdc.DataCategoryEnum.instrument_data.text,
            data_object_type="SRA toolkit-accessible sequence data",
            insdc_run_identifiers=[f"insdc.run:{run_acc}"],
            was_generated_by=ns_id,
            in_manifest=[mid] if mid else None,
            type="nmdc:DataObject",
        ))
        nuc_seqs.append(nmdc.NucleotideSequencing(
            id=ns_id,
            name=f"Run {run_acc} for experiment {exp_acc} - {biosample_name}",
            has_input=[library_output_id],
            has_output=[do_id],
            associated_studies=[study_id],
            instrument_used=[ru["instrument_id"]] if ru["instrument_id"] else [],
            analyte_category=analyte_category,
            insdc_experiment_identifiers=[f"insdc.sra:{exp_acc}"],
            insdc_bioproject_identifiers=[f"bioproject:{bioproject_accession}"],
            type="nmdc:NucleotideSequencing",
            provenance_metadata=_build_provenance_metadata(now),
        ))

    return {
        "nucleotide_sequencings": nuc_seqs,
        "data_objects": data_objects,
        "material_processings": [extraction, library_preparation],
        "processed_samples": [extraction_output, library_output],
        "manifests": manifests,
    }


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def fetch_all(accession: str) -> dict:
    print(f"Fetching BioProject {accession}...")
    project = fetch_bioproject(accession)
    print(f"  Title: {project['title']}")

    print("Fetching SRA experiments...")
    experiments = fetch_sra_experiments(accession)

    sra_biosample_accessions = {
        e["biosample_accession"] for e in experiments if e["biosample_accession"]
    }
    print(f"  Found {len(sra_biosample_accessions)} unique BioSamples across SRA records.")

    print("Querying elink for all BioSamples linked to BioProject...")
    linked_uids = fetch_linked_biosample_uids(project["uid"])

    if linked_uids is not None:
        print(f"  elink returned {len(linked_uids)} BioSample UIDs.")
        print("Fetching BioSamples by UID (covers both sequenced and unsequenced samples)...")
        biosamples = _fetch_biosample_records(linked_uids)
        linked_accessions = {s["accession"] for s in biosamples if s.get("accession")}

        missing_from_sra = linked_accessions - sra_biosample_accessions
        missing_from_elink = sra_biosample_accessions - linked_accessions

        if missing_from_sra:
            print(
                f"  NOTE: {len(missing_from_sra)} BioSample(s) under this BioProject "
                f"have no SRA submission yet (carried through without a DataGeneration)."
            )
        if missing_from_elink:
            print(
                f"  WARNING: {len(missing_from_elink)} BioSample(s) referenced by SRA "
                f"were not returned by elink — fetching them separately: "
                f"{sorted(missing_from_elink)}"
            )
            extras = fetch_biosamples(sorted(missing_from_elink))
            biosamples.extend(extras)
    else:
        print(
            "  elink unavailable — falling back to SRA-derived BioSample set only. "
            "Re-run later for a complete list."
        )
        print("Fetching BioSamples...")
        biosamples = fetch_biosamples(sorted(sra_biosample_accessions))

    print(f"  Retrieved {len(biosamples)} BioSample records.")

    return {
        "bioproject": project,
        "biosamples": biosamples,
        "sra_experiments": experiments,
    }


_MAG_PACKAGE_PREFIXES = ("MIMAG", "MISAG")


def _is_mag_package(package: str) -> bool:
    """Return True if the MIxS package indicates a single-organism genome
    assembly rather than an environmental sample.

    MIMAG = Minimum Information about a Metagenome-Assembled Genome.
    MISAG = Minimum Information about a Single Amplified Genome.

    Records using these packages represent derived genome assemblies (a
    single inferred organism per record, with a concrete ``samp_taxon_id``),
    not the environmental samples the NMDC Biosample class models. They are
    out of scope for environmental-sample ingest.
    """
    p = (package or "").strip()
    return any(p.startswith(prefix) for prefix in _MAG_PACKAGE_PREFIXES)


def build_nmdc_database(
    data: dict,
    minter: Minter,
    resolver: InstrumentResolver,
    mfd_resolver: Optional[MfdEnvTriadResolver] = None,
) -> nmdc.Database:
    project = data["bioproject"]
    raw_biosamples = data["biosamples"]
    experiments = data["sra_experiments"]

    now = datetime.now(tz=timezone.utc)

    biosamples: list[dict] = []
    excluded_packages: dict[str, int] = {}
    for sample in raw_biosamples:
        pkg = sample.get("package", "") or ""
        if _is_mag_package(pkg):
            excluded_packages[pkg] = excluded_packages.get(pkg, 0) + 1
            continue
        biosamples.append(sample)

    if excluded_packages:
        total_excluded = sum(excluded_packages.values())
        per_pkg = ", ".join(f"{pkg}={n}" for pkg, n in sorted(excluded_packages.items()))
        print(
            f"  Excluded {total_excluded} BioSample(s) using MAG-only MIxS "
            f"packages ({per_pkg}); NMDC Biosample is for environmental samples."
        )

    [study_id] = minter.mint("nmdc:Study", 1)
    study = build_study(project, study_id, now)

    biosample_ids = (
        minter.mint("nmdc:Biosample", len(biosamples)) if biosamples else []
    )
    biosample_acc_to_id: dict[str, str] = {}
    biosample_acc_to_name: dict[str, str] = {}
    nmdc_biosamples: list[nmdc.Biosample] = []
    for sample, biosample_id in zip(biosamples, biosample_ids):
        bs = build_biosample(sample, study_id, biosample_id, now, mfd_resolver)
        nmdc_biosamples.append(bs)
        biosample_acc_to_id[sample["accession"]] = bs.id
        # Name downstream material-processing records after the biosample's
        # stable sample identifier (samp_name, e.g. the MFD barcode), falling
        # back to the display name then accession when samp_name is absent.
        biosample_acc_to_name[sample["accession"]] = (
            bs.samp_name or bs.name or sample["accession"]
        )

    kept_experiments: list[dict] = []
    skip_warnings: list[str] = []
    for exp in experiments:
        bs_acc = exp["biosample_accession"]
        if bs_acc not in biosample_acc_to_id:
            skip_warnings.append(
                f"SRA experiment {exp['experiment_accession']} references "
                f"BioSample {bs_acc} which was not fetched. Skipping."
            )
            continue
        kept_experiments.append(exp)

    # Resolve each distinct SRA instrument-model string to an *existing* NMDC
    # Instrument id (instrument_set name match, else InstrumentModelEnum alias).
    # This runs *before* minting so we never mint ids for records we won't emit.
    model_counts: dict[str, int] = {}
    for exp in kept_experiments:
        model = (exp.get("instrument_model") or "").strip()
        if model:
            model_counts[model] = model_counts.get(model, 0) + 1

    model_to_instrument_id: dict[str, str] = {}
    unresolved_models: dict[str, int] = {}
    for model, count in model_counts.items():
        instrument_id = resolver.resolve(model)
        if instrument_id:
            model_to_instrument_id[model] = instrument_id
        else:
            unresolved_models[model] = count

    # The forthcoming `instrument_used` minimum_cardinality=1 schema constraint
    # makes a DataGeneration record with an empty `instrument_used` invalid, so
    # we exclude experiments without a resolvable instrument rather than emitting
    # such records. Biosamples are kept regardless (valid standalone records).
    # An experiment is eligible only if it has both a resolvable instrument and a
    # mappable analyte_category (both are required on NucleotideSequencing). Each
    # unmet condition excludes the DataGeneration with a warning rather than
    # emitting an invalid record or crashing the run.
    eligible_experiments: list[dict] = []
    missing_model_count = 0
    unmappable_analyte: dict[tuple[str, str], int] = {}
    for exp in kept_experiments:
        model = (exp.get("instrument_model") or "").strip()
        if not model:
            missing_model_count += 1
            continue
        if model not in model_to_instrument_id:
            continue  # model present but unresolved (counted in unresolved_models)
        source = exp.get("library_source", "")
        strategy = exp.get("library_strategy", "")
        try:
            _resolve_analyte_category(source, strategy)
        except ValueError:
            key = (
                (source or "").strip() or "(none)",
                (strategy or "").strip() or "(none)",
            )
            unmappable_analyte[key] = unmappable_analyte.get(key, 0) + 1
            continue
        eligible_experiments.append(exp)

    if model_to_instrument_id:
        print(
            f"  Resolved {len(model_to_instrument_id)} instrument model(s) to "
            f"existing NMDC Instruments:"
        )
        for model, instrument_id in sorted(model_to_instrument_id.items()):
            print(f"    {model!r} -> {instrument_id} ({model_counts[model]} experiment(s))")

    total_unresolved = sum(unresolved_models.values())
    total_excluded = total_unresolved + missing_model_count
    if unresolved_models:
        print(
            f"  WARNING: excluded {total_unresolved} DataGeneration record(s) from "
            f"{len(unresolved_models)} instrument model(s) that did not match any "
            f"NMDC Instrument:"
        )
        for model, count in sorted(unresolved_models.items()):
            print(f"    {model!r} ({count} experiment(s))")
    if missing_model_count:
        print(
            f"  WARNING: excluded {missing_model_count} DataGeneration record(s) from "
            f"experiment(s) with no instrument model."
        )
    if total_excluded:
        print(
            f"  Excluded {total_excluded} DataGeneration record(s) total for missing "
            f"or unresolvable instrument information (instrument_used is required)."
        )

    total_unmappable_analyte = sum(unmappable_analyte.values())
    if unmappable_analyte:
        print(
            f"  WARNING: excluded {total_unmappable_analyte} DataGeneration record(s) "
            f"from {len(unmappable_analyte)} (library_source, library_strategy) "
            f"combination(s) with no analyte_category mapping (analyte_category is "
            f"required):"
        )
        for (src, strat), count in sorted(unmappable_analyte.items()):
            print(f"    source={src!r} strategy={strat!r} ({count} experiment(s))")

    # Group eligible experiments into *unique libraries* (one chain per library,
    # not per experiment — several experiments can re-sequence one library; see
    # _library_key). Runs of a library that share an instrument are poolable
    # replicates bound by a Manifest.
    bioproject_accession = project["accession"]
    libraries: dict[tuple, list[dict]] = {}
    for exp in eligible_experiments:
        libraries.setdefault(_library_key(exp), []).append(exp)
    library_groups = list(libraries.values())

    # Per library, assemble the run units (one per run, carrying its experiment's
    # instrument) and tally how many Manifests it needs (instrument subgroups of
    # >1 run). Minting up front so we never mint ids for records we won't emit.
    lib_run_units: list[list[dict]] = []
    n_manifests = 0
    for group in library_groups:
        units: list[dict] = []
        for exp in group:
            model = (exp.get("instrument_model") or "").strip()
            instrument_id = model_to_instrument_id[model]
            for run in exp.get("runs", []):
                units.append({
                    "run_acc": run["accession"],
                    "exp_acc": exp["experiment_accession"],
                    "instrument_model": model,
                    "instrument_id": instrument_id,
                })
        lib_run_units.append(units)
        inst_counts: dict[str, int] = {}
        for u in units:
            inst_counts[u["instrument_model"]] = inst_counts.get(u["instrument_model"], 0) + 1
        n_manifests += sum(1 for c in inst_counts.values() if c > 1)

    n_libraries = len(library_groups)
    total_runs = sum(len(units) for units in lib_run_units)

    extraction_ids = iter(
        minter.mint("nmdc:Extraction", n_libraries) if n_libraries else []
    )
    library_prep_ids = iter(
        minter.mint("nmdc:LibraryPreparation", n_libraries) if n_libraries else []
    )
    processed_sample_ids = iter(
        minter.mint("nmdc:ProcessedSample", 2 * n_libraries) if n_libraries else []
    )
    ns_pool = iter(
        minter.mint("nmdc:NucleotideSequencing", total_runs) if total_runs else []
    )
    do_pool = iter(
        minter.mint("nmdc:DataObject", total_runs) if total_runs else []
    )
    manifest_pool = iter(
        minter.mint("nmdc:Manifest", n_manifests) if n_manifests else []
    )

    all_nuc_seqs: list[nmdc.NucleotideSequencing] = []
    all_data_objects: list[nmdc.DataObject] = []
    all_material_processings: list[nmdc.MaterialProcessing] = []
    all_processed_samples: list[nmdc.ProcessedSample] = []
    all_manifests: list[nmdc.Manifest] = []
    for group, units in zip(library_groups, lib_run_units):
        for u in units:
            u["ns_id"] = next(ns_pool)
            u["do_id"] = next(do_pool)
        inst_counts = {}
        for u in units:
            inst_counts[u["instrument_model"]] = inst_counts.get(u["instrument_model"], 0) + 1
        lib_manifest_ids = [
            next(manifest_pool) for c in inst_counts.values() if c > 1
        ]
        bs_acc = group[0]["biosample_accession"]
        records = build_library_records(
            group,
            study_id,
            biosample_acc_to_id[bs_acc],
            biosample_acc_to_name[bs_acc],
            bioproject_accession,
            units,
            next(extraction_ids),
            next(processed_sample_ids),
            next(library_prep_ids),
            next(processed_sample_ids),
            lib_manifest_ids,
            now,
        )
        all_nuc_seqs.extend(records["nucleotide_sequencings"])
        all_data_objects.extend(records["data_objects"])
        all_material_processings.extend(records["material_processings"])
        all_processed_samples.extend(records["processed_samples"])
        all_manifests.extend(records["manifests"])

    if n_libraries != len(eligible_experiments):
        print(
            f"  Grouped {len(eligible_experiments)} eligible experiment(s) into "
            f"{n_libraries} unique library/-ies (deduplicated by SRA library name)."
        )
    if all_manifests:
        print(
            f"  Created {len(all_manifests)} Manifest record(s) grouping poolable "
            f"replicate runs (shared biosample + library name + instrument)."
        )

    for w in skip_warnings:
        print(f"WARNING: {w}")

    database = nmdc.Database()
    database.study_set = [study]
    database.biosample_set = nmdc_biosamples
    database.material_processing_set = all_material_processings
    database.processed_sample_set = all_processed_samples
    database.data_generation_set = all_nuc_seqs
    database.data_object_set = all_data_objects
    database.manifest_set = all_manifests

    return database


_TRIAD_SLOTS = ("env_broad_scale", "env_local_scale", "env_medium")


def build_curation_inputs_sidecar(data: dict, database: nmdc.Database) -> dict:
    """Inputs file the curation agent reads when filling env-triad gaps.

    Bundles BioProject context plus the full raw NCBI attributes dict per
    biosample, keyed by NMDC biosample id. The NMDC schema doesn't model
    every NCBI attribute (e.g. isol_growth_condt, ecosystem*), so the agent
    needs this sidecar to do evidence-based inference per nmdc-env-triad.md.
    """
    project = data.get("bioproject", {})
    raw_biosamples = {bs["accession"]: bs for bs in data.get("biosamples", [])}

    biosamples_out: dict[str, dict] = {}
    for bs in database.biosample_set:
        nmdc_id = bs.id
        accession = ""
        for ident in (bs.insdc_biosample_identifiers or []):
            if ident.startswith("biosample:"):
                accession = ident.split(":", 1)[1]
                break
        raw = raw_biosamples.get(accession, {})
        biosamples_out[nmdc_id] = {
            "ncbi_accession": accession,
            "ncbi_title": raw.get("title", ""),
            "package": raw.get("package", ""),
            "models": raw.get("models", []),
            "attributes": raw.get("attributes", {}),
        }

    return {
        "study": {
            "id": database.study_set[0].id if database.study_set else "",
            "name": project.get("name", ""),
            "title": project.get("title", ""),
            "description": project.get("description", ""),
            "publications": project.get("publications", []),
        },
        "biosamples": biosamples_out,
    }


def build_curation_report_skeleton(database: nmdc.Database) -> dict:
    """Skeleton report file pre-populated with one row per (biosample, slot).

    Each row starts in outcome=left_sentinel; the agent flips outcomes to
    predicted/resolved_from_raw/validator_rejected as it processes the
    triad. Schema matches what nmdc-env-triad.md expects.
    """
    rows: list[dict] = []
    for bs in database.biosample_set:
        for slot in _TRIAD_SLOTS:
            term_value = getattr(bs, slot, None)
            term = getattr(term_value, "term", None) if term_value else None
            term_id = getattr(term, "id", "") if term else ""
            raw = getattr(term_value, "has_raw_value", "") if term_value else ""
            is_sentinel = term_id == "ENVO:00000000"
            rows.append({
                "biosample_id": bs.id,
                "slot": slot,
                "outcome": "left_sentinel" if is_sentinel else "resolved_at_pipeline",
                "raw_input": raw,
                "committed_curie": term_id if not is_sentinel else None,
                "committed_label": getattr(term, "name", "") if (term and not is_sentinel) else None,
                "evidence": [],
                "candidates_considered": [],
                "validator": {
                    "info_ok": None,
                    "anchor_ok": None,
                    "valueset_ok": None,
                },
            })
    return {"rows": rows}


def summarize_curation_report(report: dict) -> dict:
    """Per-slot count of outcome values, for the Step-7 stderr summary."""
    counts: dict[str, dict[str, int]] = {
        slot: {
            "predicted": 0,
            "resolved_from_raw": 0,
            "left_sentinel": 0,
            "validator_rejected": 0,
            "resolved_at_pipeline": 0,
        }
        for slot in _TRIAD_SLOTS
    }
    for row in report.get("rows", []):
        slot = row["slot"]
        outcome = row["outcome"]
        if slot in counts and outcome in counts[slot]:
            counts[slot][outcome] += 1
    return counts


def main():
    parser = argparse.ArgumentParser(
        description="Translate an NCBI BioProject to NMDC schema JSON."
    )
    parser.add_argument("accession", help="NCBI BioProject accession (e.g. PRJNA1452545)")
    parser.add_argument("--out", help="Output file path (default: results/ncbi_<accession>_nmdc.json)")
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="Only fetch and dump intermediate NCBI data as JSON (no NMDC conversion).",
    )
    parser.add_argument(
        "--mint-real-ids",
        action="store_true",
        help=(
            "Mint persistent NMDC IDs via the runtime API instead of placeholders. "
            "Requires NMDC_RUNTIME_CLIENT_ID and NMDC_RUNTIME_CLIENT_SECRET in the "
            "environment. Without this flag, output uses placeholder shoulder '99'."
        ),
    )
    parser.add_argument(
        "--env",
        choices=("dev", "prod"),
        default=None,
        help=(
            "NMDC runtime environment for ID minting and instrument_set lookup. "
            "Defaults to NMDC_RUNTIME_ENV, else 'dev'. dev-minted IDs are valid in "
            "both environments, so dev is the safe default; pass 'prod' to promote."
        ),
    )
    args = parser.parse_args()

    accession = args.accession.strip()
    out_path = args.out or f"results/ncbi_{accession}_nmdc.json"
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    # Single source of truth for the runtime environment, used by both minting
    # and instrument resolution. Precedence: --env flag > NMDC_RUNTIME_ENV > dev.
    env = args.env or os.environ.get("NMDC_RUNTIME_ENV") or "dev"
    print(f"NMDC runtime environment: {env}")

    minter: Minter
    if args.mint_real_ids:
        try:
            minter = runtime_minter_from_env(env)
        except RuntimeError as e:
            sys.exit(f"ERROR: {e}")
    else:
        minter = PlaceholderMinter()

    data = fetch_all(accession)

    if args.fetch_only:
        intermediate_path = out_path.replace(".json", "_intermediate.json")
        with open(intermediate_path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        print(f"\nIntermediate data written to {intermediate_path}")
        print("Review this file, then re-run without --fetch-only to produce NMDC JSON.")
        return

    # Resolve instrument_used against the live NMDC instrument_set in the same
    # environment as minting (dev's instrument_set is ahead of prod — e.g.
    # PromethION and Sequel IIe exist only there).
    print(f"\nFetching NMDC instrument_set ({env}) to resolve instrument_used...")
    resolver = InstrumentResolver.from_api(env)

    # MicroFlora Danica env-triad is resolved deterministically from the v2 MFDO
    # crosswalk when its data file is present; absent for non-MFD BioProjects.
    mfd_resolver = MfdEnvTriadResolver.from_tsv()
    if mfd_resolver is not None:
        print("  Loaded MFD env-triad crosswalk (v2); MFD biosamples resolved at pipeline.")

    print("\nBuilding NMDC Database...")
    database = build_nmdc_database(data, minter, resolver, mfd_resolver)

    print(f"  Study: {database.study_set[0].id}")
    print(f"  Biosamples: {len(database.biosample_set)}")
    print(f"  MaterialProcessings (Extraction + LibraryPreparation): {len(database.material_processing_set)}")
    print(f"  ProcessedSamples: {len(database.processed_sample_set)}")
    print(f"  DataGenerations (NucleotideSequencing, one per run): {len(database.data_generation_set)}")
    print(f"  DataObjects: {len(database.data_object_set)}")
    print(f"  Manifests: {len(database.manifest_set)}")

    json_str = json_dumper.dumps(database)

    with open(out_path, "w") as f:
        f.write(json_str)
    print(f"\nNMDC Database JSON written to {out_path}")

    inputs_path = out_path.replace(".json", "_curation_inputs.json")
    report_path = out_path.replace(".json", "_curation_report.json")

    inputs_sidecar = build_curation_inputs_sidecar(data, database)
    with open(inputs_path, "w") as f:
        json.dump(inputs_sidecar, f, indent=2, default=str)
    print(f"Curation inputs sidecar written to {inputs_path}")

    if Path(report_path).exists():
        with open(report_path) as f:
            report = json.load(f)
        print(f"Curation report exists at {report_path} (preserved; not overwritten)")
    else:
        report = build_curation_report_skeleton(database)
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"Curation report skeleton written to {report_path}")

    if not args.mint_real_ids:
        print("\n⚠ PLACEHOLDER IDS: All IDs use shoulder '99' and are NOT real NMDC IDs.")
        print("  Re-run with --mint-real-ids to mint real IDs via the NMDC Runtime API.")

    counts = summarize_curation_report(report)
    total_sentinels = sum(c["left_sentinel"] for c in counts.values())
    if total_sentinels:
        print(f"\n⚠ ENVO CURATION NEEDED: {total_sentinels} (slot, biosample) pair(s) carry ENVO:00000000 sentinels.")
        for slot, c in counts.items():
            parts = [f"{k}={v}" for k, v in c.items() if v]
            print(f"    {slot}: {', '.join(parts) if parts else '0'}")
        print("  Run /ncbi-to-nmdc to fill gaps via the nmdc-env-triad skill, ")
        print(f"  using the curation inputs sidecar and updating {report_path} in place.")


if __name__ == "__main__":
    main()
