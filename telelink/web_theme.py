"""TeleLink web UI theme — mirrors chalk.py baby-blue terminal palette."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

# Hex equivalents of telelink/chalk.py ANSI 256 palette
BG = "#000000"
SURFACE = "#0a0a0a"
BORDER = "#1e3a47"
BABY = "#87d7ff"
LIGHT = "#afd7ff"
VALUE = "#d7ffff"
MUTED = "#5fafd7"
TEXT = "#f0f0f0"
BADGE_FG = "#101010"

_PHONE_ART = """\
──▄▄██████▄▄
▄██▀▄█▄▄█▄▀██▄
▀▀▀▄██▀▀██▄▀▀▀
─▄███─██─███▄
─█████▄▄█████\
"""

_FALLBACK_BANNER = r"""\
  _____    _      _     _       _    
 |_   _|__| | ___| |   (_)_ __ | | __
   | |/ _ \ |/ _ \ |   | | '_ \| |/ /
   | |  __/ |  __/ |___| | | | |   < 
   |_|\___|_|\___|_____|_|_| |_|_|\_\
"""


def _load_banner() -> str:
    path = ASSETS / "banner.txt"
    if path.exists():
        raw = path.read_text(encoding="utf-8", errors="replace").strip("\n")
        if raw.strip():
            return raw
    return _FALLBACK_BANNER


def _esc_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _base_css() -> str:
    return f"""
    :root {{
      color-scheme: dark;
      --bg: {BG};
      --surface: {SURFACE};
      --border: {BORDER};
      --baby: {BABY};
      --light: {LIGHT};
      --value: {VALUE};
      --muted: {MUTED};
      --text: {TEXT};
      --badge-fg: {BADGE_FG};
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html {{ -webkit-text-size-adjust: 100%; }}
    body {{
      font-family: "Cascadia Mono", "Cascadia Code", Consolas, "SF Mono", Menlo, monospace;
      background: var(--bg);
      color: var(--text);
      min-height: 100dvh;
      line-height: 1.45;
      font-size: 15px;
    }}
    .shell {{
      max-width: 28rem;
      margin: 0 auto;
      padding: 1.25rem 1rem 2rem;
    }}
    pre {{
      font-family: inherit;
      white-space: pre;
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
    }}
    .boot {{
      margin-bottom: 1.25rem;
    }}
    .banner-row {{
      display: flex;
      align-items: flex-start;
      gap: 0.75rem;
      margin-bottom: 0.75rem;
    }}
    .banner {{
      color: var(--baby);
      font-size: 0.62rem;
      line-height: 1.15;
      flex: 1 1 auto;
      min-width: 0;
    }}
    .art {{
      color: var(--baby);
      font-size: 0.72rem;
      line-height: 1.1;
      flex: 0 0 auto;
      opacity: 0.95;
    }}
    .badges {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.4rem;
      margin-bottom: 0.85rem;
    }}
    .badge {{
      display: inline-block;
      background: var(--light);
      color: var(--badge-fg);
      font-weight: 700;
      font-size: 0.72rem;
      padding: 0.2rem 0.45rem;
      letter-spacing: 0.01em;
    }}
    .prompt {{
      color: var(--text);
      font-size: 0.95rem;
      margin-bottom: 0.35rem;
    }}
    .prompt .accent {{ color: var(--baby); }}
    .sub {{
      color: var(--muted);
      font-size: 0.82rem;
    }}
    .panel {{
      background: var(--surface);
      border: 1px solid var(--border);
      padding: 1rem;
    }}
    .field {{ margin-bottom: 0.85rem; }}
    .field:last-of-type {{ margin-bottom: 0; }}
    label {{
      display: block;
      color: var(--baby);
      font-weight: 700;
      font-size: 0.72rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      margin-bottom: 0.35rem;
    }}
    .hint {{
      color: var(--muted);
      font-size: 0.72rem;
      margin-top: 0.25rem;
    }}
    input[type="text"],
    input[type="url"],
    textarea {{
      width: 100%;
      padding: 0.6rem 0.65rem;
      border: 1px solid var(--border);
      background: var(--bg);
      color: var(--text);
      font: inherit;
      font-size: 0.92rem;
      border-radius: 0;
      -webkit-appearance: none;
      appearance: none;
    }}
    textarea {{
      min-height: 4.5rem;
      resize: vertical;
    }}
    input::placeholder,
    textarea::placeholder {{ color: var(--muted); opacity: 0.65; }}
    input:focus,
    textarea:focus {{
      outline: none;
      border-color: var(--baby);
      box-shadow: 0 0 0 1px var(--baby);
    }}
    .file-wrap {{
      position: relative;
      border: 1px dashed var(--border);
      padding: 0.75rem;
      text-align: center;
      background: var(--bg);
      transition: border-color 0.15s;
    }}
    .file-wrap:focus-within {{
      border-color: var(--baby);
      border-style: solid;
    }}
    .file-wrap input[type="file"] {{
      position: absolute;
      inset: 0;
      opacity: 0;
      cursor: pointer;
      width: 100%;
      height: 100%;
    }}
    .file-label {{
      color: var(--muted);
      font-size: 0.82rem;
      pointer-events: none;
    }}
    .file-label strong {{ color: var(--value); }}
    .file-name {{
      display: block;
      margin-top: 0.35rem;
      color: var(--baby);
      font-size: 0.78rem;
      word-break: break-all;
    }}
    .btn {{
      display: block;
      width: 100%;
      margin-top: 1rem;
      padding: 0.8rem 1rem;
      border: none;
      background: var(--light);
      color: var(--badge-fg);
      font: inherit;
      font-weight: 700;
      font-size: 0.92rem;
      cursor: pointer;
      letter-spacing: 0.02em;
      text-align: center;
      text-decoration: none;
    }}
    .btn:active {{ opacity: 0.82; }}
    .footer {{
      margin-top: 1rem;
      color: var(--muted);
      font-size: 0.72rem;
      text-align: center;
    }}
    .center {{
      text-align: center;
      padding: 2.5rem 1rem;
    }}
    .center h1 {{
      color: var(--baby);
      font-size: 1.35rem;
      font-weight: 700;
      margin-bottom: 0.5rem;
    }}
    .center p {{ color: var(--muted); font-size: 0.88rem; }}
    .mark {{
      color: var(--baby);
      font-size: 2rem;
      line-height: 1;
      margin-bottom: 0.75rem;
    }}
    .err-title {{
      color: var(--baby);
      font-size: 1rem;
      font-weight: 700;
      margin-bottom: 0.75rem;
    }}
    .err-body {{
      color: var(--muted);
      font-size: 0.82rem;
      white-space: pre-wrap;
      word-break: break-word;
      text-align: left;
    }}
    """


def intake_html() -> str:
    banner = _esc_html(_load_banner())
    art = _esc_html(_PHONE_ART.strip())
    css = _base_css()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TeleLink Intake</title>
  <style>{css}</style>
</head>
<body>
  <div class="shell">
    <header class="boot">
      <div class="banner-row">
        <pre class="banner" aria-hidden="true">{banner}</pre>
        <pre class="art" aria-hidden="true">{art}</pre>
      </div>
      <div class="badges">
        <span class="badge">LAN share</span>
        <span class="badge">same wi-fi</span>
        <span class="badge">intake</span>
      </div>
      <p class="prompt"><span class="accent">telelink</span> <span class="accent">&gt;</span> intake</p>
      <p class="sub">send files, messages, or links to your PC</p>
    </header>

    <form class="panel" method="POST" action="/intake" enctype="multipart/form-data">
      <div class="field">
        <label for="sender">from</label>
        <input id="sender" name="sender" type="text" placeholder="your name" autocomplete="name">
      </div>

      <div class="field">
        <label for="message">message</label>
        <textarea id="message" name="message" placeholder="text, note, or paste…"></textarea>
      </div>

      <div class="field">
        <label for="link">link</label>
        <input id="link" name="link" type="url" placeholder="https://…" inputmode="url">
      </div>

      <div class="field">
        <label for="file">file or photo</label>
        <div class="file-wrap">
          <input id="file" name="file" type="file" accept="image/*,*/*">
          <span class="file-label">tap to <strong>choose file</strong></span>
          <span class="file-name" id="file-name"></span>
        </div>
      </div>

      <button class="btn" type="submit">send to telelink</button>
    </form>

    <p class="footer">saved on your PC when you tap send</p>
  </div>
  <script>
    document.getElementById("file").addEventListener("change", function() {{
      var el = document.getElementById("file-name");
      el.textContent = this.files && this.files[0] ? this.files[0].name : "";
    }});
  </script>
</body>
</html>
"""


def success_html() -> str:
    css = _base_css()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sent · TeleLink</title>
  <style>{css}</style>
</head>
<body>
  <div class="shell center">
    <div class="mark" aria-hidden="true">✓</div>
    <h1>sent</h1>
    <p>Saved on your PC.</p>
    <p style="margin-top:0.5rem">You can close this tab.</p>
    <div class="badges" style="justify-content:center;margin-top:1.5rem">
      <span class="badge">telelink</span>
      <span class="badge">intake</span>
    </div>
    <a class="btn" href="/" style="margin-top:1.25rem">send another</a>
  </div>
</body>
</html>
"""


def error_html(message: str) -> str:
    css = _base_css()
    body = _esc_html(message)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Error · TeleLink</title>
  <style>{css}</style>
</head>
<body>
  <div class="shell">
    <header class="boot">
      <p class="prompt"><span class="accent">telelink</span> <span class="accent">&gt;</span> intake</p>
    </header>
    <div class="panel">
      <p class="err-title">something went wrong</p>
      <p class="err-body">{body}</p>
    </div>
    <p class="footer"><a href="/" style="color:var(--value);text-decoration:none">← back to intake</a></p>
  </div>
</body>
</html>
"""


# Built once at import — pages are static until restart.
INTAKE_HTML = intake_html()
SUCCESS_HTML = success_html()
