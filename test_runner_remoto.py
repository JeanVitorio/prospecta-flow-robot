"""Testes do gate de transporte no executor remoto."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from runner_remoto import RunnerRemoto


class RunnerRemotoTest(unittest.TestCase):
    def _runner(self) -> RunnerRemoto:
        runner = RunnerRemoto.__new__(RunnerRemoto)
        runner.runner_id = "runner-1"
        runner.gateway_ativo = False
        runner.processos = MagicMock()
        runner._requisicoes_confirmadas = set()
        return runner

    @patch("runner_remoto.message_repository.confirmar_comando")
    @patch("runner_remoto.message_repository.carregar_config")
    @patch("runner_remoto.message_repository.listar_comandos_runner")
    def test_meta_inicia_mesmo_sem_gateway(
        self,
        listar: MagicMock,
        carregar: MagicMock,
        confirmar: MagicMock,
    ) -> None:
        listar.return_value = [
            {
                "bot_id": "bot-meta",
                "request_id": "req-meta",
                "command": "rodando",
            }
        ]
        carregar.return_value = {
            "slug": "campanha-meta",
            "provider": "meta_cloud_api",
        }
        runner = self._runner()

        runner._processar_comandos_mensagens()

        runner.processos.iniciar_mensagens.assert_called_once_with(
            "campanha-meta"
        )
        confirmar.assert_called_once_with("bot-meta", "req-meta")

    @patch("runner_remoto.message_repository.confirmar_comando")
    @patch("runner_remoto.message_repository.carregar_config")
    @patch("runner_remoto.message_repository.listar_comandos_runner")
    def test_web_continua_exigindo_gateway(
        self,
        listar: MagicMock,
        carregar: MagicMock,
        confirmar: MagicMock,
    ) -> None:
        listar.return_value = [
            {
                "bot_id": "bot-web",
                "request_id": "req-web",
                "command": "rodando",
            }
        ]
        carregar.return_value = {
            "slug": "campanha-web",
            "provider": "whatsapp_web",
        }
        runner = self._runner()

        runner._processar_comandos_mensagens()

        runner.processos.iniciar_mensagens.assert_not_called()
        confirmar.assert_not_called()


if __name__ == "__main__":
    unittest.main()
