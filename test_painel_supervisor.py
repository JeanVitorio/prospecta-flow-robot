"""Com o painel aberto, o executor precisa ficar sempre de pé."""

from __future__ import annotations

import unittest
from threading import Event
from unittest.mock import patch

import painel_web


class SupervisorRunnerTest(unittest.TestCase):
    def _supervisionar(self, sessao, ativo, voltas: int):
        parar = Event()
        with patch.object(
            painel_web, "carregar_sessao", return_value=sessao
        ), patch.object(
            painel_web, "_runner_ativo", side_effect=ativo
        ), patch.object(
            painel_web, "_garantir_runner"
        ) as iniciar, patch.object(
            parar, "wait", side_effect=[False] * (voltas - 1) + [True]
        ):
            painel_web._supervisionar_runner(parar)
        return iniciar

    def test_inicia_o_executor_quando_ele_nao_esta_rodando(self) -> None:
        iniciar = self._supervisionar({"access_token": "x"}, [False], 1)
        iniciar.assert_called_once()

    def test_nao_duplica_quando_o_executor_ja_esta_rodando(self) -> None:
        iniciar = self._supervisionar({"access_token": "x"}, [True, True], 2)
        iniciar.assert_not_called()

    def test_reinicia_se_o_executor_cair_com_o_painel_aberto(self) -> None:
        iniciar = self._supervisionar({"access_token": "x"}, [True, False], 2)
        iniciar.assert_called_once()

    def test_sem_login_nao_inicia_o_executor(self) -> None:
        iniciar = self._supervisionar(None, [False], 1)
        iniciar.assert_not_called()


if __name__ == "__main__":
    unittest.main()
