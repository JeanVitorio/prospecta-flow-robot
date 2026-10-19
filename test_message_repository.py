"""Testes da compatibilidade de providers de WhatsApp."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import bot_repository
import message_repository


class ProviderTest(unittest.TestCase):
    def test_schema_legado_usa_whatsapp_web(self) -> None:
        self.assertEqual(
            message_repository.PROVIDER_WHATSAPP_WEB,
            message_repository.obter_provider({}),
        )

    def test_provider_relacionado_e_normalizado(self) -> None:
        config = {
            "whatsapp_session": {"provider": " META_CLOUD_API "}
        }
        self.assertEqual(
            message_repository.PROVIDER_META_CLOUD_API,
            message_repository.obter_provider(config),
        )

    def test_provider_desconhecido_nao_e_convertido_em_web(self) -> None:
        self.assertEqual(
            "outro",
            message_repository.obter_provider({"provider": "OUTRO"}),
        )

    @patch("message_repository._consultar_config")
    def test_select_novo_indisponivel_recua_para_schema_legado(
        self, consultar
    ) -> None:
        consultar.side_effect = [
            bot_repository.ErroPersistencia("schema antigo"),
            [{"id": "bot-1", "slug": "campanha"}],
        ]

        config = message_repository.carregar_config("campanha")

        self.assertEqual("whatsapp_web", config["provider"])
        self.assertEqual("*", consultar.call_args_list[1].args[2])


if __name__ == "__main__":
    unittest.main()
