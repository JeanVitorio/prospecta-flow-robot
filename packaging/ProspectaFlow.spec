# -*- mode: python ; coding: utf-8 -*-

import os
import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


ROOT = Path(SPECPATH).parent


def _arquivo_versao() -> str:
    """Preenche os metadados do .exe com a versão do build (LEADFLOW_VERSION)."""
    versao = os.environ.get("LEADFLOW_VERSION", "").strip()
    if not versao:
        texto = (ROOT / "app_version.py").read_text(encoding="utf-8")
        versao = re.search(r'__version__\s*=\s*"([^"]+)"', texto).group(1)
    partes = [int(p) for p in re.findall(r"\d+", versao)[:4]]
    tupla = tuple(partes + [0] * (4 - len(partes)))
    modelo = (ROOT / "packaging" / "version_info.txt").read_text(encoding="utf-8")
    destino = Path(workpath) / "version_info.txt"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        modelo.replace("{VERSAO_TUPLA}", repr(tupla)).replace("{VERSAO}", versao),
        encoding="utf-8",
    )
    return str(destino)
datas = []
binaries = []
hiddenimports = []

for package in (
    "supabase",
    "postgrest",
    "realtime",
    "storage3",
    "gotrue",
    "supafunc",
    "selenium",
    "dotenv",
    "tzdata",
    "webview",
):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

datas.append((str(ROOT / "packaging" / "LeadFlow.ico"), "packaging"))

a = Analysis(
    [str(ROOT / "prospecta_app.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "vitest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ProspectaFlow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "packaging" / "LeadFlow.ico"),
    version=_arquivo_versao(),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ProspectaFlow",
)
