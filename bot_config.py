"""Validação e persistência coordenada das configurações dos bots."""

from __future__ import annotations

import os
import re
import unicodedata
import warnings
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

import bot_repository as remoto
import bot_storage as local


class ErroValidacao(ValueError):
    """Configuração inválida informada pela aplicação."""


class ListagemConfigs(list):
    """Lista compatível com list que informa a origem dos dados."""

    def __init__(self, itens: list[dict[str, Any]], fonte: str, fallback_cache: bool):
        super().__init__(itens)
        self.fonte = fonte
        self.fallback_cache = fallback_cache


_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_COMANDO = re.compile(r"^[a-z][a-z0-9_-]{0,49}$")


def pasta_bot(slug: str):
    """Mantém o contrato público para localizar dados locais do bot."""
    return local.pasta_bot(slug)


def listar_configs() -> ListagemConfigs:
    """Lista o remoto; em indisponibilidade, retorna cache sinalizado."""
    try:
        configs = remoto.listar_configs()
        local.sincronizar_configs(configs)
        return ListagemConfigs(configs, "supabase", False)
    except remoto.ErroPersistencia:
        warnings.warn(
            "Supabase indisponível; configurações carregadas do cache local.",
            RuntimeWarning,
            stacklevel=2,
        )
        return ListagemConfigs(local.listar_configs(), "cache", True)


def carregar_config(referencia: str) -> dict[str, Any] | None:
    """Carrega dados atuais do remoto e usa cache quando necessário."""
    _validar_referencia(referencia)
    try:
        config = remoto.carregar_config(referencia)
        if config:
            local.gravar_config(config)
            return _com_origem(config, "supabase", False)
        return None
    except remoto.ErroPersistencia:
        config = local.carregar_config(referencia)
        if config:
            warnings.warn(
                "Supabase indisponível; configuração carregada do cache local.",
                RuntimeWarning,
                stacklevel=2,
            )
            return _com_origem(config, "cache", True)
        raise


def salvar_config(config: dict[str, Any]) -> dict[str, Any]:
    """Valida, salva primeiro no Supabase e só então atualiza o cache."""
    validada = validar_config(config)
    versao = validada.get("versao") if validada.get("id") else None
    salva = remoto.salvar_config(validada, expected_version=versao)
    local.gravar_config(salva)
    return _com_origem(salva, "supabase", False)


def excluir_config(referencia: str) -> dict[str, Any]:
    """Executa exclusão lógica remota e retira a configuração do índice local."""
    config = carregar_config(referencia)
    if not config:
        raise remoto.ErroPersistencia("Configuração não encontrada.")
    excluida = remoto.excluir_config(config["id"], config.get("versao"))
    local.remover_config(config["slug"])
    return excluida


def definir_comando(
    referencia: str,
    comando: str,
    target_runner_id: str | None = None,
) -> dict[str, Any]:
    """Sincroniza o comando e mantém cache para operação degradada."""
    config = _config_para_operacao(referencia)
    comando = _validar_comando(comando)
    if target_runner_id is not None:
        target_runner_id = _texto(
            target_runner_id, "Identificador do executor", 1, 200
        )
    controle = {
        "bot_id": config["id"],
        "comando": comando,
        "target_runner_id": target_runner_id,
        "atualizado_em": _agora(),
        "sincronizado": False,
    }
    try:
        salvo = remoto.definir_comando(
            config["id"], comando, target_runner_id
        )
        controle.update(
            {
                "comando": salvo["command"],
                "target_runner_id": salvo.get("target_runner_id"),
                "request_id": salvo.get("request_id"),
                "requested_at": salvo.get("requested_at"),
                "acknowledged_at": salvo.get("acknowledged_at"),
                "criado_em": salvo.get("created_at"),
                "atualizado_em": salvo.get("updated_at"),
                "sincronizado": True,
            }
        )
    except remoto.ErroPersistencia:
        warnings.warn(
            "Supabase indisponível; comando mantido somente no cache local.",
            RuntimeWarning,
            stacklevel=2,
        )
    local.gravar_controle(config["slug"], controle)
    return controle


