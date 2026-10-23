"""Identidade visual LeadFlow nas janelas Tk locais (mesma paleta da web)."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from app_paths import resource_path

LARANJA = "#FF6600"
LARANJA_ESCURO = "#DB3A0F"
FUNDO_ESCURO = "#0A0A0B"
TEXTO_CLARO = "#F4F4F5"
TEXTO_SOBRE_LARANJA = "#050505"
TEXTO_SECUNDARIO = "#66666F"


def aplicar_identidade(raiz: tk.Tk) -> None:
    """Define o ícone do LeadFlow como padrão da janela e de suas filhas."""
    icone = resource_path("packaging", "LeadFlow.ico")
    if not icone.exists():
        return
    try:
        raiz.iconbitmap(default=str(icone))
    except tk.TclError:
        pass


def botao_destaque(
    pai: tk.Misc, texto: str, comando: Callable[[], None]
) -> tk.Button:
    """Botão principal laranja; o tema nativo do ttk ignora cores de fundo."""
    return tk.Button(
        pai,
        text=texto,
        command=comando,
        bg=LARANJA,
        fg=TEXTO_SOBRE_LARANJA,
        activebackground=LARANJA_ESCURO,
        activeforeground=TEXTO_CLARO,
        disabledforeground="#7A3A10",
        relief="flat",
        bd=0,
        cursor="hand2",
        padx=14,
        pady=5,
        font=("Segoe UI Semibold", 10),
    )
