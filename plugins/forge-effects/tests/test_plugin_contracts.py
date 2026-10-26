import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PluginContractsTest(unittest.TestCase):
    def test_manifest_and_entries(self):
        manifest = json.loads((ROOT / '.claude-plugin/plugin.json').read_text())
        self.assertEqual('forge-effects', manifest['name'])
        self.assertEqual('0.1.0', manifest['version'])
        self.assertEqual({'develop', 'shader', 'review'}, {p.name for p in (ROOT / 'skills').iterdir()})
        for name in ('develop', 'shader', 'review'):
            text = (ROOT / 'skills' / name / 'SKILL.md').read_text()
            self.assertTrue(text.startswith(f'---\nname: {name}\n'))
            self.assertIn('\ndescription: ', text)

    def test_all_relative_links_stay_inside_plugin_and_exist(self):
        linked = set()
        for path in ROOT.rglob('*.md'):
            for target in re.findall(r'\]\(([^)]+)\)', path.read_text()):
                resolved = (path.parent / target).resolve()
                self.assertTrue(resolved.is_relative_to(ROOT), (path, target))
                self.assertTrue(resolved.is_file(), (path, target))
                linked.add(resolved)
        self.assertTrue(set((ROOT / 'references').glob('*.md')).issubset(linked))

    def test_three_shared_references(self):
        expected = {'render-contract.md', 'keyframes.md', 'gpuimage-integration.md'}
        self.assertEqual(expected, {p.name for p in (ROOT / 'references').iterdir()})
        for name in ('develop', 'shader', 'review'):
            self.assertIn('../../references/render-contract.md', (ROOT / 'skills' / name / 'SKILL.md').read_text())

    def test_portable_text_without_old_release_commands(self):
        forbidden = ('/Users/', 'aws s3 ', 'gsutil ', 'cloudfront create-invalidation',
                     'echo -e ', 'upload.py', 'GPUEffectXXXFilter', 'time % (totalSeconds * 30)')
        for path in list((ROOT / 'skills').rglob('*.md')) + list((ROOT / 'references').glob('*.md')):
            data = path.read_bytes()
            self.assertNotIn(b'\r', data, str(path))
            self.assertTrue(data.endswith(b'\n'))
            for term in forbidden:
                self.assertNotIn(term, data.decode(), (path, term))

    def test_read_only_review_and_lightweight_parameters_are_explicit(self):
        develop = (ROOT / 'skills/develop/SKILL.md').read_text()
        review = (ROOT / 'skills/review/SKILL.md').read_text()
        self.assertIn('不创建完整滤镜', develop)
        self.assertIn('只有明确授权才修复', review)
        self.assertIn('合法', review)
        self.assertIn('不一律裁剪', review)


if __name__ == '__main__':
    unittest.main()
