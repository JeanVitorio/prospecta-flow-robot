"""Envio dos logs do app ao banco: filtro, mascaramento e nova tentativa."""

from __future__ import annotations

import logging
import unittest
from unittest import mock

import log_remoto


def _registro(nome: str, mensagem: str, nivel: int = logging.INFO) -> logging.LogRecord:
    return logging.LogRecord(nome, nivel, __file__, 1, mensagem, None, None)


class LogRemotoTest(unittest.TestCase):
    def setUp(self) -> None:
        with mock.patch.object(log_remoto.threading.Thread, "start"), mock.patch.object(
            log_remoto.atexit, "register"
        ):
            self.handler = log_remoto.HandlerLogRemoto()

    def test_ignora_bibliotecas_de_rede(self) -> None:
        self.handler.emit(_registro("httpx", "HTTP Request: POST"))
        self.handler.emit(_registro("supabase.client", "x"))
        self.assertEqual(len(self.handler._fila), 0)

    def test_mascara_tokens_e_chaves(self) -> None:
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.assinatura"
        self.handler.emit(
            _registro("prospecta_runner", f"token {jwt} chave sb_secret_abc Bearer xyz.123")
        )
        mensagem = self.handler._fila[0]["message"]
        self.assertNotIn(jwt, mensagem)
        self.assertNotIn("sb_secret_abc", mensagem)
        self.assertNotIn("xyz.123", mensagem)
        self.assertIn("[oculto]", mensagem)

    def test_falha_no_envio_mantem_fila_em_ordem(self) -> None:
        for indice in range(3):
            self.handler.emit(_registro("bot", f"m{indice}", logging.WARNING))
        with mock.patch.object(log_remoto, "_enviar_lote", return_value=False):
            self.handler.enviar()
        self.assertEqual([item["message"] for item in self.handler._fila], ["m0", "m1", "m2"])
        with mock.patch.object(log_remoto, "_enviar_lote", return_value=True) as envio:
            self.handler.enviar()
        self.assertEqual(len(self.handler._fila), 0)
        self.assertEqual(envio.call_args[0][0][0]["level"], "WARNING")


if __name__ == "__main__":
    unittest.main()
