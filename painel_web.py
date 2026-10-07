"""Janela desktop que incorpora a interface Web do Prospecta Flow."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from typing import Any

from app_version import __version__
from atualizador import Atualizador
from app_paths import data_path, install_root, is_frozen, resource_path
from execucao_bot import bloquear_energia, liberar_energia


WEB_APP_URL = os.getenv("PROSPECTA_WEB_URL", "").strip()
LOG = logging.getLogger("prospecta_painel_web")


class ApiAtualizacao:
    """Expõe à interface web somente a atualização nativa validada."""

    def __init__(self) -> None:
        # O pywebview percorre atributos públicos da API recursivamente.
        # Objetos internos precisam permanecer privados para evitar ciclos.
        self._atualizador = Atualizador(LOG)
        self._janela: Any | None = None

    def _vincular_janela(self, janela: Any) -> None:
        self._janela = janela

    def obter_versao_instalada(self) -> dict[str, str]:
        return {"version": __version__}

    def buscar_e_instalar_atualizacao(self) -> dict[str, str]:
        try:
            resultado = self._atualizador.check_now()
            if not resultado:
                return {
                    "status": "updated",
                    "version": __version__,
                    "message": "O aplicativo já está na versão mais recente.",
                }
            info, installer = resultado
            if not self._atualizador.schedule_install(installer):
                raise RuntimeError("Não foi possível agendar a instalação.")
            if self._janela is not None:
                threading.Timer(1.0, self._janela.destroy).start()
            return {
                "status": "installing",
                "version": info.version,
                "message": (
                    "Atualização validada. O aplicativo será fechado e "
                    "reiniciado automaticamente."
                ),
            }
        except Exception as erro:
            LOG.warning("Atualização manual não concluída: %s", erro)
            return {
                "status": "error",
                "version": __version__,
                "message": "Não foi possível buscar ou instalar a atualização.",
            }


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
        raise RuntimeError(
            "Configure PROSPECTA_WEB_URL com o link HTTPS da Web deste cliente."
        )

    _garantir_runner()
    bloquear_energia()
    try:
        import webview

        api = ApiAtualizacao()
        janela = webview.create_window(
            "Prospecta Flow",
            WEB_APP_URL,
            width=1440,
            height=900,
            min_size=(1024, 640),
            js_api=api,
        )
        api._vincular_janela(janela)
        webview.start(
            gui="edgechromium",
            private_mode=False,
            storage_path=str(data_path("webview")),
        )
    finally:
        liberar_energia()


if __name__ == "__main__":
    main()
