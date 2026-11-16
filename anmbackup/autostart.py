"""Inicializacao automatica com o Windows (Tarefa Agendada) e ANM2000.

A tarefa roda no logon do usuario, na sessao interativa, porque a automacao
depende do cliente ANM2000 visivel. Nenhuma credencial e guardada aqui: se o
cliente estiver fechado nos apenas o abrimos; a autenticacao segue manual.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

from . import winapi

TASK_NAME = os.environ.get("ANM2000BM_TASK_NAME") or "ANM2000 Backup Manager"
LEGACY_TASKS = () if os.environ.get("ANM2000BM_TASK_NAME") else (
    "CHNET ANM2000 Backup Manager",
)
TASK_DESC = "Abre o ANM2000 Backup Manager no logon do usuario."
TASK_DELAY = "PT40S"
APP_EXE_NAME = "ANM2000 Backup Manager.exe"

ANM_EXE_NAMES = ("anms.exe", "anmse.exe")
ANM_CANDIDATES = (
    r"D:\AEMS_Client\Client\bin\anms.exe",
    r"C:\AEMS_Client\Client\bin\anms.exe",
    r"D:\AEMS\Client\bin\anms.exe",
    r"C:\AEMS\Client\bin\anms.exe",
    r"D:\fhanms\bin\anms.exe",
)


# ------------------------------------------------------------------- caminhos
def project_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def pythonw() -> Path:
    """pythonw.exe (sem console) ao lado do interpretador atual."""
    current = Path(sys.executable)
    candidate = current.with_name("pythonw.exe")
    if candidate.is_file():
        return candidate
    return current


def gui_executable() -> Path:
    """Executavel da interface (o proprio exe quando congelado ou o pythonw no fonte)."""
    if not getattr(sys, "frozen", False):
        return pythonw()
    exe = Path(sys.executable).resolve()
    candidate = exe.with_name(APP_EXE_NAME)
    return candidate if candidate.is_file() else exe


def launcher() -> tuple[str, str]:
    """(executavel, argumentos) da acao agendada."""
    if getattr(sys, "frozen", False):
        return str(gui_executable()), ""
    return str(gui_executable()), f'"{project_dir() / "gui.py"}"'


# ------------------------------------------------------------------ powershell
def _q(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _ps(script: str, timeout: float = 60.0) -> subprocess.CompletedProcess:
    prefix = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
    encoded = base64.b64encode((prefix + script).encode("utf-16-le")).decode("ascii")
    try:
        return subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-EncodedCommand", encoded],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess([], 1, "", str(exc))


def _ok_result(result: subprocess.CompletedProcess) -> tuple[bool, str]:
    if result.returncode == 0:
        return True, (result.stdout or "OK").strip()
    detail = (result.stderr or result.stdout or "falha ao falar com o Agendador de Tarefas").strip()
    return False, detail[:600]


# ---------------------------------------------------------------------- tarefa
def status() -> dict:
    """Estado da tarefa de logon (nao altera nada)."""
    script = f"""
$ErrorActionPreference = 'SilentlyContinue'
$t = Get-ScheduledTask -TaskName {_q(TASK_NAME)}
if (-not $t) {{ Write-Output '{{"installed":false}}'; exit 0 }}
$i = Get-ScheduledTaskInfo -TaskName {_q(TASK_NAME)}
$last = ''
if ($i.LastRunTime -and $i.LastRunTime.Year -gt 2000) {{ $last = $i.LastRunTime.ToString('yyyy-MM-dd HH:mm:ss') }}
$next = ''
if ($i.NextRunTime -and $i.NextRunTime.Year -gt 2000) {{ $next = $i.NextRunTime.ToString('yyyy-MM-dd HH:mm:ss') }}
$action = ''
if ($t.Actions.Count -gt 0) {{ $action = [string]$t.Actions[0].Execute + ' ' + [string]$t.Actions[0].Arguments }}
[pscustomobject]@{{
    installed = $true
    enabled = ([string]$t.State -ne 'Disabled')
    state = [string]$t.State
    last_run = $last
    next_run = $next
    last_result = [int]$i.LastTaskResult
    action = $action.Trim()
}} | ConvertTo-Json -Compress
"""
    result = _ps(script)
    if result.returncode != 0:
        return {"installed": False, "error": (result.stderr or result.stdout).strip()[:400]}
    raw = (result.stdout or "").strip().splitlines()
    if not raw:
        return {"installed": False}
    try:
        return json.loads(raw[-1])
    except ValueError:
        return {"installed": False, "error": raw[-1][:400]}


def enable() -> tuple[bool, str]:
    """Cria/atualiza a tarefa de logon apontando para este projeto."""
    exe, args = launcher()
    arg_clause = f"-Argument {_q(args)}" if args else ""
    script = f"""
