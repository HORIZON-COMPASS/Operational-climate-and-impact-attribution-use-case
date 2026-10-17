#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import xarray as xr


MAP_VARIABLES_INFO = {
	"tn": {"label": "Min. temperature", "units": "°C"},
	"tx": {"label": "Max. temperature", "units": "°C"},
	"ws": {"label": "Wind speed", "units": "m/s"},
	"pd": {"label": "Vapour pressure", "units": "hPa"},
	"pr": {"label": "Precipitation", "units": "mm/day"},
	"rg": {"label": "Radiation", "units": "kJ/m²/day"},
}


def _product_file(settings: Settings, scenario: str, var_name: str, suffix: str) -> Path:
	return settings.work_dir / "annual_products" / scenario / f"{var_name}_{suffix}.nc"


def _resolve_product_suffix(
	settings: Settings,
	var_name: str,
	year: int,
	target_date: date,
) -> str:
	date_suffix = target_date.isoformat()
	if _product_file(settings, "factual", var_name, date_suffix).exists() and _product_file(
		settings, "counterfactual", var_name, date_suffix
	).exists():
		return date_suffix
	year_suffix = str(year)
	if _product_file(settings, "factual", var_name, year_suffix).exists() and _product_file(
		settings, "counterfactual", var_name, year_suffix
	).exists():
		return year_suffix
	raise FileNotFoundError(
		"Missing factual/counterfactual annual_products for "
		f"{var_name}. Expected either suffix {date_suffix} or {year_suffix}."
	)


@dataclass
class Settings:
	step8_dir: Path
	trace_dir: Path
	gmt_file: Path
	attrici_bin: str
	work_dir: Path
	shapefile: Path
	step8_pattern: str
	trace_pattern: str
	core_vars: list[str]
	map_vars: list[str]
	modes: int
	full_extrapolation: bool
	auto_align_input: bool
	report_variables: list[str]
	map_xfirst: float
	map_xinc: float
	map_yfirst: float
	map_yinc: float
	map_xsize: int
	map_ysize: int
	default_days_back_start: int
	default_days_window: int
	daily_lag_days: int
	daily_context_days: int
	task_count: int


def _load_settings(config_path: Path) -> Settings:
	config_path = config_path.expanduser().resolve()
	with config_path.open("rb") as f:
		config = tomllib.load(f)

	paths = config["paths"]
	files = config["files"]
	workflow = config["workflow"]
	variables = config["variables"]
	grid = config["grid"]
	config_dir = config_path.parent

	def local_path(value: str) -> Path:
		path = Path(value).expanduser()
		return path if path.is_absolute() else (config_dir / path).resolve()

	attrici_bin_value = str(paths.get("attrici_bin", "attrici"))
	if Path(attrici_bin_value).is_absolute() or "/" in attrici_bin_value:
		attrici_bin = str(local_path(attrici_bin_value))
	else:
		attrici_bin = attrici_bin_value

	return Settings(
		step8_dir=local_path(paths["step8_dir"]),
		trace_dir=local_path(paths["trace_dir"]),
		gmt_file=local_path(paths["gmt_file"]),
		attrici_bin=attrici_bin,
		work_dir=local_path(paths["work_dir"]),
		shapefile=local_path(paths["shapefile"]),
		step8_pattern=files["step8_pattern"],
		trace_pattern=files["trace_pattern"],
		core_vars=list(variables["core"]),
		map_vars=list(variables["map"]),
		modes=int(workflow["modes"]),
		full_extrapolation=bool(workflow["full_extrapolation"]),
		auto_align_input=bool(workflow.get("auto_align_input", True)),
		report_variables=list(workflow["report_variables"]),
		map_xfirst=float(grid["xfirst"]),
		map_xinc=float(grid["xinc"]),
		map_yfirst=float(grid["yfirst"]),
		map_yinc=float(grid["yinc"]),
		map_xsize=int(grid["xsize"]),
		map_ysize=int(grid["ysize"]),
		default_days_back_start=int(workflow["days_back_start"]),
		default_days_window=int(workflow["days_window"]),
		daily_lag_days=int(workflow.get("daily_lag_days", 9)),
		daily_context_days=int(workflow.get("daily_context_days", 31)),
		task_count=int(workflow.get("task_count", 1)),
	)


def _step8_file(settings: Settings, var_name: str, year: int) -> Path:
	return settings.step8_dir / settings.step8_pattern.format(var=var_name, year=year)


def _trace_file(settings: Settings, var_name: str) -> Path:
	return settings.trace_dir / settings.trace_pattern.format(var=var_name)


def _detect_latest_year(settings: Settings) -> int:
	files = sorted(settings.step8_dir.glob("ERA5_tas_ERA5_filled_*_basd.nc"))
	if not files:
		raise FileNotFoundError(
			f"No step_8 tas files found in {settings.step8_dir} matching filled-year pattern"
		)
	years: list[int] = []
	for file_path in files:
		match = re.search(r"filled_(\d{4})_basd\.nc$", file_path.name)
		if match:
			years.append(int(match.group(1)))
	if not years:
		raise ValueError("Failed to detect year from step_8 filenames")
	return max(years)


def _save_dataset(ds: xr.Dataset, output_file: Path, overwrite: bool):
	if output_file.exists() and not overwrite:
		return
	output_file.parent.mkdir(parents=True, exist_ok=True)
	encoding = {
		var_name: {"zlib": True, "complevel": 4}
		for var_name in ds.data_vars.keys()
	}
	ds.to_netcdf(output_file, encoding=encoding)


def _time_index_for_date(time_values, target_date: date) -> int:
	target = target_date.isoformat()
	for i, value in enumerate(time_values):
		if str(value)[:10] == target:
			return i
	raise ValueError(f"Target date {target} not found in time coordinate")


def _time_slice_for_target(
	time_values,
	target_date: date,
	context_days: int,
) -> slice:
	idx = _time_index_for_date(time_values, target_date)
	start_idx = max(0, idx - max(1, context_days) + 1)
	return slice(start_idx, idx + 1)


