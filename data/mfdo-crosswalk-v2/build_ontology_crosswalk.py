"""Build the MFDO -> nmdc-schema crosswalk: one row per MFDO ontology leaf plus a small number
of biosample-reconciliation rows (added so the per-biosample join is total) -> nmdc-schema slots.
Exact row and coverage counts are printed at the end of a run, not asserted here.

Output: mfdo_nmdc_crosswalk.tsv
  - All 5 MFDO levels (original columns)
  - env_broad_scale, env_local_scale, env_medium (ENVO PV format)
  - *_method, *_confidence for each triad slot
  - cur_vegetation, cur_land_use, season, geo_loc_name
  - misc_param_json (stringified JSON list of PropertyAssertions)
  - n_samples (0 for unused ontology leaves)
"""
import argparse, csv, io, json, os, urllib.request, urllib.error, zipfile, xml.etree.ElementTree as ET
from collections import Counter

NS = {'a': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}

# Source xlsx inputs live in the public cmc-aau/mfd_metadata repo. Fetch them from a
# pinned commit (reproducible) and fall back to a same-named file in the CWD if offline.
# cmc-aau/mfd_metadata has no tags/releases, so the pin is a commit SHA.
MFD_RAW_BASE = 'https://raw.githubusercontent.com/cmc-aau/mfd_metadata'
MFD_DEFAULT_REF = 'b1b17d4b4e8e289c4380d878c8bf1516eb107791'  # HEAD 2026-05-28; both xlsx verified byte-identical to local
ONTOLOGY_REPO_PATH = 'data/ontology/latest_mfd-habitat-ontology.xlsx'
DB_REPO_PATH = 'analysis/releases/2025-05-28_mfd_db.xlsx'

ap = argparse.ArgumentParser(description='Build the MFDO-to-NMDC per-leaf crosswalk.')
ap.add_argument('--ref', default=MFD_DEFAULT_REF,
                help='git ref (commit SHA, branch, or tag) of cmc-aau/mfd_metadata to fetch '
                     'the source xlsx from. Default: pinned commit. Use "main" for the latest release.')
args = ap.parse_args()

def load_source_xlsx(repo_path, ref):
    """Fetch an .xlsx from cmc-aau/mfd_metadata@ref; on any network failure fall back
    to a same-named file in the CWD. Raises if neither is available."""
    local = os.path.basename(repo_path)
    url = f'{MFD_RAW_BASE}/{ref}/{repo_path}'
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = resp.read()
        print(f'  fetched {repo_path} @ {ref[:12]} ({len(data):,} bytes)')
        return zipfile.ZipFile(io.BytesIO(data))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        if os.path.exists(local):
            print(f'  fetch failed ({e}); falling back to local ./{local}')
            return zipfile.ZipFile(local)
        raise SystemExit(f'ERROR: could not fetch {url} ({e}) and no local fallback ./{local}')

# --- Load MFDO ontology ---
def cell(c, ss):
    t = c.get('t'); v = c.find('a:v', NS)
    if v is None or v.text is None: return ''
    if t == 's': return ss[int(v.text)]
    return v.text

def _col_to_idx(ref):
    """'J78' -> 9 (0-based column index). Excel omits empty <c> cells, so
    cells must be placed by their column reference, not by XML position."""
    letters = ''.join(ch for ch in ref if ch.isalpha())
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch.upper()) - ord('A') + 1)
    return idx - 1

def row_cells(r, ss, ncol):
    """Parse a sheet row into a dense list of length >= ncol, honoring each
    cell's column reference so empty/omitted cells don't shift values left."""
    out = [''] * ncol
    for c in r.findall('a:c', NS):
        ref = c.get('r')
        if not ref:
            continue
        ci = _col_to_idx(ref)
        if ci >= len(out):
            out.extend([''] * (ci - len(out) + 1))
        out[ci] = cell(c, ss)
    return out

