"""Windows desktop launcher for the bundled HWddns server."""

import os
import queue
import secrets
import socket
import sys
import tempfile
import threading
import time
import tkinter as tk
import traceback
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from tkinter import messagebox

from cryptography.fernet import Fernet


def config_path():
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return local / "HWddns" / "config.env"


def configure():
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    defaults = {
        "ADMIN_PASSWORD": "Qwer1234",
        "APP_SECRET": secrets.token_urlsafe(48),
        "DATA_KEY": Fernet.generate_key().decode(),
        "TZ": "Asia/Shanghai",
        "PORT": "6006",
        "HOST": "0.0.0.0",
    }
    try:
        with path.open("x", encoding="utf-8") as out:
            for key, value in defaults.items():
                out.write(f"{key}={value}\n")
    except FileExistsError:
        pass
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key in defaults:
            values[key] = value.strip()
    for key in ("ADMIN_PASSWORD", "APP_SECRET", "DATA_KEY"):
        if not values.get(key):
            raise ValueError(f"配置文件缺少 {key}: {path}")
    for key, value in values.items():
        os.environ[key] = value
    data = path.parent / "data"
    data.mkdir(exist_ok=True)
    os.environ["DATA_DIR"] = str(data)
    port = int(values.get("PORT", "6006"))
    if not 1 <= port <= 65535:
        raise ValueError("PORT 必须在 1 到 65535 之间")
    host = values.get("HOST", "0.0.0.0")
    if host not in ("0.0.0.0", "127.0.0.1"):
        raise ValueError("HOST 只能设置为 0.0.0.0 或 127.0.0.1")
    return path, port, host


def is_running(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.3) as response:
            return response.read(64) == b"HWddns ok"
    except (OSError, urllib.error.URLError):
        return False


def self_test():
    _, _, host = configure()
    import app
    client = app.app.test_client()
    assert client.get("/health").data == b"HWddns ok"
    assert client.post("/login", data={"password": os.environ["ADMIN_PASSWORD"]}).status_code == 302
    with client.session_transaction() as user_session:
        user_session["authenticated"] = True
        user_session["csrf"] = "test"
    assert client.get("/").status_code == 200
    assert client.get("/tasks/probe/new").status_code == 200
    assert client.get("/ip-check").status_code == 200
    with client.session_transaction() as user_session:
        assert user_session.permanent
    with socket.socket() as target:
        target.bind(("127.0.0.1", 0))
        target.listen(1)
        target.settimeout(3)
        result = client.post("/ip-check", data={"csrf": "test", "ip": "127.0.0.1",
                                               "port": str(target.getsockname()[1])})
        assert 'class="result-status up"' in result.get_data(as_text=True)
        # Drain the first connection before checking the same listening port again.
        connection, _ = target.accept()
        connection.close()
        port_range = str(target.getsockname()[1])
        result = client.post("/ip-check", data={"csrf": "test", "mode": "range",
                                               "ip": "127.0.0.1", "ports": f"{port_range}-{port_range}"})
        assert "1 / 1" in result.get_data(as_text=True)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    errors = queue.Queue()

    def run_backend():
        try:
            app.start_server(host=host, port=port)
        except Exception:
            errors.put(traceback.format_exc())

    threading.Thread(target=run_backend, daemon=True).start()
    for _ in range(50):
        if not errors.empty():
            raise RuntimeError(errors.get_nowait())
        if is_running(port):
            if sys.platform == "win32":
                from windows_desktop import desktop_self_test
                desktop_self_test()
            return
        time.sleep(0.2)
    raise RuntimeError("服务未在 10 秒内启动")


