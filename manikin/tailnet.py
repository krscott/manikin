"""Find where manikin listens and the URL a phone should open."""

import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

from manikin.config import Config


@dataclass(frozen=True, kw_only=True)
class Listen:
    bind_host: str
    url: str


@dataclass(frozen=True)
class TailnetError:
    message: str


def resolve_listen(config: Config) -> Listen | TailnetError:
    """Use the configured host, or this machine's tailnet IPv4 and MagicDNS name."""
    if config.host is not None:
        return Listen(bind_host=config.host, url=_url(config.host, config.port))
    status = _tailscale_status()
    if isinstance(status, TailnetError):
        return status
    return listen_from_status(status, port=config.port)


def listen_from_status(status: dict[str, Any], *, port: int) -> Listen | TailnetError:
    if status.get("BackendState") != "Running":
        return TailnetError(
            f"Tailscale is not connected (state: {status.get('BackendState')}). "
            "Run `tailscale up`, or set `host` in the config."
        )
    me: dict[str, Any] = status.get("Self") or {}
    ips: list[str] = me.get("TailscaleIPs") or []
    ipv4 = [ip for ip in ips if ":" not in ip]
    if not ipv4:
        return TailnetError("Tailscale reports no IPv4 address for this machine")
    dns_name = str(me.get("DNSName") or "").rstrip(".")
    return Listen(bind_host=ipv4[0], url=_url(dns_name or ipv4[0], port))


def _tailscale_status() -> dict[str, Any] | TailnetError:
    tailscale = shutil.which("tailscale")
    if tailscale is None:
        return TailnetError(
            "`tailscale` is not on PATH. Install Tailscale, or set `host` in the "
            "config to listen on another address."
        )
    result = subprocess.run(
        [tailscale, "status", "--json"], capture_output=True, text=True
    )
    if result.returncode != 0:
        return TailnetError(
            f"`tailscale status --json` failed: {result.stderr.strip() or 'no output'}"
        )
    status: dict[str, Any] = json.loads(result.stdout)
    return status


def _url(host: str, port: int) -> str:
    if ":" in host:
        host = f"[{host}]"
    return f"http://{host}:{port}/"