z = load_source_xlsx(ONTOLOGY_REPO_PATH, args.ref)
ss_root = ET.fromstring(z.read('xl/sharedStrings.xml').decode())
ss = [''.join(t.text or '' for t in si.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t'))
      for si in ss_root.findall('a:si', NS)]
sh = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
xrows = list(sh.findall('a:sheetData/a:row', NS))
hdr = row_cells(xrows[0], ss, 0)
col_idx = {h: i for i, h in enumerate(hdr)}

LEVELS = ['mfd_sampletype', 'mfd_areatype', 'mfd_hab1', 'mfd_hab2', 'mfd_hab3']
ont_rows = []
for r in xrows[1:]:
    cells = row_cells(r, ss, len(hdr))
    entry = {h: cells[col_idx[h]].strip() for h in hdr if h in col_idx}
    ont_rows.append(entry)

# --- Count samples per leaf ---
z2 = load_source_xlsx(DB_REPO_PATH, args.ref)
ss2_root = ET.fromstring(z2.read('xl/sharedStrings.xml').decode())
ss2 = [''.join(t.text or '' for t in si.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t'))
       for si in ss2_root.findall('a:si', NS)]
sh2 = ET.fromstring(z2.read('xl/worksheets/sheet1.xml'))
xrows2 = list(sh2.findall('a:sheetData/a:row', NS))
hdr2 = row_cells(xrows2[0], ss2, 0)
col_idx2 = {h: i for i, h in enumerate(hdr2)}

sample_counts = Counter()
for r in xrows2[1:]:
    cells = row_cells(r, ss2, len(hdr2))
    key = tuple(cells[col_idx2[lv]].strip() for lv in LEVELS)
    sample_counts[key] += 1

# --- Inlined facet-level mappings (formerly separate helper files) ---
# Facet values where the Ollama qwen2.5:14b decomposition (decompose_facet_values.py,
# run 2026-05-25) found taxon_parts (organism names). get_cur_vegetation tests membership
# here as its `has_taxon` signal. Frozen from mfdo_decomposed.json; to refresh, re-run
# decompose_facet_values.py and re-extract (level, value) pairs with non-empty taxon_parts.
VEGETATION_TAXON_VALUES = frozenset({  # 86 pairs
    ('mfd_hab2', 'Asparagales'),
    ('mfd_hab2', 'Asterids'),
    ('mfd_hab2', 'Fabids'),
    ('mfd_hab2', 'Malvids'),
    ('mfd_hab2', 'Poales, Cereal'),
    ('mfd_hab2', 'Poales, grass'),
    ('mfd_hab2', 'Sphagnum acid bogs'),
    ('mfd_hab2', 'Superasterids'),
    ('mfd_hab3', 'Asterales, Lettuce'),
    ('mfd_hab3', 'Barley'),
    ('mfd_hab3', 'Barley, Spring'),
    ('mfd_hab3', 'Barley, Spring, Green grain'),
    ('mfd_hab3', 'Barley, Winter'),
    ('mfd_hab3', 'Beech'),
    ('mfd_hab3', 'Beech forests Acidophilous with Ilex'),
    ('mfd_hab3', 'Beech forests Asperulo-Fagetum'),
    ('mfd_hab3', 'Beech forests Limestone'),
    ('mfd_hab3', 'Beech forests Luzulo-Fagetum'),
    ('mfd_hab3', 'Birch'),
    ('mfd_hab3', 'Birch-coniferous mix'),
    ('mfd_hab3', 'Brassicales, Cabbage'),
    ('mfd_hab3', 'Brassicales, Fodder radish'),
    ('mfd_hab3', 'Brassicales, Rapeseed'),
    ('mfd_hab3', 'Brassicales, Rapeseed, Spring'),
    ('mfd_hab3', 'Brassicales, Rapeseed, Winter'),
    ('mfd_hab3', 'Caryophyllales, Beetroot'),
    ('mfd_hab3', 'Caryophyllales, Fodder beet'),
    ('mfd_hab3', 'Caryophyllales, Spinach'),
    ('mfd_hab3', 'Caryophyllales, Sugar beet'),
    ('mfd_hab3', 'Catch crop, Fodder radish, Flower'),
    ('mfd_hab3', 'Cereal mix, Fodder radish'),
    ('mfd_hab3', 'Cereal mix, Legume plants'),
    ('mfd_hab3', 'Cereal mix, Mustard'),
    ('mfd_hab3', 'Cladium fens'),
    ('mfd_hab3', 'Coastal dunes with Juniperus spp.'),
    ('mfd_hab3', 'Decalcified Empetrum dunes'),
    ('mfd_hab3', 'Dunes H. rhamnoides'),
    ('mfd_hab3', 'Dunes creeping willow'),
    ('mfd_hab3', 'Eelgrass coastal seabed'),
    ('mfd_hab3', 'Eelgrass fjord seabed'),
    ('mfd_hab3', 'Fabales'),
    ('mfd_hab3', 'Fabales, Clover'),
    ('mfd_hab3', 'Fabales, Faba bean'),
    ('mfd_hab3', 'Fabales, Pea'),
    ('mfd_hab3', 'Grass for crop, Cocksfoot'),
    ('mfd_hab3', 'Grass for crop, Common meadow-grass'),
    ('mfd_hab3', 'Grass for crop, Fescue'),
    ('mfd_hab3', 'Grass for crop, Ryegrass'),
    ('mfd_hab3', 'Grass, Clover Permanent'),
    ('mfd_hab3', 'Grass, Clover, Rotation'),
    ('mfd_hab3', 'Inland dunes Empetrum nigrum'),
    ('mfd_hab3', 'Inland dunes Genista'),
    ('mfd_hab3', 'Juniper scrub'),
    ('mfd_hab3', 'Lake, Mixed Najas flexilis'),
    ('mfd_hab3', 'Lake, Oligotrophic isoetid'),
    ('mfd_hab3', 'Lake, Rich pondweed'),
    ('mfd_hab3', 'Legume mix'),
    ('mfd_hab3', 'Maize'),
    ('mfd_hab3', 'Maize, Silage'),
    ('mfd_hab3', 'Marram dunes (white dunes)'),
    ('mfd_hab3', 'Molinia meadows'),
    ('mfd_hab3', 'Oak-hornbeam forests Galio-Carpinetum'),
    ('mfd_hab3', 'Oak-hornbeam mixed forest'),
    ('mfd_hab3', 'Oat, Spring'),
    ('mfd_hab3', 'Oat, Spring, Green grain'),
    ('mfd_hab3', 'Old acidophilous oak woods with Q. robur on sandy plains'),
    ('mfd_hab3', 'Onion'),
    ('mfd_hab3', 'Pine'),
    ('mfd_hab3', 'Rhynchosporion depressions'),
    ('mfd_hab3', 'Rosales, Apple'),
    ('mfd_hab3', 'Rye, Spring, Green grain'),
    ('mfd_hab3', 'Rye, Winter'),
    ('mfd_hab3', 'Rye, Winter, Hybrid'),
    ('mfd_hab3', 'Rye, Winter, Hybrid (Triticale)'),
    ('mfd_hab3', 'Solanales, Potato, Other'),
    ('mfd_hab3', 'Solanales, Potato, Seed'),
    ('mfd_hab3', 'Solanales, Potato, Starch'),
    ('mfd_hab3', 'Spartina swards'),
    ('mfd_hab3', 'Species-rich Nardus upland grassland'),
    ('mfd_hab3', 'Spruce'),
    ('mfd_hab3', 'Wheat'),
    ('mfd_hab3', 'Wheat, Spring'),
    ('mfd_hab3', 'Wheat, Spring, Green grain'),
    ('mfd_hab3', 'Wheat, Winter'),
    ('mfd_hab3', 'Wheat, Winter, Green Grain'),
    ('mfd_hab3', 'Willow'),
})

# misc_param PropertyAssertions per MFDO facet value. Hand-curated 2026-05-26; this dict is
# the source of truth (no generator). 53 entries.
MISC_PARAM_MAP = {
    ('mfd_hab2', 'Potential pollution'): [{'has_attribute_label': 'pollution risk', 'has_value_term_label': 'potential'}],
    ('mfd_hab2', 'Tap water'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'tap water'}],
    ('mfd_hab2', 'Leachate'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'leachate'}],
    ('mfd_hab2', 'High salinity (saltworks)'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'high salinity'}],
    ('mfd_hab3', 'Grass, Clover, Rotation'): [{'has_attribute_label': 'crop rotation', 'has_boolean_value': True}],
    ('mfd_hab3', 'Maize, Silage'): [{'has_attribute_label': 'crop use', 'has_value_term_label': 'silage'}],
    ('mfd_hab3', 'Rye, Winter, Hybrid'): [{'has_attribute_label': 'crop variety type', 'has_value_term_label': 'hybrid'}],
    ('mfd_hab3', 'Grass in rotation, No clover'): [{'has_attribute_label': 'clover present', 'has_boolean_value': False}, {'has_attribute_label': 'crop rotation', 'has_boolean_value': True}, {'has_attribute_label': 'negation pattern in source', 'has_value_term_label': 'Grass in rotation, No clover'}],
    ('mfd_hab3', 'Cereal mix, Legume plants'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'cereal mix'}],
    ('mfd_hab3', 'Grass for crop, Ryegrass'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'grass for crop'}],
    ('mfd_hab3', 'Solanales, Potato, Starch'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'starch'}],
    ('mfd_hab3', 'Pollution'): [{'has_attribute_label': 'pollution detected', 'has_boolean_value': True}],
    ('mfd_hab3', 'Rainwater basin, Dried'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'dried'}],
    ('mfd_hab3', 'Rye, Winter, Hybrid (Triticale)'): [{'has_attribute_label': 'crop variety type', 'has_value_term_label': 'hybrid'}],
    ('mfd_hab3', 'Uncultivated'): [{'has_attribute_label': 'cultivation status', 'has_value_term_label': 'uncultivated'}],
    ('mfd_hab3', 'Lake, Hard water'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'hard water'}],
    ('mfd_hab3', 'Lake, Dystrophic'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'dystrophic'}],
    ('mfd_hab3', 'Catch crop, Fodder radish, Flower'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'catch crop'}, {'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'flower'}],
    ('mfd_hab3', 'Grass for crop'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'crop'}],
    ('mfd_hab3', 'Barley, Spring, Green grain'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'Green grain'}],
    ('mfd_hab3', 'Below detection limit'): [{'has_attribute_label': 'pollution detected', 'has_boolean_value': False}],
    ('mfd_hab3', 'Permanent grass, Normal yield'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'normal yield'}],
    ('mfd_hab3', 'Permanent grass, Low yield'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'low yield'}],
    ('mfd_hab3', 'No pollution'): [{'has_attribute_label': 'pollution detected', 'has_boolean_value': False}],
    ('mfd_hab3', 'Polluted'): [{'has_attribute_label': 'pollution detected', 'has_boolean_value': True}],
    ('mfd_hab3', 'Grass for crop, Fescue'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'crop'}, {'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'forage'}],
    ('mfd_hab3', 'Cereal mix, Fodder radish'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'cereal mix'}],
    ('mfd_hab3', 'Solanales, Potato, Other'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'other'}],
    ('mfd_hab3', 'Oat, Spring, Green grain'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'Green grain'}],
    ('mfd_hab3', 'Solanales, Potato, Seed'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'seed'}],
    ('mfd_hab3', 'Summer mowing'): [{'has_attribute_label': 'management practice', 'has_value_term_label': 'mowing'}, {'has_attribute_label': 'management season', 'has_value_term_id': 'NCIT:C94732', 'has_value_term_label': 'summer'}],
    ('mfd_hab3', 'Uncleaned/raw water'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'uncleaned/raw water'}],
    ('mfd_hab3', 'Permanent grass, No clover'): [{'has_attribute_label': 'clover present', 'has_boolean_value': False}, {'has_attribute_label': 'negation pattern in source', 'has_value_term_label': 'Permanent grass, No clover'}],
    ('mfd_hab3', 'Lake, Oligotrophic isoetid'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'oligotrophic'}],
    ('mfd_hab3', 'Treated water'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'treated water'}],
    ('mfd_hab3', 'Grass for crop, Common meadow-grass'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'crop'}, {'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'grass'}],
    ('mfd_hab3', 'Wheat, Winter, Green Grain'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'Green Grain'}],
    ('mfd_hab3', 'Trace pollution'): [{'has_attribute_label': 'pollution detected', 'has_boolean_value': True}, {'has_attribute_label': 'pollution level', 'has_value_term_label': 'trace'}],
    ('mfd_hab3', 'Potential pollution'): [{'has_attribute_label': 'pollution risk', 'has_value_term_label': 'potential'}],
    ('mfd_hab3', 'Unknown cereal'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'unknown cereal'}],
    ('mfd_hab3', 'Grass in rotation'): [{'has_attribute_label': 'crop rotation', 'has_boolean_value': True}],
    ('mfd_hab3', 'Legume mix'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'legume mix'}],
    ('mfd_hab3', 'Rye, Spring, Green grain'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'green grain'}],
    ('mfd_hab3', 'Grass, Clover Permanent'): [{'has_attribute_label': 'crop rotation', 'has_boolean_value': False}],
    ('mfd_hab3', 'Wheat, Spring, Green grain'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'Green grain'}],
    ('mfd_hab3', 'Mineral-rich springs and springfens (not Fennoscandia)'): [{'has_attribute_label': 'geographic exclusion', 'has_value_term_label': 'not Fennoscandia'}],
    ('mfd_hab3', 'Enclosed water, Dried'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'dried'}],
    ('mfd_hab3', 'Grass for crop, Cocksfoot'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'crop grass'}],
    ('mfd_hab3', 'Cereal mix, Mustard'): [{'has_attribute_label': 'sample qualifier', 'has_value_term_label': 'cereal mix'}],
    ('mfd_hab3', 'Spring mowing'): [{'has_attribute_label': 'management practice', 'has_value_term_label': 'mowing'}, {'has_attribute_label': 'management season', 'has_value_term_id': 'NCIT:C94731', 'has_value_term_label': 'spring'}],
    ('mfd_hab3', 'Atlantic salt meadows'): [{'has_attribute_label': 'geographic context', 'has_value_term_label': 'Atlantic coast'}],
    ('mfd_hab3', 'Vegetated sea cliffs of the Atlantic and Baltic Coasts'): [{'has_attribute_label': 'geographic context', 'has_value_term_label': 'Atlantic coast'}, {'has_attribute_label': 'geographic context', 'has_value_term_label': 'Baltic coast'}],
    ('mfd_hab3', 'Rainwater basin, City'): [{'has_attribute_label': 'urban context', 'has_value_term_label': 'city'}],
}

