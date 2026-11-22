import ast
import os
import subprocess
import sys
from pathlib import Path

from manikin.pose import POSE_FORMAT, POSE_FORMAT_VERSION

ADDON = Path(__file__).parent.parent / "manikin" / "blender" / "manikin_rigify.py"


def addon_constant(name: str) -> object:
    tree = ast.parse(ADDON.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {ADDON}")


def test_addon_reads_the_current_pose_format() -> None:
    assert addon_constant("POSE_FORMAT") == POSE_FORMAT
    assert addon_constant("POSE_FORMAT_VERSION") == POSE_FORMAT_VERSION


def test_blender_script_command(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "manikin", "blender-script", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    written = tmp_path / "manikin_rigify.py"
    assert written.read_text() == ADDON.read_text()
    assert str(written) in result.stdout


def test_url_with_configured_host(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "manikin", "url", "--host", "127.0.0.1", "--port", "9"],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(tmp_path)},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("http://127.0.0.1:9/\n")


def test_config_error_exit_code(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("nope = 1\n")
    result = subprocess.run(
        [sys.executable, "-m", "manikin", "--config", str(config), "url"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "Unknown setting(s)" in result.stderr


def run_serve(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "manikin", "serve", "--host", "127.0.0.1", *args],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(tmp_path)},
    )


def test_serve_missing_weights_exit_code(tmp_path: Path) -> None:
    result = run_serve(
        tmp_path, "--out-dir", str(tmp_path / "poses"), "--model-dir", str(tmp_path)
    )
    assert result.returncode == 3
    assert "hf download" in result.stderr
