"""Persistência dos agentes de WhatsApp no Supabase."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

import bot_repository

PROVIDER_WHATSAPP_WEB = "whatsapp_web"
PROVIDERS_SUPORTADOS = {PROVIDER_WHATSAPP_WEB}


def _executar(acao: str, chamada: Callable[[], Any]) -> Any:
    try:
        return chamada().data
    except Exception as erro:
        raise bot_repository.ErroPersistencia(
            f"Não foi possível {acao} no Supabase."
        ) from erro


def listar_comandos_runner(runner_id: str) -> list[dict[str, Any]]:
    dados = _executar(
        "listar os comandos dos agentes de WhatsApp",
        lambda: bot_repository.obter_cliente()
        .table("prospecta_message_bot_controls")
        .select("*")
        .eq("target_runner_id", runner_id)
        .execute(),
    )
    return list(dados or [])


def carregar_config(referencia: str) -> dict[str, Any] | None:
    try:
        UUID(str(referencia))
        campo = "id"
    except (ValueError, TypeError, AttributeError):
        campo = "slug"
    try:
        dados = _consultar_config(
            campo,
            referencia,
            "*, whatsapp_session:prospecta_whatsapp_sessions(provider)",
        )
    except bot_repository.ErroPersistencia:
        # Compatibilidade com schemas anteriores sem provider/relacionamento.
        dados = _consultar_config(campo, referencia, "*")
    if not dados:
        return None
    config = dict(dados[0])
    config["provider"] = obter_provider(config)
    return config


def _consultar_config(
    campo: str, referencia: str, select: str
) -> list[dict[str, Any]]:
    dados = _executar(
        "carregar a configuração do agente de WhatsApp",
        lambda: bot_repository.obter_cliente()
        .table("prospecta_message_bot_configs")
        .select(select)
        .eq(campo, referencia)
        .is_("deleted_at", "null")
        .limit(1)
        .execute(),
    )
    return list(dados or [])


def obter_provider(config: dict[str, Any]) -> str:
    """Obtém o transporte normalizado, preservando o schema legado."""
    valor: Any = config.get("provider")
    sessao = config.get("whatsapp_session")
    if valor is None and isinstance(sessao, dict):
        valor = sessao.get("provider")
    elif valor is None and isinstance(sessao, list) and sessao:
        primeiro = sessao[0]
        if isinstance(primeiro, dict):
            valor = primeiro.get("provider")
    if valor is None or not str(valor).strip():
        return PROVIDER_WHATSAPP_WEB
    return str(valor).strip().casefold()


def ler_comando(bot_id: str) -> dict[str, Any] | None:
    dados = _executar(
        "ler o comando do agente de WhatsApp",
        lambda: bot_repository.obter_cliente()
        .table("prospecta_message_bot_controls")
        .select("*")
        .eq("bot_id", bot_id)
        .limit(1)
        .execute(),
    )
    return dados[0] if dados else None


def confirmar_comando(bot_id: str, request_id: str) -> None:
    _executar(
        "confirmar o comando do agente de WhatsApp",
        lambda: bot_repository.obter_cliente()
        .table("prospecta_message_bot_controls")
        .update({"acknowledged_at": _agora()})
        .eq("bot_id", bot_id)
        .eq("request_id", request_id)
        .execute(),
    )


def atualizar_runtime(bot_id: str, dados: dict[str, Any]) -> None:
    payload = {"bot_id": bot_id, **dados}
    _executar(
        "atualizar o runtime do agente de WhatsApp",
        lambda: bot_repository.obter_cliente()
        .table("prospecta_message_bot_runtime")
        .upsert(payload, on_conflict="bot_id")
        .execute(),
    )


def atualizar_sessao(session_id: str, dados: dict[str, Any]) -> None:
    _executar(
        "atualizar a sessão do WhatsApp",
        lambda: bot_repository.obter_cliente()
        .table("prospecta_whatsapp_sessions")
        .update(dados)
        .eq("id", session_id)
        .is_("deleted_at", "null")
        .execute(),
    )


def listar_sessoes_runner(runner_id: str) -> list[dict[str, Any]]:
    """Sessões já autenticadas neste executor (o login fica salvo localmente)."""
    dados = _executar(
        "listar as sessões do WhatsApp",
        lambda: bot_repository.obter_cliente()
        .table("prospecta_whatsapp_sessions")
        .select("*")
        .eq("runner_id", runner_id)
        .is_("deleted_at", "null")
        .order("updated_at", desc=True)
        .execute(),
    )
    return [
        dict(sessao)
        for sessao in dados or []
        if obter_provider(sessao) == PROVIDER_WHATSAPP_WEB
    ]


def claim_lead(bot_id: str, runner_id: str) -> dict[str, Any] | None:
    dados = _executar(
        "reservar o próximo lead",
        lambda: bot_repository.obter_cliente()
        .rpc(
            "prospecta_claim_message_lead",
            {
                "p_bot_id": bot_id,
                "p_runner_id": runner_id,
                "p_lease_seconds": 300,
            },
        )
        .execute(),
    )
    return dados if isinstance(dados, dict) else None


def finalizar_entrega(
    delivery_id: int,
    claim_token: str,
    status: str,
    error_code: str | None = None,
) -> bool:
    dados = _executar(
        "finalizar o envio da mensagem",
        lambda: bot_repository.obter_cliente()
        .rpc(
            "prospecta_finalize_message_delivery",
            {
                "p_delivery_id": delivery_id,
                "p_claim_token": claim_token,
                "p_status": status,
                "p_error_code": error_code,
            },
        )
        .execute(),
    )
    return bool(dados)


def enviados_ultima_hora(bot_id: str) -> int:
    dados = _executar(
        "contar as mensagens da última hora",
        lambda: bot_repository.obter_cliente()
        .rpc("prospecta_message_sent_last_hour", {"p_bot_id": bot_id})
        .execute(),
    )
    return int(dados or 0)


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()
