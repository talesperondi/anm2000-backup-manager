"""Agendador interno: HH:MM + dias, com recuperacao de ocorrencias perdidas."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

WEEKDAY_LABELS = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]


def _days(weekdays: str) -> set[int]:
    days = {int(d) for d in str(weekdays).replace(" ", "").split(",") if d.isdigit()}
    return days or {1, 2, 3, 4, 5, 6, 7}


def _at_time(at_time: str) -> tuple[int, int] | None:
    try:
        hh, mm = [int(x) for x in str(at_time).split(":")[:2]]
    except (ValueError, AttributeError):
        return None
    if not (0 <= hh < 24 and 0 <= mm < 60):
        return None
    return hh, mm


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def next_occurrence(at_time: str, weekdays: str, after: datetime | None = None) -> datetime | None:
    """Proxima ocorrencia para 'HH:MM' e dias '1,2,3' (1=segunda ... 7=domingo)."""
    after = after or datetime.now()
    parsed = _at_time(at_time)
    if not parsed:
        return None
    hh, mm = parsed
    days = _days(weekdays)
    for offset in range(0, 15):
        day = (after + timedelta(days=offset)).date()
        if day.isoweekday() not in days:
            continue
        candidate = datetime.combine(day, datetime.min.time()).replace(hour=hh, minute=mm)
        if candidate > after:
            return candidate
    return None


def latest_occurrence(at_time: str, weekdays: str, at: datetime | None = None) -> datetime | None:
    """Ocorrencia mais recente que ja passou (inclusive hoje)."""
    at = at or datetime.now()
    parsed = _at_time(at_time)
    if not parsed:
        return None
    hh, mm = parsed
    days = _days(weekdays)
    for offset in range(0, 8):
        day = (at - timedelta(days=offset)).date()
        if day.isoweekday() not in days:
            continue
        candidate = datetime.combine(day, datetime.min.time()).replace(hour=hh, minute=mm)
        if candidate <= at:
            return candidate
    return None


class Scheduler(threading.Thread):
    """Thread que dispara callbacks quando um agendamento vence.

    `next_run_at` funciona como marcador persistente: se o PC estava desligado
    no horario, a ocorrencia continua vencida e dispara uma unica vez quando o
    gerenciador voltar (catch-up). Depois de disparar, o marcador avanca.
    """

    def __init__(self, db, on_due, is_busy, interval: float = 20.0,
                 catch_up: bool = True) -> None:
        super().__init__(daemon=True, name="anm-scheduler")
        self.db = db
        self.on_due = on_due
        self.is_busy = is_busy
        self.interval = interval
        self.catch_up = catch_up
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        self._safe_tick()
        while not self._stop.wait(self.interval):
            self._safe_tick()

    def _safe_tick(self) -> None:
        try:
            self._tick()
        except Exception:
            pass

    def _tick(self) -> None:
        now = datetime.now()
        for row in self.db.schedules():
            if not row["enabled"]:
                continue
            due = parse_dt(row["next_run_at"])
            if due is None:
                # sem marcador (agendamento antigo): apenas agenda o futuro
                nxt = next_occurrence(row["at_time"], row["weekdays"], now)
                self.db.set_schedule_run(
                    row["id"], row["last_run_at"] or "",
                    nxt.isoformat(timespec="seconds") if nxt else "")
                continue

            last = parse_dt(row["last_run_at"])
            if last and last >= due:
                # ocorrencia ja executada; so corrige o marcador
                nxt = next_occurrence(row["at_time"], row["weekdays"], now)
                self.db.set_schedule_run(
                    row["id"], row["last_run_at"],
                    nxt.isoformat(timespec="seconds") if nxt else "")
                continue

            if due > now:
                continue
            if self.is_busy():
                # tenta de novo no proximo ciclo; nada e marcado como executado
                continue
            if not self.catch_up:
                latest = latest_occurrence(row["at_time"], row["weekdays"], now)
                if not latest or due < latest:
                    # perdeu a janela: pula para a proxima, sem recuperar
                    nxt = next_occurrence(row["at_time"], row["weekdays"], now)
                    self.db.set_schedule_run(
                        row["id"], now.isoformat(timespec="seconds"),
                        nxt.isoformat(timespec="seconds") if nxt else "")
                    continue

            nxt = next_occurrence(row["at_time"], row["weekdays"], now)
            self.db.set_schedule_run(
                row["id"], now.isoformat(timespec="seconds"),
                nxt.isoformat(timespec="seconds") if nxt else "")
            payload = dict(row)
            payload["catch_up"] = (now - due).total_seconds() > 120
            payload["due_at"] = due.isoformat(timespec="seconds")
            self.on_due(payload)
