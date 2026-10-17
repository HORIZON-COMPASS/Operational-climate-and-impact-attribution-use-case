#!/bin/bash
set -euo pipefail

# Output directory
script_dir="$(cd "$(dirname "$0")" && pwd)"
output_dir="$(cd "${script_dir}/../.." && pwd)"

# Use YEAR when supplied; otherwise process the current operational year.
START_YEAR="${YEAR:-$(date +%Y)}"

# Dynamically detect available ERA5 monthly files
files=()
for month in {1..12}; do
    infile="${output_dir}/step_1/ERA5_${START_YEAR}_${month}.grib"
    if [[ -s "$infile" ]]; then
        files+=("$infile")
    elif [[ -f "$infile" ]]; then
        echo "Skipping empty input file: $infile" >&2
    fi
done

# Optionally add January of the next year if available
next_jan_file="${output_dir}/step_1/ERA5_$((START_YEAR+1))_1.grib"
if [[ -s "$next_jan_file" ]]; then
    files+=("$next_jan_file")
elif [[ -f "$next_jan_file" ]]; then
    echo "Skipping empty next January file: $next_jan_file" >&2
fi

if [[ ${#files[@]} -eq 0 ]]; then
    echo "No ERA5 monthly GRIB files found in ${output_dir}/step_1 for year ${START_YEAR}." >&2
    exit 1
fi

# Create output directory if it does not exist
mkdir -p "${output_dir}/step_2/ERA5_for_gapfill"

# Temporary directory for normalized merged input
TMP_DIR="${output_dir}/step_2/tmp/run_${START_YEAR}_$$"
mkdir -p "${TMP_DIR}"
trap 'rm -rf "${TMP_DIR}"' EXIT

# Merge once and normalize variable names for cross-platform compatibility.
# On some CDO/ecCodes builds variables are exposed as var165/var166/... instead of 10u/10v/2t/2d/ssrd/tp.
cdo -O -f nc -mergetime "${files[@]}" "${TMP_DIR}/merged_raw.nc"
cdo -O \
    -chname,var165,10u \
    -chname,var166,10v \
    -chname,var168,2d  \
    -chname,var167,2t  \
    -chname,var169,ssrd \
    -chname,var228,tp \
    "${TMP_DIR}/merged_raw.nc" "${TMP_DIR}/merged_norm.nc"

# Define output files
o_tas="${output_dir}/step_2/ERA5_for_gapfill/tas_ERA5_${START_YEAR}.nc"
o_tasmin="${output_dir}/step_2/ERA5_for_gapfill/tasmin_ERA5_${START_YEAR}.nc"
o_tasmax="${output_dir}/step_2/ERA5_for_gapfill/tasmax_ERA5_${START_YEAR}.nc"
o_sfcWind="${output_dir}/step_2/ERA5_for_gapfill/sfcWind_ERA5_${START_YEAR}.nc"
o_rsds="${output_dir}/step_2/ERA5_for_gapfill/rsds_ERA5_${START_YEAR}.nc"
o_pr="${output_dir}/step_2/ERA5_for_gapfill/pr_ERA5_${START_YEAR}.nc"
o_hurs="${output_dir}/step_2/ERA5_for_gapfill/hurs_ERA5_${START_YEAR}.nc"

# Process ERA5 data
cdo -O -f nc -daymean -selname,2t "${TMP_DIR}/merged_norm.nc" "$o_tas"
cdo -O -f nc -daymin -selname,2t "${TMP_DIR}/merged_norm.nc" "$o_tasmin"
cdo -O -f nc -daymax -selname,2t "${TMP_DIR}/merged_norm.nc" "$o_tasmax"

# Process Rsds and Pr
cdo -O -f nc expr,rsds="ssrd*24/86400" -daymean -selname,ssrd "${TMP_DIR}/merged_norm.nc" "${output_dir}/temp_rsds.nc"
cdo -O -f nc expr,pr="tp*24/86.4" -daymean -selname,tp "${TMP_DIR}/merged_norm.nc" "${output_dir}/temp_pr.nc"

# Shift time and select only the current year
cdo selyear,$START_YEAR "${output_dir}/temp_rsds.nc" "$o_rsds"
cdo selyear,$START_YEAR "${output_dir}/temp_pr.nc" "$o_pr"

# Process dew point temperature and relative humidity
cdo -O expr,hurs="(10^(7.5*(2d-273.15)/(237.3+(2d-273.15))))/(10^(7.5*(2t-273.15)/(237.3+(2t-273.15))))*100" -daymean -selname,2d,2t "${TMP_DIR}/merged_norm.nc" "$o_hurs"

# Process wind speed
cdo -O -f nc expr,sfcWind="sqrt(10u*10u+10v*10v)" -daymean -selname,10u,10v "${TMP_DIR}/merged_norm.nc" "$o_sfcWind"

# Remove temporary files
rm -f "${output_dir}/temp_rsds.nc" "${output_dir}/temp_pr.nc"

echo "Processing complete for ERA5 year $START_YEAR."
