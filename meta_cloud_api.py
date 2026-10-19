"""Cliente seguro da Edge Function de envio pela Meta Cloud API."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import bot_repository
from app_session import carregar_sessao


class _SemRedirecionamento(HTTPRedirectHandler):
    """Impede encaminhar JWT e apikey para um destino redirecionado."""

    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str,
        headers: Any, newurl: str
    ) -> None:
        return None


def _abrir(request: Request, timeout: float) -> Any:
    return build_opener(_SemRedirecionamento()).open(
        request, timeout=timeout
    )


class ClienteMetaCloudAPI:
    """Envia somente referências da entrega; o token Meta fica no servidor."""

    def __init__(self, timeout: float = 30) -> None:
        self.timeout = timeout

    def enviar(self, delivery_id: int, claim_token: str) -> None:
        sessao = self._carregar_credenciais()
        url_base = str(sessao.get("supabase_url", "")).strip().rstrip("/")
        partes = urlsplit(url_base)
        if partes.scheme != "https" or not partes.netloc:
            raise RuntimeError("Configuração segura do Supabase indisponível.")

        payload = {
            "delivery_id": int(delivery_id),
            "claim_token": str(claim_token),
        }
        request = Request(
            f"{url_base}/functions/v1/whatsapp-meta-send",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "apikey": sessao["publishable_key"],
                "Authorization": f"Bearer {sessao['access_token']}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            # O corpo não é lido nem registrado para evitar dados sensíveis.
            with _abrir(request, timeout=self.timeout):
                return
        except HTTPError as erro:
            raise RuntimeError(
                f"A Edge Function recusou o envio (HTTP {erro.code})."
            ) from erro
        except (URLError, TimeoutError, OSError) as erro:
            raise RuntimeError(
                "A Edge Function de WhatsApp está indisponível."
            ) from erro

    @staticmethod
    def _carregar_credenciais() -> dict[str, str]:
        # Inicializar o repositório permite aproveitar o refresh de sessão já
        # realizado e persistido pelo cliente Supabase.
        bot_repository.obter_cliente()
        sessao: dict[str, Any] | None = carregar_sessao()
        obrigatorios = ("supabase_url", "publishable_key", "access_token")
        if not sessao or any(
            not str(sessao.get(chave, "")).strip()
            for chave in obrigatorios
        ):
            raise RuntimeError("Sessão Supabase indisponível para o envio.")
        return {
            chave: str(sessao[chave]).strip()
            for chave in obrigatorios
        }
