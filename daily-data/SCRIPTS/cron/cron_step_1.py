#!/usr/bin/env python3

import argparse
import datetime
from pathlib import Path


def download_era5(client, output_dir, y, m):
    """ Downloads ERA5 data with full hourly coverage """
    era5_file = f"{output_dir}/ERA5_{y}_{m}.grib"

    try:
        client.retrieve(
            'reanalysis-era5-single-levels',
            {
                'product_type': 'reanalysis',
                'variable': [
                    '10m_u_component_of_wind', '10m_v_component_of_wind', '2m_dewpoint_temperature',
                    '2m_temperature', 'surface_solar_radiation_downwards', 'total_precipitation'
                ],
                'year': str(y),
                'month': str(m).zfill(2),
                'day': [str(d).zfill(2) for d in range(1, 32)],  # Select all days of the month
                'time': [f"{h:02d}:00" for h in range(24)],  # Select all hours of the day
                'area': [55, 13, 48, 26],  # Geographic bounding box for Poland
                'format': 'grib', 
            },
            era5_file
        )
    except Exception as exc:
        raise RuntimeError(f"ERA5 download failed for {y}-{m:02d}") from exc


def download_era5land(client, output_dir, y, m):
    """ Downloads ERA5-Land data with full hourly coverage """
    era5land_file = f"{output_dir}/ERA5Land_{y}_{m}.grib"

    try:
        client.retrieve(
            'reanalysis-era5-land',
            {
                'variable': [
                    '10m_u_component_of_wind', '10m_v_component_of_wind', '2m_dewpoint_temperature',
                    '2m_temperature', 'surface_solar_radiation_downwards', 'total_precipitation'
                ],
                'year': str(y),
                'month': str(m).zfill(2),
                'day': [str(d).zfill(2) for d in range(1, 32)],  # Select all days of the month
                'time': [f"{h:02d}:00" for h in range(24)],  # Select all hours of the day
                'area': [55, 13, 48, 26], # Geographic bounding box for Poland
                'format': 'grib',
                'download_format': 'unarchived', # Required to avoid compression issues
            },
            era5land_file
        )
    except Exception as exc:
        raise RuntimeError(f"ERA5-Land download failed for {y}-{m:02d}") from exc


def parse_args():
    today = datetime.date.today()
    parser = argparse.ArgumentParser(description="Download monthly ERA5 and ERA5-Land inputs")
    parser.add_argument("--year", type=int, default=today.year)
    parser.add_argument(
        "--months",
        type=str,
        nargs="+",
        help=(
            "Months to download as values, comma lists, or ranges (for example "
            "1 2 3, 1,2,3, or 1-12). Defaults to elapsed months for the "
            "current year, otherwise all months."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "step_1",
    )
    return parser.parse_args()


def expand_months(values):
    if not values:
        return None
    months = []
    for value in values:
        for item in value.split(","):
            item = item.strip()
            if not item:
                continue
            if "-" in item:
                start_text, end_text = item.split("-", 1)
                start, end = int(start_text), int(end_text)
                if end < start:
                    raise ValueError(f"Invalid descending month range: {item}")
                months.extend(range(start, end + 1))
            else:
                months.append(int(item))
    return list(dict.fromkeys(months))


def main():
    args = parse_args()
    import cdsapi

    today = datetime.date.today()
    months = expand_months(args.months) or list(
        range(1, (today.month if args.year == today.year else 12) + 1)
    )
    invalid = [month for month in months if month < 1 or month > 12]
    if invalid:
        raise ValueError(f"Invalid month numbers: {invalid}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    client = cdsapi.Client()
    for month in months:
        download_era5(client, args.output_dir, args.year, month)
        download_era5land(client, args.output_dir, args.year, month)

    print(f"ERA5 downloads complete for {args.year}, months: {months}")


if __name__ == "__main__":
    main()