def _is_cached_daily_input_valid(
	output_file: Path,
	target_date: date,
	expected_len: int,
) -> bool:
	if not output_file.exists():
		return False
	try:
		with xr.open_dataset(output_file) as ds_cached:
			if "time" not in ds_cached.coords:
				return False
			time_values = ds_cached.time.values
			if len(time_values) != expected_len:
				return False
			if expected_len < 2:
				return False
			if str(time_values[-1])[:10] != target_date.isoformat():
				return False
	except Exception:
		return False
	return True


def extract_single_day_inputs(
	settings: Settings,
	year: int,
	target_date: date,
	overwrite: bool = False,
) -> dict[str, Path]:
	day_dir = settings.work_dir / "daily_input" / target_date.isoformat()
	day_dir.mkdir(parents=True, exist_ok=True)
	resolved: dict[str, Path] = {}

	for var_name in settings.core_vars:
		input_file = _step8_file(settings, var_name, year)
		if not input_file.exists():
			raise FileNotFoundError(f"Missing step_8 input for {var_name}: {input_file}")

		output_file = day_dir / f"{var_name}_{target_date.isoformat()}.nc"
		with xr.open_dataset(input_file) as ds:
			time_slice = _time_slice_for_target(
				ds.time.values,
				target_date,
				settings.daily_context_days,
			)
			expected_len = time_slice.stop - time_slice.start
			if expected_len < 2:
				raise ValueError(
					"Daily context window resolved to fewer than 2 timesteps for "
					f"{var_name} on {target_date}. "
					"ATTRICI scaling requires at least 2 time steps. "
					f"Input: {input_file}"
				)

			if not overwrite and _is_cached_daily_input_valid(
				output_file=output_file,
				target_date=target_date,
				expected_len=expected_len,
			):
				resolved[var_name] = output_file
				continue

			ds_day = ds.isel(time=time_slice).load()
			encoding = {
				name: {"zlib": True, "complevel": 4}
				for name in ds_day.data_vars.keys()
			}
			if "time" in ds_day.coords:
				ds_day["time"].encoding = {}
			ds_day.to_netcdf(output_file, encoding=encoding)

		resolved[var_name] = output_file

	return resolved


def _input_has_matching_grid(input_file: Path, trace_file: Path) -> bool:
	with xr.open_dataset(input_file, chunks={}, decode_cf=False) as ds_input, xr.open_dataset(
		trace_file, chunks={}, decode_cf=False
	) as ds_trace:
		if "lat" not in ds_input.coords or "lon" not in ds_input.coords:
			return False
		if "lat" not in ds_trace.coords or "lon" not in ds_trace.coords:
			return False
		return np.array_equal(ds_input.lat.values, ds_trace.lat.values) and np.array_equal(
			ds_input.lon.values, ds_trace.lon.values
		)


def align_inputs_to_trace_grid(
	settings: Settings, year: int, overwrite: bool = False
) -> dict[str, Path]:
	aligned_dir = settings.work_dir / "aligned_input" / str(year)
	aligned_dir.mkdir(parents=True, exist_ok=True)
	resolved: dict[str, Path] = {}

	for var_name in settings.core_vars:
		input_file = _step8_file(settings, var_name, year)
		trace_file = _trace_file(settings, var_name)
		if not input_file.exists():
			raise FileNotFoundError(f"Missing step_8 input for {var_name}: {input_file}")
		if not trace_file.exists():
			raise FileNotFoundError(f"Missing trace file for {var_name}: {trace_file}")

		if _input_has_matching_grid(input_file, trace_file):
			resolved[var_name] = input_file
			continue

		aligned_file = aligned_dir / f"{var_name}_{year}_aligned.nc"
		if aligned_file.exists() and not overwrite:
			resolved[var_name] = aligned_file
			continue

		with xr.open_dataset(input_file, chunks={}, decode_cf=False) as ds_input, xr.open_dataset(
			trace_file, chunks={}, decode_cf=False
		) as ds_trace:
			aligned = ds_input.assign_coords(
				lat=("lat", ds_trace.lat.values.astype(ds_input.lat.dtype)),
				lon=("lon", ds_trace.lon.values.astype(ds_input.lon.dtype)),
			)
			encoding = {
				name: {"zlib": True, "complevel": 4}
				for name in aligned.data_vars.keys()
			}
			aligned.to_netcdf(aligned_file, encoding=encoding)

		resolved[var_name] = aligned_file

	return resolved


