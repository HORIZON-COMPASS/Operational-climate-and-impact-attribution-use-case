#!/bin/bash
set -euo pipefail

# Base directory
script_dir="$(cd "$(dirname "$0")" && pwd)"
output_dir="$(cd "${script_dir}/../.." && pwd)"

# Use YEAR when supplied; otherwise detect the latest available input year.
START_YEAR="${YEAR:-$(ls ${output_dir}/step_1/ERA5Land_*.grib | grep -Eo '[0-9]{4}' | sort -u | tail -n 1)}"

echo "Processing missing data for year: $START_YEAR"

# Paths to real data files (already processed in step 1)
o_tas="${output_dir}/step_2/ERA5_land_daily/tas_ERA5_${START_YEAR}.nc"
o_tasmin="${output_dir}/step_2/ERA5_land_daily/tasmin_ERA5_${START_YEAR}.nc"
o_tasmax="${output_dir}/step_2/ERA5_land_daily/tasmax_ERA5_${START_YEAR}.nc"
o_pr="${output_dir}/step_2/ERA5_land_daily/pr_ERA5_${START_YEAR}.nc"
o_rsds="${output_dir}/step_2/ERA5_land_daily/rsds_ERA5_${START_YEAR}.nc"
o_hurs="${output_dir}/step_2/ERA5_land_daily/hurs_ERA5_${START_YEAR}.nc"
o_sfcWind="${output_dir}/step_2/ERA5_land_daily/sfcWind_ERA5_${START_YEAR}.nc"

# Check existing days in the real data file
existing_days=$(cdo showdate "$o_tas" | tr ' ' '\n' | sort -u)

# Determine if the year is a leap year (366 days) or a non-leap year (365 days)
if (( START_YEAR % 4 == 0 && (START_YEAR % 100 != 0 || START_YEAR % 400 == 0) )); then
    num_days=366
else
    num_days=365
fi

# Generate a full list of days for the year
all_days=$(python3 - <<PY
import datetime
year = int("$START_YEAR")
start = datetime.date(year, 1, 1)
for i in range($num_days):
    print((start + datetime.timedelta(days=i)).isoformat())
PY
)

# Identify missing days
missing_days=$(comm -23 <(echo "$all_days" | sort) <(echo "$existing_days" | sort))

if [ -z "$missing_days" ]; then
    echo "All days are present. No missing data detected."
    exit 0
fi

echo "Detected missing days:"
echo "$missing_days"

# Paths to 30-year climatological daily mean data
clim_dir="${output_dir}/step_2/ERA5Land_30_filled/"
clim_tas="${clim_dir}/tas_ydaymean.nc"
clim_tasmin="${clim_dir}/tasmin_ydaymean.nc"
clim_tasmax="${clim_dir}/tasmax_ydaymean.nc"
clim_pr="${clim_dir}/pr_ydaymean.nc"
clim_rsds="${clim_dir}/rsds_ydaymean.nc"
clim_hurs="${clim_dir}/hurs_ydaymean.nc"
clim_sfcWind="${clim_dir}/sfcWind_ydaymean.nc"
clim_ntime=$(cdo -s ntime "$clim_tas" | awk 'NR==1 {print $1}')

# Fill missing days for each variable
for day in $missing_days; do
    day_of_year=$(python3 - <<PY
import datetime
print(datetime.date.fromisoformat("$day").timetuple().tm_yday)
PY
)
    # Align non-leap target years with 366-day climatology by skipping Feb 29.
    # Example: non-leap DOY 60 (Mar 1) -> climatology DOY 61.
    if (( num_days == 365 && clim_ntime == 366 && day_of_year >= 60 )); then
        day_sel=$((day_of_year + 1))
    else
        day_sel="$day_of_year"
    fi

    if (( day_sel > clim_ntime )); then
        day_sel="$clim_ntime"
    fi

    echo "Filling missing day: $day"

    # Create temporary files for each variable
    cdo -O -setyear,$START_YEAR -seltimestep,$day_sel "$clim_tas" "${output_dir}/tmp_tas_${day}.nc"
    cdo -O -setyear,$START_YEAR -seltimestep,$day_sel "$clim_tasmin" "${output_dir}/tmp_tasmin_${day}.nc"
    cdo -O -setyear,$START_YEAR -seltimestep,$day_sel "$clim_tasmax" "${output_dir}/tmp_tasmax_${day}.nc"
    cdo -O -setyear,$START_YEAR -seltimestep,$day_sel "$clim_pr" "${output_dir}/tmp_pr_${day}.nc"
    cdo -O -setyear,$START_YEAR -seltimestep,$day_sel "$clim_rsds" "${output_dir}/tmp_rsds_${day}.nc"
    cdo -O -setyear,$START_YEAR -seltimestep,$day_sel "$clim_hurs" "${output_dir}/tmp_hurs_${day}.nc"
    cdo -O -setyear,$START_YEAR -seltimestep,$day_sel "$clim_sfcWind" "${output_dir}/tmp_sfcWind_${day}.nc"
