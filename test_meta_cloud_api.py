"""Testes do contrato HTTP com a Edge Function."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from meta_cloud_api import ClienteMetaCloudAPI


class ClienteMetaCloudAPITest(unittest.TestCase):
    @patch("meta_cloud_api._abrir")
    @patch("meta_cloud_api.carregar_sessao")
    @patch("meta_cloud_api.bot_repository.obter_cliente")
    def test_envia_somente_referencias_com_jwt(
        self,
        obter_cliente: MagicMock,
        carregar_sessao: MagicMock,
        abrir: MagicMock,
    ) -> None:
        carregar_sessao.return_value = {
            "supabase_url": "https://projeto.supabase.co/",
            "publishable_key": "chave-publica",
            "access_token": "jwt-usuario",
            "refresh_token": "nao-enviado",
        }
        abrir.return_value.__enter__.return_value = MagicMock()

        ClienteMetaCloudAPI(timeout=12).enviar(123, "claim-abc")

        obter_cliente.assert_called_once_with()
        request = abrir.call_args.args[0]
        self.assertEqual(
            "https://projeto.supabase.co/functions/v1/whatsapp-meta-send",
            request.full_url,
        )
        self.assertEqual(
            {"delivery_id": 123, "claim_token": "claim-abc"},
            json.loads(request.data),
        )
        self.assertEqual("chave-publica", request.get_header("Apikey"))
        self.assertEqual(
            "Bearer jwt-usuario", request.get_header("Authorization")
        )
        self.assertEqual(12, abrir.call_args.kwargs["timeout"])


if __name__ == "__main__":
    unittest.main()
