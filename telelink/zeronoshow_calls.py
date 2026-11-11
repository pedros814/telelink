"""ZeroNoShow bridge — calls: ZeroNoShow asks, the PC calls from the iPhone through Phone Link (kept minimised).

Loop (own thread, so a call starts within ~1 s even while SMS are being processed):
  POST /api/telelink/appels/attente   long-poll (≤ 25 s) → {appel: {id, numero}} | {appel: null}
  POST /api/telelink/appels/etat      numerotation → en_ligne (every second, answer says if ZeroNoShow
                                      asked to hang up) → termine | echec
"en_ligne" means Phone Link shows an ongoing call (ringing or answered: Phone Link does not tell).
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Callable

MAX_CALL_SECONDS = 4 * 3600
END_CONFIRMATIONS = 2  # consecutive checks without an ongoing call before declaring it over


def default_dialer() -> Any:
    from telelink import phone_link_dial as d

    return SimpleNamespace(
        dial=d.dial,
        in_call=d.in_call,
        hang_up=d.hang_up,
        minimize_all=d.minimize_all,
        last_call_duration=d.last_call_duration,
    )


def handle_call(
    appel: dict[str, Any],
    config: dict[str, Any],
    settings: dict[str, Any],
    *,
    post: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]],
    dialer: Any,
    log: Callable[[str], None] = print,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> str:
    """Run one call end to end. Returns the final status ('termine' | 'echec')."""
    call_id = str(appel["id"])
    numero = str(appel["numero"])

    def report(statut: str, **extra: Any) -> dict[str, Any]:
        try:
            return post(settings, "/api/telelink/appels/etat", {"id": call_id, "statut": statut, **extra}) or {}
        except Exception:  # noqa: BLE001 — the call goes on even if the server blinks
            return {}

    if report("numerotation").get("raccrocher"):
        report("echec", erreur="Annulé avant la numérotation")
        return "echec"

    started_wall = datetime.now(timezone.utc)
    ok, detail = dialer.dial(numero, config)
    if not ok:
        log(f"[zns] call  ✗ {numero[:4]}****  ({detail})")
        report("echec", erreur=detail)
        return "echec"

    log(f"[zns] call  → {numero[:4]}****")
    _call_hidden(True)
    try:
        return _follow_call(call_id, numero, config, report=report, dialer=dialer, log=log, sleep=sleep, now=now, started_wall=started_wall)
    finally:
        _call_hidden(False)


def _call_hidden(active: bool) -> None:
    try:
        from telelink.phone_link_hide import set_call_active

        set_call_active(active)
    except Exception:  # noqa: BLE001
        pass


def _follow_call(call_id, numero, config, *, report, dialer, log, sleep, now, started_wall) -> str:
    start = now()
    misses = 0
    hangup_sent = False
    last_minimize = start
    while now() - start < MAX_CALL_SECONDS:
        resp = report("en_ligne")
        if resp.get("raccrocher") and not hangup_sent:
            hangup_sent = dialer.hang_up(config)
        if dialer.in_call(config):
            misses = 0
        else:
            misses += 1
            if misses >= END_CONFIRMATIONS:
                break
        if now() - last_minimize > 5:
            dialer.minimize_all(config)  # Phone Link may pop its window back up (answer, etc.)
            last_minimize = now()
        sleep(1.0)
    else:
        dialer.hang_up(config)

    elapsed = int(now() - start)
    duration = dialer.last_call_duration(config, numero, started_wall)
    report("termine", dureeS=duration if duration is not None else elapsed)
    log(f"[zns] call  ✓ terminé ({duration if duration is not None else elapsed}s)")
    return "termine"


def calls_loop(
    get_config: Callable[[], dict[str, Any]],
    settings_for: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    post: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]],
    stop: threading.Event,
    dialer: Any | None = None,
    log: Callable[[str], None] = print,
) -> None:
    dialer = dialer or default_dialer()
    while not stop.is_set():
        try:
            config = get_config()
            settings = settings_for(config)
            data = post({**settings, "timeout_seconds": 35}, "/api/telelink/appels/attente", {})
            appel = data.get("appel") if isinstance(data, dict) else None
            if appel:
                handle_call(appel, config, settings, post=post, dialer=dialer, log=log)
        except Exception as exc:  # noqa: BLE001 — keep the thread alive
            log(f"[zns] calls: {exc}")
            stop.wait(5)


def start_calls_thread(
    get_config: Callable[[], dict[str, Any]],
    settings_for: Callable[[dict[str, Any]], dict[str, Any]],
    post: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]],
) -> threading.Event:
    stop = threading.Event()
    threading.Thread(
        target=calls_loop,
        args=(get_config, settings_for),
        kwargs={"post": post, "stop": stop},
        name="zns-calls",
        daemon=True,
    ).start()
    return stop
