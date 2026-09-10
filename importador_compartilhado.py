"""Importador dinâmico e retomável do CSV local para leads no Supabase."""

from __future__ import annotations

import csv
import hashlib
import re
import time
import unicodedata
from datetime import datetime, timezone
from typing import Any

import bot_config
import bot_repository
from execucao_bot import (
    CheckpointExecucao,
    ControleExecucao,
    ParadaSolicitada,
    agora_iso,
    bloquear_energia,
    criar_logger,
    liberar_energia,
)


class Importador:
    def __init__(self, slug: str):
        carregada = bot_config.carregar_config(slug)
        if not carregada:
            raise RuntimeError(f"Configuração '{slug}' não encontrada.")
        self.config = bot_config.validar_config(carregada)
        self.slug = self.config["slug"]
        self.pasta = bot_config.pasta_bot(self.slug)
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.csv_path = self.pasta / "leads.csv"
        self.log = criar_logger(
            f"importador_{self.slug}", self.pasta / "importador.log"
        )
        self.checkpoint = CheckpointExecucao(
            self.config, "importador", self.log
        )
        self.controle = ControleExecucao(self.slug, self.checkpoint, self.log)
        self.supabase: Any | None = None
        self.owner_id = self.config.get("lead_owner_id")
        self.stage_id: str | None = None
        self.estado: dict[str, Any] = {}
        self.checkpoint_adquirido = False

    def executar(self) -> None:
        bot_config.registrar_runtime(self.slug, processo="importador")
        bloquear_energia()
        status_final = "idle"
        importacao_final = False
        try:
            self.estado = self.checkpoint.adquirir()
            self.checkpoint_adquirido = True
            self._inicializar_estado()
            self.checkpoint.iniciar_heartbeat()
            self.estado["atividade_atual"] = "Iniciando importador"
            self.checkpoint.salvar("starting")
            self.checkpoint.registrar_evento(
                "importador_iniciado", "Importador iniciado."
            )
            self.supabase = bot_repository.obter_cliente()
            self._resolver_responsavel()
            self.stage_id = self._buscar_stage()
            self.controle.verificar()
            self.log.info(
                "Monitorando %s para o responsável configurado.",
                self.csv_path.name,
            )
            self._monitorar()
        except ParadaSolicitada:
            status_final = "stopped"
            importacao_final = True
            self.estado["atividade_atual"] = "Executando importação final"
            self.checkpoint.registrar_evento(
                "importador_parando", "Importação final iniciada."
            )
            self.log.info("Parada solicitada; iniciando importação final.")
        except KeyboardInterrupt:
            status_final = "stopped"
            importacao_final = True
            self.log.info("Interrupção local; iniciando importação final.")
        except Exception as erro:
            status_final = "failed"
            self.estado["atividade_atual"] = "Importador interrompido por falha"
            self.estado["ultimo_erro"] = type(erro).__name__
            self.checkpoint.registrar_evento(
                "importador_falhou",
                self.estado["atividade_atual"],
                {"tipo_erro": type(erro).__name__},
                "error",
            )
            raise
        finally:
            if importacao_final and self.supabase and self.owner_id:
                try:
                    self._processar_csv(respeitar_controle=False)
                except Exception:
                    self.log.error(
                        "A importação final falhou; o CSV foi preservado."
                    )
                    status_final = "failed"
            if self.checkpoint_adquirido:
                self.estado["ultima_execucao"] = agora_iso()
                self.estado["atividade_atual"] = (
                    "Importador parado"
                    if status_final == "stopped"
                    else self.estado["atividade_atual"]
                )
                self.checkpoint.liberar(status_final)
                try:
                    bot_config.definir_comando(self.slug, "parado")
                except Exception as erro:
                    self.log.warning(
                        "Não foi possível registrar comando final: %s", erro
                    )
            bot_config.remover_runtime(self.slug, "importador")
            liberar_energia()

    def _inicializar_estado(self) -> None:
        self.estado.setdefault("mtime_csv", None)
        self.estado.setdefault("ultima_execucao", None)
        self.estado.setdefault("status", "starting")
        self.estado.setdefault("atividade_atual", "Preparando importador")
        self.estado.setdefault("empresa_atual", "")
        self.estado.setdefault("ultimo_lead_importado", "")
        self.estado.setdefault("ultimo_lead_importado_em", "")
        self.estado.setdefault("leads_lidos", 0)
        self.estado.setdefault("leads_importados", 0)
        self.estado.setdefault("falhas_importacao", 0)
        self.estado.setdefault("ultimo_erro", "")

    def _monitorar(self) -> None:
        while True:
            self.controle.verificar()
            try:
                self.estado["atividade_atual"] = "Aguardando alterações no CSV"
                mtime = (
                    self.csv_path.stat().st_mtime_ns
                    if self.csv_path.exists()
                    else None
                )
                if mtime != self.estado.get("mtime_csv"):
                    self.estado["atividade_atual"] = "Processando novos leads"
                    inseridos, falhas = self._processar_csv()
                    self.estado["ultima_execucao"] = agora_iso()
                    if not falhas:
                        self.estado["mtime_csv"] = mtime
                    self.checkpoint.salvar("running")
                    if inseridos:
                        self.log.info(
                            "%s novo(s) lead(s) importado(s).", inseridos
                        )
            except ParadaSolicitada:
                raise
            except Exception:
                self.log.error(
                    "Erro temporário no ciclo de importação; haverá nova tentativa."
                )
                self.checkpoint.salvar("degraded")
            self.controle.esperar(10)

    def _processar_csv(
        self, respeitar_controle: bool = True
    ) -> tuple[int, int]:
        if not self.csv_path.exists():
            return 0, 0
        existentes = self._carregar_existentes()
        inseridos = 0
        falhas = 0
        with self.csv_path.open(
            newline="", encoding="utf-8-sig"
        ) as arquivo:
            for row in csv.DictReader(arquivo):
                if respeitar_controle:
                    self.controle.verificar()
                nome = row.get("Nome", "").strip()
                telefone = row.get("Telefone", "").strip()
                if not nome or self._termo_excluido(nome):
                    continue
                self.estado["leads_lidos"] = int(self.estado["leads_lidos"]) + 1
                chave = self._chave(nome, telefone)
                if chave in existentes:
                    continue
                self.estado.update(
                    atividade_atual="Importando lead no Supabase",
                    empresa_atual=nome,
                )
                self.checkpoint.salvar(
                    "running" if respeitar_controle else "stopping"
                )
                try:
                    self._inserir(row)
                    existentes.add(chave)
                    inseridos += 1
                    self.estado.update(
                        atividade_atual="Lead importado com sucesso",
                        ultimo_lead_importado=nome,
                        ultimo_lead_importado_em=agora_iso(),
                        leads_importados=int(self.estado["leads_importados"]) + 1,
                    )
                    self.checkpoint.registrar_evento(
                        "lead_importado",
                        f"Lead importado: {nome}.",
                        {"empresa": nome},
                    )
                    self.log.info("Lead inserido: %s", nome)
                except Exception as erro:
                    falhas += 1
                    self.estado.update(
                        atividade_atual="Falha ao importar lead",
                        falhas_importacao=int(self.estado["falhas_importacao"]) + 1,
                        ultimo_erro=type(erro).__name__,
                    )
                    self.checkpoint.registrar_evento(
                        "lead_importacao_falhou",
                        f"Falha ao importar o lead {nome}.",
                        {"empresa": nome, "tipo_erro": type(erro).__name__},
                        "error",
                    )
                    self.log.error(
                        "Falha de persistência ao inserir o lead '%s'.", nome
                    )
                self.estado["ultima_execucao"] = agora_iso()
                self.checkpoint.salvar(
                    "running" if respeitar_controle else "stopping"
                )
        return inseridos, falhas

    def _carregar_existentes(self) -> set[str]:
        existentes: set[str] = set()
        inicio = 0
        tamanho_pagina = 1000
        while True:
            resposta = (
                self.supabase.table("leads")
                .select("name,phone")
                .eq("source", self.config["nicho"])
                .eq("owner_id", self.owner_id)
                .range(inicio, inicio + tamanho_pagina - 1)
                .execute()
            )
            pagina = resposta.data or []
            existentes.update(
                self._chave(
                    str(item.get("name", "")),
                    str(item.get("phone", "")),
                )
                for item in pagina
            )
            if len(pagina) < tamanho_pagina:
                return existentes
            inicio += tamanho_pagina

    def _resolver_responsavel(self) -> None:
        if self.owner_id:
            return
        resposta = (
            self.supabase.table("profiles")
            .select("id")
            .eq("email", self.config["owner_email"])
            .limit(1)
            .execute()
        )
        if resposta.data:
            self.owner_id = resposta.data[0]["id"]
        if not self.owner_id:
            raise RuntimeError("Responsável configurado não foi encontrado.")

    def _buscar_stage(self) -> str | None:
        resposta = (
            self.supabase.table("lead_stages")
            .select("id")
            .eq("is_won", False)
            .eq("is_lost", False)
            .order("position")
            .limit(1)
            .execute()
        )
        return resposta.data[0]["id"] if resposta.data else None

    def _inserir(self, row: dict[str, str]) -> None:
        agora = datetime.now(timezone.utc).isoformat()
        payload: dict[str, Any] = {
            "name": row["Nome"].strip(),
            "company": row["Nome"].strip(),
            "phone": row.get("Telefone", "").strip(),
            "source": self.config["nicho"],
            "estimated_value": self.config["ticket_estimado"],
            "niche": self.config["nicho"],
            "owner_id": self.owner_id,
            "notes": row.get("Link Google Maps", "").strip(),
            "created_at": agora,
            "updated_at": agora,
        }
        if self.stage_id:
            payload["stage_id"] = self.stage_id
        self.supabase.table("leads").insert(payload).execute()

    def _termo_excluido(self, nome: str) -> str | None:
        nome_normalizado = self._normalizar(nome)
        for palavra in self.config["palavras_excluidas"]:
            termo = self._normalizar(palavra)
            if termo and termo in nome_normalizado:
                self.log.info(
                    "Lead ignorado pelo filtro negativo: %s | termo: %s",
                    nome,
                    termo,
                )
                return termo
        return None

    @staticmethod
    def _normalizar(texto: str) -> str:
        texto = unicodedata.normalize("NFKD", texto.casefold())
        texto = texto.encode("ascii", "ignore").decode("ascii")
        texto = re.sub(r"[^a-z0-9]+", " ", texto)
        return re.sub(r"\s+", " ", texto).strip()

    @classmethod
    def _chave(cls, nome: str, telefone: str) -> str:
        texto = f"{cls._normalizar(nome)}|{telefone.strip()}"
        return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def executar_importador(slug: str) -> None:
    Importador(slug).executar()
