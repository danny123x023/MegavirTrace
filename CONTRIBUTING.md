# Contributing to MegavirTrace

Thank you for helping. Three commitments shape every change; please keep them intact:

1. **Real NASA data, any region.** Test and synthetic data are always labelled and never presented as results.
2. **Honest significance.** Any change to the statistics must keep the Monte Carlo false-alarm tests passing
   (`tests/test_montecarlo.py`): at most 5% at r₁ = 0.3 and at most 7% at r₁ = 0.5. Do not loosen the
   thresholds.
3. **Every number traceable.** Numbers come only from `src/megavir/engine`. Verdict text comes only from the
   templates in `engine/verdict.py`. The AI may explain, but never computes.

## Setup

See the README's quick start. Run the tests before opening a pull request:

```bash
.venv/bin/ruff check src tests scripts && .venv/bin/ruff format --check src tests scripts
.venv/bin/python -m pytest -m "not db" -n auto
.venv/bin/python -m pytest -m db            # needs the local PostgreSQL (scripts/dev.sh start)
(cd web && npm run typecheck && npx playwright test)
```

## Common tasks

**Add a variable.**
1. Add the dataset and variable to `src/megavir/catalog/__init__.py`. Resolve the DOI with
   `python scripts/cmr_lookup.py SHORT_NAME:VERSION`; never type a DOI from memory. Write the plain definition,
   "why it can trend" and the caveat.
2. Add the product to `src/megavir/ingest/products.py`: fields, native grid, fill values, unit conversion,
   and any orientation trap.
3. Add a reader test on a fake file in the product's real layout (`tests/test_readers.py`).
4. Run `megavir-ingest test <product>`, look at the quick-look map, then `full`.

**Change a verdict.** Edit the templates in `engine/verdict.py`, in every language, and bump
`ENGINE_VERSION` in `api/service.py`, so stored results are recomputed (the fingerprint includes it).

**Add a language.** Add a template block to `TEMPLATES` and its words to `EFFECT_WORDS` in
`engine/verdict.py`, and its direction words to `UP` and `DOWN` in `ai/numbers.py`. Number formats come from
CLDR (Babel) automatically.

**Change the statistics.** Explain the change in `docs/methods.md` with a reference, keep the reference-library
tests (`tests/test_stats.py`) exact, and rerun the Monte Carlo suite. If the AR(1) variance model changes,
rebuild the table with `python scripts/build_ar1_table.py`.

## Rules for code

- Secrets live only in the server's `.env`, never in the repository or the browser. CI runs a secret scan.
- Dependencies are locked (`uv.lock`, `web/package-lock.json`). Install with `uv sync --locked` and `npm ci`.
- Downloaded files are untrusted: ingest code runs with `python -I`, and archives are extracted only by file
  name into the product's own folder.
- Accessibility: every chart has a table view and keyboard reading, colours come from the validated palette
  (`web/lib/palette.ts`), and the axe-core gate in light and dark must stay clean.

## Licence

By contributing you agree that your contribution is licensed under Apache 2.0.
