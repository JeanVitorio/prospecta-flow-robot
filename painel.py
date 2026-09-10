"""Interface gráfica limpa do Prospecta Flow Robot."""
from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable
import bot_config
import bot_repository
from execucao_bot import bloquear_energia, liberar_energia
from painel_cards import CardBot
from painel_janelas import JanelaBot, JanelaLogs
from painel_processos import GerenciadorProcessos

class PainelProspecta:
    def __init__(self, raiz: tk.Tk) -> None:
        self.raiz = raiz
        self.raiz.title("Prospecta Flow Robot")
        self.raiz.geometry("1120x760")
        self.raiz.minsize(820, 560)
        self._fila: queue.Queue[tuple[Any, ...]] = queue.Queue()
        self._configs: list[dict[str, Any]] = []
        self._cards: dict[str, CardBot] = {}
        self._avisos_conclusao: set[str] = set()
        self._processos = GerenciadorProcessos()
        self._busca_remota_ativa = False
        self._proxima_busca_remota = 0.0
        self._fechando = False
        self._montar()
        bloquear_energia()
        self.raiz.protocol("WM_DELETE_WINDOW", self._fechar)
        self.raiz.after(100, self._processar_fila)
        self.raiz.after(1000, self._tick_local)
        self.atualizar_lista()

    def _montar(self) -> None:
        estilo = ttk.Style()
        estilo.configure("Titulo.TLabel", font=("Segoe UI", 22, "bold"))
        topo = ttk.Frame(self.raiz, padding=(22, 18))
        topo.pack(fill="x")
        ttk.Label(topo, text="Prospecta Flow Robot", style="Titulo.TLabel").pack(
            side="left"
        )
        ttk.Button(topo, text="Novo bot", command=self._novo_bot).pack(
            side="right", padx=(8, 0)
        )
        ttk.Button(topo, text="Atualizar", command=self.atualizar_lista).pack(
            side="right"
        )
        self._mensagem = tk.StringVar(value="Carregando configurações...")
        ttk.Label(
            self.raiz,
            textvariable=self._mensagem,
            padding=(22, 0, 22, 10),
            foreground="#4b5563",
        ).pack(fill="x")
        exterior = ttk.Frame(self.raiz)
        exterior.pack(fill="both", expand=True, padx=20, pady=(0, 18))
        self._canvas = tk.Canvas(exterior, highlightthickness=0)
        rolagem = ttk.Scrollbar(
            exterior, orient="vertical", command=self._canvas.yview
        )
        self._conteudo = ttk.Frame(self._canvas)
        self._janela_canvas = self._canvas.create_window(
            (0, 0), window=self._conteudo, anchor="nw"
        )
        self._canvas.configure(yscrollcommand=rolagem.set)
        self._conteudo.bind(
            "<Configure>",
            lambda _evento: self._canvas.configure(
                scrollregion=self._canvas.bbox("all")
            ),
        )
        self._canvas.bind(
            "<Configure>",
            lambda evento: self._canvas.itemconfigure(
                self._janela_canvas, width=evento.width
            ),
        )
        self._canvas.bind_all(
            "<MouseWheel>",
            lambda evento: self._canvas.yview_scroll(
                int(-evento.delta / 120), "units"
            ),
        )
        self._canvas.pack(side="left", fill="both", expand=True)
        rolagem.pack(side="right", fill="y")

    def atualizar_lista(self) -> None:
        self._mensagem.set("Atualizando configurações...")

        def carregar() -> tuple[list[dict[str, Any]], str, bool]:
            listagem = bot_config.listar_configs()
            fonte = getattr(listagem, "fonte", "supabase")
            fallback = bool(getattr(listagem, "fallback_cache", False))
            configs = []
            for item in listagem:
                config = dict(item)
                config["_persistencia"] = fonte
                config["_fallback_cache"] = fallback
                configs.append(config)
            return configs, fonte, fallback

        self._executar("lista", carregar)

    def _renderizar(self, configs: list[dict[str, Any]], fonte: str, fallback: bool) -> None:
        self._configs = configs
        for filho in self._conteudo.winfo_children():
            filho.destroy()
        self._cards.clear()
        if not configs:
            texto = (
                "Supabase indisponível e cache local vazio. "
                "Verifique a conexão e use Atualizar."
                if fallback
                else "Nenhum bot cadastrado. Use Novo bot para começar."
            )
            ttk.Label(
                self._conteudo,
                text=texto,
                padding=30,
                anchor="center",
                font=("Segoe UI", 12),
            ).pack(fill="x")
        for config in configs:
            card = CardBot(self._conteudo, config, self._acoes_card())
            card.pack(fill="x", pady=(0, 12), padx=2)
            self._cards[config["slug"]] = card
            card.atualizar_estado(self._processos.status(config["slug"]))
        origem = "Supabase" if fonte == "supabase" else "cache local sinalizado"
        self._mensagem.set(f"{len(configs)} bot(s) carregado(s) de {origem}.")
        if configs:
            self._buscar_checkpoints_remotos(configs)

    def _acoes_card(self) -> dict[str, Callable[[dict[str, Any]], None]]:
        return {
            "iniciar": self._iniciar,
            "pausar": lambda config: self._comando(config, "pausado"),
            "continuar": lambda config: self._comando(config, "rodando"),
            "parar": lambda config: self._comando(config, "parado"),
            "editar": self._editar,
            "logs": lambda config: JanelaLogs(self.raiz, config["slug"]),
            "excluir": self._excluir,
        }

    def _novo_bot(self) -> None:
        JanelaBot(self.raiz, self._salvar_bot)

    def _editar(self, config: dict[str, Any]) -> None:
        JanelaBot(self.raiz, self._salvar_bot, config)

    def _salvar_bot(self, janela: JanelaBot, dados: dict[str, Any]) -> None:
        janela.definir_processando(True, "Salvando primeiro no Supabase...")

        def sucesso(_resultado: Any) -> None:
            if janela.winfo_exists():
                janela.destroy()
            messagebox.showinfo("Prospecta Flow Robot", "Bot salvo com sucesso.")
            self.atualizar_lista()

        self._executar(
            "acao",
            lambda: bot_config.salvar_config(dados),
            sucesso,
            lambda erro: janela.mostrar_erro(str(erro)) if janela.winfo_exists() else None,
        )

    def _excluir(self, config: dict[str, Any]) -> None:
        if self._processos.status(config["slug"]) != "Inativo":
            messagebox.showwarning(
                "Bot em execução",
                "Solicite a parada e aguarde os processos terminarem antes de excluir.",
            )
            return
        if not messagebox.askyesno(
            "Excluir bot",
            f"Excluir logicamente o bot “{config['nome']}”?\n"
            "Os arquivos de execução locais não serão apagados.",
        ):
            return
        self._mensagem.set("Excluindo configuração...")
        self._executar(
            "acao",
            lambda: bot_config.excluir_config(config["slug"]),
            lambda _r: self._operacao_concluida("Bot excluído com sucesso."),
        )

    def _iniciar(self, config: dict[str, Any]) -> None:
        self._mensagem.set(f"Iniciando {config['nome']}...")
        card = self._cards.get(config["slug"])
        if card:
            card.definir_iniciando()
        self._executar(
            "acao",
            lambda: self._processos.iniciar(config["slug"]),
            lambda _r: self._operacao_concluida("Scraper e importador iniciados."),
        )

    def _comando(self, config: dict[str, Any], comando: str) -> None:
        mensagens = {
            "pausado": "Pausa solicitada com segurança.",
            "rodando": "Continuação solicitada.",
            "parado": "Parada segura solicitada.",
        }
        self._mensagem.set(f"Enviando comando para {config['nome']}...")
        self._executar(
            "acao",
            lambda: self._processos.definir_comando(config["slug"], comando),
            lambda _r: self._operacao_concluida(mensagens[comando]),
        )

    def _operacao_concluida(self, mensagem: str) -> None:
        self._mensagem.set(mensagem)
        self.atualizar_lista()

    def _buscar_checkpoints_remotos(self, configs: list[dict[str, Any]]) -> None:
        if self._busca_remota_ativa:
            return
        self._busca_remota_ativa = True

        def carregar() -> dict[
            str,
            tuple[
                dict[str, Any] | None,
                dict[str, Any] | None,
                dict[str, Any] | None,
            ],
        ]:
            resultado = {}
            for config in configs:
                if not config.get("id"):
                    continue
                try:
                    runtime = bot_repository.carregar_runtime_bot(config["id"]) or {}
                    checkpoints = runtime.get("checkpoints") or {}
                    resultado[config["slug"]] = (
                        checkpoints.get("scraper"),
                        checkpoints.get("importador"),
                        runtime.get("control"),
                    )
                except bot_repository.ErroPersistencia:
                    resultado[config["slug"]] = (None, None, None)
            return resultado

        def concluir(_resultado: Any) -> None:
            self._busca_remota_ativa = False

        def falhar(_erro: Exception) -> None:
            self._busca_remota_ativa = False

        self._executar("checkpoints", carregar, concluir, falhar)

    def _executar(
        self,
        tipo: str,
        funcao: Callable[[], Any],
        sucesso: Callable[[Any], None] | None = None,
        falha: Callable[[Exception], None] | None = None,
    ) -> None:
        def trabalhador() -> None:
            try:
                self._fila.put((tipo, True, funcao(), sucesso, falha))
            except Exception as erro:
                self._fila.put((tipo, False, erro, sucesso, falha))

        threading.Thread(target=trabalhador, daemon=True).start()

    def _processar_fila(self) -> None:
        if self._fechando:
            return
        try:
            while True:
                tipo, ok, resultado, sucesso, falha = self._fila.get_nowait()
                if not ok:
                    if falha:
                        falha(resultado)
                    else:
                        self._mensagem.set(f"Operação não concluída: {resultado}")
                    continue
                if tipo == "lista":
                    self._renderizar(*resultado)
                elif tipo == "checkpoints":
                    for slug, checkpoints in resultado.items():
                        if slug in self._cards:
                            self._cards[slug].definir_checkpoint_remoto(*checkpoints)
                if sucesso:
                    sucesso(resultado)
        except queue.Empty:
            pass
        self.raiz.after(100, self._processar_fila)

    def _tick_local(self) -> None:
        if self._fechando:
            return
        self._processos.limpar_finalizados()
        for config in self._configs:
            card = self._cards.get(config["slug"])
            if not card:
                continue
            estado = card.atualizar_estado(self._processos.status(config["slug"]))
            slug = config["slug"]
            if estado.get("concluido") and slug not in self._avisos_conclusao:
                self._avisos_conclusao.add(slug)
                if messagebox.askyesno(
                    "Cidades concluídas",
                    f"{config['nome']} concluiu todas as cidades.\n"
                    "Deseja editar as cidades agora?",
                ):
                    self._editar(config)
        agora = time.monotonic()
        if agora >= self._proxima_busca_remota:
            self._proxima_busca_remota = agora + 2
            self._buscar_checkpoints_remotos(self._configs)
        self.raiz.after(1000, self._tick_local)

    def _fechar(self) -> None:
        if self._processos.possui_ativos() and not messagebox.askokcancel(
            "Fechar painel",
            "Existem processos ativos. Eles continuarão em segundo plano.\n"
            "Deseja fechar o painel?",
        ):
            return
        self._fechando = True
        liberar_energia()
        self.raiz.destroy()


def main() -> None:
    raiz = tk.Tk()
    PainelProspecta(raiz)
    raiz.mainloop()

if __name__ == "__main__":
    main()
