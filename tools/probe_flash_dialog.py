"""Abre o dialogo de confirmacao do Save Config To Flash e o CANCELA.

Serve para validar descoberta de dialogo, botoes e verificacao de alvo
sem executar nenhuma gravacao. Nada e confirmado com OK.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anmbackup import anm, winapi

OLT = sys.argv[1] if len(sys.argv) > 1 else "OLT-01"

client = anm.AnmClient()
snap = client.connect()
print("OLTs:", snap.olt_names)
print("selecionando:", OLT, "->", client.select_olt(OLT))

before = {w[0] for w in winapi.enum_windows(snap.pid)}
winapi.post_command(snap.frame, anm.CMD_SAVE_TO_FLASH)
dlg = anm._wait_new_dialog(snap.pid, before, timeout=25)
if not dlg:
    raise SystemExit("dialogo nao apareceu")

time.sleep(1.0)
texts = anm._dialog_texts(dlg)
print("\ndialogo:", dlg, winapi.get_class(dlg), repr(winapi.get_text(dlg)))
for t in texts:
    print("   texto:", repr(t))

buttons = []
for child in winapi.enum_children(dlg):
    if winapi.get_class(child) in ("Button", "XTPButton"):
        buttons.append({"hwnd": child, "id": winapi.ctrl_id(child),
                        "text": winapi.get_text(child),
                        "enabled": winapi.is_enabled(child)})
print("\nbotoes:")
for b in buttons:
    print("  ", b)

print("\nmenciona alvo:", anm._mentions_target(texts, OLT))
print("classificacao inicial:", anm._match_verdict(" ".join(texts).lower()))

# CANCELA (nunca OK)
closed = False
for b in buttons:
    if b["text"].strip().lower() in ("close", "fechar", "cancel", "cancelar"):
        print("fechando com:", b["text"])
        winapi.click(b["hwnd"])
        closed = True
        break
time.sleep(1.5)
print("dialogo fechado:", not winapi.is_alive(dlg), "| solicitado:", closed)
print("janela responde:", anm.is_responding(snap.frame))
print("dialogos restantes:", anm.modal_dialogs(snap.pid))
