"""Mantém conectado o WhatsApp usado para validar os números dos leads."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import bot_repository
import message_repository as repositorio
from whatsapp_gateway_client import ClienteGateway

CAMPOS_SINCRONIZADOS = (
    "status",
    "connected_number",
    "qr_code_data_url",
    "last_error",
)


class SincronizadorValidacao:
    """Conecta as sessões de validação deste executor e publica o QR Code."""

    TEMPO_LIMITE_QR = 180.0
    STATUS_DESEJADOS = {"connecting", "qr_pending", "ready"}
    MENSAGEM_QR_EXPIRADO = (
        "O QR Code expirou. Clique em Conectar para gerar outro."
    )

    def __init__(self, log: logging.Logger) -> None:
        self.log = log
        self.gateway: ClienteGateway | None = None
        self.conhecidas: set[str] = set()
        self.qr_desde: dict[str, float] = {}
        # Sessões já reiniciadas no pedido atual (evita reiniciar em laço).
        self.reiniciadas: set[str] = set()

    def sincronizar(self, runner_id: str) -> bool:
        """Retorna True enquanto alguma sessão aguarda leitura do QR Code."""
        if self.gateway is None:
            try:
                self.gateway = ClienteGateway()
            except RuntimeError:
                return False
        # Falhas aqui não podem interromper o restante do ciclo do executor.
        try:
            sessoes = repositorio.listar_sessoes_validacao(runner_id)
        except bot_repository.ErroPersistencia as erro:
            self.log.debug("Sessões de validação indisponíveis: %s", erro)
            return False
        atuais = {str(sessao["id"]) for sessao in sessoes}
        # Sessão removida na Web: encerra o login salvo neste PC.
        for removida in self.conhecidas - atuais:
            self._desconectar(removida)
        self.conhecidas = atuais
        aguardando = False
        for sessao in sessoes:
            try:
                aguardando = self._sincronizar_sessao(sessao) or aguardando
            except bot_repository.ErroPersistencia as erro:
                self.log.warning("Falha ao salvar o WhatsApp de validação: %s", erro)
        return aguardando

    def _sincronizar_sessao(self, sessao: dict[str, Any]) -> bool:
        session_id = str(sessao["id"])
        if sessao.get("status") not in self.STATUS_DESEJADOS:
            self.qr_desde.pop(session_id, None)
            return False
        try:
            estado = self._estado_gateway(sessao)
        except RuntimeError as erro:
            self.log.warning("WhatsApp de validação indisponível: %s", erro)
            return False
        status = estado.get("status")
        if status == "qr_pending":
            inicio = self.qr_desde.setdefault(session_id, time.monotonic())
            if time.monotonic() - inicio > self.TEMPO_LIMITE_QR:
                self._desconectar(session_id)
                estado = {
                    "status": "disconnected",
                    "last_error": self.MENSAGEM_QR_EXPIRADO,
                }
                status = "disconnected"
        else:
            self.qr_desde.pop(session_id, None)
        if status in ("ready", "disconnected", "error"):
            self.reiniciadas.discard(session_id)
        self._gravar(sessao, estado)
        return status in ("connecting", "qr_pending")

    def _estado_gateway(self, sessao: dict[str, Any]) -> dict[str, Any]:
        assert self.gateway is not None
        session_id = str(sessao["id"])
        try:
            estado = self.gateway.status(session_id)
        except RuntimeError as erro:
            if "não foi iniciada" not in str(erro):
                raise
            return self.gateway.conectar(session_id)
        # Novo pedido de conexão na Web (status "connecting" sem erro anterior)
        # reinicia uma sessão que tinha caído no gateway.
        if (
            estado.get("status") in ("disconnected", "error")
            and sessao.get("status") == "connecting"
            and not sessao.get("last_error")
            and session_id not in self.reiniciadas
        ):
            self.reiniciadas.add(session_id)
            return self.gateway.conectar(session_id)
        return estado

    def _gravar(self, sessao: dict[str, Any], estado: dict[str, Any]) -> None:
        dados = {campo: estado.get(campo) for campo in CAMPOS_SINCRONIZADOS}
        if all(sessao.get(campo) == dados[campo] for campo in dados):
            return
        dados["last_seen_at"] = datetime.now(timezone.utc).isoformat()
        repositorio.atualizar_sessao(str(sessao["id"]), dados)

    def _desconectar(self, session_id: str) -> None:
        self.qr_desde.pop(session_id, None)
        if self.gateway is None:
            return
        try:
            self.gateway.desconectar(session_id)
        except RuntimeError as erro:
            self.log.warning("Falha ao desconectar o WhatsApp: %s", erro)
