#!/bin/bash

set -euo pipefail

# Set the base directory
script_dir="$(cd "$(dirname "$0")" && pwd)"
output_dir="$(cd "${script_dir}/../.." && pwd)"
hist_period='1990_2022_t'

# Use YEAR when supplied; otherwise detect the latest year from step 5.
latest_year="${YEAR:-$(ls ${output_dir}/step_5/ERA5_*_ERA5_filled_*.nc | grep -Eo '[0-9]{4}' | sort -nr | head -1)}"

# Determine the reference year for historical observations
if (( latest_year % 4 == 0 && (latest_year % 100 != 0 || latest_year % 400 == 0) )); then
    ref_year=1992  # Leap year reference
else
    ref_year=1994  # Non-leap year reference
fi

echo "Processing step 8 for year: $latest_year using reference year: $ref_year"

# All variables and time periods
vars="${*:-tas tasrange tasskew pr rsds hurs sfcWind}"
pers="$latest_year"

# Path to ISIMIP3BASD scripts
cdir="${output_dir}/isimip3basd-master/code"
idir_era5="${output_dir}/step_5"
idir_emo="${output_dir}/step_7"
odir="${output_dir}/step_8"

# Multiprocessing compatibility:
# ISIMIP3BASD uses local initializer functions in multiprocessing pools,
# which fails with macOS spawn start method. Use single process by default on macOS.
if [[ "$(uname -s)" == "Darwin" ]]; then
  basd_nproc_default=1
else
  basd_nproc_default=16
fi
basd_nproc="${BASD_NPROCS:-$basd_nproc_default}"
echo "Using BASD processes: $basd_nproc"

# Iterate over all variables and periods
for var in $vars; do
  for per in $pers; do
    echo "Processing var: $var, period: $per"
    
    # Define file paths with dynamic reference year
    obs_hist_fine=$idir_emo/EFAS_${var}_${ref_year}.nc
    obs_hist_coarse=$idir_emo/EFAS_${var}_${hist_period}_aggregate.nc
    sim_hist_coarse=$idir_era5/ERA5_${var}_ERA5_${hist_period}.nc
    sim_fut_coarse=$idir_era5/ERA5_${var}_ERA5_filled_${per}.nc
    sim_fut_for_ba=$sim_fut_coarse
    tmp_sim_fut=""
    sim_fut_basd_coarse=$odir/ERA5_${var}_ERA5_filled_${per}_ba.nc
    sim_fut_basd_fine=$odir/ERA5_${var}_ERA5_filled_${per}_basd.nc

    step_size_ba=1
    if (( per % 4 != 0 || (per % 100 == 0 && per % 400 != 0) )); then
      step_size_ba=0
    fi

    for required_file in "$obs_hist_fine" "$obs_hist_coarse" "$sim_hist_coarse" "$sim_fut_coarse"; do
      if [ ! -f "$required_file" ]; then
        echo "Missing required input file: $required_file"
        exit 1
      fi
    done
    
    # Set parameters based on variable
    case $var in
      hurs*)
        options_ba="-v hurs --lower-bound 0 --lower-threshold .01 --upper-bound 100 --upper-threshold 99.99 -t bounded --unconditional-ccs-transfer 1 --trendless-bound-frequency 1"
        options_sd="-v hurs --lower-bound 0 --lower-threshold .01 --upper-bound 100 --upper-threshold 99.99";;
      pr*)
        options_ba="-v pr --lower-bound 0 --lower-threshold .0000011574 --distribution gamma -t mixed"
        options_sd="-v pr --lower-bound 0 --lower-threshold .0000011574";;
      rsds*)
        # rsds data is in W/m2 (range ~0-450). upper-bound=1 was collapsing scale
        # when step_size=0 (non-leap year) because BASD then uses it as a literal ceiling.
        # 800 W/m2 is safely above any observed daily mean solar radiation in the domain.
        options_ba="-v rsds --lower-bound 0 --lower-threshold .0001 --upper-bound 800 --upper-threshold 799.99 -t bounded"
        # Some step_5 rsds files start at year-1-12-31; shift +1 day for BASD input.
        rsds_first_date=$(python - "$sim_fut_coarse" <<'PY'
import sys
import netCDF4 as nc
from netCDF4 import num2date

ds = nc.Dataset(sys.argv[1])
t = ds.variables['time']
d0 = num2date(t[:1], t.units, getattr(t, 'calendar', 'standard'))[0]
ds.close()
print(d0.strftime('%Y-%m-%d'))
PY
)
        if [[ "$rsds_first_date" != "${per}-01-01" ]]; then
          tmp_sim_fut="${odir}/tmp_ERA5_${var}_ERA5_filled_${per}_timefix.nc"
          cp "$sim_fut_coarse" "$tmp_sim_fut"
          python - "$tmp_sim_fut" <<'PY'