# --- Mapping functions ---

# EBS rules (copied from assemble_triads.py logic)
EBS_SPECIFIC_RULES = {
    ('Soil', 'Urban', 'Greenspaces'): ('ENVO:01000249', 'urban biome'),
    ('Water', 'Natural', 'Saltwater'): ('ENVO:00000447', 'marine biome'),
    ('Water', 'Natural', 'Freshwater'): ('ENVO:00000873', 'freshwater biome'),
    ('Sediment', 'Natural', 'Freshwater'): ('ENVO:00000873', 'freshwater biome'),
    ('Sediment', 'Natural', 'Saltwater'): ('ENVO:00000447', 'marine biome'),
}
# hab2-level EBS overrides
EBS_HAB2_RULES = {
    ('Soil', 'Natural', 'Dunes', 'Inland dunes'): ('ENVO:01000193', 'temperate grassland biome'),
    ('Soil', 'Natural', 'Dunes', 'Sea dunes'): ('ENVO:01000215', 'temperate shrubland biome'),
    ('Soil', 'Natural', 'Coastal', 'Salt marshes and salt meadows'): ('ENVO:01000195', 'flooded grassland biome'),  # GEE-confirmed salt marsh
    ('Soil', 'Natural', 'Coastal', 'Sea cliffs and shingle or stony beaches'): ('ENVO:01000215', 'temperate shrubland biome'),
    ('Soil', 'Natural', 'Forests', 'Forest (non-habitattype)'): ('ENVO:01000174', 'forest biome'),
    ('Soil', 'Natural', 'Forests', 'Temperate forests'): ('ENVO:01000202', 'temperate broadleaf forest biome'),
}
EBS_RULES = {
    ('Soil', 'Agriculture'): ('ENVO:01000245', 'cropland biome'),
    ('Soil', 'Agriculture (reclaimed lowland)'): ('ENVO:01000245', 'cropland biome'),
    ('Soil', 'Urban'): ('ENVO:01000249', 'urban biome'),
    ('Soil', 'Subterranean'): ('ENVO:01000249', 'urban biome'),
    ('Sediment', 'Natural'): ('ENVO:00000447', 'marine biome'),
    ('Sediment', 'Subterranean'): ('ENVO:00000447', 'marine biome'),
    ('Sediment', 'Urban'): ('ENVO:01000249', 'urban biome'),
    ('Water', 'Natural'): ('ENVO:00000447', 'marine biome'),
    ('Water', 'Urban'): ('ENVO:01000249', 'urban biome'),
    ('Water', 'Subterranean'): ('ENVO:00000873', 'freshwater biome'),
    ('Other', 'Urban'): ('ENVO:01000249', 'urban biome'),
}
EBS_HAB1_RULES = {
    'Grassland formations': ('ENVO:01000177', 'grassland biome'),
    'Fields': ('ENVO:01000245', 'cropland biome'),
    'Dunes': ('ENVO:01000215', 'temperate shrubland biome'),
    'Bogs, mires and fens': ('ENVO:01000195', 'flooded grassland biome'),
    'Temperate heath and scrub': ('ENVO:01000176', 'shrubland biome'),
    'Rocky habitats and caves': ('ENVO:00000446', 'terrestrial biome'),  # not shrubland; rows confirm terrestrial (soil/natural land) but no vegetation-biome signal
    'Coastal habitats': ('ENVO:01000215', 'temperate shrubland biome'),
    'Coastal': ('ENVO:01000215', 'temperate shrubland biome'),
    'Forests': ('ENVO:01000174', 'forest biome'),
    'Freshwater': ('ENVO:00000873', 'freshwater biome'),
    'Saltwater': ('ENVO:00000447', 'marine biome'),
    'Sclerophyllous scrub': ('ENVO:01000176', 'shrubland biome'),
    '': ('ENVO:01000177', 'grassland biome'),
}

ELS_RULES = {
    ('Soil', 'Agriculture', 'Fields'): ('ENVO:00000114', 'agricultural field'),
    ('Soil', 'Agriculture', 'Grassland formations'): ('ENVO:00000114', 'agricultural field'),
    ('Soil', 'Agriculture (reclaimed lowland)', 'Fields'): ('ENVO:00000114', 'agricultural field'),
    ('Soil', 'Agriculture (reclaimed lowland)', 'Grassland formations'): ('ENVO:00000114', 'agricultural field'),
    ('Soil', 'Natural', 'Forests'): ('ENVO:01001243', 'forest ecosystem'),
    ('Soil', 'Natural', 'Grassland formations'): ('ENVO:01001206', 'grassland ecosystem'),
    ('Soil', 'Natural', 'Dunes'): ('ENVO:00000416', 'coastal dune'),
    ('Soil', 'Natural', 'Bogs, mires and fens'): ('ENVO:00000044', 'peatland'),
    ('Soil', 'Natural', 'Coastal habitats'): ('ENVO:00000303', 'sea coast'),
    ('Soil', 'Natural', 'Coastal'): ('ENVO:00000303', 'sea coast'),
    ('Soil', 'Natural', ''): ('ENVO:01001206', 'grassland ecosystem'),
    ('Soil', 'Subterranean', ''): ('ENVO:00002184', 'subsurface landform'),       # buried urban soil, not a tunnel
    ('Soil', 'Subterranean', 'Urban'): ('ENVO:00002184', 'subsurface landform'),  # buried urban soil, not a tunnel
    ('Soil', 'Urban', 'Roadside'): ('ENVO:01000447', 'roadside'),
    ('Soil', 'Urban', 'Other'): ('ENVO:01001829', 'human settlement'),  # generic 'Other' urban soil -> general urban term, not roadside
    ('Soil', 'Urban', 'Greenspaces'): ('ENVO:00000562', 'park'),
    ('Soil', 'Urban', 'Landfill'): ('ENVO:00000533', 'landfill'),
    ('Sediment', 'Natural', 'Freshwater'): ('ENVO:00000020', 'lake'),
    ('Sediment', 'Urban', 'Freshwater'): ('ENVO:00000033', 'pond'),
    ('Sediment', 'Urban', 'Saltwater'): ('ENVO:00000482', 'sea floor'),  # urban marine sediment; harbour only via label (hab3/hab2), not this coarse rule
    # ('Sediment','Urban','Other')->harbour removed: generic 'Other' over-asserted harbour (0 biosamples)
    ('Sediment', 'Natural', 'Saltwater'): ('ENVO:00000485', 'sea shore'),
    ('Sediment', 'Subterranean', 'Saltwater'): ('ENVO:00000016', 'sea'),
    ('Water', 'Urban', 'Wastewater'): ('ENVO:00002043', 'wastewater treatment plant'),
    ('Water', 'Urban', 'Freshwater'): ('ENVO:00000033', 'pond'),
    ('Water', 'Urban', 'Drinking water'): ('ENVO:03600004', 'drinking water treatment plant'),
    ('Other', 'Urban', 'Drinking water'): ('ENVO:03600004', 'drinking water treatment plant'),
    ('Water', 'Subterranean', 'Freshwater'): ('ENVO:00000063', 'water body'),
    ('Other', 'Urban', 'Biogas'): ('ENVO:01000408', 'environmental zone'),
    ('Water', 'Urban', 'Biogas'): ('ENVO:01000408', 'environmental zone'),
    ('Other', 'Urban', 'Landfill'): ('ENVO:00000533', 'landfill'),
    ('Other', 'Urban', 'Saltwater'): ('ENVO:00000016', 'sea'),  # harbour only via label (hab3 'Harbour, marina'), not this coarse rule
    ('Water', 'Natural', 'Saltwater'): ('ENVO:00000016', 'sea'),
    ('Water', 'Natural', 'Freshwater'): ('ENVO:00000020', 'lake'),
    ('Other', 'Urban', 'Other'): ('ENVO:01000408', 'environmental zone'),
    ('Other', 'Urban', 'Industrial'): ('ENVO:01000408', 'environmental zone'),
    ('Water', 'Urban', 'Sandfilter'): ('ENVO:03600004', 'drinking water treatment plant'),
    ('Water', 'Urban', 'Landfill'): ('ENVO:00000533', 'landfill'),
    ('Water', 'Urban', 'Other'): ('ENVO:01000408', 'environmental zone'),
    ('Soil', 'Natural', 'Temperate heath and scrub'): ('ENVO:00000107', 'heath'),
    ('Soil', 'Natural', 'Sclerophyllous scrub'): ('ENVO:00000300', 'scrubland area'),
    ('Soil', 'Natural', 'Rocky habitats and caves'): ('ENVO:01000319', 'rocky slope'),
}

