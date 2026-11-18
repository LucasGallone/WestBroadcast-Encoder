"""UECP (RDS) input for streams that embed it in their MP2 / AAC frames.

An RDS encoder (or anything else producing UECP) connects over TCP and sends UECP frames
(0xFE ... 0xFF). Complete frames are queued unchanged - they aren't parsed or checked - and each
encoded audio frame then carries the next few queued bytes:

  MP2: up to 8 bytes per frame in the ancillary data (mp2_uecp_x64.exe, see native/mp2_uecp)
  AAC: up to 4 bytes per frame in a data stream element (libfdk-aac.dll)

This is the same mechanism as UecpSource, and what WestBroadcast Streamer's UECP forwarding
extracts on the receiving side.

Streams configured with the same port share one listener: every frame received goes to each of
those streams. One client is served per port; a new connection replaces the current one, so an
RDS encoder reconnecting after a network fault is never locked out by a stale connection.
"""
import collections
import socket
import sys
import threading

UECP_START = 0xFE
UECP_END = 0xFF
MAX_FRAME = 1024          # longest byte-stuffed UECP frame accepted; anything longer is discarded
MAX_QUEUED_BYTES = 4096   # per stream; ~20 s of MP2 or ~20-40 s of AAC capacity
DEFAULT_PORT = 9000

# ancillary bytes carried per encoded frame (as UecpSource)
MP2_BYTES_PER_FRAME = 8
AAC_BYTES_PER_FRAME = 4

UECP_FORMATS = ("mp2", "aac", "aac_lc", "he_aac", "he_aac_v2")


def stream_wants_uecp(stream_config):
    return bool(stream_config.get("uecp_enabled")) and stream_config.get("format") in UECP_FORMATS


class UecpQueue:
    """UECP bytes waiting to go out in one stream's audio frames.

    The encode loop calls peek(n) for the bytes to embed in the next frame, then consume(k) with
    how many were actually embedded, so bytes the encoder didn't take go out with the next frame
    instead of leaving a hole in the middle of a UECP frame.

    If frames arrive faster than the audio can carry them, the oldest whole frames are dropped
    once MAX_QUEUED_BYTES is reached, so the delay can't grow without limit. A frame that has
    started going out is never dropped."""

    def __init__(self):
        self.lock = threading.Lock()
        self.frames = collections.deque()
        self.offset = 0          # bytes of frames[0] already embedded
        self.queued = 0          # bytes not yet embedded
        self.dropped = 0         # frames dropped because the queue was full
        self.embedded = 0        # frames fully embedded

    def add(self, frame):
        with self.lock:
            keep = 1 if self.offset else 0
            while self.queued + len(frame) > MAX_QUEUED_BYTES and len(self.frames) > keep:
                old = self.frames[keep]
                del self.frames[keep]
                self.queued -= len(old)
                self.dropped += 1
            self.frames.append(frame)
            self.queued += len(frame)

    def peek(self, n):
        with self.lock:
            out = bytearray()
            off = self.offset
            for f in self.frames:
                out += f[off:off + n - len(out)]
                off = 0
                if len(out) >= n:
                    break
            return bytes(out)

    def consume(self, k):
        with self.lock:
            while k > 0 and self.frames:
                f = self.frames[0]
                left = len(f) - self.offset
                if k < left:
                    self.offset += k
                    self.queued -= k
                    return
                k -= left
                self.queued -= left
                self.frames.popleft()
                self.offset = 0
                self.embedded += 1

    def clear(self):
        with self.lock:
            self.frames.clear()
            self.offset = 0
            self.queued = 0


class UecpServer:
    """TCP listener for one port. Frames received are added to every subscribed UecpQueue."""

    def __init__(self, port, log=None):
        self.port = int(port)
        self.log = log
        self.running = False
        self.queues = []
        self.lock = threading.Lock()
        self.listener = None
        self.conn = None
        self.client_addr = ""
        self.frames_received = 0
        self.thread = None

    def _log(self, level, msg):
        if self.log:
            try: self.log(level, msg)
            except Exception: pass

    def start(self):
        """Binds the port (raises OSError if it can't) and starts accepting clients."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # SO_REUSEADDR on Windows would let another program bind the same port; its default
        # behaviour already allows rebinding straight after a restart.
        if sys.platform != "win32":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", self.port))
            s.listen(2)
        except OSError:
            s.close()
            raise
        s.settimeout(0.5)
        self.listener = s
        self.running = True
        self.thread = threading.Thread(target=self._accept_loop, daemon=True)
        self.thread.start()
        self._log("INFO", f"UECP input listening on TCP port {self.port}.")

    def stop(self):
        self.running = False
        for s in (self.conn, self.listener):
            if s:
                try: s.close()
                except OSError: pass
        self.conn = None
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)

    def add_queue(self, q):
        with self.lock:
            self.queues.append(q)

    def remove_queue(self, q):
        with self.lock:
            if q in self.queues:
                self.queues.remove(q)
            return len(self.queues)

    @property
    def client_connected(self):
        return self.conn is not None

    def _accept_loop(self):
        while self.running:
            try:
                conn, addr = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            old = self.conn
            if old:
                self._log("WARNING", f"UECP client {self.client_addr} replaced by a new connection from {addr[0]} (port {self.port}).")
                try: old.close()
                except OSError: pass
            try:
                conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            except OSError:
                pass
            conn.settimeout(0.5)
            self.conn = conn
            self.client_addr = addr[0]
            self._log("INFO", f"UECP client connected from IP {addr[0]} (port {self.port}).")
            threading.Thread(target=self._client_loop, args=(conn, addr[0]), daemon=True).start()

    def _client_loop(self, conn, addr):
        frame = bytearray()
        in_frame = False
        try:
            while self.running and self.conn is conn:
                try:
                    data = conn.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    break
                for b in data:
                    if b == UECP_START:
                        # start of a frame; discards any incomplete previous one
                        frame = bytearray([b])
                        in_frame = True
                    elif in_frame:
                        frame.append(b)
                        if b == UECP_END:
                            self._deliver(bytes(frame))
                            in_frame = False
                        elif len(frame) > MAX_FRAME:
                            in_frame = False
        except OSError:
            pass
        finally:
            if self.conn is conn:
                self.conn = None
                try: conn.close()
                except OSError: pass
                if self.running:
                    self._log("INFO", f"UECP client {addr} disconnected (port {self.port}).")

    def _deliver(self, frame):
        self.frames_received += 1
        with self.lock:
            queues = list(self.queues)
        for q in queues:
            q.add(frame)


_servers = {}
_servers_lock = threading.Lock()


def subscribe(port, log=None):
    """Returns (server, queue) for a stream embedding UECP received on this TCP port.
    Raises OSError if the port can't be opened."""
    port = int(port)
    with _servers_lock:
        srv = _servers.get(port)
        if srv is None:
            srv = UecpServer(port, log)
            srv.start()
            _servers[port] = srv
        q = UecpQueue()
        srv.add_queue(q)
        return srv, q


def unsubscribe(server, q):
    with _servers_lock:
        if server.remove_queue(q) == 0:
            server.stop()
            if _servers.get(server.port) is server:
                del _servers[server.port]
