"""Infraestrutura comum de execução, controle e checkpoint dos motores."""

from __future__ import annotations

import ctypes
import logging
import os
import platform
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import bot_config
import bot_repository as remoto
import bot_storage as local


class ParadaSolicitada(Exception):
    """Indica uma parada segura solicitada pelo controle do bot."""


def agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def criar_logger(nome: str, caminho: Path) -> logging.Logger:
    """Cria logger local sem incluir configuração ou credenciais."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(nome)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers.clear()
    formato = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    for handler in (
        logging.StreamHandler(),
        logging.FileHandler(caminho, encoding="utf-8"),
    ):
        handler.setFormatter(formato)
        logger.addHandler(handler)
    return logger


class CheckpointExecucao:
    """Coordena estado local atômico e lease remoto versionado."""

    def __init__(
        self,
        config: dict[str, Any],
        process_name: str,
        logger: logging.Logger,
        lease_seconds: int = 300,
    ):
        self.config = config
        self.slug = config["slug"]
        self.bot_id = config["id"]
        self.process_name = process_name
        self.log = logger
        self.lease_seconds = lease_seconds
        self.runner_id = str(uuid4())
        self.executor_id = os.getenv(
            "PROSPECTA_RUNNER_ID", platform.node() or "executor-local"
        )
        self.version: int | None = None
        self.com_lease = False
        self.estado: dict[str, Any] = {}
        self._status_atual = "starting"
        self._lock = threading.RLock()
        self._parar_heartbeat = threading.Event()
        self._thread_heartbeat: threading.Thread | None = None

    def adquirir(self) -> dict[str, Any]:
        """Adquire o lease e escolhe o estado mais recente disponível."""
        local_atual = local.ler_checkpoint(self.slug, self.process_name)
        estado_local = self._estado_envelope(local_atual)
        estado_remoto: dict[str, Any] = {}
        try:
            registro = remoto.claim_checkpoint(
                self.bot_id,
                self.process_name,
                self.runner_id,
                self.lease_seconds,
            )
            self.version = registro.get("version")
            self.com_lease = True
            estado_remoto = registro.get("state") or {}
        except remoto.ConflitoVersao:
            self.log.error(
                "O processo já possui um executor com lease remoto ativo."
            )
            raise
        except remoto.ErroPersistencia as erro:
            self.log.warning(
                "Checkpoint remoto indisponível na aquisição; usando estado local: %s",
                erro,
            )
        self.estado = self._mais_recente(estado_local, estado_remoto)
        self.estado["executor"] = {
            "id": self.executor_id,
            "hostname": platform.node(),
            "ambiente": os.getenv("PROSPECTA_RUNNER_ENV", "local"),
            "pid": os.getpid(),
            "processo": self.process_name,
        }
        self.estado.setdefault("iniciado_em", agora_iso())
        self._gravar_local("running")
        return self.estado

    def iniciar_heartbeat(self, intervalo: int = 20) -> None:
        """Mantém o estado remoto vivo mesmo durante operações longas."""
        if self._thread_heartbeat and self._thread_heartbeat.is_alive():
            return
        self._parar_heartbeat.clear()

        def manter_vivo() -> None:
            while not self._parar_heartbeat.wait(intervalo):
                try:
                    self.salvar(self._status_atual)
                except Exception as erro:
                    self.log.warning("Falha temporária no heartbeat: %s", erro)

        self._thread_heartbeat = threading.Thread(
            target=manter_vivo,
            name=f"heartbeat-{self.slug}-{self.process_name}",
            daemon=True,
        )
        self._thread_heartbeat.start()

    def parar_heartbeat(self) -> None:
        self._parar_heartbeat.set()
        if (
            self._thread_heartbeat
            and self._thread_heartbeat.is_alive()
            and self._thread_heartbeat is not threading.current_thread()
        ):
            self._thread_heartbeat.join(timeout=3)

    def salvar(self, status: str = "running") -> None:
        """Salva local primeiro e tenta renovar o lease no Supabase."""
        with self._lock:
            self._status_atual = status
            self.estado["status"] = status
            self.estado["heartbeat_em"] = agora_iso()
            self.estado["checkpoint_salvo_em"] = agora_iso()
            self._gravar_local(status)
            try:
                if not self.com_lease:
                    registro = remoto.claim_checkpoint(
                        self.bot_id,
                        self.process_name,
                        self.runner_id,
                        self.lease_seconds,
                    )
                    self.version = registro.get("version")
                    self.com_lease = True
                registro = remoto.save_checkpoint(
                    self.bot_id,
                    self.process_name,
                    self.runner_id,
                    self.estado,
                    status=status,
                    expected_version=self.version,
                    lease_seconds=self.lease_seconds,
                )
                self.version = registro.get("version")
                self._gravar_local(status, sincronizado=True)
                self._sincronizar_eventos_pendentes()
            except remoto.ErroPersistencia as erro:
                self.com_lease = False
                self._gravar_local(status, erro_remoto=str(erro))
                self.log.warning(
                    "Checkpoint preservado localmente; falha na sincronização remota: %s",
                    erro,
                )

    def liberar(self, status: str = "idle") -> None:
        """Persiste o estado final e libera o lease quando disponível."""
        self.parar_heartbeat()
        self.salvar(status)
        if not self.com_lease:
            return
        try:
            registro = remoto.release_checkpoint(
                self.bot_id,
                self.process_name,
                self.runner_id,
                status=status,
                expected_version=self.version,
            )
            self.version = registro.get("version")
            self.com_lease = False
            self._gravar_local(status, sincronizado=True)
        except remoto.ErroPersistencia as erro:
            self._gravar_local(status, erro_remoto=str(erro))
            self.log.warning("Não foi possível liberar o lease remoto: %s", erro)

    def registrar_evento(
        self,
        tipo: str,
        mensagem: str,
        dados: dict[str, Any] | None = None,
        nivel: str = "info",
    ) -> None:
        """Registra um evento operacional sem interromper o motor em caso de falha."""
        evento = {
            "event_id": str(uuid4()),
            "bot_id": self.bot_id,
            "process_name": self.process_name,
            "runner_id": self.executor_id,
            "event_type": tipo,
            "message": mensagem,
            "data": dados or {},
            "level": nivel,
        }
        try:
            self._sincronizar_eventos_pendentes()
            remoto.registrar_evento(**evento)
        except remoto.ErroPersistencia as erro:
            try:
                local.adicionar_evento_pendente(self.slug, evento)
            except (OSError, ValueError):
                self.log.warning("Evento também não pôde ser preservado localmente.")
            self.log.warning("Evento remoto não sincronizado: %s", erro)

    def _sincronizar_eventos_pendentes(self) -> None:
        try:
            eventos = local.listar_eventos_pendentes(self.slug)
        except (OSError, ValueError):
            return
        for evento in eventos:
            try:
                remoto.registrar_evento(**evento)
                local.remover_evento_pendente(
                    self.slug, str(evento["event_id"])
                )
            except (remoto.ErroPersistencia, KeyError, OSError, ValueError):
                return

    def _gravar_local(
        self,
        status: str,
        sincronizado: bool = False,
        erro_remoto: str | None = None,
    ) -> None:
        envelope = {
            "bot_id": self.bot_id,
            "process_name": self.process_name,
            "runner_id": self.runner_id,
            "version": self.version,
            "status": status,
            "state": self.estado,
            "sincronizado": sincronizado,
            "atualizado_em": agora_iso(),
        }
        if erro_remoto:
            envelope["erro_remoto"] = erro_remoto
        local.gravar_checkpoint(self.slug, self.process_name, envelope)

    @staticmethod
    def _estado_envelope(envelope: dict[str, Any] | None) -> dict[str, Any]:
        estado = envelope.get("state") if isinstance(envelope, dict) else None
        return dict(estado) if isinstance(estado, dict) else {}

    @staticmethod
    def _mais_recente(
        estado_local: dict[str, Any], estado_remoto: dict[str, Any]
    ) -> dict[str, Any]:
        if not estado_local:
            return dict(estado_remoto)
        if not estado_remoto:
            return dict(estado_local)
        marca_local = str(estado_local.get("checkpoint_salvo_em", ""))
        marca_remota = str(estado_remoto.get("checkpoint_salvo_em", ""))
        return dict(estado_local if marca_local > marca_remota else estado_remoto)


class ControleExecucao:
    """Interpreta o dicionário retornado por bot_config.ler_comando."""

    def __init__(
        self,
        slug: str,
        checkpoint: CheckpointExecucao,
        logger: logging.Logger,
    ):
        self.slug = slug
        self.checkpoint = checkpoint
        self.log = logger
        self._comando = "rodando"
        self._proxima_consulta_remota = 0.0

    def verificar(self) -> None:
        # O cache local torna os botões do painel imediatos. O Supabase é
        # consultado em intervalo controlado para não sobrecarregar a API.
        controle_local = local.ler_controle(self.slug) or {}
        self._comando = str(
            controle_local.get("comando", self._comando)
        ).casefold()
        agora = time.monotonic()
        if agora >= self._proxima_consulta_remota:
            controle = bot_config.ler_comando(self.slug) or {}
            self._comando = str(
                controle.get("comando", self._comando)
            ).casefold()
            self._proxima_consulta_remota = agora + 2
        comando = self._comando
        if comando == "parado":
            self.checkpoint.salvar("stopped")
            self.checkpoint.registrar_evento(
                "parada_solicitada", "Parada solicitada ao processo."
            )
            raise ParadaSolicitada()
        if comando != "pausado":
            return
        self.log.info("Execução pausada pelo controle do bot.")
        self.checkpoint.salvar("paused")
        self.checkpoint.registrar_evento(
            "execucao_pausada", "Execução pausada pelo controle remoto."
        )
        proxima_renovacao = time.monotonic() + 60
        while comando == "pausado":
            time.sleep(1)
            controle_local = local.ler_controle(self.slug) or {}
            comando = str(
                controle_local.get("comando", comando)
            ).casefold()
            agora = time.monotonic()
            if agora >= self._proxima_consulta_remota:
                controle = bot_config.ler_comando(self.slug) or {}
                comando = str(controle.get("comando", comando)).casefold()
                self._proxima_consulta_remota = agora + 2
            self._comando = comando
            if time.monotonic() >= proxima_renovacao:
                self.checkpoint.salvar("paused")
                proxima_renovacao = time.monotonic() + 60
        if comando == "parado":
            self.checkpoint.salvar("stopped")
            self.checkpoint.registrar_evento(
                "parada_solicitada", "Parada solicitada durante a pausa."
            )
            raise ParadaSolicitada()
        self.checkpoint.salvar("running")
        self.checkpoint.registrar_evento(
            "execucao_retomada", "Execução retomada pelo controle remoto."
        )
        self.log.info("Execução retomada.")

    def esperar(self, segundos: float) -> None:
        fim = time.monotonic() + segundos
        while time.monotonic() < fim:
            self.verificar()
            time.sleep(min(0.5, max(0.0, fim - time.monotonic())))


def bloquear_energia() -> None:
    """Impede suspensão do Windows durante uma execução ativa."""
    if os.name == "nt":
        ctypes.windll.kernel32.SetThreadExecutionState(
            0x80000000 | 0x00000001 | 0x00000002
        )


def liberar_energia() -> None:
    """Restaura a política normal de energia da thread no Windows."""
    if os.name == "nt":
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
