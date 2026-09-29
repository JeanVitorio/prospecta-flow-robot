"""Janela desktop que incorpora a interface Web do Prospecta Flow."""

from __future__ import annotations

import logging
import os
import subprocess
import sys

from app_paths import data_path, install_root, is_frozen, resource_path
from execucao_bot import bloquear_energia, liberar_energia


WEB_APP_URL = os.getenv(
    "PROSPECTA_WEB_URL",
    "https://jvs-prospecta-flow.netlify.app/",
).strip()
LOG = logging.getLogger("prospecta_painel_web")


def _garantir_runner() -> None:
    """Inicia o Runner; a trava global impede processos duplicados."""
    comando = (
        [sys.executable, "--runner"]
        if is_frozen()
        else [sys.executable, str(resource_path("prospecta_app.py")), "--runner"]
    )
    flags = 0
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        flags |= subprocess.CREATE_NEW_PROCESS_GROUP
    if hasattr(subprocess, "DETACHED_PROCESS"):
        flags |= subprocess.DETACHED_PROCESS

    caminho_log = data_path("logs", "runner_launcher.log")
    with caminho_log.open("a", encoding="utf-8", buffering=1) as log:
        subprocess.Popen(
            comando,
            cwd=install_root(),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=flags,
            env=os.environ.copy(),
        )


def main() -> None:
    if not WEB_APP_URL.startswith("https://"):
        raise RuntimeError("PROSPECTA_WEB_URL deve usar HTTPS.")

    _garantir_runner()
    bloquear_energia()
    try:
        import webview

        webview.create_window(
            "Prospecta Flow",
            WEB_APP_URL,
            width=1440,
            height=900,
            min_size=(1024, 640),
        )
        webview.start(
            gui="edgechromium",
            private_mode=False,
            storage_path=str(data_path("webview")),
        )
    finally:
        liberar_energia()


if __name__ == "__main__":
    main()
