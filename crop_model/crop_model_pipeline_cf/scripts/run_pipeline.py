import argparse
import subprocess
import os
import sys
import datetime
import shutil
from pathlib import Path

# --- CONFIGURATION ---
# Resolve project root dynamically from this script location.
PROJECT_ROOT = str(Path(__file__).resolve().parents[1])

# Sub-directories based on the suggested structure
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")
LISVAP_DIR = os.path.join(PROJECT_ROOT, "lisvap")
LISVAP_OUT = os.path.join(LISVAP_DIR, "output")
LISVAP_METEO = os.path.join(LISVAP_DIR, "meteo")

# Source directory for meteo sync (step_10_cf output)
COMPASS_ROOT = str(Path(__file__).resolve().parents[3])
STEP10_SRC = os.path.join(COMPASS_ROOT, "daily-data", "step_10_cf")
METEO_VARS = ("pd", "pr", "rg", "tn", "tx", "ws")
CONFIG_XML = os.path.join(LISVAP_DIR, "config/config.xml")
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
LOG_FILE = os.path.join(LOG_DIR, "pipeline.log")

# Execution settings
PYTHON_EXE = os.environ.get("LISVAP_PYTHON", "python3")
LISVAP_CMD = os.environ.get("LISVAP_CMD", "lisvap")
CONDA_ENV = os.environ.get("LISVAP_CONDA_ENV", "compass-crop")
USE_CONDA_RUN = os.environ.get("LISVAP_USE_CONDA_RUN", "1") == "1"

def _find_conda_bin() -> str:
    """Return path to the real conda binary, not a shell-function string."""
    candidate = os.environ.get("CONDA_EXE", "")
    if candidate and os.path.isfile(candidate):
        return candidate
    # Derive from active prefix: <base>/envs/<name> -> <base>/bin/conda
    prefix = os.environ.get("CONDA_PREFIX", "")
    if prefix:
        for p in [
            os.path.join(os.path.dirname(prefix), "bin", "conda"),
            os.path.join(prefix, "bin", "conda"),
        ]:
            if os.path.isfile(p):
                return p
    return "conda"

CONDA_BIN = _find_conda_bin()

# Ensure the log directory exists
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