def run_attrici_for_year(
	settings: Settings,
	year: int,
	overwrite: bool = False,
	target_date: date | None = None,
):
	attrici_executable = shutil.which(settings.attrici_bin)
	if attrici_executable is None:
		raise FileNotFoundError(f"attrici executable not found: {settings.attrici_bin}")
	if not settings.gmt_file.exists():
		raise FileNotFoundError(f"GMT file not found: {settings.gmt_file}")

	annual_base_dir = settings.work_dir / "annual_base"
	annual_base_dir.mkdir(parents=True, exist_ok=True)
	raw_dir = settings.work_dir / "attrici_raw" / str(year)
	raw_dir.mkdir(parents=True, exist_ok=True)

	if target_date is not None:
		base_input_files = extract_single_day_inputs(
			settings,
			year=year,
			target_date=target_date,
			overwrite=overwrite,
		)
	else:
		base_input_files = {
			var_name: _step8_file(settings, var_name, year)
			for var_name in settings.core_vars
		}

	if settings.auto_align_input:
		# create temporary shallow settings override by monkey-patching _step8_file source
		# through local map of input files
		# We align by creating files with corrected coordinates only when needed.
		aligned_dir = settings.work_dir / "aligned_input" / str(year)
		aligned_dir.mkdir(parents=True, exist_ok=True)
		input_files = {}
		for var_name in settings.core_vars:
			input_file = base_input_files[var_name]
			trace_file = _trace_file(settings, var_name)
			if _input_has_matching_grid(input_file, trace_file):
				input_files[var_name] = input_file
				continue
			aligned_file = aligned_dir / f"{var_name}_{input_file.stem}_aligned.nc"
			if aligned_file.exists() and not overwrite:
				input_files[var_name] = aligned_file
				continue
			with xr.open_dataset(input_file, chunks={}, decode_cf=False) as ds_input, xr.open_dataset(
				trace_file, chunks={}, decode_cf=False
			) as ds_trace:
				aligned = ds_input.assign_coords(
					lat=("lat", ds_trace.lat.values.astype(ds_input.lat.dtype)),
					lon=("lon", ds_trace.lon.values.astype(ds_input.lon.dtype)),
				)
				encoding = {
					name: {"zlib": True, "complevel": 4}
					for name in aligned.data_vars.keys()
				}
				aligned.to_netcdf(aligned_file, encoding=encoding)
			input_files[var_name] = aligned_file
	else:
		input_files = base_input_files

	for var_name in settings.core_vars:
		input_file = input_files[var_name]
		if not input_file.exists():
			raise FileNotFoundError(f"Missing step_8 input for {var_name}: {input_file}")

		trace_file = _trace_file(settings, var_name)
		if not trace_file.exists():
			raise FileNotFoundError(
				"Missing trace file for variable "
				f"{var_name}: {trace_file}. "
				"Configure [files].trace_pattern or provide file in trace_dir."
			)

		if target_date is None:
			merged_output = annual_base_dir / f"{var_name}_{year}.nc"
		else:
			merged_output = annual_base_dir / f"{var_name}_{target_date.isoformat()}.nc"
		if merged_output.exists() and not overwrite:
			continue

		var_out_dir = raw_dir / var_name
		var_out_dir.mkdir(parents=True, exist_ok=True)

		detrend_cmd = [
			attrici_executable,
			"detrend",
			"--gmt-file",
			str(settings.gmt_file),
			"--input-file",
			str(input_file),
			"--trace-file",
			str(trace_file),
			"--output-dir",
			str(var_out_dir),
			"--variable",
			var_name,
			"--modes",
			str(settings.modes),
			"--report-variables",
			*settings.report_variables,
		]
		if settings.full_extrapolation:
			detrend_cmd.append("--full-extrapolation")
		if overwrite:
			detrend_cmd.append("--overwrite")

		task_count = max(1, int(settings.task_count))
		if task_count == 1:
			subprocess.run(detrend_cmd, check=True)
		else:
			processes: list[tuple[int, subprocess.Popen]] = []
			for task_id in range(task_count):
				cmd = detrend_cmd + ["--task-id", str(task_id), "--task-count", str(task_count)]
				processes.append(
					(
						task_id,
						subprocess.Popen(cmd),
					)
				)

			failed_tasks: list[int] = []
			for task_id, proc in processes:
				ret = proc.wait()
				if ret != 0:
					failed_tasks.append(task_id)
			if failed_tasks:
				raise subprocess.CalledProcessError(
					returncode=1,
					cmd=detrend_cmd,
					output=f"Failed task ids for {var_name}: {failed_tasks}",
				)

		timeseries_dir = var_out_dir / "timeseries" / var_name
		timeseries_files = list(timeseries_dir.rglob("*.nc")) if timeseries_dir.exists() else []
		if not timeseries_files:
			raise RuntimeError(
				"ATTRICI finished without writing timeseries files for "
				f"{var_name} ({year}). Expected output under: {timeseries_dir}. "
				f"Input file used: {input_file}. "
				"Most common cause is invalid/degenerate input window (e.g. 1 timestep) "
				"or all cells masked for this variable/date. "
				"Re-run with --overwrite after clearing stale daily_input/cache if needed."
			)

		merge_cmd = [
			attrici_executable,
			"merge-output",
			str(timeseries_dir),
			str(merged_output),
		]
		subprocess.run(merge_cmd, check=True)


def _load_base_year(settings: Settings, var_name: str, year: int) -> xr.Dataset:
	file_path = settings.work_dir / "annual_base" / f"{var_name}_{year}.nc"
	if not file_path.exists():
		raise FileNotFoundError(
			f"Missing extracted annual file for {var_name}: {file_path}. "
			"Run run-attrici first."
		)
	return xr.open_dataset(file_path, chunks={"time": 370})


def _load_base_for_target(
	settings: Settings,
	var_name: str,
	year: int,
	target_date: date | None,
) -> xr.Dataset:
	if target_date is None:
		return _load_base_year(settings, var_name, year)
	file_path = settings.work_dir / "annual_base" / f"{var_name}_{target_date.isoformat()}.nc"
	if not file_path.exists():
		raise FileNotFoundError(
			f"Missing daily annual-base file for {var_name}: {file_path}. "
			"Run run-attrici first."
		)
	return xr.open_dataset(file_path, chunks={"time": 1})


