"""Regression tests for the installed Nix executable, selected explicitly by path."""

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def nix_cli() -> Path:
    executable = os.environ.get("MANIKIN_NIX_EXECUTABLE")
    if executable is None:
        pytest.skip("Set MANIKIN_NIX_EXECUTABLE to the installed Nix command")
    path = Path(executable)
    assert path.is_absolute() and path.is_file(), f"Invalid Nix executable: {path}"
    return path


@pytest.fixture
def cli_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(name, None)
    env["HOME"] = str(tmp_path)
    return env


@pytest.mark.parametrize("module", ["setproctitle", "sitecustomize"])
@pytest.mark.parametrize("command", ["help", "blender-script"])
def test_caller_pythonpath(
    nix_cli: Path, cli_env: dict[str, str], tmp_path: Path, module: str, command: str
) -> None:
    (tmp_path / f"{module}.py").write_text(
        'raise RuntimeError("Imported caller module")\n'
    )
    cli_env["PYTHONPATH"] = str(tmp_path)
    args = ["--help"] if command == "help" else ["blender-script", str(tmp_path)]
    result = subprocess.run(
        [str(nix_cli), *args], cwd=tmp_path, env=cli_env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    if command == "help":
        assert "usage:" in result.stdout
    else:
        assert (tmp_path / "manikin_rigify.py").is_file()
    assert result.stderr == ""


def test_caller_pythonhome(
    nix_cli: Path, cli_env: dict[str, str], tmp_path: Path
) -> None:
    cli_env["PYTHONHOME"] = str(tmp_path / "missing-python")
    result = subprocess.run(
        [str(nix_cli), "--version"],
        cwd=tmp_path,
        env=cli_env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()
    assert result.stderr == ""
