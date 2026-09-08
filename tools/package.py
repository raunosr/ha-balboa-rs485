"""Reproducible HACS core bundle, generated from the independent canonical source."""

import argparse
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sync_core(root: Path = ROOT, *, check: bool = False) -> bool:
    source = root / "balboa_rs485"
    target = root / "custom_components" / "balboa_rs485" / "_core"
    expected = {path.relative_to(source): path.read_bytes() for path in source.rglob("*.py")}
    if Path("runtime.py") not in expected:
        raise ValueError("Missing canonical core runtime")
    actual = {path.relative_to(target): path.read_bytes() for path in target.rglob("*.py")}
    if check:
        return expected == actual
    if actual.keys() - expected.keys():
        raise ValueError("Unexpected bundled Python files; review obsolete files explicitly")
    for relative, data in expected.items():
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    return True


def build_zip(root: Path, destination: Path) -> None:
    if not sync_core(root, check=True):
        raise ValueError("Core bundle is stale; run python -m tools.package first")
    component = root / "custom_components" / "balboa_rs485"
    manifest = json.loads((component / "manifest.json").read_text(encoding="utf-8"))
    if manifest["domain"] != "balboa_rs485" or manifest["requirements"]:
        raise ValueError("Unexpected integration identity or external runtime dependencies")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(component.rglob("*")):
            if path.is_file() and path.suffix in (".py", ".json", ".png", ".yaml"):
                info = zipfile.ZipInfo(path.relative_to(root).as_posix())
                info.create_system = 3  # Stable UNIX permission metadata on Windows too.
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--zip", type=Path)
    args = parser.parse_args()
    if args.zip:
        build_zip(ROOT, args.zip)
    return 0 if sync_core(check=args.check) else 1


if __name__ == "__main__":
    raise SystemExit(main())
