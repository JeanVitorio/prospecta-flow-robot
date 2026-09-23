"""Gerenciamento dos processos iniciados pelo painel."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import bot_config


class GerenciadorProcessos:
    """Inicia uma única dupla de processos por bot em cada sessão."""

    def __init__(self, runner_id: str | None = None) -> None:
        self._processos: dict[str, dict[str, subprocess.Popen[Any]]] = {}
        self._lock = threading.RLock()
        self._diretorio = Path(__file__).resolve().parent
        self._runner_id = runner_id

    def iniciar(self, slug: str, registrar_comando: bool = True) -> None:
        """Define o comando e inicia somente os processos ainda inativos."""
        if registrar_comando:
            bot_config.definir_comando(slug, "rodando")
        with self._lock:
            processos = self._processos.setdefault(slug, {})
            for nome in ("scraper", "importador"):
                atual = processos.get(nome)
                if atual is not None and atual.poll() is None:
                    continue
                if self._runtime_ativo(slug, nome):
                    continue
                processos[nome] = self._abrir(slug, nome)

    def iniciar_mensagens(self, slug: str) -> None:
        """Inicia um único motor de mensagens para a configuração remota."""
        chave = f"mensagens:{slug}"
        with self._lock:
            processos = self._processos.setdefault(chave, {})
            atual = processos.get("mensagens")
            if atual is not None and atual.poll() is None:
                return
            processos["mensagens"] = self._abrir(slug, "mensagens")

    def definir_comando(self, slug: str, comando: str) -> None:
        """Encaminha pausa, continuação ou parada ao contrato existente."""
        bot_config.definir_comando(slug, comando)

    def status(self, slug: str) -> str:
        """Retorna o estado dos processos conhecidos nesta sessão."""
        with self._lock:
            processos = self._processos.get(slug, {})
            ativos = {
                nome for nome, proc in processos.items() if proc.poll() is None
            }
        ativos.update(
            nome
            for nome in ("scraper", "importador")
            if self._runtime_ativo(slug, nome)
        )
        if len(ativos) == 2:
            return "Executando"
        if ativos:
            return f"Executando {next(iter(ativos))}"
        return "Inativo"

    def possui_ativos(self) -> bool:
        with self._lock:
            return any(
                processo.poll() is None
                for processos in self._processos.values()
                for processo in processos.values()
            )

    def limpar_finalizados(self) -> None:
        with self._lock:
            for slug, processos in list(self._processos.items()):
                self._processos[slug] = {
                    nome: processo
                    for nome, processo in processos.items()
                    if processo.poll() is None
                }
                if not self._processos[slug]:
                    del self._processos[slug]

    def _abrir(self, slug: str, processo: str) -> subprocess.Popen[Any]:
        pasta = (
            Path(__file__).resolve().parent / "dados_mensagens" / slug
            if processo == "mensagens"
            else bot_config.pasta_bot(slug)
        )
        pasta.mkdir(parents=True, exist_ok=True)
        caminho_log = pasta / f"painel_{processo}.log"
        log = caminho_log.open("a", encoding="utf-8", buffering=1)
        flags = 0
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            flags |= subprocess.CREATE_NEW_PROCESS_GROUP
        if hasattr(subprocess, "DETACHED_PROCESS"):
            flags |= subprocess.DETACHED_PROCESS
        ambiente = os.environ.copy()
        if self._runner_id:
            ambiente["PROSPECTA_RUNNER_ID"] = self._runner_id
            ambiente["PROSPECTA_PRESERVAR_COMANDO"] = "1"
        try:
            return subprocess.Popen(
                [sys.executable, "bot_dinamico.py", processo, slug],
                cwd=self._diretorio,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=flags,
                env=ambiente,
            )
        finally:
            log.close()

    @staticmethod
    def _runtime_ativo(slug: str, processo: str) -> bool:
        """Reconhece processos preservados após o painel ser fechado."""
        try:
            runtime = bot_config.ler_runtime(slug, processo)
            pid = int((runtime or {}).get("pid", 0))
        except (OSError, TypeError, ValueError):
            return False
        if pid <= 0:
            return False
        if os.name != "nt":
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                bot_config.remover_runtime(slug, processo)
                return False
        processo_handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not processo_handle:
            bot_config.remover_runtime(slug, processo)
            return False
        try:
            codigo = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(
                processo_handle, ctypes.byref(codigo)
            ):
                return False
            return codigo.value == 259
        finally:
            ctypes.windll.kernel32.CloseHandle(processo_handle)


def caminhos_logs(slug: str) -> list[Path]:
    """Lista apenas logs pertencentes à pasta segura do bot."""
    pasta = bot_config.pasta_bot(slug)
    return [
        pasta / "scraper.log",
        pasta / "importador.log",
        pasta / "painel_scraper.log",
        pasta / "painel_importador.log",
    ]
