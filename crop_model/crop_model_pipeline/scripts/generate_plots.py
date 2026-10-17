import os
import glob
import re
import sys
from pathlib import Path
import fiona

CONDA_PREFIX = os.environ.get("CONDA_PREFIX", sys.prefix)
os.environ.setdefault("GDAL_DATA", os.path.join(CONDA_PREFIX, "share", "gdal"))

import geopandas as gpd
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from matplotlib.colors import Normalize
from shapely.geometry import shape

# --- CONFIGURATION ---
PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")
PLOTS_DIR = os.path.join(RESULTS_DIR, "plots")
SHAPEFILE_PATH = os.path.join(PROJECT_ROOT, "data/static/voivodeships.shp")


def parse_run_date(path):
    match = re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(path))
    return match.group(1) if match else None


def prune_stale_plots(valid_run_dates):
    if not os.path.exists(PLOTS_DIR):
        return

    removed = 0
    for path in Path(PLOTS_DIR).glob("*.jpeg"):
        run_date = parse_run_date(str(path))
        if run_date and run_date not in valid_run_dates:
            path.unlink()
            removed += 1

    if removed:
        print(f"Removed {removed} stale factual map files.")

def remove_stale_plot_variants(crop, run_date, keep_filename):
    removed = 0
    pattern = os.path.join(PLOTS_DIR, f"{crop}_*_{run_date}.jpeg")
    for path in glob.glob(pattern):
        if os.path.basename(path) != keep_filename:
            os.unlink(path)
            removed += 1
    return removed

def setup_directories():
    if not os.path.exists(PLOTS_DIR):
        os.makedirs(PLOTS_DIR)
        print(f"Created directory for plots: {PLOTS_DIR}")

def load_shapefile_no_crs(path):
    rows = []
    with fiona.open(path) as source:
        for feature in source:
            props = dict(feature["properties"])
            props["geometry"] = shape(feature["geometry"])
            rows.append(props)
    return gpd.GeoDataFrame(pd.DataFrame(rows), geometry="geometry")

def load_shapefile():
    print("Loading geographic boundaries...")
    gdf = load_shapefile_no_crs(SHAPEFILE_PATH)
    
    def clean_name(name):
        name = name.replace('Województwo ', '').replace('województwo ', '').strip()
        pl_to_ascii = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
        name = name.translate(pl_to_ascii).capitalize()
        targets = {"Kujawsko-pomorskie": "Kujawsko-pomorskie", "Warminsko-mazurskie": "Warminsko-mazurskie"}
        return targets.get(name, name)

    gdf['Province_Clean'] = gdf['nazwa'].apply(clean_name)
    
    # Calculate geometric centers for labels
    gdf['centroid_lon'] = gdf.geometry.representative_point().x
    gdf['centroid_lat'] = gdf.geometry.representative_point().y
    
    return gdf


def apply_map_axis_style(ax, bounds, mean_lat):
    minx, miny, maxx, maxy = bounds
    pad_x = (maxx - minx) * 0.04
    pad_y = (maxy - miny) * 0.04
    ax.set_xlim(minx - pad_x, maxx + pad_x)
    ax.set_ylim(miny - pad_y, maxy + pad_y)

    # Keep lon/lat maps visually closer to web-map projection proportions.
    lat_factor = np.cos(np.deg2rad(mean_lat))
    if lat_factor > 0:
        ax.set_aspect(1.0 / lat_factor)

    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

def generate_static_maps():
    setup_directories()
    gdf = load_shapefile()
    map_bounds = gdf.total_bounds
    mean_lat = float(gdf.geometry.centroid.y.mean())

    # Find all dated CSV files in the results directory
    csv_files = glob.glob(os.path.join(RESULTS_DIR, "predicted_yields_*.csv"))
    valid_run_dates = {parse_run_date(path) for path in csv_files if parse_run_date(path)}
    prune_stale_plots(valid_run_dates)
    
    for csv_path in csv_files:
        # Extract the date from the filename using regex
        match = re.search(r'predicted_yields_(\d{4}-\d{2}-\d{2})\.csv', csv_path)
        if not match:
            continue # Skip files that don't match the date pattern
            
        run_date = match.group(1)
        df = pd.read_csv(csv_path)
        
        # Standardize Province names in data
        df['Province_Clean'] = df['Province'].apply(
            lambda x: x.translate(str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")).capitalize()
        )
        
        requested_year = os.environ.get("COMPASS_TARGET_YEAR")
        latest_year = int(requested_year) if requested_year else int(df['year'].max())
        if latest_year not in set(df['year'].dropna().astype(int)):
            print(f"Skipping {csv_path}: requested year {latest_year} is absent.")
            continue
        current_df = df[df['year'] == latest_year]
        
        crops = current_df['crop'].unique()
        
        for crop in crops:
            # Check if this specific plot already exists
            output_filename = f"{crop}_{latest_year}_{run_date}.jpeg"
            output_filepath = os.path.join(PLOTS_DIR, output_filename)
            removed_variants = remove_stale_plot_variants(crop, run_date, output_filename)
            if removed_variants:
                print(f"Removed {removed_variants} stale factual plot variants for {crop} ({run_date}).")
            
            if os.path.exists(output_filepath):
                continue
                
            print(f"Generating plot: {output_filename}...")
            
            crop_df = current_df[current_df['crop'] == crop]
            merged = gdf.merge(crop_df, on='Province_Clean').reset_index()
            
            # --- Create Matplotlib figure ---
            fig, ax = plt.subplots(figsize=(15, 10), dpi=80)
            
            # Normalize yield values for color mapping
            norm = Normalize(vmin=merged['prediction'].min(), vmax=merged['prediction'].max())
            
            # Plot base map (all provinces in light gray)
            gdf.plot(ax=ax, color='#f0f0f0', edgecolor='white', linewidth=1.5)
            
            # Plot choropleth (colored by prediction)
            merged.plot(
                ax=ax,
                column='prediction',
                cmap='YlGn',
                norm=norm,
                edgecolor='white',
                linewidth=1.5,
                legend=True,
                legend_kwds={'label': 'Yield (dt/ha)', 'orientation': 'vertical', 'pad': 0.05}
            )
            
            # Add text annotations for each region
            for idx, row in merged.iterrows():
                # Determine text color based on background brightness
                mid_point = (merged['prediction'].max() + merged['prediction'].min()) / 2
                text_color = '#ffffff' if row['prediction'] > mid_point else '#1e1e1e'
                
                # Add province name and value
                ax.text(
                    row['centroid_lon'], row['centroid_lat'],
                    f"{row['Province_Clean']}\n{row['prediction']:.1f}",
                    ha='center', va='center',
                    fontsize=10, fontweight='bold',
                    color=text_color,
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='none', edgecolor='none', alpha=0)
                )
            
            # Remove axis labels and keep consistent map extent/proportions
            ax.set_xlabel('')
            ax.set_ylabel('')
            apply_map_axis_style(ax, map_bounds, mean_lat)
            
            # Add title
            plt.title(f"Projected Yield: {crop} ({latest_year})\nRun Date: {run_date}", 
                     fontsize=18, fontweight='bold', pad=20)
            
            plt.tight_layout()
            
            # Export to JPEG (Matplotlib uses PIL backend for JPEG)
            plt.savefig(output_filepath, format='jpeg', dpi=150, bbox_inches='tight')
            plt.close(fig)

    print("✅ All plots are up to date.")

if __name__ == "__main__":
    generate_static_maps()
