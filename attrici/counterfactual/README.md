# COMPASS ATTRICI integration workflow

`cf_pipeline.py` orchestrates the data-side counterfactual workflow. It aligns grids when necessary, applies compatible pre-fitted ATTRICI traces through the frozen vendored runtime, derives demonstrator variables, and creates local diagnostics. It contains no model-training workflow, FTP or website deployment, or credential handling.

This wrapper is the supported public interface to the COMPASS ATTRICI compatibility snapshot. It is not an interface for developing or distributing a new ATTRICI version. The supported profile is PyMC5, four Fourier modes, full GMT extrapolation, and the trace/GMT pair used by the demonstrator; see [`../../KNOWN_LIMITATIONS.md`](../../KNOWN_LIMITATIONS.md).

## Prerequisites

- the `compass-attrici` environment from `environments/attrici.yml`;
- factual BASD files for all six core variables;
- compatible fitted traces and GMT predictor;
- adequate space for annual NetCDF intermediates;
- optional GeoPandas/Matplotlib environment and boundary shapefile for maps.

## Configure

```bash
cp settings.example.toml settings.local.toml
```

The local file is ignored by Git. Paths are resolved relative to the configuration file, except a bare `attrici_bin` executable name, which is resolved through `PATH`. Keep `modes = 4` and `full_extrapolation = true` for the documented COMPASS traces. Other values require a separately validated trace/calibration setup and are outside this release's supported profile.

Inspect the effective inputs before running:

```bash
python cf_pipeline.py --help
python cf_pipeline.py --config settings.local.toml run-attrici --help
python ../../scripts/check_installation.py --module attrici --year 2025 \
  --config settings.local.toml
```

## Commands

| Command | Function |
|---|---|
| `align-input` | align input coordinate values to the fitted trace grid |
| `run-attrici` | generate annual base factual/counterfactual fields |
| `derive-products` | derive `pd`, `pr`, `rg`, `tn`, `tx`, and `ws` |
| `plot-day` / `plot-day-batch` | create local selected-date comparisons |
| `report-day-grid` | write grid-level diagnostics for derived products |
| `report-day-core-grid` | inspect core ATTRICI `y` and `cfact` fields |
| `render-maps` | write optional local map images under `work_dir/maps` |

## Recommended first run

```bash
python cf_pipeline.py --config settings.local.toml align-input --year 2025
python cf_pipeline.py --config settings.local.toml run-attrici --year 2025
python cf_pipeline.py --config settings.local.toml derive-products --year 2025
```

Only use `--overwrite` after confirming the target work directory. If the grids already match, omit the alignment stage.

Generate numerical diagnostics for a representative date:

```bash
python cf_pipeline.py --config settings.local.toml report-day-grid \
  --year 2025 \
  --date 2025-07-15 \
  --output-dir work/reports/2025-07-15
```

Generate optional comparison plots:

```bash
python cf_pipeline.py --config settings.local.toml plot-day-batch \
  --year 2025 \
  --date 2025-07-15 \
  --output-dir work/diagnostics/2025-07-15
```

## Work directory

The configured `work_dir` may contain:

```text
aligned_input/       optional coordinate-aligned inputs
annual_base/         core ATTRICI y/cfact fields
attrici_raw/         per-cell ATTRICI results
annual_products/     six derived variables by scenario
maps/                optional local figures
```

All generated products are ignored by Git.

## Hand-off to daily-data

After validating ATTRICI results, use `daily-data/SCRIPTS/cron/extract_attrici_cfact_to_step8_cf.py` to create the `daily-data/step_8_cf` interface. Then run the counterfactual step 9 and step 10 scripts described in `daily-data/README.md`.

Record the repository commit, configuration, environment export, trace/GMT checksums, target year, replacement warnings from the ATTRICI logs, validation reports, and output checksums.