def derive_products(
	settings: Settings,
	year: int,
	overwrite: bool = False,
	target_date: date | None = None,
):
	core = {
		var_name: _load_base_for_target(settings, var_name, year, target_date)
		for var_name in settings.core_vars
	}

	if target_date is not None:
		missing_target: list[str] = []
		for var_name, ds in list(core.items()):
			n_steps = int(ds.sizes.get("time", 0))
			if n_steps <= 0:
				missing_target.append(f"{var_name} (empty time axis)")
				continue

			real_dates = np.array([np.datetime64(str(t)[:10], "D") for t in ds.time.values])
			core[var_name] = ds.assign_coords(time=("time", real_dates))

			try:
				_time_index_for_date(real_dates, target_date)
			except ValueError:
				missing_target.append(
					f"{var_name} (available {str(real_dates[0])} .. {str(real_dates[-1])})"
				)

		if missing_target:
			raise ValueError(
				"Target date is not available in annual_base for all core variables. "
				f"Requested: {target_date.isoformat()}. Missing: {', '.join(missing_target)}"
			)

	def _scenario(field: str):
		return {var_name: core[var_name][field] for var_name in settings.core_vars}

	factual = _scenario("y")
	counterfactual = _scenario("cfact")

	def _derive(source):
		tas = source["tas"]
		tasrange = source["tasrange"]
		hurs = source["hurs"]
		rsds = source["rsds"]
		wind = source["sfcWind"]
		pr = source["pr"]

		tn = tas - 0.5 * tasrange - 273.15
		tx = tas + 0.5 * tasrange - 273.15
		pd = hurs / 100.0 * (6.11 * 10.0 ** (7.5 * (tas - 273.15) / (237.3 + (tas - 273.15))))
		rg = rsds * 86400.0
		ws = wind
		pr_day = pr * 86400.0

		products = {
			"tn": tn,
			"tx": tx,
			"pd": pd,
			"rg": rg,
			"ws": ws,
			"pr": pr_day,
		}

		for name, arr in products.items():
			arr.name = name
		return products

	factual_products = _derive(factual)
	counter_products = _derive(counterfactual)
	diff_products = {
		var_name: factual_products[var_name] - counter_products[var_name]
		for var_name in settings.map_vars
	}
	for name, arr in diff_products.items():
		arr.name = name

	suffix = str(year) if target_date is None else target_date.isoformat()

	for scenario_name, products in (
		("factual", factual_products),
		("counterfactual", counter_products),
		("difference", diff_products),
	):
		scenario_dir = settings.work_dir / "annual_products" / scenario_name
		scenario_dir.mkdir(parents=True, exist_ok=True)
		for var_name in settings.map_vars:
			out_file = scenario_dir / f"{var_name}_{suffix}.nc"
			if out_file.exists() and not overwrite:
				continue
			ds = xr.Dataset({var_name: products[var_name]})
			_save_dataset(ds, out_file, overwrite=True)

	for ds in core.values():
		ds.close()


def _resolve_dates(
	time_values,
	mode: str,
	start_date: date | None,
	end_date: date | None,
	settings: Settings,
):
	dates = np.array([np.datetime64(t, "D") for t in time_values])

	if start_date and end_date:
		start = np.datetime64(start_date)
		end = np.datetime64(end_date)
		mask = (dates >= start) & (dates <= end)
		selected = dates[mask]
		return [str(d) for d in selected]

	if mode == "backfill":
		return [str(d) for d in dates]

	max_date = np.max(dates)
	start = max_date - np.timedelta64(settings.default_days_back_start, "D")
	end = start + np.timedelta64(settings.default_days_window, "D")
	mask = (dates >= start) & (dates <= end)
	selected = dates[mask]
	return [str(d) for d in selected]


def _map_file_name(scenario: str, var_name: str, date_str: str) -> str:
	if scenario == "factual":
		return f"{var_name}_{date_str}.jpg"
	if scenario == "counterfactual":
		return f"counterfactual_{var_name}_{date_str}.jpg"
	if scenario == "difference":
		return f"difference_{var_name}_{date_str}.jpg"
	raise ValueError(f"Unsupported scenario: {scenario}")


def _plot_map(
	data: np.ndarray,
	var_name: str,
	scenario: str,
	date_str: str,
	settings: Settings,
	boundary,
	output_file: Path,
	lat_values: np.ndarray | None = None,
	lon_values: np.ndarray | None = None,
	vmin=None,
	vmax=None,
):
	import matplotlib.pyplot as plt

	if lon_values is not None and lon_values.size > 0:
		lon_min = float(np.nanmin(lon_values))
		lon_max = float(np.nanmax(lon_values))
	else:
		lon_min = settings.map_xfirst
		lon_max = settings.map_xfirst + settings.map_xsize * settings.map_xinc

	if lat_values is not None and lat_values.size > 0:
		lat_min = float(np.nanmin(lat_values))
		lat_max = float(np.nanmax(lat_values))
		origin = "lower" if float(lat_values[0]) <= float(lat_values[-1]) else "upper"
	else:
		lat_max = settings.map_yfirst
		lat_min = settings.map_yfirst + settings.map_ysize * settings.map_yinc
		origin = "upper"

	if scenario == "difference":
		cmap = "bwr"
		title = f"Difference (Factual - Counterfactual): {var_name.upper()} {date_str}"
	elif scenario == "counterfactual":
		cmap = "coolwarm"
		title = f"Counterfactual: {var_name.upper()} {date_str}"
	else:
		cmap = "coolwarm"
		title = f"Factual: {var_name.upper()} {date_str}"

	meta = MAP_VARIABLES_INFO.get(var_name, {"label": var_name.upper(), "units": ""})
	colorbar_label = f"{meta['label']} [{meta['units']}]"

	fig, ax = plt.subplots(figsize=(8, 6))
	image = ax.imshow(
		data,
		cmap=cmap,
		extent=[lon_min, lon_max, lat_min, lat_max],
		aspect="auto",
		origin=origin,
		vmin=vmin,
		vmax=vmax,
	)
	boundary.boundary.plot(ax=ax, edgecolor="black", linewidth=1.2)
	plt.colorbar(image, ax=ax, label=colorbar_label)
	ax.set_title(title)
	ax.set_xlabel("Longitude")
	ax.set_ylabel("Latitude")
	ax.grid(False)

	output_file.parent.mkdir(parents=True, exist_ok=True)
	fig.savefig(output_file, bbox_inches="tight", dpi=72)
	plt.close(fig)


