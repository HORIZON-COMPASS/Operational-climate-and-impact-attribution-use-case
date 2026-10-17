#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd
import xarray as xr

VARS = ["tn", "tx", "ws", "pd", "pr", "rg"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill daily CF comparison maps from latest available factual/CF data "
            "and keep an incremental state file."
        )
    )
    parser.add_argument("--year", type=int, default=None, help="Target year (default: latest in step_10)")
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Force start date YYYY-MM-DD (overrides state and map auto-detection)",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=None,
        help="Path to state file (default: ../../temp_maps_cf/cf_backfill_<year>.state)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Only print plan, do not generate maps")
    return parser.parse_args()


def detect_latest_year(step10_dir: Path) -> int:
    years: list[int] = []
    pat = re.compile(r"^(tn|tx|ws|pd|pr|rg)_(\d{4})\.nc$")
    for p in step10_dir.glob("*.nc"):
        m = pat.match(p.name)
        if m:
            years.append(int(m.group(2)))
    if not years:
        raise FileNotFoundError(f"No yearly variable files found in {step10_dir}")
    return max(years)


def series_dates(ds_path: Path, var: str) -> pd.DatetimeIndex:
    ds = xr.open_dataset(ds_path)
    if var not in ds:
        ds.close()
        raise KeyError(f"Variable {var} missing in {ds_path}")
    idx = pd.DatetimeIndex(ds[var].time.values).normalize().drop_duplicates().sort_values()
    ds.close()
    return idx


def detect_latest_factual_map_date(maps_dir: Path, year: int) -> dt.date:
    """Return the latest date for which a factual map exists (tn_YYYY-MM-DD.jpg).

    We probe ``tn`` because it is always generated; if you change the factual
    map naming or variable set, update the pattern here accordingly.
    """
    pat = re.compile(rf"^tn_{year}-(\d{{2}})-(\d{{2}})\.jpg$")
    latest: dt.date | None = None
    if maps_dir.exists():
        for p in maps_dir.glob(f"tn_{year}-*.jpg"):
            m = pat.match(p.name)
            if m:
                d = dt.date(year, int(m.group(1)), int(m.group(2)))
                if latest is None or d > latest:
                    latest = d
    if latest is None:
        raise FileNotFoundError(
            f"No factual maps (tn_{year}-MM-DD.jpg) found in {maps_dir}"
        )
    return latest


def detect_common_window(base_dir: Path, year: int) -> tuple[dt.date, dt.date]:
    """Return (start, end): the window where both factual maps and CF data exist.

    Factual upper bound comes from the latest date in ``temp_maps/`` (not from
    step_10 yearly files, which always span the whole year even when factual
    processing has not yet reached today).
    """
    factual_end = detect_latest_factual_map_date(base_dir / "temp_maps", year)

    c_starts: list[pd.Timestamp] = []
    c_ends: list[pd.Timestamp] = []

    for var in VARS:
        cp = base_dir / "step_9_cf" / f"{var}_{year}.nc"
        if not cp.exists():
            raise FileNotFoundError(f"Missing CF file: {cp}")
        tc = series_dates(cp, var)
        c_starts.append(tc.min())
        c_ends.append(tc.max())

    common_start = max(c_starts).date()
    common_end = min(factual_end, min(c_ends).date())

    if common_end < common_start:
        raise RuntimeError(
            f"No overlapping factual/CF window for {year}: {common_start}..{common_end}"
        )

    return common_start, common_end


def detect_latest_map_date(maps_dir: Path, year: int, max_date: dt.date | None = None) -> dt.date | None:
    """Return the latest CF map date in maps_dir, optionally capped at max_date.

    Passing ``max_date`` prevents out-of-window maps (e.g. from manual runs or
    smoke tests beyond the current factual end) from being mistaken for the last
    completed backfill date.
    """
    pat = re.compile(rf"^cf_compare_tn_{year}-(\d{{2}})-(\d{{2}})\.png$")
    latest: dt.date | None = None
    if not maps_dir.exists():
        return None

    for p in maps_dir.glob("cf_compare_tn_*.png"):
        m = pat.match(p.name)
        if not m:
            continue
        d = dt.date(year, int(m.group(1)), int(m.group(2)))
        if max_date is not None and d > max_date:
            continue  # ignore maps beyond the current factual window
        if latest is None or d > latest:
            latest = d

    return latest


def read_state_date(state_file: Path) -> dt.date | None:
    if not state_file.exists():
        return None
    text = state_file.read_text(encoding="utf-8").strip()
    if not text:
        return None
    return dt.date.fromisoformat(text)


def pick_start_date(
    common_start: dt.date,
    common_end: dt.date,
    start_date_override: str | None,
    state_date: dt.date | None,
    latest_map_date: dt.date | None,
) -> dt.date:
    if start_date_override:
        start_date = dt.date.fromisoformat(start_date_override)
    else:
        max_done = None
        for d in (state_date, latest_map_date):
            if d is None:
                continue
            if max_done is None or d > max_done:
                max_done = d

        if max_done is None:
            start_date = common_start
        else:
            start_date = max_done + dt.timedelta(days=1)

    if start_date < common_start:
        start_date = common_start

    if start_date > common_end:
        return common_end + dt.timedelta(days=1)

    return start_date


def daterange(start: dt.date, end: dt.date) -> list[dt.date]:
    out: list[dt.date] = []
    d = start
    while d <= end:
        out.append(d)
        d += dt.timedelta(days=1)
    return out


def main() -> int:
    args = parse_args()

    script_dir = Path(__file__).resolve().parent
    base_dir = script_dir.parents[1]

    year = args.year or detect_latest_year(base_dir / "step_10")
    state_file = args.state_file or (base_dir / "temp_maps_cf" / f"cf_backfill_{year}.state")
    state_file.parent.mkdir(parents=True, exist_ok=True)

    common_start, common_end = detect_common_window(base_dir, year)
    factual_map_end = detect_latest_factual_map_date(base_dir / "temp_maps", year)
    latest_map_date = detect_latest_map_date(base_dir / "temp_maps_cf", year, max_date=factual_map_end)
    state_date = read_state_date(state_file)

    start_date = pick_start_date(
        common_start=common_start,
        common_end=common_end,
        start_date_override=args.start_date,
        state_date=state_date,
        latest_map_date=latest_map_date,
    )

    print(f"Year: {year}")
    print(f"Latest factual map date: {factual_map_end}")
    print(f"Common factual/CF range: {common_start} -> {common_end}")
    print(f"State file: {state_file}")
    print(f"State date: {state_date or '<none>'}")
    print(f"Latest rendered map date: {latest_map_date or '<none>'}")

    if start_date > common_end:
        print("Nothing to backfill: maps are up to date.")
        return 0

    dates = daterange(start_date, common_end)
    print(f"Backfill range: {start_date} -> {common_end} ({len(dates)} day(s))")

    if args.dry_run:
        return 0

    cmd_base = [sys.executable, str(script_dir / "cron_step_10_x_maps_cf.py"), "--year", str(year), "--date"]

    for i, d in enumerate(dates, start=1):
        d_str = d.isoformat()
        print(f"[{i}/{len(dates)}] Generating CF maps for {d_str}")
        subprocess.run(cmd_base + [d_str], check=True)
        state_file.write_text(d_str + "\n", encoding="utf-8")

    print("Backfill completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
