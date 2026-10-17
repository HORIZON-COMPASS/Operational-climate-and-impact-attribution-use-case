#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import xarray as xr


VARS = ["tas", "tasrange", "hurs", "rsds", "sfcWind", "pr"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract ATTRICI cfact fields into step_8_cf files with step_8 naming."
        )
    )
    parser.add_argument(
        "--year",
        type=int,
        required=True,
        help="Target year, for example 2025.",
    )
    parser.add_argument(
        "--attrici-dir",
        type=Path,
        default=Path("../../../attrici/counterfactual/work"),
        help=(
            "Path to ATTRICI work directory containing cell_probe_<year>_full/annual_base."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("../../step_8_cf"),
        help="Output directory for generated step_8_cf files.",
    )
    parser.add_argument(
        "--reference-dir",
        type=Path,
        default=Path("../../step_8"),
        help="Reference directory with factual step_8 files used to preserve grid orientation.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    attrici_dir = (script_dir / args.attrici_dir).resolve()
    out_dir = (script_dir / args.output_dir).resolve()
    ref_dir = (script_dir / args.reference_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    in_base = attrici_dir / f"cell_probe_{args.year}_full" / "annual_base"
    if not in_base.exists():
        print(f"Missing ATTRICI annual_base directory: {in_base}")
        return 1

    print(f"Reading ATTRICI inputs from: {in_base}")
    print(f"Writing step_8_cf outputs to: {out_dir}")

    for var in VARS:
        in_path = in_base / f"{var}_{args.year}_full.nc"
        out_path = out_dir / f"ERA5_{var}_ERA5_filled_{args.year}_basd.nc"
        ref_path = ref_dir / f"ERA5_{var}_ERA5_filled_{args.year}_basd.nc"
        if not ref_path.exists():
            # Older years may use a legacy naming convention without "_filled_".
            legacy_ref_path = ref_dir / f"ERA5_{var}_ERA5_{args.year}_basd.nc"
            if legacy_ref_path.exists():
                ref_path = legacy_ref_path

        if not in_path.exists():
            print(f"Missing file for {var}: {in_path}")
            return 1
        if not ref_path.exists():
            print(f"Missing reference step_8 file for {var}: {ref_path}")
            return 1

        ds = xr.open_dataset(in_path)
        ref_ds = xr.open_dataset(ref_path, use_cftime=True)
        if "cfact" not in ds:
            print(f"No 'cfact' variable in: {in_path}")
            ds.close()
            ref_ds.close()
            return 1

        # Keep only counterfactual field and rename it to original variable name expected by step_9.
        out = ds[["cfact"]].rename({"cfact": var})

        # Match factual step_8 coordinate orientation without reindexing on float labels.
        # ATTRICI and step_8 use the same grid shape, but not always bit-identical coordinate values.
        if "lat" in ref_ds.coords and "lat" in out.coords and out.sizes.get("lat") == ref_ds.sizes.get("lat"):
            ref_lat = ref_ds["lat"].values
            out_lat = out["lat"].values
            if bool(out_lat[0] > out_lat[-1]) != bool(ref_lat[0] > ref_lat[-1]):
                out = out.isel(lat=slice(None, None, -1))
            out = out.assign_coords(lat=ref_lat)

        if "lon" in ref_ds.coords and "lon" in out.coords and out.sizes.get("lon") == ref_ds.sizes.get("lon"):
            ref_lon = ref_ds["lon"].values
            out_lon = out["lon"].values
            if bool(out_lon[0] > out_lon[-1]) != bool(ref_lon[0] > ref_lon[-1]):
                out = out.isel(lon=slice(None, None, -1))
            out = out.assign_coords(lon=ref_lon)

        # Preserve coordinate metadata from the factual reference file so CDO
        # sees this as a proper lonlat grid (not generic).
        if "lat" in ref_ds.coords and "lat" in out.coords:
            out["lat"].attrs.update(ref_ds["lat"].attrs)
        if "lon" in ref_ds.coords and "lon" in out.coords:
            out["lon"].attrs.update(ref_ds["lon"].attrs)
        if "time" in ref_ds.coords and "time" in out.coords:
            out["time"].attrs.update(ref_ds["time"].attrs)

        # Save as NetCDF4 with compression comparable to existing pipeline outputs.
        encoding = {
            var: {"zlib": True, "complevel": 4},
        }
        out.to_netcdf(out_path, encoding=encoding)

        print(f"OK: {var} -> {out_path}")
        ds.close()
        ref_ds.close()
        out.close()

    print("Done: step_8_cf files created.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
