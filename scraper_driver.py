"""Navegação resiliente no Google Maps com Selenium Manager."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote_plus, urlsplit

from selenium import webdriver
from selenium.common.exceptions import (
    InvalidSessionIdException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from urllib3.exceptions import HTTPError as Urllib3HTTPError

from execucao_bot import ControleExecucao


class FalhaPagina(RuntimeError):
    """Indica página instável ou estrutura essencial não encontrada."""


class NavegadorMaps:
    def __init__(
        self,
        config: dict[str, Any],
        controle: ControleExecucao,
        logger: logging.Logger,
        pasta_screenshots: Path,
    ):
        self.config = config
        self.controle = controle
        self.log = logger
        self.pasta_screenshots = pasta_screenshots
        self.pasta_screenshots.mkdir(parents=True, exist_ok=True)
        self.driver: Any | None = None

    def criar(self) -> None:
        """Inicia Chrome; o Selenium Manager resolve o driver compatível."""
        self.fechar()
        options = Options()
        if self.config["headless"]:
            options.add_argument("--headless=new")
        chrome_bin = os.getenv("CHROME_BIN", "").strip()
        if chrome_bin:
            options.binary_location = chrome_bin
        if os.getenv("RENDER"):
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--lang=pt-BR")
        options.add_argument("--window-size=1400,1000")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        ultimo_erro: Exception | None = None
        for tentativa in range(1, 4):
            self.controle.verificar()
            try:
                self.driver = webdriver.Chrome(options=options)
                self.driver.set_page_load_timeout(45)
                self.driver.execute_cdp_cmd(
                    "Page.addScriptToEvaluateOnNewDocument",
                    {
                        "source": "Object.defineProperty(navigator, 'webdriver', "
                        "{get: () => undefined})"
                    },
                )
                self.log.info("Chrome iniciado com Selenium Manager.")
                return
            except (OSError, WebDriverException, Urllib3HTTPError) as erro:
                ultimo_erro = erro
                self.log.warning(
                    "Falha ao iniciar Chrome (%s/3): %s",
                    tentativa,
                    str(erro).splitlines()[0],
                )
                self.controle.esperar(tentativa * 3)
        raise RuntimeError(f"Não foi possível iniciar o Chrome: {ultimo_erro}")

    def fechar(self) -> None:
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
        self.driver = None

    def screenshot(self, nome: str) -> None:
        if not self.driver:
            return
        nome_seguro = re.sub(r"[^a-zA-Z0-9_-]+", "_", nome)
        caminho = self.pasta_screenshots / (
            f"{nome_seguro}_{datetime.now():%Y%m%d_%H%M%S}.png"
        )
        try:
            self.driver.save_screenshot(str(caminho))
        except Exception:
            self.log.warning("Não foi possível salvar screenshot de diagnóstico.")

    def abrir(self, url: str, seletor: str | None = None) -> None:
        """Tenta navegação normal, F5 e recriação completa do Chrome."""
        ultimo_erro: Exception | None = None
        for tentativa in range(3):
            self.controle.verificar()
            try:
                if not self.driver:
                    self.criar()
                if tentativa == 0:
                    self.driver.get(url)
                elif tentativa == 1:
                    self.log.warning("Página instável; aplicando F5.")
                    self.driver.refresh()
                else:
                    self.log.warning("Sessão instável; recriando o Chrome.")
                    self.criar()
                    self.driver.get(url)
                if seletor:
                    WebDriverWait(self.driver, 15).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, seletor))
                    )
                return
            except (
                InvalidSessionIdException,
                TimeoutException,
                WebDriverException,
                Urllib3HTTPError,
            ) as erro:
                ultimo_erro = erro
                self.screenshot("falha_pagina")
        raise FalhaPagina(str(ultimo_erro))

    def coletar_itens(self, cidade: str) -> list[dict[str, str]]:
        self.abrir("https://www.google.com/maps")
        self.controle.esperar(2)
        self._aceitar_cookies()
        caixa = self._caixa_busca()
        termo = self.config["termo_busca"]
        consulta = (
            termo.format(cidade=cidade)
            if "{cidade}" in termo
            else f"{termo} em {cidade}"
        )
        caixa.click()
        caixa.clear()
        caixa.send_keys(consulta)
        caixa.send_keys(Keys.ENTER)
        self.controle.esperar(3)
        painel = self._painel()
        quantidade_anterior = -1
        repeticoes = 0
        for _ in range(self.config["max_scrolls"]):
            self.controle.verificar()
            self.driver.execute_script(
                "arguments[0].scrollTop = arguments[0].scrollHeight", painel
            )
            self.controle.esperar(1.3)
            quantidade = len(self._cards(painel))
            repeticoes = repeticoes + 1 if quantidade == quantidade_anterior else 0
            quantidade_anterior = quantidade
            if repeticoes >= 3:
                break
        itens: list[dict[str, str]] = []
        urls: set[str] = set()
        for card in self._cards(self._painel()):
            try:
                link = (
                    card
                    if card.tag_name == "a"
                    else card.find_element(By.CSS_SELECTOR, "a")
                )
                url = link.get_attribute("href")
                if url and url not in urls:
                    nome = (
                        card.get_attribute("aria-label")
                        or link.get_attribute("aria-label")
                        or self._nome_pela_url(url)
                    )
                    urls.add(url)
                    itens.append({"nome": nome.strip(), "url": url})
            except (NoSuchElementException, StaleElementReferenceException):
                continue
        if not itens:
            raise FalhaPagina("Nenhum estabelecimento encontrado.")
        self.log.info("%s resultado(s) coletado(s) para %s.", len(itens), cidade)
        return itens

    def _aceitar_cookies(self) -> None:
        seletores = (
            "//button[.//span[contains(text(),'Aceitar tudo')]]",
            "//button[.//span[contains(text(),'Accept all')]]",
            "//button[contains(@aria-label,'Aceitar')]",
            "//button[contains(@aria-label,'Accept')]",
        )
        for xpath in seletores:
            try:
                botao = WebDriverWait(self.driver, 2).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                botao.click()
                return
            except TimeoutException:
                continue

    def _caixa_busca(self) -> Any:
        seletores = (
            (By.CSS_SELECTOR, "input[name='q'][role='combobox']"),
            (By.CSS_SELECTOR, "form[jsaction*='searchboxFormSubmit'] input"),
            (By.ID, "searchboxinput"),
            (
                By.XPATH,
                "//input[contains(@aria-label,'Pesquisar') or "
                "contains(@aria-label,'Search')]",
            ),
        )
        for by, seletor in seletores:
            try:
                return WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((by, seletor))
                )
            except TimeoutException:
                continue
        raise FalhaPagina("Caixa de busca não encontrada.")

    def _painel(self) -> Any:
        seletores = (
            (By.CSS_SELECTOR, "div[role='feed']"),
            (By.CSS_SELECTOR, "div.m6QErb[aria-label]"),
            (By.XPATH, "//div[contains(@aria-label, 'Resultados para')]"),
        )
        for by, seletor in seletores:
            try:
                return WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((by, seletor))
                )
            except TimeoutException:
                continue
        raise FalhaPagina("Painel de resultados não encontrado.")

    @staticmethod
    def _cards(painel: Any) -> list[Any]:
        for seletor in ("div.Nv2PK", "a.hfpxzc", "div[jsaction*='mouseover']"):
            cards = painel.find_elements(By.CSS_SELECTOR, seletor)
            if cards:
                return cards
        return []

    @staticmethod
    def _nome_pela_url(url: str) -> str:
        """Recupera o nome presente no caminho canônico do Google Maps."""
        partes = urlsplit(url).path.split("/place/", 1)
        if len(partes) == 2:
            nome = unquote_plus(partes[1].split("/", 1)[0]).strip()
            if nome:
                return nome
        return "Nome não identificado"
