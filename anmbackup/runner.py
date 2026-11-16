"""Orquestracao das rotinas de backup (serializadas, com confirmacao real)."""

from __future__ import annotations

import os
import shutil
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path

from . import anm, autostart, config, db as dbmod

FLASH_LABEL = {"succeeded": "gravado no flash", "failed": "falhou",
               "overtime": "tempo esgotado no equipamento", "busy": "equipamento ocupado (EEPROM)",
               "no_privilege": "sem privilegio de operacao", "not_changed": "configuracao nao alterada",
               "cancelled": "cancelado", "inconclusive": "INCONCLUSIVO"}


class AlreadyRunning(RuntimeError):
    pass


class RunLock:
    """Lock de instancia unica para serializar todas as operacoes."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (config.data_dir() / "run.lock")
        self._fd: int | None = None

    def _stale(self) -> bool:
        try:
            raw = self.path.read_text(encoding="utf-8").split("|")
            pid = int(raw[0])
            started = float(raw[1])
        except Exception:
            return True
        if time.time() - started > 6 * 3600:
            return True
        try:
            os.kill(pid, 0)
            return False
        except OSError:
            return True

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self._fd, f"{os.getpid()}|{time.time()}".encode())
                return
            except FileExistsError:
                if self._stale():
                    try:
                        self.path.unlink()
                    except OSError:
                        pass
                    continue
                raise AlreadyRunning("outra execucao do gerenciador esta em andamento")
        raise AlreadyRunning("nao foi possivel obter o lock de execucao")

    def is_stale(self) -> bool:
        return self._stale()

    def release(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        try:
            self.path.unlink()
        except OSError:
            pass

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()


def recover_orphans(database: dbmod.Database, lock: RunLock | None = None) -> list[int]:
    """Fecha execucoes que ficaram 'running' apos queda/reinicio.

    Se houver um lock vivo (outra execucao real), nada e tocado.
    """
    if not (lock or RunLock()).is_stale():
        return []
    reason = "interrompida: o gerenciador ou o PC foi reiniciado durante a execucao"
    ids = database.abort_running(reason)
    if ids:
        database.log("warn", f"execucoes orfas recuperadas apos reinicio: {ids}")
        database.alert("warning", "Execucao interrompida",
                       f"{len(ids)} execucao(oes) sem conclusao apos reinicio: {ids}")
    return ids


class Runner:
    def __init__(self, database: dbmod.Database | None = None,
                 cfg: config.Config | None = None) -> None:
        self.db = database or dbmod.Database()
        self.cfg = cfg or config.Config(self.db)
        self.client = anm.AnmClient()
        self._run_id: int | None = None
        self.on_log = None            # callback(level, message) para a GUI
        self.on_progress = None       # callback(etapa, detalhe)

    # ---------------------------------------------------------------- logging
    def log(self, level: str, message: str) -> None:
        self.db.log(level, message, self._run_id)
        if self.on_log:
            try:
                self.on_log(level, message)
            except Exception:
                pass
        line = f"{datetime.now():%H:%M:%S} {level.upper():5} {message}"
        print(line, flush=True)
        try:
            logfile = config.log_dir() / f"manager_{datetime.now():%Y-%m}.log"
            with open(logfile, "a", encoding="utf-8") as fh:
                fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {level.upper():5} {message}\n")
        except OSError:
            pass

    # -------------------------------------------------------------- utilitarios
    def targets(self, only: list[str] | None = None) -> list[str]:
        snap = self.client.snap or self.client.connect()
        available = list(snap.olt_names)
        wanted = only or [str(x) for x in self.cfg.get("olts") or []]
        if not wanted:
            return available
        resolved = []
        for item in wanted:
            hit = [a for a in available if item.lower() in a.lower()]
            if not hit:
                raise anm.AnmError(f"OLT configurada nao encontrada na arvore: {item!r}")
            resolved.extend(hit)
        seen, out = set(), []
        for name in resolved:
            if name not in seen:
                seen.add(name)
                out.append(name)
        return out

    def _free_mb(self, path: Path) -> float:
        try:
            return shutil.disk_usage(path).free / (1024 * 1024)
        except OSError:
            return 0.0

    @staticmethod
    def unique_dir(base: Path) -> Path:
        if not base.exists():
            return base
        for n in range(2, 100):
            candidate = base.with_name(f"{base.name}_{n}")
            if not candidate.exists():
                return candidate
        raise RuntimeError(f"nao foi possivel gerar nome unico para {base}")

    # ------------------------------------------------------------------- run
    def run(self, *, do_flash: bool = True, do_export: bool = True,
            only: list[str] | None = None, dry_run: bool = False,
            kind: str = "manual", trigger: str = "manual",
            wait_for_anm: bool = False) -> dict:
        do_flash = do_flash and bool(self.cfg.get("flash_enabled"))
        do_export = do_export and bool(self.cfg.get("export_enabled"))
        if not do_flash and not do_export:
            raise ValueError("nada a executar: flash e export estao desativados")

        with RunLock():
            orphans = self.db.abort_running(
                "interrompida: nova execucao iniciada apos encerramento anormal")
            if orphans:
                self.db.log("warn", f"execucoes anteriores sem conclusao: {orphans}")
            self._run_id = self.db.start_run(kind, trigger)
            started = datetime.now()
            try:
                self.db.prune_logs(int(self.cfg.get("retain_log_days")))
                self.db.prune_runs(int(self.cfg.get("retain_runs_days")))
            except Exception:
                pass
            report: dict = {"run_id": self._run_id, "kind": kind, "dry_run": dry_run,
                            "flash": [], "export": None, "status": "running"}
            try:
                self._connect(wait_for_anm)
                self.log("info", f"ANM2000 conectado (pid {self.client.snap.pid})")
                targets = self.targets(only)
                report["targets"] = targets
                self.log("info", f"OLTs alvo ({len(targets)}): {targets}")

                if dry_run:
                    report["status"] = "dry_run"
                    self.db.finish_run(self._run_id, "dry_run",
                                       f"simulacao: {len(targets)} OLT(s), flash={do_flash}, export={do_export}")
                    return report

                self._check_space()
                if do_export:
                    # export primeiro: independe do estado do flash e valida o cliente
                    report["export"] = self._do_export()
                if do_flash:
                    for name in targets:
                        report["flash"].append(self._do_flash(name))

                report["status"] = self._overall(report, do_flash, do_export)
                self.db.finish_run(self._run_id, report["status"],
                                   self._summary(report, started))
                return report
            except Exception as exc:
                self.log("error", f"execucao abortada: {exc}")
                self.log("debug", traceback.format_exc())
                self.db.alert("critical", "Execucao abortada", str(exc), self._run_id)
                self.db.finish_run(self._run_id, "aborted", str(exc))
                report["status"] = "aborted"
                report["error"] = str(exc)
                return report

    def _connect(self, wait: bool) -> None:
        """Conecta ao ANM; em execucoes automaticas espera (e abre) o cliente."""
        try:
            self.client.connect()
            return
        except anm.AnmError as first:
            if not wait:
                raise

        minutes = int(self.cfg.get("wait_for_anm_min") or 0)
        if minutes <= 0:
            raise anm.AnmError(
                f"{first} (espera desativada; ajuste 'Espera pelo ANM' nas configuracoes)")
        self.log("warn", f"ANM2000 indisponivel: {first}")
        if self.cfg.get("anm_autostart"):
            started, message = autostart.launch_anm(self.cfg)
            self.log("info" if started else "debug", message)
        deadline = time.time() + minutes * 60
        last_note = 0.0
        while time.time() < deadline:
            time.sleep(10)
            try:
                self.client.connect()
                self.log("info", "ANM2000 disponivel; prosseguindo com a execucao agendada")
                return
            except anm.AnmError as exc:
                if time.time() - last_note >= 60:
                    last_note = time.time()
                    self.log("info", f"aguardando ANM2000 autenticado: {exc}")
        raise anm.AnmError(
            f"ANM2000 nao ficou disponivel em {minutes} min; "
            f"abra o cliente e faca login para o backup automatico")

    def _check_space(self) -> None:
        need = float(self.cfg.get("min_free_mb"))
        free = self._free_mb(Path(str(self.cfg.get("root_dir"))))
        if free < need:
            raise RuntimeError(f"espaco livre insuficiente em {self.cfg.get('root_dir')}: "
                               f"{free:.0f} MB (minimo {need:.0f} MB)")
        self.log("info", f"espaco livre: {free/1024:.1f} GB")

    # ------------------------------------------------------------------ flash
    def _do_flash(self, olt: str) -> dict:
        t0 = datetime.now()
        day_dir = self.cfg.flash_root / t0.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)   # sem arquivos: o flash nao gera artefato local

        self.log("info", f"[flash] {olt}")
        result = self.client.save_config_to_flash(olt, float(self.cfg.get("flash_timeout_s")),
                                                  log=self.log)
        item = {"olt": olt, "operation": "flash", "status": result["status"],
                "detail": result["detail"], "seconds": result.get("seconds"),
                "started": t0.isoformat(timespec="seconds"),
                "finished": datetime.now().isoformat(timespec="seconds")}
        self.db.add_item(self._run_id, "flash", olt, result["status"],
                         result["detail"], result.get("seconds"),
                         started_at=item["started"], finished_at=item["finished"])
        label = FLASH_LABEL.get(result["status"], result["status"])
        if result["status"] == "succeeded":
            self.log("info", f"[flash] OK {olt}: {result['detail']}")
        else:
            self.log("warn", f"[flash] {label.upper()} {olt}: {result['detail']}")
            self.db.alert("warning" if result["status"] != "inconclusive" else "critical",
                          f"Flash {label}", f"{olt}: {result['detail']}", self._run_id)
        time.sleep(1.5)
        return item

    # ----------------------------------------------------------------- export
    def _do_export(self) -> dict:
        root = self.cfg.export_root
        work_root = root / ".work"
        work_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        work = work_root / f"{stamp}_{uuid.uuid4().hex[:6]}"
        work.mkdir(parents=True)

        t0 = datetime.now()
        self.log("info", f"[export] destino de trabalho {work}")
        result = self.client.export_configuration(str(work), float(self.cfg.get("export_timeout_s")),
                                                 log=self.log)
        check = self.validate_export(work)
        item = {"status": result["status"], "detail": result["detail"],
                "work": str(work), "artifact": None, "validation": check,
                "started": t0.isoformat(timespec="seconds")}

        if check["ok"] and result["status"] != "failed":
            final = self.unique_dir(root / f"ANM2000_Backup_{datetime.now():%d-%m-%Y}")
            os.replace(work, final)
            item["artifact"] = str(final)
            item["status"] = "succeeded"
            item["detail"] = (f"{check['files']} arquivos, {check['mb']:.2f} MB; "
                              f"cliente: {result['detail'][:160]}")
            self.log("info", f"[export] OK -> {final} ({check['files']} arquivos, "
                             f"{check['mb']:.2f} MB)")
        else:
            keepsake = work_root / f"FAILED_{stamp}"
            try:
                os.replace(work, keepsake)
                item["work"] = str(keepsake)
            except OSError:
                pass
            if result["status"] == "failed":
                item["status"] = "failed"
            elif check["ok"]:
                item["status"] = "inconclusive"
                item["detail"] = ("cliente reportou falha, mas o artefato parece completo; "
                                  "revisao manual necessaria")
            else:
                item["status"] = "inconclusive"
                item["detail"] = f"artefato nao validado: {check['reason']} ({result['detail'][:120]})"
            self.log("warn", f"[export] {item['status'].upper()}: {item['detail']} "
                             f"(mantido em {item['work']})")
            self.db.alert("critical", "Export nao confirmado",
                          f"{item['detail']} | {item['work']}", self._run_id)

        self.db.add_item(self._run_id, "export", "ANM2000", item["status"],
                         item["detail"], None, item.get("artifact") or "",
                         started_at=item["started"],
                         finished_at=datetime.now().isoformat(timespec="seconds"))
        return item

    def validate_export(self, path: Path) -> dict:
        files = [p for p in Path(path).rglob("*") if p.is_file()]
        total = sum(p.stat().st_size for p in files)
        names = {p.name.lower() for p in files}
        main = next((p.stat().st_size for p in files if p.name.lower() == "anconfigdata.unl"), 0)
        check = {
            "ok": True, "files": len(files), "mb": round(total / 1048576, 2),
            "configtable": "configtable.xml" in names,
            "main_bytes": main, "reason": "",
        }
        min_files = int(self.cfg.get("confirm_export_min_files"))
        min_main = float(self.cfg.get("confirm_export_min_main_mb")) * 1048576
        if len(files) < min_files:
            check.update(ok=False, reason=f"apenas {len(files)} arquivos (minimo {min_files})")
        elif self.cfg.get("confirm_export_require_configtable") and not check["configtable"]:
            check.update(ok=False, reason="configtable.xml ausente")
        elif main < min_main:
            check.update(ok=False, reason=f"anconfigdata.unl com {main} bytes (minimo {min_main:.0f})")
        return check

    # ---------------------------------------------------------------- resumo
    def _overall(self, report: dict, do_flash: bool, do_export: bool) -> str:
        statuses = [i["status"] for i in report["flash"]]
        if do_export and report["export"]:
            statuses.append(report["export"]["status"])
        if not statuses:
            return "failed"
        if all(s == "succeeded" for s in statuses):
            return "succeeded"
        if any(s == "succeeded" for s in statuses):
            return "partial"
        if any(s == "inconclusive" for s in statuses):
            return "inconclusive"
        return "failed"

    def _summary(self, report: dict, started: datetime) -> str:
        dur = (datetime.now() - started).total_seconds()
        parts = []
        if report["flash"]:
            ok = sum(1 for i in report["flash"] if i["status"] == "succeeded")
            parts.append(f"flash {ok}/{len(report['flash'])}")
        if report["export"]:
            parts.append(f"export {report['export']['status']}")
        return f"{report['status']}: " + ", ".join(parts) + f" ({dur:.0f}s)"
