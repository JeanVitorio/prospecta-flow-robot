"""Janelas auxiliares de cadastro, edição e logs."""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal, InvalidOperation
from tkinter import messagebox, ttk
from typing import Any, Callable
from uuid import UUID

from painel_processos import caminhos_logs


class JanelaBot(tk.Toplevel):
    """Formulário único para criação e edição de configurações."""

    OPCOES_PRESENCA = {
        "Com ou sem": "any",
        "Somente com": "with",
        "Somente sem": "without",
    }

    CAMPOS = (
        ("nome", "Nome"),
        ("lead_owner_id", "UID lead_owner_id"),
        ("owner_email", "E-mail do responsável"),
        ("termo_busca", "Termo de pesquisa (a cidade será adicionada)"),
        ("nicho", "Nicho / segmento"),
        ("ticket_estimado", "Ticket médio"),
        ("minimo_avaliacoes", "Mínimo de avaliações"),
        ("max_scrolls", "Máximo de rolagens"),
    )

    def __init__(
        self,
        mestre: tk.Misc,
        ao_salvar: Callable[["JanelaBot", dict[str, Any]], None],
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(mestre)
        self.title("Editar bot" if config else "Novo bot")
        self.geometry("720x900")
        self.minsize(620, 760)
        self.transient(mestre)
        self.grab_set()
        self._config = dict(config or {})
        self._ao_salvar = ao_salvar
        self._variaveis: dict[str, tk.StringVar] = {}
        self._headless = tk.BooleanVar(value=self._config.get("headless", True))
        self._filtro_site = tk.StringVar(
            value=self._rotulo_presenca(
                self._config.get("filtro_site", "without")
            )
        )
        self._filtro_telefone = tk.StringVar(
            value=self._rotulo_presenca(
                self._config.get("filtro_telefone", "any")
            )
        )
        self._filtro_avaliacoes = tk.BooleanVar(
            value=self._config.get("filtro_avaliacoes_ativo", True)
        )
        self._filtro_excluidas = tk.BooleanVar(
            value=self._config.get("filtro_palavras_excluidas_ativo", True)
        )
        self._filtro_incluidas = tk.BooleanVar(
            value=self._config.get("filtro_palavras_incluidas_ativo", True)
        )
        self._montar()

    def _montar(self) -> None:
        corpo = ttk.Frame(self, padding=18)
        corpo.pack(fill="both", expand=True)
        corpo.columnconfigure(1, weight=1)
        ttk.Label(
            corpo,
            text="Configuração do bot",
            font=("Segoe UI", 16, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 14))
        for linha, (chave, rotulo) in enumerate(self.CAMPOS, start=1):
            ttk.Label(corpo, text=rotulo).grid(
                row=linha, column=0, sticky="w", padx=(0, 12), pady=4
            )
            valor = self._valor_inicial(chave)
            variavel = tk.StringVar(value=valor)
            self._variaveis[chave] = variavel
            ttk.Entry(corpo, textvariable=variavel).grid(
                row=linha, column=1, sticky="ew", pady=4
            )
        linha = len(self.CAMPOS) + 1
        ttk.Checkbutton(
            corpo, text="Executar navegador em modo headless", variable=self._headless
        ).grid(row=linha, column=1, sticky="w", pady=5)
        for rotulo, variavel in (
            ("Filtro de site", self._filtro_site),
            ("Filtro de telefone", self._filtro_telefone),
        ):
            linha += 1
            ttk.Label(corpo, text=rotulo).grid(
                row=linha, column=0, sticky="w", padx=(0, 12), pady=4
            )
            ttk.Combobox(
                corpo,
                textvariable=variavel,
                values=tuple(self.OPCOES_PRESENCA),
                state="readonly",
            ).grid(row=linha, column=1, sticky="ew", pady=4)
        for texto, variavel in (
            ("Aplicar mínimo de avaliações", self._filtro_avaliacoes),
            ("Aplicar palavras excluídas", self._filtro_excluidas),
            ("Aplicar palavras incluídas", self._filtro_incluidas),
        ):
            linha += 1
            ttk.Checkbutton(corpo, text=texto, variable=variavel).grid(
                row=linha, column=1, sticky="w", pady=3
            )
        self._textos: dict[str, tk.Text] = {}
        for chave, rotulo in (
            ("cidades", "Cidades (uma por linha)"),
            ("palavras_excluidas", "Palavras excluídas (uma por linha)"),
            ("palavras_incluidas", "Palavras incluídas (uma por linha)"),
        ):
            linha += 1
            ttk.Label(corpo, text=rotulo).grid(
                row=linha, column=0, sticky="nw", padx=(0, 12), pady=5
            )
            texto = tk.Text(corpo, height=4, wrap="word", font=("Segoe UI", 10))
            texto.grid(row=linha, column=1, sticky="nsew", pady=5)
            texto.insert("1.0", "\n".join(self._config.get(chave, [])))
            self._textos[chave] = texto
            corpo.rowconfigure(linha, weight=1)
        linha += 1
        self._mensagem = tk.StringVar()
        ttk.Label(corpo, textvariable=self._mensagem, foreground="#a33").grid(
            row=linha, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )
        linha += 1
        botoes = ttk.Frame(corpo)
        botoes.grid(row=linha, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(botoes, text="Cancelar", command=self.destroy).pack(
            side="left", padx=5
        )
        self._botao_salvar = ttk.Button(
            botoes, text="Salvar", command=self._salvar
        )
        self._botao_salvar.pack(side="left", padx=5)

    def _valor_inicial(self, chave: str) -> str:
        padroes = {
            "minimo_avaliacoes": 0,
            "max_scrolls": 10,
            "ticket_estimado": 0,
        }
        valor = self._config.get(chave, padroes.get(chave, ""))
        if chave == "ticket_estimado" and valor not in ("", None):
            return f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return str(valor)

    def _salvar(self) -> None:
        try:
            dados = {
                chave: variavel.get().strip()
                for chave, variavel in self._variaveis.items()
            }
            UUID(dados["lead_owner_id"])
            dados["ticket_estimado"] = _ticket_brasileiro(
                dados["ticket_estimado"]
            )
            dados["minimo_avaliacoes"] = int(dados["minimo_avaliacoes"])
            dados["max_scrolls"] = int(dados["max_scrolls"])
            dados["headless"] = self._headless.get()
            dados["filtro_site"] = self.OPCOES_PRESENCA[
                self._filtro_site.get()
            ]
            dados["filtro_telefone"] = self.OPCOES_PRESENCA[
                self._filtro_telefone.get()
            ]
            dados["filtro_avaliacoes_ativo"] = self._filtro_avaliacoes.get()
            dados["filtro_palavras_excluidas_ativo"] = (
                self._filtro_excluidas.get()
            )
            dados["filtro_palavras_incluidas_ativo"] = (
                self._filtro_incluidas.get()
            )
            for chave, texto in self._textos.items():
                dados[chave] = _linhas(texto.get("1.0", "end"))
            if not dados["cidades"]:
                raise ValueError("Informe ao menos uma cidade.")
            dados["lead_owner_id"] = str(UUID(dados["lead_owner_id"]))
            for chave in ("id", "slug", "versao", "criado_em"):
                if chave in self._config:
                    dados[chave] = self._config[chave]
            self._ao_salvar(self, dados)
        except (ValueError, InvalidOperation):
            self.mostrar_erro(
                "Revise UID, ticket, avaliações, rolagens e cidades informados."
            )

    @classmethod
    def _rotulo_presenca(cls, valor: str) -> str:
        return next(
            (
                rotulo
                for rotulo, filtro in cls.OPCOES_PRESENCA.items()
                if filtro == valor
            ),
            "Com ou sem",
        )

    def definir_processando(self, ativo: bool, mensagem: str = "") -> None:
        self._botao_salvar.configure(state="disabled" if ativo else "normal")
        self._mensagem.set(mensagem)

    def mostrar_erro(self, mensagem: str) -> None:
        self.definir_processando(False, mensagem)


class JanelaLogs(tk.Toplevel):
    """Exibe e atualiza os arquivos de log de um bot."""

    def __init__(self, mestre: tk.Misc, slug: str) -> None:
        super().__init__(mestre)
        self.title(f"Logs - {slug}")
        self.geometry("900x600")
        self._slug = slug
        barra = ttk.Frame(self, padding=8)
        barra.pack(fill="x")
        ttk.Label(barra, text=f"Bot: {slug}", font=("Segoe UI", 11, "bold")).pack(
            side="left"
        )
        ttk.Button(barra, text="Atualizar", command=self._atualizar).pack(side="right")
        self._texto = tk.Text(
            self, wrap="none", state="disabled", bg="#111827", fg="#e5e7eb"
        )
        self._texto.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._atualizar()

    def _atualizar(self) -> None:
        partes = []
        for caminho in caminhos_logs(self._slug):
            if caminho.exists():
                try:
                    conteudo = caminho.read_text(encoding="utf-8", errors="replace")
                    partes.append(f"===== {caminho.name} =====\n{conteudo}")
                except OSError:
                    partes.append(f"===== {caminho.name} indisponível =====")
        exibicao = "\n\n".join(partes) or "Nenhum log disponível para este bot."
        self._texto.configure(state="normal")
        self._texto.delete("1.0", "end")
        self._texto.insert("1.0", exibicao)
        self._texto.see("end")
        self._texto.configure(state="disabled")


def _linhas(valor: str) -> list[str]:
    """Aceita uma entrada por linha ou separada por ponto e vírgula."""
    itens = []
    for parte in valor.replace(";", "\n").splitlines():
        item = parte.strip()
        if item and item.casefold() not in {atual.casefold() for atual in itens}:
            itens.append(item)
    return itens


def _ticket_brasileiro(valor: str) -> float:
    texto = valor.strip().replace("R$", "").replace(" ", "")
    if not texto:
        raise ValueError("Ticket obrigatório.")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif texto.count(".") > 1 or (
        "." in texto and len(texto.rsplit(".", 1)[1]) == 3
    ):
        texto = texto.replace(".", "")
    ticket = Decimal(texto)
    if not ticket.is_finite() or ticket < 0:
        raise ValueError("Ticket inválido.")
    return float(ticket.quantize(Decimal("0.01")))
