import netCDF4 as nc
import os
import re
from datetime import datetime
from pathlib import Path

# --- CONFIGURATION ---
# Centralized project root
PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
METEO_FOLDER = os.path.join(PROJECT_ROOT, "lisvap/meteo/")
XML_PATH = os.path.join(PROJECT_ROOT, "lisvap/config/config.xml")

# Expected units mapping (Note: 'rg' set to J/m2 based on your raw data check)
MAPPING = {
    "tn": "degree_celsius",
    "tx": "degree_celsius",
    "pd": "hPa",
    "pr": "mm",
    "rg": "J/m2",
    "ws": "m/s"
}

def get_latest_year(folder):
    """Scans filenames for 4-digit years and returns the highest one."""
    if not os.path.exists(folder):
        return None
    files = os.listdir(folder)
    years = []
    for f in files:
        match = re.search(r'_(\d{4})\.nc', f)
        if match:
            years.append(int(match.group(1)))
    
    if not years:
        return None
    return max(years)

def patch_metadata(folder, year):
    """Fixes units for all files matching the detected year."""
    print(f"--- Step 1: Patching Metadata for Year {year} ---")
    for prefix, unit in MAPPING.items():
        file_path = os.path.join(folder, f"{prefix}_{year}.nc")
        if os.path.exists(file_path):
            try:
                # Open in 'a' (append) mode to edit attributes
                with nc.Dataset(file_path, 'a') as ds:
                    # Target the actual variable (ignoring lat/lon/time)
                    data_vars = [v for v in ds.variables if v not in ['time', 'lat', 'lon', 'latitude', 'longitude', 'crs']]
                    if data_vars:
                        target_var = data_vars[0]
                        ds.variables[target_var].units = unit
                        print(f"✅ {prefix}_{year}.nc: Units set to '{unit}' for variable '{target_var}'")
                    else:
                        raise RuntimeError(f"{prefix}_{year}.nc has no data variable")
            except Exception as e:
                raise RuntimeError(f"Error patching {file_path}: {e}") from e
        else:
            raise FileNotFoundError(f"Required meteorological input is missing: {file_path}")

def sync_xml(xml_path, folder, year):
    """Updates XML dates and file paths to match the latest year and data length."""
    print(f"--- Step 2: Synchronizing config.xml to Year {year} ---")
    
    # Use 'tn' file as the time reference for this year
    ref_file = os.path.join(folder, f"tn_{year}.nc")
    if not os.path.exists(ref_file):
        raise FileNotFoundError(f"Reference file is missing: {ref_file}")

    try:
        with nc.Dataset(ref_file, 'r') as ds:
            time_var = ds.variables['time']
            # Convert time indices to datetime objects
            times = nc.num2date(time_var[:], units=time_var.units, calendar=getattr(time_var, 'calendar', 'standard'))
            
            # Use 00:00 for the start time to ensure full day coverage
            start_str = times[0].strftime("%d/%m/%Y 00:00")
            end_str = times[-1].strftime("%d/%m/%Y 00:00")
            total_steps = len(times)
    except Exception as e:
        raise RuntimeError(f"Error reading time from {ref_file}: {e}") from e

    if not os.path.exists(xml_path):
        raise FileNotFoundError(f"LISVAP XML file is missing: {xml_path}")

    with open(xml_path, 'r') as f:
        content = f.read()

    # 1. Update Dates and Simulation Length
    content = re.sub(r'name="CalendarDayStart" value="[^"]+"', f'name="CalendarDayStart" value="{start_str}"', content)
    content = re.sub(r'name="StepStart" value="[^"]+"', f'name="StepStart" value="{start_str}"', content)
    content = re.sub(r'name="StepEnd" value="[^"]+"', f'name="StepEnd" value="{end_str}"', content)
    
    # ReportSteps tells LISVAP how many days to process (e.g., 1..55)
    content = re.sub(r'name="ReportSteps" value="[^"]+"', f'name="ReportSteps" value="1..{total_steps}"', content)

    # 2. Update File Paths inside XML (Ensures tx_2024.nc becomes tx_2026.nc etc.)
    content = re.sub(r'_[0-9]{4}\.nc', f'_{year}.nc', content)

    # 3. Rewrite LISVAP absolute paths for the current machine/workspace.
    content = re.sub(
        r'name="PathOut" value="[^"]+"',
        f'name="PathOut" value="{os.path.join(PROJECT_ROOT, "lisvap/output")}"',
        content,
    )
    content = re.sub(
        r'name="PathBaseMapsIn" value="[^"]+"',
        f'name="PathBaseMapsIn" value="{os.path.join(PROJECT_ROOT, "lisvap/basemap")}"',
        content,
    )
    content = re.sub(
        r'name="PathMeteoIn" value="[^"]+"',
        f'name="PathMeteoIn" value="{os.path.join(PROJECT_ROOT, "lisvap/meteo")}"',
        content,
    )

    with open(xml_path, 'w') as f:
        f.write(content)
    
    print(f"✅ config.xml updated for {year} (Total steps: {total_steps}).")

if __name__ == "__main__":
    latest_year = get_latest_year(METEO_FOLDER)
    if latest_year:
        print(f"🚀 Detected latest data year: {latest_year}")
        patch_metadata(METEO_FOLDER, latest_year)
        sync_xml(XML_PATH, METEO_FOLDER, latest_year)
    else:
        raise SystemExit("No valid NetCDF files found in the meteo folder.")
