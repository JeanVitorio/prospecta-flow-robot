"""Janela desktop que incorpora a interface Web do LeadFlow."""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import threading
from typing import Any
from urllib.parse import urlsplit

from app_version import __version__
from atualizador import Atualizador
from app_paths import data_path, install_root, is_frozen, resource_path
from app_session import carregar_sessao, salvar_sessao
from execucao_bot import bloquear_energia, liberar_energia
from runner_remoto import MUTEX_NAME


WEB_APP_URL = os.getenv(
    "PROSPECTA_WEB_URL",
    "https://jvstech.com.br/LeadFlow/",
).strip()
LOG = logging.getLogger("prospecta_painel_web")
SYNCHRONIZE = 0x00100000
INTERVALO_SUPERVISAO = 20


class ApiAtualizacao:
    """Expõe à interface web somente a atualização nativa validada."""

    def __init__(self) -> None:
        # O pywebview percorre atributos públicos da API recursivamente.
        # Objetos internos precisam permanecer privados para evitar ciclos.
        self._atualizador = Atualizador(LOG)
        self._janela: Any | None = None

    def _vincular_janela(self, janela: Any) -> None:
        self._janela = janela

    def _origem_confiavel(self) -> bool:
        """Só a Web oficial pode acionar recursos nativos."""
        if self._janela is None:
            return False
        try:
            atual = urlsplit(str(self._janela.get_current_url() or ""))
        except Exception:
            return False
        esperado = urlsplit(WEB_APP_URL)
        prefixo = esperado.path.rstrip("/")
        return (
            atual.scheme == "https"
            and atual.netloc.casefold() == esperado.netloc.casefold()
            and (atual.path == prefixo or atual.path.startswith(prefixo + "/"))
        )

    def obter_versao_instalada(self) -> dict[str, str]:
        return {"version": __version__}

    def configurar_sessao(
        self, payload: dict[str, str]
    ) -> dict[str, str]:
        """Vincula o login web ao runner sem armazenar service_role."""
        if not self._origem_confiavel():
            LOG.warning("Sessão nativa recusada: origem não autorizada.")
            return {"status": "error", "message": "Origem não autorizada."}
        try:
            salvar_sessao(payload)
            _garantir_runner()
            return {
                "status": "connected",
                "message": "Executor conectado à sua conta.",
            }
        except Exception as erro:
            LOG.warning("Sessão nativa não configurada: %s", erro)
            return {
                "status": "error",
                "message": "Não foi possível conectar o executor.",
            }

    def buscar_e_instalar_atualizacao(self) -> dict[str, str]:
        if not self._origem_confiavel():
            LOG.warning("Atualização recusada: origem não autorizada.")
            return {
                "status": "error",
                "version": __version__,
                "message": "Origem não autorizada.",
            }
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


def _runner_ativo() -> bool:
    """Indica se o Runner já está rodando, pela trava global do Windows."""
    if os.name != "nt":
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenMutexW.argtypes = (ctypes.c_ulong, ctypes.c_bool, ctypes.c_wchar_p)
    kernel32.OpenMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel32.OpenMutexW(SYNCHRONIZE, False, MUTEX_NAME)
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True


def _supervisionar_runner(parar: threading.Event) -> None:
    """Com o painel aberto, o executor fica sempre de pé para a Web enxergar o PC."""
    while True:
        try:
            if carregar_sessao() and not _runner_ativo():
                LOG.info("Executor fora do ar; iniciando pelo painel.")
                _garantir_runner()
        except Exception as erro:
            LOG.warning("Não foi possível supervisionar o executor: %s", erro)
        if parar.wait(INTERVALO_SUPERVISAO):
            return


def main() -> None:
    if not WEB_APP_URL.startswith("https://"):
        raise RuntimeError(
            "Configure PROSPECTA_WEB_URL com o link HTTPS da Web deste cliente."
        )

    bloquear_energia()
    parar_supervisao = threading.Event()
    threading.Thread(
        target=_supervisionar_runner,
        args=(parar_supervisao,),
        name="supervisor-runner",
        daemon=True,
    ).start()
    try:
        import webview

        api = ApiAtualizacao()
        janela = webview.create_window(
            "LeadFlow",
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
        parar_supervisao.set()
        liberar_energia()


if __name__ == "__main__":
    main()
