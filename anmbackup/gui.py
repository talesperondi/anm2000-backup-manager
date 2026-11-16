"""Interface grafica (tkinter) do ANM2000 Backup Manager."""

from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from . import __version__, anm, autostart, config, db as dbmod, runner, scheduler, winapi


def _resource(*parts: str) -> str:
    """Caminho de um recurso dentro do fonte ou do executavel congelado."""
    base = getattr(sys, "_MEIPASS", None)
    root = base or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, *parts)

# ----------------------------------------------------------------- identidade
BG = "#0B1117"
SIDEBAR = "#0E1620"
PANEL = "#121C26"
CARD = "#16232F"
CARD_HI = "#1B2B39"
BORDER = "#22323F"
TEXT = "#E6EEF5"
MUTED = "#7F94A6"
ACCENT = "#00D2B4"
ACCENT_DK = "#00A891"
OK = "#3DDC84"
WARN = "#F5B942"
ERR = "#FF6B6B"
INFO = "#4FA8FF"

F = "Segoe UI"
F_SM = (F, 9)
F_MD = (F, 10)
F_BOLD = (F, 10, "bold")
F_H2 = (F, 13, "bold")
F_H1 = (F, 20, "bold")
F_MONO = ("Consolas", 9)

STATUS_LABEL = {
    "succeeded": ("sucesso", OK),
    "partial": ("parcial", WARN),
    "failed": ("falha", ERR),
    "inconclusive": ("inconclusivo", WARN),
    "aborted": ("abortado", ERR),
    "dry_run": ("simulação", INFO),
    "running": ("executando", INFO),
}


def _dpi() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


class NavButton(tk.Frame):
    def __init__(self, master, text, command, glyph=""):
        super().__init__(master, bg=SIDEBAR, cursor="hand2")
        self.command = command
        self.active = False
        self.bar = tk.Frame(self, bg=SIDEBAR, width=3)
        self.bar.pack(side="left", fill="y")
        self.label = tk.Label(self, text=f"  {glyph}  {text}" if glyph else f"  {text}",
                              bg=SIDEBAR, fg=MUTED, font=F_MD, anchor="w", padx=12, pady=10)
        self.label.pack(side="left", fill="x", expand=True)
        for w in (self, self.label):
            w.bind("<Button-1>", lambda e: self.command())
            w.bind("<Enter>", self._hover)
            w.bind("<Leave>", self._leave)

    def _hover(self, _=None):
        if not self.active:
            self.label.configure(fg=TEXT)

    def _leave(self, _=None):
        if not self.active:
            self.label.configure(fg=MUTED)

    def set_active(self, active: bool):
        self.active = active
        self.bar.configure(bg=ACCENT if active else SIDEBAR)
        self.label.configure(fg=TEXT if active else MUTED,
                             font=F_BOLD if active else F_MD,
                             bg=CARD if active else SIDEBAR)
        self.configure(bg=CARD if active else SIDEBAR)