def render_maps(
	settings: Settings,
	year: int,
	scenarios: list[str],
	mode: str,
	start_date: date | None,
	end_date: date | None,
	overwrite: bool,
	target_date: date | None = None,
):
	import geopandas as gpd

	boundary = gpd.read_file(settings.shapefile)
	products_dir = settings.work_dir / "annual_products"
	map_dir = settings.work_dir / "maps"
	map_dir.mkdir(parents=True, exist_ok=True)

	datasets: dict[str, dict[str, xr.Dataset]] = {}
	suffix = str(year) if target_date is None else target_date.isoformat()
	for scenario in scenarios:
		datasets[scenario] = {}
		for var_name in settings.map_vars:
			file_path = products_dir / scenario / f"{var_name}_{suffix}.nc"
			if not file_path.exists():
				raise FileNotFoundError(
					f"Missing annual product file: {file_path}. Run derive-products first."
				)
			datasets[scenario][var_name] = xr.open_dataset(file_path, chunks={"time": 370})

	time_ref = datasets["factual"][settings.map_vars[0]].time.values
	if target_date is not None:
		selected_dates = [target_date.isoformat()]
	else:
		selected_dates = _resolve_dates(time_ref, mode, start_date, end_date, settings)

	for date_str in selected_dates:
		for var_name in settings.map_vars:
			base_arrays = {}
			lat_values = None
			lon_values = None
			for base_scenario in ("factual", "counterfactual"):
				if base_scenario in scenarios:
					arr_da = datasets[base_scenario][var_name][var_name].sel(time=date_str)
					arr = arr_da.values
					if lat_values is None:
						lat_values = np.asarray(arr_da.lat.values)
					if lon_values is None:
						lon_values = np.asarray(arr_da.lon.values)
					base_arrays[base_scenario] = arr

			factual_arr = base_arrays.get("factual")
			counter_arr = base_arrays.get("counterfactual")

			for scenario in scenarios:
				out_name = _map_file_name(scenario, var_name, date_str)
				out_file = map_dir / out_name
				if out_file.exists() and not overwrite:
					continue

				data = datasets[scenario][var_name][var_name].sel(time=date_str).values

				if scenario == "difference":
					valid = data[np.isfinite(data)]
					if valid.size:
						lim = float(np.nanpercentile(np.abs(valid), 98))
						vmin, vmax = -lim, lim
					else:
						vmin, vmax = None, None
				else:
					vmin, vmax = None, None

				_plot_map(
					data=data,
					var_name=var_name,
					scenario=scenario,
					date_str=date_str,
					settings=settings,
					boundary=boundary,
					output_file=out_file,
					lat_values=lat_values,
					lon_values=lon_values,
					vmin=vmin,
					vmax=vmax,
				)

	for scenario_ds in datasets.values():
		for ds in scenario_ds.values():
			ds.close()


def plot_day_comparison(
	settings: Settings,
	year: int,
	var_name: str,
	target_date: date,
	output_file: Path,
	lat: float | None,
	lon: float | None,
):
	import matplotlib.pyplot as plt

	suffix = _resolve_product_suffix(settings, var_name, year, target_date)
	factual_file = _product_file(settings, "factual", var_name, suffix)
	counter_file = _product_file(settings, "counterfactual", var_name, suffix)
	if not factual_file.exists() or not counter_file.exists():
		raise FileNotFoundError(
			"Missing annual products for plotting. Run derive-products first."
		)

	with xr.open_dataset(factual_file, chunks={"time": 370}) as ds_f, xr.open_dataset(
		counter_file, chunks={"time": 370}
	) as ds_c:
		f = ds_f[var_name]
		c = ds_c[var_name]

		if lat is not None and lon is not None:
			f = f.sel(lat=lat, lon=lon, method="nearest")
			c = c.sel(lat=lat, lon=lon, method="nearest")
			loc_label = f"lat={float(f.lat.values):.3f}, lon={float(f.lon.values):.3f}"
		else:
			f = f.mean(("lat", "lon"), skipna=True)
			c = c.mean(("lat", "lon"), skipna=True)
			loc_label = "domain mean"

		f_roll = f.rolling(time=31, center=True, min_periods=1).mean()
		c_roll = c.rolling(time=31, center=True, min_periods=1).mean()

		target_dt64 = np.datetime64(target_date)
		if target_dt64 not in f.time.values:
			raise ValueError(f"Date {target_date} not found in {factual_file}")

		f_sel = float(f.sel(time=target_dt64).values)
		c_sel = float(c.sel(time=target_dt64).values)

		f_values = f.values.astype(float)
		c_values = c.values.astype(float)
		f_sorted = np.sort(f_values[np.isfinite(f_values)])
		c_sorted = np.sort(c_values[np.isfinite(c_values)])

		p_f = np.linspace(1.0 / len(f_sorted), 1.0, len(f_sorted))
		p_c = np.linspace(1.0 / len(c_sorted), 1.0, len(c_sorted))

		q_f = np.searchsorted(f_sorted, f_sel, side="right") / len(f_sorted)
		q_c = np.searchsorted(c_sorted, c_sel, side="right") / len(c_sorted)

		fig, axes = plt.subplots(1, 2, figsize=(14, 6), gridspec_kw={"width_ratios": [2, 1]})

		axes[0].scatter(f.time.values, f_values, s=14, alpha=0.35, label="Factual")
		axes[0].scatter(c.time.values, c_values, s=14, alpha=0.35, label="Counterfactual")
		axes[0].plot(f.time.values, f_roll.values, linewidth=2.5, label="Factual smooth")
		axes[0].plot(c.time.values, c_roll.values, linewidth=2.5, label="Counterfactual smooth")
		axes[0].axvline(target_dt64, linestyle="--", color="gray", linewidth=2)
		axes[0].set_title(f"A: Daily signal ({year})")
		axes[0].set_xlabel("Date")
		axes[0].set_ylabel(f"{var_name.upper()} [{MAP_VARIABLES_INFO[var_name]['units']}]")
		axes[0].legend(loc="upper left")

		axes[1].plot(p_f, f_sorted, linewidth=2.5, label="Factual CDF")
		axes[1].plot(p_c, c_sorted, linewidth=2.5, label="Counterfactual CDF")
		axes[1].scatter([q_f], [f_sel], s=90)
		axes[1].scatter([q_c], [c_sel], s=90)
		axes[1].hlines(f_sel, 0, q_f, linestyles="--", linewidth=2)
		axes[1].hlines(c_sel, 0, q_c, linestyles="--", linewidth=2)
		axes[1].set_xlim(0, 1.02)
		axes[1].set_title(f"B: Empirical CDF ({target_date.isoformat()})")
		axes[1].set_xlabel("Cumulative probability")
		axes[1].set_ylabel(f"{var_name.upper()} [{MAP_VARIABLES_INFO[var_name]['units']}]")
		axes[1].legend(loc="upper left")

		fig.suptitle(f"{var_name.upper()} factual vs counterfactual ({loc_label})", fontsize=14)
		fig.tight_layout()
		output_file.parent.mkdir(parents=True, exist_ok=True)
		fig.savefig(output_file, dpi=150, bbox_inches="tight")
		plt.close(fig)