EM_RULES = {
    ('Soil', 'Bogs, mires and fens'): ('ENVO:00005774', 'peat soil'),
    ('Soil', 'Fields'): ('ENVO:00002259', 'agricultural soil'),
    ('Sediment', 'Saltwater'): ('ENVO:03000033', 'marine sediment'),
    ('Water', 'Wastewater'): ('ENVO:00002001', 'waste water'),
    ('Water', 'Biogas'): ('ENVO:00002044', 'sludge'),
    ('Water', 'Drinking water'): ('ENVO:00003064', 'drinking water'),
    ('Water', 'Landfill'): ('ENVO:00002141', 'leachate'),
}
EM_HAB2_RULES = {
    ('Water', 'Freshwater', 'Groundwater'): ('ENVO:01001004', 'groundwater'),
    ('Water', 'Wastewater', 'Activated sludge'): ('ENVO:00002046', 'activated sludge'),
    ('Water', 'Drinking water', 'Tap water'): ('ENVO:00003096', 'tap water'),
    ('Water', 'Biogas', 'Biogas sludge'): ('ENVO:00003965', 'anaerobic digester sludge'),
    ('Water', 'Biogas', 'Biogas manure'): ('ENVO:03501300', 'manure'),
    ('Water', 'Biogas', 'Biogas unknown'): ('ENVO:00002044', 'sludge'),
}
EM_SAMPLETYPE = {
    'Soil': ('ENVO:00001998', 'soil'),
    'Sediment': ('ENVO:00002007', 'sediment'),
    'Water': ('ENVO:00002006', 'liquid water'),
    'Other': ('ENVO:00010483', 'environmental material'),
}
# sampletype=Other needs hab1-level EM rules since the sampletype itself is uninformative
EM_OTHER_RULES = {
    ('Other', 'Saltwater'): ('ENVO:00002010', 'saline water'),
    ('Other', 'Landfill'): ('ENVO:00002141', 'leachate'),
    ('Other', 'Drinking water'): ('ENVO:00003064', 'drinking water'),
    ('Other', 'Industrial'): ('ENVO:00002010', 'saline water'),
    ('Other', 'Other'): ('ENVO:00010483', 'environmental material'),
}
EM_OTHER_HAB2 = {
    ('Other', 'Saltwater', 'Flowing saltwater'): ('ENVO:00002010', 'saline water'),
    ('Other', 'Industrial', 'High salinity (saltworks)'): ('ENVO:00003044', 'brine'),
    ('Other', 'Industrial', 'High chalk concentration (limestone quarry)'): ('ENVO:00010483', 'environmental material'),
    ('Other', 'Landfill', 'Enrichment'): ('ENVO:00002141', 'leachate'),
}
EM_OTHER_HAB3 = {
    ('Other', 'Saltwater', 'Flowing saltwater', 'Harbour, marina scraped-off biofilm'): ('ENVO:01000156', 'biofilm material'),
    ('Other', 'Drinking water', 'Waterworks stage', 'Sandfilter'): ('ENVO:00003064', 'drinking water'),
}

# cur_land_use: only assign when the enum value is defensible from the MFDO context.
# Leave empty when no enum value is a good fit. Use all 5 levels.
# Key: (st, at, h1, h2) with h2='' as fallback when h2 doesn't change the answer.

CUR_LAND_USE_HAB2 = {
    # Agriculture: hab2 tells us cereal vs grass vs vegetables vs fallow
    ('Soil', 'Agriculture', 'Fields', 'Poales, Cereal'): 'small grains',
    ('Soil', 'Agriculture', 'Fields', 'Poales, grass'): 'pastureland',
    ('Soil', 'Agriculture', 'Fields', 'Mixed crops'): 'row crops',
    ('Soil', 'Agriculture', 'Fields', 'Fallow'): 'rangeland',
    ('Soil', 'Agriculture', 'Fields', 'Asterids'): 'vegetable crops',
    ('Soil', 'Agriculture', 'Fields', 'Superasterids'): 'vegetable crops',
    ('Soil', 'Agriculture', 'Fields', 'Fabids'): 'row crops',
    ('Soil', 'Agriculture', 'Fields', 'Malvids'): 'row crops',
    ('Soil', 'Agriculture', 'Fields', 'Asparagales'): 'vegetable crops',
    ('Soil', 'Agriculture (reclaimed lowland)', 'Fields', 'Poales, Cereal'): 'small grains',
    ('Soil', 'Agriculture (reclaimed lowland)', 'Fields', 'Poales, grass'): 'pastureland',
    ('Soil', 'Agriculture (reclaimed lowland)', 'Fields', 'Fallow'): 'rangeland',
    ('Soil', 'Agriculture (reclaimed lowland)', 'Fields', 'Malvids'): 'row crops',
    # Forests: hab2 tells us temperate broadleaf vs conifer vs mixed
    ('Soil', 'Natural', 'Forests', 'Temperate forests'): 'hardwoods',
    ('Soil', 'Natural', 'Forests', 'Forest (non-habitattype)'): '',  # resolved at hab3 level below
    # Natural grasslands
    ('Soil', 'Natural', 'Grassland formations', 'Semi-natural dry grasslands'): 'meadows',
    ('Soil', 'Natural', 'Grassland formations', 'Semi-natural tall-herb humid meadows'): 'meadows',
    ('Soil', 'Natural', 'Grassland formations', 'Natural grasslands'): 'rangeland',
    ('Soil', 'Natural', 'Grassland formations', 'Grasslands (non-habitat type)'): 'meadows',
    # Coastal
    ('Soil', 'Natural', 'Coastal', 'Salt marshes and salt meadows'): 'marshlands',
    ('Soil', 'Natural', 'Coastal', 'Sea cliffs and shingle or stony beaches'): 'rock',
    # Bogs subtypes
    ('Soil', 'Natural', 'Bogs, mires and fens', 'Sphagnum acid bogs'): 'swamp',
    ('Soil', 'Natural', 'Bogs, mires and fens', 'Calcareous fens'): 'marshlands',
    ('Soil', 'Natural', 'Bogs, mires and fens', 'Fen wetland (non-habitat type)'): 'marshlands',
    ('Soil', 'Natural', 'Bogs, mires and fens', 'Wet thicket  (non-habitat type)'): 'swamp',
    ('Soil', 'Natural', 'Bogs, mires and fens', 'Mire (non-habitat type)'): 'swamp',
}

