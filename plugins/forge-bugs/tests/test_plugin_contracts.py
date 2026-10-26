import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLARIFY = ROOT / 'skills/clarify/scripts/bug_clarification.py'


class PluginContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.env = dict(os.environ, HOME=str(self.home), PYTHONDONTWRITEBYTECODE='1')

    def cli(self, *args):
        result = subprocess.run([sys.executable, '-B', '-I', str(CLARIFY), *args],
                                env=self.env, cwd=self.home, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_two_entries_and_shared_source_paths(self):
        manifest = json.loads((ROOT / '.claude-plugin/plugin.json').read_text())
        self.assertEqual(manifest['name'], 'forge-bugs')
        for name in ('clarify', 'mantis'):
            text = (ROOT / 'skills' / name / 'SKILL.md').read_text()
            self.assertIn(f'\nname: {name}\n', text)
            self.assertNotIn('~/.claude/skills/', text)
            self.assertNotIn('/Users/', text)

    def test_prepare_reads_existing_state_without_writing(self):
        state = self.home / '.claude/bug-context'
        (state / 'presets').mkdir(parents=True)
        context = state / 'context.json'
        context.write_text(json.dumps({'projects': {'Sample': {'features': {'编辑': {'background': ['已有规则'], 'terms': {}}}}}, 'common_terms': {}}))
        preset = state / 'presets/Sample.json'
        preset.write_text(json.dumps({'objects': ['clip']}))
        before = {str(path): path.read_bytes() for path in state.rglob('*.json')}
        result = self.cli('prepare', '--text', '#123A_2 编辑：前面的clip显示错误', '--project', 'Sample')
        self.assertEqual(result['bug_id'], '#123A_2')
        self.assertEqual(result['context']['background'], ['已有规则'])
        self.assertEqual(result['presets']['path'], str(preset))
        self.assertEqual({str(path): path.read_bytes() for path in state.rglob('*.json')}, before)

    def test_context_and_presets_stay_in_user_state(self):
        saved = self.cli('context-set', '--project', 'Sample', '--feature', '编辑', '--background', '规则')
        self.assertEqual(Path(saved['context_file']), self.home / '.claude/bug-context/context.json')
        first = self.cli('presets-set', '--project', 'Sample', '--objects', 'clip')
        second = self.cli('presets-set', '--project', 'Sample', '--objects', '字幕')
        self.assertEqual(first['presets_file'], second['presets_file'])
        self.assertEqual(self.cli('presets-get', '--project', 'Sample')['objects'], ['clip', '字幕'])
        self.assertEqual(self.cli('context-get', '--project', 'Sample', '--feature', '编辑')['background'], ['规则'])

    def test_validate_public_cli(self):
        bug = self.home / 'bug.md'
        bug.write_text('#123A_2 标题\n' + '\n'.join(f'## {name}\n内容' for name in ('背景', '前置状态', '复现步骤', '预期结果', '实际结果')))
        self.assertTrue(self.cli('validate', '--file', str(bug), '--bug-id', '#123A_2')['valid'])

    def test_json_evals_and_static_handoff_contract(self):
        text = (ROOT / 'skills/clarify/SKILL.md').read_text()
        for phrase in ('AskUserQuestion', '开始解 Bug（推荐）', '补充内容', '同一轮开始调查和修复', '只改写描述'):
            self.assertIn(phrase, text)
        evals = json.loads((ROOT / 'skills/clarify/evals/evals.json').read_text())
        self.assertEqual(evals['skill_name'], 'forge-bugs:clarify')
        self.assertEqual(len(evals['evals']), 4)

    def test_text_files_keep_lf(self):
        for path in ROOT.rglob('*'):
            if path.is_file() and path.suffix in {'.md', '.json', '.py', '.sh'}:
                self.assertNotIn(b'\r\n', path.read_bytes(), str(path))


if __name__ == '__main__':
    unittest.main()
