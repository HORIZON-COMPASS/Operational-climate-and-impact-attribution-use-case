# COMPASS ATTRICI compatibility snapshot

## Purpose and supported scope

This directory records the exact ATTRICI-derived runtime used by the COMPASS operational demonstrator to apply pre-fitted attribution models to new factual climate data. Its inclusion supports inspection and reproduction of that execution path.

It is **not** presented as a new ATTRICI version, an upstream-compatible replacement, or a generally improved implementation of the ATTRICI method. Scientific development and general use of ATTRICI remain with the [upstream project](https://github.com/ISI-MIP/attrici).

The public COMPASS workflow supports only the following profile:

- execution through `attrici/counterfactual/cf_pipeline.py`;
- the PyMC5 backend;
- four Fourier modes (`modes = 4`);
- application of compatible pre-fitted traces using `--trace-file`;
- the same GMT predictor and scaling basis used with those traces;
- generation of counterfactual fields from new factual inputs.

Fitting new traces, the rolling-window formulation, the SciPy and PyMC3 backends, and arbitrary direct use of the vendored CLI are not validated or supported by this public workflow.

## Provenance

- Upstream repository: <https://github.com/ISI-MIP/attrici>
- Upstream base commit: [`0dae5b791461c9d58e5da5d8dcd33b4d7fc2356c`](https://github.com/ISI-MIP/attrici/commit/0dae5b791461c9d58e5da5d8dcd33b4d7fc2356c) (`Reset coords before writing to NetCDF`)
- Local working-tree delta captured: 323 insertions and 619 deletions across five tracked files
- Licence: GNU GPL v3; see `LICENSE.txt`

The `v2.0.0` tag predates the actual base of the COMPASS modifications. Comparing against that tag would mix later upstream changes with COMPASS-specific changes. The base commit above is therefore the reproducible comparison point. The local package identifier `2.0.4.dev1+compass.1` is a provenance label for this snapshot, not an upstream ATTRICI release number.

## Modified files

| File | Purpose of the local change |
|---|---|
| `attrici/commands/detrend.py` | Keeps the CLI compatible with the COMPASS Fourier-mode configuration, which no longer exposes `window_size`. |
| `attrici/detrend.py` | Reuses trace scaling for new input periods, makes GMT scaling independent of the processed input window, improves grid/trace selection, skips empty cells, and adds safeguards for parallel PyMC/ArviZ execution. It also differs from the base commit's coordinate-reset behaviour when writing NetCDF files; writing new traces is outside the supported public path. |
| `attrici/estimation/model.py` | Stores optional Fourier/window metadata on parameter definitions and adds helper constructors expected by the local variable definitions. |
| `attrici/estimation/model_pymc5.py` | Falls back to parameter-level mode/window settings when call-level settings are absent. |
| `attrici/variables.py` | Reworks scaling restoration from saved traces, adds observation/predictor alignment and project-specific extreme-value guards, and adapts variable-specific model construction used by the operational workflow. |

Large docstring-only deletions are also present in `detrend.py` and `variables.py`; they do not by themselves describe scientific behaviour. The functional changes above should be reviewed together with the exact source.

## Interpretation of the functional changes

The trace-scaling and GMT-scaling changes are operational compatibility measures. They keep a new factual input period on the scale expected by the existing fitted traces; without that constraint, a short application window could be rescaled independently of the calibration period.

The extreme-value guards in `variables.py` are not claimed as a correction to the ATTRICI method. When triggered for precipitation, temperature range, or wind, they mark an extreme quantile-mapped value as invalid so that the runtime falls back to the factual value at that point. This can change a counterfactual result and must be treated as project-specific behaviour. Review run logs for replacements and record the result with the run provenance.

Parameter-level mode handling is completed only for the PyMC5 path used by COMPASS. Although solver choices inherited from upstream remain visible in parts of the CLI, the local SciPy and PyMC3 paths are not supported by this snapshot. The rolling-window path is likewise outside scope.

These constraints do not prevent the snapshot from documenting the historical demonstrator workflow. They do prevent interpreting the snapshot or its patch as a validated general-purpose ATTRICI release.


## Verify the recorded delta (optional)

The vendored package is the authoritative copy used to reproduce this COMPASS release. The following audit procedure is optional and is intended for maintainers or reviewers who want to verify the recorded delta. Run it from the root of the `COMPASS-public-release` repository.

Clone upstream, check out the exact base in detached mode, and compare it with the vendored source:

```bash
COMPASS_ROOT="$(pwd)"
ATTRICI_BASE="0dae5b791461c9d58e5da5d8dcd33b4d7fc2356c"

git clone https://github.com/ISI-MIP/attrici.git /tmp/attrici-upstream
git -C /tmp/attrici-upstream checkout --detach "$ATTRICI_BASE"
diff -ru \
  --exclude='__pycache__' \
  /tmp/attrici-upstream/attrici \
  "$COMPASS_ROOT/vendor/attrici/attrici" || test $? -eq 1
```

An exit status of `1` from `diff` is expected because the two trees intentionally differ. Any status greater than `1` indicates an error.

For a reviewable Git patch without changing either tree:

```bash
git diff --no-index \
  /tmp/attrici-upstream/attrici \
  "$COMPASS_ROOT/vendor/attrici/attrici" \
  > compass-attrici.patch || test $? -eq 1
```

Do not replace the vendored snapshot with a different upstream tag or commit without repeating the scientific validation described in `KNOWN_LIMITATIONS.md`. Do not publish the patch as a stand-alone ATTRICI update; it exists to make the COMPASS execution history reviewable.

The same five-file delta is included as `patches/attrici-compass.patch`. Verify and apply it to the clean upstream checkout with:

```bash
git -C /tmp/attrici-upstream apply --check \
  "$COMPASS_ROOT/patches/attrici-compass.patch"
git -C /tmp/attrici-upstream apply \
  "$COMPASS_ROOT/patches/attrici-compass.patch"
```

After applying the patch, repeating the directory comparison above should produce no output and return exit status `0`.

## Packaging-only adjustments

The vendored `pyproject.toml` is not part of the five-file runtime delta. To make the frozen snapshot installable inside this repository, it was adjusted to:

- use the included `README.upstream.md` filename and prepend that copied README with a COMPASS scope notice;
- identify the package explicitly as a frozen COMPASS compatibility snapshot in its metadata;
- assign the explicit local package version `2.0.4.dev1+compass.1` instead of deriving a version from an unavailable nested Git history;
- remove the corresponding `setuptools-scm` build dependency and configuration;
- include all `attrici.*` subpackages during wheel installation.

These changes affect packaging and provenance reporting, not the numerical implementation. The resulting package is intended only for the documented COMPASS environment.