ELS_BOG_HAB2 = {
    'Sphagnum acid bogs': ('ENVO:00002268', 'sphagnum bog'),
    'Calcareous fens': ('ENVO:00000232', 'fen'),
    'Fen wetland (non-habitat type)': ('ENVO:00000232', 'fen'),
    'Wet thicket  (non-habitat type)': ('ENVO:00000044', 'peatland'),
    'Mire (non-habitat type)': ('ENVO:00000185', 'raised mire'),
}


CUR_LAND_USE_MAP = {
    # (areatype, hab1) fallback when hab2 doesn't resolve
    ('Agriculture', 'Fields'): 'row crops',
    ('Agriculture (reclaimed lowland)', 'Fields'): 'row crops',
    ('Natural', 'Temperate heath and scrub'): 'shrub land',
    ('Natural', 'Sclerophyllous scrub'): 'shrub land',
    ('Natural', 'Dunes'): 'sand',
    ('Natural', 'Rocky habitats and caves'): 'rock',
    ('Urban', 'Roadside'): 'roads/railroads',
    ('Urban', 'Landfill'): 'industrial areas',
    ('Urban', 'Industrial'): 'industrial areas',
    ('Urban', 'Biogas'): 'industrial areas',
    # Leave empty for: Urban Greenspaces (not "cities"), Urban Wastewater (not "cities"),
    # Urban Drinking water, Urban Other, Urban Saltwater, Urban Freshwater,
    # Subterranean anything, Sediment anything, Water anything
    # -- none of the enum values are a good fit for these
}

def format_pv(curie, label):
    if not curie or not label: return ''
    return f'{label.lower()} [{curie}]'

def get_ebs(st, at, hab1, hab2=''):
    # Most specific: hab2-level
    if hab2:
        r = EBS_HAB2_RULES.get((st, at, hab1, hab2))
        if r: return r[0], r[1], 'from_mfdo:hab2'
    r = EBS_SPECIFIC_RULES.get((st, at, hab1))
    if r: return r[0], r[1], 'from_mfdo:areatype+hab1'
    if at in ('Urban', 'Subterranean', 'Agriculture', 'Agriculture (reclaimed lowland)'):
        r = EBS_RULES.get((st, at))
        if r: return r[0], r[1], 'from_mfdo:sampletype+areatype'
    if hab1 in EBS_HAB1_RULES:
        r = EBS_HAB1_RULES[hab1]
        return r[0], r[1], 'from_mfdo:hab1'
    r = EBS_RULES.get((st, at))
    if r: return r[0], r[1], 'from_mfdo:sampletype+areatype'
    return 'ENVO:00000428', 'biome', 'envo_root_class'

ELS_HAB2_OVERRIDES = {
    'Running freshwater': ('ENVO:00000022', 'river'),
    'Fjords': ('ENVO:00000039', 'fjord'),
    'Harbours': ('ENVO:00000463', 'harbour'),
    'Open sea': ('ENVO:00000016', 'sea'),
    'Open sea and tidal areas': ('ENVO:00000482', 'sea floor'),
    'Oceanic': ('ENVO:00000016', 'sea'),
    'Other rocky habitats': ('ENVO:01000319', 'rocky slope'),
    'Rocky slopes with vegetation': ('ENVO:01000319', 'rocky slope'),
}

# GEE-confirmed hab3-level ELS overrides (>=70% CORINE agreement)
ELS_HAB3_OVERRIDES = {
    'Salicornia mud': ('ENVO:00000316', 'intertidal zone'),       # CORINE 79% salt marshes
    'Spartina swards': ('ENVO:00000316', 'intertidal zone'),      # CORINE 83% intertidal flats
    'Inland dunes Genista': ('ENVO:00000107', 'heath'),           # CORINE 75% moors/heathland
    'Sea caves': ('ENVO:00000067', 'cave'),                       # actually a cave
}

# Forest hab3 subtype -> specific temperate-forest ELS term.
# Denmark is temperate, so all targets are temperate forest classes.
# All CURIEs are in the ELS allow-list (els_v5.txt) and verified non-obsolete via OLS4.
# Replaces the generic 'forest ecosystem [ENVO:01001243]' that hab1='Forests' otherwise assigns.
# Mirrors the conifer/hardwood/mixed split already used for cur_land_use (FOREST_HAB3_LAND_USE).
FOREST_HAB3_ELS = {
    # Evergreen needleleaf (conifers)
    'Coniferous forest':            ('ENVO:01000383', 'temperate evergreen needleleaf forest'),
    'Spruce':                       ('ENVO:01000383', 'temperate evergreen needleleaf forest'),
    'Sitka':                        ('ENVO:01000383', 'temperate evergreen needleleaf forest'),
    'Douglas':                      ('ENVO:01000383', 'temperate evergreen needleleaf forest'),
    'Pine':                         ('ENVO:01000383', 'temperate evergreen needleleaf forest'),
    # Deciduous needleleaf (larch is a deciduous conifer)
    'Larch':                        ('ENVO:01000386', 'temperate deciduous needleleaf forest'),
    # Deciduous broadleaf (hardwoods)
    'Deciduous trees':              ('ENVO:01000385', 'temperate deciduous broadleaf forest'),
    'Beech':                        ('ENVO:01000385', 'temperate deciduous broadleaf forest'),
    'Beech forests Luzulo-Fagetum': ('ENVO:01000385', 'temperate deciduous broadleaf forest'),
    'Beech forests Acidophilous with Ilex': ('ENVO:01000385', 'temperate deciduous broadleaf forest'),
    'Beech forests Asperulo-Fagetum': ('ENVO:01000385', 'temperate deciduous broadleaf forest'),
    'Beech forests Limestone':      ('ENVO:01000385', 'temperate deciduous broadleaf forest'),
    'Oak-hornbeam mixed forest':    ('ENVO:01000385', 'temperate deciduous broadleaf forest'),
    'Oak-hornbeam forests Galio-Carpinetum': ('ENVO:01000385', 'temperate deciduous broadleaf forest'),
    'Old acidophilous oak woods with Q. robur on sandy plains': ('ENVO:01000385', 'temperate deciduous broadleaf forest'),
    'Pedunculate oak':              ('ENVO:01000385', 'temperate deciduous broadleaf forest'),
    'Aspen':                        ('ENVO:01000385', 'temperate deciduous broadleaf forest'),
    'Maple':                        ('ENVO:01000385', 'temperate deciduous broadleaf forest'),
    'Alder':                        ('ENVO:01000385', 'temperate deciduous broadleaf forest'),
    'Willow':                       ('ENVO:01000385', 'temperate deciduous broadleaf forest'),
    'Birch':                        ('ENVO:01000385', 'temperate deciduous broadleaf forest'),
    # Mixed broadleaf + needleleaf
    'Birch-coniferous mix':         ('ENVO:01001796', 'temperate mixed forest'),
    # Forested wetland (bog woodland 91D0, alluvial woodland 91E0, birch swamp)
    'Bog woodland':                 ('ENVO:01000398', 'temperate freshwater swamp forest'),
    'Alluvial woodland':            ('ENVO:01000398', 'temperate freshwater swamp forest'),
    'Birch swamp':                  ('ENVO:01000398', 'temperate freshwater swamp forest'),
}

