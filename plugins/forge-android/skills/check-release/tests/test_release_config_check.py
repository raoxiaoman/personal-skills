import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import release_config_check as c


class ConfigChecks(unittest.TestCase):
    def test_strict_json(self):
        for text in ('{"a":1,"a":2}', '{"a":NaN}'):
            with self.assertRaises(ValueError):
                c.parse(text)

    def test_versions_and_content(self):
        first = '{"version":1,"data":[1,2]}'
        same = '{"data":[1,2],"version":1}'
        result = c.compare(first, same, 'x', True, {'x':1}, {'x':1})
        self.assertEqual(result['status'], '通过')
        self.assertEqual(c.compare(first, same, 'x', True, {'x':4}, {'x':1})['status'], '待确认')
        self.assertEqual(c.compare(first, '{"version":1,"data":[2,1]}', 'x', True, {'x':1}, {'x':1})['category'], '同版本内容漂移')
        self.assertNotEqual(c.canonical(True), c.canonical(1))

    def test_nested_and_missing(self):
        self.assertEqual(c.body_version({'cover':[{'version':21}]}, 'cover'), 21)
        self.assertEqual(c.number('14'), 14)
        self.assertEqual(c.body_version({'version':'1'}, 'x', True), 1)
        for invalid in ('1.0', '-1', 'unknown'):
            with self.assertRaises(ValueError):
                c.number(invalid)
        with self.assertRaises(ValueError):
            c.number(True)
        result = c.compare('{"version":1}', '{"version":1}', 'updateMenu', False, {}, {})
        self.assertIn('本地索引缺项', result['index_issues'])

    def test_mapping_and_failure(self):
        self.assertEqual(len(c.load_project('videoguru')['configs']['raw']), 8)
        self.assertEqual(len(c.load_project('videoguru')['configs']['assets']), 4)
        def failure(path):
            raise ValueError('offline fixture')
        result, snapshots = c.check(lambda path: '{}', failure)
        self.assertEqual(result['status'], '待确认')
        self.assertEqual(len(result['details']), 12)
        self.assertFalse(snapshots)

    def test_youcut_root_versions_are_project_scoped(self):
        p = c.load_project('youcut')
        keys = p['configs']['root_version_keys']
        for key in keys:
            text = '{"version":7,"data":[]}'
            result = c.compare(text, text, key, False, {key:7}, {key:7}, keys)
            self.assertEqual(result['status'], '通过')
            with self.assertRaises(KeyError):
                c.body_version(c.parse(text), key)
        self.assertTrue(c.valid_url('https://inshot.cc/YouCut/template_match_config.json', p))
        self.assertFalse(c.valid_url('https://inshot.cc/VideoGuru/template_match_config.json', p))
        self.assertEqual(len(p['configs']['raw']), 15)
        self.assertEqual(len(p['configs']['assets']), 3)

    def test_url_boundary(self):
        self.assertTrue(c.valid_url('https://inshot.cc/VideoGuru/VersionInfo.json'))
        self.assertFalse(c.valid_url('https://example.com/VideoGuru/x.json'))
        self.assertFalse(c.valid_url('http://inshot.cc/VideoGuru/x.json'))


if __name__ == '__main__':
    unittest.main()
