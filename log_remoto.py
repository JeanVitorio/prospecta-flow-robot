"""Envia os logs do aplicativo ao Supabase para consulta do suporte."""

from __future__ import annotations

import atexit
import logging
import os
import re
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any

from app_version import __version__

# Bibliotecas de rede e navegador geram muito ruído (e o próprio envio geraria logs).
_IGNORADOS = {
    "asyncio",
    "gotrue",
    "h2",
    "hpack",
    "httpcore",
    "httpx",
    "postgrest",
    "realtime",
    "selenium",
    "storage3",
    "supabase",
    "urllib3",
    "websockets",
    "WDM",
}
_SEGREDOS = re.compile(
    r"eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]+"
    r"|sb_(?:secret|publishable)_[\w-]+"
    r"|sk_(?:live|test)_\w+"
    r"|(?i:bearer)\s+[\w.~+/=-]+"
)
_LIMITE_FILA = 2000
_TAMANHO_LOTE = 100
_INTERVALO_SEGUNDOS = 15
_ESPERA_AO_SAIR = 5

_handler: HandlerLogRemoto | None = None
_handler_lock = threading.Lock()


def instalar() -> HandlerLogRemoto:
    """Liga o envio no logger raiz deste processo (uma única vez)."""
    global _handler
    with _handler_lock:
        if _handler is None:
            _handler = HandlerLogRemoto()
            logging.getLogger().addHandler(_handler)
        return _handler


def handler_ativo() -> HandlerLogRemoto | None:
    """Handler do processo, para loggers que não propagam ao raiz."""
    return _handler


class HandlerLogRemoto(logging.Handler):
    """Guarda os registros em memória e envia em lotes numa thread separada."""

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self._fila: deque[dict[str, Any]] = deque(maxlen=_LIMITE_FILA)
        self._acordar = threading.Event()
        self._envio_lock = threading.Lock()
        threading.Thread(
            target=self._ciclo, name="log-remoto", daemon=True
        ).start()
        atexit.register(self._enviar_ao_sair)

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.split(".")[0] in _IGNORADOS:
            return
        try:
            mensagem = record.getMessage()
            if record.exc_info:
                mensagem += "\n" + logging.Formatter().formatException(
                    record.exc_info
                )
        except Exception:
            return
        self._fila.append(
            {
                "created_at": datetime.fromtimestamp(
                    record.created, timezone.utc
                ).isoformat(),
                "level": record.levelname,
                "logger": record.name[:120],
                "message": _SEGREDOS.sub("[oculto]", mensagem)[:4000],
            }
        )
        if len(self._fila) >= _TAMANHO_LOTE:
            self._acordar.set()

    def enviar(self) -> None:
        """Envia o que estiver na fila; em falha, devolve o lote para nova tentativa."""
        with self._envio_lock:
            while self._fila:
                lote = [
                    self._fila.popleft()
                    for _ in range(min(_TAMANHO_LOTE, len(self._fila)))
                ]
                if not _enviar_lote(lote):
                    self._fila.extendleft(reversed(lote))
                    return

    def _ciclo(self) -> None:
        while True:
            self._acordar.wait(_INTERVALO_SEGUNDOS)
            self._acordar.clear()
            self.enviar()

    def _enviar_ao_sair(self) -> None:
        # Sem internet o envio não pode segurar o fechamento do app.
        envio = threading.Thread(target=self.enviar, daemon=True)
        envio.start()
        envio.join(_ESPERA_AO_SAIR)


def _enviar_lote(lote: list[dict[str, Any]]) -> bool:
    try:
        from app_session import carregar_sessao

        if not carregar_sessao():
            # Sem login não há empresa para vincular os logs: descarta.
            return True
        import bot_repository

        bot_repository.obter_cliente().rpc(
            "prospecta_register_app_logs",
            {
                "p_runner_id": os.getenv("PROSPECTA_RUNNER_ID", "")[:200],
                "p_app_version": __version__,
                "p_entries": lote,
            },
        ).execute()
        return True
    except Exception:
        return False
