import contextlib
import importlib.util
import io
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'temp_logs.py'
spec = importlib.util.spec_from_file_location('temp_logs', SCRIPT)
logs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(logs)


def block(task='BUG-1', body='logger.debug("[TEMP:BUG-1] [A.run] seen")\n'):
    return f'// TEMP-LOG-BEGIN {task}\n{body}// TEMP-LOG-END {task}\n'


class TempLogsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='temp logs ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_cli(self, *arguments):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = logs.main([*arguments, '--root', str(self.root)])
        return code, out.getvalue() + err.getvalue()

    def write(self, content, name='Test.kt'):
        path = self.root / name
        path.write_bytes(content.encode('utf-8'))
        return path

    def test_preview_apply_and_idempotency_preserve_business(self):
        business = 'fun run() {\n    doBusiness()\n    logger.info("long term")\n}\n'
        path = self.write(block() + business)
        before = path.read_bytes()
        self.assertEqual(self.run_cli('clean', 'BUG-1')[0], 0)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.run_cli('verify', 'BUG-1')[0], 1)
        self.assertEqual(self.run_cli('clean', 'BUG-1', '--apply')[0], 0)
        self.assertEqual(path.read_bytes(), business.encode())
        self.assertEqual(self.run_cli('clean', 'BUG-1', '--apply')[0], 0)
        self.assertEqual(self.run_cli('verify', 'BUG-1')[0], 0)

    def test_java_multiline_import_constant_crlf_and_permissions(self):
        content = block(body='import sample.Logger;\n') + block(body='static final String TASK = "BUG-1";\n')
        content += 'class A {\n' + block(body='Logger.debug(\n TASK,\n "[A.run] seen");\n') + '}\n'
        path = self.write(content.replace('\n', '\r\n'), 'Test.java')
        path.chmod(0o640)
        self.assertEqual(self.run_cli('clean', 'BUG-1', '--apply')[0], 0)
        self.assertEqual(path.read_bytes(), b'class A {\r\n}\r\n')
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)

    def test_exact_task_isolation_and_list(self):
        other = block('BUG-10', 'logger.debug("[TEMP:BUG-10] [A.run] other")\n')
        path = self.write(block() + other)
        code, output = self.run_cli('list')
        self.assertEqual(code, 0)
        self.assertIn('BLOCK BUG-1 ', output)
        self.assertIn('BLOCK BUG-10 ', output)
        self.assertEqual(self.run_cli('clean', 'BUG-1', '--apply')[0], 0)
        self.assertEqual(path.read_text(), other)

    def test_unmanaged_reference_blocks_all_writes(self):
        first = self.write(block())
        self.write('logger.debug("[TEMP:BUG-1] old")\n', 'Old.java')
        before = first.read_bytes()
        code, output = self.run_cli('clean', 'BUG-1', '--apply')
        self.assertEqual(code, 2)
        self.assertIn('unmanaged reference', output)
        self.assertEqual(first.read_bytes(), before)

    def test_malformed_nested_and_unclosed(self):
        samples = ['// TEMP-LOG-BEGIN BUG-1\n', '// TEMP-LOG-END BUG-1\n',
                   '// TEMP-LOG-BEGIN BUG-1\n// TEMP-LOG-END BUG-2\n',
                   '// TEMP-LOG-BEGIN BUG-1\n' + block() + '// TEMP-LOG-END BUG-1\n',
                   '// TEMP-LOG-BEGIN BUG-1 trailing\n']
        for sample in samples:
            with self.subTest(sample=sample):
                path = self.write(sample)
                self.assertEqual(self.run_cli('clean', 'BUG-1', '--apply')[0], 2)
                self.assertEqual(path.read_text(), sample)

    def test_symlinks_build_and_untracked_files(self):
        with tempfile.TemporaryDirectory() as external:
            outside = Path(external) / 'Outside.kt'
            outside.write_text(block())
            (self.root / 'Link.kt').symlink_to(outside)
            (self.root / 'linked-dir').symlink_to(external, target_is_directory=True)
            (self.root / 'build').mkdir()
            self.write(block(), 'build/Generated.kt')
            untracked = self.write(block(), 'Untracked.kt')
            code, output = self.run_cli('clean', 'BUG-1', '--apply')
            self.assertEqual(code, 0)
            self.assertIn('SKIP Link.kt', output)
            self.assertEqual(outside.read_text(), block())
            self.assertEqual(untracked.read_text(), '')
            self.assertEqual((self.root / 'build/Generated.kt').read_text(), block())

    def test_preflight_concurrent_change_zero_writes(self):
        first = self.write(block(), 'A.kt')
        second = self.write(block(), 'B.kt')
        before = first.read_bytes()
        second.write_text('new business change')
        with self.assertRaisesRegex(RuntimeError, 'changed since inspection'):
            logs.apply_changes([(first, before, b''), (second, before, b'')])
        self.assertEqual(first.read_bytes(), before)
        self.assertEqual(second.read_text(), 'new business change')

    def test_partial_write_failure_is_reported_and_temporary_removed(self):
        first = self.write(block(), 'A.kt')
        second = self.write(block(), 'B.kt')
        before = first.read_bytes()
        replace = os.replace

        def fail_second(source, target):
            if target == second:
                raise OSError('simulated write error')
            replace(source, target)

        with patch.object(logs.os, 'replace', side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, 'already applied:.*A.kt'):
                logs.apply_changes([(first, before, b''), (second, before, b'')])
        self.assertEqual(first.read_bytes(), b'')
        self.assertEqual(second.read_bytes(), before)
        self.assertEqual(list(self.root.glob('.temp-logs-*')), [])

    def test_invalid_encoding_refuses_cleanup(self):
        path = self.write(block())
        (self.root / 'Other.java').write_bytes(b'\xff')
        self.assertEqual(self.run_cli('clean', 'BUG-1', '--apply')[0], 2)
        self.assertEqual(path.read_text(), block())


if __name__ == '__main__':
    unittest.main()
