"""Configuração local segura para a instalação Windows."""

from __future__ import annotations

import json
import os
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.parse import urlsplit

from app_paths import env_path
from dotenv import dotenv_values


def configuracao_disponivel() -> bool:
    values = dotenv_values(env_path())
    return bool(values.get("SUPABASE_URL") and values.get("SUPABASE_SERVICE_KEY"))


def configurar_interativo() -> bool:
    """Solicita as credenciais no primeiro uso sem embuti-las no instalador."""
    destino = env_path()
    atuais = dotenv_values(destino)
    salvo = False

    raiz = tk.Tk()
    raiz.title("Configurar Prospecta Flow")
    raiz.geometry("620x360")
    raiz.resizable(False, False)
    corpo = ttk.Frame(raiz, padding=24)
    corpo.pack(fill="both", expand=True)
    corpo.columnconfigure(1, weight=1)

    campos = (
        ("SUPABASE_URL", "URL do Supabase", False),
        ("SUPABASE_SERVICE_KEY", "Chave service_role", True),
        ("PROSPECTA_RUNNER_NAME", "Nome desta máquina", False),
        ("PROSPECTA_RUNNER_ENV", "Ambiente", False),
    )
    variaveis: dict[str, tk.StringVar] = {}
    padroes = {
        "PROSPECTA_RUNNER_NAME": os.environ.get("COMPUTERNAME", "Servidor"),
        "PROSPECTA_RUNNER_ENV": "local",
    }
    for linha, (chave, rotulo, segredo) in enumerate(campos):
        ttk.Label(corpo, text=rotulo).grid(
            row=linha, column=0, sticky="w", padx=(0, 12), pady=8
        )
        variavel = tk.StringVar(value=atuais.get(chave) or padroes.get(chave, ""))
        variaveis[chave] = variavel
        ttk.Entry(
            corpo,
            textvariable=variavel,
            show="•" if segredo else "",
        ).grid(row=linha, column=1, sticky="ew", pady=8)

    ttk.Label(
        corpo,
        text=(
            "As credenciais ficam somente nesta máquina, fora da pasta do aplicativo."
        ),
        foreground="#4b5563",
    ).grid(row=len(campos), column=0, columnspan=2, sticky="w", pady=(12, 4))

    def salvar() -> None:
        nonlocal salvo
        valores = {
            chave: variavel.get().strip()
            for chave, variavel in variaveis.items()
        }
        partes = urlsplit(valores["SUPABASE_URL"])
        if partes.scheme != "https" or not partes.netloc:
            messagebox.showerror(
                "Configuração inválida", "Informe uma URL HTTPS válida do Supabase."
            )
            return
        if len(valores["SUPABASE_SERVICE_KEY"]) < 20:
            messagebox.showerror(
                "Configuração inválida", "Informe a chave service_role completa."
            )
            return
        _gravar_env(destino, valores)
        salvo = True
        messagebox.showinfo("Prospecta Flow", "Configuração salva com sucesso.")
        raiz.destroy()

    botoes = ttk.Frame(corpo)
    botoes.grid(row=len(campos) + 1, column=0, columnspan=2, sticky="e", pady=(20, 0))
    ttk.Button(botoes, text="Cancelar", command=raiz.destroy).pack(
        side="left", padx=6
    )
    ttk.Button(botoes, text="Salvar", command=salvar).pack(side="left")
    raiz.mainloop()
    return salvo


def _gravar_env(destino: Path, valores: dict[str, str]) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    linhas = [
        f"{chave}={json.dumps(valor, ensure_ascii=False)}"
        for chave, valor in valores.items()
    ]
    descritor, temporario = tempfile.mkstemp(
        prefix=".prospecta.", suffix=".env.tmp", dir=destino.parent
    )
    try:
        with os.fdopen(descritor, "w", encoding="utf-8", newline="\n") as arquivo:
            arquivo.write("\n".join(linhas) + "\n")
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(temporario, destino)
    except Exception:
        try:
            os.unlink(temporario)
        except FileNotFoundError:
            pass
        raise
