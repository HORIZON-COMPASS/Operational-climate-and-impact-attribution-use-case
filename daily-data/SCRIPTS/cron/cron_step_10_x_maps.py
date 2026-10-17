#!/usr/bin/env python3
"""Render local factual maps from the six step_10 products."""

from __future__ import annotations

import argparse
import datetime as dt
import re
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr


VARIABLES = ("tn", "tx", "ws", "pd", "pr", "rg")
DISPLAY = {
    "tn": ("°C", 1.0),
    "tx": ("°C", 1.0),
    "ws": ("m/s", 1.0),
    "pd": ("hPa", 1.0),
    "pr": ("mm/day", 1.0),
    "rg": ("kJ/m²/day", 1.0 / 1000.0),
}


def parse_args() -> argparse.Namespace:
    base_dir = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, help="Input year; default: latest complete year in step_10")
    parser.add_argument("--start-date", type=dt.date.fromisoformat, help="First date, YYYY-MM-DD")
    parser.add_argument("--end-date", type=dt.date.fromisoformat, help="Last date, YYYY-MM-DD")
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of latest common days when no date range is supplied (default: 7)",
    )
    parser.add_argument("--input-dir", type=Path, default=base_dir / "step_10")
    parser.add_argument("--output-dir", type=Path, default=base_dir / "temp_maps")
    parser.add_argument("--shapefile", type=Path, default=base_dir / "shp/voivodeships.shp")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def detect_latest_complete_year(input_dir: Path) -> int:
    years_by_variable: dict[str, set[int]] = {variable: set() for variable in VARIABLES}
    pattern = re.compile(r"^(tn|tx|ws|pd|pr|rg)_(\d{4})\.nc$")
    for path in input_dir.glob("*.nc"):
        match = pattern.match(path.name)
        if match:
            years_by_variable[match.group(1)].add(int(match.group(2)))
    common = set.intersection(*years_by_variable.values())
    if not common:
        raise FileNotFoundError(f"No complete six-variable year found in {input_dir}")
    return max(common)


def available_dates(path: Path, variable: str) -> set[dt.date]:
    with xr.open_dataset(path) as dataset:
        if variable not in dataset:
            raise KeyError(f"Variable {variable!r} is missing from {path}")
        if "time" not in dataset[variable].dims:
            raise ValueError(f"Variable {variable!r} has no time dimension in {path}")
        return set(pd.DatetimeIndex(dataset[variable]["time"].values).date)


def select_dates(files: dict[str, Path], args: argparse.Namespace) -> list[dt.date]:
    common = set.intersection(
        *(available_dates(path, variable) for variable, path in files.items())
    )
    if not common:
        raise RuntimeError("The six factual inputs have no common dates")

    if args.start_date and args.end_date and args.end_date < args.start_date:
        raise ValueError("--end-date must not precede --start-date")
    if args.start_date or args.end_date:
        start = args.start_date or min(common)
        end = args.end_date or max(common)
        selected = sorted(date for date in common if start <= date <= end)
    else:
        if args.days < 1:
            raise ValueError("--days must be at least 1")
        selected = sorted(common)[-args.days :]

    if not selected:
        raise RuntimeError("No common dates fall inside the requested range")
    return selected


def plot_extent(data: xr.DataArray) -> tuple[list[float], str]:
    lat = np.asarray(data["lat"].values)
    lon = np.asarray(data["lon"].values)
    extent = [float(lon.min()), float(lon.max()), float(lat.min()), float(lat.max())]
    origin = "upper" if lat[0] > lat[-1] else "lower"
    return extent, origin


def main() -> int:
    args = parse_args()
    input_dir = args.input_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    shapefile = args.shapefile.expanduser().resolve()
    year = args.year or detect_latest_complete_year(input_dir)

    files = {variable: input_dir / f"{variable}_{year}.nc" for variable in VARIABLES}
    missing = [path for path in files.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing factual input(s): " + ", ".join(map(str, missing)))
    if not shapefile.is_file():
        raise FileNotFoundError(f"Missing boundary shapefile: {shapefile}")

    dates = select_dates(files, args)
    boundaries = gpd.read_file(shapefile)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Rendering {dates[0]} through {dates[-1]} for year {year}")

    for variable, path in files.items():
        unit, scale = DISPLAY[variable]
        with xr.open_dataset(path) as dataset:
            data = dataset[variable].sortby("time").drop_duplicates(dim="time")
            for date in dates:
                destination = output_dir / f"{variable}_{date.isoformat()}.jpg"
                if destination.exists() and not args.overwrite:
                    continue
                day = data.sel(time=np.datetime64(date.isoformat())) * scale
                values = np.asarray(day.values)
                extent, origin = plot_extent(day)

                figure, axis = plt.subplots(figsize=(8, 6))
                image = axis.imshow(
                    values,
                    cmap="coolwarm",
                    extent=extent,
                    aspect="auto",
                    origin=origin,
                )
                boundaries.boundary.plot(ax=axis, edgecolor="black", linewidth=1.0)
                figure.colorbar(image, ax=axis, label=f"{variable.upper()} [{unit}]")
                axis.set_title(f"{variable.upper()} — {date.isoformat()}")
                axis.set_xlabel("Longitude")
                axis.set_ylabel("Latitude")
                figure.savefig(destination, bbox_inches="tight", dpi=120)
                plt.close(figure)

    print(f"Maps written to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

