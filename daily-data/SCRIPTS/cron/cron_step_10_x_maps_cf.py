#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr


VARS = ["tn", "tx", "ws", "pd", "pr", "rg"]
UNITS = {
    "tn": "degC",
    "tx": "degC",
    "ws": "m/s",
    "pd": "hPa",
    "pr": "mm/day",
    "rg": "kJ/m2/day",
}
SCALE = {
    # step_10 rg is in J/m2/day; convert to kJ/m2/day for plotting and deltas
    "rg": 1.0 / 1000.0,
}


def update_yearly_json(json_path: Path, new_rows: list[dict]) -> None:
    """Update slim annual JSON {date: {var: {f, c, d}}} with new_rows.

    Keys are (date, var) — re-running for the same date overwrites previous values.
    Values are rounded to 3 decimal places to keep file size small.
    """
    data: dict = {}
    if json_path.exists():
        with json_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    for row in new_rows:
        date = row["date"]
        var = row["var"]
        if date not in data:
            data[date] = {}
        data[date][var] = {
            "f": round(float(row["factual_mean"]), 3),
            "c": round(float(row["cf_mean"]), 3),
            "d": round(float(row["delta_mean"]), 3),
        }
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, separators=(",", ":"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate factual vs counterfactual daily comparison maps from step_10 and step_10_cf."
    )
    parser.add_argument("--year", type=int, required=True, help="Year of files, for example 2025")
    parser.add_argument("--date", type=str, required=True, help="Target date, format YYYY-MM-DD")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("temp_maps_cf"),
        help="Directory for generated comparison maps",
    )
    parser.add_argument(
        "--metrics-dir",
        type=Path,
        default=None,
        help="Optional directory for per-day CSV metrics (default: same as output-dir)",
    )
    return parser.parse_args()


def get_grid_extent(ds: xr.Dataset) -> tuple[float, float, float, float]:
    lon = ds["lon"].values
    lat = ds["lat"].values
    lon_min = float(np.min(lon))
    lon_max = float(np.max(lon))
    lat_min = float(np.min(lat))
    lat_max = float(np.max(lat))
    return lon_min, lon_max, lat_min, lat_max


def select_day(da: xr.DataArray, target_date: str) -> xr.DataArray:
    # step_10_cf files may have time dimension from a different year (e.g., 1950 instead of 2026).
    # Match by (month, day) only, ignoring year, to handle this.
    if "time" not in da.dims:
        return da
    
    da = da.sortby("time").drop_duplicates(dim="time")
    times = da.time.values
    
    # Parse target (month, day) from target_date string
    target_dt = np.datetime64(target_date)
    target_month = int(target_date.split("-")[1])
    target_day = int(target_date.split("-")[2])
    
    # Find first time in file with matching (month, day)
    matching_idx = None
    for i, t in enumerate(times):
        t_py = t.astype("datetime64[D]").astype("object")
        if t_py.month == target_month and t_py.day == target_day:
            matching_idx = i
            break
    
    # If exact (month, day) match found, use it. Otherwise fall back to nearest.
    if matching_idx is not None:
        return da.isel(time=matching_idx)
    else:
        # Fallback to nearest
        return da.sel(time=target_dt, method="nearest")


def prepare_for_plot(da: xr.DataArray) -> tuple[np.ndarray, list[float], str]:
    lat = da["lat"].values
    lon = da["lon"].values
    lat_desc = bool(lat[0] > lat[-1])
    origin = "upper" if lat_desc else "lower"
    extent = [float(np.min(lon)), float(np.max(lon)), float(np.min(lat)), float(np.max(lat))]
    return da.values, extent, origin


def scale_for_display(var: str, da: xr.DataArray) -> xr.DataArray:
    factor = SCALE.get(var, 1.0)
    if factor == 1.0:
        return da
    return da * factor


def regrid_cf_to_factual(da_c: xr.DataArray, da_f: xr.DataArray) -> xr.DataArray:
    # First pass: linear interpolation for smooth fields.
    da_c_lin = da_c.interp(lat=da_f["lat"], lon=da_f["lon"], method="linear")
    # Fill interpolation/edge gaps with nearest neighbor.
    da_c_nn = da_c.interp(lat=da_f["lat"], lon=da_f["lon"], method="nearest")
    da_c_on_f = da_c_lin.where(np.isfinite(da_c_lin), da_c_nn)
    # Last-resort fallback keeps map panels hole-free.
    da_c_on_f = da_c_on_f.where(np.isfinite(da_c_on_f), da_f)
    return da_c_on_f


