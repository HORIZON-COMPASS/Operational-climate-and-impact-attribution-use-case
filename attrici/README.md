# Counterfactual climate generation from pre-fitted traces

This module connects factual COMPASS climate fields to compatible pre-fitted ATTRICI traces. It uses the frozen runtime in `vendor/attrici` to create counterfactual core variables and derive the six climate products used by the impact workflow.

ATTRICI is a processing dependency in this workflow, not a new software product delivered by COMPASS. The vendored source is a compatibility snapshot that preserves the demonstrator's execution path. It does not resolve the upstream v2 issue reported for `pr` and `rsds`, and it must not be presented as a generally improved ATTRICI version. Read [`../KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md) before use.

## Supported COMPASS profile

This guide supports one execution profile:

- run through `counterfactual/cf_pipeline.py`;
- PyMC5;
- `modes = 4` and `full_extrapolation = true`;
- one compatible pre-fitted trace per core variable;
- the GMT predictor used with those traces;
- application to new factual data, without fitting new traces.

The SciPy and PyMC3 backends, rolling-window fitting, model calibration, and arbitrary direct use of the vendored ATTRICI CLI are outside the validated scope of this release.

## Frozen compatibility runtime

The vendored snapshot is based on upstream commit `0dae5b7`. Its local changes are recorded in [`../ATTRICI_MODIFICATIONS.md`](../ATTRICI_MODIFICATIONS.md). Install this exact copy through the supplied environment rather than installing an arbitrary ATTRICI version:

```bash
conda env create -f environments/attrici.yml
conda activate compass-attrici
attrici --help
```

Run the first command from the repository root.

## Required data

Data are not included. Supply annual factual BASD files in `daily-data/step_8` for:

```text
tas tasrange hurs rsds sfcWind pr
```

Supply one compatible fitted trace per variable and the GMT predictor used during fitting in `attrici/cfact`, or change the paths in your local configuration. The default filename conventions are:

```text
ERA5_{var}_ERA5_filled_{year}_basd.nc
{var}_ERA5_1950_2024_trace.nc
ssa_gmt_daily_1950_2024.nc
```

Trace files, factual inputs, and GMT must share the intended training configuration, units, calendars, and spatial grid. Treat each trace set and its GMT file as one calibrated unit: replacing or extending the GMT series without validation can change predictor scaling and invalidate the application.

## Configuration

Create an ignored local configuration:

```bash
cd attrici/counterfactual
cp settings.example.toml settings.local.toml
```

Relative paths are resolved from the configuration file. `attrici_bin` may be an executable name available on `PATH` or a path to an executable. Review the grid dimensions and every filename pattern before running.

## Data-only workflow

For one known year:

```bash
python cf_pipeline.py --config settings.local.toml align-input --year 2025
python cf_pipeline.py --config settings.local.toml run-attrici --year 2025
python cf_pipeline.py --config settings.local.toml derive-products --year 2025
```

Skip `align-input` when input and trace coordinates match exactly. Run the stages separately on first use so that intermediate outputs can be inspected.

The derived products are written below the configured `work_dir` and include factual and counterfactual `tn`, `tx`, `pr`, `rg`, `pd`, and `ws`. Follow the lower-level [`counterfactual/README.md`](counterfactual/README.md) for diagnostics and export to `daily-data/step_8_cf`.

## Minimum validation

Verify:

- the supported PyMC5, four-mode, trace-application profile is unchanged;
- exact trace/input coordinate compatibility;
- trace and GMT provenance and checksums;
- continuous, unique daily timestamps;
- plausible factual and counterfactual ranges;
- no missing spatial blocks or boundary seams;
- stable selected-cell comparisons;
- run logs for invalid or extreme quantile-mapping values replaced with factual values;
- factual-minus-counterfactual sign conventions;
- separate labelling of results made with this preserved implementation.
