"""Testes do limite de leads por agente na importação e na configuração."""

from __future__ import annotations

import csv
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import bot_config
from importador_compartilhado import Importador


def importador(pasta: Path, nomes: list[str]) -> Importador:
    """Monta só o necessário para _processar_csv, sem Supabase."""
    caminho = pasta / "leads.csv"
    with caminho.open("w", newline="", encoding="utf-8") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=["Nome", "Telefone"])
        escritor.writeheader()
        for nome in nomes:
            escritor.writerow({"Nome": nome, "Telefone": ""})
    objeto = Importador.__new__(Importador)
    objeto.slug = "agente-teste"
    objeto.csv_path = caminho
    objeto.config = {
        "filtro_telefone": "without",
        "filtro_palavras_excluidas_ativo": False,
        "limite_leads": 1,
    }
    objeto.estado = {
        "leads_lidos": 0,
        "leads_importados": 0,
        "falhas_importacao": 0,
        "leads_sem_whatsapp": 0,
    }
    objeto.existentes = set()
    objeto.descartados = set()
    objeto.controle = MagicMock()
    objeto.checkpoint = MagicMock()
    objeto.validador = MagicMock()
    objeto.log = logging.getLogger("teste_limite_leads")
    return objeto


class LimiteLeadsImportadorTest(unittest.TestCase):
    def test_limite_do_agente_mantem_os_demais_pendentes(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            alvo = importador(Path(pasta), ["Empresa A", "Empresa B", "Empresa C"])
            gravado = [{"name": "Empresa A", "phone": ""}]
            alvo._inserir_lote = MagicMock(
                return_value={
                    "inserted_leads": gravado,
                    "processed_leads": gravado,
                    "limit_reached": False,
                    "bot_limit_reached": True,
                }
            )
            inseridos, falhas, limite_mensal = alvo._processar_csv(False)
        self.assertEqual(1, inseridos)
        self.assertEqual(2, falhas)
        self.assertFalse(limite_mensal)
        self.assertTrue(alvo.estado["limite_agente_atingido"])

    def test_sem_limite_do_agente_nao_sinaliza(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            alvo = importador(Path(pasta), ["Empresa A"])
            gravado = [{"name": "Empresa A", "phone": ""}]
            alvo._inserir_lote = MagicMock(
                return_value={
                    "inserted_leads": gravado,
                    "processed_leads": gravado,
                }
            )
            inseridos, falhas, _ = alvo._processar_csv(False)
        self.assertEqual((1, 0), (inseridos, falhas))
        self.assertFalse(alvo.estado["limite_agente_atingido"])

    def test_limite_atingido_para_o_agente(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            alvo = importador(Path(pasta), [])
        alvo.estado["atividade_atual"] = ""
        with patch.object(bot_config, "definir_comando") as definir:
            alvo._encerrar_por_limite_agente()
        definir.assert_called_once_with("agente-teste", "parado")
        self.assertIn("1 leads", alvo.estado["atividade_atual"])


class LimiteLeadsConfigTest(unittest.TestCase):
    BASE = {
        "nome": "Agente teste",
        "owner_email": "teste@exemplo.com",
        "termo_busca": "Lojas",
        "nicho": "Varejo",
        "cidades": ["Curitiba"],
        "ticket_estimado": 0,
    }

    def test_sem_limite_por_padrao(self) -> None:
        self.assertIsNone(bot_config.validar_config(dict(self.BASE))["limite_leads"])

    def test_aceita_limite_valido(self) -> None:
        dados = bot_config.validar_config({**self.BASE, "limite_leads": 250})
        self.assertEqual(250, dados["limite_leads"])

    def test_rejeita_limite_invalido(self) -> None:
        for valor in (0, -5, bot_config.LIMITE_LEADS_MAXIMO + 1, "100", True):
            with self.assertRaises(bot_config.ErroValidacao):
                bot_config.validar_config({**self.BASE, "limite_leads": valor})


if __name__ == "__main__":
    unittest.main()
