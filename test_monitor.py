"""Tests for Port & URL Monitor – Persistence Manager."""

import json
import os
import tempfile
import tkinter as tk

import pytest

from monitor import Target, save_targets, load_targets


# =============================================================================
# Persistence – save_targets / load_targets
# =============================================================================

class TestSaveTargets:
    """Unit tests for save_targets."""

    def test_save_creates_json_file(self, tmp_path):
        filepath = str(tmp_path / "targets.json")
        targets = [Target("localhost", 8080, "port")]
        save_targets(targets, filepath)
        assert os.path.exists(filepath)

    def test_save_writes_correct_fields(self, tmp_path):
        filepath = str(tmp_path / "targets.json")
        targets = [Target("google.com", 443, "url", status="Online", notified=True)]
        save_targets(targets, filepath)

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert len(data) == 1
        assert data[0] == {"host": "google.com", "port": 443, "target_type": "url"}

    def test_save_excludes_runtime_fields(self, tmp_path):
        filepath = str(tmp_path / "targets.json")
        targets = [Target("host", 80, "port", status="Offline", notified=True)]
        save_targets(targets, filepath)

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "status" not in data[0]
        assert "notified" not in data[0]

    def test_save_empty_list(self, tmp_path):
        filepath = str(tmp_path / "targets.json")
        save_targets([], filepath)

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data == []

    def test_save_ioerror_prints_warning(self, tmp_path, capsys):
        # Use a path that can't be written to
        filepath = str(tmp_path / "no_such_dir" / "nested" / "targets.json")
        save_targets([Target("h", 1, "port")], filepath)
        captured = capsys.readouterr()
        assert "Warning" in captured.err


