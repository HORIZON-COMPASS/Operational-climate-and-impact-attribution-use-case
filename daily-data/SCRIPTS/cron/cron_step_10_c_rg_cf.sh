#!/bin/bash

set -euo pipefail
TOOL_PATH_PREFIX="${TOOL_PATH_PREFIX:-/opt/homebrew/bin:/usr/local/bin}"
export PATH="${TOOL_PATH_PREFIX}:$PATH"

# Set the base directories
script_dir="$(cd "$(dirname "$0")" && pwd)"
output_dir="$(cd "${script_dir}/../.." && pwd)"
ipath="${output_dir}/step_9_cf/"
epath="${output_dir}/step_2/ERA5_for_gapfill/"
opath="${output_dir}/step_10_cf/"

# Detect the year: use YEAR env var if set, otherwise take the latest from step_9_cf
if [ -n "${YEAR:-}" ]; then
    latest_year="$YEAR"
    if [ ! -f "${ipath}rg_${latest_year}.nc" ]; then
        echo "No rg_${latest_year}.nc found in ${ipath}"
        exit 1
    fi
else
    latest_year=$(ls ${ipath}rg_*.nc | grep -Eo '[0-9]{4}' | sort -nr | head -1)
    if [ -z "${latest_year:-}" ]; then
        echo "No rg_*.nc files found in ${ipath}"
        exit 1
    fi
fi

echo "Processing step_10_cf for year: $latest_year"

# Create output directory if not exists
mkdir -p "$opath"

# Compute BASD landmask, grid, and weights for regridding ERA5 (only needed once)
basd_file="${ipath}rg_${latest_year}.nc"  # Reference file from step 9
basd_mask="${opath}basd_landmask_pl2.nc"
grid_file="${opath}basd_grid.txt"
weight_file="${opath}ERA5_weights.nc"

factual_mask="${output_dir}/step_10/basd_landmask_pl2.nc"
factual_grid="${output_dir}/step_10/basd_grid.txt"
factual_weights="${output_dir}/step_10/ERA5_weights.nc"

basd_gridsize=$(cdo -s griddes "$basd_file" | awk '/gridsize/{print $3; exit}')
use_factual_assets=0
if [[ -f "$factual_mask" && -f "$factual_grid" && -f "$factual_weights" ]]; then
    factual_gridsize=$(cdo -s griddes "$factual_mask" | awk '/gridsize/{print $3; exit}')
    if [[ "$factual_gridsize" == "$basd_gridsize" ]]; then
        use_factual_assets=1
    fi
fi

if [[ "$use_factual_assets" -eq 1 ]]; then
    cp "$factual_mask" "$basd_mask"
    cp "$factual_grid" "$grid_file"
    cp "$factual_weights" "$weight_file"
else
    cdo -f nc4c -z zip -setmisstoc,0 -gtc,0 "$basd_file" "$basd_mask"
    cdo griddes "$basd_file" > "$grid_file"
    era5_file="${epath}rsds_ERA5_filled_${latest_year}.nc"
    [[ ! -f "$era5_file" ]] && era5_file="${epath}rsds_ERA5_${latest_year}.nc"
    cdo gennn,"$grid_file" "$era5_file" "$weight_file"
fi

# Define chunk dimensions (adjust as needed)
n_times=1
n_lats=142
n_lons=262

# Process the `ws` variable for the detected year
for y in $(seq "$latest_year" "$latest_year"); do  
    filename="${ipath}rg_${y}.nc"  # From step 9
    tile="$(basename "$filename" .nc | cut -d'_' -f2)"
    era5_file="${epath}rsds_ERA5_filled_${tile}.nc"  # From step 2
    [[ ! -f "$era5_file" ]] && era5_file="${epath}rsds_ERA5_${tile}.nc"
    era5_file_regrid="${epath}regrid_rsds_filled_ERA5_${tile}.nc"
    [[ ! -f "$era5_file_regrid" ]] && era5_file_regrid="${epath}regrid_rsds_ERA5_${tile}.nc"
    oname1="${opath}tb_$(basename "$filename" .nc).nc"
    oname2="${opath}tc_$(basename "$filename" .nc).nc"
    oname3="${opath}td_$(basename "$filename" .nc).nc"
    oname4="${opath}te_$(basename "$filename" .nc).nc"
    oname5="${opath}$(basename "$filename" .nc).nc"

    # Regrid and bias adjust wind speed data
    rg_var=$(cdo -s showname "$era5_file" | awk '{print $1}')
    cdo -f nc4c -z zip remap,"$grid_file","$weight_file" -expr,"rg=${rg_var}*86400" -shifttime,1days "$era5_file" "$era5_file_regrid"
    cdo -f nc4c -z zip ifthenelse "$basd_mask" "$filename" "$era5_file_regrid" "$oname1"
    cdo -f nc4c -z zip shifttime,0minutes "$oname1" "$oname2"

    # Set missing value attributes
    ncatted -O -a _FillValue,rg,o,s,-9999 "$oname2"
    ncatted -O -a missing_value,rg,o,s,-9999 "$oname2"

    # Apply data compression
    ncap2 -v -O -s 'rg=pack(rg,10000,0);' "$oname2" "$oname3"
    ncpdq -O --cnk_plc=g3d --cnk_dmn=time,$n_times --cnk_dmn=lat,$n_lats --cnk_dmn=lon,$n_lons -a time,lat,lon "$oname3" "$oname4"

    # Adapt time vector for regridded file
    ncap2 -O -s 'time=(time-24)/24;' "$oname4" "$oname5"

    # Keep a stable epoch for historical years to avoid shifted calendar dates.
    ncatted -a units,time,o,c,"days since 1950-01-01 00:00:00" "$oname5"

    # Remove temporary files explicitly
    rm -f "${opath}tb_rg_${y}.nc" "${opath}tc_rg_${y}.nc" "${opath}td_rg_${y}.nc" "${opath}te_rg_${y}.nc"
done

echo "Step_10_cf completed successfully for year $latest_year."