def main():
    if "--self-test" in sys.argv:
        try:
            self_test()
        except Exception as exc:
            error = Path(tempfile.gettempdir()) / "hwddns-self-test-error.txt"
            error.write_text(traceback.format_exc(), encoding="utf-8")
            raise SystemExit(1) from exc
        return
    try:
        path, port, host = configure()
    except Exception as exc:
        messagebox.showerror("HWddns 启动失败", str(exc))
        return
    from windows_desktop import DesktopTray, InstanceLock
    url = f"http://127.0.0.1:{port}"
    try:
        instance = InstanceLock(path)
    except Exception as exc:
        messagebox.showerror("HWddns 启动失败", str(exc))
        return
    if not instance.acquired or is_running(port):
        instance.close()
        if "--background" not in sys.argv:
            messagebox.showinfo("HWddns", "面板已经在运行，请从右下角托盘图标打开管理面板。")
        return

    root = tk.Tk()
    root.withdraw()
    root.title("HWddns · DNS 解析管理")
    root.geometry("490x350")
    root.resizable(False, False)
    root.configure(bg="#f5f7fb")
    # Tool windows stay out of the taskbar; the explicit button hides to tray.
    root.attributes("-toolwindow", True)
    tk.Label(root, text="HWddns", font=("Microsoft YaHei UI", 22, "bold"),
             fg="#2563eb", bg="#f5f7fb").pack(pady=(22, 7))
    status = tk.StringVar(value="正在启动本地面板…")
    tk.Label(root, textvariable=status, font=("Microsoft YaHei UI", 11),
             fg="#344054", bg="#f5f7fb").pack()
    tk.Label(root, text=f"{url}  ·  首次密码 Qwer1234", font=("Microsoft YaHei UI", 9),
             fg="#68778a", bg="#f5f7fb").pack(pady=(8, 12))
    autostart = tk.BooleanVar()

    def on_error(title, detail):
        messagebox.showerror(title, detail, parent=root)

    tray = DesktopTray(root, lambda: webbrowser.open(url), root.destroy, on_error,
                       on_startup_change=autostart.set)
    autostart.set(tray.autostart)
    tk.Checkbutton(root, text="开机自动启动（当前用户登录后）", variable=autostart,
                   command=lambda: tray.change_startup(autostart.get()),
                   font=("Microsoft YaHei UI", 10), bg="#f5f7fb").pack(pady=(0, 12))
    buttons = tk.Frame(root, bg="#f5f7fb")
    buttons.pack()
    tk.Button(buttons, text="打开管理面板", command=tray.open_panel,
              font=("Microsoft YaHei UI", 10), padx=12, pady=5).pack(side="left", padx=5)
    tk.Button(buttons, text="最小化到托盘", command=tray.hide_window,
              font=("Microsoft YaHei UI", 10), padx=12, pady=5).pack(side="left", padx=5)
    tk.Label(root, text="关闭或最小化窗口后，任务仍会在后台运行。", font=("Microsoft YaHei UI", 9),
             fg="#64748b", bg="#f5f7fb").pack(pady=(14, 0))
    tk.Label(root, text="从右下角托盘菜单可打开面板、显示窗口或退出程序。",
             font=("Microsoft YaHei UI", 9), fg="#64748b", bg="#f5f7fb").pack(pady=(4, 0))
    tk.Label(root, text=f"外网访问需放行防火墙和安全组 TCP {port}。",
             font=("Microsoft YaHei UI", 9), fg="#64748b", bg="#f5f7fb").pack(pady=(4, 0))
    errors = queue.Queue()

    def run_backend():
        try:
            import app
            app.start_server(host=host, port=port)
        except Exception as exc:
            log_path = path.parent / "startup-error.log"
            log_path.write_text(traceback.format_exc(), encoding="utf-8")
            errors.put(f"{exc}\n详细信息：{log_path}")

    attempts = 0

    def check_startup():
        nonlocal attempts
        if tray.stopped:
            return
        if not errors.empty():
            on_error("HWddns 启动失败", errors.get_nowait())
            tray.stop()
            return
        if is_running(port):
            status.set("面板正在后台运行")
            tray.set_status("运行中")
            return
        attempts += 1
        if attempts >= 50:
            on_error("HWddns 启动失败", f"无法启动本地面板。配置文件：{path}")
            tray.stop()
            return
        root.after(200, check_startup)

    try:
        tray.start()
        threading.Thread(target=run_backend, daemon=True, name="HWddns-backend").start()
        root.after(200, check_startup)
        root.mainloop()
    except Exception as exc:
        messagebox.showerror("HWddns 启动失败", str(exc))
    finally:
        tray.stop()
        instance.close()


if __name__ == "__main__":
    main()
