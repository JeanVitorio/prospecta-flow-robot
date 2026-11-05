"""Erro permanente não pode virar milhares de gravações no banco."""

from __future__ import annotations

import csv
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import importador_compartilhado as importador
from importador_compartilhado import Importador


def _csv_com_leads(pasta: Path, total: int) -> Path:
    caminho = pasta / "leads.csv"
    with caminho.open("w", newline="", encoding="utf-8") as arquivo:
        escritor = csv.DictWriter(
            arquivo, fieldnames=["Nome", "Cidade", "Telefone", "Site"]
        )
        escritor.writeheader()
        for indice in range(total):
            escritor.writerow(
                {
                    "Nome": f"Corretora {indice}",
                    "Cidade": "Pato Branco PR",
                    "Telefone": f"(46) 9{indice:04d}-0000",
                    "Site": "",
                }
            )
    return caminho


def _importador(caminho: Path) -> Importador:
    objeto = Importador.__new__(Importador)
    objeto.slug = "agente-teste"
    objeto.csv_path = caminho
    objeto.config = {
        "filtro_palavras_excluidas_ativo": False,
        "limite_leads": None,
    }
    objeto.estado = {
        "leads_lidos": 0,
        "leads_importados": 0,
        "falhas_importacao": 0,
        "ultimo_erro": "",
    }
    objeto.log = logging.getLogger("teste_importador_falha")
    objeto.log.addHandler(logging.NullHandler())
    objeto.log.propagate = False
    objeto.checkpoint = MagicMock()
    objeto.controle = MagicMock()
    objeto.existentes = set()
    objeto.ciclos_com_falha = 0
    return objeto


class FalhaPersistenteTest(unittest.TestCase):
    def test_para_de_enviar_lotes_quando_o_erro_se_repete(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            caminho = _csv_com_leads(Path(pasta), 1000)
            objeto = _importador(caminho)
            objeto._inserir_lote = MagicMock(
                side_effect=RuntimeError("function digest does not exist")
            )
            inseridos, falhas, _limite = objeto._processar_csv()
        # Sem o freio seriam 10 lotes; agora para no terceiro.
        self.assertEqual(
            objeto._inserir_lote.call_count,
            importador.MAX_LOTES_SEGUIDOS_COM_FALHA,
        )
        self.assertEqual(inseridos, 0)
        self.assertEqual(falhas, 1000)

    def test_espera_cresce_a_cada_ciclo_com_falha(self) -> None:
        objeto = _importador(Path("leads.csv"))
        self.assertEqual(objeto._espera_do_ciclo(), importador.INTERVALO_CICLO)
        esperas = []
        for _ in range(12):
            objeto.ciclos_com_falha += 1
            esperas.append(objeto._espera_do_ciclo())
        self.assertEqual(esperas[0], 10)
        self.assertEqual(esperas[1], 20)
        self.assertEqual(esperas[2], 40)
        self.assertEqual(max(esperas), importador.ESPERA_MAXIMA)
        self.assertTrue(all(a <= b for a, b in zip(esperas, esperas[1:])))

    def test_encerra_o_agente_depois_de_varios_ciclos_falhando(self) -> None:
        objeto = _importador(Path("leads.csv"))
        objeto.estado["ultimo_erro"] = "APIError"
        with patch.object(importador.bot_config, "definir_comando") as parar:
            objeto._encerrar_por_falha_persistente()
        parar.assert_called_once_with("agente-teste", "parado")
        objeto.checkpoint.salvar.assert_called_once_with("failed")
        self.assertIn("APIError", objeto.estado["atividade_atual"])
        self.assertIn(
            "salvos no PC", objeto.estado["atividade_atual"]
        )

    def test_sucesso_zera_a_contagem_de_falhas(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            caminho = _csv_com_leads(Path(pasta), 250)
            objeto = _importador(caminho)
            objeto._inserir_lote = MagicMock(
                side_effect=[
                    RuntimeError("instabilidade"),
                    {"inserted_leads": [], "processed_leads": []},
                    {"inserted_leads": [], "processed_leads": []},
                ]
            )
            objeto._processar_csv()
        # Falhou uma vez e seguiu: instabilidade passageira não interrompe.
        self.assertEqual(objeto._inserir_lote.call_count, 3)


if __name__ == "__main__":
    unittest.main()