# Natura2000 (EU Habitats Directive Annex I) code -> specific ELS term. Refines leaves whose
# habitat-label-derived ELS is coarse. Each Annex I label was matched to ENVO via the
# rich-definition embedding index, then the chosen CURIE was OLS-verified (label + non-obsolete)
# and confirmed in the ELS allow-list. See holistic_els_v2.py for the candidate generator.
N2K_ELS = {
    '1230': ('ENVO:00000088', 'sea cliff'),        # Vegetated sea cliffs (was: sea coast)
    '1300': ('ENVO:00000054', 'saline marsh'),     # Salt marshes and salt meadows (was: sea coast)
    '1330': ('ENVO:00000054', 'saline marsh'),     # Atlantic salt meadows
    '1340': ('ENVO:00000054', 'saline marsh'),     # Inland salt meadows
    '2190': ('ENVO:00000308', 'dune slack'),       # Humid dune slacks (was: coastal dune)
    '5130': ('ENVO:01000241', 'juniper woodland'), # Juniper scrub (was: scrubland area)
    '7220': ('ENVO:00000027', 'spring'),           # Petrifying springs -- a spring, not a fen
    # Grasslands -> temperate grassland (Denmark is temperate; more specific than the generic
    # 'grassland ecosystem' default). 6430 (hydrophilous tall-herb swamp) is deliberately omitted.
    '6000': ('ENVO:01001811', 'temperate grassland'),
    '6100': ('ENVO:01001811', 'temperate grassland'),
    '6120': ('ENVO:01001811', 'temperate grassland'),
    '6200': ('ENVO:01001811', 'temperate grassland'),
    '6210': ('ENVO:01001811', 'temperate grassland'),
    '6230': ('ENVO:01001811', 'temperate grassland'),
    # Humid meadows -> wet meadow ecosystem (harmonizes the meadow family, was grassland ecosystem)
    '6400': ('ENVO:01000449', 'wet meadow ecosystem'),
    '6410': ('ENVO:01000449', 'wet meadow ecosystem'),  # Molinia meadows (moist)
    # Refinements surfaced by mapping the full Annex I habitat names (richer than MFD labels)
    # against the label+definition+synonym ENVO backend; each OLS-verified + allow-listed.
    # 1150 "Coastal lagoons" intentionally has NO override: lagoon [ENVO:00000038] sits under
    # 'aquatic layer', not under any env_local_scale anchor, so it fails the ELS allow-list and
    # ENVO has no anchor-valid 'coastal lagoon' term. Falls back to the leaf default (lake).
    '2330': ('ENVO:01001811', 'temperate grassland'), # Inland dunes with open grasslands (was: coastal dune)
    '3130': ('ENVO:01000775', 'mesotrophic lake'),  # Oligotrophic-mesotrophic standing waters (was: lake)
    '3140': ('ENVO:01000775', 'mesotrophic lake'),  # Hard oligo-mesotrophic waters with Chara (was: lake)
    '3150': ('ENVO:01000548', 'eutrophic lake'),    # Natural eutrophic lakes (was: lake)
    '7160': ('ENVO:00000125', 'mineral spring'),    # Mineral-rich springs and springfens (was: sphagnum bog)
    '8330': ('ENVO:00000326', 'sea cave'),          # Submerged sea caves (was: cave)
    # Realignment: 6430 is a hydrophilous tall-herb FRINGE community (herbaceous freshwater
    # wetland), not grassland -> freshwater marsh.
    '6430': ('ENVO:00000053', 'freshwater marsh'),  # Hydrophilous tall-herb fringe (was: grassland ecosystem)
}

# hab3 habitat refinements not keyed by a Natura2000 code: seabed substrate, lake trophic state,
# raised-bog morphology, meadow subtypes. All CURIEs OLS-verified + in the ELS allow-list.
HAB3_ELS = {
    'Eelgrass coastal seabed':            ('ENVO:01000059', 'sea grass bed'),
    'Eelgrass fjord seabed':              ('ENVO:01000059', 'sea grass bed'),
    'Rocky coastal seabed':               ('ENVO:00000130', 'rocky reef'),
    'Rocky fjord seabed':                 ('ENVO:00000130', 'rocky reef'),
    'Lake, Dystrophic':                   ('ENVO:01001021', 'humic lake'),
    'Lake, Oligotrophic isoetid':         ('ENVO:01000774', 'oligotrophic lake'),
    'Active raised bogs':                 ('ENVO:00000185', 'raised mire'),
    'Degraded raised bog':                ('ENVO:00000185', 'raised mire'),
    'Natural meadow (6410 subtype)':      ('ENVO:01000449', 'wet meadow ecosystem'),
    'Agricultural meadow (6430 subtype)': ('ENVO:01000449', 'wet meadow ecosystem'),
    # Realignment: engineered stormwater retention basins are not natural ponds -> back off to
    # the general 'water body' (they are standing freshwater bodies, but not natural ponds).
    'Rainwater basin, City':              ('ENVO:00000063', 'water body'),
    'Rainwater basin, Roadside':          ('ENVO:01000447', 'roadside'),   # roadside context is the signal (ENVO has roadside)
    'Rainwater basin, Dried':             ('ENVO:00000063', 'water body'),
    # Harbour ONLY where the label says so (the only sampled harbour leaf, n=82); the coarse
    # Urban+Saltwater rule otherwise over-asserts harbour on label-less leaves.
    'Harbour, marina scraped-off biofilm': ('ENVO:00000463', 'harbour'),
}

# Full-context (sampletype, areatype, hab1, hab2) ELS overrides, for leaves where a coarse hab1
# rule would mis-assert. Keyed on the FULL context, never on a bare generic token like 'Other'
# (which could mean different things under a different hab1 in a future release).
ELS_HAB2_CTX = {
    # 'Other' (unspecified) urban greenspace is not a park -> 'area of developed open space'
    # (NLCD class: developed land dominated by lawn/vegetation -- parks, lawns, recreation areas).
    ('Soil', 'Urban', 'Greenspaces', 'Other'): ('ENVO:01000883', 'area of developed open space'),
}

def get_els(st, at, hab1, hab2='', hab3='', natura2000=''):
    # Natura2000 Annex I code -> specific ELS (precise habitat type; highest confidence)
    if natura2000 and natura2000 in N2K_ELS:
        r = N2K_ELS[natura2000]
        return r[0], r[1], 'from_natura2000'
    # hab3 overrides (GEE-confirmed, highest confidence)
    if hab3 and hab3 in ELS_HAB3_OVERRIDES:
        r = ELS_HAB3_OVERRIDES[hab3]
        return r[0], r[1], 'from_mfdo:hab3+gee_corine'
    # hab3 habitat refinements (seabed/lake-trophic/raised-bog/meadow-subtype)
    if hab3 and hab3 in HAB3_ELS:
        r = HAB3_ELS[hab3]
        return r[0], r[1], 'from_mfdo:hab3'
    # Forest hab3 subtype -> specific temperate-forest ELS (otherwise generic 'forest ecosystem')
    if hab1 == 'Forests' and hab3 in FOREST_HAB3_ELS:
        r = FOREST_HAB3_ELS[hab3]
        return r[0], r[1], 'from_mfdo:hab3'
    # Bog/fen/mire hab2 overrides (now in expanded allow-list)
    if hab2 and hab2 in ELS_BOG_HAB2:
        r = ELS_BOG_HAB2[hab2]
        return r[0], r[1], 'from_mfdo:hab2'
    # hab2 overrides (more specific than hab1)
    if hab2 and hab2 in ELS_HAB2_OVERRIDES:
        r = ELS_HAB2_OVERRIDES[hab2]
        return r[0], r[1], 'from_mfdo:hab2'
    # Full-context override (most specific; keyed on the complete tuple, not a bare token)
    r = ELS_HAB2_CTX.get((st, at, hab1, hab2))
    if r: return r[0], r[1], 'from_mfdo:hab2'
    r = ELS_RULES.get((st, at, hab1))
    if r: return r[0], r[1], 'from_mfdo:hab1'
    r = ELS_RULES.get((st, at, ''))
    if r: return r[0], r[1], 'from_mfdo:sampletype+areatype'
    return 'ENVO:01000408', 'environmental zone', 'envo_root_class'

# hab3-specific env_medium overrides (material contradicts the hab1-level default).
EM_HAB3 = {
    # Annex I 7220 tells us this is a calcareous tufa spring, NOT peat -- but the sampletype is
    # Soil, so the medium is soil (not 'travertine', which is the deposited rock, not the sample).
    'Petrifying springs': ('ENVO:00001998', 'soil'),  # was wrongly 'peat soil'; sampletype=Soil
}
def get_em(st, hab1, hab2, hab3='', empo=''):
    if hab3 and hab3 in EM_HAB3:                 # keyed on the hab3 label, so provenance is hab3
        r = EM_HAB3[hab3]
        return r[0], r[1], 'from_mfdo:hab3'
    # EMPO salinity refinement (EMPO is the authoritative salinity signal): saline free water
    # -> sea water, more specific than generic 'liquid water' and consistent with the marine
    # biome these leaves carry. Saline soil/sediment salinity is already reflected in their ELS
    # (saline marsh / intertidal zone) and EM (marine sediment), so EMPO only refines water here.
    _ep = [x.strip() for x in empo.split(';')]
    if len(_ep) > 2 and _ep[1] == 'Saline' and 'Water' in _ep[2]:
        return 'ENVO:00002149', 'sea water', 'from_empo'
    # Most specific first: hab3 for Other sampletype
    if st == 'Other' and hab3:
        r = EM_OTHER_HAB3.get((st, hab1, hab2, hab3))
        if r: return r[0], r[1], 'from_mfdo:hab3'
    # hab2 level
    r = EM_HAB2_RULES.get((st, hab1, hab2))
    if r: return r[0], r[1], 'from_mfdo:hab2'
    if st == 'Other':
        r = EM_OTHER_HAB2.get((st, hab1, hab2))
        if r: return r[0], r[1], 'from_mfdo:hab2'
    # hab1 level
    r = EM_RULES.get((st, hab1))
    if r: return r[0], r[1], 'from_mfdo:hab1'
    if st == 'Other':
        r = EM_OTHER_RULES.get((st, hab1))
        if r: return r[0], r[1], 'from_mfdo:hab1'
    # sampletype default
    r = EM_SAMPLETYPE.get(st)
    if r: return r[0], r[1], 'from_mfdo:sampletype'
    return 'ENVO:00010483', 'environmental material', 'envo_root_class'

