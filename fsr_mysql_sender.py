"""Sends saved reports to MySQL in the background.

A save writes everything on this PC first and is finished there. The MySQL
part of the save waits in the save record (fsr_save_journal) with its step
"mysql" still open; this sender then does it in a background thread, so the
window never waits for the server:

  request()   ask for a round. Requests that arrive while a round runs are
              folded into one more round afterwards.
  a round     work() in the background thread: every report whose MySQL
              step is open is sent, over ONE connection, each through the
              overwrite guard (check and write in one transaction, as
              before).
  poll()      on the window's thread, every few tenths of a second: the
              result of a finished round goes to on_result(), which tells
              the user. Nothing in the background thread touches the
              window.

What a round has done is on disk before it is reported: the save record is
ticked off only after MySQL committed, the ledger is written right after
the commit. A program closed (or a PC losing power) in the middle of a
round therefore leaves the step open and the next start sends the report
again - and the guard finds MySQL either without it (written now) or equal
to it (nothing written, now this copy's own). Never twice, never lost.

inline=True does a round at once on the calling thread: used by the
automated tests of everything that is not about the background itself.
"""
import logging
import queue
import threading

log = logging.getLogger("fsr")


class Sender:
    def __init__(self, work, on_result, inline=False, name="MySQL send"):
        self.name = name                    # in the log: what failed
        self._work = work                   # work(request) -> result
        self._on_result = on_result         # on_result(result), GUI thread
        self.inline = inline
        self._lock = threading.Lock()
        self._wanted = None                 # the request of the next round
        self._running = False
        self._results = queue.Queue()
        self._thread = None
        self._done = threading.Event()
        self._done.set()

    # ---- the window's side ----
    def request(self, **request):
        """Ask for a round. Keyword arguments reach work(); a later
        request's values win, flags that are True stay True."""
        if self.inline:
            self._deliver(self._run(request))
            return
        with self._lock:
            wanted = self._wanted if self._wanted is not None else {}
            for key, value in request.items():
                if isinstance(value, bool):         # a flag stays set
                    wanted[key] = wanted.get(key, False) or value
                else:
                    wanted[key] = value
            self._wanted = wanted
            self._done.clear()
            if not self._running:
                self._running = True
                self._thread = threading.Thread(
                    target=self._loop, name="mysql-sender", daemon=True)
                self._thread.start()

    def poll(self):
        """Hand finished rounds to on_result(). Call from the window."""
        while True:
            try:
                result = self._results.get_nowait()
            except queue.Empty:
                return
            self._deliver(result)

    def idle(self):
        """Nothing running, nothing asked for, nothing left to report."""
        with self._lock:
            quiet = not self._running and self._wanted is None
        return quiet and self._results.empty()

    def wait(self, timeout=None):
        """Until the background has nothing more to do (for closing the
        program, and for tests). True when it is quiet."""
        return self._done.wait(timeout)

    # ---- the background thread ----
    def _loop(self):
        while True:
            with self._lock:
                request = self._wanted
                self._wanted = None
                if request is None:
                    self._running = False
                    self._done.set()
                    return
            self._results.put(self._run(request))

    def _run(self, request):
        try:
            return {"request": request, "result": self._work(**request),
                    "error": None}
        except Exception as error:          # reported, never lost silently
            log.exception("%s round failed", self.name)
            return {"request": request, "result": None, "error": error}

    def _deliver(self, item):
        try:
            self._on_result(item)
        except Exception:
            log.exception("Reporting a %s round failed", self.name)