def summarize_array(values: np.ndarray) -> dict[str, float]:
    valid = values[np.isfinite(values)]
    if valid.size == 0:
        return {
            "min": np.nan,
            "p05": np.nan,
            "mean": np.nan,
            "median": np.nan,
            "p95": np.nan,
            "max": np.nan,
            "std": np.nan,
        }
    return {
        "min": float(np.min(valid)),
        "p05": float(np.percentile(valid, 5)),
        "mean": float(np.mean(valid)),
        "median": float(np.median(valid)),
        "p95": float(np.percentile(valid, 95)),
        "max": float(np.max(valid)),
        "std": float(np.std(valid)),
    }


def missing_pct(values: np.ndarray) -> float:
    return float(np.mean(~np.isfinite(values)) * 100.0)


def sort_metrics_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    var_rank = {v: i for i, v in enumerate(VARS)}

    def _key(row: dict[str, object]) -> tuple[str, int]:
        date = str(row.get("date", ""))
        var = str(row.get("var", ""))
        return date, var_rank.get(var, 999)

    return sorted(rows, key=_key)


def merge_yearly_metrics_csv(
    yearly_csv_path: Path,
    fieldnames: list[str],
    new_rows: list[dict[str, object]],
) -> None:
    merged_by_key: dict[tuple[str, str], dict[str, object]] = {}

    if yearly_csv_path.exists():
        with yearly_csv_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (row.get("date", ""), row.get("var", ""))
                merged_by_key[key] = row

    for row in new_rows:
        key = (str(row.get("date", "")), str(row.get("var", "")))
        merged_by_key[key] = row

    merged_rows = sort_metrics_rows(list(merged_by_key.values()))
    with yearly_csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(merged_rows)


