#!/usr/bin/env bash
# NMDC Database JSON -> PHA4GE WastewaterPathogenAgnostic rows, with linkml-map.
# Requires: uv (uv run for the project env, uvx for linkml-map) and network once.
#   1. prepare_nmdc_samples_for_linkml_map.py : Database JSON -> per-class tables (out/tables/)
#   2. linkml-map   : tables + nmdc_to_pha4ge.transform.yaml -> out/pha4ge_rows.{json,tsv}
#   3. linkml-validate each row against the PHA4GE schema
set -euo pipefail
cd "$(dirname "$0")"

# PHA4GE wastewater template 4.4.4, pinned (cidgoh/pathogen-genomics-package, templates/wastewater/schema.yaml)
PHA4GE_SHA=cd16622b275f849b7093790524246b07a4bf844a
PHA4GE_SCHEMA=pha4ge_wastewater.schema.yaml
[ -f "$PHA4GE_SCHEMA" ] || curl -sSL -o "$PHA4GE_SCHEMA" \
    "https://raw.githubusercontent.com/cidgoh/pathogen-genomics-package/$PHA4GE_SHA/templates/wastewater/schema.yaml"

# nmdc-schema, materialized, from the installed package (the version pinned in uv.lock)
NMDC_SCHEMA=$(uv run python -c 'import nmdc_schema, pathlib; print(pathlib.Path(nmdc_schema.__file__).parent / "nmdc_materialized_patterns.yaml")' 2>/dev/null)

echo "1/3 tables";    uv run python prepare_nmdc_samples_for_linkml_map.py gssp_samples_nmdc.json out/tables
echo "2/3 linkml-map"
# uvx = isolated env; linkml-map pins its own linkml-runtime, which clashes with the project's linkml
uvx --from 'linkml-map==0.5.4' linkml-map map-data \
    -T nmdc_to_pha4ge.transform.yaml \
    -s "$NMDC_SCHEMA" \
    --target-schema "$PHA4GE_SCHEMA" \
    -f json -o out/pha4ge_rows.json -O out/pha4ge_rows.tsv \
    out/tables/
echo "3/3 validate against the PHA4GE schema"
uv run python - "$PHA4GE_SCHEMA" <<'EOF'
import json, subprocess, sys, tempfile, collections, pathlib, yaml
schema = sys.argv[1]
rows = json.load(open("out/pha4ge_rows.json"))
rows = [{k: v for k, v in r.items() if v not in (None, [], "")} for r in (rows if isinstance(rows, list) else [rows])]
json.dump(rows, open("out/pha4ge_rows.json", "w"), indent=1)
errors = collections.Counter()
with tempfile.TemporaryDirectory() as tmp:
    for i, row in enumerate(rows):
        p = pathlib.Path(tmp, f"{i}.yaml"); yaml.safe_dump(row, open(p, "w"))
        out = subprocess.run(["uv", "run", "linkml-validate", "-s", schema, "-C", "WastewaterPathogenAgnostic", str(p)], capture_output=True, text=True)
        for line in (out.stdout + out.stderr).splitlines():
            if line.startswith("[ERROR]"):
                errors[line.split("] ", 2)[-1]] += 1
print(f"{len(rows)} PHA4GE rows, {len(rows[0])} slots each -> out/pha4ge_rows.json, out/pha4ge_rows.tsv")
print("validation:", "clean" if not errors else "")
for msg, n in errors.most_common():
    print(f"  {n}x {msg}")
EOF
