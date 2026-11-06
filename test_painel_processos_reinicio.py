"""Processo que morre ao abrir não pode ser reaberto a cada ciclo."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import painel_processos
from painel_processos import GerenciadorProcessos


class ReinicioProtegidoTest(unittest.TestCase):
    def setUp(self) -> None:
        self.gerenciador = GerenciadorProcessos("executor-teste")
        self.relogio = 1000.0
        self.patch_tempo = patch.object(
            painel_processos.time, "monotonic", lambda: self.relogio
        )
        self.patch_tempo.start()
        self.addCleanup(self.patch_tempo.stop)

    def _morreu_logo(self) -> MagicMock:
        processo = MagicMock()
        processo.poll.return_value = 1
        return processo

    def test_primeira_abertura_e_liberada(self) -> None:
        self.assertTrue(self.gerenciador._pode_abrir("mensagens:teste"))

    def test_espera_cresce_a_cada_queda_rapida(self) -> None:
        chave = "mensagens:teste"
        self.assertTrue(self.gerenciador._pode_abrir(chave))
        esperas = []
        for _ in range(4):
            self.relogio += 5  # caiu 5 segundos depois de abrir
            self.assertFalse(self.gerenciador._pode_abrir(chave))
            inicio = self.relogio
            while not self.gerenciador._pode_abrir(chave):
                self.relogio += 1
                if self.relogio - inicio > 2000:
                    self.fail("nunca liberou nova tentativa")
            esperas.append(self.relogio - inicio)
        self.assertEqual(esperas, [10, 20, 40, 80])

    def test_desiste_depois_de_muitas_quedas(self) -> None:
        chave = "mensagens:teste"
        for _ in range(painel_processos.MAX_REINICIOS_SEGUIDOS):
            self.gerenciador._aberturas[chave] = self.relogio
            self.relogio += 5
            self.gerenciador._pode_abrir(chave)
            self.relogio += painel_processos.ESPERA_MAXIMA_REINICIO
        self.assertFalse(self.gerenciador._pode_abrir(chave))
        self.relogio += 10_000
        self.assertFalse(self.gerenciador._pode_abrir(chave))

    def test_processo_saudavel_zera_a_contagem(self) -> None:
        chave = "mensagens:teste"
        self.assertTrue(self.gerenciador._pode_abrir(chave))
        self.relogio += 5
        self.assertFalse(self.gerenciador._pode_abrir(chave))
        self.assertEqual(self.gerenciador._falhas[chave], 1)
        self.relogio += 10
        self.assertTrue(self.gerenciador._pode_abrir(chave))
        # Desta vez rodou bastante antes de encerrar: começa do zero.
        self.relogio += painel_processos.DURACAO_MINIMA_SAUDAVEL + 1
        self.assertTrue(self.gerenciador._pode_abrir(chave))
        self.assertNotIn(chave, self.gerenciador._falhas)

    def test_nao_reabre_processo_que_continua_vivo(self) -> None:
        vivo = MagicMock()
        vivo.poll.return_value = None
        self.gerenciador._processos["mensagens:teste"] = {"mensagens": vivo}
        with patch.object(self.gerenciador, "_abrir") as abrir:
            self.gerenciador.iniciar_mensagens("teste")
        abrir.assert_not_called()

    def test_reabre_uma_vez_quando_o_processo_morre(self) -> None:
        with patch.object(
            self.gerenciador, "_abrir", return_value=self._morreu_logo()
        ) as abrir:
            self.gerenciador.iniciar_mensagens("teste")
            self.relogio += 5
            self.gerenciador.iniciar_mensagens("teste")
            self.gerenciador.iniciar_mensagens("teste")
        # A segunda e a terceira chamadas caem na espera, sem abrir de novo.
        self.assertEqual(abrir.call_count, 1)


if __name__ == "__main__":
    unittest.main()
