"""Bounded Windows session-end integration. Never saves a report."""
import ctypes
import os
import logging
import sys


def process_alive(pid):
    if pid == os.getpid():
        return True
    if not isinstance(pid, int) or pid <= 0:
        return False
    if sys.platform != 'win32':
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        kernel.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))
        return code.value == 259
    finally:
        kernel.CloseHandle(ctypes.c_void_p(handle))


class SessionHook:
    """Subclass only this app's top-level HWND; restore the original on stop."""
    def __init__(self, window, checkpoint):
        self.window, self.checkpoint = window, checkpoint
        self.old = self.callback = self.hwnd = None
        if sys.platform != 'win32':
            return
        from ctypes import wintypes
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        proc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND,
                                      wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        self.user.GetParent.restype = wintypes.HWND
        self.user.CallWindowProcW.restype = ctypes.c_ssize_t
        self.user.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND,
                                             wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self.set_proc = getattr(self.user, 'SetWindowLongPtrW' if ctypes.sizeof(ctypes.c_void_p) == 8 else 'SetWindowLongW')
        self.set_proc.restype = ctypes.c_void_p
        self.set_proc.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        window.update_idletasks()
        self.hwnd = self.user.GetParent(window.winfo_id()) or window.winfo_id()

        def dispatch(hwnd, message, wparam, lparam):
            if message in (0x11, 0x16):
                try:
                    # Query: queue promptly. End-session: a bounded final flush.
                    if message == 0x11:
                        self.checkpoint(0.)
                    elif wparam:
                        self.checkpoint(1.5)
                except Exception:
                    logging.getLogger('fsr').exception('Windows session draft checkpoint failed')
                return 1 if message == 0x11 else 0
            return self.user.CallWindowProcW(self.old, hwnd, message, wparam, lparam)
        self.callback = proc_type(dispatch)
        self.old = self.set_proc(self.hwnd, -4, ctypes.cast(self.callback, ctypes.c_void_p))
        if not self.old:
            raise OSError(ctypes.get_last_error(), 'Could not attach Windows session checkpoint')

    def close(self):
        if self.old:
            self.set_proc(self.hwnd, -4, self.old)
            self.old = None


def process_token(pid):
    """Creation time prevents a reused process ID from locking an old draft."""
    if not isinstance(pid, int) or pid <= 0:
        return None
    if sys.platform != 'win32':
        try:
            from pathlib import Path
            return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
        except (OSError, IndexError):
            return None
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        created, exited, system, user = (ctypes.c_ulonglong() for _ in range(4))
        if kernel.GetProcessTimes(ctypes.c_void_p(handle), ctypes.byref(created), ctypes.byref(exited), ctypes.byref(system), ctypes.byref(user)):
            return str(created.value)
        return None
    finally:
        kernel.CloseHandle(ctypes.c_void_p(handle))


def draft_is_running(value):
    token = value.get('process_started')
    return bool(token and process_alive(value.get('pid')) and process_token(value['pid']) == token)
