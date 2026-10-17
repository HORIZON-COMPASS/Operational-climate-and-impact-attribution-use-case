#!/bin/bash
set -euo pipefail

# Set the base directory
script_dir="$(cd "$(dirname "$0")" && pwd)"
output_dir="$(cd "${script_dir}/../.." && pwd)"

# Use YEAR when supplied; otherwise detect the latest year from step 5.
latest_year="${YEAR:-$(ls ${output_dir}/step_5/ERA5_*_ERA5_filled_*.nc | grep -Eo '[0-9]{4}' | sort -nr | head -1)}"

# Determine which reference year to use (1994 for non-leap years, 1992 for leap years)
if (( latest_year % 4 == 0 && (latest_year % 100 != 0 || latest_year % 400 == 0) )); then
    ref_year=1992
else
    ref_year=1994
fi

echo "Processing step 6 for year: $latest_year (Using reference year: $ref_year)"

# List of variables to process
variables=("rsds" "pr" "tas" "sfcWind" "tasmax" "tasmin" "hurs")

## Process each variable
for var in "${variables[@]}"; do
    # ERA5Land file used to generate the grid file
    era5_name="${output_dir}/step_2/ERA5_land_daily/${var}_ERA5_filled_${latest_year}.nc"
    grid_file="${output_dir}/step_5/ERA5_${var}_ERA5_filled_${latest_year}_t_aggregate.txt"

    # Check if the file exists
    if [ ! -f "$era5_name" ]; then
        echo "File not found: $era5_name. Skipping..."
        continue
    fi

    # Generate the grid file
    cdo griddes "$era5_name" > "$grid_file"

    # EMO1 file and weight file using the reference year
    emo1_file="${output_dir}/step_3/emo_data/EFAS_converted/${var}_${ref_year}.nc"
    weight_file="${output_dir}/step_6/remap_weight_${var}_${ref_year}_t_aggregate.nc"
    efas_grid="${output_dir}/step_4/merge_emo1/efas_grid.txt"

    # Check if the EMO1 file from the reference year exists
    if [ ! -f "$emo1_file" ]; then
        echo "EMO1 file missing: $emo1_file. Skipping..."
        continue
    fi

    # Generate conservative remapping weights
    cdo gencon,"$grid_file" -setgrid,"$efas_grid" "$emo1_file" "$weight_file"

    # Remap the EMO1 file to the ERA5Land grid
    cdo remap,"$grid_file","$weight_file" "$emo1_file" "${output_dir}/step_6/${var}_filled_${latest_year}_aggregate.nc"

    echo "Processed variable: $var for year $latest_year"
done

echo "Step 6 completed successfully for year $latest_year."