def ler_comando(referencia: str) -> dict[str, Any] | None:
    """Lê o comando remoto e usa o cache local em indisponibilidade."""
    config = _config_para_operacao(referencia)
    pendente = local.ler_controle(config["slug"])
    try:
        if pendente and not pendente.get("sincronizado", False):
            salvo = remoto.definir_comando(
                config["id"],
                pendente["comando"],
                pendente.get("target_runner_id"),
            )
        else:
            salvo = remoto.ler_comando(config["id"])
        if not salvo:
            return None
        controle = {
            "bot_id": salvo["bot_id"],
            "comando": salvo["command"],
            "target_runner_id": salvo.get("target_runner_id"),
            "request_id": salvo.get("request_id"),
            "requested_at": salvo.get("requested_at"),
            "acknowledged_at": salvo.get("acknowledged_at"),
            "criado_em": salvo.get("created_at"),
            "atualizado_em": salvo.get("updated_at"),
            "sincronizado": True,
        }
        local.gravar_controle(config["slug"], controle)
        return controle
    except remoto.ErroPersistencia:
        controle = local.ler_controle(config["slug"])
        if controle:
            controle = dict(controle)
            controle["sincronizado"] = False
            warnings.warn(
                "Supabase indisponível; comando lido do cache local.",
                RuntimeWarning,
                stacklevel=2,
            )
        return controle


def registrar_runtime(
    referencia: str, pid: int | None = None, processo: str = "bot"
) -> dict[str, Any]:
    """Registra somente o PID local; nenhum runtime é enviado ao Supabase."""
    config = _config_para_operacao(referencia)
    pid = os.getpid() if pid is None else pid
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ErroValidacao("PID deve ser um número inteiro positivo.")
    runtime = {"pid": pid, "processo": processo, "registrado_em": _agora()}
    local.gravar_runtime(config["slug"], runtime, processo)
    return runtime


def ler_runtime(
    referencia: str, processo: str = "bot"
) -> dict[str, Any] | None:
    """Consulta exclusivamente o runtime local."""
    config = _config_para_operacao(referencia)
    return local.ler_runtime(config["slug"], processo)


def remover_runtime(referencia: str, processo: str = "bot") -> None:
    """Remove o registro local quando o processo termina."""
    config = local.carregar_config(referencia)
    if config:
        local.remover_runtime(config["slug"], processo)


