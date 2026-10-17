import os
import glob
import sys
from datetime import datetime
from pathlib import Path
import fiona

CONDA_PREFIX = os.environ.get("CONDA_PREFIX", sys.prefix)
os.environ.setdefault("GDAL_DATA", os.path.join(CONDA_PREFIX, "share", "gdal"))

import geopandas as gpd
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize, TwoSlopeNorm
import numpy as np
import pandas as pd
from shapely.geometry import shape

# --- CONFIGURATION ---
CF_ROOT = Path(__file__).resolve().parents[1]
CROP_MODEL_ROOT = CF_ROOT.parent
FACTUAL_DIR = str(CROP_MODEL_ROOT / "crop_model_pipeline" / "results")
CF_DIR = str(CF_ROOT / "results")
SHAPEFILE_PATH = str(CROP_MODEL_ROOT / "crop_model_pipeline" / "data" / "static" / "voivodeships.shp")

# Where to save the final 3-panel comparison plots
OUTPUT_DIR = str(CF_ROOT / "results" / "comparison_plots")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def load_shapefile_no_crs(path):
    rows = []
    with fiona.open(path) as source:
        for feature in source:
            props = dict(feature["properties"])
            props["geometry"] = shape(feature["geometry"])
            rows.append(props)
    return gpd.GeoDataFrame(pd.DataFrame(rows), geometry="geometry")

def extract_run_date(path):
    """Extract run date from predicted_yields_YYYY-MM-DD.csv filename."""
    base = os.path.basename(path)
    if not base.startswith("predicted_yields_") or not base.endswith(".csv"):
        return None
    date_str = base.replace("predicted_yields_", "").replace(".csv", "")
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None
    return date_str


def csvs_by_run_date(directory):
    """Return {run_date: file_path} for all dated prediction CSVs in a directory."""
    mapping = {}
    for path in glob.glob(os.path.join(directory, "predicted_yields_*.csv")):
        run_date = extract_run_date(path)
        if run_date:
            mapping[run_date] = path
    return mapping


def prune_stale_comparison_plots(valid_run_dates):
    removed = 0
    output_dir = Path(OUTPUT_DIR)
    if not output_dir.exists():
        return

    for path in output_dir.glob("Figure_Comparison_*.jpeg"):
        run_date = extract_run_date(str(path))
        if run_date and run_date not in valid_run_dates:
            path.unlink()
            removed += 1

    if removed:
        print(f"Removed {removed} stale comparison plot files.")

def remove_stale_comparison_variants(crop, run_date, keep_filename):
    removed = 0
    pattern = os.path.join(OUTPUT_DIR, f"Figure_Comparison_{crop}_*_{run_date}.jpeg")
    for path in glob.glob(pattern):
        if os.path.basename(path) != keep_filename:
            os.unlink(path)
            removed += 1
    return removed

def clean_province_name(name):
    """Ensures shapefile names perfectly match the CSV names."""
    name = name.replace('Województwo ', '').replace('województwo ', '').strip()
    pl_to_ascii = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
    name = name.translate(pl_to_ascii).capitalize()
    exact_targets = {"Kujawsko-pomorskie": "Kujawsko-pomorskie", "Warminsko-mazurskie": "Warminsko-mazurskie"}
    for k, v in exact_targets.items():
        if name.lower() == k.lower(): return v
    return name


def select_target_year(df_fact, df_cf):
    """Prefer the requested run year, then current year, then latest common year."""
    fact_years = set(df_fact["year"].dropna().astype(int).unique())
    cf_years = set(df_cf["year"].dropna().astype(int).unique())
    common_years = sorted(fact_years.intersection(cf_years))

    if not common_years:
        return None

    requested_year = os.environ.get("COMPASS_TARGET_YEAR")
    if requested_year:
        target_year = int(requested_year)
        if target_year in common_years:
            print(f"Using requested prediction year: {target_year}")
            return target_year
        print(f"Requested prediction year {target_year} is absent from a factual/CF pair.")
        return None

    current_year = datetime.today().year
    if current_year in common_years:
        print(f"Using current year from predictions: {current_year}")
        return current_year

    fallback_year = common_years[-1]
    print(
        f"Current year {current_year} is not available in prediction rows. "
        f"Falling back to latest common year: {fallback_year}"
    )
    return fallback_year