def get_cur_vegetation(leaf):
    # Use the most specific MFDO level that describes vegetation, as-is.
    # The original MFDO values ("Wheat, Winter", "Species-rich Nardus upland grassland")
    # are more informative than decomposed taxon parts.
    # Skip values that are metadata, not vegetation: "Free-living;", codes like "V37", "R", "Q"
    skip_patterns = ['Free-living', 'Non-saline', 'Saline', 'non-habitat']
    for lv in ['mfd_hab3', 'mfd_hab2', 'mfd_hab1']:
        val = leaf.get(lv, '').strip()
        if not val:
            continue
        if len(val) <= 3:
            continue  # skip codes like V37, R, Q, V11, V15, V1, V2, N1, T
        if any(p in val for p in skip_patterns):
            continue
        has_taxon = (lv, val) in VEGETATION_TAXON_VALUES
        has_veg_habitat = any(h in val.lower() for h in [
            'grass', 'forest', 'heath', 'scrub', 'meadow', 'woodland',
            'bog', 'fen', 'mire', 'dune', 'vegetation', 'trees', 'swamp',
        ])
        if has_taxon or has_veg_habitat:
            # Strip Danish legal designation prefix (§3 = Nature Protection Act section 3)
            cleaned = val.replace('§3 ', '') if val.startswith('§3 ') else val
            return cleaned
    return ''

def get_season(leaf):
    # Season should come from sampling_date, not crop variety names.
    # "Wheat, Winter" means winter wheat (cultivar), not sampled in winter.
    # Returning empty; crop variety info is in cur_vegetation and misc_param.
    return ''

# Geographic names from MFDO go into misc_param as named water body / region context.
# geo_loc_name will be populated from Nominatim (per-biosample, not per-leaf).
GEO_TO_MISC_PARAM = {
    'Baltic Sea': {'has_attribute_label': 'named water body', 'has_value_term_label': 'Baltic Sea'},
    'Kattegat': {'has_attribute_label': 'named water body', 'has_value_term_label': 'Kattegat'},
    'Skagerak': {'has_attribute_label': 'named water body', 'has_value_term_label': 'Skagerrak'},
    'Mariager fjord': {'has_attribute_label': 'named water body', 'has_value_term_label': 'Mariager Fjord'},
    'Lillebælt': {'has_attribute_label': 'named water body', 'has_value_term_label': 'Lillebaelt'},
}

def get_geo(leaf):
    # geo_loc_name from MFDO alone is always just "Denmark".
    # Nominatim provides the locality refinement per-biosample, not per-leaf.
    return ''

def get_geo_misc_params(leaf):
    """Return misc_param assertions for named water bodies that appear as MFDO facet values.
    (The 5 mapped water bodies are themselves the facet value, so a direct GEO_TO_MISC_PARAM
    lookup is equivalent to the former decomposition geographic_parts lookup.)"""
    assertions = []
    for lv in ['mfd_hab2', 'mfd_hab3']:
        mp = GEO_TO_MISC_PARAM.get(leaf.get(lv, ''))
        if mp:
            assertions.append(dict(mp))
    return assertions

def get_misc_param(leaf):
    all_assertions = []
    for lv in LEVELS:
        val = leaf.get(lv, '')
        if not val: continue
        mp = MISC_PARAM_MAP.get((lv, val), [])
        all_assertions.extend(mp)
    # Add geographic misc_params (named water bodies from MFDO)
    all_assertions.extend(get_geo_misc_params(leaf))
    if all_assertions:
        # Deduplicate by (attribute_label, value)
        seen = set()
        deduped = []
        for a in all_assertions:
            key = (a.get('has_attribute_label',''),
                   a.get('has_value_term_label', a.get('has_boolean_value', a.get('has_value_term_id',''))))
            if key not in seen:
                seen.add(key)
                deduped.append(a)
        return json.dumps(deduped, separators=(',', ':'))
    return ''

# --- Build crosswalk ---
# Forest hab3 -> cur_land_use (conifers / hardwoods / mix). Module scope so land_use_provenance
# can reference it directly. 'Non-native trees (exotic)' intentionally omitted: the label gives
# no tree type (LLM decomposition had empty taxon_parts, unmappable=true).
FOREST_HAB3_LAND_USE = {
    'Coniferous forest': 'conifers', 'Spruce': 'conifers', 'Larch': 'conifers',
    'Sitka': 'conifers', 'Douglas': 'conifers', 'Pine': 'conifers',
    'Deciduous trees': 'hardwoods', 'Beech': 'hardwoods', 'Pedunculate oak': 'hardwoods',
    'Aspen': 'hardwoods', 'Maple': 'hardwoods', 'Alder': 'hardwoods',
    'Willow': 'hardwoods', 'Birch': 'hardwoods',
    'Birch-coniferous mix': 'intermixed hardwood and conifers',
    'Birch swamp': 'hardwoods',
}

out_cols = (
    ['row_type'] +  # 'ontology_leaf' (279) or 'biosample_reconciliation' (rows added to make the join total)
    list(hdr) +  # all original MFDO columns
    ['n_samples',
     'env_broad_scale', 'env_broad_scale_provenance',
     'env_local_scale', 'env_local_scale_provenance',
     'env_medium', 'env_medium_provenance',
     'cur_vegetation', 'cur_vegetation_provenance',
     'cur_land_use', 'cur_land_use_provenance',
     'misc_param_json', 'misc_param_provenance',
     'underspecified_slots']  # triad slots left at a coarse root value (review aid)
)

# Coarse root CURIEs per triad slot: a value at one of these is the fallback, not a
# habitat-specific term. Specific biomes (cropland biome, forest biome) are NOT coarse --
# env_broad_scale is supposed to be a biome. Used to populate underspecified_slots.
COARSE_CURIES = {
    'env_broad_scale': {'ENVO:00000428'},                           # bare 'biome' only; 'terrestrial biome' is fine
    'env_local_scale': {'ENVO:01000408', 'ENVO:01000813'},          # environmental zone, astronomical body part
    'env_medium':      {'ENVO:00010483'},                           # environmental material
}

def underspecified_slots(row):
    """Pipe-joined list of triad slots whose value is a coarse root term; '' if all specific."""
    flagged = []
    for slot, coarse in COARSE_CURIES.items():
        val = row.get(slot, '')
        curie = val[val.rfind('[') + 1:val.rfind(']')].strip() if '[' in val and ']' in val else ''
        if curie in coarse:
            flagged.append(slot)
    return '|'.join(flagged)

