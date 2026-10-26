import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT/'skills/implement-ui/scripts/capture_ui.py'
spec = importlib.util.spec_from_file_location('capture_ui', SCRIPT)
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


def png():
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind+data))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b'\0\0\0\0\xff')) + chunk(b'IEND', b'')


class UiCapture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='forge ui evidence ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root/'fresh evidence'
        self.calls = []
        self.should_fail = None
        self.state = b'device\r\n'
        self.image = png()
        self.xml = b'<?xml version="1.0"?><hierarchy><node text="sample"/></hierarchy>'

    def fake_run(self, command, **kwargs):
        self.calls.append(command)
        self.assertEqual(command[:3], ['/fake sdk/adb', '-s', 'BOUND'])
        self.assertEqual(kwargs, {'capture_output': True, 'timeout': 20})
        args = command[3:]
        if self.should_fail and self.should_fail(args):
            return subprocess.CompletedProcess(command, 1, stdout=b'', stderr=b'failure')
        if args == ['get-state']:
            result = self.state
        elif args == ['exec-out', 'screencap', '-p']:
            result = self.image
        elif args[:3] == ['shell', 'uiautomator', 'dump']:
            self.assertRegex(args[3], r'^/data/local/tmp/forge-android-ui-[a-f0-9]{32}\.xml$')
            result = b'UI hierarchy dumped'
        elif args[:2] == ['exec-out', 'cat']:
            result = self.xml
        elif args[:3] == ['shell', 'rm', '-f']:
            result = b''
        elif args[:1] == ['shell']:
            result = b'sample value\n'
        else:
            self.fail('Unexpected command '+repr(command))
        return subprocess.CompletedProcess(command, 0, stdout=result, stderr=b'')

    def run_capture(self, *extra, bound='BOUND', output=None):
        argv = ['capture', '--output-dir', str(output or self.output), *extra]
        with patch.dict(os.environ, {'ANDROID_SERIAL': bound}), patch.object(sys, 'argv', argv), patch.object(capture.shutil, 'which', return_value='/fake sdk/adb'), patch.object(capture.subprocess, 'run', side_effect=self.fake_run):
            return capture.main()

    def test_capture_current_bound_device_with_spaces(self):
        self.assertEqual(self.run_capture(), 0)
        self.assertEqual((self.output/'screen.png').read_bytes(), self.image)
        self.assertEqual(self.output.stat().st_mode & 0o077, 0)
        metadata = json.loads((self.output/'device.json').read_text())
        self.assertEqual(metadata['serial'], 'BOUND')
        self.assertEqual(metadata['screenshot_width'], 1)
        self.assertFalse((self.output/'layout.xml').exists())
        self.assertEqual(self.calls[0][3:], ['get-state'])

    def test_unbound_and_conflicting_serial_do_not_call_adb(self):
        self.assertEqual(self.run_capture(bound=''), 1)
        self.assertEqual(self.run_capture('--serial', 'OTHER'), 1)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.output.exists())

    def test_offline_binding_never_captures_or_changes_device(self):
        self.state = b'offline\n'
        self.assertEqual(self.run_capture(), 1)
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(self.output.exists())

    def test_existing_evidence_is_unchanged(self):
        self.output.mkdir()
        image = self.output/'screen.png'
        image.write_bytes(b'previous evidence')
        self.assertEqual(self.run_capture(), 1)
        self.assertEqual(image.read_bytes(), b'previous evidence')
        self.assertEqual(self.calls, [])

    def test_plugin_output_and_symlink_into_plugin_are_rejected(self):
        link = self.root/'plugin'
        link.symlink_to(ROOT, target_is_directory=True)
        for path in [ROOT/'skills/analytics/rejected-ui', link/'skills/analytics/rejected-ui']:
            with self.subTest(path=str(path)):
                self.assertEqual(self.run_capture(output=path), 1)
                self.assertFalse(path.exists())
        self.assertEqual(self.calls, [])

    def test_invalid_screenshot_does_not_create_image(self):
        for index, image in enumerate([b'not a png', png()[:24]]):
            with self.subTest(index=index):
                self.output = self.root/f'invalid screenshot {index}'
                self.image = image
                self.assertEqual(self.run_capture(), 1)
                self.assertFalse((self.output/'screen.png').exists())

    def test_layout_uses_unique_path_and_cleans_only_that_path(self):
        self.assertEqual(self.run_capture('--layout-tree'), 0)
        self.assertEqual((self.output/'layout.xml').read_bytes(), self.xml)
        dump = next(c for c in self.calls if c[3:6] == ['shell', 'uiautomator', 'dump'])
        read = next(c for c in self.calls if c[3:5] == ['exec-out', 'cat'])
        clean = next(c for c in self.calls if c[3:6] == ['shell', 'rm', '-f'])
        self.assertEqual(dump[-1], read[-1])
        self.assertEqual(dump[-1], clean[-1])

    def test_dump_failure_never_reads_old_layout(self):
        self.should_fail = lambda args: args[:3] == ['shell', 'uiautomator', 'dump']
        self.assertEqual(self.run_capture('--layout-tree'), 1)
        self.assertFalse(any(c[3:5] == ['exec-out', 'cat'] for c in self.calls))
        self.assertTrue(any(c[3:6] == ['shell', 'rm', '-f'] for c in self.calls))
        self.assertTrue((self.output/'screen.png').is_file())
        self.assertFalse((self.output/'layout.xml').exists())

    def test_invalid_xml_and_cleanup_failure_are_not_success(self):
        self.xml = b'<old-error/>'
        self.assertEqual(self.run_capture('--layout-tree'), 1)
        self.assertFalse((self.output/'layout.xml').exists())
        self.output = self.root/'second capture'
        self.xml = b'<hierarchy/>'
        self.should_fail = lambda args: args[:3] == ['shell', 'rm', '-f']
        self.assertEqual(self.run_capture('--layout-tree'), 1)
        self.assertTrue((self.output/'screen.png').is_file())
        self.assertFalse((self.output/'layout.xml').exists())

    def test_subprocess_timeout_returns_failure(self):
        with patch.object(capture.subprocess, 'run', side_effect=subprocess.TimeoutExpired('adb', 20)):
            with self.assertRaises(capture.CaptureError):
                capture.command(['/fake sdk/adb', '-s', 'BOUND'], 'get-state', timeout=20)

    def test_invalid_timeout_stops_before_adb(self):
        self.assertEqual(self.run_capture('--timeout', '0'), 1)
        self.assertEqual(self.calls, [])

    def test_capture_does_not_install_launch_or_modify_global_settings(self):
        self.assertEqual(self.run_capture('--layout-tree'), 0)
        for call in self.calls:
            self.assertNotIn('install', call)
            self.assertNotIn('force-stop', call)
            self.assertNotIn('monkey', call)
            self.assertNotIn('devices', call)
            self.assertNotIn('put', call)
            self.assertNotIn('push', call)


if __name__ == '__main__':
    unittest.main()