$ErrorActionPreference = 'Stop'
$user = "$env:USERDOMAIN\\$env:USERNAME"
$legacy = @({", ".join(_q(name) for name in LEGACY_TASKS)})
foreach ($name in $legacy) {{ Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue | Out-Null }}
$action = New-ScheduledTaskAction -Execute {_q(exe)} {arg_clause} -WorkingDirectory {_q(str(project_dir()))}
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$trigger.Delay = {_q(TASK_DELAY)}
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName {_q(TASK_NAME)} -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description {_q(TASK_DESC)} -Force | Out-Null
Write-Output 'OK'
"""
    ok, msg = _ok_result(_ps(script))
    return ok, ("inicialização com o Windows ativada" if ok else msg)


def disable() -> tuple[bool, str]:
    st = status()
    if not st.get("installed"):
        return True, "tarefa não instalada"
    script = f"""
$ErrorActionPreference = 'Stop'
Disable-ScheduledTask -TaskName {_q(TASK_NAME)} | Out-Null
Write-Output 'OK'
"""
    ok, msg = _ok_result(_ps(script))
    return ok, ("inicialização com o Windows desativada" if ok else msg)


def set_enabled(enabled: bool) -> tuple[bool, str]:
    if enabled:
        st = status()
        if st.get("installed") and st.get("enabled"):
            return True, "inicialização com o Windows já está ativa"
        if st.get("installed"):
            script = f"""
$ErrorActionPreference = 'Stop'
Enable-ScheduledTask -TaskName {_q(TASK_NAME)} | Out-Null
Write-Output 'OK'
"""
            ok, msg = _ok_result(_ps(script))
            return ok, ("inicialização com o Windows ativada" if ok else msg)
        return enable()
    return disable()


def _task_execute() -> str:
    """Executavel configurado na acao da tarefa ('' quando nao ha tarefa)."""
    script = f"""
$t = Get-ScheduledTask -TaskName {_q(TASK_NAME)} -ErrorAction SilentlyContinue
if ($t -and $t.Actions.Count -gt 0) {{ Write-Output ([string]$t.Actions[0].Execute) }}
"""
    result = _ps(script)
    lines = (result.stdout or "").strip().splitlines()
    return lines[-1].strip() if lines else ""


def _same_target(expected: str, actual: str) -> bool:
    """Compara caminhos de executaveis ignorando caixa, aspas e variaveis."""
    def norm(value: str) -> str:
        text = os.path.expandvars(str(value).strip().strip('"'))
        return os.path.normcase(os.path.normpath(text))

    return bool(actual) and norm(expected) == norm(actual)


def remove() -> tuple[bool, str]:
    """Remove a tarefa de logon somente se ela apontar para esta instalacao."""
    st = status()
    if not st.get("installed"):
        return True, "tarefa não instalada"
    exe, _args = launcher()
    current = _task_execute()
    if not _same_target(exe, current):
        return True, (f"tarefa de outra instalação preservada ({current or 'desconhecida'})")
    script = f"""
$ErrorActionPreference = 'Stop'
Unregister-ScheduledTask -TaskName {_q(TASK_NAME)} -Confirm:$false
Write-Output 'OK'
"""
    ok, msg = _ok_result(_ps(script))
    return ok, ("tarefa removida" if ok else msg)


# ------------------------------------------------------------------------ ANM
def resolve_anm_exe(cfg=None) -> Path | None:
    """Executavel do ANM2000: configuracao > processo aberto > locais conhecidos."""
    if cfg is not None:
        configured = str(cfg.get("anm_exe") or "").strip().strip('"')
        if configured:
            path = Path(configured)
            if path.is_file():
                return path
    for name in ANM_EXE_NAMES:
        for path in winapi.find_process_paths(name):
            candidate = Path(path)
            if candidate.is_file():
                return candidate
    for path in ANM_CANDIDATES:
        candidate = Path(path)
        if candidate.is_file():
            return candidate
    return None


def anm_running() -> bool:
    return any(winapi.find_process_ids(name) for name in ANM_EXE_NAMES)


def launch_anm(cfg=None) -> tuple[bool, str]:
    """Abre o cliente ANM2000 se ele nao estiver em execucao (sem credenciais)."""
    if anm_running():
        return False, "ANM2000 já está em execução; aguardando autenticação"
    exe = resolve_anm_exe(cfg)
    if not exe:
        return False, ("ANM2000 não localizado; informe o executável em "
                       "Configurações → Executável do ANM2000")
    workdir = ""
    if cfg is not None:
        workdir = str(cfg.get("anm_workdir") or "").strip().strip('"')
    cwd = workdir if workdir and Path(workdir).is_dir() else str(exe.parent)
    try:
        subprocess.Popen(
            [str(exe)], cwd=cwd, close_fds=True,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
        )
    except OSError as exc:
        return False, f"falha ao iniciar o ANM2000: {exc}"
    return True, (f"ANM2000 iniciado ({exe}); autentique-se no cliente para "
                  f"liberar os backups")
