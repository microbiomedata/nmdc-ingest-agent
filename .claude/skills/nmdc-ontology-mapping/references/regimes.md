# The regime decision

A mapping artifact earns its keep only when source terms are **closed** (an enumerable set)
and **recurring** (each term resolves many records). Measure both before building anything —
a "mapping" with one row per record is just the curation report with extra ceremony.

## Step 0 — reuse before build (do this first)

The operational gate is **Step 0 of `SKILL.md`** — if an authoritative mapping already exists
(a committed `examples/<project>/crosswalk/…`, a reusable `data/` lookup, or, for the env-triad,
a per-biosample crosswalk the ingest applies via `--env-triad-crosswalk`), apply it and stop; do
not author a new set. Kept here only for the worked signal of *why*: the classic trap is
MicroFlora Danica — its env-triad crosswalk (built from the full 5-level habitat ontology plus
GEE land-cover) already exists, so an agent seeing MFD's coarse `isolation_source` sentinels must
reuse that crosswalk, **not** re-derive a coarser mapping from `isolation_source`. Only reach
Step 1 (below) for a vocabulary with no existing mapping.

## How to measure

From the biosamples in scope, for the source field you'd map (e.g. `isolation_source`,
a habitat code, a land-cover class):

1. Count records `N` and distinct source values `D`.
2. Compute the amortization `N / D` — how many records the average mapping row resolves.

- `N / D` large (say ≥ 3–5) and `D` bounded → **Regime A/B**: build a set.
- `D ≈ N` (nearly every value unique) → **Regime C**: don't.

MicroFlora Danica is the archetypal Regime A: **284 crosswalk rows resolve ~10,689
biosamples** (37× amortization) because MFDO is a closed habitat ontology.

## The three regimes

**A — a reusable vocabulary already exists.** Source terms come from a published/closed set
with stable ids: CORINE or ESA WorldCover land-cover classes, GOLD ecosystem paths, EMPO, a
project's own habitat ontology. Map the whole vocabulary once; the set outlives the run and
other ingests reuse it. The crispest test: *does a closed valueset already exist for this
slot?* (NMDC's `SoilInterface`, for instance, enumerates 52/83/85 allowed env-triad values.)

**B — recurs but must be derived.** Free-text values with meaningful repetition and no
pre-existing vocabulary. Distill the distinct values into a normalized source-term list,
mint a local `curie_map` prefix for them (e.g. `MYPROJ:<slug>`), and map that list. The
subject side is agent-manufactured, but the amortization is still real.

**C — long-tail / near-unique free text.** No closed vocabulary and little repetition.
Building a set buys nothing. Hand back to `nmdc-env-triad` / `nmdc-taxon-resolution` for
per-record resolution; the durable artifact is the run notes + curation report, and any
genuinely one-off decisions live there, not in a table.

## Subject ids and the regime

SSSOM wants `subject_id` to be a CURIE/IRI. That requirement is itself a regime signal:
CORINE classes have ids (Regime A, near-ready); MFDO leaves and free-text strings do not
(Regime B — mint a local prefix — or Regime C — don't build a set).
