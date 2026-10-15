"""Re-serialise an NMDC Database JSON into the per-class tables linkml-map joins over.

    uv run python prepare_nmdc_samples_for_linkml_map.py gssp_samples_nmdc.json out/tables

Nothing here is curation; it is the shape linkml-map (0.5.x) needs:

* joins are one hop from the primary table on *scalar* keys, and NMDC references are lists
  (`has_input: ["nmdc:bsm-…"]`) -> one-element lists are flattened to their element;
* the Biosample -> LibraryPreparation -> ProcessedSample -> NucleotideSequencing chain is stored in
  the inverse direction, so each Biosample row gets `sequencing`, `data_object` and `instrument`
  foreign-key columns (declared to linkml-map in the spec via `source_schema_patches`); a Biosample
  with several sequencing runs is emitted once per run (one PHA4GE row = one sequencing event);
* joined JSON tables are read through DuckDB as text, so the primary table (Biosample) is written as
  YAML to keep its nested value objects (TextValue, GeolocationValue, …) native; joined tables only
  ever supply scalar columns.
"""
import copy
import json
import sys
from collections import defaultdict
from pathlib import Path

import yaml

COLLECTIONS = {
    "biosample_set": "Biosample",
    "study_set": "Study",
    "data_generation_set": "NucleotideSequencing",
    "data_object_set": "DataObject",
    "material_processing_set": "LibraryPreparation",
    "processed_sample_set": "ProcessedSample",
    "instrument_set": "Instrument",  # not emitted by the ingest; in production fetch it from the NMDC runtime API
}


def scalarize(record: dict) -> dict:
    return {k: (v[0] if isinstance(v, list) and len(v) == 1 and not isinstance(v[0], dict) else v) for k, v in record.items()}


def main(nmdc_json: Path, out_dir: Path) -> None:
    db = json.load(open(nmdc_json))
    tables = {cls: [scalarize(r) for r in db.get(coll, [])] for coll, cls in COLLECTIONS.items()}

    lib_by_biosample = defaultdict(list)
    for lib in tables["LibraryPreparation"]:
        lib_by_biosample[lib.get("has_input")].append(lib)
    seq_by_input = defaultdict(list)
    for seq in tables["NucleotideSequencing"]:
        seq_by_input[seq.get("has_input")].append(seq)

    rows = []
    for biosample in tables["Biosample"]:
        runs = [seq for lib in lib_by_biosample[biosample["id"]] for seq in seq_by_input[lib.get("has_output")]]
        for seq in runs or [None]:
            row = copy.deepcopy(biosample)
            if seq:
                row["sequencing"], row["data_object"], row["instrument"] = seq["id"], seq.get("has_output"), seq.get("instrument_used")
            rows.append(row)

    out_dir.mkdir(parents=True, exist_ok=True)
    yaml.safe_dump(rows, open(out_dir / "Biosample.yaml", "w"), sort_keys=False, allow_unicode=True)
    for cls, records in tables.items():
        if cls != "Biosample":
            json.dump(records, open(out_dir / f"{cls}.json", "w"), indent=1)
    print(f"{len(rows)} Biosample row(s) + {', '.join(f'{len(v)} {k}' for k, v in tables.items() if k != 'Biosample')} -> {out_dir}/")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
