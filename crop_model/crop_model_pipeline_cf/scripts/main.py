import pandas as pd
import os
import glob
import shutil
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
# Ensure data.py and modeling.py are in the same folder as this script
from data import store_data_to_dict, detrend, process_data, store_predictions
from modeling import run_cv, get_performances, estimate_final_model, predict_trends, predict_models

# --- CONFIGURATION ---
PROJECT_ROOT = str(Path(__file__).resolve().parents[1])

# Paths aligned with the new structure
TRAIN_FILE = os.path.join(PROJECT_ROOT, "data/static/monthy_climate_original_yields.csv") 
PREDICTION_FILE = os.path.join(PROJECT_ROOT, "data/historical/prediction_data.csv") 
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")

# Setup Date-based saving
TODAY = datetime.today()
TODAY_STR = TODAY.strftime('%Y-%m-%d')
OUTPUT_FILE_DATED = os.path.join(RESULTS_DIR, f"predicted_yields_{TODAY_STR}.csv")

GROWING_SEASONS = {
    "Cereals_all": [4, 10], "Wheat": [-3, 8], "Rye": [-3, 8], "Barley": [-3, 9],
    "Oats": [4, 8], "Potato": [4, 7], "Sugar_beet": [4, 11], "Rape": [-4, 8]
}

DATE_PATTERN = re.compile(r'(\d{4}-\d{2}-\d{2})')


def parse_date_from_name(path):
    base = os.path.basename(path)
    match = DATE_PATTERN.search(base)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), '%Y-%m-%d').date()
    except ValueError:
        return None


