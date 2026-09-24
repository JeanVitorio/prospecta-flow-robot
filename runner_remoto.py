"""Executor independente para comandos enviados pelo Supabase."""

from __future__ import annotations

import os
import platform
import socket
import time
import logging
from typing import Any

import bot_config
import bot_repository
import message_repository
from painel_processos import GerenciadorProcessos
from whatsapp_gateway_process import GatewayWhatsApp

LOG = logging.getLogger("prospecta_runner")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


class RunnerRemoto:
    """Mantém uma máquina disponível para iniciar bots sem depender do painel."""

    def __init__(self) -> None:
        hostname = socket.gethostname() or platform.node() or "executor"
        self.runner_id = os.getenv("PROSPECTA_RUNNER_ID", hostname).strip()
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

    def executar(self) -> None:
        os.environ["PROSPECTA_RUNNER_ID"] = self.runner_id
        os.environ["PROSPECTA_RUNNER_ENV"] = self.ambiente
        self.gateway_ativo = self.gateway.iniciar()
        proximo_heartbeat = 0.0
        try:
            while True:
                try:
                    agora = time.monotonic()
                    if agora >= proximo_heartbeat:
                        self._registrar("online")
                        proximo_heartbeat = agora + 60
                    self._processar_comandos()
                    self._processar_comandos_mensagens()
                    self.processos.limpar_finalizados()
                except bot_repository.ErroPersistencia as erro:
                    LOG.warning("Supabase indisponível; nova tentativa em breve: %s", erro)
                time.sleep(10)
        except KeyboardInterrupt:
            LOG.info("Encerramento do executor solicitado.")
        finally:
            self.gateway.parar()
            try:
                self._registrar("offline")
            except bot_repository.ErroPersistencia:
                pass

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
        if not self.gateway_ativo:
            return
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


def main() -> None:
    RunnerRemoto().executar()


if __name__ == "__main__":
    main()
