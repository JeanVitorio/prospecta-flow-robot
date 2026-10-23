"""Testes do WhatsApp de validação mantido pelo executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import bot_repository
from sincronizador_validacao import SincronizadorValidacao

LISTAR = "sincronizador_validacao.repositorio.listar_sessoes_validacao"
ATUALIZAR = "sincronizador_validacao.repositorio.atualizar_sessao"


def sessao(status: str = "connecting", **extra: object) -> dict[str, object]:
    return {
        "id": "s1",
        "status": status,
        "connected_number": None,
        "qr_code_data_url": None,
        "last_error": None,
        **extra,
    }


class SincronizadorValidacaoTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sync = SincronizadorValidacao(MagicMock())
        self.sync.gateway = MagicMock()

    @patch(ATUALIZAR)
    @patch(LISTAR)
    def test_publica_qr_code_e_acelera_ciclo(
        self, listar: MagicMock, atualizar: MagicMock
    ) -> None:
        listar.return_value = [sessao()]
        self.sync.gateway.status.side_effect = RuntimeError(
            "Sessão ainda não foi iniciada."
        )
        self.sync.gateway.conectar.return_value = {
            "status": "qr_pending",
            "qr_code_data_url": "data:image/png;base64,abc",
        }

        self.assertTrue(self.sync.sincronizar("runner-1"))
        dados = atualizar.call_args.args[1]
        self.assertEqual("qr_pending", dados["status"])
        self.assertEqual("data:image/png;base64,abc", dados["qr_code_data_url"])

    @patch(ATUALIZAR)
    @patch(LISTAR)
    def test_nao_grava_quando_nada_mudou(
        self, listar: MagicMock, atualizar: MagicMock
    ) -> None:
        listar.return_value = [sessao("ready", connected_number="5511999999999")]
        self.sync.gateway.status.return_value = {
            "status": "ready",
            "connected_number": "5511999999999",
        }

        self.assertFalse(self.sync.sincronizar("runner-1"))
        atualizar.assert_not_called()

    @patch(ATUALIZAR)
    @patch(LISTAR)
    def test_qr_expirado_desconecta(
        self, listar: MagicMock, atualizar: MagicMock
    ) -> None:
        listar.return_value = [sessao("qr_pending")]
        self.sync.gateway.status.return_value = {"status": "qr_pending"}
        self.sync.qr_desde["s1"] = -1_000.0

        self.assertFalse(self.sync.sincronizar("runner-1"))
        self.sync.gateway.desconectar.assert_called_once_with("s1")
        self.assertEqual("disconnected", atualizar.call_args.args[1]["status"])

    @patch(ATUALIZAR)
    @patch(LISTAR)
    def test_falha_persistente_reinicia_uma_vez_so(
        self, listar: MagicMock, atualizar: MagicMock
    ) -> None:
        listar.return_value = [sessao()]
        self.sync.gateway.status.return_value = {
            "status": "error",
            "last_error": "falhou",
        }
        self.sync.gateway.conectar.return_value = {"status": "connecting"}

        self.sync.sincronizar("runner-1")
        self.sync.sincronizar("runner-1")

        self.sync.gateway.conectar.assert_called_once_with("s1")
        self.assertEqual("error", atualizar.call_args.args[1]["status"])

    @patch(ATUALIZAR)
    @patch(LISTAR)
    def test_sessao_removida_na_web_faz_logout(
        self, listar: MagicMock, _atualizar: MagicMock
    ) -> None:
        self.sync.conhecidas = {"antiga"}
        listar.return_value = []

        self.sync.sincronizar("runner-1")

        self.sync.gateway.desconectar.assert_called_once_with("antiga")

    @patch(LISTAR)
    def test_falha_no_supabase_nao_interrompe(self, listar: MagicMock) -> None:
        listar.side_effect = bot_repository.ErroPersistencia("offline")

        self.assertFalse(self.sync.sincronizar("runner-1"))


if __name__ == "__main__":
    unittest.main()
