"""Pasta de dados na instalação e migração dos dados antigos do disco C:."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app_paths


class PastaDadosTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.base = Path(self._temp.name)
        self.instalacao = self.base / "D" / "LeadFlow"
        self.instalacao.mkdir(parents=True)
        self.local = self.base / "C" / "AppData" / "Local"
        self.legado = self.local / app_paths.APP_NAME
        app_paths._data_root_cache = None

    def tearDown(self) -> None:
        app_paths._data_root_cache = None
        self._temp.cleanup()

    def _patches(self):
        return (
            mock.patch.object(app_paths, "install_root", return_value=self.instalacao),
            mock.patch.object(app_paths, "is_frozen", return_value=True),
            mock.patch.dict(
                os.environ, {"LOCALAPPDATA": str(self.local), "PROSPECTA_DATA_DIR": ""}
            ),
        )

    def test_usa_pasta_dados_da_instalacao(self) -> None:
        p1, p2, p3 = self._patches()
        with p1, p2, p3:
            self.assertEqual(app_paths.data_root(), self.instalacao / "dados")

    def test_migra_dados_antigos_e_apaga_pasta_do_c(self) -> None:
        (self.legado / "logs").mkdir(parents=True)
        (self.legado / "session.dat").write_bytes(b"sessao")
        (self.legado / "logs" / "app.log").write_text("linha", encoding="utf-8")
        p1, p2, p3 = self._patches()
        with p1, p2, p3:
            raiz = app_paths.data_root()
        self.assertEqual((raiz / "session.dat").read_bytes(), b"sessao")
        self.assertTrue((raiz / "logs" / "app.log").is_file())
        self.assertTrue((raiz / ".migrado").is_file())
        self.assertFalse(self.legado.exists())

    def test_nao_sobrescreve_dados_novos(self) -> None:
        self.legado.mkdir(parents=True)
        (self.legado / "session.dat").write_bytes(b"antiga")
        dados = self.instalacao / "dados"
        dados.mkdir()
        (dados / "session.dat").write_bytes(b"nova")
        p1, p2, p3 = self._patches()
        with p1, p2, p3:
            app_paths.data_root()
        self.assertEqual((dados / "session.dat").read_bytes(), b"nova")

    def test_instalacao_sem_escrita_usa_pasta_antiga(self) -> None:
        p1, p2, p3 = self._patches()
        with p1, p2, p3, mock.patch.object(
            app_paths, "_pasta_dados_instalacao", return_value=None
        ):
            self.assertEqual(app_paths.data_root(), self.legado)


if __name__ == "__main__":
    unittest.main()