done

# Merge real data with the filled missing days
shopt -s nullglob
tmp_tas=("${output_dir}"/tmp_tas_*.nc)
tmp_tasmin=("${output_dir}"/tmp_tasmin_*.nc)
tmp_tasmax=("${output_dir}"/tmp_tasmax_*.nc)
tmp_pr=("${output_dir}"/tmp_pr_*.nc)
tmp_rsds=("${output_dir}"/tmp_rsds_*.nc)
tmp_hurs=("${output_dir}"/tmp_hurs_*.nc)
tmp_sfcWind=("${output_dir}"/tmp_sfcWind_*.nc)

if (( ${#tmp_tas[@]} )); then cdo -O -mergetime "$o_tas" "${tmp_tas[@]}" "${output_dir}/step_2/ERA5_land_daily/tas_ERA5_filled_${START_YEAR}.nc"; else cdo -O copy "$o_tas" "${output_dir}/step_2/ERA5_land_daily/tas_ERA5_filled_${START_YEAR}.nc"; fi
if (( ${#tmp_tasmin[@]} )); then cdo -O -mergetime "$o_tasmin" "${tmp_tasmin[@]}" "${output_dir}/step_2/ERA5_land_daily/tasmin_ERA5_filled_${START_YEAR}.nc"; else cdo -O copy "$o_tasmin" "${output_dir}/step_2/ERA5_land_daily/tasmin_ERA5_filled_${START_YEAR}.nc"; fi
if (( ${#tmp_tasmax[@]} )); then cdo -O -mergetime "$o_tasmax" "${tmp_tasmax[@]}" "${output_dir}/step_2/ERA5_land_daily/tasmax_ERA5_filled_${START_YEAR}.nc"; else cdo -O copy "$o_tasmax" "${output_dir}/step_2/ERA5_land_daily/tasmax_ERA5_filled_${START_YEAR}.nc"; fi
if (( ${#tmp_pr[@]} )); then cdo -O -mergetime "$o_pr" "${tmp_pr[@]}" "${output_dir}/step_2/ERA5_land_daily/pr_ERA5_filled_${START_YEAR}.nc"; else cdo -O copy "$o_pr" "${output_dir}/step_2/ERA5_land_daily/pr_ERA5_filled_${START_YEAR}.nc"; fi
if (( ${#tmp_rsds[@]} )); then cdo -O -mergetime "$o_rsds" "${tmp_rsds[@]}" "${output_dir}/step_2/ERA5_land_daily/rsds_ERA5_filled_${START_YEAR}.nc"; else cdo -O copy "$o_rsds" "${output_dir}/step_2/ERA5_land_daily/rsds_ERA5_filled_${START_YEAR}.nc"; fi
if (( ${#tmp_hurs[@]} )); then cdo -O -mergetime "$o_hurs" "${tmp_hurs[@]}" "${output_dir}/step_2/ERA5_land_daily/hurs_ERA5_filled_${START_YEAR}.nc"; else cdo -O copy "$o_hurs" "${output_dir}/step_2/ERA5_land_daily/hurs_ERA5_filled_${START_YEAR}.nc"; fi
if (( ${#tmp_sfcWind[@]} )); then cdo -O -mergetime "$o_sfcWind" "${tmp_sfcWind[@]}" "${output_dir}/step_2/ERA5_land_daily/sfcWind_ERA5_filled_${START_YEAR}.nc"; else cdo -O copy "$o_sfcWind" "${output_dir}/step_2/ERA5_land_daily/sfcWind_ERA5_filled_${START_YEAR}.nc"; fi

# Remove temporary files
rm -f "${output_dir}"/tmp_tas_*.nc
rm -f "${output_dir}"/tmp_tasmin_*.nc
rm -f "${output_dir}"/tmp_tasmax_*.nc
rm -f "${output_dir}"/tmp_pr_*.nc
rm -f "${output_dir}"/tmp_rsds_*.nc
rm -f "${output_dir}"/tmp_hurs_*.nc
rm -f "${output_dir}"/tmp_sfcWind_*.nc

echo "Missing data successfully filled for $START_YEAR."
