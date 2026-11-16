"""Cria o atalho da area de trabalho para o ANM2000 Backup Manager."""
import os
import subprocess
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHONW = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
if not os.path.exists(PYTHONW):
    PYTHONW = sys.executable
ICON = os.path.join(PROJECT, "assets", "app.ico")
GUI = os.path.join(PROJECT, "gui.py")
NAME = "ANM2000 Backup Manager.lnk"

script = f"""
$ws = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$path = Join-Path $desktop '{NAME}'
$lnk = $ws.CreateShortcut($path)
$lnk.TargetPath = '{PYTHONW}'
$lnk.Arguments = '"{GUI}"'
$lnk.WorkingDirectory = '{PROJECT}'
$lnk.IconLocation = '{ICON}'
$lnk.Description = 'Backup automatico ANM2000 (flash das OLTs + export de configuracao)'
$lnk.WindowStyle = 1
$lnk.Save()
Write-Output $path
"""
result = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                        capture_output=True, text=True)
print(result.stdout.strip() or result.stderr.strip())
