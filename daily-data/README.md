# Daily meteorological data preparation

This module prepares the factual and counterfactual meteorological products used by the COMPASS agricultural-impact workflow. It converts ERA5 and ERA5-Land inputs to daily fields, combines them with an EMO-1 reference, applies ISIMIP3BASD, and derives six variables for LISVAP and the crop model.

This is a code-only, researcher-operated workflow. It does not download every historical input, publish files, transfer them to a server, or provide a scheduler.

## Output contract

For a target year `YEAR`, the final factual and counterfactual directories contain:

| File | Variable | Expected unit |
|---|---|---|
| `tn_YEAR.nc` | daily minimum near-surface temperature | °C |
| `tx_YEAR.nc` | daily maximum near-surface temperature | °C |
| `pr_YEAR.nc` | daily precipitation | mm/day |
| `rg_YEAR.nc` | surface solar radiation | J/m²/day |
| `pd_YEAR.nc` | vapour-pressure quantity used by LISVAP | hPa |
| `ws_YEAR.nc` | near-surface wind speed | m/s |

The module hand-offs are:

```text
step_8/       factual BASD fields consumed by ATTRICI
step_10/      final factual products consumed by the crop model
step_8_cf/    ATTRICI counterfactual fields in the step_8 contract
step_10_cf/   final counterfactual products consumed by the crop model
```

Treat filenames, internal variable names, units, calendars, coordinates, masks, and grid orientation as part of the interface.

## Install the environment

Run from the repository root:

```bash
conda env create -f environments/daily-data.yml
conda activate compass-daily-data
```

The environment provides Python, CDO, NCO, ecCodes, NetCDF, xarray, and mapping libraries. The scripts expect the ISIMIP3BASD source tree separately at:

```text
daily-data/isimip3basd-master/code/
```

