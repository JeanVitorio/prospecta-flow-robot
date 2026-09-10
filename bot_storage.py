"""Cache local atômico de configurações, controles e runtime."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


_BASE = Path(__file__).resolve().parent / "dados_bots"
_INDICE = _BASE / "index.json"
_LOCK = threading.RLock()
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PROCESSO = re.compile(r"^[a-z][a-z0-9_-]{0,49}$")


def pasta_bot(slug: str) -> Path:
    """Retorna a pasta segura do bot, sem criá-la."""
    if not isinstance(slug, str) or not _SLUG.fullmatch(slug):
        raise ValueError("Slug inválido para armazenamento local.")
    return _BASE / slug


def gravar_config(config: dict[str, Any]) -> None:
    slug = config["slug"]
    with _LOCK:
        _gravar_json(pasta_bot(slug) / "config.json", config)
        indice = _ler_json(_INDICE, {"slugs": []})
        slugs = set(indice.get("slugs", []))
        slugs.add(slug)
        _gravar_json(_INDICE, {"slugs": sorted(slugs)})


def sincronizar_configs(configs: list[dict[str, Any]]) -> None:
    """Substitui o índice pela fotografia remota mais recente."""
    with _LOCK:
        indice_anterior = _ler_json(_INDICE, {"slugs": []})
        slugs_novos = {config["slug"] for config in configs}
        for config in configs:
            _gravar_json(pasta_bot(config["slug"]) / "config.json", config)
        for slug in set(indice_anterior.get("slugs", [])) - slugs_novos:
            try:
                (pasta_bot(slug) / "config.json").unlink()
            except FileNotFoundError:
                pass
        _gravar_json(_INDICE, {"slugs": sorted(slugs_novos)})


def listar_configs() -> list[dict[str, Any]]:
    with _LOCK:
        indice = _ler_json(_INDICE, {"slugs": []})
        slugs = indice.get("slugs", [])
        if not isinstance(slugs, list):
            slugs = []
        configs = []
        for slug in slugs:
            try:
                config = _ler_json(pasta_bot(slug) / "config.json", None)
                if isinstance(config, dict) and not config.get("excluido_em"):
                    configs.append(config)
            except (ValueError, OSError, json.JSONDecodeError):
                continue
        return sorted(configs, key=lambda item: item.get("nome", "").casefold())


def carregar_config(referencia: str) -> dict[str, Any] | None:
    if isinstance(referencia, str) and _SLUG.fullmatch(referencia):
        config = _ler_json(pasta_bot(referencia) / "config.json", None)
        if isinstance(config, dict) and not config.get("excluido_em"):
            return config
    for config in listar_configs():
        if config.get("id") == referencia:
            return config
    return None


def remover_config(slug: str) -> None:
    """Remove a configuração do índice sem apagar runtime ou outros artefatos."""
    with _LOCK:
        caminho = pasta_bot(slug) / "config.json"
        if caminho.exists():
            caminho.unlink()
        indice = _ler_json(_INDICE, {"slugs": []})
        slugs = [item for item in indice.get("slugs", []) if item != slug]
        _gravar_json(_INDICE, {"slugs": sorted(set(slugs))})


def gravar_controle(slug: str, controle: dict[str, Any]) -> None:
    _gravar_json(pasta_bot(slug) / "controle.json", controle)


def ler_controle(slug: str) -> dict[str, Any] | None:
    controle = _ler_json(pasta_bot(slug) / "controle.json", None)
    return controle if isinstance(controle, dict) else None


def gravar_runtime(
    slug: str, runtime: dict[str, Any], processo: str = "bot"
) -> None:
    _gravar_json(pasta_bot(slug) / _arquivo_runtime(processo), runtime)


def ler_runtime(slug: str, processo: str = "bot") -> dict[str, Any] | None:
    runtime = _ler_json(pasta_bot(slug) / _arquivo_runtime(processo), None)
    return runtime if isinstance(runtime, dict) else None


def remover_runtime(slug: str, processo: str = "bot") -> None:
    """Remove somente o runtime do processo informado."""
    try:
        (pasta_bot(slug) / _arquivo_runtime(processo)).unlink()
    except FileNotFoundError:
        pass


def _arquivo_runtime(processo: str) -> str:
    if not isinstance(processo, str) or not _PROCESSO.fullmatch(processo):
        raise ValueError("Nome de processo inválido.")
    return f"runtime_{processo}.json"


def gravar_checkpoint(
    slug: str, process_name: str, checkpoint: dict[str, Any]
) -> None:
    """Persiste atomicamente o checkpoint local de um processo."""
    _validar_processo(process_name)
    _gravar_json(
        pasta_bot(slug) / f"checkpoint_{process_name}.json",
        checkpoint,
    )


def ler_checkpoint(slug: str, process_name: str) -> dict[str, Any] | None:
    """Lê o checkpoint local sem criar arquivos ou diretórios."""
    _validar_processo(process_name)
    checkpoint = _ler_json(
        pasta_bot(slug) / f"checkpoint_{process_name}.json",
        None,
    )
    return checkpoint if isinstance(checkpoint, dict) else None


def adicionar_evento_pendente(slug: str, evento: dict[str, Any]) -> None:
    """Mantém eventos não sincronizados para reenvio sem duplicidade."""
    caminho = pasta_bot(slug) / "eventos_pendentes.json"
    with _LOCK:
        eventos = _ler_json(caminho, [])
        if not isinstance(eventos, list):
            eventos = []
        event_id = evento.get("event_id")
        if not any(item.get("event_id") == event_id for item in eventos):
            eventos.append(evento)
            _gravar_json(caminho, eventos)


def listar_eventos_pendentes(slug: str) -> list[dict[str, Any]]:
    eventos = _ler_json(pasta_bot(slug) / "eventos_pendentes.json", [])
    if not isinstance(eventos, list):
        return []
    return [item for item in eventos if isinstance(item, dict)]


def remover_evento_pendente(slug: str, event_id: str) -> None:
    caminho = pasta_bot(slug) / "eventos_pendentes.json"
    with _LOCK:
        eventos = listar_eventos_pendentes(slug)
        restantes = [
            item for item in eventos if item.get("event_id") != event_id
        ]
        if restantes:
            _gravar_json(caminho, restantes)
        else:
            try:
                caminho.unlink()
            except FileNotFoundError:
                pass


def _validar_processo(process_name: str) -> None:
    if not isinstance(process_name, str) or not re.fullmatch(
        r"[a-z][a-z0-9_-]{0,49}", process_name
    ):
        raise ValueError("Nome de processo inválido para armazenamento local.")


def _gravar_json(caminho: Path, dados: Any) -> None:
    """Grava em arquivo temporário e troca o destino atomicamente."""
    with _LOCK:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        descritor, temporario = tempfile.mkstemp(
            prefix=f".{caminho.name}.", suffix=".tmp", dir=caminho.parent
        )
        try:
            with os.fdopen(descritor, "w", encoding="utf-8", newline="\n") as arquivo:
                json.dump(dados, arquivo, ensure_ascii=False, indent=2)
                arquivo.write("\n")
                arquivo.flush()
                os.fsync(arquivo.fileno())
            for tentativa in range(8):
                try:
                    os.replace(temporario, caminho)
                    break
                except PermissionError:
                    if tentativa == 7:
                        raise
                    time.sleep(min(0.05 * (tentativa + 1), 0.25))
        except Exception:
            try:
                os.unlink(temporario)
            except FileNotFoundError:
                pass
            raise


def _ler_json(caminho: Path, padrao: Any) -> Any:
    for tentativa in range(8):
        try:
            with caminho.open("r", encoding="utf-8") as arquivo:
                return json.load(arquivo)
        except FileNotFoundError:
            return padrao
        except PermissionError:
            if tentativa == 7:
                raise
            time.sleep(min(0.05 * (tentativa + 1), 0.25))
    return padrao
