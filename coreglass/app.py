"""`coreglass app`: the desktop GUI. A local server plus an app window (Omarchy web-app style).

One session at a time (live, scripted run, or replay) streams into the embedded dashboard.
Captures and rendered frames live under $XDG_DATA_HOME/coreglass.
"""

import json
import mimetypes
import os
import shutil
import socket
import subprocess
import sys
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import apppage, build, compare, livepage, remote, theme
from .live import LiveHandler, Session

DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "coreglass"
PREFS = Path.home() / ".config/coreglass/app.json"
ICON = Path(__file__).with_name("icon.svg")


class App:
    def __init__(self):
        (DATA / "captures").mkdir(parents=True, exist_ok=True)
        (DATA / "out").mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.session, self.mode, self.target, self.capture = None, "idle", None, None
        self.log, self.error, self.cancel = [], None, threading.Event()
        prefs = json.loads(PREFS.read_text()) if PREFS.exists() else {}
        self.theme_name = prefs.get("theme", "synthwave")

    # -- state -------------------------------------------------------------------------------
    def palette(self):
        return theme.get(self.theme_name)

    def state(self):
        p = self.palette()
        return {"mode": self.mode, "target": self.target, "capture": self.capture, "log": self.log[-12:],
                "error": self.error, "theme": self.theme_name, "palette": p["name"],
                "samples": self.session.hub.count if self.session else 0,
                "omarchy": theme.omarchy() is not None}

    def set_theme(self, name):
        self.theme_name = name if name in ("synthwave", "omarchy") else "synthwave"
        PREFS.parent.mkdir(parents=True, exist_ok=True)
        PREFS.write_text(json.dumps({"theme": self.theme_name}))

    def say(self, msg):
        with self.lock:
            self.log.append(f"{datetime.now():%H:%M:%S}  {msg}")

    # -- sessions ----------------------------------------------------------------------------
    def _begin(self, mode, target):
        self.stop()
        with self.lock:
            self.mode, self.target, self.error, self.log = mode, target, None, []
            self.cancel = threading.Event()

    def _record(self, name):
        return str(DATA / "captures" / f"{name}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.jsonl")

    def _thread(self, fn):
        def wrapped():
            failed = True
            try:
                fn()
                failed = False
            except SystemExit as e:
                self.error = str(e)
                self.say(str(e))
            except Exception as e:  # surface any failure in the UI instead of a dead thread
                self.error = f"{type(e).__name__}: {e}"
                self.say(self.error)
            finally:
                with self.lock:
                    if failed or self.mode not in ("live", "replay"):
                        self.mode = "idle"
        threading.Thread(target=wrapped, daemon=True).start()

    def start_live(self, name):
        self._begin("live", name)
        host = remote.resolve(name)
        record = self._record(name)
        self.capture = Path(record).name

        def go():
            self.say(f"connecting to {host['ssh']} …")
            self.session = Session(host["ssh"], 10, record).start()
            self.say("streaming · recording " + Path(record).name)
        self._thread(go)

    def start_run(self, name):
        self._begin("run", name)
        record = self._record(name)
        self.capture = Path(record).name
        self._thread(lambda: remote.run_cmd(name, [], [], True, 10, None, False, False, 8, 4, 10, record,
                                            attach=lambda s: setattr(self, "session", s), log=self.say,
                                            cancel=self.cancel))

    def start_replay(self, capture):
        self._begin("replay", Path(capture).stem)
        self.capture = Path(capture).name
        path = DATA / "captures" / self.capture

        def go():
            self.session = Session("replay", 10, None, None, str(path), 1.0).start()
            self.say(f"replaying {path.name}")
        self._thread(go)

    def stop(self):
        self.cancel.set()
        s, self.session = self.session, None
        if s:
            s.stop()
        with self.lock:
            was_live, self.mode = self.mode == "live", "idle"
        if was_live:
            self.say("stopped")

    # -- data --------------------------------------------------------------------------------
    def hosts(self):
        hosts, path = remote.load_hosts()
        names = list(hosts)

        def one(n):
            h = remote.resolve(n)
            pf = remote.preflight(h)
            return {"name": n, "ssh": h["ssh"], "chip": h.get("chip", ""), "mlx": bool(h.get("mlx_python")),
                    "ane": bool(h.get("ane_cmd")), "yields": bool(h.get("before_run")), "preflight": pf,
                    "blockers": remote.blockers(pf, h)}
        with ThreadPoolExecutor(max_workers=8) as ex:
            return {"file": str(path), "hosts": list(ex.map(one, names))}

    def captures(self):
        out = []
        for p in sorted((DATA / "captures").glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
            man = p.with_suffix(".run.json")
            info = json.loads(man.read_text()) if man.exists() else {}
            with p.open() as f:
                first = f.readline()
            if not first.startswith('{"meta"'):  # a run stopped before the sampler spoke; nothing to show
                continue
            meta = json.loads(first)["meta"]
            built = DATA / "out" / p.stem / "index.html"
            out.append({"name": p.name, "host": meta.get("host", "?"), "model": meta.get("model", ""),
                        "seconds": round(info.get("seconds", 0), 1), "steps": [s["label"] for s in info.get("steps", [])],
                        "kind": "run" if info else "live", "bytes": p.stat().st_size,
                        "built": built.exists(), "when": datetime.fromtimestamp(p.stat().st_mtime).strftime("%b %d %H:%M")})
        return out

    def phases(self, capture):
        return remote.phases(DATA / "captures" / Path(capture).name)

    def build(self, capture, reference=True, anonymize=False):
        path = DATA / "captures" / Path(capture).name
        inputs = (["reference"] if reference else []) + [str(path)]
        return build.build(inputs, DATA / "out" / path.stem, anonymize=anonymize, theme_name=self.theme_name)

    def compare(self, names, anonymize=False):
        """One capture: its engines side by side. Several: the same step from each (prefer `LLM`)."""
        paths = [DATA / "captures" / Path(n).name for n in names]
        specs = [str(p) for p in paths]
        if len(paths) > 1:
            steps = [{r["label"] for r in remote.phases(p)["results"]} for p in paths]
            common = set.intersection(*steps)
            if not common:
                raise SystemExit("the marked captures share no LLM step")
            step = "LLM" if "LLM" in common else sorted(common)[0]
            stamps = [p.stem.rsplit("-", 1)[-1] for p in paths]
            specs = [f"{p}#{step}={s[9:11]}:{s[11:13]}Z run" for p, s in zip(paths, stamps)]
        out = DATA / "out" / ("compare-" + "-".join(p.stem.rsplit("-", 1)[-1] for p in paths))
        r = compare.compare(specs, out, png=build.browser() is not None, anonymize=anonymize,
                            theme_name=self.theme_name)
        rel = out.relative_to(DATA)
        return {**r, "svg": f"/{rel}/compare.svg", "png": f"/{rel}/compare.png" if build.browser() else None}


def handler(app):
    class Handler(LiveHandler):
        def hub(self):
            return app.session.hub if app.session else None

        def title(self):
            return app.target or "coreglass"

        def json(self, obj, code=200):
            self.send_body(json.dumps(obj), "application/json", code)

        def do_GET(self):
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            path = url.path
            if path == "/":
                return self.send_body(apppage.render(app.palette()), "text/html; charset=utf-8")
            if path == "/live":
                return self.send_body(livepage.render(self.title(), app.palette()), "text/html; charset=utf-8")
            if path == "/events":
                return self.serve_events()
            if path == "/icon.svg":
                return self.send_body(ICON.read_bytes(), "image/svg+xml")
            if path == "/api/state":
                return self.json(app.state())
            if path == "/api/hosts":
                return self.json(app.hosts())
            if path == "/api/captures":
                return self.json(app.captures())
            if path == "/api/phases":
                return self.json(app.phases(q["name"]))
            if path.startswith("/out/"):
                f = (DATA / unquote(path)[1:]).resolve()
                if DATA.resolve() in f.parents and f.is_file():
                    return self.send_body(f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")
            self.send_error(404)

        def do_POST(self):
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            actions = {
                "/mark": lambda: self.post_mark(),
                "/api/live": lambda: (app.start_live(q["host"]), self.json(app.state())),
                "/api/run": lambda: (app.start_run(q["host"]), self.json(app.state())),
                "/api/replay": lambda: (app.start_replay(q["name"]), self.json(app.state())),
                "/api/stop": lambda: (app.stop(), self.json(app.state())),
                "/api/theme": lambda: (app.set_theme(q.get("name", "synthwave")), self.json(app.state())),
                "/api/build": lambda: self.json(app.build(q["name"], q.get("reference", "1") == "1",
                                                          q.get("anonymize") == "1")),
                "/api/compare": lambda: self.json(app.compare(q["names"].split(","), q.get("anonymize") == "1")),
            }
            if url.path not in actions:
                return self.send_error(404)
            try:
                actions[url.path]()
            except SystemExit as e:
                self.json({"error": str(e)}, 400)

    return Handler


def open_window(url):
    """Open the app the Omarchy way (a chromeless web-app window); fall back to any Chromium, then a browser."""
    if shutil.which("omarchy-launch-webapp"):
        return subprocess.Popen(["omarchy-launch-webapp", url], start_new_session=True)
    chrome = build.browser()
    if chrome:
        return subprocess.Popen([chrome, f"--app={url}", "--class=coreglass"], start_new_session=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import webbrowser
    webbrowser.open(url)


def already_running(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=1) as r:
            return "mode" in json.loads(r.read())
    except (OSError, ValueError):
        return False


def run(port=8777, window=True):
    url = f"http://127.0.0.1:{port}/"
    if already_running(port):
        print(f"coreglass app already running: {url}")
        if window:
            open_window(url)
        return
    app = App()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), handler(app))
    except OSError:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        url = f"http://127.0.0.1:{port}/"
        server = ThreadingHTTPServer(("127.0.0.1", port), handler(app))
    server.daemon_threads = True
    print(f"coreglass app: {url}  (data in {DATA})", flush=True)
    if window:
        open_window(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()


DESKTOP = """[Desktop Entry]
Version=1.0
Type=Application
Name=Coreglass
GenericName=Apple Silicon inference studio
Comment=See where local inference loses speed on Apple Silicon under Linux
Exec={exec} app
Icon={icon}
Terminal=false
Categories=Development;System;Monitor;
Keywords=mlx;omlx;ane;gpu;apple;aurora;omarchy;inference;benchmark;
StartupWMClass=coreglass
"""


def install_desktop():
    """Add Coreglass to the app launcher (Omarchy: Super + Space)."""
    exe = shutil.which("coreglass") or f"{sys.executable} -m coreglass"
    icon_dir = Path.home() / ".local/share/icons/hicolor/scalable/apps"
    icon_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ICON, icon_dir / "coreglass.svg")
    apps = Path.home() / ".local/share/applications"
    apps.mkdir(parents=True, exist_ok=True)
    entry = apps / "coreglass.desktop"
    entry.write_text(DESKTOP.format(exec=exe, icon=icon_dir / "coreglass.svg"))
    print(f"{entry}\n{icon_dir / 'coreglass.svg'}\nLaunch it from the app launcher, or run: coreglass app")
