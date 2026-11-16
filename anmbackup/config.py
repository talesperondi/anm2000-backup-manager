"""Configuracao persistida em SQLite (sem credenciais).

O ANM2000 e usado ja autenticado: nenhuma senha e armazenada em lugar algum.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

APP_NAME = "ANM2000_BackupManager"
APP_FOLDER = "ANM2000BackupManager"
LEGACY_VENDOR = "CHNET"
LEGACY_FOLDER = "ANM2000_BackupManager"

DEFAULTS: dict[str, object] = {
    "root_dir": r"C:\ANM2000",
    #lista vazia = descobrir todas as OLTs da arvore automaticamente
    "olts": [],
    "flash_enabled": True,
    "export_enabled": True,
    "flash_timeout_s": 300,
    "export_timeout_s": 300,
    "confirm_export_min_files": 50,
    "confirm_export_min_main_mb": 1.0,
    "confirm_export_require_configtable": True,
    "min_free_mb": 500,
    "retain_log_days": 365,
    "retain_runs_days": 0,          # 0 = nunca apagar historico
    "schedules_enabled": False,
    # resilience / inicializacao
    "anm_exe": "",                  # vazio = detectar automaticamente
    "anm_workdir": "",
    "anm_autostart": True,          # abrir o cliente ANM se necessario
    "wait_for_anm_min": 60,         # espera por login do ANM em execucoes automaticas
    "catch_up_enabled": True,       # executar backup perdido quando o PC volta
}


def data_dir() -> Path:
    override = os.environ.get("ANM2000BM_DATA")
    if override:
        path = Path(override)
    else:
        base = Path(os.environ.get("LOCALAPPDATA") or str(Path.home()))
        path = base / APP_FOLDER
        legacy = base / LEGACY_VENDOR / LEGACY_FOLDER
        if not path.exists() and legacy.exists():
            # migra dados da versao anterior sem perder historico nem agendamentos
            try:
                shutil.move(str(legacy), str(path))
            except OSError:
                try:
                    shutil.copytree(legacy, path)
                except OSError:
                    path = legacy
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "manager.db"


def log_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


class Config:
    """Leitura/escrita de configuracoes tipadas sobre a tabela settings."""

    def __init__(self, db) -> None:
        self.db = db
        self._cache: dict[str, object] = {}
        self._load()

    def _load(self) -> None:
        with self.db.connect() as con:
            rows = con.execute("SELECT key, value FROM settings").fetchall()
        stored = {r["key"]: r["value"] for r in rows}
        for key, default in DEFAULTS.items():
            raw = stored.get(key)
            if raw is None:
                self._cache[key] = default
                continue
            self._cache[key] = self._decode(key, raw, default)

    @staticmethod
    def _decode(key: str, raw: str, default):
        if isinstance(default, bool):
            return raw.strip().lower() in ("1", "true", "yes", "on")
        if isinstance(default, int):
            return int(raw)
        if isinstance(default, float):
            return float(raw)
        if isinstance(default, (list, dict)):
            return json.loads(raw)
        return raw

    @staticmethod
    def _encode(value) -> str:
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def get(self, key: str):
        return self._cache.get(key, DEFAULTS.get(key))

    def set(self, key: str, value) -> None:
        if key not in DEFAULTS:
            raise KeyError(f"configuracao desconhecida: {key}")
        self._cache[key] = value
        with self.db.connect() as con:
            con.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, self._encode(value)),
            )

    def all(self) -> dict[str, object]:
        return dict(self._cache)

    # atalhos
    @property
    def root(self) -> Path:
        return Path(str(self.get("root_dir")))

    @property
    def flash_root(self) -> Path:
        return self.root / "OLT_FLASH"

    @property
    def export_root(self) -> Path:
        return self.root / "ANM2000_EXPORT"
