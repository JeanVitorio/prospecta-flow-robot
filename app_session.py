"""Sessão SaaS protegida pelo perfil do usuário no Windows."""

from __future__ import annotations

import ctypes
import base64
import json
import os
import tempfile
from ctypes import wintypes
from typing import Any
from urllib.parse import urlsplit

from app_paths import data_path


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


CRYPTPROTECT_UI_FORBIDDEN = 0x01


def salvar_sessao(dados: dict[str, str]) -> None:
    """Valida e persiste tokens criptografados com DPAPI."""
    obrigatorios = (
        "supabase_url",
        "publishable_key",
        "access_token",
        "refresh_token",
    )
    valores = {
        chave: str(dados.get(chave, "")).strip()
        for chave in obrigatorios
    }
    url = urlsplit(valores["supabase_url"])
    if url.scheme != "https" or not url.netloc:
        raise ValueError("URL do Supabase inválida.")
    if any(not valores[chave] for chave in obrigatorios):
        raise ValueError("A sessão recebida está incompleta.")

    conteudo = json.dumps(
        valores, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    protegido = _proteger(conteudo)
    destino = data_path("session.dat")
    descritor, temporario = tempfile.mkstemp(
        prefix=".session.",
        suffix=".tmp",
        dir=destino.parent,
    )
    try:
        with os.fdopen(descritor, "wb") as arquivo:
            arquivo.write(protegido)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(temporario, destino)
    except Exception:
        try:
            os.unlink(temporario)
        except FileNotFoundError:
            pass
        raise


def carregar_sessao() -> dict[str, str] | None:
    caminho = data_path("session.dat")
    if not caminho.is_file():
        return None
    try:
        dados: Any = json.loads(_desproteger(caminho.read_bytes()))
        if not isinstance(dados, dict):
            return None
        return {
            chave: str(valor)
            for chave, valor in dados.items()
            if isinstance(chave, str) and isinstance(valor, str)
        }
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def remover_sessao() -> None:
    data_path("session.dat").unlink(missing_ok=True)

def usuario_sessao() -> str | None:
    sessao = carregar_sessao()
    token = str(sessao.get("access_token", "")) if sessao else ""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        dados = json.loads(base64.urlsafe_b64decode(payload))
        usuario = dados.get("sub")
        return str(usuario) if usuario else None
    except (IndexError, ValueError, json.JSONDecodeError):
        return None


def _blob(dados: bytes) -> tuple[_DataBlob, Any]:
    buffer = ctypes.create_string_buffer(dados)
    return (
        _DataBlob(
            len(dados),
            ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)),
        ),
        buffer,
    )


def _proteger(dados: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("A proteção da sessão requer Windows.")
    entrada, _buffer = _blob(dados)
    saida = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    if not crypt32.CryptProtectData(
        ctypes.byref(entrada),
        "ProspectaFlow",
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(saida),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(saida.pbData, saida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(saida.pbData)


def _desproteger(dados: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("A proteção da sessão requer Windows.")
    entrada, _buffer = _blob(dados)
    saida = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    if not crypt32.CryptUnprotectData(
        ctypes.byref(entrada),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(saida),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(saida.pbData, saida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(saida.pbData)
