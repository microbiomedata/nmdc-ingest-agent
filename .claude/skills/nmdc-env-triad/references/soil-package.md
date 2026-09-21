# Soil package valueset

For **soil** biosamples (MIxS `soil` or `MIMS.me.soil.*` package), the submission schema further restricts each env-triad slot to a package-specific value set (a small curated list of ENVO terms).

Before resolving any sentinel on a soil-package biosample, check whether `nmdc-submission-schema` is importable in the active environment:

```bash
uv run python -c "import nmdc_submission_schema" 2>&1 || echo "MISSING"
```

- **If present**: pull the allowed values from the soil package and prefer matches inside that valueset.
- **If absent (current default)**: fall back to the anchor-class descendants (`SKILL.md` § Slot anchor classes). **You must explicitly tell the source skill's report step** that the soil-package valueset constraint was not enforced, so the run summary calls it out as a known gap. Every soil-package run without `nmdc-submission-schema` should produce a "valueset constraint not enforced" line in the report — silent fall-back is a bug.

> **Future seam.** This reference will grow into its own `nmdc-soil-curation` skill the first time a second package's guidance lands (water, sediment, host-associated, built-environment). Until then, additions for non-soil packages should live alongside this section in matching subsections so the future split stays mechanical.
