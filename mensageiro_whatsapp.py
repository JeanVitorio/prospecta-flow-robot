"""Motor agendado de mensagens iniciais pelo WhatsApp Web."""

from __future__ import annotations

import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import bot_repository
import message_repository as repositorio
from execucao_bot import criar_logger


DIAS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class ParadaMensageiro(Exception):
    """Indica encerramento solicitado pelo controle remoto."""


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


class MensageiroWhatsApp:
    """Executa uma campanha com envio único por lead e ritmo controlado."""

    def __init__(self, slug: str) -> None:
        config = repositorio.carregar_config(slug)
        if not config:
            raise RuntimeError(f"Bot de mensagens '{slug}' não encontrado.")
        self.config = config
        self.bot_id = str(config["id"])
        self.session_id = str(config["whatsapp_session_id"])
        self.runner_id = os.getenv("PROSPECTA_RUNNER_ID", "").strip()
        if not self.runner_id:
            raise RuntimeError("Executor remoto não identificado.")
        pasta = Path(__file__).resolve().parent / "dados_mensagens" / slug
        self.log = criar_logger(f"mensageiro_{slug}", pasta / "mensageiro.log")
        self.gateway = ClienteGateway()
        self.fuso = ZoneInfo("America/Sao_Paulo")
        self.proxima_consulta_controle = 0.0
        self.proximo_heartbeat = 0.0
        self.proximo_status_sessao = 0.0
        self.proximo_envio = 0.0
        self.ultimo_estado_sessao: tuple[Any, ...] | None = None
        self.gerador = random.SystemRandom()

    def executar(self) -> None:
        self._runtime("starting")
        try:
            self.gateway.conectar(self.session_id)
            self._aguardar_conexao()
            while True:
                self._verificar_controle()
                self._verificar_sessao()
                agora = datetime.now(self.fuso)
                if not dentro_da_agenda(
                    self.config.get("weekly_schedule") or {}, agora
                ):
                    self._runtime_periodico("outside_schedule")
                    self._esperar(30)
                    continue
                if time.monotonic() < self.proximo_envio:
                    self._runtime_periodico(
                        "running",
                        next_send_at=datetime.fromtimestamp(
                            time.time()
                            + self.proximo_envio
                            - time.monotonic(),
                            tz=timezone.utc,
                        ).isoformat(),
                    )
                    self._esperar(
                        min(10, self.proximo_envio - time.monotonic())
                    )
                    continue
                if repositorio.enviados_ultima_hora(self.bot_id) >= int(
                    self.config["max_messages_per_hour"]
                ):
                    self._runtime_periodico("hourly_limit")
                    self._esperar(60)
                    continue

                lead = repositorio.claim_lead(self.bot_id, self.runner_id)
                if not lead:
                    self._runtime_periodico("no_leads")
                    self._esperar(60)
                    continue
                self._processar_lead(lead)
                intervalo = self.gerador.randint(
                    int(self.config["min_interval_seconds"]),
                    int(self.config["max_interval_seconds"]),
                )
                self.proximo_envio = time.monotonic() + intervalo
        except ParadaMensageiro:
            self._runtime("stopped", next_send_at=None, current_lead_id=None)
        except Exception as erro:
            self.log.exception("Falha no motor de mensagens.")
            self._runtime(
                "failed",
                last_error=type(erro).__name__,
                current_lead_id=None,
            )
            raise

    def _aguardar_conexao(self) -> None:
        while True:
            self._verificar_controle()
            estado = self.gateway.status(self.session_id)
            forcar = time.monotonic() >= self.proximo_status_sessao
            self._sincronizar_sessao(estado, forcar=forcar)
            if forcar:
                self.proximo_status_sessao = time.monotonic() + 60
            if estado.get("status") == "ready":
                self._runtime("running", last_error=None)
                return
            if estado.get("status") == "error":
                raise RuntimeError("A sessão do WhatsApp falhou.")
            self._runtime_periodico("waiting_qr")
            self._esperar(5)

    def _processar_lead(self, lead: dict[str, Any]) -> None:
        delivery_id = int(lead["delivery_id"])
        claim_token = str(lead["claim_token"])
        self._runtime("running", current_lead_id=lead["lead_id"])
        mensagem = renderizar_mensagem(
            str(self.config["message_template"]), lead
        )
        try:
            resposta = self.gateway.enviar(
                self.session_id, str(lead["phone"]), mensagem
            )
            if not resposta.get("exists"):
                repositorio.finalizar_entrega(
                    delivery_id, claim_token, "invalid", "number_not_found"
                )
                self._runtime("running", current_lead_id=None)
                return
            if not resposta.get("sent"):
                repositorio.finalizar_entrega(
                    delivery_id, claim_token, "failed", "send_not_confirmed"
                )
                self._runtime("running", current_lead_id=None)
                return
            repositorio.finalizar_entrega(
                delivery_id, claim_token, "sent"
            )
            self._runtime(
                "running",
                current_lead_id=None,
                last_sent_at=datetime.now(timezone.utc).isoformat(),
                last_error=None,
            )
        except Exception as erro:
            repositorio.finalizar_entrega(
                delivery_id,
                claim_token,
                "failed",
                type(erro).__name__,
            )
            self._runtime(
                "running",
                current_lead_id=None,
                last_error=type(erro).__name__,
            )

    def _verificar_controle(self) -> None:
        agora = time.monotonic()
        if agora < self.proxima_consulta_controle:
            return
        controle = repositorio.ler_comando(self.bot_id) or {}
        self.proxima_consulta_controle = agora + 10
        destino = str(controle.get("target_runner_id") or "")
        if destino and destino != self.runner_id:
            raise ParadaMensageiro()
        comando = str(controle.get("command", "")).casefold()
        if comando == "parado":
            raise ParadaMensageiro()
        while comando == "pausado":
            self._runtime_periodico("paused")
            time.sleep(5)
            controle = repositorio.ler_comando(self.bot_id) or {}
            destino = str(controle.get("target_runner_id") or "")
            if destino and destino != self.runner_id:
                raise ParadaMensageiro()
            comando = str(controle.get("command", "")).casefold()
            if comando == "parado":
                raise ParadaMensageiro()

    def _verificar_sessao(self) -> None:
        if time.monotonic() < self.proximo_status_sessao:
            return
        estado = self.gateway.status(self.session_id)
        self._sincronizar_sessao(estado, forcar=True)
        self.proximo_status_sessao = time.monotonic() + 60
        if estado.get("status") != "ready":
            self.gateway.conectar(self.session_id)
            self._aguardar_conexao()

    def _sincronizar_sessao(
        self, estado: dict[str, Any], forcar: bool = False
    ) -> None:
        assinatura = (
            estado.get("status"),
            estado.get("qr_generated_at"),
            estado.get("connected_number"),
            estado.get("last_error"),
        )
        if not forcar and assinatura == self.ultimo_estado_sessao:
            return
        self.ultimo_estado_sessao = assinatura
        repositorio.atualizar_sessao(
            self.session_id,
            {
                "status": estado.get("status", "error"),
                "runner_id": self.runner_id,
                "connected_number": estado.get("connected_number"),
                "qr_code_data_url": estado.get("qr_code_data_url"),
                "qr_generated_at": estado.get("qr_generated_at"),
                "last_error": estado.get("last_error"),
                "last_seen_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def _runtime_periodico(self, status: str, **dados: Any) -> None:
        if time.monotonic() >= self.proximo_heartbeat:
            self._runtime(status, **dados)

    def _runtime(self, status: str, **dados: Any) -> None:
        repositorio.atualizar_runtime(
            self.bot_id,
            {
                "runner_id": self.runner_id,
                "status": status,
                "heartbeat_at": datetime.now(timezone.utc).isoformat(),
                **dados,
            },
        )
        self.proximo_heartbeat = time.monotonic() + 60

    def _esperar(self, segundos: float) -> None:
        fim = time.monotonic() + max(0, segundos)
        while time.monotonic() < fim:
            self._verificar_controle()
            time.sleep(max(0, min(1, fim - time.monotonic())))


def dentro_da_agenda(agenda: dict[str, Any], agora: datetime) -> bool:
    dia = agenda.get(DIAS[agora.weekday()])
    if not isinstance(dia, dict) or not dia.get("enabled"):
        return False
    inicio = _minutos(str(dia.get("start", "")))
    fim = _minutos(str(dia.get("end", "")))
    atual = agora.hour * 60 + agora.minute
    return inicio is not None and fim is not None and inicio <= atual < fim


def _minutos(valor: str) -> int | None:
    try:
        hora, minuto = (int(parte) for parte in valor.split(":", 1))
    except (TypeError, ValueError):
        return None
    if not 0 <= hora <= 23 or not 0 <= minuto <= 59:
        return None
    return hora * 60 + minuto


def renderizar_mensagem(modelo: str, lead: dict[str, Any]) -> str:
    valores = {
        "nome": str(lead.get("name") or ""),
        "empresa": str(lead.get("company") or ""),
        "nicho": str(lead.get("niche") or ""),
    }
    mensagem = modelo
    for chave, valor in valores.items():
        mensagem = mensagem.replace(f"{{{chave}}}", valor)
    return mensagem.strip()


def executar_mensageiro(slug: str) -> None:
    try:
        MensageiroWhatsApp(slug).executar()
    except bot_repository.ErroPersistencia:
        logging.getLogger("mensageiro_whatsapp").exception(
            "Supabase indisponível para o bot de mensagens."
        )
        raise
