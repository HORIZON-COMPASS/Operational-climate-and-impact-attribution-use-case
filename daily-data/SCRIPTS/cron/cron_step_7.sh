#!/bin/bash
set -euo pipefail

# Set the base directory
script_dir="$(cd "$(dirname "$0")" && pwd)"
output_dir="$(cd "${script_dir}/../.." && pwd)"

# Use YEAR when supplied; otherwise detect the latest year from step 6.
latest_year="${YEAR:-$(ls ${output_dir}/step_6/*_filled_*.nc | grep -Eo '[0-9]{4}' | sort -nr | head -1)}"

# Determine the reference year (1994 for non-leap years, 1992 for leap years)
if (( latest_year % 4 == 0 && (latest_year % 100 != 0 || latest_year % 400 == 0) )); then
    ref_year=1992
else
    ref_year=1994
fi

echo "Processing step 7 for year: $latest_year (Using reference year: $ref_year)"

# Number of netCDF chunks (do not change)
n_lats=10
n_lons=10

# List of variables to process
variables=("rsds" "pr" "tas" "sfcWind" "hurs" "tasrange" "tasskew")  
types=("aggregate" "")  # 'aggregate' and the second type is empty

# Processing files for each variable and data type
for type in "${types[@]}"; do
    for var in "${variables[@]}"; do
        if [ -n "$type" ]; then
            filename="${output_dir}/step_6/${var}_filled_${latest_year}_${type}.nc"
        else
            filename="${output_dir}/step_3/emo_data/EFAS_converted/${var}_${ref_year}.nc"
        fi
        
        if [ -f "$filename" ]; then  # Check if the file exists
            n_times=$(cdo ntime "$filename" | awk 'NR==1 {print $1}')
            ncpdq -4 -O --cnk_plc=g3d --cnk_dmn=time,$n_times --cnk_dmn=lat,$n_lats --cnk_dmn=lon,$n_lons -a lon,lat,time "$filename" "${output_dir}/step_7/EFAS_$(basename "$filename" .nc).nc"
            echo "Processed: $filename -> ${output_dir}/step_7/EFAS_$(basename "$filename" .nc)"
        else
            echo "File $filename does not exist, skipping..."
        fi
    done
done

# Processing tasmin and tasmax files to tasrange and tasskew for both data types
for type in "${types[@]}"; do
    if [ -n "$type" ]; then
        tas="${output_dir}/step_6/tas_filled_${latest_year}_${type}.nc"
        tn="${output_dir}/step_6/tasmin_filled_${latest_year}_${type}.nc"
        tx="${output_dir}/step_6/tasmax_filled_${latest_year}_${type}.nc"
        tasrange="${output_dir}/step_6/tasrange_filled_${latest_year}_${type}.nc"
        tasskew="${output_dir}/step_6/tasskew_filled_${latest_year}_${type}.nc"
    else
        tas="${output_dir}/step_3/emo_data/EFAS_converted/tas_${ref_year}.nc"
        tn="${output_dir}/step_3/emo_data/EFAS_converted/tasmin_${ref_year}.nc"
        tx="${output_dir}/step_3/emo_data/EFAS_converted/tasmax_${ref_year}.nc"
        tasrange="${output_dir}/step_3/emo_data/EFAS_converted/tasrange_${ref_year}.nc"
        tasskew="${output_dir}/step_3/emo_data/EFAS_converted/tasskew_${ref_year}.nc"
    fi

    if [ -f "$tn" ] && [ -f "$tx" ]; then
        cdo -expr,tasrange="(( tasmax - tasmin ) > 0 ) ? ( tasmax - tasmin ) : ( tasmin - tasmax )" -merge "$tn" "$tx" "$tasrange"
        cdo -expr,tasskew=" ( tas - tasmin ) / ( tasmax - tasmin ) " -merge "$tn" "$tx" "$tas" "$tasskew"

        # Processing tasrange and tasskew files
        for file in "$tasrange" "$tasskew"; do
            if [ -f "$file" ]; then
                n_times=$(cdo ntime "$file" | awk 'NR==1 {print $1}')
                ncpdq -4 -O --cnk_plc=g3d --cnk_dmn=time,$n_times --cnk_dmn=lat,$n_lats --cnk_dmn=lon,$n_lons -a lon,lat,time "$file" "${output_dir}/step_7/EFAS_$(basename "$file" .nc).nc"
                echo "Processed: $file -> ${output_dir}/step_7/EFAS_$(basename "$file" .nc)"
            else
                echo "File $file does not exist, skipping..."
            fi
        done
    else
        echo "Files $tn or $tx do not exist, skipping..."
    fi
done

echo "Step 7 completed successfully for year $latest_year."
