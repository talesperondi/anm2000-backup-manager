"""Interface de linha de comando (prototipo e suporte)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, anm, config, db as dbmod, runner


def _utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def cmd_run(args) -> int:
    r = runner.Runner()
    do_flash = not args.export_only
    do_export = not args.flash_only
    report = r.run(do_flash=do_flash, do_export=do_export, only=args.olt,
                   dry_run=args.dry_run, kind=args.kind, trigger="cli",
                   wait_for_anm=args.wait_anm)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if report["status"] in ("succeeded", "dry_run") else 2


def cmd_status(args) -> int:
    r = runner.Runner()
    print(f"raiz de backups : {r.cfg.root}")
    print(f"flash           : {r.cfg.flash_root}")
    print(f"export          : {r.cfg.export_root}")
    print(f"banco           : {r.db.path}")
    from . import autostart
    st = autostart.status()
    print(f"inicio Windows  : {'ativa' if st.get('enabled') else ('inativa' if st.get('installed') else 'não configurada')}")
    try:
        snap = r.client.connect()
        print(f"\nANM2000 conectado: pid {snap.pid} | {snap.title}")
        print("OLTs:")
        for name in snap.olt_names:
            print(f"  - {name}")
        print("selecionado:", r.client.selected_olts())
    except anm.AnmError as exc:
        print(f"\nANM2000 indisponivel: {exc}")

    runs = r.db.recent_runs(5)
    print("\nultimas execucoes:")
    for row in runs:
        print(f"  #{row['id']} {row['started_at']} {row['status']:12} {row['summary'] or ''}")
    alerts = [a for a in r.db.recent_alerts(10) if not a["ack"]]
    if alerts:
        print("\nalertas pendentes:")
        for a in alerts:
            print(f"  [{a['severity']}] {a['ts']} {a['title']}: {a['message']}")
    return 0


def cmd_history(args) -> int:
    r = runner.Runner()
    for row in r.db.recent_runs(args.limit):
        print(f"#{row['id']} {row['started_at']} -> {row['finished_at'] or '...'} "
              f"[{row['status']}] {row['summary'] or ''}")
        for item in r.db.run_items(row["id"]):
            extra = f" {item['seconds']}s" if item["seconds"] else ""
            art = f" -> {item['artifact']}" if item["artifact"] else ""
            print(f"    {item['operation']:6} {item['status']:12} {item['target']}{extra}{art}")
            if item["status"] != "succeeded" and item["detail"]:
                print(f"           {item['detail'][:300]}")
    return 0


def cmd_logs(args) -> int:
    r = runner.Runner()
    for row in reversed(r.db.recent_logs(args.limit)):
        print(f"{row['ts']} {row['level']:5} {row['message']}")
    return 0


def cmd_config(args) -> int:
    r = runner.Runner()
    if args.action == "show" or not args.action:
        print(json.dumps(r.cfg.all(), ensure_ascii=False, indent=2, default=str))
        return 0
    if args.action == "set":
        if not args.key or args.value is None:
            print("uso: config set <chave> <valor>", file=sys.stderr)
            return 1
        current = r.cfg.get(args.key)
        raw = args.value
        if isinstance(current, bool):
            value = raw.strip().lower() in ("1", "true", "yes", "on", "sim")
        elif isinstance(current, int):
            value = int(raw)
        elif isinstance(current, float):
            value = float(raw)
        elif isinstance(current, list):
            value = json.loads(raw)
        else:
            value = raw
        r.cfg.set(args.key, value)
        print(f"{args.key} = {value!r}")
        return 0
    print("acao invalida", file=sys.stderr)
    return 1


def cmd_autostart(args) -> int:
    from . import autostart
    action = args.action or "status"
    if action == "status":
        print(json.dumps(autostart.status(), ensure_ascii=False, indent=2))
        return 0
    if action == "enable":
        ok, message = autostart.enable()
    elif action == "disable":
        ok, message = autostart.disable()
    elif action == "remove":
        ok, message = autostart.remove()
    else:
        print("acao invalida", file=sys.stderr)
        return 1
    print(message)
    return 0 if ok else 2


def cmd_gui(args) -> int:
    from .gui import run_gui
    return run_gui()


def cmd_probe(args) -> int:
    snap = anm.discover()
    data = {
        "pid": snap.pid, "frame": snap.frame, "titulo": snap.title,
        "mdi_client": snap.mdi_client, "topology": snap.topology,
        "object_tree": snap.object_tree,
        "arvore_visivel": anm.winapi.is_visible(snap.object_tree),
        "respondendo": anm.is_responding(snap.frame),
        "dialogos_abertos": anm.modal_dialogs(snap.pid),
        "olts": snap.olt_names,
    }
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="anm2000bm",
                                description="ANM2000 Backup Manager")
    p.add_argument("--version", action="version",
                   version=f"anm2000bm {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="executa ciclo de backup")
    run.add_argument("--flash-only", action="store_true")
    run.add_argument("--export-only", action="store_true")
    run.add_argument("--olt", action="append", help="OLT alvo (substring, pode repetir)")
    run.add_argument("--dry-run", action="store_true", help="somente valida, nada executa")
    run.add_argument("--wait-anm", action="store_true",
                     help="aguarda o ANM2000 abrir/autenticar antes de executar")
    run.add_argument("--kind", default="manual")
    run.set_defaults(func=cmd_run)

    st = sub.add_parser("status", help="estado atual")
    st.set_defaults(func=cmd_status)

    h = sub.add_parser("history", help="historico de execucoes")
    h.add_argument("-n", "--limit", type=int, default=10)
    h.set_defaults(func=cmd_history)

    lg = sub.add_parser("logs", help="logs recentes")
    lg.add_argument("-n", "--limit", type=int, default=50)
    lg.set_defaults(func=cmd_logs)

    cf = sub.add_parser("config", help="configuracoes")
    cf.add_argument("action", nargs="?", choices=["show", "set"], default="show")
    cf.add_argument("key", nargs="?")
    cf.add_argument("value", nargs="?")
    cf.set_defaults(func=cmd_config)

    au = sub.add_parser("autostart", help="inicializacao com o Windows")
    au.add_argument("action", nargs="?",
                    choices=["status", "enable", "disable", "remove"], default="status")
    au.set_defaults(func=cmd_autostart)

    pr = sub.add_parser("probe", help="diagnostico da janela do ANM2000")
    pr.set_defaults(func=cmd_probe)

    gu = sub.add_parser("gui", help="abre a interface grafica")
    gu.set_defaults(func=cmd_gui)
    return p


def main(argv: list[str] | None = None) -> int:
    _utf8()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except anm.AnmError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 3
    except runner.AlreadyRunning as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 4
