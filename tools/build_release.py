"""Builds the Linux release archive: release/TF3-Dashboard-<version>-linux.tar.gz, the companion without Python
(every distro ships 3.10+), .sh launchers with LF line endings and the executable bit (zip loses it with many
unpackers). The Windows zip and the mod zip stay with build_release.cmd.

Usage: python3 tools/build_release.py   (runs on Linux and macOS, also on Windows)
The version is VERSION = "x.y.z" in dashboard/server.py, as for build_release.cmd. Stdlib only.
"""
from __future__ import annotations

import argparse
import io
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "collector"))
import tf3paths  # noqa: E402

OUT = ROOT / "release"
TOP = "TF3-Dashboard"                      # top folder inside the archive, as in the Windows zip
MOD = ROOT / "mod" / "tf3_dashboard_export"

ROOT_FILES = ["launch.py", "README.md", "LICENSE", "config.example.json",
              "run_dashboard.sh", "_python.sh", "collector/run_collector.sh"]
# never shipped (as in build_release.cmd / build_exclude.txt): the mod.io entry id (private to the author: the Mod
# Hub would try to *update* that entry instead of creating a new one), the icons extracted from the developer's own
# game, probe pages; plus developer-only docs
EXCLUDE_DOCS = {"LINUX_PLAN.md"}
EXCLUDE_MOD = {"_metadata/mod.io_fileid.txt"}


def _excluded_static(rel: str) -> bool:
    """No icons extracted from the developer's game, no probe files."""
    return "/icons/" in f"/{rel}" or "_probe" in rel


def companion_files() -> list[tuple[Path, str]]:
    """(source, path inside the archive below TOP)."""
    files: list[tuple[Path, str]] = []

    def add(src: Path) -> None:
        files.append((src, src.relative_to(ROOT).as_posix()))

    for p in sorted((ROOT / "collector").glob("*.py")) + [ROOT / "collector" / "schema.sql"]:
        add(p)
    for p in sorted((ROOT / "dashboard").glob("*.py")):
        add(p)
    for p in sorted((ROOT / "dashboard" / "static").rglob("*")):
        rel = p.relative_to(ROOT / "dashboard" / "static").as_posix()
        if p.is_file() and not _excluded_static(rel):
            add(p)
    for p in sorted((ROOT / "docs").rglob("*")):
        if p.is_file() and p.name not in EXCLUDE_DOCS:
            add(p)
    for name in ROOT_FILES:
        add(ROOT / name)
    for p in sorted(MOD.rglob("*")):
        if p.is_file() and p.relative_to(MOD).as_posix() not in EXCLUDE_MOD:
            add(p)
    return files


def _content(src: Path) -> bytes:
    """File bytes; shell scripts with LF whatever the working copy has (sh fails on CRLF)."""
    data = src.read_bytes()
    return data.replace(b"\r\n", b"\n") if src.suffix == ".sh" else data


def _mode(arcname: str) -> int:
    return 0o755 if arcname.endswith(".sh") else 0o644


def build_linux(version: str) -> Path:
    dist = OUT / f"TF3-Dashboard-{version}-linux.tar.gz"

    def info(name: str, size: int, mtime: float, mode: int, kind=tarfile.REGTYPE) -> tarfile.TarInfo:
        ti = tarfile.TarInfo(name)
        ti.size, ti.mtime, ti.mode, ti.type = size, int(mtime), mode, kind
        ti.uname = ti.gname = ""
        return ti

    with tarfile.open(dist, "w:gz", format=tarfile.PAX_FORMAT) as t:
        t.addfile(info(TOP, 0, time.time(), 0o755, tarfile.DIRTYPE))
        for src, rel in companion_files():
            data = _content(src)
            t.addfile(info(f"{TOP}/{rel}", len(data), src.stat().st_mtime, _mode(rel)), io.BytesIO(data))
        t.addfile(info(f"{TOP}/db", 0, time.time(), 0o755, tarfile.DIRTYPE))
        data = f"{version}\n".encode()
        t.addfile(info(f"{TOP}/VERSION", len(data), time.time(), 0o644), io.BytesIO(data))
    return dist


def main(argv=None) -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    version = tf3paths.version()
    if version == "?":
        print("could not read VERSION from dashboard/server.py", file=sys.stderr)
        return 1
    print(f"[build] version {version}")
    OUT.mkdir(exist_ok=True)
    p = build_linux(version)
    print(f"[build] done: {p.relative_to(ROOT)}  ({p.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
