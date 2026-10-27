"""Windows tray controls and per-user login startup settings."""

import hashlib
import queue
import subprocess
import sys
import threading
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "HWddns"


def startup_command():
    args = [sys.executable]
    if not getattr(sys, "frozen", False):
        args.append(str(Path(__file__).with_name("windows_launcher.py").resolve()))
    return subprocess.list2cmdline([*args, "--background"])


def startup_enabled(key_path=RUN_KEY):
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, RUN_VALUE)
            return bool(value)
    except FileNotFoundError:
        return False


def set_startup(enabled, key_path=RUN_KEY):
    import winreg
    if enabled:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, startup_command())
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, RUN_VALUE)
        except FileNotFoundError:
            pass


class InstanceLock:
    """Keep a single launcher per configuration in this Windows login session."""

    def __init__(self, config):
        import ctypes
        from ctypes import wintypes
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        name = hashlib.sha256(str(Path(config).resolve()).casefold().encode()).hexdigest()[:24]
        self.handle = self.kernel.CreateMutexW(None, False, "Local\\HWddns-" + name)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.acquired = ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
        if not self.acquired:
            self.close()

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def tray_image():
    from PIL import Image, ImageDraw
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((2, 2, 62, 62), radius=14, fill="#2563eb")
    draw.line([(18, 45), (45, 18)], fill="white", width=7)
    draw.line([(24, 18), (45, 18), (45, 39)], fill="white", width=7)
    return image


class DesktopTray:
    """Pass tray callbacks to Tk's thread; withdrawing never stops the backend."""

    def __init__(self, root, open_panel, on_exit, on_error, on_startup_change=lambda value: None):
        self.root = root
        self.open_panel = open_panel
        self.on_exit = on_exit
        self.on_error = on_error
        self.on_startup_change = on_startup_change
        self.events = queue.Queue()
        self.ready = threading.Event()
        self.stopped = False
        self.icon = None
        self.autostart = startup_enabled()
        root.protocol("WM_DELETE_WINDOW", self.hide_window)
        root.bind("<Unmap>", self._on_unmap, add="+")

    def _on_unmap(self, event):
        if event.widget == self.root and self.root.state() == "iconic":
            self.hide_window()

    def hide_window(self):
        self.root.withdraw()

    def show_window(self):
        self.autostart = startup_enabled()
        self.on_startup_change(self.autostart)
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def change_startup(self, enabled):
        try:
            set_startup(enabled)
            self.autostart = enabled
        except OSError as exc:
            self.on_error("无法更新开机启动设置", str(exc))
        self.on_startup_change(self.autostart)
        if self.icon:
            self.icon.update_menu()

    def _menu_callback(self, action):
        return lambda icon, item: self.events.put(action)

    def start(self):
        import pystray
        self.icon = pystray.Icon("HWddns", tray_image(), "HWddns · 正在启动",
            menu=pystray.Menu(
                pystray.MenuItem("打开管理面板", self._menu_callback("open"), default=True),
                pystray.MenuItem("显示启动窗口", self._menu_callback("show")),
                pystray.MenuItem("开机自动启动", self._menu_callback("startup"),
                                 checked=lambda item: self.autostart),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出程序", self._menu_callback("quit")),
            ))
        self.hide_window()

        def setup(icon):
            icon.visible = True
            self.ready.set()

        def run_tray():
            try:
                self.icon.run(setup=setup)
            except Exception as exc:
                self.events.put(("error", str(exc)))

        threading.Thread(target=run_tray, daemon=True, name="HWddns-tray").start()
        self.root.after(100, self._poll)

    def _poll(self):
        while not self.stopped:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if event == "open":
                self.open_panel()
            elif event == "show":
                self.show_window()
            elif event == "startup":
                self.change_startup(not self.autostart)
            elif event == "quit":
                self.stop()
            elif isinstance(event, tuple) and event[0] == "error":
                self.on_error("托盘启动失败", event[1])
                self.stop()
        if not self.stopped:
            self.root.after(100, self._poll)

    def set_status(self, text):
        if self.icon:
            self.icon.title = "HWddns · " + text

    def stop(self):
        if self.stopped:
            return
        self.stopped = True
        if self.icon:
            self.icon.stop()
        self.on_exit()


def desktop_self_test():
    """Exercise the real Windows tray, taskbar style and registry in CI."""
    import tkinter as tk
    import winreg
    key_path = r"Software\HWddns\SelfTest\Run"
    try:
        set_startup(True, key_path)
        assert startup_enabled(key_path)
        set_startup(False, key_path)
        assert not startup_enabled(key_path)
    finally:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
        except FileNotFoundError:
            pass
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        first = InstanceLock(Path(folder) / "config.env")
        try:
            assert first.acquired
            second = InstanceLock(Path(folder) / "config.env")
            assert not second.acquired
        finally:
            first.close()
    root = tk.Tk()
    root.withdraw()
    root.attributes("-toolwindow", True)
    opened, errors = [], []
    tray = DesktopTray(root, lambda: opened.append(True), lambda: None,
                       lambda title, detail: errors.append((title, detail)))
    try:
        tray.start()
        for _ in range(100):
            root.update()
            if tray.ready.is_set():
                break
            threading.Event().wait(0.05)
        assert tray.ready.is_set(), "Tray icon did not start"
        assert tray.icon.visible
        assert root.state() == "withdrawn"
        assert not opened, "Startup opened a browser"
        tray.show_window()
        root.update()
        assert root.state() == "normal"
        assert root.attributes("-toolwindow")
        tray.hide_window()
        root.update()
        assert root.state() == "withdrawn"
        assert not tray.stopped
        assert not errors, errors
    finally:
        tray.stop()
        root.destroy()
