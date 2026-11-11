"""Find a control in a Phone Link window, whatever pywinauto object we hold.

``find_phone_link_window`` returns a ``UIAWrapper`` (from ``Desktop().windows()``), which has no
``child_window()``: calling it raised AttributeError, silently caught, so buttons were never found
and the code fell back to pressing Enter blindly. This helper works with both a
``WindowSpecification`` (``child_window``) and a wrapper (``descendants``).
"""

from __future__ import annotations

import re
from typing import Any


def _matches(el: Any, spec: dict[str, str]) -> bool:
    info = el.element_info
    name = str(getattr(info, "name", "") or "")
    auto_id = str(getattr(info, "automation_id", "") or "")
    ctrl = str(getattr(info, "control_type", "") or "")
    cls = str(getattr(info, "class_name", "") or "")
    if "control_type" in spec and ctrl != spec["control_type"]:
        return False
    if "title" in spec and name != spec["title"]:
        return False
    if "title_re" in spec and not re.search(spec["title_re"], name):
        return False
    if "auto_id" in spec and auto_id != spec["auto_id"]:
        return False
    if "auto_id_re" in spec and not re.search(spec["auto_id_re"], auto_id):
        return False
    if "class_name" in spec and cls != spec["class_name"]:
        return False
    return True


def find_control(win: Any, spec: dict[str, str], *, timeout: float = 0.3) -> Any | None:
    """First control matching ``spec`` (keys: title, title_re, auto_id, auto_id_re, control_type, class_name)."""
    if win is None:
        return None
    if hasattr(win, "child_window"):
        try:
            ctl = win.child_window(**spec)
            if ctl.exists(timeout=timeout):
                return ctl.wrapper_object()
        except Exception:  # noqa: BLE001
            pass
    try:
        kwargs = {"control_type": spec["control_type"]} if "control_type" in spec else {}
        for el in win.descendants(**kwargs):
            try:
                if _matches(el, spec):
                    return el
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return None


def press(ctl: Any) -> bool:
    """Invoke (UIA) first — works off-screen, no mouse — then a real click as last resort."""
    for method in ("invoke", "click", "click_input"):
        fn = getattr(ctl, method, None)
        if fn is None:
            continue
        try:
            fn()
            return True
        except Exception:  # noqa: BLE001
            continue
    return False
