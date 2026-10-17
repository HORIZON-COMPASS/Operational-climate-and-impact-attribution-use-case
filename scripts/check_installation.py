#!/usr/bin/env python3
"""Preflight checks for user-supplied tools, configuration, and data."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE_VARS = ("tas", "tasrange", "hurs", "rsds", "sfcWind", "pr")
PRODUCT_VARS = ("pd", "pr", "rg", "tn", "tx", "ws")


class Reporter:
    def __init__(self):
        self.errors = 0

    def ok(self, message):
        print(f"[OK] {message}")

    def missing(self, message):
        self.errors += 1
        print(f"[MISSING] {message}")

    def file(self, path: Path, label: str):
        (self.ok if path.is_file() else self.missing)(f"{label}: {path}")

    def directory(self, path: Path, label: str):
        (self.ok if path.is_dir() else self.missing)(f"{label}: {path}")

    def command(self, name: str):
        resolved = shutil.which(name)
        (self.ok if resolved else self.missing)(f"command {name}: {resolved or 'not on PATH'}")


def local_path(config_file: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (config_file.parent / path).resolve()


def check_attrici(args, report: Reporter):
    import tomllib

    config_file = args.config or ROOT / "attrici/counterfactual/settings.local.toml"
    config_file = config_file.expanduser().resolve()
    report.file(config_file, "ATTRICI local configuration")
    if not config_file.is_file():
        return
    with config_file.open("rb") as stream:
        config = tomllib.load(stream)
    paths = config["paths"]
    files = config["files"]
    executable = str(paths.get("attrici_bin", "attrici"))
    if "/" in executable:
        report.file(local_path(config_file, executable), "ATTRICI executable")
    else:
        report.command(executable)
    step8 = local_path(config_file, paths["step8_dir"])
    traces = local_path(config_file, paths["trace_dir"])
    report.file(local_path(config_file, paths["gmt_file"]), "GMT predictor")
    for variable in CORE_VARS:
        report.file(
            step8 / files["step8_pattern"].format(var=variable, year=args.year),
            f"step_8 {variable}",
        )
        report.file(
            traces / files["trace_pattern"].format(var=variable),
            f"trace {variable}",
        )


def check_daily_data(args, report: Reporter):
    for command in ("cdo", "ncpdq", "ncrename"):
        report.command(command)
    report.directory(ROOT / "daily-data/isimip3basd-master/code", "ISIMIP3BASD source")
    report.directory(ROOT / "daily-data/step_3/emo_data/EFAS_converted", "EMO-1 converted data")
    report.file(ROOT / "daily-data/shp/voivodeships.shp", "voivodeship boundaries")


def check_crop_branch(branch: str, input_dir: str, args, report: Reporter):
    root = ROOT / "crop_model" / branch
    report.file(root / "lisvap/config/config.xml", f"{branch} LISVAP configuration")
    report.directory(root / "lisvap/basemap", f"{branch} LISVAP basemaps")
    report.file(
        root / "data/static/monthy_climate_original_yields.csv",
        f"{branch} crop training table",
    )
    report.file(root / "data/static/voivodeships.shp", f"{branch} boundaries")
    for variable in PRODUCT_VARS:
        report.file(
            ROOT / "daily-data" / input_dir / f"{variable}_{args.year}.nc",
            f"{input_dir} {variable}",
        )


def check_crop_model(args, report: Reporter):
    report.command("conda")
    if args.scenario in {"factual", "both"}:
        check_crop_branch("crop_model_pipeline", "step_10", args, report)
    if args.scenario in {"counterfactual", "both"}:
        check_crop_branch("crop_model_pipeline_cf", "step_10_cf", args, report)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", required=True, choices=("daily-data", "attrici", "crop-model"))
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--config", type=Path, help="ATTRICI settings file")
    parser.add_argument(
        "--scenario",
        choices=("factual", "counterfactual", "both"),
        default="both",
        help="crop-model branch to check",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    report = Reporter()
    if args.module == "daily-data":
        check_daily_data(args, report)
    elif args.module == "attrici":
        check_attrici(args, report)
    else:
        check_crop_model(args, report)
    print(f"Preflight complete: {report.errors} missing requirement(s).")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
