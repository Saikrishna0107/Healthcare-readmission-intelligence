"""Command-line entry point: `hri <command>` or `python -m hri <command>`."""

import argparse
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from hri import PROJECT_ROOT
from hri.ingest import RawStore, ingest, load_sources

DBT_DIR = PROJECT_ROOT / "dbt"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hri", description="Hospital Readmission Intelligence pipeline")
    parser.add_argument("-v", "--verbose", action="store_true", help="show debug logging")
    commands = parser.add_subparsers(dest="command", required=True)

    ingest_cmd = commands.add_parser("ingest", help="download new releases of the raw sources")
    ingest_cmd.add_argument("--only", nargs="+", metavar="SOURCE", help="ingest only these sources")
    ingest_cmd.add_argument("--force", action="store_true", help="download even if the release is stored")

    commands.add_parser("status", help="show the stored releases of each source")

    dbt_cmd = commands.add_parser(
        "dbt",
        help="run a dbt command on the project's dbt folder, e.g. `hri dbt build`",
        description="Passes everything after `dbt` to dbt, run from the dbt/ folder.",
    )
    dbt_cmd.add_argument("dbt_args", nargs=argparse.REMAINDER, help="arguments for dbt")

    model_cmd = commands.add_parser("model", help="train and evaluate the penalty-risk model")
    model_actions = model_cmd.add_subparsers(dest="action", required=True)
    train_cmd = model_actions.add_parser("train", help="baselines, ridge, LightGBM and EBM")
    train_cmd.add_argument("--bootstrap", type=int, default=1000, metavar="N",
                           help="bootstrap resamples for the 95%% intervals (0 to skip)")
    train_cmd.add_argument("--seed", type=int, default=0, help="random seed for folds and resamples")

    args = parser.parse_args(argv)
    if args.command == "dbt":
        return run_dbt(args.dbt_args)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    if args.command == "ingest":
        return _ingest(args)
    if args.command == "model":
        return _model_train(args)
    return _status()


def _model_train(args: argparse.Namespace) -> int:
    # Imported here so `hri ingest` and `hri dbt` do not load scikit-learn.
    from hri.model import run, summary

    try:
        results = run(n_boot=args.bootstrap, seed=args.seed)
    except FileNotFoundError as exc:
        print(exc)
        return 2
    print()
    print(summary(results))
    return 0


def _ingest(args: argparse.Namespace) -> int:
    sources = load_sources()
    unknown = set(args.only or []) - set(sources)
    if unknown:
        print(f"Unknown source(s): {', '.join(sorted(unknown))}. Known: {', '.join(sources)}")
        return 2
    selected = [s for name, s in sources.items() if not args.only or name in args.only]

    results = ingest(selected, force=args.force)
    print()
    for r in results:
        detail = f"{r.rows:,} rows" if r.rows else (r.error or "")
        print(f"  {r.status:9s} {r.source:22s} {r.release or '-':12s} {detail}")
    failed = [r for r in results if r.status == "failed"]
    return 1 if failed else 0


def run_dbt(dbt_args: list[str]) -> int:
    """Run dbt from inside dbt/, so its relative paths (profiles.yml, raw_dir) resolve the same way
    whichever folder `hri` is called from. Uses the dbt installed next to this Python interpreter."""
    dbt = shutil.which("dbt", path=str(Path(sys.executable).parent))
    if dbt is None:
        print("dbt is not installed in this environment. Run: pip install -e .")
        return 2
    return subprocess.run([dbt, *(dbt_args or ["--help"])], cwd=DBT_DIR).returncode


def _status() -> int:
    manifest = RawStore().load_manifest()
    if not manifest:
        print("Nothing ingested yet. Run: hri ingest")
        return 0
    for name in load_sources():
        entry = manifest.get(name)
        if not entry or not entry["releases"]:
            print(f"  {name:22s} not ingested")
            continue
        latest = entry["releases"][entry["latest"]]
        print(
            f"  {name:22s} latest {entry['latest']:12s} {latest['rows']:>9,} rows  "
            f"ingested {latest['ingested_at']}  ({len(entry['releases'])} release(s) stored)"
        )
    return 0
