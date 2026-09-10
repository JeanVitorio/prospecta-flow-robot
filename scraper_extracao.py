"""Extração e filtros dinâmicos dos estabelecimentos do Google Maps."""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from selenium.common.exceptions import NoSuchElementException
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
        possui_site = self._possui_site(driver)
        telefone = self._extrair_telefone(driver)
        self.log.info(
            "%s | categoria: %s | avaliações: %s | %s",
            nome,
            categoria or "não identificada",
            avaliacoes if avaliacoes is not None else "não identificadas",
            "tem site" if possui_site else "sem site",
        )
        if (
            possui_site
            or avaliacoes is None
            or avaliacoes < self.config["minimo_avaliacoes"]
        ):
            return None
        return {
            "Nome": nome,
            "Cidade": cidade,
            "Telefone": telefone,
            "Avaliações": avaliacoes,
            "Link Google Maps": driver.current_url,
        }

    def _aceitar_filtros(self, nome: str, categoria: str) -> bool:
        combinado = normalizar_texto(f"{nome} {categoria}")
        excluidas = [
            normalizar_texto(str(palavra))
            for palavra in self.config["palavras_excluidas"]
        ]
        incluidas = [
            normalizar_texto(str(palavra))
            for palavra in self.config["palavras_incluidas"]
        ]
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
            "span.F7nice span[aria-label]",
            "span[aria-label*='avaliações']",
            "span[aria-label*='reviews']",
            "button[aria-label*='avaliações']",
            "button[aria-label*='reviews']",
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
        correspondencia = re.search(r"([\d][\d.,]*)", texto or "")
        if not correspondencia:
            return None
        digitos = re.sub(r"\D", "", correspondencia.group(1))
        try:
            return int(digitos)
        except ValueError:
            return None

    @staticmethod
    def _possui_site(driver: Any) -> bool:
        return any(
            driver.find_elements(By.CSS_SELECTOR, seletor)
            for seletor in (
                "a[data-item-id='authority']",
                "a[aria-label^='Site:']",
                "a[aria-label^='Website:']",
            )
        )

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