def _describe_array(values: np.ndarray) -> dict[str, float]:
	valid = values[np.isfinite(values)]
	if valid.size == 0:
		return {
			"mean": float("nan"),
			"std": float("nan"),
			"p01": float("nan"),
			"p50": float("nan"),
			"p99": float("nan"),
			"min": float("nan"),
			"max": float("nan"),
		}
	return {
		"mean": float(np.nanmean(valid)),
		"std": float(np.nanstd(valid)),
		"p01": float(np.nanpercentile(valid, 1)),
		"p50": float(np.nanpercentile(valid, 50)),
		"p99": float(np.nanpercentile(valid, 99)),
		"min": float(np.nanmin(valid)),
		"max": float(np.nanmax(valid)),
	}


def plot_day_batch(
	settings: Settings,
	year: int,
	target_date: date,
	output_dir: Path,
	lat: float | None,
	lon: float | None,
):
	output_dir.mkdir(parents=True, exist_ok=True)
	rows: list[str] = [
		"variable,units,f_mean,c_mean,delta_mean,f_p01,c_p01,delta_p01,f_p50,c_p50,delta_p50,f_p99,c_p99,delta_p99,f_min,c_min,f_max,c_max"
	]

	for var_name in settings.map_vars:
		plot_day_comparison(
			settings=settings,
			year=year,
			var_name=var_name,
			target_date=target_date,
			output_file=output_dir / f"{var_name}_{target_date.isoformat()}_compare.png",
			lat=lat,
			lon=lon,
		)

		suffix = _resolve_product_suffix(settings, var_name, year, target_date)
		factual_file = _product_file(settings, "factual", var_name, suffix)
		counter_file = _product_file(settings, "counterfactual", var_name, suffix)

		with xr.open_dataset(factual_file) as ds_f, xr.open_dataset(counter_file) as ds_c:
			f = ds_f[var_name]
			c = ds_c[var_name]
			if lat is not None and lon is not None:
				f = f.sel(lat=lat, lon=lon, method="nearest")
				c = c.sel(lat=lat, lon=lon, method="nearest")
			else:
				f = f.mean(("lat", "lon"), skipna=True)
				c = c.mean(("lat", "lon"), skipna=True)

			f_stats = _describe_array(f.values.astype(float))
			c_stats = _describe_array(c.values.astype(float))

		rows.append(
			",".join(
				[
					var_name,
					MAP_VARIABLES_INFO[var_name]["units"],
					f"{f_stats['mean']:.6g}",
					f"{c_stats['mean']:.6g}",
					f"{(f_stats['mean'] - c_stats['mean']):.6g}",
					f"{f_stats['p01']:.6g}",
					f"{c_stats['p01']:.6g}",
					f"{(f_stats['p01'] - c_stats['p01']):.6g}",
					f"{f_stats['p50']:.6g}",
					f"{c_stats['p50']:.6g}",
					f"{(f_stats['p50'] - c_stats['p50']):.6g}",
					f"{f_stats['p99']:.6g}",
					f"{c_stats['p99']:.6g}",
					f"{(f_stats['p99'] - c_stats['p99']):.6g}",
					f"{f_stats['min']:.6g}",
					f"{c_stats['min']:.6g}",
					f"{f_stats['max']:.6g}",
					f"{c_stats['max']:.6g}",
				]
			)
		)

	(output_dir / f"summary_{target_date.isoformat()}.csv").write_text(
		"\n".join(rows) + "\n",
		encoding="utf-8",
	)


