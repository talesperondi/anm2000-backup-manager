"""Descoberta e operacoes contra o cliente ANM2000 ja aberto/autenticado.

Nada aqui guarda credenciais: o cliente e usado como esta em execucao.
Todos os hwnds sao descobertos em tempo de execucao (nunca fixos).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from . import msaa, winapi

CMD_SAVE_TO_FLASH = 61658
CMD_EXPORT_CONFIG = 24400

EXE_NAMES = ("anms.exe", "anmse.exe")
OLT_RE = re.compile(r"^(AN\d{4}-\d+_\d+\.\d+\.\d+\.\d+)", re.IGNORECASE)

SUCCESS_WORDS = ("command succeed",)
FAILURE_MAP = (
    ("command failed", "failed"),
    ("command fail", "failed"),
    ("failed to save configuration", "failed"),
    ("device returned null", "failed"),
    ("command overtime", "overtime"),
    ("busy in writing", "busy"),
    ("no operation privilege", "no_privilege"),
    ("no modification privilege", "no_privilege"),
    ("configuration not changed", "not_changed"),
    ("cancel", "cancelled"),
)
EXPORT_OK_WORDS = ("export config data success", "export succeed", "export success")
EXPORT_FAIL_WORDS = ("export failed", "failed to export", "export file failed",
                     "failed to export file")


class AnmError(RuntimeError):
    pass


@dataclass
class Snapshot:
    pid: int
    frame: int
    mdi_client: int
    object_tree: int
    topology: int | None
    title: str
    olt_names: list[str] = field(default_factory=list)


def _find_pid() -> int:
    for hwnd, cls, text in winapi.enum_windows():
        if not cls.startswith("Afx:") or "ANM2000" not in text.upper():
            continue
        pid = winapi.get_pid(hwnd)
        exe = winapi.process_path(pid).lower()
        if any(exe.endswith(name) for name in EXE_NAMES):
            return pid
    raise AnmError("ANM2000 nao encontrado: abra e autentique o cliente antes de executar.")


def discover() -> Snapshot:
    pid = _find_pid()
    frames = [w for w in winapi.enum_windows(pid)
              if w[1].startswith("Afx:") and "ANM2000" in w[2].upper()]
    if not frames:
        raise AnmError("janela principal do ANM2000 nao localizada")
    # maior janela = frame principal
    frame = max(frames, key=lambda w: _area(w[0]))[0]

    mdi_client = next((c for c in winapi.direct_children(frame)
                       if winapi.get_class(c) == "MDIClient"), 0)
    topology = None
    if mdi_client:
        for child in winapi.direct_children(mdi_client):
            if "topology" in winapi.get_text(child).lower():
                topology = child
                break

    tree, names = 0, []
    for hwnd in winapi.enum_children(frame):
        if winapi.get_class(hwnd) != "SysTreeView32":
            continue
        acc = msaa.accessible_from_hwnd(hwnd)
        if not acc:
            continue
        found = [n for _i, n, _s in msaa.items(acc) if OLT_RE.match(n)]
        if found:
            tree, names = hwnd, found
            break
    if not tree:
        raise AnmError("arvore de objetos (OLTs) nao encontrada no ANM2000")

    return Snapshot(pid=pid, frame=frame, mdi_client=mdi_client, object_tree=tree,
                    topology=topology, title=winapi.get_text(frame), olt_names=names)


def _area(hwnd: int) -> int:
    import ctypes
    from ctypes import wintypes
    r = wintypes.RECT()
    winapi.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r))
    return max(0, r.right - r.left) * max(0, r.bottom - r.top)


def modal_dialogs(pid: int) -> list[tuple[int, str]]:
    out = []
    for hwnd, cls, text in winapi.enum_windows(pid):
        if cls == "#32770" and hwnd:
            out.append((hwnd, text))
    return out


def wait_no_dialogs(pid: int, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not modal_dialogs(pid):
            return
        time.sleep(0.5)
    raise AnmError("existe um dialogo modal aberto no ANM2000; feche-o antes de continuar")


def is_responding(hwnd: int, timeout_ms: int = 5000) -> bool:
    import ctypes
    from ctypes import wintypes
    res = ctypes.c_size_t()
    ok = winapi.user32.SendMessageTimeoutW(
        wintypes.HWND(hwnd), 0x0000, 0, 0, 0x0002, timeout_ms, ctypes.byref(res))
    return bool(ok)


class AnmClient:
    def __init__(self) -> None:
        self.snap: Snapshot | None = None

    def connect(self) -> Snapshot:
        self.snap = discover()
        return self.snap

    @property
    def frame(self) -> int:
        if not self.snap:
            raise AnmError("cliente nao conectado")
        return self.snap.frame

    def refresh(self) -> Snapshot:
        self.snap = discover()
        return self.snap

    def ensure_topology(self) -> int:
        snap = self.snap or self.connect()
        if not snap.topology:
            raise AnmError("janela 'Topology View' nao encontrada")
        winapi.activate_mdi_child(snap.mdi_client, snap.topology)
        time.sleep(0.6)
        if not winapi.is_visible(snap.object_tree):
            snap = self.refresh()
            if not winapi.is_visible(snap.object_tree):
                raise AnmError("arvore de objetos nao esta visivel")
        winapi.bring_to_front(snap.frame)
        return snap.object_tree

    def selected_olts(self) -> list[str]:
        snap = self.snap or self.connect()
        acc = msaa.accessible_from_hwnd(snap.object_tree)
        if not acc:
            raise AnmError("sem acesso MSAA a arvore de objetos")
        return [n for _i, n, _s in msaa.selected_items(acc) if OLT_RE.match(n)]

    def select_olt(self, olt: str) -> str:
        tree = self.ensure_topology()
        acc = msaa.accessible_from_hwnd(tree)
        if not acc:
            raise AnmError("sem acesso MSAA a arvore de objetos")
        hit = msaa.find_item(acc, olt)
        if not hit:
            raise AnmError(f"OLT nao encontrada na arvore: {olt}")
        index, name, _state = hit
        msaa.select_item(acc, index)
        time.sleep(0.8)
        acc2 = msaa.accessible_from_hwnd(tree)
        selected = [n for _i, n, _s in msaa.selected_items(acc2)] if acc2 else []
        if not any(olt.lower() in n.lower() for n in selected):
            raise AnmError(f"selecao nao confirmada para {olt!r} (selecionado: {selected})")
        return selected[0]

    # ---------------------------------------------------------------- flash
    def save_config_to_flash(self, olt: str, timeout: float = 300.0,
                             log=None) -> dict:
        log = log or (lambda *_: None)
        snap = self.snap or self.connect()
        wait_no_dialogs(snap.pid)
        self.select_olt(olt)

        before = {w[0] for w in winapi.enum_windows(snap.pid)}
        log("info", f"enviando WM_COMMAND {CMD_SAVE_TO_FLASH} para {olt}")
        winapi.post_command(snap.frame, CMD_SAVE_TO_FLASH)

        dlg = _wait_new_dialog(snap.pid, before, timeout=25)
        if not dlg:
            return _result("inconclusive", "nenhum dialogo de confirmacao apareceu")

        texts = _dialog_texts(dlg)
        joined = " ".join(texts).lower()
        log("info", f"dialogo: {texts[:6]}")

        # guarda: o dialogo precisa citar o alvo selecionado
        if not _mentions_target(texts, olt):
            _safe_close(dlg)
            return _result("inconclusive",
                           f"dialogo nao corresponde a OLT {olt!r}: {texts[:4]}")

        ok = _find_button(dlg, ("ok", "&ok", "yes", "&yes")) or \
            (winapi.first_child(dlg, cid=1148) or 0)
        if not ok:
            _safe_close(dlg)
            return _result("inconclusive", "botao OK do dialogo nao encontrado")

        log("info", "confirmando dialogo (OK)")
        winapi.click(ok)

        verdict, raw, seconds = self._watch_flash(dlg, timeout, log)
        _safe_close(dlg, keep_open=False)
        result = _result(verdict, raw, seconds)
        result["raw_texts"] = raw
        return result

    def _watch_flash(self, dlg: int, timeout: float, log) -> tuple[str, list[str], int | None]:
        deadline = time.time() + timeout
        seen: list[str] = []
        verdict, raw_text = "inconclusive", ""
        while time.time() < deadline:
            if not winapi.is_alive(dlg):
                break
            for t in _dialog_texts(dlg):
                if t not in seen:
                    seen.append(t)
                    log("debug", f"dialogo: {t[:200]}")
            joined = " ".join(seen).lower()
            hit = _match_verdict(joined)
            if hit:
                verdict, raw_text = hit, _best_line(seen, hit)
                time.sleep(1.5)          # deixa o texto final estabilizar
                if winapi.is_alive(dlg):
                    for t in _dialog_texts(dlg):
                        if t not in seen:
                            seen.append(t)
                break
            time.sleep(0.6)
        seconds = None
        m = re.search(r"\[\s*(\d+)\s*sec", raw_text or " ".join(seen), re.IGNORECASE)
        if m:
            seconds = int(m.group(1))
        if not winapi.is_alive(dlg) and verdict == "inconclusive":
            return "inconclusive", "dialogo fechou sem texto de resultado", seconds
        return verdict, raw_text or " | ".join(seen[:6]), seconds

    # --------------------------------------------------------------- export
    def export_configuration(self, dest: str, timeout: float = 300.0, log=None) -> dict:
        """Dispara o export. O status aqui reflete APENAS os dialogos do cliente.

        A confirmacao oficial e o artefato em disco (validado pelo Runner).
        """
        log = log or (lambda *_: None)
        snap = self.snap or self.connect()
        wait_no_dialogs(snap.pid)
        winapi.bring_to_front(snap.frame)

        before = {w[0] for w in winapi.enum_windows(snap.pid)}
        log("info", f"enviando WM_COMMAND {CMD_EXPORT_CONFIG} para export em {dest}")
        winapi.post_command(snap.frame, CMD_EXPORT_CONFIG)

        dlg = _wait_new_dialog(snap.pid, before, timeout=20,
                              title_contains="choose directory", alt_cid=(2072,))
        if not dlg:
            return _result("inconclusive", "dialogo 'Choose Directory' nao apareceu")

        edit = winapi.first_child(dlg, cls="Edit", cid=2072) or winapi.first_child(dlg, cls="Edit")
        if not edit:
            _safe_close(dlg)
            return _result("inconclusive", "campo de diretorio nao encontrado")

        winapi.set_edit_text(edit, dest)
        time.sleep(0.3)
        back = winapi.get_edit_text(edit)
        if back.strip().rstrip("\\").lower() != dest.rstrip("\\").lower():
            _safe_close(dlg)
            return _result("inconclusive",
                           f"caminho nao confirmado no dialogo (lido: {back!r})")
        log("info", "caminho confirmado no dialogo")

        ok = winapi.first_child(dlg, cid=1) or _find_button(dlg, ("ok", "&ok"))
        if not ok:
            _safe_close(dlg)
            return _result("inconclusive", "botao Ok nao encontrado")
        winapi.click(ok)

        deadline = time.time() + timeout
        success = failure = progress_seen = ""
        last_dialog_at = time.time()
        while time.time() < deadline:
            time.sleep(0.5)
            dialogs = [(h, winapi.get_text(h)) for h in _new_windows(snap.pid, before)
                       if winapi.get_class(h) == "#32770" and winapi.is_alive(h)]
            if dialogs:
                last_dialog_at = time.time()
            for h, title in dialogs:
                body = " ".join(_dialog_texts(h))
                low = (title + " " + body).lower()
                if any(w in low for w in EXPORT_OK_WORDS) and not success:
                    success = f"{title} | {body}".strip(" |")
                    log("info", f"sucesso declarado pelo cliente: {body[:200]}")
                elif any(w in low for w in EXPORT_FAIL_WORDS) and not failure:
                    failure = f"{title} | {body}".strip(" |")
                    log("warn", f"falha declarada pelo cliente: {body[:200]}")
                elif "cancel" in low and not progress_seen:
                    progress_seen = f"{title} | {body}"
                    log("debug", f"progresso: {body[:120] or title}")
                if success or failure:
                    _dismiss(h, log)
            if success or failure:
                break
            # o popup de sucesso nasce ~1s depois do progresso fechar: da uma folga
            if progress_seen and not dialogs and time.time() - last_dialog_at > 8:
                log("debug", "progresso encerrado; aguardando resultado")
                break

        if success:
            status, detail = "succeeded", success
        elif failure:
            status, detail = "failed", failure
        elif progress_seen:
            status, detail = "inconclusive", f"progresso sem resultado declarado: {progress_seen[:200]}"
        else:
            status, detail = "inconclusive", "nenhum dialogo de progresso/resultado observado"
        return _result(status, detail)


def _new_windows(pid: int, before: set[int]) -> list[int]:
    return [w[0] for w in winapi.enum_windows(pid) if w[0] not in before]


def _wait_new_dialog(pid: int, before: set[int], timeout: float,
                     title_contains: str | None = None,
                     alt_cid: tuple[int, ...] = ()) -> int:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for hwnd, cls, text in winapi.enum_windows(pid):
            if hwnd in before or cls != "#32770":
                continue
            if title_contains and title_contains in text.lower():
                return hwnd
            if title_contains is None:
                return hwnd
            if alt_cid and any(winapi.first_child(hwnd, cid=cid) for cid in alt_cid):
                return hwnd
        time.sleep(0.25)
    return 0


def _dialog_texts(hwnd: int) -> list[str]:
    out = [winapi.get_text(hwnd)]
    out += msaa.window_texts(hwnd)
    for child in winapi.enum_children(hwnd):
        if winapi.get_class(child) in ("Static", "Edit", "Button", "SysListView32"):
            t = winapi.get_text(child).strip()
            if t:
                out.append(t)
    cleaned = []
    for t in out:
        t = (t or "").strip()
        if t and t not in cleaned:
            cleaned.append(t)
    return cleaned


def _find_button(dlg: int, labels: tuple[str, ...]) -> int:
    for child in winapi.enum_children(dlg):
        if winapi.get_class(child) not in ("Button", "XTPButton"):
            continue
        if winapi.get_text(child).strip().lower() in labels:
            return child
    return 0


def _safe_close(dlg: int, keep_open: bool = False) -> None:
    if not winapi.is_alive(dlg):
        return
    for label in ("close", "fechar", "cancel", "cancelar"):
        btn = _find_button(dlg, (label,))
        if btn:
            winapi.click(btn)
            time.sleep(0.8)
            if not winapi.is_alive(dlg):
                return
    winapi.close_window(dlg)


def _dismiss(dlg: int, log) -> None:
    if not winapi.is_alive(dlg):
        return
    for label in ("ok", "&ok", "close", "fechar"):
        btn = _find_button(dlg, (label,))
        if btn:
            log("debug", f"fechando popup com {label!r}")
            winapi.click(btn)
            time.sleep(0.5)
            return


def _match_verdict(joined: str) -> str | None:
    if any(w in joined for w in SUCCESS_WORDS):
        return "succeeded"
    for word, status in FAILURE_MAP:
        if word in joined:
            return status
    return None


def _best_line(lines: list[str], verdict: str) -> str:
    words = SUCCESS_WORDS if verdict == "succeeded" else tuple(w for w, s in FAILURE_MAP if s == verdict)
    for line in reversed(lines):
        low = line.lower()
        if any(w in low for w in words):
            return line.strip()
    return lines[-1].strip() if lines else ""


def _mentions_target(texts: list[str], olt: str) -> bool:
    joined = " ".join(texts).lower().replace(" ", "")
    key = olt.lower().replace(" ", "")
    short = OLT_RE.match(olt)
    if short and short.group(1).lower().replace(" ", "") in joined:
        return True
    return key in joined


def _result(status: str, detail: str, seconds: int | None = None) -> dict:
    return {"status": status, "detail": detail, "seconds": seconds,
            "confirmed": status == "succeeded"}
