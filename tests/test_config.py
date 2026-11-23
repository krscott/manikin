from pathlib import Path

import pytest

from manikin.config import (
    DEFAULT_IDLE_TIMEOUT,
    DEFAULT_PORT,
    Config,
    ConfigError,
    load_config,
)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_defaults_without_config_file(home: Path) -> None:
    config = load_config(None, {}, env={})
    assert config == Config(
        out_dir=home / "manikin" / "poses",
        host=None,
        port=DEFAULT_PORT,
        model_dir=home / ".local/share/manikin/models/sam-3d-body-vith",
        model_idle_timeout=DEFAULT_IDLE_TIMEOUT,
    )


def test_xdg_dirs(home: Path) -> None:
    xdg = home / "xdg"
    config_file = xdg / "config" / "manikin" / "config.toml"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("port = 9000\n")
    env = {"XDG_CONFIG_HOME": str(xdg / "config"), "XDG_DATA_HOME": str(xdg / "data")}
    config = load_config(None, {}, env=env)
    assert isinstance(config, Config)
    assert config.port == 9000
    assert config.model_dir == xdg / "data/manikin/models/sam-3d-body-vith"


def test_file_then_overrides(home: Path) -> None:
    path = home / "manikin.toml"
    path.write_text('out_dir = "~/poses"\nport = 9000\nhost = "127.0.0.1"\n')
    config = load_config(path, {"port": 9100, "host": None}, env={})
    assert isinstance(config, Config)
    assert config.out_dir == home / "poses"
    assert config.port == 9100
    assert config.host == "127.0.0.1"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("colour = 1\n", "Unknown setting(s)"),
        ("port = 0\n", "port"),
        ('port = "80"\n', "port"),
        ("model_idle_timeout = 0\n", "model_idle_timeout"),
        ('host = ""\n', "host"),
        ("port = \n", "Invalid TOML"),
    ],
)
def test_invalid_file(home: Path, text: str, message: str) -> None:
    path = home / "config.toml"
    path.write_text(text)
    config = load_config(path, {}, env={})
    assert isinstance(config, ConfigError)
    assert message in config.message
    assert str(path) in config.message


def test_missing_explicit_file(home: Path) -> None:
    config = load_config(home / "nope.toml", {}, env={})
    assert isinstance(config, ConfigError)
    assert "Cannot read config file" in config.message
