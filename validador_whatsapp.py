"""Validação dos telefones no WhatsApp Web antes de salvar os leads."""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from pathlib import Path

import bot_repository
import message_repository as repositorio
from message_repository import FINALIDADE_VALIDACAO
from whatsapp_gateway_client import ClienteGateway


def normalizar_telefone(valor: str) -> str:
    """Mesma regra do gateway: DDI 55 implícito e 12 a 15 dígitos."""
    digitos = re.sub(r"\D", "", str(valor or ""))
    if len(digitos) in (10, 11):
        digitos = f"55{digitos}"
    if len(digitos) < 12 or len(digitos) > 15:
        return ""
    return digitos


class ValidadorWhatsApp:
    """Consulta o WhatsApp conectado neste executor e memoriza o resultado."""

    INTERVALO_MINIMO = 1.0
    INTERVALO_MAXIMO = 3.0

    def __init__(self, pasta: Path, log: logging.Logger) -> None:
        self.arquivo = pasta / "validacao_whatsapp.json"
        self.log = log
        self.cache = self._carregar_cache()
        self.cache_alterado = False
        self.gateway: ClienteGateway | None = None
        self.session_id: str | None = None
        self.gerador = random.SystemRandom()

    def validar(self, telefone: str) -> bool | None:
        """True/False quando confirmado; None se o WhatsApp estiver indisponível."""
        numero = normalizar_telefone(telefone)
        if not numero:
            return False
        if numero in self.cache:
            return self.cache[numero]
        if not self._preparar():
            return None
        assert self.gateway is not None and self.session_id is not None
        try:
            resposta = self.gateway.validar(self.session_id, numero)
        except RuntimeError as erro:
            self.log.warning("Validação no WhatsApp indisponível: %s", erro)
            self.session_id = None
            return None
        if "exists" not in resposta:
            return None
        existe = bool(resposta["exists"])
        self.cache[numero] = existe
        self.cache_alterado = True
        # Ritmo humano entre consultas para reduzir risco de bloqueio do número.
        time.sleep(
            self.gerador.uniform(self.INTERVALO_MINIMO, self.INTERVALO_MAXIMO)
        )
        return existe

    def salvar_cache(self) -> None:
        if not self.cache_alterado:
            return
        temporario = self.arquivo.with_suffix(".tmp")
        temporario.write_text(json.dumps(self.cache), encoding="utf-8")
        temporario.replace(self.arquivo)
        self.cache_alterado = False

    def _preparar(self) -> bool:
        if self.session_id:
            return True
        if self.gateway is None:
            try:
                self.gateway = ClienteGateway()
            except RuntimeError:
                self.log.warning(
                    "Gateway WhatsApp indisponível; leads aguardando validação."
                )
                return False
        runner_id = os.getenv("PROSPECTA_RUNNER_ID", "").strip()
        if not runner_id:
            return False
        try:
            sessoes = repositorio.listar_sessoes_runner(runner_id)
        except bot_repository.ErroPersistencia:
            return False
        # Só usa sessões já autenticadas; a de validação tem prioridade.
        conectadas = sorted(
            (sessao for sessao in sessoes if sessao.get("status") == "ready"),
            key=lambda sessao: sessao.get("purpose") != FINALIDADE_VALIDACAO,
        )
        for sessao in conectadas:
            session_id = str(sessao.get("id") or "")
            if self._sessao_pronta(session_id):
                self.session_id = session_id
                return True
        self.log.warning(
            "Nenhum WhatsApp conectado neste PC; conecte o WhatsApp de "
            "validação na página Agentes de Prospecção."
        )
        return False

    def _sessao_pronta(self, session_id: str) -> bool:
        assert self.gateway is not None
        try:
            estado = self.gateway.status(session_id)
        except RuntimeError:
            # Gateway reiniciado: o login salvo é restaurado sem novo QR Code.
            try:
                estado = self.gateway.conectar(session_id)
            except RuntimeError:
                return False
        return estado.get("status") == "ready"

    def _carregar_cache(self) -> dict[str, bool]:
        try:
            dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(dados, dict):
            return {}
        return {str(chave): bool(valor) for chave, valor in dados.items()}