def main() -> int:
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    base_dir = script_dir.parents[1]

    factual_dir = base_dir / "step_10"
    cf_dir = base_dir / "step_10_cf"
    out_dir = args.output_dir if args.output_dir.is_absolute() else (base_dir / args.output_dir)
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.metrics_dir is None:
        metrics_dir = out_dir
    else:
        metrics_dir = args.metrics_dir if args.metrics_dir.is_absolute() else (base_dir / args.metrics_dir)
        metrics_dir = metrics_dir.resolve()
    metrics_dir.mkdir(parents=True, exist_ok=True)

    daily_rows: list[dict[str, object]] = []

    default_shp = base_dir / "shp" / "voivodeships.shp"
    if default_shp.exists():
        shp_path = default_shp
    else:
        raise FileNotFoundError(f"Missing voivodeships shapefile: {default_shp}")
    poland = gpd.read_file(shp_path)

    for var in VARS:
        factual_path = factual_dir / f"{var}_{args.year}.nc"
        cf_path = cf_dir / f"{var}_{args.year}.nc"

        if not factual_path.exists() or not cf_path.exists():
            print(f"Skipping {var}: missing factual or cf file")
            continue

        ds_f = xr.open_dataset(factual_path)
        ds_c = xr.open_dataset(cf_path)

        if var not in ds_f or var not in ds_c:
            print(f"Skipping {var}: variable missing in one of datasets")
            ds_f.close()
            ds_c.close()
            continue

        da_f = select_day(ds_f[var], args.date)
        da_c = select_day(ds_c[var], args.date)

        # Convert variables to display units before interpolation/delta.
        da_f = scale_for_display(var, da_f)
        da_c = scale_for_display(var, da_c)

        # step_10 factual and step_10_cf can be on different grids.
        # Interpolate CF to factual grid for a comparable difference panel.
        da_c_on_f = regrid_cf_to_factual(da_c, da_f)
        da_d = da_f - da_c_on_f

        f_vals = da_f.values
        c_raw_vals = da_c.values
        c_vals = da_c_on_f.values
        d_vals = da_d.values

        vals_f, extent_f, origin_f = prepare_for_plot(da_f)
        vals_c, _, _ = prepare_for_plot(da_c_on_f)
        vals_d, extent_d, origin_d = prepare_for_plot(da_d)

        vmin = float(np.nanpercentile(np.r_[f_vals.ravel(), c_vals.ravel()], 2))
        vmax = float(np.nanpercentile(np.r_[f_vals.ravel(), c_vals.ravel()], 98))
        d_abs = float(np.nanpercentile(np.abs(d_vals), 98))
        if not np.isfinite(d_abs) or d_abs == 0.0:
            d_abs = 1.0

        f_stats = summarize_array(f_vals)
        c_stats = summarize_array(c_vals)
        d_stats = summarize_array(d_vals)
        daily_rows.append(
            {
                "date": args.date,
                "var": var,
                "unit": UNITS.get(var, "-"),
                "plot_vmin": vmin,
                "plot_vmax": vmax,
                "plot_delta_abs_vmax": d_abs,
                "factual_missing_pct": missing_pct(f_vals),
                "cf_raw_missing_pct": missing_pct(c_raw_vals),
                "cf_on_f_missing_pct": missing_pct(c_vals),
                "delta_missing_pct": missing_pct(d_vals),
                "factual_min": f_stats["min"],
                "factual_p05": f_stats["p05"],
                "factual_mean": f_stats["mean"],
                "factual_median": f_stats["median"],
                "factual_p95": f_stats["p95"],
                "factual_max": f_stats["max"],
                "factual_std": f_stats["std"],
                "cf_min": c_stats["min"],
                "cf_p05": c_stats["p05"],
                "cf_mean": c_stats["mean"],
                "cf_median": c_stats["median"],
                "cf_p95": c_stats["p95"],
                "cf_max": c_stats["max"],
                "cf_std": c_stats["std"],
                "delta_min": d_stats["min"],
                "delta_p05": d_stats["p05"],
                "delta_mean": d_stats["mean"],
                "delta_median": d_stats["median"],
                "delta_p95": d_stats["p95"],
                "delta_max": d_stats["max"],
                "delta_std": d_stats["std"],
            }
        )

        fig, axes = plt.subplots(1, 3, figsize=(15, 5), constrained_layout=True)

        im0 = axes[0].imshow(vals_f, extent=extent_f, origin=origin_f, cmap="coolwarm", vmin=vmin, vmax=vmax, aspect="auto")
        axes[0].set_title(f"Factual: {var.upper()} {args.date}")
        poland.boundary.plot(ax=axes[0], edgecolor="black", linewidth=1.0)
        plt.colorbar(im0, ax=axes[0], label=f"{var.upper()} [{UNITS.get(var, '-')}]", fraction=0.046, pad=0.04)

        im1 = axes[1].imshow(vals_c, extent=extent_f, origin=origin_f, cmap="coolwarm", vmin=vmin, vmax=vmax, aspect="auto")
        axes[1].set_title(f"Counterfactual: {var.upper()} {args.date}")
        poland.boundary.plot(ax=axes[1], edgecolor="black", linewidth=1.0)
        plt.colorbar(im1, ax=axes[1], label=f"{var.upper()} [{UNITS.get(var, '-')}]", fraction=0.046, pad=0.04)

        im2 = axes[2].imshow(vals_d, extent=extent_d, origin=origin_d, cmap="bwr", vmin=-d_abs, vmax=d_abs, aspect="auto")
        axes[2].set_title(f"Difference (Factual - Counterfactual): {var.upper()} {args.date}")
        poland.boundary.plot(ax=axes[2], edgecolor="black", linewidth=1.0)
        plt.colorbar(im2, ax=axes[2], label=f"Delta {var.upper()} [{UNITS.get(var, '-')}]", fraction=0.046, pad=0.04)

        for ax in axes:
            ax.set_xlabel("Longitude")
            ax.set_ylabel("Latitude")

        out_path = out_dir / f"cf_compare_{var}_{args.date}.png"
        fig.savefig(out_path, dpi=110)
        plt.close(fig)

        ds_f.close()
        ds_c.close()
        print(f"Saved: {out_path}")

    if daily_rows:
        csv_path = metrics_dir / f"cf_compare_metrics_{args.date}.csv"
        fieldnames = [
            "date",
            "var",
            "unit",
            "plot_vmin",
            "plot_vmax",
            "plot_delta_abs_vmax",
            "factual_missing_pct",
            "cf_raw_missing_pct",
            "cf_on_f_missing_pct",
            "delta_missing_pct",
            "factual_min",
            "factual_p05",
            "factual_mean",
            "factual_median",
            "factual_p95",
            "factual_max",
            "factual_std",
            "cf_min",
            "cf_p05",
            "cf_mean",
            "cf_median",
            "cf_p95",
            "cf_max",
            "cf_std",
            "delta_min",
            "delta_p05",
            "delta_mean",
            "delta_median",
            "delta_p95",
            "delta_max",
            "delta_std",
        ]
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(daily_rows)
        print(f"Saved: {csv_path}")

        yearly_csv_path = metrics_dir / f"cf_compare_metrics_{args.year}.csv"
        merge_yearly_metrics_csv(
            yearly_csv_path=yearly_csv_path,
            fieldnames=fieldnames,
            new_rows=daily_rows,
        )
        print(f"Updated: {yearly_csv_path}")

        json_path = metrics_dir / f"cf_metrics_{args.year}.json"
        update_yearly_json(json_path, daily_rows)
        print(f"Updated: {json_path}")

    print("Done: comparison maps generated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
