"""Persistência remota dos bots no Supabase."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


class ErroPersistencia(RuntimeError):
    """Erro seguro da camada de persistência remota."""


class ConflitoVersao(ErroPersistencia):
    """Indica alteração concorrente ou registro indisponível."""


_cliente: Any | None = None
_cliente_lock = threading.Lock()

_COLUNAS_PARA_APP = {
    "name": "nome",
    "search_term": "termo_busca",
    "niche": "nicho",
    "cities": "cidades",
    "min_reviews": "minimo_avaliacoes",
    "estimated_ticket": "ticket_estimado",
    "excluded_words": "palavras_excluidas",
    "included_words": "palavras_incluidas",
    "version": "versao",
    "created_at": "criado_em",
    "updated_at": "atualizado_em",
    "deleted_at": "excluido_em",
}
_APP_PARA_COLUNAS = {valor: chave for chave, valor in _COLUNAS_PARA_APP.items()}


def obter_cliente() -> Any:
    """Cria o cliente somente no primeiro acesso."""
    global _cliente
    if _cliente is not None:
        return _cliente
    with _cliente_lock:
        if _cliente is not None:
            return _cliente
        load_dotenv(Path(__file__).with_name(".env"), override=False)
        url = os.getenv("SUPABASE_URL", "").strip()
        chave = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
        if not url or not chave:
            raise ErroPersistencia(
                "Configure SUPABASE_URL e SUPABASE_SERVICE_KEY no arquivo .env."
            )
        try:
            from supabase import create_client

            _cliente = create_client(url, chave)
        except Exception as erro:
            raise ErroPersistencia(
                "Não foi possível inicializar a conexão com o Supabase."
            ) from erro
    return _cliente


def linha_para_config(linha: dict[str, Any]) -> dict[str, Any]:
    """Converte nomes de colunas para o contrato usado pela aplicação."""
    return {_COLUNAS_PARA_APP.get(chave, chave): valor for chave, valor in linha.items()}


def config_para_linha(config: dict[str, Any]) -> dict[str, Any]:
    """Converte o contrato da aplicação para as colunas do banco."""
    ignoradas = {"_persistencia", "_fallback_cache", "sincronizado"}
    return {
        _APP_PARA_COLUNAS.get(chave, chave): valor
        for chave, valor in config.items()
        if chave not in ignoradas
    }


def _executar(acao: str, chamada: Any) -> Any:
    try:
        return chamada().data
    except ErroPersistencia:
        raise
    except Exception as erro:
        detalhe = str(erro).casefold()
        if "invalid api key" in detalhe or "'code': 401" in detalhe:
            raise ErroPersistencia(
                "A SUPABASE_SERVICE_KEY foi recusada pelo Supabase. "
                "Atualize a chave no arquivo .env."
            ) from erro
        if "pgrst205" in detalhe or (
            "could not find the table" in detalhe
            and "prospecta_bot_" in detalhe
        ) or (
            "pgrst202" in detalhe
            and "prospecta_" in detalhe
        ):
            raise ErroPersistencia(
                "O contrato de banco dos bots está desatualizado. Execute "
                "supabase_bot_tables.sql no SQL Editor do Supabase."
            ) from erro
        # Não propagamos resposta bruta para evitar dados sensíveis em logs.
        raise ErroPersistencia(f"Não foi possível {acao} no Supabase.") from erro


def _unico(dados: Any, mensagem: str) -> dict[str, Any]:
    if isinstance(dados, list) and dados:
        return dados[0]
    if isinstance(dados, dict) and dados:
        return dados
    raise ConflitoVersao(mensagem)


def listar_configs() -> list[dict[str, Any]]:
    dados = _executar(
        "listar as configurações",
        lambda: obter_cliente()
        .table("prospecta_bot_configs")
        .select("*")
        .is_("deleted_at", "null")
        .order("name")
        .execute(),
    )
    return [linha_para_config(item) for item in dados or []]


def carregar_config(referencia: str) -> dict[str, Any] | None:
    consulta = (
        obter_cliente()
        .table("prospecta_bot_configs")
        .select("*")
        .is_("deleted_at", "null")
    )
    campo = "id" if _parece_uuid(referencia) else "slug"
    dados = _executar(
        "carregar a configuração",
        lambda: consulta.eq(campo, referencia).limit(1).execute(),
    )
    return linha_para_config(dados[0]) if dados else None


def salvar_config(
    config: dict[str, Any], expected_version: int | None = None
) -> dict[str, Any]:
    linha = config_para_linha(config)
    bot_id = linha.pop("id", None)
    for campo in ("created_at", "updated_at", "deleted_at", "version"):
        linha.pop(campo, None)

    if not bot_id:
        dados = _executar(
            "criar a configuração",
            lambda: obter_cliente()
            .table("prospecta_bot_configs")
            .insert(linha)
            .execute(),
        )
    else:
        consulta = (
            obter_cliente()
            .table("prospecta_bot_configs")
            .update(linha)
            .eq("id", bot_id)
            .is_("deleted_at", "null")
        )
        if expected_version is not None:
            consulta = consulta.eq("version", expected_version)
        dados = _executar("atualizar a configuração", consulta.execute)

    salvo = _unico(
        dados,
        "A configuração foi alterada por outro processo ou não está mais ativa.",
    )
    return linha_para_config(salvo)


def excluir_config(bot_id: str, expected_version: int | None = None) -> dict[str, Any]:
    from datetime import datetime, timezone

    consulta = (
        obter_cliente()
        .table("prospecta_bot_configs")
        .update({"deleted_at": datetime.now(timezone.utc).isoformat()})
        .eq("id", bot_id)
        .is_("deleted_at", "null")
    )
    if expected_version is not None:
        consulta = consulta.eq("version", expected_version)
    dados = _executar("excluir logicamente a configuração", consulta.execute)
    return linha_para_config(
        _unico(dados, "A configuração já foi alterada ou excluída.")
    )


def definir_comando(
    bot_id: str,
    comando: str,
    target_runner_id: str | None = None,
) -> dict[str, Any]:
    dados = _rpc(
        "prospecta_request_command",
        {
            "p_bot_id": bot_id,
            "p_command": comando,
            "p_target_runner_id": target_runner_id,
        },
        "salvar o comando",
    )
    return _unico(dados, "O comando não pôde ser confirmado.")


def ler_comando(bot_id: str) -> dict[str, Any] | None:
    dados = _executar(
        "ler o comando",
        lambda: obter_cliente()
        .table("prospecta_bot_controls")
        .select("*")
        .eq("bot_id", bot_id)
        .limit(1)
        .execute(),
    )
    return dados[0] if dados else None


def excluir_comando(bot_id: str) -> None:
    _executar(
        "excluir o comando",
        lambda: obter_cliente()
        .table("prospecta_bot_controls")
        .delete()
        .eq("bot_id", bot_id)
        .execute(),
    )


def claim_checkpoint(
    bot_id: str, process_name: str, runner_id: str, lease_seconds: int = 300
) -> dict[str, Any]:
    dados = _rpc(
        "prospecta_claim_checkpoint",
        {
            "p_bot_id": bot_id,
            "p_process_name": process_name,
            "p_runner_id": runner_id,
            "p_lease_seconds": lease_seconds,
        },
        "reservar o checkpoint",
    )
    return _unico(dados, "O checkpoint está reservado por outro executor.")


def save_checkpoint(
    bot_id: str,
    process_name: str,
    runner_id: str,
    state: dict[str, Any],
    status: str = "running",
    expected_version: int | None = None,
    lease_seconds: int = 300,
) -> dict[str, Any]:
    dados = _rpc(
        "prospecta_save_checkpoint",
        {
            "p_bot_id": bot_id,
            "p_process_name": process_name,
            "p_runner_id": runner_id,
            "p_state": state,
            "p_status": status,
            "p_expected_version": expected_version,
            "p_lease_seconds": lease_seconds,
        },
        "salvar o checkpoint",
    )
    return _unico(dados, "Lease expirado, executor inválido ou versão divergente.")


def release_checkpoint(
    bot_id: str,
    process_name: str,
    runner_id: str,
    status: str = "idle",
    expected_version: int | None = None,
) -> dict[str, Any]:
    dados = _rpc(
        "prospecta_release_checkpoint",
        {
            "p_bot_id": bot_id,
            "p_process_name": process_name,
            "p_runner_id": runner_id,
            "p_status": status,
            "p_expected_version": expected_version,
        },
        "liberar o checkpoint",
    )
    return _unico(dados, "Checkpoint não pertence ao executor ou versão divergente.")


def load_checkpoint(bot_id: str, process_name: str) -> dict[str, Any] | None:
    dados = _executar(
        "carregar o checkpoint",
        lambda: obter_cliente()
        .table("prospecta_bot_checkpoints")
        .select("*")
        .eq("bot_id", bot_id)
        .eq("process_name", process_name)
        .limit(1)
        .execute(),
    )
    return dados[0] if dados else None


def carregar_runtime_bot(bot_id: str) -> dict[str, Any] | None:
    """Retorna a fotografia remota completa preparada para qualquer interface."""
    dados = _rpc(
        "prospecta_get_bot_runtime",
        {"p_bot_id": bot_id},
        "carregar o runtime do bot",
    )
    return dados if isinstance(dados, dict) else None


def listar_runtimes_bots() -> list[dict[str, Any]]:
    """Carrega todos os runtimes em uma única chamada ao Supabase."""
    dados = _rpc(
        "prospecta_list_bot_runtimes",
        {},
        "listar os runtimes dos bots",
    )
    return [
        item["runtime"]
        for item in dados or []
        if isinstance(item, dict) and isinstance(item.get("runtime"), dict)
    ]


def carregar_eventos_bot(
    bot_id: str, limite: int = 100
) -> list[dict[str, Any]]:
    dados = _rpc(
        "prospecta_get_bot_events",
        {"p_bot_id": bot_id, "p_limit": limite},
        "carregar os eventos do bot",
    )
    return list(dados or [])


def registrar_runner(
    runner_id: str,
    nome: str,
    ambiente: str,
    metadata: dict[str, Any],
    status: str = "online",
) -> dict[str, Any]:
    dados = _executar(
        "registrar o executor",
        lambda: obter_cliente()
        .table("prospecta_bot_runners")
        .upsert(
            {
                "id": runner_id,
                "name": nome,
                "environment": ambiente,
                "status": status,
                "metadata": metadata,
                "heartbeat_at": _agora_iso(),
            },
            on_conflict="id",
        )
        .execute(),
    )
    return _unico(dados, "O executor não pôde ser registrado.")


def listar_comandos_runner(runner_id: str) -> list[dict[str, Any]]:
    dados = _executar(
        "listar os comandos do executor",
        lambda: obter_cliente()
        .table("prospecta_bot_controls")
        .select("*")
        .eq("target_runner_id", runner_id)
        .execute(),
    )
    return list(dados or [])


def confirmar_comando(bot_id: str, request_id: str) -> None:
    _executar(
        "confirmar o comando",
        lambda: obter_cliente()
        .table("prospecta_bot_controls")
        .update({"acknowledged_at": _agora_iso()})
        .eq("bot_id", bot_id)
        .eq("request_id", request_id)
        .execute(),
    )


def registrar_evento(
    bot_id: str,
    process_name: str,
    runner_id: str | None,
    event_type: str,
    message: str,
    data: dict[str, Any] | None = None,
    level: str = "info",
    event_id: str | None = None,
) -> None:
    payload = {
        "bot_id": bot_id,
        "process_name": process_name,
        "runner_id": runner_id,
        "event_type": event_type,
        "level": level,
        "message": message,
        "data": data or {},
    }
    if event_id:
        payload["event_id"] = event_id
    _executar(
        "registrar o evento do bot",
        lambda: obter_cliente()
        .table("prospecta_bot_events")
        .upsert(payload, on_conflict="event_id")
        .execute(),
    )


def _rpc(nome: str, parametros: dict[str, Any], acao: str) -> Any:
    return _executar(
        acao, lambda: obter_cliente().rpc(nome, parametros).execute()
    )


def _parece_uuid(valor: str) -> bool:
    from uuid import UUID

    try:
        UUID(str(valor))
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def _agora_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
