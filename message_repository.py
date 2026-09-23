"""Persistência dos bots de mensagens no Supabase."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

import bot_repository


def _executar(acao: str, chamada: Callable[[], Any]) -> Any:
    try:
        return chamada().data
    except Exception as erro:
        raise bot_repository.ErroPersistencia(
            f"Não foi possível {acao} no Supabase."
        ) from erro


def listar_comandos_runner(runner_id: str) -> list[dict[str, Any]]:
    dados = _executar(
        "listar os comandos dos bots de mensagens",
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
    dados = _executar(
        "carregar a configuração do bot de mensagens",
        lambda: bot_repository.obter_cliente()
        .table("prospecta_message_bot_configs")
        .select("*")
        .eq(campo, referencia)
        .is_("deleted_at", "null")
        .limit(1)
        .execute(),
    )
    return dados[0] if dados else None


def ler_comando(bot_id: str) -> dict[str, Any] | None:
    dados = _executar(
        "ler o comando do bot de mensagens",
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
        "confirmar o comando do bot de mensagens",
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
        "atualizar o runtime do bot de mensagens",
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
