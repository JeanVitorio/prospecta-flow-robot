"""Motor dinâmico e retomável de prospecção no Google Maps."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from selenium.common.exceptions import WebDriverException
from urllib3.exceptions import HTTPError as Urllib3HTTPError

import bot_config
from execucao_bot import (
    CheckpointExecucao,
    ControleExecucao,
    ParadaSolicitada,
    agora_iso,
    bloquear_energia,
    criar_logger,
    liberar_energia,
)
from scraper_driver import FalhaPagina, NavegadorMaps
from scraper_extracao import ExtratorMaps, normalizar_url_maps


CAMPOS_CSV = (
    "Nome",
    "Cidade",
    "Telefone",
    "Avaliações",
    "Link Google Maps",
)


class ScraperMaps:
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
            f"scraper_{self.slug}", self.pasta / "scraper.log"
        )
        self.checkpoint = CheckpointExecucao(
            self.config, "scraper", self.log
        )
        self.controle = ControleExecucao(self.slug, self.checkpoint, self.log)
        self.navegador = NavegadorMaps(
            self.config,
            self.controle,
            self.log,
            self.pasta / "screenshots",
        )
        self.extrator = ExtratorMaps(self.config, self.navegador, self.log)
        self.estado: dict[str, Any] = {}
        self.checkpoint_adquirido = False
        self.urls_existentes = self._carregar_urls_existentes()

    def executar(self) -> None:
        bot_config.registrar_runtime(self.slug, processo="scraper")
        bloquear_energia()
        status_final = "idle"
        try:
            self.estado = self.checkpoint.adquirir()
            self.checkpoint_adquirido = True
            self._inicializar_estado()
            self.checkpoint.iniciar_heartbeat()
            self.estado["atividade_atual"] = "Iniciando navegador"
            self.checkpoint.salvar("starting")
            self.checkpoint.registrar_evento(
                "execucao_iniciada", "Execução do scraper iniciada."
            )
            self.controle.verificar()
            self.navegador.criar()
            self._processar_cidades()
            self.estado["concluido"] = not self.estado["cidades_com_falha"]
            self.estado["atividade_atual"] = (
                "Todas as cidades foram concluídas"
                if self.estado["concluido"]
                else "Execução concluída com cidades pendentes"
            )
            self.estado.update(empresa_atual="", item_atual=0, total_itens=0)
            self.checkpoint.salvar("completed")
            self.checkpoint.registrar_evento(
                "execucao_concluida",
                self.estado["atividade_atual"],
                {
                    "empresas_verificadas": self.estado["empresas_verificadas"],
                    "leads_incluidos": self.estado["leads_incluidos"],
                },
            )
            status_final = "completed"
            if self.estado["cidades_com_falha"]:
                self.log.warning(
                    "Execução terminou com cidades pendentes: %s",
                    ", ".join(self.estado["cidades_com_falha"]),
                )
            else:
                self.log.info("Todas as cidades foram concluídas.")
        except ParadaSolicitada:
            status_final = "stopped"
            self.estado["atividade_atual"] = "Execução parada com segurança"
            self.checkpoint.registrar_evento(
                "execucao_parada", self.estado["atividade_atual"]
            )
            self.log.info("Parada segura concluída; checkpoint preservado.")
        except Exception as erro:
            status_final = "failed"
            self.estado["atividade_atual"] = "Execução interrompida por falha"
            self.estado["ultimo_erro"] = type(erro).__name__
            self.checkpoint.registrar_evento(
                "execucao_falhou",
                self.estado["atividade_atual"],
                {"tipo_erro": type(erro).__name__},
                "error",
            )
            raise
        finally:
            if self.checkpoint_adquirido:
                self.checkpoint.liberar(status_final)
            self.navegador.fechar()
            if self.checkpoint_adquirido:
                try:
                    bot_config.definir_comando(self.slug, "parado")
                except Exception as erro:
                    self.log.warning(
                        "Não foi possível registrar comando final: %s", erro
                    )
            bot_config.remover_runtime(self.slug, "scraper")
            liberar_energia()

    def _inicializar_estado(self) -> None:
        padrao = {
            "cidade_atual": "",
            "ultima_cidade": "",
            "ultimo_lead_salvo": "",
            "ultimo_lead_cidade": "",
            "atividade_atual": "Preparando execução",
            "empresa_atual": "",
            "item_atual": 0,
            "total_itens": 0,
            "indice_cidade": 0,
            "total_cidades": len(self.config["cidades"]),
            "ultima_cidade_concluida": "",
            "ultima_empresa_verificada": "",
            "ultimo_resultado_verificacao": "",
            "ultima_verificacao_em": "",
            "empresas_coletadas": 0,
            "empresas_verificadas": 0,
            "leads_incluidos": 0,
            "empresas_descartadas": 0,
            "empresas_com_falha": 0,
            "ultimo_lead_incluido": "",
            "ultimo_lead_incluido_cidade": "",
            "ultimo_lead_incluido_em": "",
            "ultimo_erro": "",
            "itens": [],
            "proximo_item": 0,
            "cidades_concluidas": [],
            "cidades_com_falha": [],
            "concluido": False,
        }
        for chave, valor in padrao.items():
            self.estado.setdefault(chave, valor)

    def _processar_cidades(self) -> None:
        novo_csv = (
            not self.csv_path.exists() or self.csv_path.stat().st_size == 0
        )
        with self.csv_path.open(
            "a", newline="", encoding="utf-8-sig"
        ) as arquivo:
            writer = csv.DictWriter(arquivo, fieldnames=CAMPOS_CSV)
            if novo_csv:
                writer.writeheader()
                arquivo.flush()
            concluidas = set(self.estado["cidades_concluidas"])
            total_cidades = len(self.config["cidades"])
            for indice_cidade, cidade in enumerate(
                self.config["cidades"], start=1
            ):
                if cidade in concluidas:
                    continue
                self.controle.verificar()
                self.estado.update(
                    cidade_atual=cidade,
                    ultima_cidade=cidade,
                    indice_cidade=indice_cidade,
                    total_cidades=total_cidades,
                    atividade_atual=f"Pesquisando estabelecimentos em {cidade}",
                    empresa_atual="",
                    item_atual=0,
                    total_itens=0,
                )
                self.checkpoint.salvar("running")
                self.checkpoint.registrar_evento(
                    "cidade_iniciada",
                    f"Pesquisa iniciada em {cidade}.",
                    {
                        "cidade": cidade,
                        "indice": indice_cidade,
                        "total": total_cidades,
                    },
                )
                self.log.info("Pesquisando cidade: %s", cidade)
                sucesso = self._executar_cidade(cidade, writer, arquivo)
                if sucesso:
                    concluidas.add(cidade)
                    self.estado["cidades_concluidas"] = [
                        item
                        for item in self.config["cidades"]
                        if item in concluidas
                    ]
                    if cidade in self.estado["cidades_com_falha"]:
                        self.estado["cidades_com_falha"].remove(cidade)
                    self.estado["ultima_cidade_concluida"] = cidade
                    self.checkpoint.registrar_evento(
                        "cidade_concluida",
                        f"Pesquisa concluída em {cidade}.",
                        {"cidade": cidade},
                    )
                elif cidade not in self.estado["cidades_com_falha"]:
                    self.estado["cidades_com_falha"].append(cidade)
                    self.checkpoint.registrar_evento(
                        "cidade_falhou",
                        f"Pesquisa não concluída em {cidade}.",
                        {"cidade": cidade},
                        "warning",
                    )
                self.estado.update(
                    cidade_atual="",
                    atividade_atual=f"Pesquisa em {cidade} finalizada",
                    empresa_atual="",
                    item_atual=0,
                    total_itens=0,
                    itens=[],
                    proximo_item=0,
                )
                self.checkpoint.salvar("running")

    def _executar_cidade(
        self,
        cidade: str,
        writer: csv.DictWriter,
        arquivo: Any,
    ) -> bool:
        if self.estado.get("cidade_atual") != cidade:
            self.estado.update(cidade_atual=cidade, itens=[], proximo_item=0)
        if not self.estado.get("itens"):
            if not self._coletar_com_recuperacao(cidade):
                return False
        itens = self.estado["itens"]
        self.estado["total_itens"] = len(itens)
        inicio = int(self.estado.get("proximo_item", 0))
        for indice in range(inicio, len(itens)):
            self.controle.verificar()
            item = itens[indice]
            nome_item = item.get("nome") or "Nome não identificado"
            if nome_item == "Nome não identificado":
                nome_item = self.navegador._nome_pela_url(item.get("url", ""))
            self.estado.update(
                atividade_atual="Abrindo e verificando empresa",
                empresa_atual=nome_item,
                item_atual=indice + 1,
                total_itens=len(itens),
            )
            self.checkpoint.salvar("running")
            try:
                url_item = normalizar_url_maps(item["url"])
                if url_item not in self.urls_existentes:
                    linha = self.extrator.extrair(item, cidade)
                    if linha:
                        url_final = normalizar_url_maps(
                            str(linha["Link Google Maps"])
                        )
                        if url_final not in self.urls_existentes:
                            writer.writerow(linha)
                            arquivo.flush()
                            self.urls_existentes.update(
                                {url_item, url_final}
                            )
                            self.estado.update(
                                ultimo_lead_salvo=linha["Nome"],
                                ultimo_lead_cidade=cidade,
                                ultimo_lead_incluido=linha["Nome"],
                                ultimo_lead_incluido_cidade=cidade,
                                ultimo_lead_incluido_em=agora_iso(),
                                leads_incluidos=int(
                                    self.estado["leads_incluidos"]
                                )
                                + 1,
                                atividade_atual="Lead aprovado e salvo",
                            )
                            self.checkpoint.registrar_evento(
                                "lead_incluido",
                                f"Lead incluído: {linha['Nome']}.",
                                {"empresa": linha["Nome"], "cidade": cidade},
                            )
                        else:
                            self.estado["atividade_atual"] = "Lead já salvo anteriormente"
                            self.estado["empresas_descartadas"] += 1
                    else:
                        self.estado["atividade_atual"] = "Empresa descartada pelos filtros"
                        self.estado["empresas_descartadas"] += 1
                else:
                    self.estado["atividade_atual"] = "Empresa já processada"
                    self.estado["empresas_descartadas"] += 1
            except (FalhaPagina, WebDriverException, Urllib3HTTPError) as erro:
                self.estado["atividade_atual"] = "Falha ao verificar empresa"
                self.estado["empresas_com_falha"] += 1
                self.estado["ultimo_erro"] = type(erro).__name__
                self.log.error(
                    "Item %s ignorado após recuperação automática: %s",
                    indice + 1,
                    erro,
                )
                self.navegador.screenshot(f"item_{cidade}_{indice + 1}")
            self.estado.update(
                empresas_verificadas=int(self.estado["empresas_verificadas"]) + 1,
                ultima_empresa_verificada=nome_item,
                ultimo_resultado_verificacao=self.estado["atividade_atual"],
                ultima_verificacao_em=agora_iso(),
            )
            self.estado["proximo_item"] = indice + 1
            self.checkpoint.salvar("running")
        return True

    def _coletar_com_recuperacao(self, cidade: str) -> bool:
        for tentativa in range(3):
            try:
                self.estado.update(
                    atividade_atual=(
                        f"Coletando empresas em {cidade} "
                        f"(tentativa {tentativa + 1} de 3)"
                    ),
                    empresa_atual="",
                    item_atual=0,
                    total_itens=0,
                )
                self.checkpoint.salvar("running")
                itens = self.navegador.coletar_itens(cidade)
                self.estado.update(
                    cidade_atual=cidade,
                    atividade_atual=f"{len(itens)} empresa(s) encontrada(s)",
                    itens=itens,
                    proximo_item=0,
                    total_itens=len(itens),
                    empresas_coletadas=int(self.estado["empresas_coletadas"])
                    + len(itens),
                )
                self.checkpoint.salvar("running")
                return True
            except (FalhaPagina, WebDriverException, Urllib3HTTPError) as erro:
                self.log.warning(
                    "Falha ao pesquisar %s (%s/3): %s",
                    cidade,
                    tentativa + 1,
                    erro,
                )
                self.navegador.screenshot(f"cidade_{cidade}")
                if tentativa == 0 and self.navegador.driver:
                    try:
                        self.navegador.driver.refresh()
                    except WebDriverException:
                        self.navegador.criar()
                elif tentativa == 1:
                    self.navegador.criar()
        return False

    def _carregar_urls_existentes(self) -> set[str]:
        if not self.csv_path.exists():
            return set()
        try:
            with self.csv_path.open(
                newline="", encoding="utf-8-sig"
            ) as arquivo:
                return {
                    normalizar_url_maps(
                        row.get("Link Google Maps", "")
                    )
                    for row in csv.DictReader(arquivo)
                    if row.get("Link Google Maps", "").strip()
                }
        except (OSError, csv.Error):
            self.log.warning("CSV existente inválido; dedupe iniciará vazio.")
            return set()


def executar_scraper(slug: str) -> None:
    ScraperMaps(slug).executar()
