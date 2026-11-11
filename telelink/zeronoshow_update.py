"""Mise à jour automatique du pont depuis ZeroNoShow (sans changer le jeton).

Au démarrage puis toutes les 6 h :
1. empreinte locale des fichiers du pont (même calcul que le serveur : chemins + contenus) ;
2. empreinte servie par ZeroNoShow (POST /api/telelink/bridge/version) ;
3. si elles diffèrent : téléchargement du paquet (GET /api/telelink/bridge), contrôle, sauvegarde des
   fichiers remplacés dans data/backup-maj-…, copie (jamais data/, .venv/, config.yaml), dépendances si
   requirements.txt a changé, puis redémarrage du pont.

Jamais pendant un envoi ou un appel (UI_LOCK). En cas d'échec : le pont continue avec sa version actuelle.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

CHECK_EVERY_S = 6 * 3600
# Même exclusion que le serveur (src/server/sms/telelink-bundle.ts).
EXCLUDED = re.compile(r"(^|/)(\.venv|data|__pycache__|node_modules|\.git)(/|$)|(^|/)config(\.local)?\.yaml$|\.py[cod]$")


def install_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def list_files(root: Path) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        dirnames[:] = [d for d in dirnames if not EXCLUDED.search(f"{rel_dir}/{d}".lstrip("/"))]
        for name in filenames:
            rel = f"{rel_dir}/{name}".lstrip("/")
            if not EXCLUDED.search(rel):
                out.append(rel)
    return sorted(out)


def local_version(root: Path | None = None) -> str:
    root = root or install_dir()
    h = hashlib.sha256()
    for rel in list_files(root):
        h.update(rel.encode("utf-8") + b"\0")
        h.update((root / rel).read_bytes())
        h.update(b"\0")
    return h.hexdigest()[:16]


_VERSION_CACHE: str | None = None


def announced_version(root: Path) -> str:
    """Version enregistrée à la dernière mise à jour (data/version_pont.txt), sinon l'empreinte du dossier.

    L'empreinte seule peut différer à cause de fichiers propres au PC (ex. dump.txt) alors que le pont
    est à jour : ZeroNoShow afficherait « mise à jour en attente » à tort.
    """
    stamp = root / "data" / "version_pont.txt"
    try:
        value = stamp.read_text(encoding="utf-8").strip() if stamp.exists() else ""
        return value or local_version(root)
    except Exception:  # noqa: BLE001
        return "inconnue"


def current_version() -> str:
    """Version annoncée au serveur par ce pont (calculée une fois par démarrage)."""
    global _VERSION_CACHE
    if _VERSION_CACHE is None:
        _VERSION_CACHE = announced_version(install_dir())
    return _VERSION_CACHE


def _download_bundle(settings: dict[str, Any]) -> bytes:
    req = urllib.request.Request(
        settings["url"] + "/api/telelink/bridge",
        method="GET",
        headers={"Authorization": f"Bearer {settings['token']}", "User-Agent": "TeleLink-ZeroNoShow-Bridge/update"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def apply_bundle(data: bytes, root: Path, *, log: Callable[[str], None] = print) -> list[str]:
    """Extrait le paquet par-dessus l'installation. Retourne les fichiers modifiés."""
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for m in tar.getmembers():
                name = m.name.replace("\\", "/")
                if not m.isfile() or name.startswith("/") or ".." in name.split("/") or EXCLUDED.search(name):
                    continue  # jamais en dehors du dossier, jamais data/.venv/config
                target = staging / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(m) as src, open(target, "wb") as dst:  # type: ignore[union-attr]
                    shutil.copyfileobj(src, dst)
        if not (staging / "telelink" / "__init__.py").exists() or not (staging / "telelink" / "zeronoshow_bridge.py").exists():
            raise RuntimeError("paquet incomplet : mise à jour annulée")

        changed = [rel for rel in list_files(staging)
                   if not (root / rel).exists() or (root / rel).read_bytes() != (staging / rel).read_bytes()]
        if not changed:
            return []
        backup = root / "data" / f"backup-maj-{datetime.now():%Y%m%d-%H%M%S}"
        for rel in changed:
            dst = root / rel
            if dst.exists():
                (backup / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, backup / rel)
        for rel in changed:
            dst = root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(staging / rel, dst)
        log(f"[zns] mise à jour : {len(changed)} fichier(s), sauvegarde dans {backup.name}")
        return changed


