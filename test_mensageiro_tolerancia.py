"""Banco lento não pode derrubar um agente de mensagens que está enviando."""

from __future__ import annotations

import logging
import unittest
from unittest.mock import MagicMock, patch

import bot_repository
import mensageiro_whatsapp as motor
from mensageiro_whatsapp import MensageiroWhatsApp, ParadaMensageiro


def _agente() -> MensageiroWhatsApp:
    agente = MensageiroWhatsApp.__new__(MensageiroWhatsApp)
    agente.bot_id = "bot-1"
    agente.session_id = "sessao-1"
    agente.runner_id = "executor-1"
    agente.log = logging.getLogger("teste_mensageiro_tolerancia")
    agente.log.addHandler(logging.NullHandler())
    agente.log.propagate = False
    agente.proxima_consulta_controle = 0.0
    agente.proximo_heartbeat = 0.0
    agente.proximo_status_sessao = 0.0
    agente.ultimo_estado_sessao = None
    agente.falhas_controle = 0
    return agente


class ToleranciaTest(unittest.TestCase):
    def test_andamento_que_falha_nao_derruba_o_agente(self) -> None:
        agente = _agente()
        with patch.object(
            motor.repositorio,
            "atualizar_runtime",
            side_effect=bot_repository.ErroPersistencia("timeout"),
        ):
            agente._runtime("running")  # não pode levantar exceção

    def test_estado_da_sessao_que_falha_nao_derruba_o_agente(self) -> None:
        agente = _agente()
        with patch.object(
            motor.repositorio,
            "atualizar_sessao",
            side_effect=bot_repository.ErroPersistencia("timeout"),
        ):
            agente._sincronizar_sessao({"status": "ready"}, forcar=True)
        # Como não gravou, a próxima volta tenta de novo.
        self.assertIsNone(agente.ultimo_estado_sessao)

    def test_estado_gravado_nao_e_reenviado(self) -> None:
        agente = _agente()
        with patch.object(motor.repositorio, "atualizar_sessao") as gravar:
            agente._sincronizar_sessao({"status": "ready"}, forcar=False)
            agente._sincronizar_sessao({"status": "ready"}, forcar=False)
        gravar.assert_called_once()

    def test_falha_passageira_no_comando_nao_para_o_agente(self) -> None:
        agente = _agente()
        with patch.object(
            motor.repositorio,
            "ler_comando",
            side_effect=bot_repository.ErroPersistencia("timeout"),
        ), patch.object(motor.time, "monotonic", side_effect=[0.0, 100.0, 200.0]):
            agente._verificar_controle()
            agente._verificar_controle()
        self.assertEqual(agente.falhas_controle, 2)

    def test_para_quando_nao_consegue_mais_ler_o_comando(self) -> None:
        agente = _agente()
        agente.falhas_controle = motor.MAX_FALHAS_CONTROLE - 1
        with patch.object(
            motor.repositorio,
            "ler_comando",
            side_effect=bot_repository.ErroPersistencia("timeout"),
        ), patch.object(motor.time, "monotonic", return_value=0.0):
            with self.assertRaises(ParadaMensageiro):
                agente._verificar_controle()

    def test_leitura_bem_sucedida_zera_as_falhas(self) -> None:
        agente = _agente()
        agente.falhas_controle = 3
        with patch.object(
            motor.repositorio, "ler_comando", return_value={"command": "rodando"}
        ), patch.object(motor.time, "monotonic", return_value=0.0):
            agente._verificar_controle()
        self.assertEqual(agente.falhas_controle, 0)


class RepositorioMensagensTest(unittest.TestCase):
    def test_erro_401_descarta_a_conexao(self) -> None:
        import message_repository

        bot_repository._cliente = object()

        def chamada():
            raise RuntimeError("{'code': 401, 'message': 'Invalid JWT'}")

        with self.assertRaises(bot_repository.ErroPersistencia):
            message_repository._executar("atualizar a sessão", chamada)
        self.assertIsNone(bot_repository.cliente_autenticado())


if __name__ == "__main__":
    unittest.main()
