"""Testes de unidade das regras criticas (nao tocam no ANM2000)."""

import os
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anmbackup import anm, autostart, db as dbmod, msaa, runner, scheduler


class UniqueDirTest(unittest.TestCase):
    def test_nao_sobrescreve(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "ANM2000_Backup_14-11-2026"
            base.mkdir()
            (base / "marca.txt").write_text("original", encoding="utf-8")
            nxt = runner.Runner.unique_dir(base)
            self.assertEqual(nxt.name, "ANM2000_Backup_14-11-2026_2")
            nxt.mkdir()
            nxt3 = runner.Runner.unique_dir(base)
            self.assertEqual(nxt3.name, "ANM2000_Backup_14-11-2026_3")
            self.assertEqual((base / "marca.txt").read_text(encoding="utf-8"), "original")


class ValidateExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.art = self.root / "art"
        self.art.mkdir()
        self.db = dbmod.Database(self.root / "t.db")
        from anmbackup import config
        self.runner = runner.Runner.__new__(runner.Runner)
        self.runner.db = self.db
        self.runner.cfg = config.Config(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def _make(self, files=60, configtable=True, main_mb=2.0):
        for i in range(files):
            (self.art / f"t{i}.unl").write_bytes(b"x" * 10)
        (self.art / "anconfigdata.unl").write_bytes(b"y" * int(main_mb * 1048576))
        if configtable:
            (self.art / "configtable.xml").write_text("<x/>", encoding="utf-8")

    def test_artefato_valido(self):
        self._make()
        check = self.runner.validate_export(self.art)
        self.assertTrue(check["ok"], check)
        self.assertTrue(check["configtable"])
        self.assertEqual(check["files"], 62)

    def test_sem_configtable(self):
        self._make(configtable=False)
        check = self.runner.validate_export(self.art)
        self.assertFalse(check["ok"])
        self.assertIn("configtable", check["reason"])

    def test_poucos_arquivos(self):
        self._make(files=3)
        self.assertFalse(self.runner.validate_export(self.root)["ok"])

    def test_arquivo_principal_pequeno(self):
        self._make(main_mb=0.2)
        self.assertFalse(self.runner.validate_export(self.root)["ok"])


class VerdictTest(unittest.TestCase):
    def test_sucesso(self):
        self.assertEqual(anm._match_verdict("command succeed\t[ 17 sec ]"), "succeeded")

    def test_falhas_tipificadas(self):
        self.assertEqual(anm._match_verdict("command failed"), "failed")
        self.assertEqual(anm._match_verdict("command overtime"), "overtime")
        self.assertEqual(anm._match_verdict("busy in writing erprom..."), "busy")
        self.assertEqual(anm._match_verdict("no operation privilege"), "no_privilege")
        self.assertEqual(anm._match_verdict("configuration not changed"), "not_changed")

    def test_em_andamento_nao_e_veredito(self):
        self.assertIsNone(anm._match_verdict("sending the command. please wait..."))

    def test_alvo_mencionado(self):
        olt = "AN5516-04_10.0.0.2 (FIBER ALFA)"
        textos = ["Command Result", "Save Config  to Flash\nUndivided Systems-" + olt]
        self.assertTrue(anm._mentions_target(textos, olt))
        self.assertFalse(anm._mentions_target(textos, "AN5516-01_10.0.0.4 (FIBER GAMA)"))


class SchedulerTest(unittest.TestCase):
    def test_proxima_ocorrencia(self):
        base = datetime(2026, 11, 14, 10, 0)      # sabado
        nxt = scheduler.next_occurrence("02:00", "1,2,3,4,5", base)
        self.assertEqual(nxt, datetime(2026, 11, 16, 2, 0))  # segunda
        nxt2 = scheduler.next_occurrence("23:00", "6", base)
        self.assertEqual(nxt2, datetime(2026, 11, 14, 23, 0))

    def test_hora_invalida(self):
        self.assertIsNone(scheduler.next_occurrence("xx", "1"))

    def test_ultima_ocorrencia(self):
        base = datetime(2026, 11, 16, 10, 0)
        self.assertEqual(scheduler.latest_occurrence("09:00", "1", base),
                         datetime(2026, 11, 16, 9, 0))
        self.assertEqual(scheduler.latest_occurrence("18:00", "1", base),
                         datetime(2026, 11, 9, 18, 0))


class FakeSchedulerDB:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def schedules(self):
        return [self.row]

    def set_schedule_run(self, sid, last, nxt):
        self.calls.append((sid, last, nxt))
        self.row["last_run_at"] = last
        self.row["next_run_at"] = nxt


def _row(next_run, last_run="", at_time="00:01"):
    return {"id": 1, "enabled": 1, "at_time": at_time,
            "weekdays": "1,2,3,4,5,6,7", "last_run_at": last_run,
            "next_run_at": next_run}


class CatchUpTest(unittest.TestCase):
    def _sched(self, row, busy=False, catch_up=True):
        db = FakeSchedulerDB(row)
        fired = []
        s = scheduler.Scheduler(db, fired.append, lambda: busy, catch_up=catch_up)
        return db, fired, s

    def test_recupera_ocorrencia_perdida(self):
        now = datetime.now()
        row = _row((now - timedelta(days=1)).isoformat(timespec="seconds"))
        db, fired, s = self._sched(row)
        s._tick()
        self.assertEqual(len(fired), 1)
        self.assertTrue(fired[0]["catch_up"])
        self.assertGreater(datetime.fromisoformat(db.row["next_run_at"]), now)
        s._tick()
        self.assertEqual(len(fired), 1, "nao pode repetir a mesma ocorrencia")

    def test_nao_dispara_antes_da_hora(self):
        now = datetime.now()
        row = _row((now + timedelta(hours=2)).isoformat(timespec="seconds"))
        _db, fired, s = self._sched(row)
        s._tick()
        self.assertEqual(fired, [])

    def test_respeita_execucao_em_andamento(self):
        now = datetime.now()
        due = (now - timedelta(minutes=5)).isoformat(timespec="seconds")
        row = _row(due)
        db, fired, s = self._sched(row, busy=True)
        s._tick()
        self.assertEqual(fired, [])
        self.assertEqual(db.row["next_run_at"], due)
        self.assertEqual(db.calls, [])

    def test_ja_executada_nao_repete(self):
        now = datetime.now()
        due = (now - timedelta(days=1)).isoformat(timespec="seconds")
        row = _row(due, last_run=(now - timedelta(hours=2)).isoformat(timespec="seconds"))
        db, fired, s = self._sched(row)
        s._tick()
        self.assertEqual(fired, [])
        self.assertGreater(datetime.fromisoformat(db.row["next_run_at"]), now)

    def test_catch_up_desativado_pula_ocorrencia(self):
        now = datetime.now()
        row = _row((now - timedelta(days=2)).isoformat(timespec="seconds"))
        _db, fired, s = self._sched(row, catch_up=False)
        s._tick()
        self.assertEqual(fired, [])


class OrphanRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = dbmod.Database(self.root / "t.db")
        self.lock = runner.RunLock(self.root / "run.lock")

    def tearDown(self):
        self.tmp.cleanup()

    def test_execucao_orfa_vira_abortada(self):
        run_id = self.db.start_run("scheduled", "scheduled")
        ids = runner.recover_orphans(self.db, self.lock)
        self.assertEqual(ids, [run_id])
        row = self.db.recent_runs(1)[0]
        self.assertEqual(row["status"], "aborted")
        self.assertIn("reiniciado", row["summary"])
        self.assertTrue(self.db.recent_alerts(5))

    def test_lock_vivo_nao_e_tocado(self):
        self.lock.acquire()
        try:
            run_id = self.db.start_run("scheduled", "scheduled")
            self.assertEqual(runner.recover_orphans(self.db, self.lock), [])
            self.assertEqual(self.db.recent_runs(1)[0]["status"], "running")
            self.assertNotEqual(run_id, 0)
        finally:
            self.lock.release()


class AutostartTest(unittest.TestCase):
    def test_launcher_aponta_para_gui(self):
        exe, args = autostart.launcher()
        self.assertTrue(exe.lower().endswith(("pythonw.exe", "python.exe")))
        self.assertIn("gui.py", args)
        self.assertTrue((autostart.project_dir() / "gui.py").is_file())

    def test_launcher_congelado_usa_o_proprio_exe(self):
        old_frozen = getattr(sys, "frozen", None)
        old_exe = sys.executable
        try:
            sys.frozen = True
            sys.executable = r"C:\Teste\ANM2000 Backup Manager.exe"
            exe, args = autostart.launcher()
            self.assertEqual(args, "")
            self.assertEqual(Path(exe).name, "ANM2000 Backup Manager.exe")
        finally:
            if old_frozen is None:
                del sys.frozen
            else:
                sys.frozen = old_frozen
            sys.executable = old_exe

    def test_enable_nao_passa_argumento_vazio(self):
        captured = {}

        def fake_ps(script, timeout=60.0):
            captured["script"] = script
            return subprocess.CompletedProcess([], 0, "OK", "")

        with mock.patch.object(autostart, "_ps", fake_ps), \
                mock.patch.object(autostart, "launcher",
                                  lambda: (r"C:\Teste\app.exe", "")):
            ok, _message = autostart.enable()
        self.assertTrue(ok)
        self.assertNotIn("-Argument ''", captured["script"])
        self.assertIn(r"C:\Teste\app.exe", captured["script"])

    def test_remove_preserva_tarefa_de_outra_instalacao(self):
        captured = {}

        def fake_ps(script, timeout=60.0):
            captured["script"] = script
            return subprocess.CompletedProcess([], 0, r"C:\Outro\app.exe", "")

        with mock.patch.object(autostart, "status", lambda: {"installed": True}), \
                mock.patch.object(autostart, "_ps", fake_ps), \
                mock.patch.object(autostart, "launcher",
                                  lambda: (r"C:\Teste\app.exe", "")):
            ok, message = autostart.remove()
        self.assertTrue(ok)
        self.assertIn("preservada", message)
        self.assertNotIn("Unregister-ScheduledTask", captured["script"])

    def test_remove_apaga_tarefa_da_propria_instalacao(self):
        scripts = []

        def fake_ps(script, timeout=60.0):
            scripts.append(script)
            stdout = r"C:\Teste\app.exe" if len(scripts) == 1 else "OK"
            return subprocess.CompletedProcess([], 0, stdout, "")

        with mock.patch.object(autostart, "status", lambda: {"installed": True}), \
                mock.patch.object(autostart, "_ps", fake_ps), \
                mock.patch.object(autostart, "launcher",
                                  lambda: (r"C:\Teste\app.exe", "")):
            ok, message = autostart.remove()
        self.assertTrue(ok)
        self.assertIn("removida", message)
        self.assertIn("Unregister-ScheduledTask", scripts[-1])


class ComThreadTest(unittest.TestCase):
    def test_com_inicializa_em_thread_nova(self):
        result = {}

        def work():
            try:
                msaa.init_com()
                result["ok"] = True
            except Exception as exc:          # pragma: no cover - diagnostico
                result["error"] = repr(exc)

        t = threading.Thread(target=work)
        t.start()
        t.join()
        self.assertTrue(result.get("ok"), result.get("error"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
