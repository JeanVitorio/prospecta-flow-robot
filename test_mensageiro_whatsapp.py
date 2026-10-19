"""Testes da seleção e preservação dos transportes de WhatsApp."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import message_repository
from mensageiro_whatsapp import MensageiroWhatsApp


class MensageiroWhatsAppTest(unittest.TestCase):
    def _config(self, provider: str) -> dict[str, object]:
        return {
            "id": "bot-1",
            "slug": "campanha",
            "whatsapp_session_id": "sessao-1",
            "provider": provider,
            "message_template": "Olá, {nome}",
        }

    @patch.dict("os.environ", {"PROSPECTA_RUNNER_ID": "runner-1"})
    @patch("mensageiro_whatsapp.ClienteMetaCloudAPI")
    @patch("mensageiro_whatsapp.ClienteGateway")
    @patch("mensageiro_whatsapp.criar_logger")
    @patch("mensageiro_whatsapp.data_path")
    @patch("mensageiro_whatsapp.repositorio.carregar_config")
    def test_seleciona_cliente_meta_sem_gateway(
        self,
        carregar_config: MagicMock,
        _data_path: MagicMock,
        _logger: MagicMock,
        cliente_gateway: MagicMock,
        cliente_meta: MagicMock,
    ) -> None:
        carregar_config.return_value = self._config("meta_cloud_api")

        mensageiro = MensageiroWhatsApp("campanha")

        cliente_gateway.assert_not_called()
        cliente_meta.assert_called_once_with()
        self.assertIsNone(mensageiro.gateway)

    @patch.dict("os.environ", {"PROSPECTA_RUNNER_ID": "runner-1"})
    @patch("mensageiro_whatsapp.ClienteMetaCloudAPI")
    @patch("mensageiro_whatsapp.ClienteGateway")
    @patch("mensageiro_whatsapp.criar_logger")
    @patch("mensageiro_whatsapp.data_path")
    @patch("mensageiro_whatsapp.repositorio.carregar_config")
    def test_provider_desconhecido_falha_sem_abrir_transporte(
        self,
        carregar_config: MagicMock,
        _data_path: MagicMock,
        _logger: MagicMock,
        cliente_gateway: MagicMock,
        cliente_meta: MagicMock,
    ) -> None:
        carregar_config.return_value = self._config("desconhecido")

        with self.assertRaisesRegex(RuntimeError, "não suportado"):
            MensageiroWhatsApp("campanha")

        cliente_gateway.assert_not_called()
        cliente_meta.assert_not_called()

    @patch("mensageiro_whatsapp.repositorio.finalizar_entrega")
    def test_modo_local_mantem_envio_e_finalizacao(
        self, finalizar: MagicMock
    ) -> None:
        mensageiro = MensageiroWhatsApp.__new__(MensageiroWhatsApp)
        mensageiro.provider = message_repository.PROVIDER_WHATSAPP_WEB
        mensageiro.session_id = "sessao-1"
        mensageiro.config = {"message_template": "Olá, {nome}"}
        mensageiro.gateway = MagicMock()
        mensageiro.gateway.enviar.return_value = {
            "exists": True,
            "sent": True,
        }
        mensageiro.meta = None
        mensageiro._runtime = MagicMock()

        mensageiro._processar_lead(
            {
                "delivery_id": 10,
                "claim_token": "claim-local",
                "lead_id": "lead-1",
                "phone": "5511999999999",
                "name": "Ana",
            }
        )

        mensageiro.gateway.enviar.assert_called_once_with(
            "sessao-1", "5511999999999", "Olá, Ana"
        )
        finalizar.assert_called_once_with(10, "claim-local", "sent")

    @patch("mensageiro_whatsapp.repositorio.finalizar_entrega")
    def test_meta_nao_finaliza_entrega_no_desktop(
        self, finalizar: MagicMock
    ) -> None:
        mensageiro = MensageiroWhatsApp.__new__(MensageiroWhatsApp)
        mensageiro.provider = message_repository.PROVIDER_META_CLOUD_API
        mensageiro.config = {"message_template": "Olá"}
        mensageiro.gateway = None
        mensageiro.meta = MagicMock()
        mensageiro._runtime = MagicMock()

        mensageiro._processar_lead(
            {
                "delivery_id": 11,
                "claim_token": "claim-meta",
                "lead_id": "lead-2",
            }
        )

        mensageiro.meta.enviar.assert_called_once_with(11, "claim-meta")
        finalizar.assert_not_called()


if __name__ == "__main__":
    unittest.main()
