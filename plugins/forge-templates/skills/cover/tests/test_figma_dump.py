import json
from pathlib import Path
import shutil
import subprocess
import unittest


SKILL = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), '缺少现有 Node，不安装')
class FigmaDump(unittest.TestCase):
    def run_dump(self, mixed=False):
        script = r'''
const fs = require('fs');
const code = fs.readFileSync(process.argv[1], 'utf8');
const bounds = {x: 0, y: 0, width: 100, height: 100};
const text = {type: 'TEXT', id: 'text', name: 'title', visible: true,
  absoluteBoundingBox: bounds, characters: 'sample', fontName: {family: 'Test', style: 'Regular'},
  fontSize: 20, textAlignHorizontal: 'LEFT', fills: [{type: 'SOLID', color: {r: 1, g: 0, b: 0}}]};
if (process.argv[2] === 'mixed') text.fontName = Symbol('mixed');
const vector = {type: 'VECTOR', id: 'vector', name: 'decoration', absoluteBoundingBox: bounds};
const nested = {type: 'GROUP', id: 'nested', name: 'nested', absoluteBoundingBox: bounds, children: [text]};
const group = {type: 'GROUP', id: 'group', name: 'mixed group', absoluteBoundingBox: bounds, children: [nested, vector]};
const frame = {type: 'FRAME', id: 'frame', name: 'frame', absoluteBoundingBox: {x: 0, y: 0, width: 600, height: 800}, children: [group]};
const before = JSON.stringify(frame);
const figma = {getNodeByIdAsync: async () => frame};
(async () => {
  const fn = Object.getPrototypeOf(async function(){}).constructor('figma', code);
  const result = await fn(figma);
  if (before !== JSON.stringify(frame)) throw new Error('Read-only script mutated input');
  console.log(result);
})().catch(error => { console.error(error.message); process.exitCode = 1; });
'''
        return subprocess.run([shutil.which('node'), '-e', script, str(SKILL/'scripts/figma_dump.js'), 'mixed' if mixed else 'normal'], capture_output=True, text=True, timeout=10)

    def test_nested_text_is_not_flattened_into_sticker(self):
        result = self.run_dump()
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual([(x['kind'], x['id']) for x in value['elements']], [('text', 'text'), ('image', 'vector')])

    def test_mixed_font_fails_without_partial_json(self):
        result = self.run_dump(mixed=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('混合文字样式', result.stderr)
        self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
