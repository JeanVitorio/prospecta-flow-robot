"""CLI única para os motores dinâmicos de scraper e importação."""

from __future__ import annotations

import argparse
import os

import bot_config
from importador_compartilhado import executar_importador
from mensageiro_whatsapp import executar_mensageiro
from scraper_maps import executar_scraper


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Executa um motor dinâmico pela configuração do bot."
    )
    parser.add_argument("processo", choices=("scraper", "importador", "mensagens"))
    parser.add_argument("slug", help="Slug da configuração remota.")
    argumentos = parser.parse_args()

    # O runner remoto preserva o destino registrado no comando.
    if (
        argumentos.processo != "mensagens"
        and os.getenv("PROSPECTA_PRESERVAR_COMANDO") != "1"
    ):
        bot_config.definir_comando(argumentos.slug, "rodando")
    if argumentos.processo == "scraper":
        executar_scraper(argumentos.slug)
    elif argumentos.processo == "importador":
        executar_importador(argumentos.slug)
    else:
        executar_mensageiro(argumentos.slug)


if __name__ == "__main__":
    main()
