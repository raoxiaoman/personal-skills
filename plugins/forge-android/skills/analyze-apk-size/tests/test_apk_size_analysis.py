#!/usr/bin/env python3
"""标准库测试；固定脚本路径，不从被分析 APK 导入代码。"""
import importlib.util
import json
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'apk_size_analysis.py'
spec = importlib.util.spec_from_file_location('apk_size_analysis', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def sample_dex(catch_all=False):
    data = bytearray(512)
    data[:8] = b'dex\n035\0'
    def put(at, value):
        struct.pack_into('<I', data, at, value)
    put(32, len(data))
    put(36, 112)
    put(40, 0x12345678)
    for at, count, offset in [(56, 3, 112), (64, 2, 124), (72, 1, 132),
                              (88, 1, 144), (96, 1, 152)]:
        put(at, count)
        put(at + 4, offset)
    for i, (offset, text) in enumerate([(400, b'Lcom/example/Test;'), (430, b'V'), (440, b'run')]):
        put(112 + 4 * i, offset)
        data[offset:offset + len(text) + 2] = bytes([len(text)]) + text + b'\0'
    put(124, 0)
    put(128, 1)
    put(132, 1)  # shorty
    put(136, 1)  # return type
    struct.pack_into('<HHI', data, 144, 0, 0, 2)
    put(152 + 8, 0xffffffff)  # superclass
    put(152 + 16, 0xffffffff)  # source file
    put(152 + 24, 200)
    data[200:208] = b'\x00\x00\x01\x00\x00\x01\x80\x02'
    struct.pack_into('<HHHHII', data, 256, 1, 0, 0, int(catch_all), 0, 2)
    data[272:276] = b'\x0e\x00\x0e\x00'
    if catch_all:
        struct.pack_into('<IHH', data, 276, 0, 2, 1)
        data[284:287] = b'\x01\x00\x00'  # 一个 handler，size=0，仅 catch-all，address=0
    return bytes(data)


def apk(path, extras=None, dex=None):
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('classes.dex', sample_dex() if dex is None else dex,
                         compress_type=zipfile.ZIP_DEFLATED)
        for name, content in (extras or {}).items():
            archive.writestr(name, content, compress_type=zipfile.ZIP_STORED)


class DexTests(unittest.TestCase):
    def test_code_item(self):
        dex = module.Dex(sample_dex())
        self.assertEqual(dex.code_size(256), 20)
        result = dex.analyze({})
        group = result['groups']['prefix:com/example/Test']
        self.assertEqual(group, {'classes': 1, 'methods': 1, 'bytes': 68})
        self.assertEqual(result['unassigned_bytes'], 512 - 68)

    def test_catch_all(self):
        dex = module.Dex(sample_dex(True))
        self.assertEqual(dex.code_size(256), 31)
        self.assertEqual(sum(g['bytes'] for g in dex.analyze({})['groups'].values()), 79)

    def test_typed_and_catch_all(self):
        data = bytearray(sample_dex(True))
        data[284:289] = b'\x01\x7f\x00\x00\x00'  # size=-1，typed + catch-all
        self.assertEqual(module.Dex(bytes(data)).code_size(256), 33)

    def test_odd_instructions_padding(self):
        data = bytearray(sample_dex(True))
        struct.pack_into('<I', data, 268, 1)
        struct.pack_into('<H', data, 280, 1)
        self.assertEqual(module.Dex(bytes(data)).code_size(256), 31)

    def test_invalid_handler(self):
        data = bytearray(sample_dex(True))
        struct.pack_into('<H', data, 282, 2)
        with self.assertRaises(module.AnalysisError):
            module.Dex(bytes(data)).code_size(256)

    def test_bad_headers(self):
        for data in [b'bad', sample_dex()[:-1], b'dex\n041\0' + sample_dex()[8:]]:
            with self.subTest(data=data[:8]), self.assertRaises(module.AnalysisError):
                module.Dex(data)

    def test_invalid_string_index(self):
        data = bytearray(sample_dex())
        struct.pack_into('<I', data, 124, 999)
        with self.assertRaises(module.AnalysisError):
            module.Dex(bytes(data)).analyze({})

    def test_leb_bounds(self):
        dex = module.Dex(sample_dex())
        with self.assertRaises(module.AnalysisError):
            dex.leb(512)
        data = bytearray(sample_dex())
        data[200:205] = b'\x80' * 5
        with self.assertRaises(module.AnalysisError):
            module.Dex(bytes(data)).analyze({})

    def test_prefix_specificity(self):
        rules = {'com/': 'general', 'com/example/': 'application'}
        self.assertEqual(module.package_group('Lcom/example/Test;', rules), 'application')
        self.assertEqual(module.package_group('La/b;', rules), 'Other / obfuscated')


class ZipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old = self.root / 'old package.apk'
        self.new = self.root / 'new package.apk'

    def test_reconciliation_and_files(self):
        apk(self.old, {'assets/shrink': b'x' * 100, 'res/deleted': b'x' * 30})
        apk(self.new, {'assets/shrink': b'x' * 50, 'lib/arm64-v8a/new.so': b'x' * 200})
        report = module.compare(self.old, self.new)
        self.assertEqual(report['delta_bytes'], self.new.stat().st_size - self.old.stat().st_size)
        self.assertEqual(report['reconciled_delta_bytes'], report['delta_bytes'])
        files = {f['path']: f for f in report['files']}
        self.assertEqual(files['assets/shrink']['delta_compressed_bytes'], -50)
        self.assertEqual(files['res/deleted']['status'], 'removed')
        self.assertEqual(files['lib/arm64-v8a/new.so']['status'], 'added')
        self.assertEqual(report['old']['dex']['groups'], report['new']['dex']['groups'])

    def test_identical(self):
        apk(self.old)
        report = module.compare(self.old, self.old)
        self.assertEqual(report['delta_bytes'], 0)
        self.assertEqual(report['files'], [])

    def test_compressed_vs_raw(self):
        apk(self.old)
        report = module.compare(self.old, self.old)
        dex = next(g for g in report['categories'] if g['name'] == 'DEX')
        self.assertLess(dex['old_compressed_bytes'], 512)
        self.assertEqual(report['old']['dex']['raw_bytes'], 512)

    def test_properties(self):
        apk(self.old, {'billing.properties': b'version=1.0\nclient=billing\n'})
        report = module.compare(self.old, self.old)
        self.assertEqual(report['old']['sdk_properties']['billing.properties']['version'], '1.0')

    def test_partial_dex(self):
        apk(self.old)
        apk(self.new, dex=b'bad dex')
        report = module.compare(self.old, self.new)
        self.assertFalse(report['new']['dex']['complete'])
        self.assertEqual(report['delta_bytes'], report['reconciled_delta_bytes'])
        self.assertIn('DEX 解析不完整', module.render(report))
        completed = subprocess.run([sys.executable, '-I', str(SCRIPT), str(self.old), str(self.new)], capture_output=True)
        self.assertEqual(completed.returncode, 2)

    def test_duplicate_entry(self):
        apk(self.old)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with zipfile.ZipFile(self.old, 'a') as archive:
                archive.writestr('classes.dex', sample_dex())
        with self.assertRaises(module.AnalysisError):
            module.compare(self.old, self.old)

    def test_cli_outputs_and_no_overwrite(self):
        apk(self.old)
        apk(self.new)
        output = self.root / 'report'
        args = [sys.executable, '-I', str(SCRIPT), str(self.old), str(self.new), '--output-dir', str(output)]
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((output / 'report.md').read_text(), result.stdout.rstrip('\n') + '\n')
        self.assertEqual(json.loads((output / 'report.json').read_text())['delta_bytes'], 0)
        self.assertEqual(subprocess.run(args, capture_output=True).returncode, 1)

    def test_output_cannot_pollute_sibling_skill(self):
        apk(self.old)
        apk(self.new)
        output = SCRIPT.parents[2] / 'maestro' / 'rejected-apk-report'
        args = [sys.executable, '-I', '-B', str(SCRIPT), str(self.old), str(self.new), '--output-dir', str(output)]
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('整个插件之外', result.stderr)
        self.assertFalse(output.exists())

    def test_bad_zip_and_missing_file(self):
        self.old.write_bytes(b'not a zip')
        apk(self.new)
        args = [sys.executable, '-I', str(SCRIPT), str(self.old), str(self.new)]
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('错误', result.stderr)
        with self.assertRaises(FileNotFoundError):
            module.compare(self.root / 'missing', self.new)


if __name__ == '__main__':
    unittest.main(verbosity=2)