def validar_config(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise ErroValidacao("A configuração deve ser um objeto.")
    dados = {chave: valor for chave, valor in config.items() if not chave.startswith("_")}
    dados["nome"] = _texto(dados.get("nome"), "Nome", 2, 120)
    dados["slug"] = _validar_slug(dados.get("slug") or _slugificar(dados["nome"]))
    if dados.get("id") is not None:
        dados["id"] = _uuid(dados["id"], "ID da configuração")
    if dados.get("lead_owner_id") not in (None, ""):
        dados["lead_owner_id"] = _uuid(dados["lead_owner_id"], "ID do responsável")
    else:
        dados["lead_owner_id"] = None
    email = _texto(dados.get("owner_email"), "E-mail do responsável", 3, 254)
    if not _EMAIL.fullmatch(email):
        raise ErroValidacao("E-mail do responsável inválido.")
    dados["owner_email"] = email.casefold()
    dados["termo_busca"] = _texto(dados.get("termo_busca"), "Termo de busca", 1, 200)
    dados["nicho"] = _texto(dados.get("nicho"), "Nicho", 1, 120)
    dados["cidades"] = _lista(dados.get("cidades"), "Cidades", obrigatoria=True)
    dados["palavras_excluidas"] = _lista(
        dados.get("palavras_excluidas", []), "Palavras excluídas"
    )
    dados["palavras_incluidas"] = _lista(
        dados.get("palavras_incluidas", []), "Palavras incluídas"
    )
    sobrepostas = set(dados["palavras_excluidas"]) & set(dados["palavras_incluidas"])
    if sobrepostas:
        raise ErroValidacao("Uma palavra não pode estar nos dois filtros.")
    dados["minimo_avaliacoes"] = _inteiro(
        dados.get("minimo_avaliacoes", 0), "Mínimo de avaliações", 0
    )
    dados["max_scrolls"] = _inteiro(dados.get("max_scrolls", 10), "Máximo de rolagens", 1)
    dados["ticket_estimado"] = _ticket(dados.get("ticket_estimado"))
    if not isinstance(dados.get("headless", True), bool):
        raise ErroValidacao("Headless deve ser verdadeiro ou falso.")
    dados["headless"] = dados.get("headless", True)
    return dados


def _config_para_operacao(referencia: str) -> dict[str, Any]:
    # Processos ativos usam primeiro o cache para evitar uma consulta de
    # configuração a cada leitura do comando remoto.
    config = local.carregar_config(referencia) or carregar_config(referencia)
    if not config:
        raise remoto.ErroPersistencia("Configuração não encontrada.")
    if not config.get("id"):
        raise remoto.ErroPersistencia("Configuração local sem identificador remoto.")
    return config


def _texto(valor: Any, campo: str, minimo: int, maximo: int) -> str:
    if not isinstance(valor, str) or not minimo <= len(valor.strip()) <= maximo:
        raise ErroValidacao(f"{campo} deve ter entre {minimo} e {maximo} caracteres.")
    return valor.strip()


def _lista(valor: Any, campo: str, obrigatoria: bool = False) -> list[str]:
    if not isinstance(valor, (list, tuple)):
        raise ErroValidacao(f"{campo} deve ser uma lista.")
    itens = []
    for item in valor:
        texto = _texto(item, campo, 1, 120)
        if texto.casefold() not in {existente.casefold() for existente in itens}:
            itens.append(texto)
    if obrigatoria and not itens:
        raise ErroValidacao(f"{campo} deve conter ao menos um item.")
    return itens


def _inteiro(valor: Any, campo: str, minimo: int) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < minimo:
        raise ErroValidacao(f"{campo} deve ser inteiro maior ou igual a {minimo}.")
    return valor


def _ticket(valor: Any) -> float:
    try:
        ticket = Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        raise ErroValidacao("Ticket estimado deve ser numérico.") from None
    if not ticket.is_finite() or ticket < 0:
        raise ErroValidacao("Ticket estimado deve ser maior ou igual a zero.")
    return float(ticket.quantize(Decimal("0.01")))


def _uuid(valor: Any, campo: str) -> str:
    try:
        return str(UUID(str(valor)))
    except (ValueError, TypeError, AttributeError):
        raise ErroValidacao(f"{campo} deve ser um UUID válido.") from None


def _validar_slug(valor: str) -> str:
    if not isinstance(valor, str) or not _SLUG.fullmatch(valor):
        raise ErroValidacao("Slug deve conter letras minúsculas, números e hífens.")
    return valor


def _slugificar(valor: str) -> str:
    normalizado = unicodedata.normalize("NFKD", valor).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", normalizado.casefold()).strip("-")


def _validar_referencia(valor: str) -> None:
    if not isinstance(valor, str) or not valor.strip():
        raise ErroValidacao("Referência da configuração é obrigatória.")


def _validar_comando(valor: str) -> str:
    if not isinstance(valor, str) or not _COMANDO.fullmatch(valor):
        raise ErroValidacao("Comando inválido.")
    return valor


def _com_origem(config: dict[str, Any], fonte: str, fallback: bool) -> dict[str, Any]:
    resultado = dict(config)
    resultado["_persistencia"] = fonte
    resultado["_fallback_cache"] = fallback
    return resultado


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()
