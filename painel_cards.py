"""Cards visuais e leitura local de estado dos bots."""

from __future__ import annotations

import tkinter as tk
from datetime import datetime, timezone
from tkinter import ttk
from typing import Any, Callable

import bot_storage


AcaoCard = Callable[[dict[str, Any]], None]


class CardBot(ttk.Frame):
    """Apresenta configuração, progresso e ações de um bot."""

    def __init__(
        self,
        mestre: tk.Misc,
        config: dict[str, Any],
        acoes: dict[str, AcaoCard],
    ) -> None:
        super().__init__(mestre, padding=15, relief="solid", borderwidth=1)
        self.config = config
        self._acoes = acoes
        self._remoto: dict[str, Any] | None = None
        self._remoto_importador: dict[str, Any] | None = None
        self._remoto_controle: dict[str, Any] | None = None
        self.columnconfigure(0, weight=1)
        self._titulo = ttk.Label(
            self, text=config["nome"], font=("Segoe UI", 14, "bold")
        )
        self._titulo.grid(row=0, column=0, sticky="w")
        origem = "Supabase" if config.get("_persistencia") == "supabase" else "Cache local"
        ttk.Label(self, text=f"Origem: {origem}", foreground="#4b5563").grid(
            row=0, column=1, sticky="e"
        )
        ticket = _moeda(config.get("ticket_estimado", 0))
        cidades = ", ".join(config.get("cidades", [])) or "Nenhuma"
        resumo = (
            f"Nicho: {config.get('nicho', '—')}   |   Ticket: {ticket}\n"
            f"Cidades: {cidades}"
        )
        ttk.Label(self, text=resumo, wraplength=900, justify="left").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(8, 6)
        )
        self._estado = tk.StringVar(value="Status: carregando estado local...")
        ttk.Label(self, textvariable=self._estado, justify="left").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(2, 10)
        )
        botoes = ttk.Frame(self)
        botoes.grid(row=3, column=0, columnspan=2, sticky="w")
        self._botoes: dict[str, ttk.Button] = {}
        for texto, acao in (
            ("Iniciar", "iniciar"),
            ("Pausar", "pausar"),
            ("Continuar", "continuar"),
            ("Parar", "parar"),
            ("Editar", "editar"),
            ("Logs", "logs"),
            ("Excluir", "excluir"),
        ):
            botao = ttk.Button(
                botoes,
                text=texto,
                command=lambda nome=acao: self._acoes[nome](self.config),
            )
            botao.pack(side="left", padx=(0, 6))
            self._botoes[acao] = botao

    def definir_checkpoint_remoto(
        self,
        checkpoint: dict[str, Any] | None,
        importador: dict[str, Any] | None = None,
        controle: dict[str, Any] | None = None,
    ) -> None:
        self._remoto = checkpoint
        self._remoto_importador = importador
        self._remoto_controle = controle

    def definir_iniciando(self) -> None:
        """Mostra imediatamente que a solicitação de início está em andamento."""
        self._estado.set("Status: Iniciando\nAtividade atual: preparando processos...")
        self._atualizar_botoes(True, "rodando")

    def atualizar_estado(self, status_sessao: str) -> dict[str, Any]:
        """Atualiza pelo disco e retorna o estado útil para avisos."""
        try:
            local = bot_storage.ler_checkpoint(self.config["slug"], "scraper")
        except (OSError, ValueError):
            local = None
        try:
            controle = bot_storage.ler_controle(self.config["slug"]) or {}
        except (OSError, ValueError):
            controle = {}
        checkpoint = _mais_recente(local, self._remoto)
        estado = checkpoint.get("state", {}) if checkpoint else {}
        status_checkpoint = checkpoint.get("status", "sem checkpoint") if checkpoint else "sem checkpoint"
        comando = str(
            (self._remoto_controle or {}).get("command")
            or controle.get("comando", "")
        ).casefold()
        ativo_remoto = _lease_ativo(checkpoint)
        ativo = status_sessao != "Inativo" or ativo_remoto
        status = _status_exibicao(ativo, status_sessao, str(status_checkpoint), comando)
        cidade_atual = estado.get("cidade_atual") or "—"
        ultima_cidade = estado.get("ultima_cidade") or "—"
        ultimo_lead = (
            estado.get("ultimo_lead_incluido")
            or estado.get("ultimo_lead_salvo")
            or "—"
        )
        atividade = estado.get("atividade_atual") or "Aguardando início"
        empresa_atual = estado.get("empresa_atual") or "—"
        item_atual = int(estado.get("item_atual") or 0)
        total_itens = int(estado.get("total_itens") or 0)
        indice_cidade = int(estado.get("indice_cidade") or 0)
        total_cidades = int(estado.get("total_cidades") or 0)
        ultima_empresa = estado.get("ultima_empresa_verificada") or "—"
        resultado = estado.get("ultimo_resultado_verificacao") or "—"
        executor = estado.get("executor") or {}
        executor_nome = executor.get("id") or "—"
        estado_importador = (
            self._remoto_importador.get("state", {})
            if self._remoto_importador
            else {}
        )
        status_importador = (
            self._remoto_importador.get("status", "inativo")
            if self._remoto_importador
            else "inativo"
        )
        atividade_importador = (
            estado_importador.get("atividade_atual") or "Aguardando"
        )
        ultimo_importado = (
            estado_importador.get("ultimo_lead_importado") or "—"
        )
        progresso = (
            f" ({item_atual} de {total_itens})"
            if item_atual and total_itens
            else ""
        )
        progresso_cidade = (
            f" ({indice_cidade} de {total_cidades})"
            if indice_cidade and total_cidades
            else ""
        )
        origem_estado = "remoto" if checkpoint is self._remoto else "local"
        if not checkpoint:
            origem_estado = "indisponível"
        elif checkpoint is local and not checkpoint.get("sincronizado", False):
            origem_estado = "local — sincronização pendente"
        self._estado.set(
            f"Status: {status}   |   Checkpoint: {origem_estado}\n"
            f"Executor: {executor_nome}   |   Cidade atual: "
            f"{cidade_atual}{progresso_cidade}   |   Última: {ultima_cidade}\n"
            f"Atividade atual: {atividade}\n"
            f"Empresa sendo verificada: {empresa_atual}{progresso}\n"
            f"Última verificada: {ultima_empresa}   |   Resultado: {resultado}\n"
            f"Último lead salvo: {ultimo_lead}\n"
            f"Importador: {status_importador} — {atividade_importador}   |   "
            f"Último importado: {ultimo_importado}"
        )
        self._atualizar_botoes(ativo, comando)
        return estado

    def _atualizar_botoes(self, ativo: bool, comando: str) -> None:
        pausado = ativo and comando == "pausado"
        parando = ativo and comando == "parado"
        estados = {
            "iniciar": not ativo,
            "pausar": ativo and not pausado and not parando,
            "continuar": pausado,
            "parar": ativo and not parando,
            "editar": not ativo,
            "logs": True,
            "excluir": not ativo,
        }
        for acao, habilitado in estados.items():
            self._botoes[acao].configure(
                state="normal" if habilitado else "disabled"
            )


