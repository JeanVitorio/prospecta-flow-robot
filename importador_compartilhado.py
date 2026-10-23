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
import bot_storage as local
from execucao_bot import (
    CheckpointExecucao,
    ControleExecucao,
    ParadaSolicitada,
    agora_iso,
    bloquear_energia,
    criar_logger,
    liberar_energia,
)
from validador_whatsapp import ValidadorWhatsApp, normalizar_telefone


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
        self.existentes: set[str] | None = None
        self.estado: dict[str, Any] = {}
        self.checkpoint_adquirido = False
        self.validador = ValidadorWhatsApp(self.pasta, self.log)
        self.descartados: set[str] = set()

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
        self.estado.setdefault("leads_sem_whatsapp", 0)
        self.estado.setdefault("aguardando_whatsapp", False)
        if "falhas_pendentes" not in self.estado:
            self.estado["falhas_pendentes"] = int(
                self.estado["falhas_importacao"]
            )
        self.estado.setdefault("ultimo_erro", "")
        self.estado.setdefault("lote_csv_processado", 0)
        self.estado.setdefault("limite_leads_atingido", False)
        self.estado.setdefault("proxima_verificacao_quota", 0.0)
        # Recalculado a cada lote: o limite pode ter sido aumentado na edição.
        self.estado["limite_agente_atingido"] = False

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
                lote_disponivel = self._lote_csv_disponivel()
                lote_processado = int(
                    self.estado.get("lote_csv_processado") or 0
                )
                falhas_pendentes = int(
                    self.estado.get("falhas_pendentes") or 0
                )
                csv_alterado = mtime != self.estado.get("mtime_csv")
                quota_bloqueada = bool(
                    self.estado.get("limite_leads_atingido")
                )
                verificar_quota = (
                    time.time()
                    >= float(
                        self.estado.get("proxima_verificacao_quota") or 0
                    )
                )
                if mtime is not None and (
                    lote_disponivel > lote_processado
                    or csv_alterado
                    or falhas_pendentes > 0
                ) and (not quota_bloqueada or verificar_quota):
                    self.estado["atividade_atual"] = "Processando novos leads"
                    inseridos, falhas, limite_atingido = self._processar_csv()
                    self.estado["ultima_execucao"] = agora_iso()
                    self.estado["mtime_csv"] = mtime
                    self.estado["falhas_pendentes"] = falhas
                    self.estado["limite_leads_atingido"] = limite_atingido
                    self.estado["proxima_verificacao_quota"] = (
                        time.time() + 300 if limite_atingido else 0.0
                    )
                    if falhas == 0 and not limite_atingido:
                        self.estado["lote_csv_processado"] = lote_disponivel
                    elif limite_atingido:
                        self.estado["atividade_atual"] = (
                            "Limite mensal atingido; faça upgrade para continuar"
                        )
                        self.log.warning(
                            "Importação pausada porque o limite mensal foi atingido."
                        )
                    elif self.estado.get("aguardando_whatsapp"):
                        self.estado["atividade_atual"] = (
                            "Aguardando WhatsApp conectado para validar números"
                        )
                    else:
                        self.estado["atividade_atual"] = (
                            "Falha ao importar leads; nova tentativa agendada"
                        )
                        self.log.warning(
                            "Lote %s mantido como pendente após %s falha(s).",
                            lote_disponivel,
                            falhas,
                        )
                    if self.estado.get("limite_agente_atingido"):
                        self._encerrar_por_limite_agente()
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
                self.checkpoint.salvar_local("degraded")
            self.controle.esperar(10)

    def _processar_csv(
        self, respeitar_controle: bool = True
    ) -> tuple[int, int, bool]:
        if not self.csv_path.exists():
            return 0, 0, False
        existentes = self._carregar_existentes()
        pendentes: list[tuple[dict[str, str], str]] = []
        chaves_pendentes: set[str] = set()
        inseridos = 0
        falhas = 0
        limite_atingido = False
        self.estado["limite_agente_atingido"] = False
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
                if chave in existentes or chave in chaves_pendentes:
                    continue
                pendentes.append((row, chave))
                chaves_pendentes.add(chave)

        pendentes, aguardando = self._filtrar_whatsapp(
            pendentes, respeitar_controle
        )
        falhas += aguardando

        for inicio in range(0, len(pendentes), 100):
            if respeitar_controle:
                self.controle.verificar()
            lote = pendentes[inicio : inicio + 100]
            self.estado.update(
                atividade_atual="Importando lote de leads no Supabase",
                empresa_atual="",
            )
            self.checkpoint.salvar_local(
                "running" if respeitar_controle else "stopping"
            )
            try:
                resultado = self._inserir_lote(
                    [row for row, _chave in lote],
                    [chave for _row, chave in lote],
                )
                chaves_processadas = self._chaves_resultado(
                    resultado.get("processed_leads")
                )
                chaves_inseridas = self._chaves_resultado(
                    resultado.get("inserted_leads")
                )
                for row, chave in lote:
                    if chave in chaves_processadas:
                        existentes.add(chave)
                    if chave in chaves_inseridas:
                        inseridos += 1
                        self.estado.update(
                            ultimo_lead_importado=row["Nome"].strip(),
                            ultimo_lead_importado_em=agora_iso(),
                            leads_importados=(
                                int(self.estado["leads_importados"]) + 1
                            ),
                        )
                limite_agente = bool(resultado.get("bot_limit_reached"))
                if bool(resultado.get("limit_reached")) or limite_agente:
                    limite_atingido = bool(resultado.get("limit_reached"))
                    self.estado["limite_agente_atingido"] = limite_agente
                    # Os não gravados ficam pendentes para quando o limite subir.
                    falhas += len(pendentes) - inicio - len(
                        chaves_processadas
                    )
                    break
            except Exception as erro:
                falhas += len(lote)
                self.estado.update(
                    atividade_atual="Falha ao importar lote de leads",
                    falhas_importacao=(
                        int(self.estado["falhas_importacao"]) + len(lote)
                    ),
                    ultimo_erro=type(erro).__name__,
                )
                self.log.error(
                    "Falha de persistência ao inserir lote de %s lead(s): %s.",
                    len(lote),
                    type(erro).__name__,
                )

        self.estado["ultima_execucao"] = agora_iso()
        if inseridos or falhas:
            self.checkpoint.registrar_evento(
                "lote_leads_processado",
                "Lote de leads processado.",
                {
                    "importados": inseridos,
                    "falhas": falhas,
                    "limite_atingido": limite_atingido,
                    "limite_agente_atingido": bool(
                        self.estado.get("limite_agente_atingido")
                    ),
                },
                "warning" if falhas or limite_atingido else "info",
            )
        return inseridos, falhas, limite_atingido

    def _encerrar_por_limite_agente(self) -> None:
        """Para scraper e importador quando o agente atinge seu limite de leads."""
        limite = self.config.get("limite_leads")
        self.estado["atividade_atual"] = (
            f"Limite de {limite} leads do agente atingido"
            if limite
            else "Limite de leads do agente atingido"
        )
        self.log.info("%s; encerrando o agente.", self.estado["atividade_atual"])
        self.checkpoint.registrar_evento(
            "limite_agente_atingido",
            self.estado["atividade_atual"],
            {"limite_leads": limite},
        )
        try:
            bot_config.definir_comando(self.slug, "parado")
        except Exception as erro:
            self.log.warning(
                "Não foi possível registrar a parada por limite: %s", erro
            )

    def _filtrar_whatsapp(
        self,
        pendentes: list[tuple[dict[str, str], str]],
        respeitar_controle: bool,
    ) -> tuple[list[tuple[dict[str, str], str]], int]:
        """Aplica o filtro de telefone do agente com validação no WhatsApp.

        - "with": só salva leads com WhatsApp validado;
        - "any": salva os sem telefone e, dos com telefone, só os validados;
        - "without": salva sem validar.
        Retorna os aprovados e quantos ficaram aguardando o WhatsApp conectar.
        """
        filtro = self.config.get("filtro_telefone", "any")
        aprovados: list[tuple[dict[str, str], str]] = []
        aguardando = 0
        if pendentes and filtro != "without":
            self.estado["atividade_atual"] = "Validando números no WhatsApp"
        try:
            for posicao, (row, chave) in enumerate(pendentes):
                if respeitar_controle:
                    self.controle.verificar()
                telefone = row.get("Telefone", "")
                sem_telefone = not normalizar_telefone(telefone)
                if filtro == "without" or (filtro == "any" and sem_telefone):
                    aprovados.append((row, chave))
                    continue
                existe = self.validador.validar(telefone)
                if existe is None:
                    aguardando = len(pendentes) - posicao
                    break
                if existe:
                    aprovados.append((row, chave))
                elif chave not in self.descartados:
                    self.descartados.add(chave)
                    self.estado["leads_sem_whatsapp"] = (
                        int(self.estado["leads_sem_whatsapp"]) + 1
                    )
                    self.log.info(
                        "Lead descartado (número sem WhatsApp): %s",
                        row.get("Nome", "").strip(),
                    )
        finally:
            self.validador.salvar_cache()
        self.estado["aguardando_whatsapp"] = aguardando > 0
        if aguardando:
            self.log.warning(
                "%s lead(s) aguardando WhatsApp conectado para validação.",
                aguardando,
            )
        return aprovados, aguardando

    def _carregar_existentes(self) -> set[str]:
        if self.existentes is not None:
            return self.existentes
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
                self.existentes = existentes
                return self.existentes
            inicio += tamanho_pagina

    def _lote_csv_disponivel(self) -> int:
        """Importa somente quando o scraper encerra o processamento da cidade."""
        try:
            checkpoint = local.ler_checkpoint(self.slug, "scraper") or {}
        except (OSError, ValueError):
            return int(self.estado.get("lote_csv_processado") or 0)
        estado_scraper = checkpoint.get("state") or {}
        versao = estado_scraper.get("lote_csv_versao")
        if versao is None:
            versao = len(estado_scraper.get("cidades_concluidas") or [])
        try:
            return int(versao)
        except (TypeError, ValueError):
            return int(self.estado.get("lote_csv_processado") or 0)

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

    def _inserir_lote(
        self,
        rows: list[dict[str, str]],
        chaves: list[str],
    ) -> dict[str, Any]:
        payloads = [self._payload(row) for row in rows]
        if not payloads:
            return {}
        lote_hash = hashlib.sha256(
            f"{self.config['id']}|{'|'.join(chaves)}".encode("utf-8")
        ).hexdigest()
        resposta = self.supabase.rpc(
            "prospecta_insert_leads_with_quota",
            {
                "p_bot_id": self.config["id"],
                "p_leads": payloads,
                "p_batch_key": lote_hash,
            },
        ).execute()
        return dict(resposta.data or {})

    @classmethod
    def _chaves_resultado(cls, itens: Any) -> set[str]:
        if not isinstance(itens, list):
            return set()
        return {
            cls._chave(
                str(item.get("name", "")),
                str(item.get("phone", "")),
            )
            for item in itens
            if isinstance(item, dict) and item.get("name")
        }

    def _payload(self, row: dict[str, str]) -> dict[str, Any]:
        agora = datetime.now(timezone.utc).isoformat()
        payload: dict[str, Any] = {
            "name": row["Nome"].strip(),
            "company": row["Nome"].strip(),
            "phone": row.get("Telefone", "").strip(),
            "city": row.get("Cidade", "").strip() or None,
            "website": row.get("Site", "").strip() or None,
            "instagram": row.get("Instagram", "").strip() or None,
            "source": self.config["nicho"],
            "estimated_value": self.config["ticket_estimado"],
            "niche": self.config["nicho"],
            "first_contact_message": self.config["mensagem_inicial"],
            "owner_id": self.owner_id,
            "google_maps_url": (
                row.get("Link Google Maps", "").strip() or None
            ),
            "created_at": agora,
            "updated_at": agora,
        }
        if self.stage_id:
            payload["stage_id"] = self.stage_id
        return payload

    def _termo_excluido(self, nome: str) -> str | None:
        if not self.config.get("filtro_palavras_excluidas_ativo", True):
            return None
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
