import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


TEMPLATES = Path(__file__).resolve().parents[1] / 'skills/maestro/templates'
FAKE_ADB = r'''
adb() {
  printf '%s\n' "$*" >> "$CALLS"
  [[ "$1" == -s && "$2" == SER ]] || return 90
  shift 2
  case "$*" in
    get-state) printf '%s\n' "${DEVICE_STATE:-device}"; return "${DEVICE_CODE:-0}" ;;
    'shell settings get global wifi_on')
      if [[ -n "${WIFI_READ:-}" ]]; then printf '%s\n' "$WIFI_READ"; else read -r value < "$WIFI"; printf '%s\n' "$value"; fi ;;
    'shell cmd wifi set-wifi-enabled enabled'|'shell svc wifi enable')
      [[ "${SWITCH_FAIL:-0}" == 0 ]] || return 1
      printf '1\n' > "$WIFI" ;;
    'shell cmd wifi set-wifi-enabled disabled'|'shell svc wifi disable')
      [[ "${SWITCH_FAIL:-0}" == 0 ]] || return 1
      printf '0\n' > "$WIFI" ;;
    'shell wm size') printf '%s\n' "${SIZE:-Physical size: 1080x2400}" ;;
    'shell mktemp /data/local/tmp/forge-maestro-ui.XXXXXX') printf '%s\n' '/data/local/tmp/forge-maestro-ui.abc123' ;;
    'shell uiautomator dump /data/local/tmp/forge-maestro-ui.abc123') return "${DUMP_CODE:-0}" ;;
    'shell cat /data/local/tmp/forge-maestro-ui.abc123') printf '%s\n' "${DUMP_XML:-<hierarchy></hierarchy>}" ;;
    'shell rm -f /data/local/tmp/forge-maestro-ui.abc123') return "${REMOVE_CODE:-0}" ;;
    'shell input tap '*) return 0 ;;
    *) printf 'Unexpected fake adb call: %s\n' "$*" >&2; return 99 ;;
  esac
}
sleep() { :; }
maestro() { printf '%s\n' "$@" > "$MAESTRO_ARGS"; }
'''


class MaestroTemplates(unittest.TestCase):
    def run_script(self, script, initial='0', **values):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wifi, calls, args = root/'wifi', root/'calls', root/'args'
            wifi.write_text(initial+'\n')
            calls.write_text('')
            env = dict(os.environ, ANDROID_SERIAL='SER', WIFI=str(wifi), CALLS=str(calls), MAESTRO_ARGS=str(args))
            env.update(values)
            code = 'set -euo pipefail\nsource '+shlex.quote(str(TEMPLATES/'lib-device.sh'))+'\n'+FAKE_ADB+'\n'+script
            result = subprocess.run(['/bin/bash', '-c', code], env=env, capture_output=True, text=True, timeout=5)
            return result, wifi.read_text().strip(), calls.read_text(), args.read_text() if args.exists() else ''

    def test_bound_device_is_used(self):
        result, _, calls, _ = self.run_script('resolve_serial')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'SER\n')
        self.assertEqual(calls, '-s SER get-state\n')

    def test_missing_or_conflicting_binding_never_lists_devices(self):
        for script, env in [('resolve_serial', {'ANDROID_SERIAL': ''}), ('resolve_serial OTHER', {})]:
            with self.subTest(script=script):
                result, _, calls, _ = self.run_script(script, **env)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, '')

    def test_unavailable_device_and_changed_binding_stop_actions(self):
        for script, env in [('device_wifi SER off', {'DEVICE_STATE': 'offline'}), ('device_wifi SER off', {'DEVICE_CODE': '1'}), ('ANDROID_SERIAL=OTHER; device_wifi SER off', {})]:
            with self.subTest(script=script, env=env):
                result, _, calls, _ = self.run_script(script, **env)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('shell ', calls)

    def test_wifi_original_state_restored_on_normal_and_failed_exit(self):
        for original, action in [('0', 'on'), ('1', 'off')]:
            for code in [0, 7]:
                with self.subTest(original=original, code=code):
                    result, wifi, calls, _ = self.run_script(f'restore_wifi_on_exit SER\ndevice_wifi SER {action}\nexit {code}', initial=original)
                    self.assertEqual(result.returncode, code, result.stderr)
                    self.assertEqual(wifi, original)
                    self.assertNotIn('svc data', calls)

    def test_restore_failure_is_nonzero_and_preserves_original_failure(self):
        for code in [0, 7]:
            result, _, _, _ = self.run_script(f'restore_wifi_on_exit SER\nSWITCH_FAIL=1\nexit {code}')
            self.assertEqual(result.returncode, 1 if code == 0 else code)
            self.assertIn('恢复失败', result.stderr)

    def test_existing_cleanup_is_not_overwritten(self):
        result, _, _, _ = self.run_script("trap 'printf old-cleanup' EXIT\nrestore_wifi_on_exit SER")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('old-cleanup', result.stdout)
        self.assertIn('已有 EXIT trap', result.stderr)

    def test_term_restores_original_state(self):
        result, wifi, _, _ = self.run_script('restore_wifi_on_exit SER\ndevice_wifi SER on\nkill -TERM $$')
        self.assertEqual(result.returncode, 143, result.stderr)
        self.assertEqual(wifi, '0')

    def test_unknown_wifi_state_stops_before_mutation(self):
        result, _, calls, _ = self.run_script('restore_wifi_on_exit SER\ndevice_wifi SER off', WIFI_READ='null')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('set-wifi-enabled', calls)

    def test_failed_wifi_change_is_not_success(self):
        result, _, _, _ = self.run_script('device_wifi SER on', SWITCH_FAIL='1')
        self.assertNotEqual(result.returncode, 0)

    def test_square_and_override_display_dimensions(self):
        for raw, expected in [('Physical size: 1080x1080', '1080 1080\n'), ('Physical size: 1080x2400\r\nOverride size: 800x1200\r', '800 1200\n')]:
            result, _, _, _ = self.run_script('device_screen_size SER', SIZE=raw)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, expected)

    def test_ambiguous_or_invalid_dimensions_fail(self):
        for raw in ['Physical size: 0x100', 'Physical size: 800x1200\nPhysical size: 900x1300', 'unknown: 123x456']:
            result, _, _, _ = self.run_script('device_screen_size SER', SIZE=raw)
            self.assertNotEqual(result.returncode, 0)

    def test_dump_failure_never_reads_old_xml(self):
        result, _, calls, _ = self.run_script('device_ui_dump SER', DUMP_CODE='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('shell cat ', calls)
        self.assertIn('shell rm -f /data/local/tmp/forge-maestro-ui.abc123', calls)
        self.assertEqual(result.stdout, '')

    def test_dump_success_and_invalid_content(self):
        result, _, _, _ = self.run_script('device_ui_dump SER')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '<hierarchy></hierarchy>\n')
        result, _, _, _ = self.run_script('device_ui_dump SER', DUMP_XML='stale error')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')

    def test_maestro_arguments_keep_spaces(self):
        result, _, _, args = self.run_script('maestro_phase SER "/flow with spaces.yaml" prepare -e "VALUE=has spaces"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(args.splitlines(), ['--device', 'SER', 'test', '-e', 'PHASE=prepare', '-e', 'VALUE=has spaces', '/flow with spaces.yaml'])

    def test_tap_inputs_cannot_inject_shell_commands(self):
        for script in ['device_tap_pct SER "10; touch bad" 50', 'device_repeat_tap SER 0 0 "1; touch bad"']:
            result, _, calls, _ = self.run_script(script)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('shell input', calls)


if __name__ == '__main__':
    unittest.main()
