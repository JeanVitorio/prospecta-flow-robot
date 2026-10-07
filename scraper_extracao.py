"""Extração e filtros dinâmicos dos estabelecimentos do Google Maps."""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any
from urllib.parse import parse_qs, urlsplit, urlunsplit

from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException,
)
from selenium.webdriver.common.by import By

from scraper_driver import NavegadorMaps


def normalizar_texto(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.casefold())
    texto = texto.encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def normalizar_url_maps(url: str) -> str:
    """Remove fragmentos e parâmetros voláteis usados pelo Google Maps."""
    url = url.strip()
    if not url:
        return ""
    partes = urlsplit(url)
    caminho = partes.path.rstrip("/")
    return urlunsplit((partes.scheme.casefold(), partes.netloc.casefold(), caminho, "", ""))


class ExtratorMaps:
    def __init__(
        self,
        config: dict[str, Any],
        navegador: NavegadorMaps,
        logger: logging.Logger,
    ):
        self.config = config
        self.navegador = navegador
        self.log = logger

    def extrair(
        self, item: dict[str, str], cidade: str
    ) -> dict[str, str | int] | None:
        self.navegador.abrir(item["url"], "h1")
        driver = self.navegador.driver
        nome = item["nome"]
        for seletor in ("h1.DUwDvf", "h1.qrShPb", "h1"):
            try:
                nome = driver.find_element(By.CSS_SELECTOR, seletor).text.strip() or nome
                break
            except NoSuchElementException:
                continue
        categoria = self._extrair_categoria(driver)
        if not self._aceitar_filtros(nome, categoria):
            return None
        avaliacoes = self._extrair_avaliacoes(driver)
        site = self._extrair_site(driver)
        telefone = self._extrair_telefone(driver)
        instagram = self._extrair_instagram(driver)
        self.log.info(
            "%s | categoria: %s | avaliações: %s | %s | %s | %s",
            nome,
            categoria or "não identificada",
            avaliacoes if avaliacoes is not None else "não identificadas",
            "tem site" if site else "sem site",
            "tem telefone" if telefone != "não encontrado" else "sem telefone",
            "tem Instagram" if instagram else "sem Instagram",
        )
        if not self._aceitar_presenca(
            bool(site), self.config.get("filtro_site", "without")
        ):
            return None
        if not self._aceitar_presenca(
            telefone != "não encontrado",
            self.config.get("filtro_telefone", "any"),
        ):
            return None
        minimo_avaliacoes = self.config["minimo_avaliacoes"]
        if (
            self.config.get("filtro_avaliacoes_ativo", True)
            and minimo_avaliacoes > 0
            and avaliacoes is not None
            and avaliacoes < minimo_avaliacoes
        ):
            return None
        return {
            "Nome": nome,
            "Cidade": cidade,
            "Telefone": telefone,
            "Avaliações": avaliacoes,
            "Site": site,
            "Instagram": instagram,
            "Link Google Maps": driver.current_url,
        }

    def _aceitar_filtros(self, nome: str, categoria: str) -> bool:
        combinado = normalizar_texto(f"{nome} {categoria}")
        excluidas = (
            [
                normalizar_texto(str(palavra))
                for palavra in self.config["palavras_excluidas"]
            ]
            if self.config.get("filtro_palavras_excluidas_ativo", True)
            else []
        )
        incluidas = (
            [
                normalizar_texto(str(palavra))
                for palavra in self.config["palavras_incluidas"]
            ]
            if self.config.get("filtro_palavras_incluidas_ativo", True)
            else []
        )
        termo_excluido = next(
            (termo for termo in excluidas if termo and termo in combinado), None
        )
        if termo_excluido:
            self.log.info(
                "Descartado pelo filtro negativo: %s | termo: %s",
                nome,
                termo_excluido,
            )
            return False
        if incluidas and not any(
            termo and termo in combinado for termo in incluidas
        ):
            self.log.info(
                "Descartado por não atender ao filtro positivo: %s", nome
            )
            return False
        return True

    @staticmethod
    def _aceitar_presenca(presente: bool, filtro: str) -> bool:
        if filtro == "with":
            return presente
        if filtro == "without":
            return not presente
        return True

    @staticmethod
    def _extrair_categoria(driver: Any) -> str:
        seletores = (
            "button[jsaction*='pane.rating.category']",
            "button.DkEaL",
            "button[jsaction*='category']",
        )
        for seletor in seletores:
            for elemento in driver.find_elements(By.CSS_SELECTOR, seletor):
                categoria = elemento.text.strip()
                if categoria:
                    return categoria
        return ""

    @classmethod
    def _extrair_avaliacoes(cls, driver: Any) -> int | None:
        seletores = (
            "button[jsaction*='reviewChart']",
            "button[jsaction*='moreReviews']",
            "span.F7nice",
            "span.F7nice span[aria-label]",
            "span[aria-label*='avaliações']",
            "span[aria-label*='avaliação']",
            "span[aria-label*='reviews']",
            "span[aria-label*='review']",
            "button[aria-label*='avaliações']",
            "button[aria-label*='avaliação']",
            "button[aria-label*='reviews']",
            "button[aria-label*='review']",
        )
        for seletor in seletores:
            for elemento in driver.find_elements(By.CSS_SELECTOR, seletor):
                valor = cls._numero_avaliacoes(
                    elemento.get_attribute("aria-label") or elemento.text
                )
                if valor is not None:
                    return valor
        return None

    @staticmethod
    def _numero_avaliacoes(texto: str | None) -> int | None:
        texto = texto or ""
        correspondencia = re.search(
            r"([\d][\d.,\s]*)\s+"
            r"(?:avaliaç(?:ão|ões)|comentários?|reviews?)\b",
            texto,
            flags=re.IGNORECASE,
        )
        if not correspondencia:
            correspondencia = re.search(r"\(([\d][\d.,\s]*)\)", texto)
        if not correspondencia:
            return None
        digitos = re.sub(r"\D", "", correspondencia.group(1))
        try:
            return int(digitos)
        except ValueError:
            return None

    def _extrair_site(self, driver: Any) -> str:
        try:
            for seletor in (
                "a[data-item-id='authority']",
                "a[aria-label^='Site:']",
                "a[aria-label^='Website:']",
            ):
                for elemento in driver.find_elements(By.CSS_SELECTOR, seletor):
                    url = (elemento.get_attribute("href") or "").strip()
                    if url:
                        return url
        except (StaleElementReferenceException, WebDriverException) as erro:
            self.log.warning(
                "Site não pôde ser lido; a empresa continuará: %s",
                type(erro).__name__,
            )
        return ""

    def _extrair_instagram(self, driver: Any) -> str:
        """Rola o painel da empresa e retorna o primeiro Instagram exibido."""
        for tentativa in range(4):
            self.navegador.controle.verificar()
            instagram = self._primeiro_instagram(driver)
            if instagram:
                return instagram
            if tentativa == 3:
                break
            try:
                painel = driver.execute_script(
                    """
                    const raiz = document.querySelector("div[role='main']");
                    if (!raiz) return null;
                    const candidatos = [raiz, ...raiz.querySelectorAll("div")];
                    return candidatos
                      .filter((item) => item.scrollHeight > item.clientHeight + 20)
                      .sort(
                        (a, b) =>
                          (b.scrollHeight - b.clientHeight) -
                          (a.scrollHeight - a.clientHeight),
                      )[0] || raiz;
                    """
                )
                if not painel:
                    return ""
                driver.execute_script(
                    "arguments[0].scrollTop += 500", painel
                )
                self.navegador.controle.esperar(0.6)
            except (StaleElementReferenceException, WebDriverException) as erro:
                self.log.warning(
                    "Instagram não pôde ser pesquisado; "
                    "a empresa continuará: %s",
                    type(erro).__name__,
                )
                return ""
        return ""

    @classmethod
    def _primeiro_instagram(cls, driver: Any) -> str:
        try:
            links = driver.find_elements(
                By.CSS_SELECTOR,
                "a[href*='instagram.com'], a[data-item-id*='instagram' i]",
            )
            for link in links:
                url = cls._normalizar_instagram(
                    link.get_attribute("href") or ""
                )
                if url:
                    return url
        except (StaleElementReferenceException, WebDriverException):
            return ""
        return ""

    @staticmethod
    def _normalizar_instagram(url: str) -> str:
        url = url.strip()
        if not url:
            return ""
        partes = urlsplit(url)
        if "google." in partes.netloc.casefold():
            parametros = parse_qs(partes.query)
            url = (parametros.get("q") or parametros.get("url") or [""])[0]
            partes = urlsplit(url)
        host = partes.netloc.casefold().removeprefix("www.")
        if host not in {"instagram.com", "m.instagram.com"}:
            return ""
        return urlunsplit(("https", "www.instagram.com", partes.path.rstrip("/"), "", ""))

    @staticmethod
    def _extrair_telefone(driver: Any) -> str:
        seletores = (
            "button[data-item-id^='phone:tel:']",
            "button[aria-label^='Telefone:']",
            "button[aria-label^='Phone:']",
        )
        for seletor in seletores:
            elementos = driver.find_elements(By.CSS_SELECTOR, seletor)
            if elementos:
                elemento = elementos[0]
                texto = elemento.text.strip()
                if texto:
                    return texto
                return (elemento.get_attribute("aria-label") or "").split(
                    ":", 1
                )[-1].strip()
        return "não encontrado"