def report_day_grid_stats(
	settings: Settings,
	year: int,
	target_date: date,
	output_dir: Path,
):
	output_dir.mkdir(parents=True, exist_ok=True)
	date_str = target_date.isoformat()

	summary_file = output_dir / f"grid_summary_{date_str}.csv"
	extremes_file = output_dir / f"grid_extremes_{date_str}.csv"

	summary_rows: list[list[object]] = [[
		"variable",
		"n_valid_f",
		"n_valid_c",
		"n_valid_delta",
		"f_mean",
		"c_mean",
		"d_mean",
		"f_std",
		"c_std",
		"d_std",
		"f_min",
		"f_p01",
		"f_p50",
		"f_p99",
		"f_max",
		"c_min",
		"c_p01",
		"c_p50",
		"c_p99",
		"c_max",
		"d_min",
		"d_p01",
		"d_p50",
		"d_p99",
		"d_max",
	]]

	extreme_rows: list[list[object]] = [["variable", "metric", "value"]]

	for var_name in settings.map_vars:
		suffix = _resolve_product_suffix(settings, var_name, year, target_date)
		factual_file = _product_file(settings, "factual", var_name, suffix)
		counter_file = _product_file(settings, "counterfactual", var_name, suffix)

		with xr.open_dataset(factual_file) as ds_f, xr.open_dataset(counter_file) as ds_c:
			f = ds_f[var_name].sel(time=date_str).values.astype(float)
			c = ds_c[var_name].sel(time=date_str).values.astype(float)

		d = f - c
		fv = f[np.isfinite(f)]
		cv = c[np.isfinite(c)]
		dv = d[np.isfinite(d)]

		f_stats = _describe_array(fv)
		c_stats = _describe_array(cv)
		d_stats = _describe_array(dv)

		summary_rows.append([
			var_name,
			int(fv.size),
			int(cv.size),
			int(dv.size),
			f_stats["mean"],
			c_stats["mean"],
			d_stats["mean"],
			f_stats["std"],
			c_stats["std"],
			d_stats["std"],
			f_stats["min"],
			f_stats["p01"],
			f_stats["p50"],
			f_stats["p99"],
			f_stats["max"],
			c_stats["min"],
			c_stats["p01"],
			c_stats["p50"],
			c_stats["p99"],
			c_stats["max"],
			d_stats["min"],
			d_stats["p01"],
			d_stats["p50"],
			d_stats["p99"],
			d_stats["max"],
		])

		f_iqr = float(np.nanpercentile(fv, 75) - np.nanpercentile(fv, 25)) if fv.size else float("nan")
		c_iqr = float(np.nanpercentile(cv, 75) - np.nanpercentile(cv, 25)) if cv.size else float("nan")
		iqr_ratio = c_iqr / max(1e-12, f_iqr) if np.isfinite(f_iqr) and np.isfinite(c_iqr) else float("nan")

		extreme_rows.append([var_name, "cf_minus_f_p01", c_stats["p01"] - f_stats["p01"]])
		extreme_rows.append([var_name, "cf_minus_f_p99", c_stats["p99"] - f_stats["p99"]])
		extreme_rows.append([var_name, "cf_iqr_over_f_iqr", iqr_ratio])

		if var_name in ("tn", "tx"):
			extreme_rows.append([var_name, "frac_cf_lt_-40C", float(np.mean(cv < -40.0))])
			extreme_rows.append([var_name, "frac_cf_gt_40C", float(np.mean(cv > 40.0))])
		if var_name == "pr":
			extreme_rows.append([var_name, "frac_cf_gt_20mm_day", float(np.mean(cv > 20.0))])
		if var_name == "ws":
			extreme_rows.append([var_name, "frac_cf_gt_30m_s", float(np.mean(cv > 30.0))])

	with summary_file.open("w", newline="", encoding="utf-8") as f:
		csv.writer(f).writerows(summary_rows)
	with extremes_file.open("w", newline="", encoding="utf-8") as f:
		csv.writer(f).writerows(extreme_rows)

	print(f"Wrote {summary_file}")
	print(f"Wrote {extremes_file}")


def report_day_core_grid_stats(
	settings: Settings,
	year: int,
	target_date: date,
	output_dir: Path,
):
	output_dir.mkdir(parents=True, exist_ok=True)
	date_str = target_date.isoformat()

	summary_file = output_dir / f"core_grid_summary_{date_str}.csv"

	rows: list[list[object]] = [[
		"variable",
		"n_valid_y",
		"n_valid_cfact",
		"y_mean",
		"cfact_mean",
		"delta_mean",
		"y_p01",
		"cfact_p01",
		"delta_p01",
		"y_p50",
		"cfact_p50",
		"delta_p50",
		"y_p99",
		"cfact_p99",
		"delta_p99",
		"y_min",
		"cfact_min",
		"y_max",
		"cfact_max",
	]]

	for var_name in settings.core_vars:
		base_file = settings.work_dir / "annual_base" / f"{var_name}_{date_str}.nc"
		if not base_file.exists():
			base_file = settings.work_dir / "annual_base" / f"{var_name}_{year}.nc"
		if not base_file.exists():
			raise FileNotFoundError(f"Missing annual_base for {var_name}: {base_file}")

		with xr.open_dataset(base_file) as ds:
			t_idx = _time_index_for_date(ds.time.values, target_date)
			y = ds["y"].isel(time=t_idx).values.astype(float)
			c = ds["cfact"].isel(time=t_idx).values.astype(float)

		d = y - c
		yv = y[np.isfinite(y)]
		cv = c[np.isfinite(c)]
		dv = d[np.isfinite(d)]

		y_stats = _describe_array(yv)
		c_stats = _describe_array(cv)
		d_stats = _describe_array(dv)

		rows.append([
			var_name,
			int(yv.size),
			int(cv.size),
			y_stats["mean"],
			c_stats["mean"],
			d_stats["mean"],
			y_stats["p01"],
			c_stats["p01"],
			d_stats["p01"],
			y_stats["p50"],
			c_stats["p50"],
			d_stats["p50"],
			y_stats["p99"],
			c_stats["p99"],
			d_stats["p99"],
			y_stats["min"],
			c_stats["min"],
			y_stats["max"],
			c_stats["max"],
		])

	with summary_file.open("w", newline="", encoding="utf-8") as f:
		csv.writer(f).writerows(rows)

	print(f"Wrote {summary_file}")


def _parse_date(s: str) -> date:
	return date.fromisoformat(s)


def _default_config_path() -> Path:
	return Path(__file__).with_name("settings.toml")