The scripts call `bias_adjustment.py` and `statistical_downscaling.py` from that directory. Obtain the compatible source and retain its version or commit with the run record. The fuller [COMPASS Integration of datasets and models](https://github.com/HORIZON-COMPASS/Integration-of-datasets-and-models) repository documents the original preparation process.

## Supply the inputs

No meteorological data or credentials are included. Provide:

- ERA5 hourly single-level fields used by the scripts;
- ERA5-Land hourly fields used by the scripts;
- converted EMO-1 daily reference fields;
- the historical ERA5 and EMO-1 files expected by step 8;
- a licensed voivodeship boundary dataset for optional maps.

Configure CDS API credentials in the normal user-level CDS configuration, outside this repository. Record every dataset identifier, release/version, time range, geographic subset, acquisition date, licence, and checksum.

The public snapshot does not include the project-specific EMO-1 conversion and historical-reference construction formerly represented by steps 3 and 4. Prepare these inputs using the integration repository above, then place compatible files under:

```text
step_3/emo_data/EFAS_converted/
step_4/merge_emo1/
```

The required filenames can be read directly from `cron_step_6.sh`, `cron_step_7.sh`, and `cron_step_8.sh`. Do not proceed until their reference years, grid descriptor, historical period (`1990_2022_t`), variables, units, and calendars match the scripts.

For optional maps, follow [`shp/README.md`](shp/README.md). Boundary data are deliberately not distributed here.

## Create working directories and run preflight

From the repository root:

```bash
mkdir -p daily-data/step_{1..10} \
  daily-data/step_2/ERA5_land_daily \
  daily-data/step_2/ERA5_for_gapfill \
  daily-data/step_8_cf daily-data/step_9_cf daily-data/step_10_cf

python scripts/check_installation.py --module daily-data --year 2025
```

The preflight reports missing tools and user-supplied material. A missing item is not downloaded automatically.

## Process one factual year

Work from `daily-data/SCRIPTS/cron`. Start with one known year and run scripts individually so every interface can be inspected.

1. Download or stage ERA5 and ERA5-Land monthly inputs:

   ```bash
   python cron_step_1.py --year 2025 --months 1-12
   ```

   Use a shorter month list such as `1,2,3` when testing. The default for the current year is the elapsed months; a historical year defaults to all months.

   Pin the same year for the shell stages. If `YEAR` is omitted, early operational stages use the current year and later stages detect the newest available input:

   ```bash
   export YEAR=2025
   ```

2. Create and validate daily ERA5-Land and ERA5 fields:

   ```bash
   bash cron_step_2_a_land.sh
   bash cron_step_2_b_land_lastday.sh
   bash cron_step_2_c_fill_land.sh
   bash cron_step_2_a_era.sh
   bash cron_step_2_d_era_lastday.sh
   bash cron_step_2_e_fill_era.sh
   ```

3. After supplying the prepared historical EMO-1/ERA5 references, run:

   ```bash
   bash cron_step_5.sh
   bash cron_step_6.sh
   bash cron_step_7.sh
   BASD_NPROCS=4 bash cron_step_8.sh
   bash cron_step_9.sh
   bash cron_step_10_a_pd.sh
   bash cron_step_10_b_pr.sh
   bash cron_step_10_c_rg.sh
   bash cron_step_10_d_tn.sh
   bash cron_step_10_e_tx.sh
   bash cron_step_10_f_ws.sh
   ```

On macOS, step 8 defaults to one BASD worker for multiprocessing compatibility. On other systems it defaults to 16; set `BASD_NPROCS` to a value suitable for the available memory and cores.

Several scripts infer the newest year from upstream filenames. Keep only the intended run in the working directories, verify the year printed at the beginning of each step, and archive outputs before starting another year.

When `YEAR` is set, the included shell stages use it instead of automatic detection. Unset it after the run with `unset YEAR` if you want to return to current-year operation.

## Build the counterfactual branch

After the ATTRICI module has produced and validated `cfact` fields:

```bash
python extract_attrici_cfact_to_step8_cf.py --year 2025
bash cron_step_9_cf.sh
bash cron_step_10_a_pd_cf.sh
bash cron_step_10_b_pr_cf.sh
bash cron_step_10_c_rg_cf.sh
bash cron_step_10_d_tn_cf.sh
bash cron_step_10_e_tx_cf.sh
bash cron_step_10_f_ws_cf.sh
```

The extraction command defaults to the work layout documented in [`../attrici/counterfactual/README.md`](../attrici/counterfactual/README.md). Override `--attrici-dir`, `--reference-dir`, or `--output-dir` when using another layout.

Create factual diagnostic maps for an explicit window before using the optional counterfactual backfill helper:

```bash
python cron_step_10_x_maps.py \
  --year 2025 \
  --start-date 2025-07-09 \
  --end-date 2025-07-15
```

Optional comparison maps require an explicit date:

```bash
python cron_step_10_x_maps_cf.py \
  --year 2025 \
  --date 2025-07-15 \
  --output-dir ../../temp_maps_cf
```

## Validate every hand-off

For each annual NetCDF file, verify:

- exact date count, timestamp order, duplicates, gaps, and leap-day handling;
- internal variable name and unit;
- plausible range and missing-value fraction;
- monotonic latitude/longitude, grid orientation, mask, and compression;
- identical coordinates and timestamps for factual/counterfactual pairs;
- expected filename and year.

Useful checks include:

```bash
cdo sinfo ../../step_10/tn_2025.nc
cdo showtimestamp ../../step_10/tn_2025.nc
ncdump -h ../../step_10/tn_2025.nc
cdo diffn ../../step_10/tn_2025.nc ../../step_10_cf/tn_2025.nc
```

`cdo diffn` confirms that a pair differs; it does not establish scientific validity. Review numerical summaries and spatial patterns with xarray/CDO before handing products to ATTRICI or the crop model.

## Operational cautions

- Scripts can replace intermediate and output files. Use a copy of the data for first runs.
- `TOOL_PATH_PREFIX` may be set when CDO/NCO are installed outside the active environment; otherwise normal `PATH` resolution is used.
- Do not commit NetCDF/GRIB files, logs, credentials, local configuration, or generated maps.
- Preserve stdout/stderr, environment export, code commit, input/output checksums, and validation decisions for each run.
