#!/bin/bash

set -euo pipefail

TOOL_PATH_PREFIX="${TOOL_PATH_PREFIX:-/opt/homebrew/bin:/usr/local/bin}"
export PATH="${TOOL_PATH_PREFIX}:$PATH"

# Set the base directories
script_dir="$(cd "$(dirname "$0")" && pwd)"
output_dir="$(cd "${script_dir}/../.." && pwd)"

ipath="${output_dir}/step_9/"
epath="${output_dir}/step_2/ERA5_for_gapfill/"
opath="${output_dir}/step_10/"

# Detect the latest available year dynamically
latest_year="${YEAR:-$(ls ${ipath}tx_*.nc | grep -Eo '[0-9]{4}' | sort -nr | head -1)}"

if [ -z "${latest_year:-}" ]; then
    echo "No tx_*.nc files found in ${ipath}"
    exit 1
fi

echo "Processing step 10 for year: $latest_year"

# Create output directory if it does not exist
mkdir -p "$opath"

# Compute BASD landmask, grid, and weights for regridding ERA5 (only needed once)
basd_file="${ipath}tx_${latest_year}.nc"  # Reference file from step 9
basd_mask="${opath}basd_landmask_pl2.nc"
grid_file="${opath}basd_grid.txt"
weight_file="${opath}ERA5_weights.nc"

# Generate grid file
cdo griddes "$basd_file" > "$grid_file"

# Select the correct ERA5 file from step 2
era5_file="${epath}tasmax_ERA5_filled_${latest_year}.nc"

# Generate nearest-neighbor weights
cdo gennn,"$grid_file" "$era5_file" "$weight_file"

# Define chunk dimensions (adjust as needed)
n_times=1
n_lats=142
n_lons=262

# Process the `tx` variable for the detected year
for y in $(seq "$latest_year" "$latest_year"); do  
    filename="${ipath}tx_${y}.nc"  # From step 9
    tile="$(basename "$filename" .nc | cut -d'_' -f2)"
    era5_file="${epath}tasmax_ERA5_filled_${tile}.nc"  # From step 2
    era5_file_regrid="${epath}regrid_tasmax_filled_ERA5_${tile}.nc"
    oname1="${opath}tb_$(basename "$filename" .nc).nc"
    oname2="${opath}tc_$(basename "$filename" .nc).nc"
    oname3="${opath}td_$(basename "$filename" .nc).nc"
    oname4="${opath}te_$(basename "$filename" .nc).nc"
    oname5="${opath}$(basename "$filename" .nc).nc"

    # Apply remapping, correcting previous issue where tasmax and tasmin were swapped
    cdo -f nc4c -z zip remap,"$grid_file","$weight_file" -expr,tx="2t-273.15" "$era5_file" "$era5_file_regrid"

    # Apply conditional masking and time shifts
    cdo -f nc4c -z zip ifthenelse "$basd_mask" "$filename" "$era5_file_regrid" "$oname1"
    cdo -f nc4c -z zip shifttime,390minutes "$oname1" "$oname2"

    # Set missing value attributes
    ncatted -O -a _FillValue,tx,o,s,-9999 "$oname2"
    ncatted -O -a missing_value,tx,o,s,-9999 "$oname2"

    # Apply data compression
    ncap2 -v -O -s 'tx=pack(tx,0.1,0);' "$oname2" "$oname3"
    ncpdq -O --cnk_plc=g3d --cnk_dmn=time,$n_times --cnk_dmn=lat,$n_lats --cnk_dmn=lon,$n_lons -a time,lat,lon "$oname3" "$oname4"

    # Adapt time vector for regridded file
    ncap2 -O -s 'time=(time-24)/24;' "$oname4" "$oname5"

    # Update time reference units
    ncatted -a units,time,o,c,"days since $latest_year-01-01 00:00:00" "$oname5"

    # Remove temporary files explicitly
    rm -f "${opath}tb_tx_${y}.nc" "${opath}tc_tx_${y}.nc" "${opath}td_tx_${y}.nc" "${opath}te_tx_${y}.nc"
done

echo "Step 10 completed successfully for year $latest_year."