out_rows = []
for leaf in ont_rows:
    # Skip completely empty rows
    if not any(leaf.get(lv, '').strip() for lv in LEVELS):
        continue
    st = leaf.get('mfd_sampletype', '')
    at = leaf.get('mfd_areatype', '')
    h1 = leaf.get('mfd_hab1', '')
    h2 = leaf.get('mfd_hab2', '')
    h3 = leaf.get('mfd_hab3', '')

    key = tuple(leaf.get(lv, '') for lv in LEVELS)
    n = sample_counts.get(key, 0)

    ebs_c, ebs_l, ebs_m = get_ebs(st, at, h1, h2)
    els_c, els_l, els_m = get_els(st, at, h1, h2, h3, leaf.get('Natura2000', '').strip())
    em_c, em_l, em_m = get_em(st, h1, h2, h3, leaf.get('EMPO', '').strip())

    cur_veg = get_cur_vegetation(leaf)
    # cur_land_use: try hab3 (FOREST_HAB3_LAND_USE, defined at module scope), then hab2, then (at, h1)
    land_use = ''
    if h3 and h3 in FOREST_HAB3_LAND_USE:
        land_use = FOREST_HAB3_LAND_USE[h3]
    if not land_use:
        land_use = CUR_LAND_USE_HAB2.get((st, at, h1, h2), CUR_LAND_USE_MAP.get((at, h1), ''))
    season = get_season(leaf)
    geo = get_geo(leaf)
    misc = get_misc_param(leaf)

    # Determine provenance for non-triad slots
    def veg_provenance(cur_veg, leaf):
        if not cur_veg: return ''
        for lv in ['mfd_hab3', 'mfd_hab2', 'mfd_hab1']:
            if leaf.get(lv, '').strip() == cur_veg:
                return f'from_mfdo:{lv.replace("mfd_", "")}'
        return 'from_mfdo:decomposed'

    def land_use_provenance(land_use, st, at, h1, h2, h3):
        if not land_use: return ''
        if h3 and h3 in FOREST_HAB3_LAND_USE:
            return 'from_mfdo:hab3'
        if (st, at, h1, h2) in CUR_LAND_USE_HAB2:
            return 'from_mfdo:hab2'
        if (at, h1) in CUR_LAND_USE_MAP:
            return 'from_mfdo:areatype+hab1'
        return 'from_mfdo:hab1'

    def misc_provenance(misc):
        if not misc: return ''
        return 'from_mfdo:decomposed'

    row = dict(leaf)
    row.update({
        'row_type': 'ontology_leaf',
        'n_samples': n,
        'env_broad_scale': format_pv(ebs_c, ebs_l),
        'env_broad_scale_provenance': ebs_m,
        'env_local_scale': format_pv(els_c, els_l),
        'env_local_scale_provenance': els_m,
        'env_medium': format_pv(em_c, em_l),
        'env_medium_provenance': em_m,
        'cur_vegetation': cur_veg,
        'cur_vegetation_provenance': veg_provenance(cur_veg, leaf),
        'cur_land_use': land_use,
        'cur_land_use_provenance': land_use_provenance(land_use, st, at, h1, h2, h3),
        'misc_param_json': misc,
        'misc_param_provenance': misc_provenance(misc),
    })
    out_rows.append(row)

# --- Reconciliation rows: make the per-leaf -> biosample join TOTAL ---
# A handful of db biosample 5-tuples match no ontology leaf: biogas is typed 'Other' in the db
# but 'Water' in the ontology (sampletype mismatch), and some bare soil/sediment samples carry
# no habitat. Emit one reconciliation row per such tuple so a plain 5-level join covers ALL
# biosamples. Flagged via provenance 'biosample_reconciliation:*'.
ont_keys = {tuple(r.get(l, '') for l in LEVELS) for r in out_rows}
by_subkey = {tuple(r.get(l, '') for l in LEVELS[1:]): r for r in out_rows}  # (areatype,hab1,hab2,hab3) -> a leaf
ROOT_ELS = 'environmental zone [ENVO:01000408]'
recon = []
for key, n in sample_counts.items():
    if key in ont_keys or not any(key):
        continue
    st, at, h1, h2, h3 = key
    saline = (h1 == 'Saltwater')
    row = {h: '' for h in out_cols}
    row['row_type'] = 'biosample_reconciliation'
    row['mfd_sampletype'], row['mfd_areatype'], row['mfd_hab1'], row['mfd_hab2'], row['mfd_hab3'] = key
    row['n_samples'] = n
    twin = by_subkey.get((at, h1, h2, h3))  # same habitat, different sampletype
    if st in ('Soil', 'Sediment', 'Water'):
        # Run the standard rule functions with the available context. This covers
        # biosamples whose habitat classification (hab1/hab2) has rules in the
        # existing dicts (e.g. Soil+Agriculture+Fields -> cropland biome /
        # agricultural field / agricultural soil) without needing hard-coded
        # per-case entries here. Fall back to saline/medium-specific floors only
        # when the rules don't resolve to something more specific.
        prov = 'biosample_reconciliation:floor'
        ebs_c, ebs_l, _ = get_ebs(st, at, h1, h2)
        els_c, els_l, _ = get_els(st, at, h1, h2, h3)
        em_c, em_l, _  = get_em(st, h1, h2, h3)
        ebs = format_pv(ebs_c, ebs_l)
        els = format_pv(els_c, els_l)
        em  = format_pv(em_c, em_l)
        # Saline-context overrides for Sediment/Water when rules resolve to a
        # non-saline default: prefer sea floor / sea / sea water for saltwater.
        if saline and st == 'Sediment' and els_c not in ('ENVO:00000482',):
            els = 'sea floor [ENVO:00000482]'
        if saline and st in ('Sediment', 'Water') and ebs_c not in ('ENVO:00000447',):
            ebs = 'marine biome [ENVO:00000447]'
        if saline and st == 'Water' and em_c not in ('ENVO:00002149',):
            em = 'sea water [ENVO:00002149]'
        cur_v = cur_l = misc = ''
    elif twin:
        # non-medium sampletype (e.g. biogas typed 'Other' in db vs 'Water' in ontology): the only
        # difference is the sampletype label, so copy the matching leaf's full mapping.
        prov = 'biosample_reconciliation:sampletype'
        ebs, els, em = twin['env_broad_scale'], twin['env_local_scale'], twin['env_medium']
        cur_v, cur_l, misc = twin['cur_vegetation'], twin['cur_land_use'], twin['misc_param_json']
    else:
        prov = 'biosample_reconciliation:floor'
        ebs, els, em = 'biome [ENVO:00000428]', ROOT_ELS, 'environmental material [ENVO:00010483]'
        cur_v = cur_l = misc = ''
    row['env_broad_scale'], row['env_local_scale'], row['env_medium'] = ebs, els, em
    row['cur_vegetation'], row['cur_land_use'], row['misc_param_json'] = cur_v, cur_l, misc
    for c in ('env_broad_scale_provenance', 'env_local_scale_provenance', 'env_medium_provenance'):
        row[c] = prov
    recon.append(row)
out_rows += recon
print(f'  + {len(recon)} reconciliation rows ({sum(r["n_samples"] for r in recon)} biosamples) -> 5-level join now total')

# Tag rows whose triad still carries a coarse root value (review aid).
for r in out_rows:
    r['underspecified_slots'] = underspecified_slots(r)

# Sort by sample impact (descending), then by the habitat 5-tuple for a deterministic,
# drift-guard-friendly order. High-impact mappings sort to the top for review.
out_rows.sort(key=lambda r: (-int(r.get('n_samples') or 0),
                             tuple(r.get(lv, '') for lv in LEVELS)))

with open('mfdo_nmdc_crosswalk.tsv', 'w') as f:
    writer = csv.DictWriter(f, fieldnames=out_cols, delimiter='\t', extrasaction='ignore', lineterminator='\n')
    writer.writeheader()
    for r in out_rows:
        writer.writerow(r)

print(f'Wrote {len(out_rows)} rows to mfdo_nmdc_crosswalk.tsv')

# Stats -- per-leaf coverage is computed over ontology leaves only (reconciliation rows
# excluded, so 'specific' counts are not inflated by their floored placeholders).
leaves = [r for r in out_rows if r['row_type'] == 'ontology_leaf']
def _specific(col, prov):
    return sum(1 for r in leaves if r[col] and 'envo_root_class' not in r[prov] and 'reconciliation' not in r[prov])
has_ebs = _specific('env_broad_scale', 'env_broad_scale_provenance')
has_els = _specific('env_local_scale', 'env_local_scale_provenance')
has_em = sum(1 for r in leaves if r['env_medium'])
has_veg = sum(1 for r in leaves if r['cur_vegetation'])
has_lu = sum(1 for r in leaves if r['cur_land_use'])
has_misc = sum(1 for r in leaves if r['misc_param_json'])
has_samples = sum(1 for r in leaves if r['n_samples'] > 0)

print(f'\nCoverage across {len(leaves)} ontology leaves ({len(out_rows)-len(leaves)} reconciliation rows excluded):')
print(f'  with samples:       {has_samples}')
print(f'  env_broad_scale:    {has_ebs} specific + {len(leaves)-has_ebs} fallback')
print(f'  env_local_scale:    {has_els} specific + {len(leaves)-has_els} fallback')
print(f'  env_medium:         {has_em}')
print(f'  cur_vegetation:     {has_veg}')
print(f'  cur_land_use:       {has_lu}')
print(f'  misc_param:         {has_misc}')
