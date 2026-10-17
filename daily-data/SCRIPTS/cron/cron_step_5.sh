#!/bin/bash
set -euo pipefail

# Set directories
script_dir="$(cd "$(dirname "$0")" && pwd)"
output_dir="$(cd "${script_dir}/../.." && pwd)"

# Use YEAR when supplied; otherwise detect the latest available filled year.
latest_year="${YEAR:-$(ls ${output_dir}/step_2/ERA5_land_daily/*_filled_*.nc | grep -Eo '[0-9]{4}' | sort -nr | head -1)}"

echo "Processing ERA5 filled data for year: $latest_year"

# Set NetCDF chunk size
n_lats=10
n_lons=10

# List of variables to process
variables=("hurs" "tas" "tasmin" "tasmax" "sfcWind" "rsds" "pr")

# Process each variable separately
for var in "${variables[@]}"; do
    filename="${output_dir}/step_2/ERA5_land_daily/${var}_ERA5_filled_${latest_year}.nc"
    
    # Check if file exists
    if [ ! -f "$filename" ]; then
        echo "File not found: $filename. Skipping..."
        continue
    fi

    n_times=$(cdo ntime "$filename" | awk 'NR==1 {print $1}')
    
    # Compress and chunk NetCDF data
    ncpdq -4 -O --cnk_plc=g3d --cnk_dmn=time,$n_times --cnk_dmn=lat,$n_lats --cnk_dmn=lon,$n_lons -a lon,lat,time "$filename" \
        "${output_dir}/step_5/ERA5_$(basename "$filename" .nc).nc"

    echo "Processed: $filename -> ${output_dir}/step_5/ERA5_$(basename "$filename" .nc).nc"
done

# **Additional transformations for tasrange and tasskew**
tn="${output_dir}/step_2/ERA5_land_daily/tasmin_ERA5_filled_${latest_year}.nc"
tx="${output_dir}/step_2/ERA5_land_daily/tasmax_ERA5_filled_${latest_year}.nc"
tas="${output_dir}/step_2/ERA5_land_daily/tas_ERA5_filled_${latest_year}.nc"
tasrange="${output_dir}/step_2/ERA5_land_daily/tasrange_ERA5_filled_${latest_year}.nc"
tasskew="${output_dir}/step_2/ERA5_land_daily/tasskew_ERA5_filled_${latest_year}.nc"

# Check if required files exist
if [ -f "$tn" ] && [ -f "$tx" ] && [ -f "$tas" ]; then
    echo "Processing tasrange and tasskew..."
    
    # Calculate tasrange (difference between tx and tn)
    cdo expr,tasrange="tx - tn" -merge -chname,2t,tn "$tn" -chname,2t,tx "$tx" "$tasrange"
    
    # Calculate tasskew (temperature skewness)
    cdo expr,tasskew=" ( tas - tn ) / ( tx - tn ) " -merge -chname,2t,tn "$tn" -chname,2t,tx "$tx" -chname,2t,tas "$tas" "$tasskew"

    # Chunking and saving to step_5
    n_times=$(cdo ntime "$tasrange" | awk 'NR==1 {print $1}')
    
    ncpdq -4 -O --cnk_plc=g3d --cnk_dmn=time,$n_times --cnk_dmn=lat,$n_lats --cnk_dmn=lon,$n_lons -a lon,lat,time "$tasrange" \
        "${output_dir}/step_5/ERA5_$(basename "$tasrange" .nc).nc"

    ncpdq -4 -O --cnk_plc=g3d --cnk_dmn=time,$n_times --cnk_dmn=lat,$n_lats --cnk_dmn=lon,$n_lons -a lon,lat,time "$tasskew" \
        "${output_dir}/step_5/ERA5_$(basename "$tasskew" .nc).nc"

    echo "Processed tasrange and tasskew successfully."
else
    echo "Skipping tasrange and tasskew – one or more required files are missing."
fi

# **Rename variable 2t -> tas only for tas file**
tas_nc_file="${output_dir}/step_5/ERA5_tas_ERA5_filled_${latest_year}.nc"
if [[ -f "$tas_nc_file" ]]; then
    echo "Renaming variable 2t -> tas in: $tas_nc_file"
    ncrename -v 2t,tas "$tas_nc_file"
    echo "Renamed 2t -> tas in $tas_nc_file"
fi

echo "Step 5 completed successfully for year $latest_year."
