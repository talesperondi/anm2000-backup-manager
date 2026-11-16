"""Autoteste da GUI: monta a janela, visita todas as paginas e valida dados."""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from anmbackup import anm, gui

errors = []
app = gui.App()
app.update_idletasks()
app.update()

print("titulo:", app.title())
print("tamanho:", app.winfo_width(), "x", app.winfo_height())

for key, nav in app.navs.items():
    try:
        app._show(key)
        app.update_idletasks()
        app.update()
        page = app.pages[key]
        kids = len(page.winfo_children())
        print(f"pagina {key:14} ok  widgets={kids}  mapeada={bool(page.winfo_ismapped())}")
    except Exception as exc:
        errors.append(f"{key}: {exc}")
        traceback.print_exc()

# dados
print("\nlinhas no historico:", len(app.runs_tree.get_children()))
if app.runs_tree.get_children():
    app.runs_tree.selection_set(app.runs_tree.get_children()[0])
    app.update()
    txt = app.run_detail.get("1.0", "end").strip()
    print("detalhe:", txt.splitlines()[:3])

print("OLTs na tela:", list(app.olt_vars))
snap = anm.discover()
app._set_conn(True, f"ANM2000 conectado • pid {snap.pid}", snap.olt_names)
app.update()
print("OLTs apos conexao:", list(app.olt_vars))
print("pill:", app.pill.cget("text"))
print("painel: ultima =", app.stat_last[1].cget("text"),
      "| export =", app.stat_export[1].cget("text"),
      "| alertas =", app.stat_alert[1].cget("text"))

app._refresh_logs()
print("logs carregados:", app.log_count.cget("text"))

app._show("agendamentos")
app.sch_name.insert(0, "teste")
app.sch_time.delete(0, "end")
app.sch_time.insert(0, "03:30")
app.update()
app._refresh_schedules()
print("agendamentos:", len(app.sch_tree.get_children()))

# limpa o agendamento de teste
with app.db.connect() as con:
    con.execute("DELETE FROM schedules WHERE name='teste'")
app._refresh_schedules()

app.scheduler.stop()
app.destroy()
print("\nerros:", errors or "nenhum")
