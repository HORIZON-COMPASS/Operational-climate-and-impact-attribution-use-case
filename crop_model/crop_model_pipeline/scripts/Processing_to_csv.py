import os
import re
import sys
from pathlib import Path
import fiona

CONDA_PREFIX = os.environ.get("CONDA_PREFIX", sys.prefix)
os.environ.setdefault("GDAL_DATA", os.path.join(CONDA_PREFIX, "share", "gdal"))

import geopandas as gpd
import numpy as np
import pandas as pd
import rioxarray
import xarray as xr
from rasterio.features import geometry_mask
from shapely.geometry import shape

# --- CONFIGURATION ---
# Centralized project root
PROJECT_ROOT = str(Path(__file__).resolve().parents[1])

# Paths according to the new automated structure
shapefile_path = os.path.join(PROJECT_ROOT, "data/static/voivodeships.shp")
netcdf_dir = os.path.join(PROJECT_ROOT, "lisvap/output") 
meteo_dir = os.path.join(PROJECT_ROOT, "lisvap/meteo")
historical_dir = os.path.join(PROJECT_ROOT, "data/historical")
final_output = os.path.join(historical_dir, "prediction_data.csv")

# We aggregate 'et' (from output), 'pr', and 'tx' (from meteo). 
# 'm' will be calculated manually from 'pr' and 'pet'.
var_mapping = {
    'et': 'pet', 
    'pr': 'pr', 
    'tx': 'tx'
}

# Ensure the historical directory exists (just in case)
if not os.path.exists(historical_dir):
    os.makedirs(historical_dir)

def detect_years(directory):
    if not os.path.exists(directory):
        return []
    files = os.listdir(directory)
    year_pattern = re.compile(r'_(\d{4})\.nc') 
    found_years = set()
    for f in files:
        match = year_pattern.search(f)
        if match:
            found_years.add(int(match.group(1)))
    return sorted(list(found_years))

def load_shapefile_no_crs(path):
    rows = []
    with fiona.open(path) as source:
        for feature in source:
            props = dict(feature["properties"])
            props["geometry"] = shape(feature["geometry"])
            rows.append(props)
    return gpd.GeoDataFrame(pd.DataFrame(rows), geometry="geometry")

# 1. LOAD EXISTING DATA
if os.path.exists(final_output):
    print(f"Loading existing data from {final_output}...")
    existing_df = pd.read_csv(final_output)
else:
    print(f"No existing prediction_data.csv found. Starting fresh in {historical_dir}.")
    existing_df = pd.DataFrame()

# 2. DETECT YEARS IN FOLDERS
# Usually, we check the meteo folder for all years that need processing
all_available_years = detect_years(meteo_dir)
requested_year = os.environ.get("COMPASS_TARGET_YEAR")
if requested_year:
    target_year = int(requested_year)
    years_to_process = [target_year] if target_year in all_available_years else []
else:
    # Retain the operational incremental default when this stage is run alone.
    years_to_process = [y for y in all_available_years if y >= 2024]

print(f"Years targeted for update/processing: {years_to_process}")

if not years_to_process:
    print("No new years to process. Exiting.")
    sys.exit(1)

if not os.path.exists(shapefile_path):
    print(f"❌ ERROR: Shapefile not found at {shapefile_path}")
    sys.exit(1)

poland_shapefile = load_shapefile_no_crs(shapefile_path)
results = []

# --- SPATIAL PROCESSING ---
for raw_var, model_prefix in var_mapping.items():
    # Use 'lisvap/output' for ET/PET, use 'lisvap/meteo' for raw weather (pr, tx)
    current_dir = netcdf_dir if raw_var == 'et' else meteo_dir
    
    for year in years_to_process:
        netcdf_file = os.path.join(current_dir, f'{raw_var}_{year}.nc')
        if not os.path.exists(netcdf_file):
            raise FileNotFoundError(f"Required model input is missing: {netcdf_file}")

        print(f"Aggregating {raw_var} for {year}...")
        ds = xr.open_dataset(netcdf_file)
        
        # Internal variable names match the filename prefix (et, pr, tx)
        nc_var_name = raw_var 
        var_data = ds[nc_var_name].rio.write_crs("EPSG:4326")

        for month in range(1, 13):
            # Select days within the specific month
            monthly_data = var_data.sel(time=var_data['time'].dt.month == month)
            if monthly_data.size == 0: continue

            for idx, voivodeship in poland_shapefile.iterrows():
                geometry = [voivodeship['geometry']]
                mask = geometry_mask(geometry, transform=var_data.rio.transform(), 
                                     invert=True, out_shape=var_data.shape[-2:])

                masked_month = monthly_data.where(mask)
                mean_val = masked_month.mean().item()

                results.append({
                    'Province': voivodeship['nazwa'],
                    'year': year,
                    'month': month,
                    'variable_prefix': model_prefix,
                    'value': mean_val
                })

# --- PIVOTING, CALCULATION & MERGING ---
if results:
    new_data_df = pd.DataFrame(results)

    # Clean Province Names (Removing Polish characters for model compatibility)
    def clean_province_name(name):
        name = name.replace('Województwo ', '').replace('województwo ', '').strip()
        pl_to_ascii = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
        name = name.translate(pl_to_ascii).capitalize()
        # Ensuring specific hyphenated targets are preserved correctly
        exact_targets = {"Kujawsko-pomorskie": "Kujawsko-pomorskie", "Warminsko-mazurskie": "Warminsko-mazurskie"}
        for k, v in exact_targets.items():
            if name.lower() == k.lower(): return v
        return name

    new_data_df['Province'] = new_data_df['Province'].apply(clean_province_name)
    new_data_df['column_name'] = new_data_df['variable_prefix'] + '_' + new_data_df['month'].astype(str)
    
    # Pivot to wide format (columns: pet_1, pet_2... pr_1, pr_2...)
    pivot_new = new_data_df.pivot_table(index=['Province', 'year'], 
                                        columns='column_name', 
                                        values='value').reset_index()

    # --- CALCULATE M (Pr - PET) ---
    print("Calculating Water Balance (m = pr - pet)...")
    for month in range(1, 13):
        pr_col = f'pr_{month}'
        pet_col = f'pet_{month}'
        m_col = f'm_{month}'
        
        if pr_col in pivot_new.columns and pet_col in pivot_new.columns:
            pivot_new[m_col] = (pivot_new[pr_col] - pivot_new[pet_col]).round(4)

    # Combine with historical data while preserving non-null historical values.
    # This protects rows when an incremental run has only partial variables (e.g., pr/tx present, et missing).
    if not existing_df.empty:
        existing_indexed = existing_df.set_index(['Province', 'year'])
        new_indexed = pivot_new.set_index(['Province', 'year'])
        final_indexed = new_indexed.combine_first(existing_indexed)
        final_df = final_indexed.reset_index()
    else:
        final_df = pivot_new

    # --- FIX COLUMN ORDER ---
    # Expected order: Province, year, pet_1..12, pr_1..12, tx_1..12, m_1..12
    ordered_cols = ['Province', 'year']
    for var in ['pet', 'pr', 'tx', 'm']:
        ordered_cols += [f"{var}_{m}" for m in range(1, 13)]
    
    # Ensure all columns exist, fill missing with NaN if necessary
    final_df = final_df.reindex(columns=ordered_cols)
    final_df = final_df.sort_values(by=['year', 'Province'])

    # SAVE TO MASTER CSV
    final_df.to_csv(final_output, index=False)
    print(f"✅ Success! Updated {final_output}. m_ columns calculated as (Pr - PET).")
else:
    print("No new data was processed.")
    sys.exit(1)
