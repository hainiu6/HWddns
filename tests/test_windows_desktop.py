import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import windows_desktop as desktop


class WindowsDesktopTests(unittest.TestCase):
    def make_tray(self):
        self.root = MagicMock()
        self.open_panel = MagicMock()
        self.on_exit = MagicMock()
        self.on_error = MagicMock()
        self.changed = MagicMock()
        with patch.object(desktop, "startup_enabled", return_value=False):
            return desktop.DesktopTray(self.root, self.open_panel, self.on_exit,
                                       self.on_error, self.changed)

    def test_startup_command_quotes_executable_paths(self):
        with patch.object(sys, "executable", r"C:\Program Files\HWddns\HWddns.exe"), \
                patch.object(sys, "frozen", True, create=True):
            self.assertEqual(desktop.startup_command(),
                             r'"C:\Program Files\HWddns\HWddns.exe" --background')

    def test_registry_enable_disable_only_affects_current_user_value(self):
        registry = MagicMock()
        registry.HKEY_CURRENT_USER = "current-user"
        registry.OpenKey.return_value.__enter__.return_value = "key"
        registry.CreateKey.return_value.__enter__.return_value = "key"
        registry.QueryValueEx.return_value = ("program --background", 1)
        with patch.dict(sys.modules, winreg=registry), patch.object(sys, "platform", "win32"):
            desktop.set_startup(True)
            registry.SetValueEx.assert_called_once_with("key", "HWddns", 0,
                                                       registry.REG_SZ, desktop.startup_command())
            self.assertTrue(desktop.startup_enabled())
            desktop.set_startup(False)
            registry.DeleteValue.assert_called_once_with("key", "HWddns")
            registry.OpenKey.side_effect = FileNotFoundError
            self.assertFalse(desktop.startup_enabled())
            desktop.set_startup(False)

    def test_startup_failure_keeps_checkbox_and_menu_consistent(self):
        tray = self.make_tray()
        with patch.object(desktop, "set_startup", side_effect=PermissionError("denied")):
            tray.change_startup(True)
        self.assertFalse(tray.autostart)
        self.changed.assert_called_once_with(False)
        self.on_error.assert_called_once()
        self.on_exit.assert_not_called()

    def test_start_is_hidden_and_browser_opens_only_on_explicit_action(self):
        tray = self.make_tray()
        icon = MagicMock()
        menu = MagicMock()
        pystray = SimpleNamespace(Icon=MagicMock(return_value=icon), Menu=menu, MenuItem=MagicMock())
        with patch.dict(sys.modules, pystray=pystray), \
                patch.object(desktop, "tray_image", return_value=None), \
                patch.object(desktop.threading, "Thread"):
            tray.start()
        self.root.withdraw.assert_called_once()
        self.open_panel.assert_not_called()
        self.on_exit.assert_not_called()
        self.assertFalse(tray.stopped)
        tray._menu_callback("open")(icon, None)
        tray._poll()
        self.open_panel.assert_called_once()

    def test_minimize_and_close_keep_background_running_and_restore_works(self):
        tray = self.make_tray()
        tray.hide_window()
        self.assertFalse(tray.stopped)
        self.on_exit.assert_not_called()
        self.root.withdraw.assert_called_once()
        self.root.reset_mock()
        self.root.state.return_value = "iconic"
        tray._on_unmap(SimpleNamespace(widget=self.root))
        self.root.withdraw.assert_called_once()
        with patch.object(desktop, "startup_enabled", return_value=True):
            tray.show_window()
        self.root.deiconify.assert_called_once()
        self.changed.assert_called_once_with(True)
        self.open_panel.assert_not_called()

    def test_exit_stops_tray_and_application_once(self):
        tray = self.make_tray()
        tray.icon = MagicMock()
        tray._menu_callback("quit")(tray.icon, None)
        tray._poll()
        tray.stop()
        self.assertTrue(tray.stopped)
        tray.icon.stop.assert_called_once()
        self.on_exit.assert_called_once()
        self.root.after.assert_not_called()


if __name__ == "__main__":
    unittest.main()