def get_target_run_date():
    """Use an explicit run date, then the newest CF map date, then today."""
    run_date = os.environ.get("COMPASS_RUN_DATE")
    if run_date:
        try:
            return datetime.strptime(run_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError("COMPASS_RUN_DATE must use YYYY-MM-DD format") from exc

    compass_root = Path(PROJECT_ROOT).parents[1]
    temp_maps_cf_dir = compass_root / "daily-data" / "temp_maps_cf"

    if not temp_maps_cf_dir.exists():
        return TODAY.date()

    dates = []
    for path in temp_maps_cf_dir.glob("cf_compare_pd_*.png"):
        parsed = parse_date_from_name(str(path))
        if parsed:
            dates.append(parsed)

    if not dates:
        return TODAY.date()

    return max(dates)


def prune_outputs_after(target_end_date):
    """Remove dated result artifacts newer than the daily-data cutoff."""
    removed = 0

    for path in Path(RESULTS_DIR).glob("predicted_yields_*"):
        if not path.is_file():
            continue
        parsed = parse_date_from_name(str(path))
        if parsed and parsed > target_end_date:
            path.unlink()
            removed += 1

    plots_dir = Path(RESULTS_DIR) / "plots"
    if plots_dir.exists():
        for path in plots_dir.glob("*.jpeg"):
            parsed = parse_date_from_name(str(path))
            if parsed and parsed > target_end_date:
                path.unlink()
                removed += 1

    comparison_dir = Path(RESULTS_DIR) / "comparison_plots"
    if comparison_dir.exists():
        for path in comparison_dir.glob("*.jpeg"):
            parsed = parse_date_from_name(str(path))
            if parsed and parsed > target_end_date:
                path.unlink()
                removed += 1

    if removed:
        print(f"Pruned {removed} stale counterfactual artifacts newer than {target_end_date}.")

def get_latest_prediction_year(csv_path):
    df = pd.read_csv(csv_path)
    if "year" not in df.columns or df["year"].dropna().empty:
        return None
    return int(df["year"].dropna().astype(int).max())

def needs_year_upgrade(csv_path, target_year):
    latest_year = get_latest_prediction_year(csv_path)
    if latest_year is None:
        return True
    return latest_year < int(target_year)

def fill_missing_dates(
    target_end_date,
    seed_file_path=None,
    include_end_date=True,
    overwrite_existing=False,
    overwrite_if_year_below=None,
    force_source_file=None,
):
    """
    Ensure one prediction CSV per day from Jan 1 to target_end_date.
    Missing days are filled by copying the closest available dated CSV.
    overwrite_existing=True refreshes all days in range.
    overwrite_if_year_below=YYYY refreshes only days whose CSV max(year) < YYYY.
    """
    files = glob.glob(os.path.join(RESULTS_DIR, "predicted_yields_*.csv"))

    date_to_file = {}
    for path in files:
        parsed = parse_date_from_name(path)
        if parsed:
            date_to_file[parsed] = path

    if seed_file_path:
        seed_date = parse_date_from_name(seed_file_path)
        if seed_date:
            date_to_file[seed_date] = seed_file_path

    if not date_to_file:
        print("No dated prediction CSV available for backfill source yet.")
        return

    start_date = datetime(target_end_date.year, 1, 1).date()
    end_date = target_end_date if include_end_date else (target_end_date - timedelta(days=1))
    if end_date < start_date:
        return

    known_dates = sorted(date_to_file.keys())

    day = start_date
    while day <= end_date:
        existing_file = date_to_file.get(day)
        should_overwrite_by_year = (
            overwrite_if_year_below is not None
            and existing_file is not None
            and needs_year_upgrade(existing_file, overwrite_if_year_below)
        )

        if overwrite_existing or should_overwrite_by_year or day not in date_to_file:
            if force_source_file:
                src_file = force_source_file
                src_date = parse_date_from_name(force_source_file)
            else:
                prev_candidates = [d for d in known_dates if d <= day]
                if prev_candidates:
                    src_date = prev_candidates[-1]
                else:
                    src_date = known_dates[0]
                src_file = date_to_file[src_date]

            dst_file = os.path.join(RESULTS_DIR, f"predicted_yields_{day.strftime('%Y-%m-%d')}.csv")
            if os.path.abspath(src_file) != os.path.abspath(dst_file):
                shutil.copy2(src_file, dst_file)
            date_to_file[day] = dst_file
            known_dates = sorted(date_to_file.keys())
            if overwrite_existing:
                action = "Refreshed"
            elif should_overwrite_by_year:
                action = f"Upgraded-to-{overwrite_if_year_below}"
            else:
                action = "Filled"
            print(f" - {action}: {day.strftime('%Y-%m-%d')} (from {src_date.strftime('%Y-%m-%d')})")

        day += timedelta(days=1)

def save_xml_for_all_predictions(overwrite_existing=False):
    """Generate XML for all predicted_yields_*.csv files."""
    csv_files = glob.glob(os.path.join(RESULTS_DIR, "predicted_yields_*.csv"))
    
    for csv_path in csv_files:
        # Check if XML already exists; skip if so
        xml_path = csv_path.replace('.csv', '.xml')
        if os.path.exists(xml_path) and not overwrite_existing:
            continue
        
        df = pd.read_csv(csv_path)
        latest_year = df['year'].max()
        df_latest = df[df['year'] == latest_year]
        
        # Keep only the requested columns
        df_xml = df_latest[['Province', 'year', 'prediction', 'crop']]
        
        # Export to XML
        df_xml.to_xml(xml_path, index=False, root_name='YieldProjections', row_name='Record')
        print(f"✅ XML generated for {os.path.basename(csv_path)}")
    
    print(f"✅ XML summaries up to date for all prediction dates.")

def main():
    print(f"--- Yield Prediction Started: {pd.Timestamp.now()} ---")

    if not os.path.exists(RESULTS_DIR):
        os.makedirs(RESULTS_DIR)
        print(f"Created missing directory: {RESULTS_DIR}")

    target_run_date = get_target_run_date()
    output_file_dated = os.path.join(RESULTS_DIR, f"predicted_yields_{target_run_date.strftime('%Y-%m-%d')}.csv")
    print(f"Target run date for crop-model outputs: {target_run_date}")
    prune_outputs_after(target_run_date)
    
    # Fill prior gaps first, then write fresh target date and backfill full YTD span.
    fill_missing_dates(target_run_date, include_end_date=False)
    
    # 1. LOAD & TRAIN (Baseline Historical Logic)
    if not os.path.exists(TRAIN_FILE):
        print(f"❌ Error: Training file not found at {TRAIN_FILE}")
        return 1

    print("Loading training data...")
    train_data = pd.read_csv(TRAIN_FILE)
    
    dfs_train = store_data_to_dict(train_data, GROWING_SEASONS)
    dfs_detrended, trend_models = detrend(dfs_train)
    data_model_train = process_data(dfs_detrended, GROWING_SEASONS)
    
    print("Training/Estimating models...")
    cv_results = run_cv(data_model_train)
    performances = get_performances(cv_results)
    final_models = estimate_final_model(data_model_train, performances, cv_results)

    # 2. PREDICT (Current Year Data)
    print("Loading prediction data...")
    if not os.path.exists(PREDICTION_FILE):
        print(f"❌ Error: {PREDICTION_FILE} not found!")
        return 1
        
    data_predict = pd.read_csv(PREDICTION_FILE)
    dfs_predict = store_data_to_dict(data_predict, GROWING_SEASONS, out_of_sample=True)
    dfs_trend_predictions = predict_trends(dfs_predict, trend_models)
    data_model_predict = process_data(dfs_predict, GROWING_SEASONS, out_of_sample=True)
    
    print("Generating final yield predictions...")
    dfs_predictions = predict_models(data_model_predict, dfs_trend_predictions, final_models)

    # 3. EXPORT
    print(f"Saving daily record to {output_file_dated}...")
    store_predictions(dfs_predictions, output_path=output_file_dated)

    latest_prediction_year = get_latest_prediction_year(output_file_dated)
    refresh_current_year = latest_prediction_year == target_run_date.year
    if refresh_current_year:
        print(
            f"Current-year predictions detected in {os.path.basename(output_file_dated)}. "
            f"Filling missing dates without overwriting existing daily snapshots."
        )
    # Always: fill gaps only, never overwrite existing daily snapshot files.
    fill_missing_dates(target_run_date, seed_file_path=output_file_dated, include_end_date=True)

    # --- Generate XML files for all prediction dates ---
    save_xml_for_all_predictions(overwrite_existing=refresh_current_year)
    
    print("--- Yield Prediction Complete ---")
    return 0


if __name__ == "__main__":
    sys.exit(main())