def _pip_install(root: Path, log: Callable[[str], None]) -> None:
    python = root / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = Path(sys.executable)
    try:
        subprocess.run([str(python), "-m", "pip", "install", "-r", str(root / "requirements.txt"), "--quiet"],
                       check=False, timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as exc:  # noqa: BLE001
        log(f"[zns] dépendances non mises à jour : {exc}")


def restart_bridge(root: Path) -> None:
    """Relance le pont dans une nouvelle fenêtre réduite, puis termine celui-ci."""
    if sys.platform == "win32":
        subprocess.Popen(
            'cmd /c start "ZeroNoShow - pont iPhone" /min cmd /c "timeout /t 4 /nobreak >nul & zeronoshow-bridge.bat"',
            cwd=str(root), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    os._exit(4)  # libère le verrou d'instance unique : la nouvelle instance prend le relais


def check_and_update(settings: dict[str, Any], *, post: Callable[..., dict[str, Any]], log: Callable[[str], None] = print,
                     download: Callable[[dict[str, Any]], bytes] = _download_bundle, root: Path | None = None) -> str:
    """'a_jour' | 'mis_a_jour' | 'occupe' | 'erreur:…' — ne redémarre pas lui-même."""
    from telelink.phone_link_dial import UI_LOCK

    root = root or install_dir()
    try:
        remote = str(post(settings, "/api/telelink/bridge/version", {}).get("version") or "")
    except Exception as exc:  # noqa: BLE001
        return f"erreur:{exc}"
    stamp = root / "data" / "version_pont.txt"
    applied = stamp.read_text(encoding="utf-8").strip() if stamp.exists() else ""
    if not remote or remote == applied or remote == local_version(root):
        return "a_jour"
    if not UI_LOCK.acquire(blocking=False):
        return "occupe"  # un envoi ou un appel est en cours : on réessaiera
    try:
        before_req = (root / "requirements.txt").read_bytes() if (root / "requirements.txt").exists() else b""
        changed = apply_bundle(download(settings), root, log=log)
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(remote, encoding="utf-8")
        if not changed:
            return "a_jour"
        if (root / "requirements.txt").exists() and (root / "requirements.txt").read_bytes() != before_req:
            _pip_install(root, log)
        return "mis_a_jour"
    except Exception as exc:  # noqa: BLE001 — l'ancienne version continue
        log(f"[zns] mise à jour impossible : {exc}")
        return f"erreur:{exc}"
    finally:
        UI_LOCK.release()


def start_update_thread(get_settings: Callable[[], dict[str, Any]], post: Callable[..., dict[str, Any]],
                        *, log: Callable[[str], None] = print) -> threading.Event:
    stop = threading.Event()

    def _run() -> None:
        stop.wait(20)  # laisser le pont démarrer
        while not stop.is_set():
            result = check_and_update(get_settings(), post=post, log=log)
            if result == "mis_a_jour":
                log("[zns] nouvelle version installée : redémarrage du pont")
                time.sleep(1)
                restart_bridge(install_dir())
            stop.wait(300 if result == "occupe" else CHECK_EVERY_S)

    threading.Thread(target=_run, name="zns-update", daemon=True).start()
    return stop


# ---------------------------------------------------------------- instance unique

_MUTEX_HANDLE = None


def acquire_single_instance(name: str = "Local\\ZeroNoShowPontTeleLink") -> bool:
    """False si un autre pont tourne déjà pour cet utilisateur (relance auto + démarrage = jamais deux ponts)."""
    global _MUTEX_HANDLE
    if sys.platform != "win32":
        return True
    import ctypes

    k32 = ctypes.windll.kernel32
    k32.CreateMutexW.restype = ctypes.c_void_p
    handle = k32.CreateMutexW(None, False, name)
    if not handle:
        return True
    if k32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        k32.CloseHandle(ctypes.c_void_p(handle))
        return False
    _MUTEX_HANDLE = handle
    return True


# ---------------------------------------------------------------- relance automatique

WATCHDOG_TASK = "ZeroNoShow - pont iPhone"


def watchdog_task_exists() -> bool:
    if sys.platform != "win32":
        return True
    r = subprocess.run(["schtasks", "/Query", "/TN", WATCHDOG_TASK], capture_output=True, text=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.returncode == 0


def install_watchdog_task(root: Path | None = None) -> tuple[bool, str]:
    """Tâche Windows de l'utilisateur : à l'ouverture de session et toutes les 5 min, relance le pont s'il
    ne tourne pas (scripts/zns-relance.vbs, invisible). Sans droits administrateur."""
    if sys.platform != "win32":
        return False, "Windows uniquement"
    root = root or install_dir()
    vbs = root / "scripts" / "zns-relance.vbs"
    if not vbs.exists():
        return False, f"{vbs} introuvable"
    ps = f"""
$ErrorActionPreference = 'Stop'
$act = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument '"{vbs}"' -WorkingDirectory '{root}'
$t1 = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$t2 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
$set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew
$pr = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName '{WATCHDOG_TASK}' -Action $act -Trigger $t1,$t2 -Settings $set -Principal $pr -Description 'Relance le pont ZeroNoShow (iPhone, SMS, WhatsApp) s il ne tourne pas.' -Force | Out-Null
"""
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                       capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.returncode == 0, (r.stderr or r.stdout).strip()[:300]


def ensure_watchdog_task(*, log: Callable[[str], None] = print) -> None:
    try:
        if not watchdog_task_exists():
            ok, detail = install_watchdog_task()
            log("[zns] relance automatique installée" if ok else f"[zns] relance automatique non installée : {detail}")
    except Exception as exc:  # noqa: BLE001
        log(f"[zns] relance automatique : {exc}")

