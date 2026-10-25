"""Testes do ciclo do executor: uma etapa com falha não bloqueia as demais."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

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

    def test_heartbeat_com_falha_e_repetido_no_proximo_ciclo(self) -> None:
        runner = runner_falhando_mensagens()
        runner._registrar.side_effect = [
            bot_repository.ErroPersistencia("offline"),
            None,
            None,
        ]
        with patch(
            "runner_remoto.time.sleep", side_effect=[None, KeyboardInterrupt]
        ):
            runner.executar()
        # Duas tentativas de "online" (falha + nova tentativa) e o "offline" final.
        self.assertEqual(runner._registrar.call_count, 3)


if __name__ == "__main__":
    unittest.main()
