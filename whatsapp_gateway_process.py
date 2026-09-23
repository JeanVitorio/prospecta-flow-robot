"""Gerencia o gateway local e isolado do WhatsApp Web."""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


class GatewayWhatsApp:
    """Mantém um único processo Node disponível para todos os bots."""

    def __init__(self, logger: logging.Logger) -> None:
        self.log = logger
        self.base = Path(__file__).resolve().parent
        self.pasta = self.base / "whatsapp_gateway"
        self.processo: subprocess.Popen[str] | None = None
        self.arquivo_log = None
        self.porta = int(os.getenv("WHATSAPP_GATEWAY_PORT", "32145"))
        self.token = secrets.token_urlsafe(32)
        self.url = f"http://127.0.0.1:{self.porta}"

    def iniciar(self) -> bool:
        node = shutil.which("node")
        if not node:
            self.log.error(
                "Node.js não encontrado; bots de WhatsApp permanecerão indisponíveis."
            )
            return False
        if not (self.pasta / "node_modules").exists():
            self.log.error(
                "Dependências do gateway ausentes. Execute npm install em %s.",
                self.pasta,
            )
            return False

        ambiente = os.environ.copy()
        ambiente.update(
            WHATSAPP_GATEWAY_PORT=str(self.porta),
            WHATSAPP_GATEWAY_TOKEN=self.token,
            WHATSAPP_SESSION_PATH=str(self.base / "dados_whatsapp"),
        )
        os.environ["WHATSAPP_GATEWAY_URL"] = self.url
        os.environ["WHATSAPP_GATEWAY_TOKEN"] = self.token
        self.arquivo_log = (self.base / "whatsapp_gateway.log").open(
            "a", encoding="utf-8", buffering=1
        )
        self.processo = subprocess.Popen(
            [node, "server.js"],
            cwd=self.pasta,
            env=ambiente,
            stdin=subprocess.DEVNULL,
            stdout=self.arquivo_log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for _ in range(40):
            if self.processo.poll() is not None:
                self.log.error("O gateway WhatsApp encerrou durante a inicialização.")
                return False
            if self._saudavel():
                self.log.info("Gateway WhatsApp local iniciado.")
                return True
            time.sleep(0.5)
        self.log.error("Gateway WhatsApp não respondeu dentro do tempo esperado.")
        self.parar()
        return False

    def parar(self) -> None:
        if self.processo and self.processo.poll() is None:
            self.processo.terminate()
            try:
                self.processo.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.processo.kill()
        self.processo = None
        if self.arquivo_log:
            self.arquivo_log.close()
            self.arquivo_log = None

    def _saudavel(self) -> bool:
        request = Request(
            f"{self.url}/health",
            headers={"Authorization": f"Bearer {self.token}"},
        )
        try:
            with urlopen(request, timeout=1) as resposta:
                return json.load(resposta).get("status") == "ok"
        except (URLError, TimeoutError, ValueError, OSError):
            return False