def log(message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"[{timestamp}] {message}"
    print(log_msg)
    with open(LOG_FILE, "a") as f:
        f.write(log_msg + "\n")

def run_step(name, command):
    log(f"Starting Step: {name}...")
    try:
        cmd = command
        if USE_CONDA_RUN:
            cmd = [CONDA_BIN, "run", "--no-capture-output", "-n", CONDA_ENV] + command

        # Check=True ensures we stop if a script fails
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        log(f"✅ {name} completed successfully.")
        return True
    except subprocess.CalledProcessError as e:
        log(f"❌ ERROR in {name}: {e.stderr}")
        # Log the output even if it failed to help debugging
        log(f"Output: {e.stdout}") 
        return False
    except OSError as e:
        log(f"❌ ERROR starting {name}: {e}")
        return False


def validate_inputs(target_year):
    """Stop before cleanup if the branch is not complete enough to run."""
    required_files = [
        CONFIG_XML,
        os.path.join(PROJECT_ROOT, "data", "static", "monthy_climate_original_yields.csv"),
        os.path.join(PROJECT_ROOT, "data", "static", "voivodeships.shp"),
    ]
    required_files.extend(
        os.path.join(STEP10_SRC, f"{var}_{target_year}.nc") for var in METEO_VARS
    )
    missing = [path for path in required_files if not os.path.isfile(path)]
    basemap_dir = os.path.join(LISVAP_DIR, "basemap")
    if not os.path.isdir(basemap_dir):
        missing.append(basemap_dir)
    if missing:
        log("❌ Preflight failed; no files were removed or copied.")
        for path in missing:
            log(f"  MISSING: {path}")
        return False
    return True

def main():
    parser = argparse.ArgumentParser(description="Crop model daily pipeline (CF)")
    parser.add_argument(
        "--year", type=int, default=datetime.datetime.now().year,
        help="Target year for pipeline processing (default: current year)"
    )
    parser.add_argument(
        "--run-date",
        help="Date assigned to generated daily outputs (YYYY-MM-DD; default: newest CF map or today)",
    )
    args = parser.parse_args()
    target_year = args.year

    if args.run_date:
        try:
            parsed_run_date = datetime.date.fromisoformat(args.run_date)
        except ValueError:
            parser.error("--run-date must use YYYY-MM-DD format")
        if parsed_run_date.year != target_year:
            parser.error("--run-date year must match --year")
        os.environ["COMPASS_RUN_DATE"] = args.run_date
    os.environ["COMPASS_TARGET_YEAR"] = str(target_year)

    log(
        "--- STARTING DAILY CROP MODEL PIPELINE "
        f"(year={target_year}, run_date={args.run_date or 'auto'}) ---"
    )

    if not validate_inputs(target_year):
        sys.exit(2)

    # STEP 0a: Sync meteo files from step_10_cf for the target year.
    os.makedirs(LISVAP_METEO, exist_ok=True)
    synced = 0
    for var in METEO_VARS:
        src = os.path.join(STEP10_SRC, f"{var}_{target_year}.nc")
        dst = os.path.join(LISVAP_METEO, f"{var}_{target_year}.nc")
        shutil.copy2(src, dst)
        synced += 1
    log(f"Step 0a: Synced {synced}/{len(METEO_VARS)} meteo files for year {target_year}.")

    # STEP 0b: Clean meteo folder - keep only files for the target year.
    # This ensures prepare_lisvap.py auto-detects the correct year and
    # prevents LISVAP from seeing conflicting multi-year input files.
    if os.path.exists(LISVAP_METEO):
        removed = 0
        for file in os.listdir(LISVAP_METEO):
            if file.endswith(".nc") and not file.endswith(f"_{target_year}.nc"):
                os.unlink(os.path.join(LISVAP_METEO, file))
                removed += 1
        log(f"Step 0b: Removed {removed} meteo files not matching year {target_year}.")

    # STEP 1: Cleanup old LISVAP outputs
    # This prevents old days from contaminating current day results
    if os.path.exists(LISVAP_OUT):
        files_removed = 0
        for file in os.listdir(LISVAP_OUT):
            file_path = os.path.join(LISVAP_OUT, file)
            if os.path.isfile(file_path):
                os.unlink(file_path)
                files_removed += 1
        log(f"Step 1: Cleaned {files_removed} files from LISVAP Output folder.")

    # STEP 2: Run Metadata Patching
    # Fixes units/spelling (e.g., degree_celsius, J/m2) for the current year
    if not run_step("Metadata Patching", [PYTHON_EXE, os.path.join(SCRIPTS_DIR, "prepare_lisvap.py")]):
        sys.exit(1)

    # STEP 3: Run LISVAP
    # This generates the annual daily ET file using updated config.xml
    if not run_step("LISVAP Calculation", [LISVAP_CMD, CONFIG_XML]):
        sys.exit(1)

    # STEP 4: Process to CSV
    # Aggregates NetCDFs, calculates m = Pr - PET, and updates prediction_data.csv
    if not run_step("CSV Data Aggregation", [PYTHON_EXE, os.path.join(SCRIPTS_DIR, "Processing_to_csv.py")]):
        sys.exit(1)

    # STEP 5: Run Yield Prediction Model
    # Runs the final model (main.py) to generate predicted_yields.csv
    if not run_step("Yield Prediction", [PYTHON_EXE, os.path.join(SCRIPTS_DIR, "main.py")]):
        sys.exit(1)
        
    # STEP 6: Generate Static Maps
    # Sweeps the results folder and generates high-quality JPEGs for any missing days
    if not run_step("Generate JPEG Plots", [PYTHON_EXE, os.path.join(SCRIPTS_DIR, "generate_plots.py")]):
        sys.exit(1)

    # STEP 7: Generate Factual vs Counterfactual Comparison Maps
    if not run_step("Generate Comparison Plots", [PYTHON_EXE, os.path.join(SCRIPTS_DIR, "difference_plot.py")]):
        sys.exit(1)

    log("--- PIPELINE FINISHED SUCCESSFULLY ---")

if __name__ == "__main__":
    main()
