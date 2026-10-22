"""Testes da validação de telefones no WhatsApp antes de salvar leads."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from validador_whatsapp import ValidadorWhatsApp, normalizar_telefone


class NormalizarTelefoneTest(unittest.TestCase):
    def test_adiciona_ddi_brasil(self) -> None:
        self.assertEqual("551141645358", normalizar_telefone("(11) 4164-5358"))

    def test_rejeita_sem_telefone(self) -> None:
        self.assertEqual("", normalizar_telefone("não encontrado"))


@patch("validador_whatsapp.time.sleep", MagicMock())
class ValidadorWhatsAppTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pasta = tempfile.TemporaryDirectory()
        self.addCleanup(self.pasta.cleanup)
        self.validador = ValidadorWhatsApp(Path(self.pasta.name), MagicMock())
        self.validador.gateway = MagicMock()
        self.validador.session_id = "sessao-1"

    def test_numero_inexistente_e_memorizado(self) -> None:
        self.validador.gateway.validar.return_value = {"exists": False}

        self.assertFalse(self.validador.validar("11 4164-5358"))
        self.assertFalse(self.validador.validar("11 4164-5358"))

        self.validador.gateway.validar.assert_called_once_with(
            "sessao-1", "551141645358"
        )
        self.validador.salvar_cache()
        recarregado = ValidadorWhatsApp(Path(self.pasta.name), MagicMock())
        self.assertEqual({"551141645358": False}, recarregado.cache)

    def test_gateway_indisponivel_retorna_none(self) -> None:
        self.validador.gateway.validar.side_effect = RuntimeError("offline")

        self.assertIsNone(self.validador.validar("11 99999-9999"))
        self.assertIsNone(self.validador.session_id)

    def test_sem_telefone_nao_consulta_gateway(self) -> None:
        self.assertFalse(self.validador.validar(""))
        self.validador.gateway.validar.assert_not_called()

    @patch.dict("os.environ", {"PROSPECTA_RUNNER_ID": "runner-1"})
    @patch("validador_whatsapp.repositorio.listar_sessoes_runner")
    def test_sem_sessao_conectada_fica_indisponivel(
        self, listar: MagicMock
    ) -> None:
        self.validador.session_id = None
        listar.return_value = [{"id": "sessao-2"}]
        self.validador.gateway.conectar.return_value = {"status": "qr_pending"}

        self.assertIsNone(self.validador.validar("11 99999-9999"))


if __name__ == "__main__":
    unittest.main()
