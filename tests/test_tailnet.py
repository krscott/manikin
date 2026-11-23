from pathlib import Path

from manikin.config import Config
from manikin.tailnet import Listen, TailnetError, listen_from_status, resolve_listen

STATUS = {
    "BackendState": "Running",
    "CurrentTailnet": {"MagicDNSEnabled": True},
    "Self": {
        "DNSName": "box.example.ts.net.",
        "TailscaleIPs": ["100.64.0.7", "fd7a:115c:a1e0::7"],
    },
}


def test_tailnet_ipv4_and_magicdns_url() -> None:
    assert listen_from_status(STATUS, port=8471) == Listen(
        bind_host="100.64.0.7", url="http://box.example.ts.net:8471/"
    )


def test_ip_url_without_magicdns() -> None:
    status = {**STATUS, "CurrentTailnet": {"MagicDNSEnabled": False}}
    assert listen_from_status(status, port=8471) == Listen(
        bind_host="100.64.0.7", url="http://100.64.0.7:8471/"
    )


def test_tailscale_not_running() -> None:
    result = listen_from_status({"BackendState": "Stopped"}, port=8471)
    assert isinstance(result, TailnetError)
    assert "tailscale up" in result.message


def test_configured_host_skips_tailscale(tmp_path: Path) -> None:
    config = Config(
        out_dir=tmp_path,
        host="::1",
        port=9000,
        model_dir=tmp_path,
        model_idle_timeout=60,
    )
    assert resolve_listen(config) == Listen(bind_host="::1", url="http://[::1]:9000/")