import sys
import netCDF4 as nc

ds = nc.Dataset(sys.argv[1], 'r+')
t = ds.variables['time']
t[:] = t[:] + 24
ds.close()
PY
          sim_fut_for_ba="$tmp_sim_fut"
          echo "Adjusted rsds sim_fut time axis (+1 day): $sim_fut_coarse -> $sim_fut_for_ba"
        fi
        if (( step_size_ba == 1 )); then
          options_ba="$options_ba -w 15"
        fi
        options_sd="-v rsds --lower-bound 0 --lower-threshold .01";;
      sfcWind*)
        options_ba="-v sfcWind --lower-bound 0 --lower-threshold .01 --distribution weibull -t mixed"
        options_sd="-v sfcWind --lower-bound 0 --lower-threshold .01";;
      tas)
        options_ba="-v tas --distribution normal -t additive -d 1"
        options_sd="-v tas";;
      tasrange)
        options_ba="-v tasrange --lower-bound 0 --lower-threshold .01 --distribution weibull -t mixed"
        options_sd="-v tasrange --lower-bound 0 --lower-threshold .01";;
      tasskew)
        options_ba="-v tasskew --lower-bound 0 --lower-threshold .0001 --upper-bound 1 --upper-threshold .9999 -t bounded"
        options_sd="-v tasskew --lower-bound 0 --lower-threshold .0001 --upper-bound 1 --upper-threshold .9999";;
      *)
        echo "Variable $var not supported ... aborting ..."
        exit 1;;
    esac

    # Perform bias adjustment
    time python -u $cdir/bias_adjustment.py $options_ba \
    --n-processes $basd_nproc \
    --randomization-seed 0 \
    --step-size $step_size_ba \
    -o $obs_hist_coarse \
    -s $sim_hist_coarse \
    -f $sim_fut_for_ba \
    -b $sim_fut_basd_coarse

    if [ ! -f "$sim_fut_basd_coarse" ]; then
      echo "Bias adjustment output missing: $sim_fut_basd_coarse"
      exit 1
    fi
    chmod 664 $sim_fut_basd_coarse
    echo "Bias adjustment completed for $var, period $per"

    # Perform statistical downscaling
    time python -u $cdir/statistical_downscaling.py $options_sd \
    --n-processes $basd_nproc \
    --randomization-seed 0 \
    -o $obs_hist_fine \
    -s $sim_fut_basd_coarse \
    -f $sim_fut_basd_fine

    if [ ! -f "$sim_fut_basd_fine" ]; then
      echo "Statistical downscaling output missing: $sim_fut_basd_fine"
      exit 1
    fi
    chmod 664 $sim_fut_basd_fine
    echo "Statistical downscaling completed for $var, period $per"
    if [[ -n "$tmp_sim_fut" && -f "$tmp_sim_fut" ]]; then
      rm -f "$tmp_sim_fut"
    fi
    echo
  done
done

echo "Step 8 completed successfully for year $latest_year."