class Card(tk.Frame):
    def __init__(self, master, title="", **kw):
        super().__init__(master, bg=CARD, highlightbackground=BORDER,
                         highlightthickness=1, **kw)
        self.body = self
        if title:
            head = tk.Frame(self, bg=CARD)
            head.pack(fill="x", padx=16, pady=(12, 0))
            tk.Label(head, text=title.upper(), bg=CARD, fg=MUTED,
                     font=(F, 8, "bold")).pack(side="left")


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ANM2000 Backup Manager")
        self.geometry("1260x790")
        self.minsize(1120, 700)
        self.configure(bg=BG)

        self.db = dbmod.Database()
        self.cfg = config.Config(self.db)
        self.runner = runner.Runner(self.db, self.cfg)
        self.recovered = runner.recover_orphans(self.db)
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        self.olt_vars: dict[str, tk.BooleanVar] = {}
        self.pages: dict[str, tk.Frame] = {}
        self.navs: dict[str, NavButton] = {}
        self.conn_state = False
        self._run_lock = threading.Lock()
        self._bg_hint_shown = False

        icon = _resource("assets", "app.ico")
        if os.path.exists(icon):
            try:
                self.iconbitmap(icon)
            except tk.TclError:
                pass

        self.runner.on_log = lambda level, msg: self.q.put(("log", level, msg))

        self._style()
        self._build()
        self._show("painel")
        self._bind_events()

        self.scheduler = scheduler.Scheduler(
            self.db, self._schedule_due, lambda: self.busy,
            catch_up=bool(self.cfg.get("catch_up_enabled")))
        self.scheduler.start()

        self.after(120, self._drain)
        self.after(400, self._initial_refresh)
        self.after(900, self._startup_notes)
        self.after(6000, self._maybe_launch_anm)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ estilo
    def _style(self) -> None:
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure(".", background=BG, foreground=TEXT, font=F_MD)
        st.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT,
                     borderwidth=0, rowheight=26, font=F_MD)
        st.configure("Treeview.Heading", background=PANEL, foreground=MUTED,
                     relief="flat", font=(F, 9, "bold"), padding=(8, 6))
        st.map("Treeview", background=[("selected", "#1F3A4A")],
               foreground=[("selected", TEXT)])
        st.map("Treeview.Heading", background=[("active", PANEL)])
        st.configure("Vertical.TScrollbar", background=PANEL, troughcolor=BG,
                     bordercolor=BG, arrowcolor=MUTED, relief="flat")
        st.configure("TCombobox", fieldbackground=PANEL, background=PANEL,
                     foreground=TEXT, arrowcolor=MUTED, bordercolor=BORDER,
                     lightcolor=PANEL, darkcolor=PANEL, padding=6)
        st.map("TCombobox", fieldbackground=[("readonly", PANEL)],
               foreground=[("readonly", TEXT)])
        st.configure("Accent.Horizontal.TProgressbar", background=ACCENT,
                     troughcolor=PANEL, bordercolor=PANEL, lightcolor=ACCENT,
                     darkcolor=ACCENT)
        st.configure("TCheckbutton", background=CARD, foreground=TEXT, font=F_MD)
        st.map("TCheckbutton", background=[("active", CARD)])
        self.option_add("*TCombobox*Listbox.background", PANEL)
        self.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT_DK)
        self.option_add("*TCombobox*Listbox.selectForeground", "#06121A")

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        side = tk.Frame(self, bg=SIDEBAR, width=232)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        brand = tk.Frame(side, bg=SIDEBAR)
        brand.pack(fill="x", padx=20, pady=(22, 8))
        tk.Label(brand, text="ANM2000", bg=SIDEBAR, fg=ACCENT,
                 font=(F, 16, "bold")).pack(anchor="w")
        tk.Label(brand, text="Backup Manager", bg=SIDEBAR, fg=MUTED,
                 font=F_SM).pack(anchor="w")

        tk.Frame(side, bg=BORDER, height=1).pack(fill="x", padx=16, pady=(14, 10))

        nav = tk.Frame(side, bg=SIDEBAR)
        nav.pack(fill="x")
        for key, label, glyph in (("painel", "Painel", "◉"),
                                  ("execucoes", "Execuções", "≡"),
                                  ("logs", "Logs", "❏"),
                                  ("agendamentos", "Agendamentos", "⏱"),
                                  ("alertas", "Alertas", "⚠"),
                                  ("config", "Configurações", "⚙")):
            btn = NavButton(nav, label, lambda k=key: self._show(k), glyph)
            btn.pack(fill="x", pady=1)
            self.navs[key] = btn

        foot = tk.Frame(side, bg=SIDEBAR)
        foot.pack(side="bottom", fill="x", padx=18, pady=16)
        self.side_status = tk.Label(foot, text="●  verificando ANM2000…", bg=SIDEBAR,
                                    fg=MUTED, font=F_SM, anchor="w", justify="left")
        self.side_status.pack(anchor="w")
        tk.Label(foot, text=f"v{__version__}  •  by CHNET", bg=SIDEBAR, fg="#3E5364",
                 font=(F, 8)).pack(anchor="w", pady=(6, 0))

        main = tk.Frame(self, bg=BG)
        main.pack(side="left", fill="both", expand=True)

        head = tk.Frame(main, bg=BG)
        head.pack(fill="x", padx=26, pady=(20, 6))
        self.page_title = tk.Label(head, text="Painel", bg=BG, fg=TEXT, font=F_H1)
        self.page_title.pack(side="left")
        self.page_sub = tk.Label(head, text="", bg=BG, fg=MUTED, font=F_SM)
        self.page_sub.pack(side="left", padx=(12, 0), pady=(9, 0))
        self.pill = tk.Label(head, text="●  desconectado", bg=CARD, fg=ERR,
                             font=(F, 9, "bold"), padx=14, pady=6)
        self.pill.pack(side="right")

        self.content = tk.Frame(main, bg=BG)
        self.content.pack(fill="both", expand=True, padx=22, pady=(6, 18))

        self._build_dashboard()
        self._build_runs()
        self._build_logs()
        self._build_schedules()
        self._build_alerts()
        self._build_config()

    # ------------------------------------------------------------------ painel
    def _build_dashboard(self) -> None:
        page = tk.Frame(self.content, bg=BG)
        self.pages["painel"] = page

        stats = tk.Frame(page, bg=BG)
        stats.pack(fill="x")
        self.stat_last = self._stat(stats, "Última execução", "—", "nenhuma ainda")
        self.stat_flash = self._stat(stats, "Flash hoje", "0/0", "nenhuma OLT gravada")
        self.stat_export = self._stat(stats, "Último export", "—", "sem export")
        self.stat_alert = self._stat(stats, "Alertas", "0", "nada pendente")

        body = tk.Frame(page, bg=BG)
        body.pack(fill="both", expand=True, pady=(14, 0))

        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True, padx=(0, 12))

        actions = Card(left, "Ações")
        actions.pack(fill="x")
        btns = tk.Frame(actions, bg=CARD)
        btns.pack(fill="x", padx=16, pady=(10, 4))
        self.btn_run = self._action_button(btns, "Executar agora", self._ask_full, primary=True)
        self.btn_run.pack(side="left", padx=(0, 8))
        self.btn_export = self._action_button(btns, "Somente export", self._ask_export)
        self.btn_export.pack(side="left", padx=(0, 8))
        self.btn_flash = self._action_button(btns, "Somente flash", self._ask_flash)
        self.btn_flash.pack(side="left")

        olt_head = tk.Frame(actions, bg=CARD)
        olt_head.pack(fill="x", padx=16, pady=(12, 0))
        tk.Label(olt_head, text="OLTs alvo", bg=CARD, fg=MUTED,
                 font=(F, 8, "bold")).pack(side="left")
        tk.Button(olt_head, text="atualizar lista", command=self._refresh_olts,
                  bg=CARD, fg=INFO, activebackground=CARD, activeforeground=TEXT,
                  relief="flat", font=F_SM, cursor="hand2", bd=0).pack(side="right")
        self.olt_box = tk.Frame(actions, bg=CARD)
        self.olt_box.pack(fill="x", padx=16, pady=(4, 14))

        activity = Card(left, "Atividade")
        activity.pack(fill="both", expand=True, pady=(12, 0))
        self.progress = ttk.Progressbar(activity, mode="indeterminate",
                                        style="Accent.Horizontal.TProgressbar")
        self.progress.pack(fill="x", padx=16, pady=(10, 8))
        self.live = tk.Text(activity, bg="#0C141B", fg=TEXT, font=F_MONO, bd=0,
                            relief="flat", height=10, wrap="none",
                            insertbackground=TEXT, padx=10, pady=8)
        self.live.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        for tag, color in (("INFO", INFO), ("WARN", WARN), ("ERROR", ERR),
                           ("DEBUG", MUTED), ("OK", OK)):
            self.live.tag_configure(tag, foreground=color)
        self.live.configure(state="disabled")

        right = tk.Frame(body, bg=BG, width=330)
        right.pack(side="left", fill="y")
        right.pack_propagate(False)

        recent = Card(right, "Últimas execuções")
        recent.pack(fill="both", expand=True)
        self.mini_runs = tk.Text(recent, bg=CARD, fg=TEXT, font=F_SM, bd=0,
                                 relief="flat", height=12, wrap="word",
                                 padx=14, pady=10)
        self.mini_runs.pack(fill="both", expand=True)
        self.mini_runs.configure(state="disabled")

    def _stat(self, parent, title, value, hint):
        card = tk.Frame(parent, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        card.pack(side="left", fill="x", expand=True, padx=(0, 10))
        tk.Label(card, text=title.upper(), bg=CARD, fg=MUTED,
                 font=(F, 8, "bold")).pack(anchor="w", padx=14, pady=(12, 0))
        val = tk.Label(card, text=value, bg=CARD, fg=TEXT, font=(F, 18, "bold"))
        val.pack(anchor="w", padx=14)
        hint_lbl = tk.Label(card, text=hint, bg=CARD, fg=MUTED, font=F_SM)
        hint_lbl.pack(anchor="w", padx=14, pady=(0, 12))
        return card, val, hint_lbl

    def _action_button(self, parent, text, command, primary=False):
        bg = ACCENT if primary else PANEL
        fg = "#06121A" if primary else TEXT
        hover = ACCENT_DK if primary else CARD_HI
        return tk.Button(parent, text=text, command=command, bg=bg, fg=fg,
                         activebackground=hover, activeforeground=fg,
                         relief="flat", bd=0, font=(F, 9, "bold"),
                         padx=16, pady=8, cursor="hand2")

    # -------------------------------------------------------------- execucoes
    def _build_runs(self) -> None:
        page = tk.Frame(self.content, bg=BG)
        self.pages["execucoes"] = page
        top = tk.Frame(page, bg=BG)
        top.pack(fill="both", expand=True)

        cols = ("id", "inicio", "status", "resumo", "duracao")
        self.runs_tree = ttk.Treeview(top, columns=cols, show="headings", height=12)
        for col, label, width, anchor in (
                ("id", "#", 50, "center"), ("inicio", "Início", 150, "w"),
                ("status", "Status", 110, "w"), ("resumo", "Resumo", 560, "w"),
                ("duracao", "Duração", 80, "center")):
            self.runs_tree.heading(col, text=label)
            self.runs_tree.column(col, width=width, anchor=anchor)
        self.runs_tree.pack(fill="both", expand=True)
        self.runs_tree.bind("<<TreeviewSelect>>", self._run_selected)

        detail = Card(page, "Itens da execução")
        detail.pack(fill="both", expand=False, pady=(12, 0))
        self.run_detail = tk.Text(detail, bg="#0C141B", fg=TEXT, font=F_MONO, bd=0,
                                  height=9, wrap="word", padx=12, pady=10)
        self.run_detail.pack(fill="both", expand=True, padx=14, pady=(8, 12))
        self.run_detail.configure(state="disabled")

    # -------------------------------------------------------------------- logs
    def _build_logs(self) -> None:
        page = tk.Frame(self.content, bg=BG)
        self.pages["logs"] = page
        bar = tk.Frame(page, bg=BG)
        bar.pack(fill="x", pady=(0, 8))
        tk.Label(bar, text="Nível", bg=BG, fg=MUTED, font=F_SM).pack(side="left")
        self.log_level = tk.StringVar(value="TODOS")
        combo = ttk.Combobox(bar, textvariable=self.log_level, width=10, state="readonly",
                             values=("TODOS", "INFO", "WARN", "ERROR", "DEBUG"))
        combo.pack(side="left", padx=(6, 14))
        combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_logs())
        tk.Button(bar, text="Atualizar", command=self._refresh_logs, bg=PANEL, fg=TEXT,
                  activebackground=CARD_HI, relief="flat", bd=0, padx=14, pady=6,
                  font=F_SM, cursor="hand2").pack(side="left")
        self.log_count = tk.Label(bar, text="", bg=BG, fg=MUTED, font=F_SM)
        self.log_count.pack(side="right")

        box = Card(page)
        box.pack(fill="both", expand=True)
        self.log_text = tk.Text(box, bg="#0C141B", fg=TEXT, font=F_MONO, bd=0,
                                wrap="none", padx=12, pady=10)
        self.log_text.pack(fill="both", expand=True, padx=12, pady=10)
        for tag, color in (("INFO", INFO), ("WARN", WARN), ("ERROR", ERR),
                           ("DEBUG", MUTED), ("OK", OK)):
            self.log_text.tag_configure(tag, foreground=color)
        self.log_text.configure(state="disabled")

    # ------------------------------------------------------------ agendamentos
    def _build_schedules(self) -> None:
        page = tk.Frame(self.content, bg=BG)
        self.pages["agendamentos"] = page

        form = Card(page, "Novo / editar agendamento")
        form.pack(fill="x")
        row = tk.Frame(form, bg=CARD)
        row.pack(fill="x", padx=16, pady=(10, 6))
        tk.Label(row, text="Nome", bg=CARD, fg=MUTED, font=F_SM).pack(side="left")
        self.sch_name = tk.Entry(row, bg=PANEL, fg=TEXT, insertbackground=TEXT,
                                 relief="flat", font=F_MD, width=26)
        self.sch_name.pack(side="left", padx=(6, 16), ipady=5)
        tk.Label(row, text="Operação", bg=CARD, fg=MUTED, font=F_SM).pack(side="left")
        self.sch_kind = ttk.Combobox(row, state="readonly", width=14,
                                     values=("Completo", "Só export", "Só flash"))
        self.sch_kind.set("Completo")
        self.sch_kind.pack(side="left", padx=(6, 16))
        tk.Label(row, text="Hora", bg=CARD, fg=MUTED, font=F_SM).pack(side="left")
        self.sch_time = tk.Entry(row, bg=PANEL, fg=TEXT, insertbackground=TEXT,
                                 relief="flat", font=F_MD, width=7, justify="center")
        self.sch_time.insert(0, "02:00")
        self.sch_time.pack(side="left", padx=(6, 16), ipady=5)

        days = tk.Frame(form, bg=CARD)
        days.pack(fill="x", padx=16, pady=(0, 4))
        tk.Label(days, text="Dias", bg=CARD, fg=MUTED, font=F_SM).pack(side="left", padx=(0, 8))
        self.sch_days: dict[int, tk.BooleanVar] = {}
        for i, label in enumerate(scheduler.WEEKDAY_LABELS, start=1):
            var = tk.BooleanVar(value=True)
            self.sch_days[i] = var
            tk.Checkbutton(days, text=label, variable=var, bg=CARD, fg=TEXT,
                           selectcolor=PANEL, activebackground=CARD, font=F_SM,
                           bd=0, highlightthickness=0).pack(side="left", padx=2)

        actions = tk.Frame(form, bg=CARD)
        actions.pack(fill="x", padx=16, pady=(4, 14))
        self._action_button(actions, "Salvar agendamento", self._save_schedule,
                            primary=True).pack(side="left")
        tk.Button(actions, text="Ativar/desativar", command=self._toggle_schedule,
                  bg=PANEL, fg=TEXT, activebackground=CARD_HI, relief="flat", bd=0,
                  padx=12, pady=7, font=F_SM, cursor="hand2").pack(side="left", padx=8)
        tk.Button(actions, text="Excluir", command=self._delete_schedule,
                  bg=PANEL, fg=ERR, activebackground=CARD_HI, relief="flat", bd=0,
                  padx=12, pady=7, font=F_SM, cursor="hand2").pack(side="left")

        cols = ("id", "nome", "tipo", "hora", "dias", "proximo", "ativo")
        self.sch_tree = ttk.Treeview(page, columns=cols, show="headings", height=8)
        for col, label, width in (("id", "#", 44), ("nome", "Nome", 220),
                                  ("tipo", "Operação", 130), ("hora", "Hora", 70),
                                  ("dias", "Dias", 150), ("proximo", "Próxima", 170),
                                  ("ativo", "Ativo", 70)):
            self.sch_tree.heading(col, text=label)
            self.sch_tree.column(col, width=width, anchor="w" if width > 80 else "center")
        self.sch_tree.pack(fill="both", expand=True, pady=(12, 0))
        self.sch_tree.bind("<<TreeviewSelect>>", self._schedule_selected)

        note = tk.Label(page, bg=BG, fg=MUTED, font=F_SM, justify="left",
                        text="O agendador roda enquanto o gerenciador estiver aberto — inclusive "
                             "minimizado. Se o PC estava desligado no horário, a execução perdida "
                             "é recuperada quando o gerenciador voltar (catch-up).")
        note.pack(anchor="w", pady=(10, 0))

    # ----------------------------------------------------------------- alertas
    def _build_alerts(self) -> None:
        page = tk.Frame(self.content, bg=BG)
        self.pages["alertas"] = page
        bar = tk.Frame(page, bg=BG)
        bar.pack(fill="x", pady=(0, 8))
        tk.Button(bar, text="Reconhecer selecionado", command=self._ack_alert,
                  bg=PANEL, fg=TEXT, activebackground=CARD_HI, relief="flat", bd=0,
                  padx=14, pady=6, font=F_SM, cursor="hand2").pack(side="left")
        tk.Button(bar, text="Atualizar", command=self._refresh_alerts, bg=PANEL, fg=TEXT,
                  activebackground=CARD_HI, relief="flat", bd=0, padx=14, pady=6,
                  font=F_SM, cursor="hand2").pack(side="left", padx=8)

        cols = ("id", "ts", "sev", "titulo", "msg", "ack")
        self.alerts_tree = ttk.Treeview(page, columns=cols, show="headings", height=14)
        for col, label, width in (("id", "#", 44), ("ts", "Quando", 150),
                                  ("sev", "Sev.", 80), ("titulo", "Título", 220),
                                  ("msg", "Detalhe", 480), ("ack", "Reconhecido", 90)):
            self.alerts_tree.heading(col, text=label)
            self.alerts_tree.column(col, width=width, anchor="w" if width > 100 else "center")
        self.alerts_tree.pack(fill="both", expand=True)
        self.alerts_tree.tag_configure("critical", foreground=ERR)
        self.alerts_tree.tag_configure("warning", foreground=WARN)

    # ------------------------------------------------------------ configuracoes
    def _build_config(self) -> None:
        page = tk.Frame(self.content, bg=BG)
        self.pages["config"] = page

        card = Card(page, "Parâmetros")
        card.pack(fill="x")

        fields = [
            ("root_dir", "Raiz dos backups", "C:\\ANM2000"),
            ("anm_exe", "Executável do ANM2000 (vazio = detectar)", ""),
            ("wait_for_anm_min", "Espera pelo ANM em execuções automáticas (min)", "60"),
            ("flash_timeout_s", "Timeout do flash (s)", "300"),
            ("export_timeout_s", "Timeout do export (s)", "300"),
            ("confirm_export_min_files", "Mín. de arquivos no export", "50"),
            ("confirm_export_min_main_mb", "Tamanho mín. do anconfigdata.unl (MB)", "1.0"),
            ("min_free_mb", "Espaço livre mínimo (MB)", "500"),
            ("retain_log_days", "Retenção de logs (dias, 0 = infinito)", "365"),
            ("retain_runs_days", "Retenção do histórico (dias, 0 = infinito)", "0"),
        ]
        self.cfg_entries: dict[str, tk.Entry] = {}
        grid = tk.Frame(card, bg=CARD)
        grid.pack(fill="x", padx=18, pady=(12, 4))
        for i, (key, label, hint) in enumerate(fields):
            row, col = divmod(i, 2)
            tk.Label(grid, text=label, bg=CARD, fg=MUTED, font=F_SM,
                     anchor="w").grid(row=row, column=col * 2, sticky="w", pady=5,
                                      padx=(0 if col == 0 else 24, 10))
            entry = tk.Entry(grid, bg=PANEL, fg=TEXT, insertbackground=TEXT,
                             relief="flat", font=F_MD, width=34)
            entry.grid(row=row, column=col * 2 + 1, sticky="w", pady=5, ipady=4)
            entry.insert(0, str(self.cfg.get(key)))
            self.cfg_entries[key] = entry

        checks = tk.Frame(card, bg=CARD)
        checks.pack(fill="x", padx=18, pady=(8, 0))
        self.cfg_checks: dict[str, tk.BooleanVar] = {}
        for key, label in (
            ("flash_enabled", "Executar Save Config To Flash"),
            ("export_enabled", "Executar Export Configuration"),
            ("anm_autostart", "Abrir o ANM2000 se estiver fechado"),
            ("catch_up_enabled", "Recuperar backup perdido após reinício"),
        ):
            var = tk.BooleanVar(value=bool(self.cfg.get(key)))
            self.cfg_checks[key] = var
            tk.Checkbutton(checks, text=label, variable=var, bg=CARD, fg=TEXT,
                           selectcolor=PANEL, activebackground=CARD, font=F_SM,
                           bd=0, highlightthickness=0).pack(side="left", padx=(0, 18))

        btns = tk.Frame(card, bg=CARD)
        btns.pack(fill="x", padx=18, pady=(10, 14))
        self._action_button(btns, "Salvar", self._save_config, primary=True).pack(side="left")
        tk.Button(btns, text="Abrir pasta de backups", command=self._open_root,
                  bg=PANEL, fg=TEXT, activebackground=CARD_HI, relief="flat", bd=0,
                  padx=12, pady=7, font=F_SM, cursor="hand2").pack(side="left", padx=10)
        tk.Button(btns, text="Abrir pasta de dados", command=self._open_data,
                  bg=PANEL, fg=TEXT, activebackground=CARD_HI, relief="flat", bd=0,
                  padx=12, pady=7, font=F_SM, cursor="hand2").pack(side="left")
        tk.Button(btns, text="Encerrar o gerenciador", command=self._on_close,
                  bg=PANEL, fg=ERR, activebackground=CARD_HI, relief="flat", bd=0,
                  padx=12, pady=7, font=F_SM, cursor="hand2").pack(side="right")

        tk.Label(card, bg=CARD, fg=MUTED, font=F_SM, justify="left", wraplength=900,
                 text="Nenhuma senha é armazenada. O gerenciador usa o cliente ANM2000 "
                      "já aberto e autenticado. Os backups antigos nunca são apagados "
                      "automaticamente; a retenção vale apenas para logs e histórico."
                 ).pack(anchor="w", padx=18, pady=(0, 14))

        boot = Card(page, "Inicialização automática")
        boot.pack(fill="x", pady=(14, 0))

        line = tk.Frame(boot, bg=CARD)
        line.pack(fill="x", padx=18, pady=(12, 2))
        self.autostart_var = tk.BooleanVar(value=False)
        tk.Checkbutton(line, text="Iniciar o gerenciador com o Windows ao entrar no usuário",
                       variable=self.autostart_var, command=self._toggle_autostart,
                       bg=CARD, fg=TEXT, selectcolor=PANEL, activebackground=CARD,
                       font=F_MD, bd=0, highlightthickness=0).pack(side="left")
        self.autostart_status = tk.Label(line, text="verificando…", bg=CARD, fg=MUTED,
                                         font=F_SM)
        self.autostart_status.pack(side="left", padx=12)

        boot_actions = tk.Frame(boot, bg=CARD)
        boot_actions.pack(fill="x", padx=18, pady=(8, 4))
        tk.Button(boot_actions, text="Abrir o ANM2000 agora", command=self._open_anm,
                  bg=PANEL, fg=TEXT, activebackground=CARD_HI, relief="flat", bd=0,
                  padx=12, pady=7, font=F_SM, cursor="hand2").pack(side="left")
        tk.Button(boot_actions, text="Detectar caminho do ANM", command=self._detect_anm,
                  bg=PANEL, fg=TEXT, activebackground=CARD_HI, relief="flat", bd=0,
                  padx=12, pady=7, font=F_SM, cursor="hand2").pack(side="left", padx=10)

        tk.Label(boot, bg=CARD, fg=MUTED, font=F_SM, justify="left", wraplength=900,
                 text="A tarefa inicia a interface cerca de 40 s após o login, na sessão "
                      "do usuário. O ANM2000 não armazena a senha: após reiniciar o PC, "
                      "abra o cliente e autentique-se. Se o horário do backup passar antes "
                      "do login, o gerenciador espera pelo ANM e recupera a execução perdida."
                 ).pack(anchor="w", padx=18, pady=(4, 14))

    def _refresh_autostart_status(self) -> None:
        try:
            st = autostart.status()
        except Exception as exc:
            self.autostart_status.configure(text=f"Tarefa do Windows: erro ({exc})", fg=ERR)
            return
        if not st.get("installed"):
            self.autostart_var.set(False)
            self.autostart_status.configure(text="Tarefa do Windows: não configurada",
                                            fg=MUTED)
            return
        enabled = bool(st.get("enabled"))
        self.autostart_var.set(enabled)
        bits = ["ativa" if enabled else "desativada"]
        if st.get("next_run"):
            bits.append("próxima: " + st["next_run"])
        if st.get("last_run"):
            bits.append("última: " + st["last_run"])
        self.autostart_status.configure(text="Tarefa do Windows: " + " • ".join(bits),
                                        fg=OK if enabled else WARN)

    def _toggle_autostart(self) -> None:
        desired = bool(self.autostart_var.get())
        ok, message = autostart.set_enabled(desired)
        if not ok:
            self.autostart_var.set(not desired)
            self._append_live("ERROR", f"inicialização automática: {message}")
            messagebox.showerror("Inicialização automática", message)
        else:
            self._append_live("INFO" if desired else "WARN", message)
        self._refresh_autostart_status()

    def _open_anm(self) -> None:
        started, message = autostart.launch_anm(self.cfg)
        self._append_live("INFO" if started else "DEBUG", message)
        if not started:
            messagebox.showinfo("ANM2000", message)

    def _detect_anm(self) -> None:
        path = autostart.resolve_anm_exe(self.cfg)
        if not path:
            messagebox.showwarning("ANM2000", "Executável do ANM2000 não encontrado.\n"
                                   "Informe o caminho completo no campo acima.")
            return
        entry = self.cfg_entries["anm_exe"]
        entry.delete(0, "end")
        entry.insert(0, str(path))
        self._append_live("INFO", f"ANM2000 detectado: {path}")

    # --------------------------------------------------------------- navegacao
    def _bind_events(self) -> None:
        self.bind("<F5>", lambda e: self.refresh_all())

    def _show(self, key: str) -> None:
        for name, page in self.pages.items():
            if name == key:
                page.pack(fill="both", expand=True)
            else:
                page.pack_forget()
        for name, nav in self.navs.items():
            nav.set_active(name == key)
        titles = {"painel": ("Painel", "visão geral e execução"),
                  "execucoes": ("Execuções", "histórico confirmado"),
                  "logs": ("Logs", "eventos do gerenciador"),
                  "agendamentos": ("Agendamentos", "execuções automáticas"),
                  "alertas": ("Alertas", "pendências e falhas"),
                  "config": ("Configurações", "parâmetros do sistema")}
        title, sub = titles[key]
        self.page_title.configure(text=title)
        self.page_sub.configure(text=sub)
        if key == "execucoes":
            self._refresh_runs()
        elif key == "logs":
            self._refresh_logs()
        elif key == "agendamentos":
            self._refresh_schedules()
        elif key == "alertas":
            self._refresh_alerts()
        elif key == "config":
            self._load_config()

    # --------------------------------------------------------------- refresh
    def _initial_refresh(self) -> None:
        self.refresh_all()
        threading.Thread(target=self._probe_anm, daemon=True).start()
        self.after(15000, self._periodic)

    def _startup_notes(self) -> None:
        if self.recovered:
            self._append_live(
                "WARN",
                f"{len(self.recovered)} execução(ões) anterior(es) marcada(s) como "
                f"abortada(s) por reinício/queda do PC")
            self.refresh_all()

    def _maybe_launch_anm(self) -> None:
        """Se há agendamento ativo, abre o ANM já no logon para o usuário logar."""
        if not self.cfg.get("anm_autostart"):
            return
        try:
            anm.discover()
            return
        except anm.AnmError:
            pass
        if not any(row["enabled"] for row in self.db.schedules()):
            return
        started, message = autostart.launch_anm(self.cfg)
        self._append_live("INFO" if started else "DEBUG", message)

    def _periodic(self) -> None:
        if not self.busy:
            threading.Thread(target=self._probe_anm, daemon=True).start()
        self.after(15000, self._periodic)

    def _probe_anm(self) -> None:
        try:
            snap = anm.discover()
            self.q.put(("conn", True, f"ANM2000 conectado • pid {snap.pid}", snap.olt_names))
        except Exception as exc:
            self.q.put(("conn", False, str(exc), []))

    def refresh_all(self) -> None:
        self._refresh_stats()
        self._refresh_runs()
        self._refresh_alerts()

    def _refresh_stats(self) -> None:
        runs = self.db.recent_runs(1)
        if runs:
            row = runs[0]
            label, color = STATUS_LABEL.get(row["status"], (row["status"], MUTED))
            self.stat_last[1].configure(text=label, fg=color)
            when = (row["started_at"] or "")[:16].replace("T", " ")
            self.stat_last[2].configure(text=f"{when} • {row['summary'] or ''}"[:70])
        else:
            self.stat_last[1].configure(text="—", fg=TEXT)
            self.stat_last[2].configure(text="nenhuma execução registrada")

        today = datetime.now().strftime("%Y-%m-%d")
        with self.db.connect() as con:
            total = con.execute(
                "SELECT COUNT(*) c FROM run_items WHERE operation='flash'").fetchone()["c"]
            ok_today = con.execute(
                "SELECT COUNT(*) c FROM run_items WHERE operation='flash' AND status='succeeded' "
                "AND started_at LIKE ?", (today + "%",)).fetchone()["c"]
        self.stat_flash[1].configure(text=f"{ok_today}", fg=OK if ok_today else TEXT)
        self.stat_flash[2].configure(text=f"{total} gravações confirmadas no total")

        exp = self.db.last_success("export", "ANM2000")
        if exp:
            path = exp["artifact"] or ""
            size = ""
            try:
                files = [p for p in os.scandir(path) if p.is_file()]
                size = f"{len(files)} arquivos, {sum(f.stat().st_size for f in files)/1048576:.1f} MB"
            except OSError:
                size = "artefato indisponível"
            self.stat_export[1].configure(text=(exp["finished_at"] or "")[:10], fg=TEXT)
            self.stat_export[2].configure(text=size or os.path.basename(path))
        else:
            self.stat_export[1].configure(text="—", fg=TEXT)
            self.stat_export[2].configure(text="nenhum export confirmado")

        alerts = [a for a in self.db.recent_alerts(50) if not a["ack"]]
        self.stat_alert[1].configure(text=str(len(alerts)), fg=ERR if alerts else OK)
        self.stat_alert[2].configure(
            text=alerts[0]["title"] if alerts else "nada pendente")

        self._refresh_mini_runs()

    def _refresh_mini_runs(self) -> None:
        lines = []
        for row in self.db.recent_runs(8):
            label, _ = STATUS_LABEL.get(row["status"], (row["status"], MUTED))
            when = (row["started_at"] or "")[5:16].replace("T", " ")
            lines.append(f"{when}  {label:<12} {row['summary'] or ''}"[:64])
        self.mini_runs.configure(state="normal")
        self.mini_runs.delete("1.0", "end")
        self.mini_runs.insert("1.0", "\n".join(lines) or "sem execuções")
        self.mini_runs.configure(state="disabled")

    def _refresh_olts(self) -> None:
        try:
            snap = anm.discover()
        except Exception as exc:
            self._append_live("ERROR", f"não foi possível listar OLTs: {exc}")
            return
        checked = {name for name, var in self.olt_vars.items() if var.get()}
        for child in self.olt_box.winfo_children():
            child.destroy()
        self.olt_vars.clear()
        for name in snap.olt_names:
            var = tk.BooleanVar(value=(not checked) or (name in checked))
            self.olt_vars[name] = var
            tk.Checkbutton(self.olt_box, text=name, variable=var, bg=CARD, fg=TEXT,
                           selectcolor=PANEL, activebackground=CARD, anchor="w",
                           font=F_SM, bd=0, highlightthickness=0).pack(anchor="w")

    def _selected_olts(self) -> list[str]:
        return [n for n, v in self.olt_vars.items() if v.get()]

    # ------------------------------------------------------------ execucao
    def _ask_full(self) -> None:
        self._start(flash=True, export=True)

    def _ask_export(self) -> None:
        self._start(flash=False, export=True)

    def _ask_flash(self) -> None:
        self._start(flash=True, export=False)

    def _start(self, flash: bool, export: bool, only: list[str] | None = None,
               kind: str = "manual", confirm: bool = True,
               trigger: str = "manual", wait_anm: bool = False) -> None:
        if self.busy:
            if confirm:
                messagebox.showinfo("Em andamento", "Já existe uma execução em andamento.")
            return
        if confirm:
            parts = []
            if export:
                parts.append("Export Configuration do ANM2000")
            if flash:
                targets = only or self._selected_olts()
                if not targets:
                    messagebox.showwarning("Sem OLT", "Selecione ao menos uma OLT para o flash.")
                    return
                parts.append("Save Config To Flash em:\n  " + "\n  ".join(targets))
            if not messagebox.askyesno("Confirmar execução",
                                       "Executar agora?\n\n" + "\n\n".join(parts)):
                return
        self.busy = True
        self._set_buttons(False)
        self.progress.start(14)
        self._show("painel")
        self._append_live("INFO", "=== execução iniciada ===")
        threading.Thread(target=self._worker,
                         args=(flash, export, only, kind, trigger, wait_anm),
                         daemon=True).start()

    def _worker(self, flash: bool, export: bool, only: list[str] | None,
                kind: str, trigger: str, wait_anm: bool) -> None:
        try:
            report = self.runner.run(do_flash=flash, do_export=export, only=only,
                                     kind=kind, trigger=trigger,
                                     wait_for_anm=wait_anm)
        except Exception as exc:
            report = {"status": "aborted", "error": str(exc)}
        finally:
            self.q.put(("done", report))

    def _set_buttons(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for btn in (self.btn_run, self.btn_export, self.btn_flash):
            btn.configure(state=state)

    def _schedule_due(self, row: dict) -> None:
        # chamado pela thread do agendador: apenas enfileira para a thread da GUI
        self.q.put(("due", row))

    def _run_due(self, row: dict) -> None:
        kind = row.get("kind", "full")
        flash = kind in ("full", "flash")
        export = kind in ("full", "export")
        catch_up = bool(row.get("catch_up"))
        trigger = "catch-up" if catch_up else "scheduled"
        note = " (recuperando horário perdido)" if catch_up else ""
        self._append_live("INFO", f"agendamento disparado: {row.get('name', '?')}{note}")
        self._start(flash=flash, export=export, only=None, kind="scheduled",
                    confirm=False, trigger=trigger, wait_anm=True)

    # ------------------------------------------------------------------ fila
    def _drain(self) -> None:
        try:
            while True:
                kind, *payload = self.q.get_nowait()
                if kind == "log":
                    level, msg = payload
                    tag = {"ERROR": "ERROR", "WARN": "WARN", "DEBUG": "DEBUG"}.get(level, "INFO")
                    if "OK" in msg or "Succeed" in msg:
                        tag = "OK"
                    self._append_live(tag, msg)
                elif kind == "done":
                    self._finish(payload[0])
                elif kind == "conn":
                    self._set_conn(*payload)
                elif kind == "due":
                    self._run_due(payload[0])
                elif kind == "scheduled":
                    self._append_live("INFO", f"agendamento disparado: {payload[0]}")
        except queue.Empty:
            pass
        self.after(150, self._drain)

    def _append_live(self, tag: str, msg: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.live.configure(state="normal")
        self.live.insert("end", f"{stamp}  {msg}\n", tag)
        lines = int(self.live.index("end-1c").split(".")[0])
        if lines > 400:
            self.live.delete("1.0", "50.0")
        self.live.see("end")
        self.live.configure(state="disabled")

    def _finish(self, report: dict) -> None:
        self.busy = False
        self._set_buttons(True)
        self.progress.stop()
        status = report.get("status", "?")
        label, color = STATUS_LABEL.get(status, (status, MUTED))
        self._append_live("OK" if status == "succeeded" else "WARN",
                          f"=== execução finalizada: {label} ===")
        self.refresh_all()
        self._refresh_schedules()
        if status not in ("succeeded",):
            messagebox.showwarning("Execução " + label,
                                   f"Resultado: {label}\n\n"
                                   f"{report.get('error') or report.get('summary') or ''}")

    def _set_conn(self, connected: bool, detail: str, olts: list[str]) -> None:
        self.conn_state = connected
        self.pill.configure(text=("●  conectado" if connected else "●  desconectado"),
                            fg=OK if connected else ERR)
        self.side_status.configure(text=("●  " + detail) if connected else "●  " + detail[:46],
                                   fg=OK if connected else ERR)
        if connected and (not self.olt_vars or set(self.olt_vars) != set(olts)):
            for child in self.olt_box.winfo_children():
                child.destroy()
            self.olt_vars.clear()
            for name in olts:
                var = tk.BooleanVar(value=True)
                self.olt_vars[name] = var
                tk.Checkbutton(self.olt_box, text=name, variable=var, bg=CARD,
                               fg=TEXT, selectcolor=PANEL, activebackground=CARD,
                               anchor="w", font=F_SM, bd=0,
                               highlightthickness=0).pack(anchor="w")

    # ------------------------------------------------------------ historico
    def _refresh_runs(self) -> None:
        for item in self.runs_tree.get_children():
            self.runs_tree.delete(item)
        for row in self.db.recent_runs(50):
            start = datetime.fromisoformat(row["started_at"]) if row["started_at"] else None
            dur = ""
            if row["finished_at"] and start:
                try:
                    dur = f"{(datetime.fromisoformat(row['finished_at'])-start).total_seconds():.0f}s"
                except ValueError:
                    dur = ""
            self.runs_tree.insert("", "end", iid=str(row["id"]), values=(
                row["id"], (row["started_at"] or "")[:16].replace("T", " "),
                STATUS_LABEL.get(row["status"], (row["status"],))[0],
                row["summary"] or "", dur))

    def _run_selected(self, _=None) -> None:
        sel = self.runs_tree.selection()
        if not sel:
            return
        run_id = int(sel[0])
        lines = []
        for item in self.db.run_items(run_id):
            lines.append(f"{item['operation']:6}  {item['status']:12}  {item['target']}")
            extra = []
            if item["seconds"]:
                extra.append(f"{item['seconds']}s")
            if item["artifact"]:
                extra.append(item["artifact"])
            if extra:
                lines.append("        " + "  |  ".join(extra))
            if item["detail"]:
                lines.append(f"        {item['detail'][:400]}")
        self.run_detail.configure(state="normal")
        self.run_detail.delete("1.0", "end")
        self.run_detail.insert("1.0", "\n".join(lines) or "sem itens")
        self.run_detail.configure(state="disabled")

    # ------------------------------------------------------------------ logs
    def _refresh_logs(self) -> None:
        level = self.log_level.get()
        rows = self.db.recent_logs(400)
        if level != "TODOS":
            rows = [r for r in rows if r["level"] == level]
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        for row in reversed(rows):
            self.log_text.insert("end", f"{row['ts'].replace('T', ' ')}  {row['level']:5}  "
                                        f"{row['message']}\n", row["level"])
        self.log_text.configure(state="disabled")
        self.log_count.configure(text=f"{len(rows)} eventos")

    # ----------------------------------------------------------- agendamentos
    def _refresh_schedules(self) -> None:
        for item in self.sch_tree.get_children():
            self.sch_tree.delete(item)
        for row in self.db.schedules():
            days = ",".join(scheduler.WEEKDAY_LABELS[int(d) - 1]
                            for d in str(row["weekdays"]).split(",") if d.isdigit())
            self.sch_tree.insert("", "end", iid=str(row["id"]), values=(
                row["id"], row["name"], row["kind"], row["at_time"], days,
                (row["next_run_at"] or "").replace("T", " ")[:16],
                "sim" if row["enabled"] else "não"))

    def _schedule_selected(self, _=None) -> None:
        sel = self.sch_tree.selection()
        if not sel:
            return
        row = next((r for r in self.db.schedules() if str(r["id"]) == sel[0]), None)
        if not row:
            return
        self.sch_name.delete(0, "end")
        self.sch_name.insert(0, row["name"])
        self.sch_kind.set({"full": "Completo", "export": "Só export",
                           "flash": "Só flash"}.get(row["kind"], "Completo"))
        self.sch_time.delete(0, "end")
        self.sch_time.insert(0, row["at_time"])
        chosen = {int(d) for d in str(row["weekdays"]).split(",") if d.isdigit()}
        for day, var in self.sch_days.items():
            var.set(day in chosen)

    def _save_schedule(self) -> None:
        name = self.sch_name.get().strip()
        at = self.sch_time.get().strip()
        try:
            hh, mm = [int(x) for x in at.split(":")]
            assert 0 <= hh < 24 and 0 <= mm < 60
        except Exception:
            messagebox.showerror("Hora inválida", "Use o formato HH:MM (ex.: 02:30).")
            return
        if not name:
            messagebox.showerror("Nome obrigatório", "Informe um nome para o agendamento.")
            return
        days = [str(d) for d, var in self.sch_days.items() if var.get()]
        if not days:
            messagebox.showerror("Dias", "Selecione ao menos um dia.")
            return
        kind = {"Completo": "full", "Só export": "export",
                "Só flash": "flash"}[self.sch_kind.get()]
        sid = self.db.upsert_schedule(name, kind, f"{hh:02d}:{mm:02d}", ",".join(days))
        nxt = scheduler.next_occurrence(f"{hh:02d}:{mm:02d}", ",".join(days))
        if nxt:
            self.db.set_schedule_run(sid, "", nxt.isoformat(timespec="seconds"))
        self._refresh_schedules()
        self._append_live("INFO", f"agendamento salvo: {name} às {at}")

    def _toggle_schedule(self) -> None:
        sel = self.sch_tree.selection()
        if not sel:
            return
        with self.db.connect() as con:
            con.execute("UPDATE schedules SET enabled = 1 - enabled WHERE id=?", (int(sel[0]),))
        self._refresh_schedules()

    def _delete_schedule(self) -> None:
        sel = self.sch_tree.selection()
        if not sel:
            return
        if messagebox.askyesno("Excluir", "Excluir este agendamento?"):
            with self.db.connect() as con:
                con.execute("DELETE FROM schedules WHERE id=?", (int(sel[0]),))
            self._refresh_schedules()

    # ---------------------------------------------------------------- alertas
    def _refresh_alerts(self) -> None:
        for item in self.alerts_tree.get_children():
            self.alerts_tree.delete(item)
        for row in self.db.recent_alerts(80):
            self.alerts_tree.insert("", "end", iid=str(row["id"]), values=(
                row["id"], (row["ts"] or "")[:16].replace("T", " "), row["severity"],
                row["title"], (row["message"] or "")[:200],
                "sim" if row["ack"] else "não"),
                tags=(row["severity"],))

    def _ack_alert(self) -> None:
        sel = self.alerts_tree.selection()
        if not sel:
            return
        with self.db.connect() as con:
            con.execute("UPDATE alerts SET ack=1 WHERE id=?", (int(sel[0]),))
        self._refresh_alerts()
        self._refresh_stats()

    # ------------------------------------------------------------ configuracoes
    def _load_config(self) -> None:
        for key, entry in self.cfg_entries.items():
            value = self.cfg.get(key)
            if key == "anm_exe" and not value:
                detected = autostart.resolve_anm_exe(self.cfg)
                value = str(detected) if detected else ""
            entry.delete(0, "end")
            entry.insert(0, str(value or ""))
        for key, var in self.cfg_checks.items():
            var.set(bool(self.cfg.get(key)))
        self._refresh_autostart_status()

    def _save_config(self) -> None:
        try:
            for key, entry in self.cfg_entries.items():
                current = self.cfg.get(key)
                raw = entry.get().strip()
                if isinstance(current, bool):
                    value = raw.lower() in ("1", "true", "sim", "yes")
                elif isinstance(current, int):
                    value = int(raw)
                elif isinstance(current, float):
                    value = float(raw)
                else:
                    value = raw
                self.cfg.set(key, value)
            for key, var in self.cfg_checks.items():
                self.cfg.set(key, bool(var.get()))
        except ValueError:
            messagebox.showerror("Valor inválido", "Verifique os campos numéricos.")
            return
        try:
            self.scheduler.catch_up = bool(self.cfg.get("catch_up_enabled"))
        except Exception:
            pass
        self._append_live("INFO", "configurações salvas")
        messagebox.showinfo("Configurações", "Parâmetros salvos.")

    def _open_root(self) -> None:
        path = str(self.cfg.root)
        os.makedirs(path, exist_ok=True)
        os.startfile(path)  # noqa: S606

    def _open_data(self) -> None:
        os.startfile(str(config.data_dir()))  # noqa: S606

    # ------------------------------------------------------------------ close
    def _force_exit(self) -> None:
        try:
            self.scheduler.stop()
        except Exception:
            pass
        self.destroy()

    def _on_close(self) -> None:
        if self.busy:
            if not messagebox.askyesno(
                    "Execução em andamento",
                    "Há uma execução em andamento. Fechar mesmo assim?"):
                return
            self._force_exit()
            return

        enabled = [s for s in self.db.schedules() if s["enabled"]]
        if enabled:
            answer = messagebox.askyesnocancel(
                "Manter em segundo plano?",
                "Existem agendamentos ativos.\n\n"
                "Sim  →  minimizar e continuar rodando em segundo plano\n"
                "Não  →  encerrar o gerenciador\n"
                "Cancelar  →  voltar à janela")
            if answer is None:
                return
            if answer:
                if not self._bg_hint_shown:
                    self._bg_hint_shown = True
                    messagebox.showinfo(
                        "Continuando em segundo plano",
                        "O gerenciador continua ativo e os agendamentos serão executados.\n\n"
                        "Para reabrir, clique no ícone da barra de tarefas ou no atalho\n"
                        "da área de trabalho.\n\n"
                        "Para encerrar de verdade: Configurações → Encerrar o gerenciador.")
                self.iconify()
                return
        self._force_exit()


def _existing_window() -> int:
    for hwnd, _cls, text in winapi.enum_windows():
        if "ANM2000 Backup Manager" in text:
            return hwnd
    return 0


def run_gui(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # comandos usados pelo instalador (executam sem abrir a interface)
    if "--enable-autostart" in argv:
        ok, _message = autostart.enable()
        return 0 if ok else 2
    if "--disable-autostart" in argv:
        ok, _message = autostart.disable()
        return 0 if ok else 2
    if "--remove-autostart" in argv:
        ok, _message = autostart.remove()
        return 0 if ok else 2
    _dpi()
    existing = _existing_window()
    if existing:
        winapi.bring_to_front(existing)
        return 0
    app = App()
    app.mainloop()
    return 0
