"""Testes do transporte WhatsApp Web dos agentes de mensagens."""

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
    @patch("mensageiro_whatsapp.ClienteGateway")
    @patch("mensageiro_whatsapp.criar_logger")
    @patch("mensageiro_whatsapp.data_path")
    @patch("mensageiro_whatsapp.repositorio.carregar_config")
    def test_whatsapp_web_abre_gateway(
        self,
        carregar_config: MagicMock,
        _data_path: MagicMock,
        _logger: MagicMock,
        cliente_gateway: MagicMock,
    ) -> None:
        carregar_config.return_value = self._config("whatsapp_web")

        mensageiro = MensageiroWhatsApp("campanha")

        cliente_gateway.assert_called_once_with()
        self.assertIs(mensageiro.gateway, cliente_gateway.return_value)

    @patch.dict("os.environ", {"PROSPECTA_RUNNER_ID": "runner-1"})
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
    ) -> None:
        carregar_config.return_value = self._config("meta_cloud_api")

        with self.assertRaisesRegex(RuntimeError, "não suportado"):
            MensageiroWhatsApp("campanha")

        cliente_gateway.assert_not_called()

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


if __name__ == "__main__":
    unittest.main()
