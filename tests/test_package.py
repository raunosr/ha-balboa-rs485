"""The HACS-installed core must not depend on the repository or HA imports."""

import json
import shutil
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from tools.package import sync_core


def test_bundled_core_imports_in_isolation_without_private_package_dependency(tmp_path):
    shutil.copytree(
        Path(__file__).parents[1] / "balboa_rs485",
        tmp_path / "balboa_rs485",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    sync_core(tmp_path)
    component = tmp_path / "custom_components" / "balboa_rs485"
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); from _core.runtime import SpaRuntime; "
            "assert 'homeassistant' not in sys.modules; print(SpaRuntime.__module__)",
            str(component),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "_core.runtime"
    assert sync_core(tmp_path, check=True)


def test_install_zip_is_self_contained_reproducible_and_excludes_development_files(tmp_path):
    from tools.package import build_zip

    root = Path(__file__).parents[1]
    first, second = tmp_path / "first.zip", tmp_path / "second.zip"
    build_zip(root, first)
    build_zip(root, second)
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        names = archive.namelist()
        assert "custom_components/balboa_rs485/manifest.json" in names
        assert "custom_components/balboa_rs485/_core/runtime.py" in names
        assert "custom_components/balboa_rs485/brand/icon.png" in names
        assert "custom_components/balboa_rs485/services.yaml" in names
        # Pin ZIP creator metadata too: Windows/Linux builds must not differ.
        assert all(info.create_system == 3 for info in archive.infolist())
        assert all(name.startswith("custom_components/balboa_rs485/") for name in names)
        assert not any("__pycache__" in name or ".research" in name for name in names)


def test_missing_canonical_core_is_never_treated_as_a_valid_bundle(tmp_path):
    with pytest.raises(ValueError, match="Missing canonical core"):
        sync_core(tmp_path, check=True)


def test_package_cli_checks_bundle_and_builds_install_zip(tmp_path):
    destination = tmp_path / "balboa-rs485.zip"
    result = subprocess.run(
        [sys.executable, "-m", "tools.package", "--check", "--zip", str(destination)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert zipfile.is_zipfile(destination)


def test_stale_bundle_blocks_distribution_and_obsolete_files_are_preserved(tmp_path):
    from tools.package import build_zip

    shutil.copytree(
        Path(__file__).parents[1] / "balboa_rs485",
        tmp_path / "balboa_rs485",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    sync_core(tmp_path)
    extra = tmp_path / "custom_components/balboa_rs485/_core/unexpected.py"
    extra.write_text("# unexpected source", encoding="utf-8")
    assert not sync_core(tmp_path, check=True)
    with pytest.raises(ValueError, match="stale"):
        build_zip(tmp_path, tmp_path / "package.zip")
    with pytest.raises(ValueError, match="Unexpected bundled"):
        sync_core(tmp_path)
    assert extra.read_text(encoding="utf-8") == "# unexpected source"


def test_hacs_version_local_icon_and_bilingual_strings_are_bundled():
    root = Path(__file__).parents[1]
    component = root / "custom_components/balboa_rs485"
    assert json.loads((root / "hacs.json").read_text())["homeassistant"] == "2026.8.3"
    english = json.loads((component / "strings.json").read_text(encoding="utf-8"))
    assert english == json.loads((component / "translations/en.json").read_text(encoding="utf-8"))
    finnish = json.loads((component / "translations/fi.json").read_text(encoding="utf-8"))

    def keys(value, prefix=""):
        return {prefix + key for key in value} | {
            child
            for key, item in value.items()
            if isinstance(item, dict)
            for child in keys(item, prefix + key + ".")
        }

    assert keys(english) == keys(finnish)
    icon = (component / "brand/icon.png").read_bytes()
    assert icon[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", icon[16:24])
    assert width == height and width >= 256
    assert icon[25] == 6  # RGBA PNG, supports transparent local branding.
