"""Cliente HTTP do gateway local do WhatsApp Web."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ClienteGateway:
    """Cliente HTTP restrito ao gateway local iniciado pelo runner."""

    def __init__(self) -> None:
        self.url = os.getenv("WHATSAPP_GATEWAY_URL", "").rstrip("/")
        self.token = os.getenv("WHATSAPP_GATEWAY_TOKEN", "")
        if not self.url or not self.token:
            raise RuntimeError("Gateway WhatsApp não foi iniciado pelo runner.")

    def conectar(self, session_id: str) -> dict[str, Any]:
        return self._post("/sessions/connect", {"session_id": session_id})

    def status(self, session_id: str) -> dict[str, Any]:
        return self._post("/sessions/status", {"session_id": session_id})

    def desconectar(self, session_id: str) -> dict[str, Any]:
        return self._post("/sessions/logout", {"session_id": session_id})

    def enviar(
        self, session_id: str, telefone: str, mensagem: str
    ) -> dict[str, Any]:
        return self._post(
            "/messages/send",
            {
                "session_id": session_id,
                "phone": telefone,
                "message": mensagem,
            },
        )

    def _post(self, caminho: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            f"{self.url}{caminho}",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=90) as resposta:
                dados = json.load(resposta)
        except HTTPError as erro:
            try:
                detalhe = json.load(erro).get("error", "Falha no gateway.")
            except (ValueError, AttributeError):
                detalhe = "Falha no gateway."
            raise RuntimeError(str(detalhe)) from erro
        except (URLError, TimeoutError, OSError, ValueError) as erro:
            raise RuntimeError("Gateway WhatsApp indisponível.") from erro
        return dados if isinstance(dados, dict) else {}
