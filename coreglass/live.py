"""Live capture: stream the sampler from a host (or replay a capture), record it, serve the dashboard over SSE."""

import json
import queue
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import livepage

SAMPLER = Path(__file__).with_name("sampler.py")
BACKLOG = 1200


class Hub:
    """Fan-out of sampler lines to SSE clients, plus the capture file."""

    def __init__(self, record):
        self.lock = threading.Lock()
        self.clients, self.meta, self.backlog = [], None, []
        self.record = open(record, "a", buffering=1) if record else None
        self.count, self.t = 0, 0.0
        self.has_meta = threading.Event()

    def publish(self, line):
        msg = json.loads(line)
        with self.lock:
            if "meta" in msg:
                self.meta = line
                self.has_meta.set()
            else:
                self.backlog = (self.backlog + [line])[-BACKLOG:]
                if "mark" not in msg:
                    self.count += 1
                    self.t = msg.get("t", self.t)
            if self.record:
                self.record.write(line + "\n")
            for q in self.clients:
                q.put(line)

    def subscribe(self):
        q = queue.Queue()
        with self.lock:
            for line in ([self.meta] if self.meta else []) + self.backlog:
                q.put(line)
            self.clients.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            self.clients.remove(q)


def handler(hub, title):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/":
                body = livepage.render(title).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path == "/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                q = hub.subscribe()
                try:
                    while True:
                        self.wfile.write(f"data: {q.get()}\n\n".encode())
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    hub.unsubscribe(q)
            else:
                self.send_error(404)

        def do_POST(self):
            if urlparse(self.path).path != "/mark":
                return self.send_error(404)
            hub.publish(json.dumps({"mark": parse_qs(urlparse(self.path).query).get("label", ["mark"])[0][:80],
                                    "t": hub.t}))
            self.send_response(204)
            self.end_headers()

    return Handler


class Session:
    """One sampler stream: `ssh` (or a local process, or a replayed file) -> Hub -> capture file + dashboard."""

    def __init__(self, ssh, hz=10, record=None, port=None, replay=None, speed=1.0):
        self.ssh, self.hz, self.record, self.port, self.replay, self.speed = ssh, hz, record, port, replay, speed
        if record:
            Path(record).parent.mkdir(parents=True, exist_ok=True)
        self.hub, self.stopped, self.server, self.proc = Hub(record), threading.Event(), None, None

    def start(self):
        if self.port:
            title = Path(self.replay).name if self.replay else self.ssh
            try:
                self.server = ThreadingHTTPServer(("127.0.0.1", self.port), handler(self.hub, title))
            except OSError as e:
                raise SystemExit(f"port {self.port}: {e.strerror}; pass --port with a free port") from None
            self.server.daemon_threads = True
            threading.Thread(target=self.server.serve_forever, daemon=True).start()
        threading.Thread(target=self._replay if self.replay else self._pump, daemon=True).start()
        if not self.hub.has_meta.wait(30):
            self.stop()
            raise SystemExit(f"{self.ssh}: sampler sent no meta line within 30 s")
        return self

    def _pump(self):
        remote = ["python3", "-u", "-", "--hz", str(self.hz)]
        cmd = remote if self.ssh == "local" else ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", self.ssh, *remote]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.proc.stdin.write(SAMPLER.read_text())
        self.proc.stdin.close()
        for line in self.proc.stdout:
            if self.stopped.is_set():
                break
            self.hub.publish(line.strip())
        self.stopped.set()

    def _replay(self):
        prev = None
        for line in Path(self.replay).read_text().splitlines():
            if self.stopped.is_set():
                break
            msg = json.loads(line)
            if "meta" in msg:
                msg["meta"]["replay"] = Path(self.replay).name
                line = json.dumps(msg)
            elif "cpu" in msg:
                if prev is not None:
                    time.sleep(max(0.0, (msg["t"] - prev) / self.speed))
                prev = msg["t"]
            self.hub.publish(line)
        self.stopped.set()

    @property
    def meta(self):
        return json.loads(self.hub.meta)["meta"]

    def mark(self, label):
        self.hub.publish(json.dumps({"mark": label, "t": self.hub.t}))

    def stop(self):
        self.stopped.set()
        if self.proc:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        if self.server:
            self.server.shutdown()


def run(ssh, hz, record, port, seconds, serve, replay=None, speed=1.0):
    s = Session(ssh, hz, None if replay else record, port if serve else None, replay, speed).start()
    where = f"http://127.0.0.1:{port}/" if serve else "headless"
    print(f"live: {where}  source={replay or ssh}  recording={None if replay else record}", flush=True)
    deadline = time.monotonic() + seconds if seconds else None
    try:
        while (deadline is None or time.monotonic() < deadline) and not (s.stopped.is_set() and not serve):
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    s.stop()
    print(f"{record if not replay else replay}: {s.hub.count} samples, {s.hub.t:.1f} s", flush=True)
