# Crop-impact model workflow

This module converts factual and counterfactual meteorological products into agricultural-impact estimates. Each branch stages six climate variables, runs LISVAP to calculate reference evapotranspiration, aggregates predictors, applies the crop-yield models, and creates local result tables and maps.

The repository contains code only. LISVAP configuration/basemaps, historical yield data, boundary files, climate inputs, and generated results are not included.

## Comparable branches

```text
crop_model_pipeline/       factual branch; reads daily-data/step_10
crop_model_pipeline_cf/    counterfactual branch; reads daily-data/step_10_cf
```

Use the same static data, boundary release, growing-season definitions, preprocessing, model dependencies, and LISVAP configuration in both branches. Only the factual/counterfactual meteorological input should differ.

## Install

Linux or Windows Subsystem for Linux with Conda/Mamba is recommended. From the repository root:

```bash
conda env create -f environments/crop-model.yml
conda activate compass-crop
lisvap --help
```

The supplied environment pins the main model libraries and installs LISVAP 1.4.0. Preserve the solved environment export with every scientific run; platform-specific dependency resolution may still differ.

The runners use these environment variables:

| Variable | Purpose | Default |
|---|---|---|
| `LISVAP_PYTHON` | Python executable used by pipeline stages | `python3` |
| `LISVAP_CMD` | LISVAP executable | `lisvap` |
| `LISVAP_CONDA_ENV` | Conda environment name | `compass-crop` |
| `LISVAP_USE_CONDA_RUN` | wrap each stage with `conda run` (`1` or `0`) | `1` |
| `CONDA_EXE` | explicit Conda executable | auto-detected |

If the environment is already active, either keep the default wrapper or run with:

```bash
export LISVAP_USE_CONDA_RUN=0
```

## Supply runtime data

For each branch, supply the omitted files described in its placeholder guides:

```text
crop_model_pipeline/
├── scripts/                         included
├── lisvap/
│   ├── config/config.xml            user supplied
│   ├── basemap/                     user supplied
│   ├── meteo/                       staged by the runner
│   └── output/                      generated
├── data/
│   ├── static/                      training table and boundaries
│   └── historical/                  generated prediction table
├── logs/                            generated
└── results/                         generated
```

Mirror the same material under `crop_model_pipeline_cf`. Read the `README.md` placeholders in `data/static`, `data/historical`, and `lisvap` for the expected role of each directory.

At minimum, each branch expects:

- `lisvap/config/config.xml` and every basemap referenced by it;
- `data/static/monthy_climate_original_yields.csv` (the historical filename is retained for compatibility);
- `data/static/voivodeships.shp` plus its complete shapefile sidecar set;
- `data/historical/prediction_data.csv`, created by the aggregation stage;
- compatible factual or counterfactual NetCDF inputs.

Review the column schemas accessed by `Processing_to_csv.py`, `data.py`, `modeling.py`, and `main.py`. The code intentionally does not fabricate absent training data or silently substitute another boundary dataset.

## Meteorological input contract

For `YEAR`, both `daily-data/step_10` and `daily-data/step_10_cf` must contain:

```text
pd_YEAR.nc
pr_YEAR.nc
rg_YEAR.nc
tn_YEAR.nc
tx_YEAR.nc
ws_YEAR.nc
```

The pair must have identical timestamps, coordinates, masks, units, and internal variable names. The runners copy the six files into their branch-specific `lisvap/meteo` directory.

## Preflight before any cleanup

From the repository root:

```bash
python scripts/check_installation.py \
  --module crop-model \
  --year 2025 \
  --scenario both
```

Each runner repeats its critical file checks before it copies inputs or removes stale runtime files. A failed preflight exits with code 2.

Also verify that the LISVAP periods and paths in both `config.xml` files match the intended year and local directory layout. XML files are machine/runtime configuration and should remain untracked unless a portable, data-free example is prepared.

## Run factual and counterfactual estimates

Use an explicit run date so output labels are deterministic:

```bash
python crop_model/crop_model_pipeline/scripts/run_pipeline.py \
  --year 2025 \
  --run-date 2025-07-15

python crop_model/crop_model_pipeline_cf/scripts/run_pipeline.py \
  --year 2025 \
  --run-date 2025-07-15
```

`--run-date` must belong to `--year`. If omitted, the model uses the newest available counterfactual comparison-map date and otherwise the current date; explicit use is recommended for reproducible runs.

The runner performs these stages:

1. validates inputs before mutation;
2. copies six target-year NetCDF files into `lisvap/meteo`;
3. removes other-year files from that staging directory and clears old LISVAP output;
4. patches input metadata with `prepare_lisvap.py`;
5. runs LISVAP with `lisvap/config/config.xml`;
6. aggregates precipitation and PET predictors with `Processing_to_csv.py`;
7. estimates crop yields with `main.py`;
8. creates local static maps; the counterfactual branch also creates comparison plots.

The cleanup is limited to branch runtime directories, but it is destructive. Archive results and LISVAP output before rerunning a year.

This public release contains no webhook, FTP transfer, or website-publishing operation. Generated products remain local until the user deliberately exports them.

## Diagnose a stage

The runner logs to the branch `logs/pipeline.log` and stops on the first failed command. To reproduce a failing factual stage with an already activated environment:

```bash
cd crop_model/crop_model_pipeline
python scripts/prepare_lisvap.py
lisvap lisvap/config/config.xml
python scripts/Processing_to_csv.py
COMPASS_RUN_DATE=2025-07-15 python scripts/main.py
python scripts/generate_plots.py
```

Use the counterfactual branch for an equivalent counterfactual diagnosis. Never continue to crop-yield prediction when meteorological staging or LISVAP validation has failed.

## Validation

For each run, verify:

- all six climate fields cover the same dates and grid;
- LISVAP processed exactly the intended period without stale inputs;
- evapotranspiration units, range, missing values, and spatial patterns are plausible;
- province aggregation uses the intended boundary identifiers;
- crop, month, province, year, and predictor columns match the model schema;
- factual and counterfactual outputs contain identical comparison keys;
- reported differences can be independently reproduced from source tables;
- missing data, extrapolation, and model failures remain visible.

Record the repository commit, Conda export, LISVAP/config checksums, climate-input checksums, training-table checksum, boundary provenance, run date, log, and validation decision.

