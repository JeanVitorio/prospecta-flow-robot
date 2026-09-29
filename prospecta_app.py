"""Entrada única do aplicativo Windows e dos workers internos."""

from __future__ import annotations

import argparse
import logging
import multiprocessing
import os
import sys

from app_config import configuracao_disponivel, configurar_interativo
from app_paths import configure_bundled_runtime, data_path, env_path
from app_version import __version__
from dotenv import load_dotenv


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()
    configure_bundled_runtime()
    load_dotenv(env_path(), override=False)
    _configure_logging()

    parser = argparse.ArgumentParser(description="Prospecta Flow")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--runner", action="store_true")
    mode.add_argument("--panel", action="store_true")
    mode.add_argument("--configure", action="store_true")
    mode.add_argument("--version", action="store_true")
    mode.add_argument(
        "--worker",
        nargs=2,
        metavar=("PROCESSO", "SLUG"),
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)

    if args.version:
        print(__version__)
        return 0
    if args.configure:
        return 0 if configurar_interativo() else 1
    if args.worker:
        from bot_dinamico import main as worker_main

        worker_main(args.worker)
        return 0

    if not configuracao_disponivel() and not configurar_interativo():
        return 1
    load_dotenv(env_path(), override=True)

    if args.panel:
        from painel_web import main as panel_main

        panel_main()
        return 0

    from runner_remoto import main as runner_main

    runner_main()
    return 0


def _configure_logging() -> None:
    log_path = data_path("logs", "prospecta_app.log")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(
        isinstance(handler, logging.FileHandler)
        and os.path.abspath(handler.baseFilename) == os.path.abspath(log_path)
        for handler in root.handlers
    ):
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
            )
        )
        root.addHandler(handler)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        logging.getLogger("prospecta_app").exception(
            "Falha não tratada no aplicativo."
        )
        raise
