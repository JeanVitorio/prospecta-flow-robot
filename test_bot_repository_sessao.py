"""Conexão com o Supabase: login que falha não pode ficar guardado."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

import bot_repository


class ClienteFake:
    def __init__(self, renovar) -> None:
        self.auth = SimpleNamespace(
            refresh_session=renovar,
            set_session=lambda *_args: None,
            on_auth_state_change=lambda *_args: None,
        )


class ObterClienteTest(unittest.TestCase):
    def setUp(self) -> None:
        bot_repository.descartar_cliente()
        self.sessao = {
            "supabase_url": "https://exemplo.supabase.co",
            "publishable_key": "sb_publishable_teste",
            "refresh_token": "refresh-123",
            "access_token": "access-123",
        }

    def tearDown(self) -> None:
        bot_repository.descartar_cliente()

    def _supabase(self, renovar):
        modulo = SimpleNamespace(
            create_client=lambda *_args: ClienteFake(renovar)
        )
        return mock.patch.dict("sys.modules", {"supabase": modulo})

    def test_falha_na_renovacao_nao_guarda_cliente(self) -> None:
        def renovar(_token):
            raise RuntimeError("refresh token já utilizado")

        with mock.patch.object(
            bot_repository, "carregar_sessao", return_value=self.sessao
        ), self._supabase(renovar):
            with self.assertRaises(bot_repository.ErroPersistencia):
                bot_repository.obter_cliente()
        self.assertIsNone(bot_repository.cliente_autenticado())

    def test_nova_tentativa_conecta_depois_da_falha(self) -> None:
        tentativas = {"total": 0}

        def renovar(_token):
            tentativas["total"] += 1
            if tentativas["total"] == 1:
                raise RuntimeError("refresh token já utilizado")
            return SimpleNamespace(
                session=SimpleNamespace(
                    access_token="novo-access", refresh_token="novo-refresh"
                )
            )

        with mock.patch.object(
            bot_repository, "carregar_sessao", return_value=self.sessao
        ), mock.patch.object(
            bot_repository, "salvar_sessao"
        ), self._supabase(renovar):
            with self.assertRaises(bot_repository.ErroPersistencia):
                bot_repository.obter_cliente()
            self.assertIsNotNone(bot_repository.obter_cliente())
        self.assertEqual(tentativas["total"], 2)

    def test_erro_401_descarta_o_cliente(self) -> None:
        bot_repository._cliente = object()

        def chamada():
            raise RuntimeError("{'code': 401, 'message': 'Invalid JWT'}")

        with self.assertRaises(bot_repository.ErroPersistencia):
            bot_repository._executar("registrar o executor", chamada)
        self.assertIsNone(bot_repository.cliente_autenticado())


if __name__ == "__main__":
    unittest.main()
