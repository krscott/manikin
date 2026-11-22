"""Settings from an optional TOML file, overridden by command-line flags."""

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_PORT = 8471
DEFAULT_IDLE_TIMEOUT = 600


@dataclass(frozen=True, kw_only=True)
class Config:
    out_dir: Path
    # None binds the tailnet IPv4 address reported by `tailscale`.
    host: str | None
    port: int
    model_dir: Path
    # Seconds without a photo before the model is unloaded from the GPU.
    model_idle_timeout: int


@dataclass(frozen=True)
class ConfigError:
    message: str


def default_config_path(env: Mapping[str, str] = os.environ) -> Path:
    return _xdg_dir(env, "XDG_CONFIG_HOME", ".config") / "manikin" / "config.toml"


def defaults(env: Mapping[str, str] = os.environ) -> dict[str, Any]:
    return {
        "out_dir": Path.home() / "manikin" / "poses",
        "host": None,
        "port": DEFAULT_PORT,
        "model_dir": _xdg_dir(env, "XDG_DATA_HOME", ".local/share")
        / "manikin"
        / "models"
        / "sam-3d-body-vith",
        "model_idle_timeout": DEFAULT_IDLE_TIMEOUT,
    }


def load_config(
    path: Path | None,
    overrides: Mapping[str, Any],
    env: Mapping[str, str] = os.environ,
) -> Config | ConfigError:
    """Merge defaults, the config file, then non-None overrides.

    Without an explicit path, the default path is read only if it exists.
    """
    values = defaults(env)
    if path is None:
        candidate = default_config_path(env)
        path = candidate if candidate.is_file() else None
    if path is not None:
        loaded = _read_toml(path)
        if isinstance(loaded, ConfigError):
            return loaded
        values.update(loaded)
    values.update({k: v for k, v in overrides.items() if v is not None})
    return _validate(values, source=str(path) if path else "settings")


def _read_toml(path: Path) -> dict[str, Any] | ConfigError:
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except OSError as e:
        return ConfigError(f"Cannot read config file {path}: {e.strerror}")
    except tomllib.TOMLDecodeError as e:
        return ConfigError(f"Invalid TOML in {path}: {e}")
    unknown = sorted(set(data) - set(Config.__dataclass_fields__))
    if unknown:
        return ConfigError(
            f"Unknown setting(s) in {path}: {', '.join(unknown)}. "
            f"Known settings: {', '.join(Config.__dataclass_fields__)}"
        )
    return data


def _validate(values: dict[str, Any], *, source: str) -> Config | ConfigError:
    def error(key: str, expected: str) -> ConfigError:
        return ConfigError(f"{key} in {source} must be {expected}: {values[key]!r}")

    for key in ("out_dir", "model_dir"):
        if not isinstance(values[key], str | Path) or not str(values[key]):
            return error(key, "a path")
    host = values["host"]
    if host is not None and (not isinstance(host, str) or not host):
        return error("host", "a hostname or IP address")
    port = values["port"]
    if not isinstance(port, int) or isinstance(port, bool) or not 0 < port < 65536:
        return error("port", "an integer from 1 to 65535")
    timeout = values["model_idle_timeout"]
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1:
        return error("model_idle_timeout", "a positive number of seconds")

    return Config(
        out_dir=Path(values["out_dir"]).expanduser(),
        host=host,
        port=port,
        model_dir=Path(values["model_dir"]).expanduser(),
        model_idle_timeout=timeout,
    )


def _xdg_dir(env: Mapping[str, str], var: str, fallback: str) -> Path:
    value = env.get(var, "")
    # The XDG spec says relative paths are invalid and should be ignored.
    if value and Path(value).is_absolute():
        return Path(value)
    return Path.home() / fallback
