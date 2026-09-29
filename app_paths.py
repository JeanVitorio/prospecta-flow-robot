"""Caminhos compatíveis com execução por código-fonte e aplicativo Windows."""

from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "ProspectaFlow"
SOURCE_ROOT = Path(__file__).resolve().parent


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
    configured = os.getenv("PROSPECTA_DATA_DIR", "").strip()
    if configured:
        root = Path(configured).expanduser().resolve()
    elif is_frozen():
        base = os.getenv("LOCALAPPDATA") or os.getenv("PROGRAMDATA")
        root = Path(base or install_root()) / APP_NAME
    else:
        root = SOURCE_ROOT
    root.mkdir(parents=True, exist_ok=True)
    return root


def data_path(*parts: str) -> Path:
    path = data_root().joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def env_path() -> Path:
    configured = os.getenv("PROSPECTA_ENV_FILE", "").strip()
    return Path(configured).expanduser().resolve() if configured else data_path(".env")


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
