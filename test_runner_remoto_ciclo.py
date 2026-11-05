"""Testes do ciclo do executor: uma etapa com falha não bloqueia as demais."""

from __future__ import annotations

import unittest
from threading import Event
from unittest.mock import MagicMock, call, patch

import bot_repository
from runner_remoto import RunnerRemoto


def runner_falhando_mensagens() -> RunnerRemoto:
    runner = RunnerRemoto.__new__(RunnerRemoto)
    runner.runner_id = "usuario:PC"
    runner.ambiente = "local"
    runner.gateway = MagicMock()
    runner.gateway.iniciar.return_value = True
    runner.processos = MagicMock()
    runner.atualizador = MagicMock()
    runner.atualizador.check_if_due.return_value = None
    runner._instalador_pendente = None
    runner._atualizar_identidade = MagicMock()
    runner._registrar = MagicMock()
    runner._processar_comandos = MagicMock()
    # Tabela sem permissão (403) para o usuário logado.
    runner._processar_comandos_mensagens = MagicMock(
        side_effect=bot_repository.ErroPersistencia("permission denied")
    )
    return runner


class CicloRunnerTest(unittest.TestCase):
    def test_falha_nos_comandos_de_mensagem_nao_bloqueia_o_ciclo(self) -> None:
        runner = runner_falhando_mensagens()
        with patch("runner_remoto.time.sleep", side_effect=KeyboardInterrupt):
            runner.executar()
        runner.atualizador.check_if_due.assert_called_once()
        runner.processos.limpar_finalizados.assert_called_once()

    def test_heartbeat_continua_depois_de_uma_falha(self) -> None:
        # O sinal de "PC disponível" tem thread própria: uma falha de rede não
        # pode interromper as próximas batidas nem sumir com o PC na Web.
        runner = runner_falhando_mensagens()
        runner._registrar.side_effect = [
            bot_repository.ErroPersistencia("offline"),
            None,
            None,
        ]
        parar = Event()
        with patch.object(parar, "wait", side_effect=[False, False, True]):
            runner._ciclo_heartbeat(parar)
        self.assertEqual(runner._registrar.call_count, 3)
        self.assertEqual(runner._registrar.call_args_list, [call("online")] * 3)

    def test_encerramento_marca_o_pc_como_offline(self) -> None:
        runner = runner_falhando_mensagens()
        with patch("runner_remoto.time.sleep", side_effect=KeyboardInterrupt):
            runner.executar()
        self.assertIn(call("offline"), runner._registrar.call_args_list)


if __name__ == "__main__":
    unittest.main()
