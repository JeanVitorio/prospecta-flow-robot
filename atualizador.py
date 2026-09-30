"""Atualização autenticada por hash para o aplicativo Windows."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from app_paths import data_path, is_frozen
from app_version import __version__


UPDATE_INTERVAL_SECONDS = 4 * 60 * 60
DEFAULT_UPDATE_URL = (
    "https://github.com/JeanVitorio/prospecta-flow-robot/"
    "releases/latest/download/version.json"
)
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    url: str
    sha256: str
    required: bool


class Atualizador:
    def __init__(self, logger: logging.Logger) -> None:
        self.log = logger
        self.metadata_url = os.getenv(
            "PROSPECTA_UPDATE_URL", DEFAULT_UPDATE_URL
        ).strip()
        self.next_check_at = 0.0

    def check_if_due(self) -> Path | None:
        now = time.monotonic()
        if now < self.next_check_at:
            return None
        self.next_check_at = now + UPDATE_INTERVAL_SECONDS
        if not is_frozen() and os.getenv("PROSPECTA_TEST_UPDATES") != "1":
            return None
        try:
            info = self._fetch_metadata()
            if _version_tuple(info.version) <= _version_tuple(__version__):
                return None
            installer = self._download(info)
            self.log.info(
                "Atualização %s validada e pronta para instalação.", info.version
            )
            return installer
        except Exception as error:
            self.log.warning("Não foi possível verificar atualizações: %s", error)
            return None

    def schedule_install(self, installer: Path) -> bool:
        """Agenda instalação após o runner encerrar e reinicia a versão nova."""
        if not is_frozen() or os.name != "nt" or not installer.is_file():
            return False
        app = Path(sys.executable).resolve()
        current_pid = os.getpid()
        quoted_installer = _powershell_quote(str(installer))
        quoted_app = _powershell_quote(str(app))
        script = (
            f"Wait-Process -Id {current_pid} -Timeout 60 "
            "-ErrorAction SilentlyContinue; "
            f"$p = Start-Process -FilePath {quoted_installer} "
            "-ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' "
            "-PassThru -Wait; "
            f"if ($p.ExitCode -eq 0) {{ Start-Process -FilePath {quoted_app} "
            "-ArgumentList '--runner' }}"
        )
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-Command",
                script,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        return True

    def _fetch_metadata(self) -> UpdateInfo:
        _require_https(self.metadata_url)
        request = Request(
            self.metadata_url,
            headers={
                "Accept": "application/json",
                "User-Agent": f"ProspectaFlow/{__version__}",
            },
        )
        with urlopen(request, timeout=15) as response:
            payload = json.load(response)
        version = str(payload.get("version", "")).strip()
        url = str(payload.get("url", "")).strip()
        sha256 = str(payload.get("sha256", "")).strip().casefold()
        if not _VERSION.fullmatch(version):
            raise ValueError("Versão remota inválida")
        _require_https(url)
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ValueError("Hash SHA-256 inválido")
        return UpdateInfo(version, url, sha256, bool(payload.get("required")))

    def _download(self, info: UpdateInfo) -> Path:
        destination = data_path(
            "updates", f"ProspectaFlowSetup-{info.version}.exe"
        )
        temporary = destination.with_suffix(".download")
        request = Request(
            info.url,
            headers={"User-Agent": f"ProspectaFlow/{__version__}"},
        )
        digest = hashlib.sha256()
        with urlopen(request, timeout=60) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest().casefold() != info.sha256:
            temporary.unlink(missing_ok=True)
            raise ValueError("Assinatura SHA-256 da atualização não confere")
        os.replace(temporary, destination)
        return destination


def _version_tuple(value: str) -> tuple[int, int, int]:
    if not _VERSION.fullmatch(value):
        raise ValueError("Versão inválida")
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def _require_https(value: str) -> None:
    if urlsplit(value).scheme != "https":
        raise ValueError("Atualização deve usar HTTPS")


def _powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
