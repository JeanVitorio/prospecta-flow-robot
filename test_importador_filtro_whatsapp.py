"""Testes do filtro de telefone com validação no WhatsApp na importação."""

from __future__ import annotations

import logging
import unittest
from unittest.mock import MagicMock

from importador_compartilhado import Importador

COM_WHATSAPP = "(11) 99999-0001"
SEM_WHATSAPP = "(11) 4164-5358"


def importador(filtro: str, disponivel: bool = True) -> Importador:
    """Monta só o necessário para _filtrar_whatsapp, sem Supabase."""
    objeto = Importador.__new__(Importador)
    objeto.config = {"filtro_telefone": filtro}
    objeto.estado = {"leads_sem_whatsapp": 0, "aguardando_whatsapp": False}
    objeto.descartados = set()
    objeto.controle = MagicMock()
    objeto.log = logging.getLogger("teste_importador")
    objeto.validador = MagicMock()
    objeto.validador.validar.side_effect = lambda telefone: (
        None if not disponivel else telefone == COM_WHATSAPP
    )
    return objeto


def leads(*telefones: str) -> list[tuple[dict[str, str], str]]:
    return [
        ({"Nome": f"Empresa {i}", "Telefone": t}, f"chave-{i}")
        for i, t in enumerate(telefones)
    ]


class FiltroWhatsAppTest(unittest.TestCase):
    def nomes(self, aprovados: list[tuple[dict[str, str], str]]) -> list[str]:
        return [row["Nome"] for row, _chave in aprovados]

    def test_somente_com_telefone_exige_whatsapp_validado(self) -> None:
        alvo = importador("with")
        aprovados, aguardando = alvo._filtrar_whatsapp(
            leads(COM_WHATSAPP, SEM_WHATSAPP, "não encontrado"), False
        )
        self.assertEqual(["Empresa 0"], self.nomes(aprovados))
        self.assertEqual(0, aguardando)
        self.assertEqual(2, alvo.estado["leads_sem_whatsapp"])

    def test_com_ou_sem_mantem_sem_telefone_e_valida_os_demais(self) -> None:
        alvo = importador("any")
        aprovados, _ = alvo._filtrar_whatsapp(
            leads(COM_WHATSAPP, SEM_WHATSAPP, "não encontrado"), False
        )
        self.assertEqual(["Empresa 0", "Empresa 2"], self.nomes(aprovados))

    def test_somente_sem_telefone_nao_valida(self) -> None:
        alvo = importador("without")
        aprovados, _ = alvo._filtrar_whatsapp(leads("não encontrado"), False)
        self.assertEqual(["Empresa 0"], self.nomes(aprovados))
        alvo.validador.validar.assert_not_called()

    def test_whatsapp_desconectado_segura_os_leads(self) -> None:
        alvo = importador("with", disponivel=False)
        aprovados, aguardando = alvo._filtrar_whatsapp(
            leads(COM_WHATSAPP, SEM_WHATSAPP), False
        )
        self.assertEqual([], aprovados)
        self.assertEqual(2, aguardando)
        self.assertTrue(alvo.estado["aguardando_whatsapp"])


if __name__ == "__main__":
    unittest.main()