def _mais_recente(
    local: dict[str, Any] | None,
    remoto: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not local:
        return remoto
    if not remoto:
        return local
    marca_local = str(local.get("atualizado_em", ""))
    marca_remota = str(remoto.get("updated_at", ""))
    return local if marca_local >= marca_remota else remoto


def _status_exibicao(
    ativo: bool,
    status_sessao: str,
    status_checkpoint: str,
    comando: str,
) -> str:
    if ativo:
        if comando == "pausado":
            return "Pausado"
        if comando == "parado":
            return "Parando"
        if status_checkpoint == "failed":
            return "Finalizando após falha"
        if status_checkpoint == "stopped":
            return "Finalizando parada"
        if status_checkpoint == "completed":
            return "Finalizando execução concluída"
        if status_checkpoint == "starting":
            return "Iniciando"
        if status_sessao != "Inativo":
            return status_sessao
        return {
            "running": "Executando remotamente",
            "degraded": "Executando com falhas",
            "paused": "Pausado",
        }.get(status_checkpoint, "Executando remotamente")
    return {
        "completed": "Concluído",
        "failed": "Falhou",
        "stopped": "Parado",
        "paused": "Pausado",
        "idle": "Inativo",
        "starting": "Executor offline durante a inicialização",
        "running": "Executor offline / lease expirado",
        "degraded": "Executor offline após falha",
    }.get(status_checkpoint, "Inativo")


def _lease_ativo(checkpoint: dict[str, Any] | None) -> bool:
    if not checkpoint or not checkpoint.get("runner_id"):
        return False
    if checkpoint.get("status") not in {"starting", "running", "paused", "degraded"}:
        return False
    try:
        expira = datetime.fromisoformat(
            str(checkpoint.get("lease_expires_at", "")).replace("Z", "+00:00")
        )
        return expira >= datetime.now(timezone.utc)
    except ValueError:
        return False


def _moeda(valor: Any) -> str:
    try:
        formatado = f"{float(valor):,.2f}"
    except (TypeError, ValueError):
        return "R$ 0,00"
    return "R$ " + formatado.replace(",", "X").replace(".", ",").replace("X", ".")
