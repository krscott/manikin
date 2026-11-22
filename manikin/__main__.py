import argparse
import logging
import sys
from importlib.resources import files
from pathlib import Path

from setproctitle import setproctitle

from manikin import __version__
from manikin.config import Config, ConfigError, default_config_path, load_config
from manikin.tailnet import Listen, TailnetError, resolve_listen

log = logging.getLogger("manikin")

BLENDER_SCRIPT = "manikin_rigify.py"


def main() -> None:
    setproctitle("manikin")
    args = _parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s"
    )
    sys.exit(args.command(args))


def serve(args: argparse.Namespace) -> int:
    config = _config(args)
    if config is None:
        return 2
    listen = _listen(config)
    if listen is None:
        return 1

    # Imported here so `url` and `blender-script` start without these modules.
    import uvicorn

    from manikin.sam_backend import SamBackend, missing_weights_error
    from manikin.server import create_app

    weights_error = missing_weights_error(config.model_dir)
    if weights_error is not None:
        print(weights_error, file=sys.stderr)
        return 1

    backend = SamBackend(
        model_dir=config.model_dir, idle_timeout=config.model_idle_timeout
    )
    app = create_app(backend=backend, out_dir=config.out_dir)
    log.info("manikin %s: open %s on your phone", __version__, listen.url)
    log.info("Saving poses to %s", config.out_dir)
    uvicorn.run(
        app,
        host=listen.bind_host,
        port=config.port,
        log_config=None,
        access_log=False,
    )
    return 0


def url(args: argparse.Namespace) -> int:
    import segno

    config = _config(args)
    if config is None:
        return 2
    listen = _listen(config)
    if listen is None:
        return 1
    print(listen.url)
    segno.make(listen.url).terminal(compact=True)
    return 0


def blender_script(args: argparse.Namespace) -> int:
    target: Path = args.path
    if target.is_dir():
        target = target / BLENDER_SCRIPT
    source = files("manikin") / "blender" / BLENDER_SCRIPT
    target.write_text(source.read_text())
    print(f"Wrote {target}")
    print(
        "Install it in Blender: Edit > Preferences > Add-ons > Install from Disk, "
        "then use File > Import > manikin pose (.json)."
    )
    return 0


def _config(args: argparse.Namespace) -> Config | None:
    overrides = {
        key: getattr(args, key, None)
        for key in ("host", "port", "out_dir", "model_dir")
    }
    config = load_config(args.config, overrides)
    if isinstance(config, ConfigError):
        print(config.message, file=sys.stderr)
        return None
    return config


def _listen(config: Config) -> Listen | None:
    listen = resolve_listen(config)
    if isinstance(listen, TailnetError):
        print(listen.message, file=sys.stderr)
        return None
    return listen


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manikin",
        description="Capture a pose from a phone photo for a Blender Rigify rig.",
        allow_abbrev=False,
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="show debug log messages"
    )
    parser.add_argument(
        "--config",
        type=Path,
        help=f"TOML config file (default: {default_config_path()}, if it exists)",
    )
    commands = parser.add_subparsers(required=True, metavar="COMMAND")

    def listen_options(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--host", help="address to listen on (default: this machine's tailnet IP)"
        )
        command.add_argument("--port", type=int, help="port to listen on")

    serve_cmd = commands.add_parser(
        "serve", help="run the app for your phone", allow_abbrev=False
    )
    listen_options(serve_cmd)
    serve_cmd.add_argument("--out-dir", type=Path, help="directory for accepted poses")
    serve_cmd.add_argument(
        "--model-dir", type=Path, help="directory with SAM 3D Body weights"
    )
    serve_cmd.set_defaults(command=serve)

    url_cmd = commands.add_parser(
        "url", help="print the phone URL and a QR code", allow_abbrev=False
    )
    listen_options(url_cmd)
    url_cmd.set_defaults(command=url)

    script_cmd = commands.add_parser(
        "blender-script",
        help=f"write the Blender add-on ({BLENDER_SCRIPT})",
        allow_abbrev=False,
    )
    script_cmd.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path(BLENDER_SCRIPT),
        help=f"file or directory to write (default: ./{BLENDER_SCRIPT})",
    )
    script_cmd.set_defaults(command=blender_script)

    return parser


if __name__ == "__main__":
    main()