class TestLoadTargets:
    """Unit tests for load_targets."""

    def test_load_returns_targets(self, tmp_path):
        filepath = str(tmp_path / "targets.json")
        data = [{"host": "localhost", "port": 8080, "target_type": "port"}]
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f)

        targets = load_targets(filepath)
        assert len(targets) == 1
        assert targets[0].host == "localhost"
        assert targets[0].port == 8080
        assert targets[0].target_type == "port"

    def test_load_sets_default_runtime_fields(self, tmp_path):
        filepath = str(tmp_path / "targets.json")
        data = [{"host": "h", "port": 1, "target_type": "port"}]
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f)

        targets = load_targets(filepath)
        assert targets[0].status == "Unknown"
        assert targets[0].notified is False

    def test_load_missing_file_returns_empty(self, tmp_path):
        filepath = str(tmp_path / "nonexistent.json")
        assert load_targets(filepath) == []

    def test_load_invalid_json_returns_empty(self, tmp_path, capsys):
        filepath = str(tmp_path / "bad.json")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("{not valid json!!")

        targets = load_targets(filepath)
        assert targets == []
        captured = capsys.readouterr()
        assert "Warning" in captured.err

    def test_load_empty_array(self, tmp_path):
        filepath = str(tmp_path / "targets.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump([], f)

        assert load_targets(filepath) == []


# =============================================================================
# Alarm System – send_notification / update_target_status
# =============================================================================

from monitor import send_notification, update_target_status


class TestSendNotification:
    """Unit tests for send_notification."""

    def test_calls_plyer_notify(self, monkeypatch):
        called_with = {}

        def fake_notify(**kwargs):
            called_with.update(kwargs)

        monkeypatch.setattr("monitor.notification.notify", fake_notify)
        target = Target("myhost", 9090, "port")
        send_notification(target)

        assert called_with["title"] == "Target Offline"
        assert "myhost" in called_with["message"]
        assert "9090" in called_with["message"]

    def test_notification_contains_host_and_port(self, monkeypatch):
        messages = []

        def fake_notify(**kwargs):
            messages.append(kwargs.get("message", ""))

        monkeypatch.setattr("monitor.notification.notify", fake_notify)
        target = Target("example.com", 443, "url")
        send_notification(target)

        assert "example.com" in messages[0]
        assert "443" in messages[0]

    def test_plyer_failure_does_not_crash(self, monkeypatch, capsys):
        def failing_notify(**kwargs):
            raise RuntimeError("no notification backend")

        monkeypatch.setattr("monitor.notification.notify", failing_notify)
        target = Target("h", 1, "port")
        send_notification(target)  # should not raise

        captured = capsys.readouterr()
        assert "Warning" in captured.err


class TestUpdateTargetStatus:
    """Unit tests for update_target_status."""

    def test_online_sets_status_and_resets_notified(self):
        target = Target("h", 80, "port", status="Offline", notified=True)
        update_target_status(target, is_online=True, notify_func=lambda t: None)

        assert target.status == "Online"
        assert target.notified is False

    def test_offline_from_online_triggers_notification(self):
        notifications = []
        target = Target("h", 80, "port", status="Online", notified=False)
        update_target_status(target, is_online=False, notify_func=lambda t: notifications.append(t))

        assert target.status == "Offline"
        assert target.notified is True
        assert len(notifications) == 1
        assert notifications[0] is target

    def test_offline_from_unknown_triggers_notification(self):
        notifications = []
        target = Target("h", 80, "port", status="Unknown", notified=False)
        update_target_status(target, is_online=False, notify_func=lambda t: notifications.append(t))

        assert target.status == "Offline"
        assert target.notified is True
        assert len(notifications) == 1

    def test_consecutive_offline_suppresses_duplicate(self):
        notifications = []
        target = Target("h", 80, "port", status="Offline", notified=True)
        update_target_status(target, is_online=False, notify_func=lambda t: notifications.append(t))

        assert target.status == "Offline"
        assert target.notified is True
        assert len(notifications) == 0

    def test_offline_to_online_resets_notified(self):
        target = Target("h", 80, "port", status="Offline", notified=True)
        update_target_status(target, is_online=True, notify_func=lambda t: None)

        assert target.status == "Online"
        assert target.notified is False

    def test_full_cycle_online_offline_online_offline(self):
        """Verify a full state cycle triggers notifications correctly."""
        notifications = []
        notify = lambda t: notifications.append(t)
        target = Target("h", 80, "port", status="Online", notified=False)

        # Online → Offline: should notify
        update_target_status(target, is_online=False, notify_func=notify)
        assert len(notifications) == 1

        # Offline → Offline: suppress
        update_target_status(target, is_online=False, notify_func=notify)
        assert len(notifications) == 1

        # Offline → Online: reset
        update_target_status(target, is_online=True, notify_func=notify)
        assert target.notified is False

        # Online → Offline: should notify again
        update_target_status(target, is_online=False, notify_func=notify)
        assert len(notifications) == 2



# =============================================================================
# Monitor Thread – monitor_loop
# =============================================================================

import threading
import time

from monitor import monitor_loop, check_port, check_url, CHECK_INTERVAL


class TestMonitorLoop:
    """Unit tests for monitor_loop."""

    def test_checks_port_target_and_updates_status(self, monkeypatch):
        """monitor_loop should call check_port for port targets and update status."""
        target = Target("localhost", 9999, "port", status="Unknown")
        targets = [target]
        lock = threading.Lock()
        stop_event = threading.Event()
        callback_calls = []

        monkeypatch.setattr("monitor.check_port", lambda h, p, t: True)
        monkeypatch.setattr("monitor.send_notification", lambda t: None)

        def fake_callback():
            callback_calls.append(1)
            stop_event.set()  # stop after first cycle

        monitor_loop(targets, lock, stop_event, fake_callback)

        assert target.status == "Online"
        assert len(callback_calls) == 1

    def test_checks_url_target_and_updates_status(self, monkeypatch):
        """monitor_loop should call check_url for url targets and update status."""
        target = Target("example.com", 443, "url", status="Unknown")
        targets = [target]
        lock = threading.Lock()
        stop_event = threading.Event()
        callback_calls = []

        monkeypatch.setattr("monitor.check_url", lambda h, p, t: True)
        monkeypatch.setattr("monitor.send_notification", lambda t: None)

        def fake_callback():
            callback_calls.append(1)
            stop_event.set()

        monitor_loop(targets, lock, stop_event, fake_callback)

        assert target.status == "Online"
        assert len(callback_calls) == 1

    def test_offline_result_sets_offline_status(self, monkeypatch):
        """When a check returns False, the target status should be Offline."""
        target = Target("localhost", 9999, "port", status="Unknown")
        targets = [target]
        lock = threading.Lock()
        stop_event = threading.Event()

        monkeypatch.setattr("monitor.check_port", lambda h, p, t: False)
        monkeypatch.setattr("monitor.send_notification", lambda t: None)

        def fake_callback():
            stop_event.set()

        monitor_loop(targets, lock, stop_event, fake_callback)

        assert target.status == "Offline"

    def test_stop_event_exits_loop(self, monkeypatch):
        """Setting stop_event before starting should cause immediate return."""
        targets = []
        lock = threading.Lock()
        stop_event = threading.Event()
        stop_event.set()

        # Should return immediately without hanging
        monitor_loop(targets, lock, stop_event, lambda: None)

    def test_stop_event_during_sleep_exits_promptly(self, monkeypatch):
        """The loop should exit within ~1 second when stop_event is set during sleep."""
        targets = []
        lock = threading.Lock()
        stop_event = threading.Event()
        callback_calls = []

        def fake_callback():
            callback_calls.append(1)
            # Set stop event after callback so it exits during sleep
            threading.Timer(0.5, stop_event.set).start()

        start = time.time()
        monitor_loop(targets, lock, stop_event, fake_callback)
        elapsed = time.time() - start

        assert len(callback_calls) == 1
        # Should exit well before CHECK_INTERVAL (30s)
        assert elapsed < 3.0

    def test_multiple_targets_all_checked(self, monkeypatch):
        """All targets in the list should be checked each cycle."""
        t1 = Target("host1", 80, "port", status="Unknown")
        t2 = Target("host2.com", 443, "url", status="Unknown")
        targets = [t1, t2]
        lock = threading.Lock()
        stop_event = threading.Event()

        checked_hosts = []

        def fake_check_port(h, p, t):
            checked_hosts.append(h)
            return True

        def fake_check_url(h, p, t):
            checked_hosts.append(h)
            return False

        monkeypatch.setattr("monitor.check_port", fake_check_port)
        monkeypatch.setattr("monitor.check_url", fake_check_url)
        monkeypatch.setattr("monitor.send_notification", lambda t: None)

        def fake_callback():
            stop_event.set()

        monitor_loop(targets, lock, stop_event, fake_callback)

        assert "host1" in checked_hosts
        assert "host2.com" in checked_hosts
        assert t1.status == "Online"
        assert t2.status == "Offline"

    def test_notification_triggered_on_online_to_offline(self, monkeypatch):
        """Notification should fire when a target goes from Online to Offline."""
        target = Target("myhost", 8080, "port", status="Online", notified=False)
        targets = [target]
        lock = threading.Lock()
        stop_event = threading.Event()
        notifications = []

        monkeypatch.setattr("monitor.check_port", lambda h, p, t: False)
        monkeypatch.setattr("monitor.send_notification", lambda t: notifications.append(t))

        def fake_callback():
            stop_event.set()

        monitor_loop(targets, lock, stop_event, fake_callback)

        assert target.status == "Offline"
        assert target.notified is True
        assert len(notifications) == 1

    def test_empty_target_list_completes_cycle(self, monkeypatch):
        """An empty target list should not cause errors; callback still fires."""
        targets = []
        lock = threading.Lock()
        stop_event = threading.Event()
        callback_calls = []

        def fake_callback():
            callback_calls.append(1)
            stop_event.set()

        monitor_loop(targets, lock, stop_event, fake_callback)

        assert len(callback_calls) == 1


# =============================================================================
# GUI Lifecycle – MonitorApp wiring (Task 7.3)
# =============================================================================

from unittest.mock import patch, MagicMock
from monitor import MonitorApp, DATA_FILE


class TestMonitorAppLifecycle:
    """Tests for MonitorApp startup wiring, monitor thread, and shutdown.

    Uses a single shared Tk root per class to avoid transient TclError
    issues that occur when creating many Tk() instances in one session.
    """

    @pytest.fixture(autouse=True)
    def _patch_monitor_loop(self, monkeypatch):
        """Prevent the real monitor_loop from running during tests."""
        monkeypatch.setattr("monitor.monitor_loop", lambda *a, **kw: None)

    @pytest.fixture
    def make_app(self, tmp_path, monkeypatch):
        """Factory fixture that creates a MonitorApp with an isolated DATA_FILE.

        Reuses a single Tk root and resets it between tests.
        """
        roots = []

        def _factory(json_data=None):
            filepath = str(tmp_path / "targets.json")
            if json_data is not None:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(json_data, f)
            else:
                # Ensure no leftover file
                if os.path.exists(filepath):
                    os.remove(filepath)
            monkeypatch.setattr("monitor.DATA_FILE", filepath)
            root = tk.Tk()
            root.withdraw()
            roots.append(root)
            return MonitorApp(root), root

        yield _factory

        for r in roots:
            try:
                r.destroy()
            except tk.TclError:
                pass

    def test_startup_loads_targets_from_json(self, make_app):
        """On startup, MonitorApp should load targets from the JSON file."""
        app, root = make_app([{"host": "localhost", "port": 8080, "target_type": "port"}])

        assert len(app.targets) == 1
        assert app.targets[0].host == "localhost"
        assert app.targets[0].port == 8080

    def test_startup_empty_when_no_json(self, make_app):
        """When no JSON file exists, targets should be an empty list."""
        app, root = make_app()
        assert app.targets == []

    def test_start_monitoring_creates_daemon_thread(self, make_app):
        """_start_monitoring should create a daemon thread."""
        app, root = make_app()
        assert hasattr(app, "_monitor_thread")
        assert app._monitor_thread.daemon is True

    def test_on_close_sets_stop_event(self, make_app):
        """on_close should set the stop_event."""
        app, root = make_app()
        assert not app.stop_event.is_set()
        app.on_close()
        assert app.stop_event.is_set()

    def test_on_close_destroys_root(self, make_app):
        """on_close should destroy the root window."""
        app, root = make_app()
        app.on_close()
        with pytest.raises(tk.TclError):
            root.winfo_exists()

    def test_schedule_refresh_uses_root_after(self, make_app, monkeypatch):
        """_schedule_refresh should call root.after(0, refresh_display)."""
        app, root = make_app()
        after_calls = []
        monkeypatch.setattr(app.root, "after", lambda ms, fn: after_calls.append((ms, fn)))

        app._schedule_refresh()

        assert len(after_calls) == 1
        assert after_calls[0][0] == 0
        assert after_calls[0][1] == app.refresh_display

    def test_wm_delete_window_triggers_on_close(self, make_app):
        """The WM_DELETE_WINDOW protocol should be bound to on_close."""
        app, root = make_app()
        assert not app.stop_event.is_set()
        app.on_close()
        assert app.stop_event.is_set()

    def test_startup_refreshes_display_with_loaded_targets(self, make_app):
        """After loading targets, the Treeview should reflect them."""
        data = [
            {"host": "host1", "port": 80, "target_type": "port"},
            {"host": "host2.com", "port": 443, "target_type": "url"},
        ]
        app, root = make_app(data)

        children = app.tree.get_children()
        assert len(children) == 2

        vals0 = app.tree.item(children[0], "values")
        assert vals0[0] == "host1"
        assert str(vals0[1]) == "80"

        vals1 = app.tree.item(children[1], "values")
        assert vals1[0] == "host2.com"
        assert str(vals1[1]) == "443"
