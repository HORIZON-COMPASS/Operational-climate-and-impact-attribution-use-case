#!/bin/bash

set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
output_dir="$(cd "${script_dir}/../.." && pwd)"
opath="${output_dir}/step_9/"
TOOL_PATH_PREFIX="${TOOL_PATH_PREFIX:-/opt/homebrew/bin:/usr/local/bin}"
export PATH="${TOOL_PATH_PREFIX}:$PATH"

for tool in ncpdq cdo; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Required tool '$tool' not found in PATH=$PATH"
    exit 1
  fi
done

# Use YEAR when supplied; otherwise detect the latest year from step 8.
latest_year="${YEAR:-$(ls ${output_dir}/step_8/ERA5_*_ERA5_filled_*_basd.nc 2>/dev/null | grep -Eo '[0-9]{4}' | sort -nr | head -1)}"

if [ -z "${latest_year:-}" ]; then
  echo "No *_basd.nc files found in ${output_dir}/step_8. Run step 8 first."
  exit 1
fi

echo "Detected latest year: $latest_year"

mkdir -p "$opath"

required_step8_files=(
  "${output_dir}/step_8/ERA5_tas_ERA5_filled_${latest_year}_basd.nc"
  "${output_dir}/step_8/ERA5_tasrange_ERA5_filled_${latest_year}_basd.nc"
  "${output_dir}/step_8/ERA5_hurs_ERA5_filled_${latest_year}_basd.nc"
  "${output_dir}/step_8/ERA5_rsds_ERA5_filled_${latest_year}_basd.nc"
  "${output_dir}/step_8/ERA5_sfcWind_ERA5_filled_${latest_year}_basd.nc"
  "${output_dir}/step_8/ERA5_pr_ERA5_filled_${latest_year}_basd.nc"
)

for required_file in "${required_step8_files[@]}"; do
  if [ ! -f "$required_file" ]; then
    echo "Missing required step_8 output: $required_file"
    exit 1
  fi
done

###################################### 
#            1 - Temperature
###################################### 
tas="${output_dir}/step_8/ERA5_tas_ERA5_filled_${latest_year}_basd.nc"
tasrange="${output_dir}/step_8/ERA5_tasrange_ERA5_filled_${latest_year}_basd.nc"
tas_a="${opath}t_$(basename "$tas" .nc).nc"
tasrange_a="${opath}t_$(basename "$tasrange" .nc).nc"
ncpdq -O --cnk_plc=uck -a time,lat,lon "$tas" "$tas_a"
ncpdq -O --cnk_plc=uck -a time,lat,lon "$tasrange" "$tasrange_a"

for (( y=latest_year; y<=latest_year; y++ )); do
  tas_b="${opath}ta_$(basename "$tas" .nc)_${y}.nc"
  tasrange_b="${opath}ta_$(basename "$tasrange" .nc)_${y}.nc"
  cdo -L -f nc4c -z zip -selyear,$y "$tas_a" "$tas_b"
  cdo -L -f nc4c -z zip -selyear,$y "$tasrange_a" "$tasrange_b"
  tx="${opath}tx_${y}.nc"
  tn="${opath}tn_${y}.nc"
  cdo -L -f nc4c -z zip expr,tx="tas + 0.5 * tasrange - 273.15" -merge "$tas_b" "$tasrange_b" "$tx"
  cdo -L -f nc4c -z zip expr,tn="tas - 0.5 * tasrange - 273.15" -merge "$tas_b" "$tasrange_b" "$tn"
  rm "$tasrange_b" # don't remove tas_b, needed later
done
rm "$tas_a"
rm "$tasrange_a"

###################################### 
#            2 - Vapour pressure / Humidity
###################################### 
filename="${output_dir}/step_8/ERA5_hurs_ERA5_filled_${latest_year}_basd.nc"
oname1="${opath}t_$(basename "$filename" .nc).nc"
ncpdq -O --cnk_plc=uck -a time,lat,lon "$filename" "$oname1"

for (( y=latest_year; y<=latest_year; y++ )); do
  oname2="${opath}ta_$(basename "$filename" .nc)_${y}.nc"
  cdo -L -f nc4c -z zip -selyear,$y "$oname1" "$oname2"
  oname3="${opath}pd_${y}.nc"
  cdo -L -f nc4c -z zip expr,pd="hurs / 100 * (6.11 * 10 ^ (7.5 * (tas - 273.15) / (237.3+ (tas - 273.15) ) ))" -merge -shifttime,1days -selyear,$y "$oname2" -shifttime,630minutes "$tas_b" "$oname3"
done
rm "$oname1"

###################################### 
#            3 - Radiation
###################################### 
filename="${output_dir}/step_8/ERA5_rsds_ERA5_filled_${latest_year}_basd.nc"
oname1="${opath}t_$(basename "$filename" .nc).nc"
ncpdq -O --cnk_plc=uck -a time,lat,lon "$filename" "$oname1"

apply_rsds_shift=1
rsds_first_year=$(cdo -s showyear "$oname1" | awk '{print $1}')
if [[ -n "${rsds_first_year:-}" && "$rsds_first_year" -ge "$latest_year" ]]; then
  apply_rsds_shift=0
  echo "Radiation: rsds already aligned to ${latest_year}, skipping +1 day shift"
else
  echo "Radiation: rsds starts before ${latest_year}, applying +1 day shift"
fi

for (( y=latest_year; y<=latest_year; y++ )); do
  oname2="${opath}rg_${y}.nc"
  if (( apply_rsds_shift == 1 )); then
    cdo -L -f nc4c -z zip expr,rg="rsds * 86400" -shifttime,1days -selyear,$y "$oname1" "$oname2"
  else
    cdo -L -f nc4c -z zip expr,rg="rsds * 86400" -selyear,$y "$oname1" "$oname2"
  fi
done
rm "$oname1"

###################################### 
#            4 - Wind
###################################### 
filename="${output_dir}/step_8/ERA5_sfcWind_ERA5_filled_${latest_year}_basd.nc"
oname1="${opath}t_$(basename "$filename" .nc).nc"
ncpdq -O --cnk_plc=uck -a time,lat,lon "$filename" "$oname1"

for (( y=latest_year; y<=latest_year; y++ )); do
  oname2="${opath}ws_${y}.nc"
  cdo -L -f nc4c -z zip expr,ws="sfcWind" -shifttime,1days -selyear,$y "$oname1" "$oname2"
done
rm "$oname1" || { echo "Failed to remove $oname1"; exit 1; }

###################################### 
#            5 - Precipitation
###################################### 
filename="${output_dir}/step_8/ERA5_pr_ERA5_filled_${latest_year}_basd.nc"
oname1="${opath}t_$(basename "$filename" .nc).nc"
ncpdq -O --cnk_plc=uck -a time,lat,lon "$filename" "$oname1"

for (( y=latest_year; y<=latest_year; y++ )); do
  oname2="${opath}pr_${y}.nc"
  cdo -L -f nc4c -z zip mulc,86400 -shifttime,24hours -selyear,$y "$oname1" "$oname2"
done
rm "$oname1"
