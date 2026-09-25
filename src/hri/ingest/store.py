"""Raw storage: one Parquet file per source release, plus a manifest (download log)."""

import json
import re
from pathlib import Path

import pandas as pd

from hri import PROJECT_ROOT

DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "raw"


class RawStore:
    """Files live at <raw_dir>/<source>/<release>.parquet; <raw_dir>/manifest.json records each one.

    Old releases are kept, not overwritten, so past results can be reproduced and time periods
    can be aligned across sources.
    """

    def __init__(self, raw_dir: Path = DEFAULT_RAW_DIR):
        self.raw_dir = raw_dir
        self.manifest_path = raw_dir / "manifest.json"
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, source_name: str, release_label: str) -> Path:
        safe_label = re.sub(r"[^A-Za-z0-9_.-]", "_", release_label)
        return self.raw_dir / source_name / f"{safe_label}.parquet"

    def load_manifest(self) -> dict:
        if not self.manifest_path.exists():
            return {}
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def has_release(self, source_name: str, release_label: str) -> bool:
        entry = self.load_manifest().get(source_name, {}).get("releases", {}).get(release_label)
        return entry is not None and self.path_for(source_name, release_label).exists()

    def write(self, df: pd.DataFrame, source_name: str, release_label: str, record: dict) -> Path:
        path = self.path_for(source_name, release_label)
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(path.name + ".part")
        df.to_parquet(partial, index=False)
        partial.replace(path)

        manifest = self.load_manifest()
        entry = manifest.setdefault(source_name, {"latest": None, "releases": {}})
        entry["releases"][release_label] = {"file": path.relative_to(self.raw_dir).as_posix(), **record}
        entry["latest"] = max(entry["releases"])  # labels are ISO dates or FYyyyy, so they sort in time order
        self._save_manifest(manifest)
        return path

    def _save_manifest(self, manifest: dict) -> None:
        partial = self.manifest_path.with_name(self.manifest_path.name + ".part")
        partial.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        partial.replace(self.manifest_path)
