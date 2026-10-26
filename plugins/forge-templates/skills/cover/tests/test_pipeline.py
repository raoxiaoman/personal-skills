import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile


SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL/'scripts'))
import build_config as build
import template_common as common
import validate_template as validate


def config():
    text = dict(TI_1='title', TI_6='/fonts/Test.ttf', TI_12=7, TI_13=1)
    sticker = dict(SI_1='file:///stickers/template7_sticker1.png', SI_10=7, SI_11=1)
    return dict(texts=[text], textsH=[dict(text)], stickers=[sticker], stickersH=[dict(sticker)])


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='forge cover pipeline ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = config()
        self.source = self.save('input.json', self.data)
        self.stickers, self.fonts = self.root/'stickers', self.root/'fonts'
        self.stickers.mkdir(); self.fonts.mkdir()
        (self.stickers/'template7_sticker1.png').write_bytes(b'local png fixture')
        (self.fonts/'Test.ttf').write_bytes(b'local font fixture')
        self.cover = self.root/'cover.webp'
        self.cover.write_bytes(b'local cover fixture')

    def save(self, name, data):
        path = self.root/name
        path.write_text(json.dumps(data), encoding='utf-8')
        return path

    def run_cli(self, name, *args):
        return subprocess.run([sys.executable, '-I', '-B', str(SKILL/'scripts'/name), *map(str, args)], capture_output=True, text=True, timeout=15)

    def package(self, output=None):
        return self.run_cli('package_template.py', '--config', self.source, '--stickers', self.stickers, '--fonts', self.fonts, '--cover', self.cover, '--template-num', 7, '--out', output or self.root/'package')

    def test_package_then_strict_local_validation(self):
        result = self.package()
        self.assertEqual(result.returncode, 0, result.stderr)
        archive = self.root/'package/template7.zip'
        result = self.run_cli('validate_template.py', '--config', self.source, '--zip', archive)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('远端：未执行', result.stdout)
        with zipfile.ZipFile(archive) as stream:
            self.assertEqual(set(stream.namelist()), {'cover_template_item_config_7.json', 'template7_sticker1.png', 'Test.ttf'})

    def test_stable_sticker_numbers_survive_directory_order(self):
        rows = [dict(SI_1='file:///stickers/template7_sticker2.png', SI_10=7, SI_11=1),
                dict(SI_1='file:///stickers/template7_sticker10.png', SI_10=7, SI_11=2)]
        self.data['stickers'] = rows
        self.data['stickersH'] = copy.deepcopy(rows)
        self.source = self.save('final.json', self.data)
        (self.stickers/'template7_sticker10.png').write_bytes(b'arrow ten')
        (self.stickers/'template7_sticker2.png').write_bytes(b'arrow two')
        result = self.package()
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(self.root/'package/template7.zip') as archive:
            self.assertEqual(archive.read('template7_sticker2.png'), b'arrow two')
            self.assertEqual(archive.read('template7_sticker10.png'), b'arrow ten')
            self.assertNotIn('template7_sticker1.png', archive.namelist())
            saved = json.loads(archive.read('cover_template_item_config_7.json'))
            self.assertEqual(saved['stickers'], rows)

    def test_existing_build_and_archive_are_never_removed(self):
        output = self.root/'package'
        (output/'build').mkdir(parents=True)
        marker = output/'build/user-work'
        marker.write_bytes(b'keep')
        result = self.package(output)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(marker.read_bytes(), b'keep')

    def test_missing_asset_rejected_before_output_creation(self):
        (self.fonts/'Test.ttf').unlink()
        result = self.package()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root/'package').exists())

    def test_asset_symlink_escape_rejected(self):
        (self.fonts/'Test.ttf').unlink()
        (self.fonts/'Test.ttf').symlink_to(self.cover)
        result = self.package()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root/'package').exists())

    def test_merge_preserves_full_export_and_input_files(self):
        exported = copy.deepcopy(self.data)
        exported['manualExport'] = 'preserve exact values'
        path = self.save('exported.json', exported)
        output = self.root/'merged.json'
        before = self.source.read_bytes()
        result = self.run_cli('merge_export.py', '--base', self.source, '--exported', path, '--out', output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(output.read_text()), exported)
        self.assertEqual(self.source.read_bytes(), before)
        result = self.run_cli('merge_export.py', '--base', self.source, '--exported', path, '--out', self.source)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.source.read_bytes(), before)
        other = copy.deepcopy(exported)
        for group in ('texts', 'textsH'):
            other[group][0]['TI_12'] = 8
        for group in ('stickers', 'stickersH'):
            other[group][0]['SI_10'] = 8
            other[group][0]['SI_1'] = 'file:///stickers/template8_sticker1.png'
        wrong = self.save('wrong-template.json', other)
        rejected = self.root/'rejected.json'
        result = self.run_cli('merge_export.py', '--base', self.source, '--exported', wrong, '--out', rejected)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(rejected.exists())

    def test_partial_export_requires_direction_and_preserves_other_side(self):
        partial = {'texts': copy.deepcopy(self.data['texts']), 'stickers': copy.deepcopy(self.data['stickers'])}
        partial['texts'][0]['manualPosition'] = [9, 12]
        path = self.save('partial.json', partial)
        output = self.root/'merged.json'
        args = ('--base', self.source, '--exported', path, '--out', output)
        self.assertNotEqual(self.run_cli('merge_export.py', *args).returncode, 0)
        self.assertFalse(output.exists())
        result = self.run_cli('merge_export.py', *args, '--direction', 'v')
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(output.read_text())
        self.assertEqual(value['texts'], partial['texts'])
        self.assertEqual(value['textsH'], self.data['textsH'])

    def test_configuration_identity_and_geometry_failures(self):
        cases = []
        duplicate = copy.deepcopy(self.data); duplicate['texts'].append(duplicate['texts'][0]); cases.append(duplicate)
        wrong = copy.deepcopy(self.data); wrong['stickersH'][0]['SI_1'] = 'file:///x/template7_sticker2.png'; cases.append(wrong)
        title = copy.deepcopy(self.data); title['textsH'][0]['TI_1'] = 'other'; cases.append(title)
        matrix = copy.deepcopy(self.data); matrix['texts'][0]['BI_10'] = [0]; cases.append(matrix)
        number = copy.deepcopy(self.data); number['texts'][0]['TI_12'] = 8; cases.append(number)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValueError):
                common.validate_config(value)

    def test_zip_duplicate_extra_or_stale_config_fails(self):
        self.assertEqual(self.package().returncode, 0)
        good = self.root/'package/template7.zip'
        for case in ['duplicate', 'extra', 'stale']:
            folder = self.root/case; folder.mkdir()
            archive = folder/'template7.zip'
            with zipfile.ZipFile(good) as source, zipfile.ZipFile(archive, 'w') as target:
                for name in source.namelist():
                    content = source.read(name)
                    if case == 'stale' and name.endswith('.json'):
                        value = json.loads(content); value['extra'] = 'stale'; content = json.dumps(value).encode()
                    target.writestr(name, content)
                if case == 'duplicate':
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore')
                        target.writestr('Test.ttf', b'duplicate')
                if case == 'extra':
                    target.writestr('cover_config_android_v2.json', b'{}')
            result = self.run_cli('validate_template.py', '--config', self.source, '--zip', archive)
            self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_remote_urls_require_explicit_https_and_default_is_offline(self):
        self.assertEqual(self.package().returncode, 0)
        argv = ['validate', '--config', str(self.source), '--zip', str(self.root/'package/template7.zip')]
        with patch.object(sys, 'argv', argv), patch.object(validate.urllib.request, 'build_opener') as opener:
            self.assertEqual(validate.main(), 0)
            opener.return_value.open.assert_not_called()
        with patch.object(sys, 'argv', argv+['--base-url', 'http://localhost/template7']), patch.object(validate.urllib.request, 'build_opener') as opener:
            self.assertNotEqual(validate.main(), 0)
            opener.assert_not_called()

    def test_plugin_and_symlink_output_boundaries(self):
        link = self.root/'plugin'; link.symlink_to(common.PLUGIN, target_is_directory=True)
        for output in [common.PLUGIN/'not-a-report', link/'not-a-report']:
            with self.subTest(output=output), self.assertRaises(ValueError):
                common.new_output(output)

    def test_text_mismatch_and_duplicate_content_are_not_guessed(self):
        context = {'avg': (10, 20), 'canvas': (100, 200)}
        with self.assertRaises(ValueError):
            build._align_texts([{'TI_1': 'A'}], [{'TI_1': 'B'}], context, context, 'text')
        with self.assertRaises(ValueError):
            build._align_texts([{'TI_1': 'A'}, {'TI_1': 'A'}], [{'TI_1': 'A'}, {'TI_1': 'A'}], context, context, 'text')

    def test_build_cli_reports_pairs_and_normalizes_reordered_sticker_ids(self):
        def element(name, width, height, x):
            return dict(kind='image', id=name, name=name, rot=0, box=dict(x=x, y=30, w=width, h=height))
        a, b = element('small', 10, 20, 10), element('large', 50, 60, 90)
        vertical = self.save('vertical.json', {'frame': {'w': 400, 'h': 600}, 'elements': [a, b]})
        horizontal = self.save('horizontal.json', {'frame': {'w': 600, 'h': 400}, 'elements': [b, a]})
        meta = self.save('meta.json', dict(templateNum=7, fontDir='/fonts', stickerDir='/stickers', fonts={}, canvas=[400, 600], canvasH=[600, 400]))
        output = self.root/'generated'
        args = ('--figma', vertical, '--figma-h', horizontal, '--blueprint', SKILL/'reference/blueprint.json', '--meta', meta, '--out', output)
        result = self.run_cli('build_config.py', *args)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads((output/'cover_template_item_config_7.json').read_text())
        self.assertEqual([x['SI_11'] for x in value['stickersH']], [1, 2])
        self.assertEqual([x['SI_1'] for x in value['stickers']], [x['SI_1'] for x in value['stickersH']])
        self.assertNotIn('_source_id', json.dumps(value))
        report = json.loads((output/'conversion_report.json').read_text())
        self.assertEqual([x['horizontal_source'] for x in report['orientation_pairs']['stickers']], ['small', 'large'])
        self.assertNotEqual(self.run_cli('build_config.py', *args).returncode, 0)

    def test_svg_background_is_not_removed_and_external_references_fail(self):
        import rasterize_svg_assets as raster
        valid = self.root/'sticker.svg'
        value = '<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"><rect width="2" height="2" fill="#ff0000"/></svg>'
        valid.write_text(value)
        raster.check_svg(valid)
        self.assertEqual(valid.read_text(), value)
        for extra in ['<image href="file:///private/data.png"/>', '<style>@import "https://example.invalid/a.css";</style>', '<path fill="url(https://example.invalid/a)"/>', '<path style="fill:u&#x72;l(https://example.invalid/a)"/>', '<path style="fill:u&#92;72l(https://example.invalid/a)"/>']:
            valid.write_text('<svg xmlns="http://www.w3.org/2000/svg">'+extra+'</svg>')
            with self.assertRaises(ValueError):
                raster.check_svg(valid)

    @unittest.skipUnless(shutil.which('rsvg-convert'), '缺少现有 rsvg-convert，不安装')
    def test_real_rsvg_conversion_of_local_fixture(self):
        source = self.root/'svg'; source.mkdir()
        (source/'template7_sticker1.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"><rect width="2" height="2" fill="#ff0000"/></svg>')
        output = self.root/'png'
        result = self.run_cli('rasterize_svg_assets.py', '--input', source, '--out', output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((output/'template7_sticker1.png').read_bytes().startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertNotEqual(self.run_cli('rasterize_svg_assets.py', '--input', source, '--out', output).returncode, 0)


if __name__ == '__main__':
    unittest.main()
