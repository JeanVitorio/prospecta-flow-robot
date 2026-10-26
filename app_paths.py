"""Caminhos compatíveis com execução por código-fonte e aplicativo Windows."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path


APP_NAME = "ProspectaFlow"
SOURCE_ROOT = Path(__file__).resolve().parent
# Pasta de dados dentro da instalação: fica no disco escolhido no instalador.
INSTALL_DATA_DIR = "dados"
_MARCADOR_MIGRACAO = ".migrado"
_data_root_cache: Path | None = None


def is_frozen() -> bool:
    """Indica execução por binário gerado pelo PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def install_root() -> Path:
    """Retorna a pasta do executável ou do código-fonte."""
    return Path(sys.executable).resolve().parent if is_frozen() else SOURCE_ROOT


def resource_path(*parts: str) -> Path:
    """Localiza recursos externos distribuídos junto ao aplicativo."""
    relative = Path(*parts)
    beside_executable = install_root() / relative
    if beside_executable.exists():
        return beside_executable
    bundle_root = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT))
    return bundle_root / relative


def data_root() -> Path:
    """Retorna a pasta persistente que não é substituída em atualizações."""
    global _data_root_cache
    if _data_root_cache is not None:
        return _data_root_cache
    configured = os.getenv("PROSPECTA_DATA_DIR", "").strip()
    if configured:
        root = Path(configured).expanduser().resolve()
    elif is_frozen():
        root = _pasta_dados_instalacao() or _pasta_dados_legada()
    else:
        root = SOURCE_ROOT
    root.mkdir(parents=True, exist_ok=True)
    _data_root_cache = root
    return root


def _pasta_dados_legada() -> Path:
    base = os.getenv("LOCALAPPDATA") or os.getenv("PROGRAMDATA")
    return Path(base or install_root()) / APP_NAME


def _pasta_dados_instalacao() -> Path | None:
    """Usa a pasta da instalação quando ela aceita escrita do usuário."""
    root = install_root() / INSTALL_DATA_DIR
    try:
        root.mkdir(parents=True, exist_ok=True)
        teste = root / f".escrita-{os.getpid()}"
        teste.write_bytes(b"")
        teste.unlink()
    except OSError:
        return None
    _migrar_dados_legados(root)
    return root


def _migrar_dados_legados(destino: Path) -> None:
    """Traz uma única vez os dados da versão antiga (LOCALAPPDATA) e libera o disco C:."""
    marcador = destino / _MARCADOR_MIGRACAO
    origem = _pasta_dados_legada()
    if marcador.exists():
        return
    if not origem.is_dir() or origem.resolve() == destino.resolve():
        marcador.touch()
        return
    trava = destino / ".migrando"
    try:
        descritor = os.open(trava, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            if time.time() - trava.stat().st_mtime > 600:
                # Trava esquecida por uma migração interrompida; a próxima abertura refaz.
                trava.unlink(missing_ok=True)
                return
        except OSError:
            return
        # Outro processo do app está migrando: aguarda para não ler dados pela metade.
        limite = time.monotonic() + 120
        while not marcador.exists() and time.monotonic() < limite:
            time.sleep(1)
        return
    os.close(descritor)
    try:
        for item in origem.iterdir():
            alvo = destino / item.name
            if alvo.exists():
                continue
            try:
                shutil.move(str(item), str(alvo))
            except OSError:
                # Arquivo em uso ou sem espaço: fica na pasta antiga e é recriado se preciso.
                continue
        shutil.rmtree(origem, ignore_errors=True)
        marcador.touch()
    finally:
        trava.unlink(missing_ok=True)


def data_path(*parts: str) -> Path:
    path = data_root().joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def env_path() -> Path:
    configured = os.getenv("PROSPECTA_ENV_FILE", "").strip()
    return Path(configured).expanduser().resolve() if configured else data_path(".env")


def configure_temp_dir() -> None:
    """Direciona os temporários (Chrome, downloads) para o disco da instalação."""
    if not is_frozen() or os.getenv("PROSPECTA_DATA_DIR", "").strip():
        return
    if data_root() != install_root() / INSTALL_DATA_DIR:
        return
    temporarios = data_path("tmp", ".keep").parent
    for variavel in ("TEMP", "TMP"):
        os.environ[variavel] = str(temporarios)
    tempfile.tempdir = None


def configure_bundled_runtime() -> None:
    """Expõe Node, Chrome e driver incluídos sem exigir instalação global."""
    bundled = {
        "PROSPECTA_NODE_BIN": resource_path("runtime", "node", "node.exe"),
        "CHROME_BIN": resource_path("runtime", "chrome", "chrome.exe"),
        "CHROMEDRIVER_BIN": resource_path(
            "runtime", "chromedriver", "chromedriver.exe"
        ),
    }
    for variable, path in bundled.items():
        if path.exists() and not os.getenv(variable):
            os.environ[variable] = str(path)
