import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT/'skills/check-release/scripts'
sys.path.insert(0, str(SCRIPTS))
import release_apk_check
import release_tracking_check


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


baseline = load('forge_baseline', SCRIPTS/'baseline-profile.py')


class ReleaseIntegration(unittest.TestCase):
    def test_baseline_requires_current_binding(self):
        with self.assertRaises(ValueError):
            baseline.serial_value('emulator-5554', None)
        with self.assertRaises(ValueError):
            baseline.serial_value('emulator-5554', 'emulator-5556')
        self.assertEqual(baseline.serial_value('emulator-5554', 'emulator-5554'), 'emulator-5554')

    def test_capture_without_binding_does_not_call_adb(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'events.json'
            argv = ['capture', '--capture', '--serial', 'old-device', '--package', 'com.example.app', '--content', 'denoise', '--output', str(output)]
            with patch.dict(os.environ, {'ANDROID_SERIAL': ''}), patch.object(sys, 'argv', argv), patch.object(subprocess, 'check_output') as command:
                self.assertNotEqual(release_tracking_check.main(), 0)
                command.assert_not_called()
            self.assertFalse(output.exists())

    def test_capture_rejects_offline_binding_before_process_query(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'events.json'
            argv = ['capture', '--capture', '--package', 'com.example.app', '--content', 'denoise', '--output', str(output)]
            with patch.dict(os.environ, {'ANDROID_SERIAL': 'SER'}), patch.object(sys, 'argv', argv), patch.object(subprocess, 'check_output', return_value='offline\n') as command:
                self.assertNotEqual(release_tracking_check.main(), 0)
                command.assert_called_once_with(['adb', '-s', 'SER', 'get-state'], text=True, timeout=10)
            self.assertFalse(output.exists())

    def test_tracking_output_cannot_pollute_plugin_or_follow_symlink_into_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'events.log'
            source.write_text('E UtTrackFirebaseImpl: logEvent: event: select_content, content: denoise, item_id: start')
            (root/'plugin-link').symlink_to(ROOT, target_is_directory=True)
            for output in [ROOT/'skills/maestro/rejected-tracking.json', root/'plugin-link/skills/maestro/rejected-tracking.json']:
                argv = ['tracking', '--input', str(source), '--content', 'denoise', '--output', str(output)]
                with self.subTest(output=str(output)), patch.object(sys, 'argv', argv), patch.object(subprocess, 'check_output') as command:
                    self.assertNotEqual(release_tracking_check.main(), 0)
                    command.assert_not_called()
                self.assertFalse(output.exists())

    def test_real_same_plugin_apk_delegation_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix='forge apk delegation ') as directory:
            root = Path(directory)
            old, new = root/'old package.apk', root/'new package.apk'
            for apk in (old, new):
                with zipfile.ZipFile(apk, 'w') as archive:
                    archive.writestr('assets/sample.txt', b'sample')
            result = release_apk_check.analyze(old, new, root/'fresh report')
            self.assertEqual(result['tool'], str(ROOT/'skills/analyze-apk-size/scripts/apk_size_analysis.py'))
            self.assertEqual(result['returncode'], 2)
            self.assertEqual(result['measurement'], 'ZIP可用，DEX归因不完整')
            self.assertEqual(result['status'], '待确认')
            report = json.loads(Path(result['json']).read_text())
            self.assertEqual(report['delta_bytes'], 0)
            self.assertEqual(report['reconciled_delta_bytes'], 0)


if __name__ == '__main__':
    unittest.main()