def apply_map_axis_style(ax, bounds, mean_lat):
    """Apply consistent bounds and mercator-like aspect ratio for lon/lat data."""
    minx, miny, maxx, maxy = bounds
    pad_x = (maxx - minx) * 0.04
    pad_y = (maxy - miny) * 0.04
    ax.set_xlim(minx - pad_x, maxx + pad_x)
    ax.set_ylim(miny - pad_y, maxy + pad_y)

    # Compensate lon/lat distortion to resemble web mercator appearance.
    lat_factor = np.cos(np.deg2rad(mean_lat))
    if lat_factor > 0:
        ax.set_aspect(1.0 / lat_factor)

    ax.axis("off")

def generate_comparison_maps():
    factual_csvs = csvs_by_run_date(FACTUAL_DIR)
    cf_csvs = csvs_by_run_date(CF_DIR)

    common_dates = sorted(set(factual_csvs.keys()).intersection(cf_csvs.keys()))
    if not common_dates:
        print("❌ Error: Could not find common prediction CSV dates in factual and CF folders.")
        return

    prune_stale_comparison_plots(set(common_dates))

    # 4. Load Spatial Data
    gdf = load_shapefile_no_crs(SHAPEFILE_PATH)
    gdf['Province'] = gdf['nazwa'].apply(clean_province_name)
    map_bounds = gdf.total_bounds
    mean_lat = float(gdf.geometry.centroid.y.mean())

    # Define the text styling for readability (black text with a white outline)
    text_style = dict(
        fontsize=11, 
        fontname='Arial', 
        fontweight='bold', 
        color='black', 
        ha='center', 
        va='center',
        path_effects=[pe.withStroke(linewidth=2.5, foreground="white")]
    )

    for run_date in common_dates:
        factual_csv = factual_csvs[run_date]
        cf_csv = cf_csvs[run_date]

        print(f"Loaded Factual: {os.path.basename(factual_csv)}")
        print(f"Loaded Counterfactual: {os.path.basename(cf_csv)}")

        # 2. Load Data
        df_fact = pd.read_csv(factual_csv)
        df_cf = pd.read_csv(cf_csv)

        target_year = select_target_year(df_fact, df_cf)
        if target_year is None:
            print(f"⚠️ Skipping run date {run_date}: no common year between factual and counterfactual rows.")
            continue

        df_fact = df_fact[df_fact['year'].astype(int) == target_year]
        df_cf = df_cf[df_cf['year'].astype(int) == target_year]

        # Rename columns safely
        df_fact = df_fact.rename(columns={'prediction': 'yield_factual'})
        df_cf = df_cf.rename(columns={'prediction': 'yield_cf'})

        # 3. Merge Factual and Counterfactual
        merge_cols = ['Province', 'crop', 'yield_factual']
        df_merged = pd.merge(df_fact[merge_cols], df_cf[['Province', 'crop', 'yield_cf']], on=['Province', 'crop'], how='inner')

        # Calculate difference
        df_merged['yield_diff'] = df_merged['yield_factual'] - df_merged['yield_cf']
        crops = df_merged['crop'].unique()

        # 5. Generate a 3-Panel Plot for EACH Crop
        for crop in crops:
            output_file = os.path.join(OUTPUT_DIR, f"Figure_Comparison_{crop}_{target_year}_{run_date}.jpeg")
            removed_variants = remove_stale_comparison_variants(crop, run_date, os.path.basename(output_file))
            if removed_variants:
                print(f"Removed {removed_variants} stale comparison plot variants for {crop} ({run_date}).")
            if os.path.exists(output_file):
                output_mtime = os.path.getmtime(output_file)
                fact_mtime = os.path.getmtime(factual_csv)
                cf_mtime = os.path.getmtime(cf_csv)
                if output_mtime >= max(fact_mtime, cf_mtime):
                    continue
                print(f"Regenerating comparison map for {crop} ({run_date}) because source CSV is newer.")

            print(f"Generating comparison map for {crop} ({run_date})...")
            crop_data = df_merged[df_merged['crop'] == crop]
            
            # Merge data onto the shapefile
            map_df = gdf.merge(crop_data, on='Province', how='left')

            vmin_yield = min(map_df['yield_factual'].min(), map_df['yield_cf'].min())
            vmax_yield = max(map_df['yield_factual'].max(), map_df['yield_cf'].max())
            diff_min = float(map_df['yield_diff'].min())
            diff_max = float(map_df['yield_diff'].max())

            # Keep the difference legend consistent with displayed values.
            if np.isclose(diff_min, diff_max):
                diff_min -= 1e-6
                diff_max += 1e-6
            if diff_min < 0 < diff_max:
                diff_norm = TwoSlopeNorm(vmin=diff_min, vcenter=0.0, vmax=diff_max)
            else:
                diff_norm = Normalize(vmin=diff_min, vmax=diff_max)
            
            # Setup the 3-panel horizontal canvas
            fig, axes = plt.subplots(1, 3, figsize=(20, 6), facecolor='white')
            fig.suptitle(
                f'Climate Change Impact on {crop} Yield ({target_year}) - {run_date}',
                fontsize=20,
                fontname='Arial',
                y=1.05,
            )

            # Panel 1: Factual
            ax1 = axes[0]
            map_df.plot(column='yield_factual', ax=ax1, cmap='YlGn', vmin=vmin_yield, vmax=vmax_yield, edgecolor='black', linewidth=0.5)
            ax1.set_title("Factual Yield (Current Climate)", fontsize=14, fontname='Arial', pad=10)
            apply_map_axis_style(ax1, map_bounds, mean_lat)

            # Panel 2: Counterfactual
            ax2 = axes[1]
            map_df.plot(column='yield_cf', ax=ax2, cmap='YlGn', vmin=vmin_yield, vmax=vmax_yield, edgecolor='black', linewidth=0.5)
            ax2.set_title("Counterfactual Yield (No CC)", fontsize=14, fontname='Arial', pad=10)
            apply_map_axis_style(ax2, map_bounds, mean_lat)

            # Panel 3: Difference
            ax3 = axes[2]
            map_df.plot(column='yield_diff', ax=ax3, cmap='BrBG', norm=diff_norm, edgecolor='black', linewidth=0.5)
            ax3.set_title("Attributable Difference (Factual - CF)", fontsize=14, fontname='Arial', pad=10)
            apply_map_axis_style(ax3, map_bounds, mean_lat)

            # ==========================================
            # ADD NUMERICAL LABELS TO ALL THREE PANELS
            # ==========================================
            for idx, row in map_df.iterrows():
                if pd.notnull(row['yield_cf']):
                    # Find the center point of the province
                    rep_point = row['geometry'].representative_point()
                    x, y = rep_point.x, rep_point.y
                    
                    # Panel 1 Text (Factual Yield rounded to 1 decimal)
                    ax1.text(x, y, f"{row['yield_factual']:.1f}", **text_style)
                    
                    # Panel 2 Text (CF Yield rounded to 1 decimal)
                    ax2.text(x, y, f"{row['yield_cf']:.1f}", **text_style)
                    
                    # Panel 3 Text (Difference, explicitly adding a '+' sign if positive)
                    diff_val = row['yield_diff']
                    sign = "+" if diff_val > 0 else ""
                    ax3.text(x, y, f"{sign}{diff_val:.1f}", **text_style)

            # Colorbars
            sm = plt.cm.ScalarMappable(cmap='YlGn', norm=plt.Normalize(vmin=vmin_yield, vmax=vmax_yield))
            cbar = fig.colorbar(sm, ax=axes[0:2], orientation='horizontal', fraction=0.05, pad=0.05, aspect=40)
            cbar.set_label('Yield (dt/ha)', fontname='Arial', fontsize=12)

            sm_diff = plt.cm.ScalarMappable(cmap='BrBG', norm=diff_norm)
            cbar_diff = fig.colorbar(sm_diff, ax=ax3, orientation='horizontal', fraction=0.05, pad=0.05, aspect=20)
            cbar_diff.set_label('Difference (dt/ha)', fontname='Arial', fontsize=12)

            plt.savefig(output_file, dpi=300, bbox_inches='tight')
            plt.close()

    print(f"✅ Comparison maps backfilled and saved to {OUTPUT_DIR}")

if __name__ == "__main__":
    generate_comparison_maps()
