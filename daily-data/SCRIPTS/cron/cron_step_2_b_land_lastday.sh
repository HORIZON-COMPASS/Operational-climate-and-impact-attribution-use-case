#!/bin/bash
set -euo pipefail

# Use YEAR when supplied; otherwise process the current operational year.
CURRENT_YEAR="${YEAR:-$(date +%Y)}"

# Path to the directory containing data
script_dir="$(cd "$(dirname "$0")" && pwd)"
output_dir="$(cd "${script_dir}/../.." && pwd)"
input_dir="${output_dir}/step_2/ERA5_land_daily"

# List of variables to check
variables=("hurs" "pr" "rsds" "sfcWind" "tas" "tasmax" "tasmin")

for var in "${variables[@]}"; do
    input_file="${input_dir}/${var}_ERA5_${CURRENT_YEAR}.nc"

    if [[ -f "$input_file" ]]; then
        echo "Checking time consistency for: $var"

        # Retrieve all unique timestamps in the file
        unique_times=$(cdo showtime "$input_file" | awk '{for(i=2;i<=NF;i++) print $i}' | sort | uniq -c)

        # Find the most frequently occurring timestamp (assumed to be the correct one)
        expected_time=$(echo "$unique_times" | sort -nr | head -1 | awk '{print $2}')

        # Get the timestamp of the last recorded day
        last_time=$(cdo showtime "$input_file" | awk '{print $NF}')

        # If the last timestamp is different, remove the last day
        if [[ "$last_time" != "$expected_time" ]]; then
            echo "The last day in $var has a different time ($last_time instead of $expected_time), removing it..."
            cdo -O delete,timestep=-1 "$input_file" "${input_file}_fixed.nc"
            mv "${input_file}_fixed.nc" "$input_file"
            echo "Removed the last day with an incorrect timestamp in file: $input_file"
        else
            echo "All timestamps are consistent for: $var"
        fi
    else
        echo "File does not exist: $input_file, skipping."
    fi
done

echo "Timestamp validation and correction process completed!"
