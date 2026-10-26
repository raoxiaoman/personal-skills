#!/usr/bin/env python3
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

import importlib.util
import io
import contextlib
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'watch_android_logcat.py'
spec = importlib.util.spec_from_file_location('watch_android_logcat', SCRIPT)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


class WatchAndroidLogcatTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "logs"
        self.calls = self.root / "adb-calls.txt"
        self.fake_adb = self.root / "adb"
        self.fake_adb.write_text(textwrap.dedent("""\
            #!/usr/bin/env python3
            import os, sys, time
            args = sys.argv[1:]
            with open(os.environ['FAKE_ADB_CALLS'], 'a') as handle:
                handle.write(repr(args) + '\\n')
            if args == ['devices']:
                print('List of devices attached')
                print(os.environ.get('FAKE_DEVICES', 'only-device') + '\\tdevice')
                sys.exit(0)
            if len(args) < 3 or args[0] != '-s':
                print('missing fixed serial', file=sys.stderr)
                sys.exit(9)
            rest = args[2:]
            if rest == ['get-state']:
                state = os.environ.get('FAKE_STATE', 'device')
                print(state)
                sys.exit(0 if state == 'device' else 1)
            if rest[:5] == ['shell', 'cmd', 'package', 'list', 'packages']:
                if os.environ.get('FAKE_UID_FAIL'):
                    print('permission denied', file=sys.stderr)
                    sys.exit(1)
                package = rest[-1]
                print('package:' + package + ' uid:' + os.environ.get('FAKE_UID', '10123'))
                sys.exit(0)
            if rest == ['shell', 'date', '+%s.%N']:
                print('1788834600.123456789')
                sys.exit(0)
            if rest[:1] == ['logcat'] and '-d' in rest:
                if os.environ.get('FAKE_UID_UNSUPPORTED'):
                    print('unknown option --uid', file=sys.stderr)
                    sys.exit(1)
                sys.exit(0)
            if rest[:1] == ['logcat']:
                if os.environ.get('FAKE_START_FAIL'):
                    print('permission denied for --uid', file=sys.stderr)
                    sys.exit(1)
                for line in os.environ.get('FAKE_LOGS', '').split('\\n'):
                    if line:
                        print(line, flush=True)
                if os.environ.get('FAKE_EXIT'):
                    time.sleep(float(os.environ.get('FAKE_EXIT_DELAY', '0')))
                    print('transport disconnected', file=sys.stderr, flush=True)
                    sys.exit(int(os.environ.get('FAKE_EXIT')))
                while True:
                    time.sleep(.1)
            print('unexpected: ' + repr(rest), file=sys.stderr)
            sys.exit(8)
        """))
        self.fake_adb.chmod(0o755)
        self.base_env = os.environ.copy()
        self.base_env.pop("ANDROID_SERIAL", None)
        self.base_env.update({"FAKE_ADB_CALLS": str(self.calls), "FAKE_UID": "10123"})

    def tearDown(self):
        self.temp.cleanup()

    def launch(self, extra=None, serial=None):
        command = [sys.executable, str(SCRIPT), "--task", "TASK-42", "--package", "com.example.app", "--output", str(self.output), "--adb", str(self.fake_adb)]
        if serial:
            command.extend(["--serial", serial])
        env = self.base_env.copy()
        if extra:
            env.update(extra)
        return subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)

    @staticmethod
    def wait_ready(process):
        deadline = time.time() + 5
        lines = []
        while time.time() < deadline:
            line = process.stdout.readline()
            if line:
                lines.append(line)
                if line.startswith("READY "):
                    return lines
            elif process.poll() is not None:
                break
        stdout, stderr = process.communicate(timeout=2)
        raise AssertionError(f"collector did not become ready: {''.join(lines)}{stdout} {stderr}")

    def stop(self, process):
        process.terminate()
        stdout, stderr = process.communicate(timeout=5)
        return stdout, stderr

    def logs(self):
        files = list(self.output.rglob("*.log"))
        self.assertEqual(1, len(files))
        return files[0], files[0].read_text()

    def test_explicit_serial_uid_command_and_exact_filters(self):
        lines = "\n".join([
            "09-08 10:30:01.000  100  100 I ProjectLogger: [TEMP:TASK-42] [A.run] first process",
            "09-08 10:30:02.000  200  200 I ProjectLogger: [TEMP:TASK-42] [A.run] restarted process",
            "09-08 10:30:03.000  200  200 E AndroidRuntime: FATAL EXCEPTION: main",
            "09-08 10:30:04.000  200  200 E AndroidRuntime: java.lang.IllegalStateException",
            "09-08 10:30:05.000  200  200 F libc: Fatal signal 11 (SIGSEGV)",
            "09-08 10:30:06.000  200  200 F DEBUG: backtrace:",
            "09-08 10:30:07.000  200  200 I ProjectLogger: [TEMP:TASK-420] [A.run] near-miss tag",
            "09-08 10:30:08.000  999  999 I ForeignApp: foreign log",
            "09-08 10:30:09.000  200  200 I OtherTag: target uid noise",
        ])
        process = self.launch({"FAKE_LOGS": lines}, serial="explicit-device")
        ready = self.wait_ready(process)
        time.sleep(.25)
        stdout, stderr = self.stop(process)
        path, contents = self.logs()
        self.assertIn("serial=explicit-device uid=10123", "".join(ready))
        self.assertIn("first process", contents)
        self.assertIn("restarted process", contents)
        self.assertIn("AndroidRuntime", contents)
        self.assertIn("Fatal signal", contents)
        self.assertIn("backtrace:", contents)
        self.assertNotIn("near-miss", contents)
        self.assertNotIn("foreign log", contents)
        self.assertNotIn("target uid noise", contents)
        self.assertNotIn("ForeignApp", "".join(ready) + stdout + stderr)
        self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
        self.assertEqual(0o700, stat.S_IMODE(self.output.stat().st_mode))
        calls = self.calls.read_text()
        self.assertIn("['-s', 'explicit-device', 'logcat', '--uid', '10123', '-d', '-t', '1']", calls)
        self.assertIn("['-s', 'explicit-device', 'logcat', '--uid', '10123', '-T', '1788834600.123456789', '-v', 'threadtime', '*:V']", calls)

    def test_android_serial_is_used_without_enumeration(self):
        process = self.launch({"ANDROID_SERIAL": "environment-device"})
        ready = self.wait_ready(process)
        self.stop(process)
        self.assertIn("serial=environment-device", "".join(ready))
        self.assertNotIn("['devices']", self.calls.read_text())

    def test_unbound_device_fails_without_enumerating(self):
        process = self.launch()
        stdout, stderr = process.communicate(timeout=5)
        self.assertEqual(2, process.returncode, stdout + stderr)
        self.assertIn("未绑定设备", stdout)
        self.assertFalse(self.calls.exists())
        self.assertFalse(self.output.exists())

    def test_conflicting_serial_fails_before_any_adb_call(self):
        process = self.launch({"ANDROID_SERIAL": "bound-device"}, serial="other-device")
        stdout, stderr = process.communicate(timeout=5)
        self.assertEqual(2, process.returncode, stdout + stderr)
        self.assertIn("绑定不一致", stdout)
        self.assertFalse(self.calls.exists())

    def test_unavailable_bound_device_never_falls_back(self):
        for state in ("offline", "unauthorized"):
            with self.subTest(state=state):
                process = self.launch({"ANDROID_SERIAL": "bound-device", "FAKE_STATE": state})
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(2, process.returncode, stdout + stderr)
                self.assertIn("不会换机", stdout)
        calls = self.calls.read_text()
        self.assertNotIn("['devices']", calls)
        self.assertNotIn("'logcat'", calls)
        self.assertFalse(self.output.exists())

    def test_unsupported_uid_filter_fails_without_global_fallback(self):
        process = self.launch({"FAKE_UID_UNSUPPORTED": "1"}, serial="device")
        stdout, stderr = process.communicate(timeout=5)
        self.assertEqual(2, process.returncode)
        self.assertIn("不会降级为全局日志采集", stdout)
        self.assertFalse(self.output.exists())
        calls = self.calls.read_text()
        self.assertIn("--uid", calls)
        self.assertNotIn("'-T'", calls)

    def test_logcat_exit_and_permission_failure_are_reported(self):
        denied = self.launch({"FAKE_UID_FAIL": "1"}, serial="device")
        stdout, stderr = denied.communicate(timeout=5)
        self.assertEqual(2, denied.returncode)
        self.assertIn("权限", stdout)
        self.assertFalse(self.output.exists())
        exited = self.launch({"FAKE_EXIT": "7", "FAKE_EXIT_DELAY": "0.6"}, serial="device")
        stdout, stderr = exited.communicate(timeout=5)
        self.assertEqual(2, exited.returncode)
        self.assertIn("logcat", stdout)

    def test_sigterm_stops_collector_and_emits_bounded_status(self):
        process = self.launch(serial="device")
        self.wait_ready(process)
        stdout, stderr = self.stop(process)
        self.assertEqual(0, process.returncode, stdout + stderr)
        self.assertIn("STATUS stopped", stdout)
        self.assertNotIn("List of devices", stdout)


    def test_device_binding_is_checked_before_uid_query(self):
        process = self.launch({"ANDROID_SERIAL": "bound-device"}, serial="bound-device")
        ready = self.wait_ready(process)
        self.stop(process)
        calls = self.calls.read_text().splitlines()
        self.assertEqual("['-s', 'bound-device', 'get-state']", calls[0])
        self.assertIn("'packages'", calls[1])
        self.assertIn("serial=bound-device", "".join(ready))

    def test_output_default_uses_external_cache(self):
        with patch.dict(os.environ, {"XDG_CACHE_HOME": str(self.root / "cache")}, clear=True):
            args = collector.parse_args(['--task', 'BUG-1', '--package', 'com.example.app'])
            self.assertEqual(str(self.root / 'cache' / 'forge-android' / 'logcat'), args.output)
        with patch.dict(os.environ, {"XDG_CACHE_HOME": "relative-cache"}, clear=True):
            self.assertEqual(str(Path.home() / '.cache' / 'forge-android' / 'logcat'), collector.default_output_directory())

    def test_flood_is_saved_without_per_line_notifications(self):
        lines = '\n'.join(f'09-08 10:30:01.123  1  2 D Logger: [TEMP:TASK-42] [A.run] item-{i}' for i in range(1000))
        process = self.launch({'FAKE_LOGS': lines}, serial='device')
        ready = self.wait_ready(process)
        time.sleep(.3)
        stdout, stderr = self.stop(process)
        self.assertEqual(process.returncode, 0, stdout + stderr)
        self.assertEqual(len(self.logs()[1].splitlines()), 1000)
        self.assertLess(len((''.join(ready) + stdout).splitlines()), 10)

    def test_single_line_notifies_after_silence_and_flood_is_batched(self):
        output = io.StringIO()
        with patch.object(collector.time, 'monotonic', return_value=0), contextlib.redirect_stdout(output):
            reporter = collector.StatusReporter()
            reporter.record()
            self.assertEqual(output.getvalue(), '')
            with patch.object(collector.time, 'monotonic', return_value=6):
                reporter.flush()
            self.assertIn('captured=1', output.getvalue())
            for _ in range(1000):
                reporter.record()
            self.assertEqual(len(output.getvalue().splitlines()), 1)
            reporter.flush(force=True)
            self.assertIn('captured=1000', output.getvalue())

    def test_output_sessions_unique_and_existing_permissions_unchanged(self):
        self.output.mkdir(mode=0o755)
        first, stream = collector.create_output_file(str(self.output), 'TASK-42')
        stream.close()
        second, stream = collector.create_output_file(str(self.output), 'TASK-42')
        stream.close()
        self.assertNotEqual(first, second)
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(first.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o600)

    def test_defaults_validation_and_message_marker(self):
        args = collector.parse_args(['--task', 'BUG-1', '--package', 'com.example.app'])
        self.assertTrue(args.output.endswith('/forge-android/logcat'))
        self.assertTrue(collector.keep_line('09-08 10:30:00.123  1  2 D Class: [TEMP:BUG-1] [Class.run] yes', 'BUG-1'))
        self.assertFalse(collector.keep_line('09-08 10:30:00.123  1  2 D Class: [TEMP:BUG-10] no', 'BUG-1'))
        self.assertTrue(collector.keep_line('09-08 10:30:00.123  1  2 D [TEMP:BUG-1]: yes', 'BUG-1'))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            collector.parse_args(['--task', '../BAD', '--package', 'com.example.app'])

    def test_start_failure_never_reports_ready(self):
        process = self.launch({'FAKE_START_FAIL': '1'}, serial='device')
        stdout, stderr = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 2)
        self.assertNotIn('READY', stdout)
        self.assertIn('ERROR', stdout)

    def test_size_cap_stops_with_visible_error(self):
        env = self.base_env.copy()
        env['FAKE_LOGS'] = '09-08 10:30:00.123  1  2 D Class: [TEMP:TASK-42] [Class.run] hello'
        result = subprocess.run([sys.executable, str(SCRIPT), '--task', 'TASK-42', '--package', 'com.example.app',
                                 '--serial', 'device', '--output', str(self.output), '--adb', str(self.fake_adb), '--max-bytes', '20'],
                                env=env, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertIn('--max-bytes=20', result.stdout)
        self.assertIn('hello', self.logs()[1])


if __name__ == "__main__":
    unittest.main()