def _parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Counterfactual workflow built on ATTRICI outputs",
		formatter_class=argparse.ArgumentDefaultsHelpFormatter,
	)
	parser.add_argument("--config", type=Path, default=_default_config_path())

	sub = parser.add_subparsers(dest="command", required=True)

	align = sub.add_parser(
		"align-input",
		help="Align step_8 input grid to trace grid to avoid lat/lon precision mismatches",
	)
	align.add_argument("--year", type=int)
	align.add_argument("--overwrite", action="store_true")

	run_attrici = sub.add_parser(
		"run-attrici",
		help="Run ATTRICI on step_8 data using merged trace files and create annual base files",
	)
	run_attrici.add_argument("--year", type=int)
	run_attrici.add_argument("--target-date", type=_parse_date)
	run_attrici.add_argument("--lag-days", type=int)
	run_attrici.add_argument("--overwrite", action="store_true")

	derive = sub.add_parser("derive-products", help="Build pd/pr/rg/tn/tx/ws per scenario")
	derive.add_argument("--year", type=int)
	derive.add_argument("--target-date", type=_parse_date)
	derive.add_argument("--overwrite", action="store_true")

	render = sub.add_parser("render-maps", help="Render JPG maps for factual/counterfactual/difference")
	render.add_argument("--year", type=int)
	render.add_argument("--target-date", type=_parse_date)
	render.add_argument("--mode", choices=["last7", "backfill"], default="last7")
	render.add_argument("--start-date", type=_parse_date)
	render.add_argument("--end-date", type=_parse_date)
	render.add_argument(
		"--scenarios",
		nargs="+",
		default=["factual", "counterfactual", "difference"],
		choices=["factual", "counterfactual", "difference"],
	)
	render.add_argument("--overwrite", action="store_true")

	run_all = sub.add_parser("run", help="Run ATTRICI + derive + render")
	run_all.add_argument("--year", type=int)
	run_all.add_argument("--target-date", type=_parse_date)
	run_all.add_argument("--lag-days", type=int)
	run_all.add_argument("--mode", choices=["last7", "backfill"], default="last7")
	run_all.add_argument("--start-date", type=_parse_date)
	run_all.add_argument("--end-date", type=_parse_date)
	run_all.add_argument("--overwrite", action="store_true")

	plot = sub.add_parser("plot-day", help="Create factual vs counterfactual comparison plot")
	plot.add_argument("--year", type=int)
	plot.add_argument("--var", required=True, choices=["tn", "tx", "ws", "pd", "pr", "rg"])
	plot.add_argument("--date", type=_parse_date, required=True)
	plot.add_argument("--lat", type=float)
	plot.add_argument("--lon", type=float)
	plot.add_argument("--output", type=Path, required=True)

	plot_batch = sub.add_parser(
		"plot-day-batch",
		help="Create comparison plots and numeric summary for all map variables",
	)
	plot_batch.add_argument("--year", type=int)
	plot_batch.add_argument("--date", type=_parse_date, required=True)
	plot_batch.add_argument("--lat", type=float)
	plot_batch.add_argument("--lon", type=float)
	plot_batch.add_argument("--output-dir", type=Path, required=True)

	grid_report = sub.add_parser(
		"report-day-grid",
		help="Create grid-level factual/counterfactual diagnostics for one date",
	)
	grid_report.add_argument("--year", type=int)
	grid_report.add_argument("--date", type=_parse_date, required=True)
	grid_report.add_argument("--output-dir", type=Path, required=True)

	core_grid_report = sub.add_parser(
		"report-day-core-grid",
		help="Create grid-level diagnostics for annual_base core y/cfact fields",
	)
	core_grid_report.add_argument("--year", type=int)
	core_grid_report.add_argument("--date", type=_parse_date, required=True)
	core_grid_report.add_argument("--output-dir", type=Path, required=True)

	return parser.parse_args()


def _resolve_target_date(args: argparse.Namespace, settings: Settings) -> date | None:
	if getattr(args, "target_date", None) is not None:
		return args.target_date
	lag_days = getattr(args, "lag_days", None)
	if lag_days is None:
		return None
	return (datetime.utcnow().date() - timedelta(days=lag_days))


def main():
	args = _parse_args()
	settings = _load_settings(args.config)

	target_date = _resolve_target_date(args, settings)
	year = getattr(args, "year", None)
	if year is None and target_date is not None:
		year = target_date.year
	if year is None:
		year = _detect_latest_year(settings)
	if target_date is not None and target_date.year != year:
		raise ValueError(
			f"target-date {target_date} is in year {target_date.year}, but --year is {year}"
		)

	if args.command == "align-input":
		align_inputs_to_trace_grid(settings, year=year, overwrite=args.overwrite)
		return

	if args.command == "run-attrici":
		run_attrici_for_year(
			settings,
			year=year,
			overwrite=args.overwrite,
			target_date=target_date,
		)
		return

	if args.command == "derive-products":
		derive_products(
			settings,
			year=year,
			overwrite=args.overwrite,
			target_date=target_date,
		)
		return

	if args.command == "render-maps":
		render_maps(
			settings,
			year=year,
			scenarios=args.scenarios,
			mode=args.mode,
			start_date=args.start_date,
			end_date=args.end_date,
			overwrite=args.overwrite,
			target_date=target_date,
		)
		return

	if args.command == "run":
		run_attrici_for_year(
			settings,
			year=year,
			overwrite=args.overwrite,
			target_date=target_date,
		)
		derive_products(
			settings,
			year=year,
			overwrite=args.overwrite,
			target_date=target_date,
		)
		render_maps(
			settings,
			year=year,
			scenarios=["factual", "counterfactual", "difference"],
			mode=args.mode,
			start_date=args.start_date,
			end_date=args.end_date,
			overwrite=args.overwrite,
			target_date=target_date,
		)
		return

	if args.command == "plot-day":
		plot_day_comparison(
			settings,
			year=year,
			var_name=args.var,
			target_date=args.date,
			output_file=args.output,
			lat=args.lat,
			lon=args.lon,
		)
		return

	if args.command == "plot-day-batch":
		plot_day_batch(
			settings=settings,
			year=year,
			target_date=args.date,
			output_dir=args.output_dir,
			lat=args.lat,
			lon=args.lon,
		)
		return

	if args.command == "report-day-grid":
		report_day_grid_stats(
			settings=settings,
			year=year,
			target_date=args.date,
			output_dir=args.output_dir,
		)
		return

	if args.command == "report-day-core-grid":
		report_day_core_grid_stats(
			settings=settings,
			year=year,
			target_date=args.date,
			output_dir=args.output_dir,
		)
		return


if __name__ == "__main__":
	main()
