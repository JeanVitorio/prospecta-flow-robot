"""Executor independente para comandos enviados pelo Supabase."""

from __future__ import annotations

import ctypes
import os
import platform
import socket
import time
import logging
from typing import Any, Callable

import bot_config
import bot_repository
import message_repository
from atualizador import Atualizador
from app_session import usuario_sessao
from painel_processos import GerenciadorProcessos
from whatsapp_gateway_process import GatewayWhatsApp

LOG = logging.getLogger("prospecta_runner")
MUTEX_NAME = r"Local\ProspectaFlow.Runner"
ERROR_ALREADY_EXISTS = 183
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


class RunnerRemoto:
    """Mantém uma máquina disponível para iniciar bots sem depender do painel."""

    def __init__(self) -> None:
        hostname = socket.gethostname() or platform.node() or "executor"
        usuario_id = usuario_sessao()
        runner_padrao = (
            f"{usuario_id}:{hostname}" if usuario_id else hostname
        )
        self.runner_id = os.getenv(
            "PROSPECTA_RUNNER_ID", runner_padrao
        ).strip()
        if not self.runner_id:
            raise RuntimeError("PROSPECTA_RUNNER_ID não pode ser vazio.")
        self.ambiente = os.getenv(
            "PROSPECTA_RUNNER_ENV",
            "render" if os.getenv("RENDER") else "local",
        ).strip()
        self.nome = os.getenv("PROSPECTA_RUNNER_NAME", hostname).strip()
        self.processos = GerenciadorProcessos(self.runner_id)
        self._requisicoes_confirmadas: set[str] = set()
        self.gateway = GatewayWhatsApp(LOG)
        self.gateway_ativo = False
        self.atualizador = Atualizador(LOG)
        self._instalador_pendente = None

    def executar(self) -> None:
        os.environ["PROSPECTA_RUNNER_ID"] = self.runner_id
        os.environ["PROSPECTA_RUNNER_ENV"] = self.ambiente
        self.gateway_ativo = self.gateway.iniciar()
        proximo_heartbeat = 0.0
        try:
            while True:
                intervalo = 10
                try:
                    self._etapa(self._atualizar_identidade)
                    agora = time.monotonic()
                    if agora >= proximo_heartbeat and self._etapa(
                        self._registrar, "online"
                    ):
                        proximo_heartbeat = agora + 60
                    # Cada etapa é isolada: uma tabela sem acesso não pode
                    # impedir as demais etapas nem as atualizações.
                    self._etapa(self._processar_comandos)
                    self._etapa(self._processar_comandos_mensagens)
                    self.processos.limpar_finalizados()
                    self._instalador_pendente = (
                        self._instalador_pendente
                        or self.atualizador.check_if_due()
                    )
                    if (
                        self._instalador_pendente
                        and not self.processos.possui_ativos()
                        and self.atualizador.schedule_install(
                            self._instalador_pendente
                        )
                    ):
                        LOG.info("Atualização agendada; encerrando versão atual.")
                        return
                except bot_repository.ErroPersistencia as erro:
                    LOG.warning("Supabase indisponível; nova tentativa em breve: %s", erro)
                time.sleep(intervalo)
        except KeyboardInterrupt:
            LOG.info("Encerramento do executor solicitado.")
        finally:
            self.gateway.parar()
            try:
                self._registrar("offline")
            except bot_repository.ErroPersistencia:
                pass

    @staticmethod
    def _etapa(funcao: Callable[..., Any], *args: Any) -> bool:
        """Executa uma etapa do ciclo e informa se ela terminou sem falha."""
        try:
            funcao(*args)
            return True
        except bot_repository.ErroPersistencia as erro:
            LOG.warning("Supabase indisponível; nova tentativa em breve: %s", erro)
            return False

    def _atualizar_identidade(self) -> None:
        usuario_id = usuario_sessao()
        if not usuario_id or self.runner_id.startswith(f"{usuario_id}:"):
            return
        hostname = socket.gethostname() or platform.node() or "executor"
        self.runner_id = f"{usuario_id}:{hostname}"
        os.environ["PROSPECTA_RUNNER_ID"] = self.runner_id
        self.processos = GerenciadorProcessos(self.runner_id)

    def _processar_comandos(self) -> None:
        for controle in bot_repository.listar_comandos_runner(self.runner_id):
            bot_id = str(controle.get("bot_id", ""))
            requisicao = str(controle.get("request_id", ""))
            comando = str(controle.get("command", "")).casefold()
            if not bot_id or not requisicao:
                continue
            config = bot_config.carregar_config(bot_id)
            if not config:
                continue
            if comando == "rodando":
                self.processos.iniciar(
                    config["slug"], registrar_comando=False
                )
            if requisicao not in self._requisicoes_confirmadas:
                bot_repository.confirmar_comando(bot_id, requisicao)
                self._requisicoes_confirmadas.add(requisicao)

    def _processar_comandos_mensagens(self) -> None:
        for controle in message_repository.listar_comandos_runner(
            self.runner_id
        ):
            bot_id = str(controle.get("bot_id", ""))
            requisicao = str(controle.get("request_id", ""))
            comando = str(controle.get("command", "")).casefold()
            if not bot_id or not requisicao:
                continue
            if requisicao in self._requisicoes_confirmadas:
                continue
            config = message_repository.carregar_config(bot_id)
            if not config:
                message_repository.confirmar_comando(bot_id, requisicao)
                self._requisicoes_confirmadas.add(requisicao)
                continue
            provider = message_repository.obter_provider(config)
            if provider not in message_repository.PROVIDERS_SUPORTADOS:
                LOG.error(
                    "Comando de mensagens ignorado: provider não suportado."
                )
                message_repository.confirmar_comando(bot_id, requisicao)
                self._requisicoes_confirmadas.add(requisicao)
                continue
            if (
                provider == message_repository.PROVIDER_WHATSAPP_WEB
                and not self.gateway_ativo
            ):
                continue
            if comando == "rodando":
                self.processos.iniciar_mensagens(str(config["slug"]))
            message_repository.confirmar_comando(bot_id, requisicao)
            self._requisicoes_confirmadas.add(requisicao)

    def _registrar(self, status: str) -> None:
        metadata: dict[str, Any] = {
            "hostname": socket.gethostname(),
            "sistema": platform.system(),
            "versao_python": platform.python_version(),
            "whatsapp_gateway": self.gateway_ativo,
        }
        bot_repository.registrar_runner(
            self.runner_id,
            self.nome,
            self.ambiente,
            metadata,
            status,
        )


def _adquirir_instancia_unica() -> int | None:
    """Mantém somente um Runner ativo na sessão atual do Windows."""
    if os.name != "nt":
        return 1
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return int(handle)


def main() -> None:
    handle = _adquirir_instancia_unica()
    if handle is None:
        LOG.info("O Runner já está ativo nesta sessão.")
        return
    try:
        RunnerRemoto().executar()
    finally:
        if os.name == "nt":
            ctypes.windll.kernel32.CloseHandle(handle)


if __name__ == "__main__":
    main()
