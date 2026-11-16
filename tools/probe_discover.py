"""Diagnostico somente-leitura: descoberta do cliente, arvore e selecao."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anmbackup import anm, msaa, winapi

snap = anm.discover()
print("PID           :", snap.pid)
print("frame         :", snap.frame, repr(snap.title))
print("mdi client    :", snap.mdi_client)
print("topology view :", snap.topology, repr(winapi.get_text(snap.topology or 0)))
print("object tree   :", snap.object_tree, "visivel:", winapi.is_visible(snap.object_tree))
print("respondendo   :", anm.is_responding(snap.frame))
print("dialogos      :", anm.modal_dialogs(snap.pid))
print("\nMDI children:")
for c in winapi.direct_children(snap.mdi_client):
    print(f"   {c} {winapi.get_class(c):20} {winapi.get_text(c)!r} visivel={winapi.is_visible(c)}")

acc = msaa.accessible_from_hwnd(snap.object_tree)
sel = msaa.selected_items(acc)
print("\nselecionado:", [(n, hex(s)) for _i, n, s in sel])
print("OLTs:")
for i, name in enumerate(snap.olt_names):
    print(f"   {i+1}. {name}")

print("\narvores SysTreeView32 encontradas:")
for h in winapi.enum_children(snap.frame):
    if winapi.get_class(h) == "SysTreeView32":
        a = msaa.accessible_from_hwnd(h)
        sample = msaa.texts(a, 3) if a else []
        print(f"   {h} itens={msaa.child_count(a) if a else 0} exemplo={sample}")
