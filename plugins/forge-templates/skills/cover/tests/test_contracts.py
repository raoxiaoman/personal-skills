import ast
import json
from pathlib import Path
import re
import unittest


SKILL = Path(__file__).resolve().parents[1]
ROOT = SKILL.parents[1]


class PluginContracts(unittest.TestCase):
    def test_manifest_and_single_entry(self):
        self.assertEqual(json.loads((ROOT/'.claude-plugin/plugin.json').read_text())['name'], 'forge-templates')
        self.assertEqual([p.parent.name for p in (ROOT/'skills').glob('*/SKILL.md')], ['cover'])
        self.assertIn('\nname: cover\n', (SKILL/'SKILL.md').read_text())

    def test_references_and_source_are_portable(self):
        for path in [SKILL/'SKILL.md', *sorted((SKILL/'references').glob('*.md'))]:
            value = path.read_text()
            self.assertNotIn('/Users/raohui', value)
            for target in re.findall(r'\]\(([^)]+)\)', value):
                if '://' not in target:
                    resolved = (path.parent/target.split('#')[0]).resolve()
                    self.assertTrue(resolved.is_relative_to(ROOT))
                    self.assertTrue(resolved.is_file(), str(resolved))
        for path in (SKILL/'scripts').glob('*.py'):
            ast.parse(path.read_text(), filename=str(path))
        self.assertFalse((SKILL/'tmp').exists())
        self.assertFalse((ROOT/'hooks').exists())
        self.assertFalse((ROOT/'.mcp.json').exists())


if __name__ == '__main__':
    unittest.main()
