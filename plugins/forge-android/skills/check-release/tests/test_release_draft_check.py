import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import release_draft_check as d
spec = importlib.util.spec_from_file_location('release_entry', Path(__file__).parents[1] / 'scripts/release-check.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

REG = json.dumps([dict(models=['Nested'], tests=['a.b.Test'], evidence=['Gson.java'])])
P = 'VideoEngine/src/main/java/Model.java'


class DraftChecks(unittest.TestCase):
    def check(self, a, b, reg=REG):
        return d.check(a, b, reg, c.lexical)

    def test_inherited_fields_not_locals_and_modifiers(self):
        old = {P: 'class Model implements ClipInfo { int x=0; void a(){int local=1;} }'}
        new = {P: 'class Model implements ClipInfo { int x=1; transient int tmp; static int s; final int f=1; void a(){int local=2;} }'}
        result = self.check(old, new)
        self.assertEqual([x['field'] for x in result['changes']], ['x'])
        self.assertEqual(result['status'], '待确认')
        self.assertFalse(result['changes'][0]['tests'])

    def test_json_name_alternate_type_deletion_and_nested(self):
        old = {P: 'class Nested { @SerializedName(value="old", alternate={"older"}) int x=1; int gone; }'}
        new = {P: 'class Nested { @SerializedName("new") long x=1; }'}
        result = self.check(old, new)
        self.assertEqual({x['field'] for x in result['changes']}, {'x', 'gone'})
        self.assertEqual(result['selectors'], ['a.b.Test'])

    def test_comments_crlf_and_methods_do_not_change_contract(self):
        old = {P: 'class Model implements ClipInfo { int x=0; }\r\n'}
        new = {P: 'class Model implements ClipInfo { int x=0; /* int fake=2; */ void a(){int local=2;} }\n'}
        self.assertEqual(self.check(old, new)['status'], '不涉及')

    def test_indirect_parent_and_multi_class_conservative(self):
        old = {P: 'class Parent extends BaseClipInfo { }', 'Guru/src/main/java/Child.java': 'class Child extends Parent { }'}
        new = {**old, 'Guru/src/main/java/Child.java': 'class Child extends Parent { int added; }'}
        self.assertEqual(self.check(old, new)['changes'][0]['field'], 'added')
        new[P] += ' class Other {}'
        self.assertEqual(self.check(old, new)['status'], '待确认')

    def test_kotlin_is_not_silently_passed(self):
        p = 'VideoEngine/src/main/java/Model.kt'
        self.assertEqual(self.check({}, {p: 'class Model : ClipInfo { val x = 1 }'})['status'], '待确认')

    def test_youcut_models_without_maker_inheritance_are_registered(self):
        project = d.load_project('youcut')
        registration = (Path(__file__).parents[1] / 'projects/youcut/release-draft-tests.json').read_text()
        path = 'VideoEngine/src/main/java/MediaClipInfo.java'
        result = d.check({path:'class MediaClipInfo { }'}, {path:'class MediaClipInfo { int added; }'}, registration, c.lexical, project)
        self.assertEqual(result['status'], '待确认')
        self.assertEqual(result['changes'][0]['model'], 'MediaClipInfo')
        self.assertEqual(result['selectors'], [])
        self.assertTrue(all('YouCut/' in e for e in result['changes'][0]['evidence']))

    def test_registry_command_rejected(self):
        with self.assertRaises(ValueError):
            d.registry(json.dumps([dict(models=['Nested'], tests=['--exec foo'], evidence=[])]))

    def test_test_runner_requires_fresh_nonzero_xml(self):
        def run(command, **kwargs):
            if '--dry-run' not in command:
                init = Path(command[command.index('--init-script') + 1]).read_text()
                import re
                output = Path(json.loads(re.search(r'file\(("[^"]+")\)', init)[1]))
                output.mkdir()
                (output / 'TEST-a.b.Test.xml').write_text('<testsuite name="a.b.Test" tests="3" failures="0" errors="0"/>')
            return SimpleNamespace(returncode=0, stdout=':Guru:testGooglePlayDebugUnitTest SKIPPED\nBUILD SUCCESSFUL', stderr='')
        with patch.object(d.contract_tests.subprocess, 'run', side_effect=run) as mocked:
            result, _ = d.run_tests('.', ['a.b.Test'], 1)
        self.assertEqual(result['status'], '通过')
        self.assertIn('--offline', mocked.call_args.args[0])
        self.assertIn(':Guru:uploadServerAuthTask', mocked.call_args.args[0])
        with patch.object(d.contract_tests.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='', stderr='')):
            self.assertEqual(d.run_tests('.', ['a.b.Test'], 1)[0]['status'], '未执行')

    def test_task_graph_failure_and_timeout(self):
        with patch.object(d.contract_tests.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=':Guru:uploadServerAuthTask SKIPPED', stderr='')) as mocked:
            self.assertEqual(d.run_tests('.', ['a.b.Test'], 1)[0]['status'], '未执行')
            self.assertEqual(mocked.call_count, 1)
        with patch.object(d.contract_tests.subprocess, 'run', side_effect=d.contract_tests.subprocess.TimeoutExpired('gradle', 1)):
            self.assertEqual(d.run_tests('.', ['a.b.Test'], 1)[0]['status'], '未执行')
        with patch.object(d.contract_tests.subprocess, 'run') as mocked:
            self.assertEqual(d.run_tests('.', [], 1)[0]['status'], '未执行')
            mocked.assert_not_called()

    def test_worktree_digest_includes_cross_module_tests_and_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [P, 'Guru/src/test/java/Test.kt']
            for path in paths:
                p = root / path
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text('x')
            import release_common
            with patch.object(release_common, 'git', return_value='\n'.join(paths)):
                self.assertEqual(set(c.worktree_inputs(root)), set(paths))

    def test_failed_or_zero_test_suite_cannot_pass(self):
        def execute(command, **kwargs):
            if '--dry-run' not in command:
                import re
                content = Path(command[command.index('--init-script') + 1]).read_text()
                path = Path(json.loads(re.search(r'file\(("[^"]+")\)', content)[1]))
                path.mkdir()
                (path / 'TEST-a.b.Test.xml').write_text('<testsuite name="a.b.Test" tests="1" failures="1" errors="0"/>')
            return SimpleNamespace(returncode=0, stdout=':Guru:testGooglePlayDebugUnitTest SKIPPED\n', stderr='')
        with patch.object(d.contract_tests.subprocess, 'run', side_effect=execute):
            self.assertEqual(d.run_tests('.', ['a.b.Test'], 1)[0]['status'], '异常')

    def test_json_alternate_does_not_hide_field(self):
        result = self.check({}, {P: 'class Nested { @SerializedName(value="x", alternate={"old"}) int field=1; }'})
        self.assertEqual(result['changes'][0]['field'], 'field')
        self.assertIn('old', result['changes'][0]['after']['json_name'][0])

    def test_cli_rejects_execution_without_worktree_before_gradle(self):
        import subprocess
        entry = Path(__file__).parents[1] / 'scripts/release-check.py'
        result = subprocess.run([sys.executable, "-I", "-B", str(entry), '--project', 'videoguru', '--base', 'missing', '--check-drafts', '--run-draft-tests'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('--worktree', result.stderr)

    def test_commit_and_worktree_registry_are_separate(self):
        import subprocess
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            subprocess.run(['git', '-C', str(root), 'config', 'user.email', 'test@example.invalid'], check=True)
            subprocess.run(['git', '-C', str(root), 'config', 'user.name', 'Test'], check=True)
            for path, content in [('build.gradle', "versionCode=1\nversionName='old'"), (P, 'class Model implements ClipInfo { int x; }'), ('unused-fixture-registry.json', REG)]:
                p = root / path
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content)
            subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(root), 'commit', '-qm', 'baseline'], check=True)
            subprocess.run(['git', '-C', str(root), 'tag', 'base'], check=True)
            (root / P).write_text('class Model implements ClipInfo { int x; int added; }')
            commit = c.run(root, 'base', 'HEAD', drafts=True)
            work = c.run(root, 'base', 'HEAD', worktree=True, drafts=True)
            self.assertEqual(commit['checks'][5]['status'], '不涉及')
            self.assertEqual(work['checks'][5]['changes'][0]['field'], 'added')
            self.assertTrue(work['stable'])

    def test_string_default_spaces_are_semantic(self):
        old = {P: 'class Model implements ClipInfo { String label="a b"; }'}
        new = {P: 'class Model implements ClipInfo { String label="ab"; }'}
        self.assertEqual(self.check(old, new)['status'], '待确认')

    def test_extends_and_implements_both_preserved(self):
        result = self.check({}, {P: 'class Model extends BaseClipInfo implements Cloneable { int added; }'})
        self.assertEqual([row['field'] for row in result['changes']], ['added'])

    def test_kotlin_constructor_parent_requires_review(self):
        path = 'VideoEngine/src/main/java/Model.kt'
        old = {path: 'class Model : BaseClipInfo() { val x = 1 }'}
        new = {path: 'class Model : BaseClipInfo() { val x = 2 }'}
        self.assertEqual(self.check(old, new)['status'], '待确认')

    def test_character_brace_does_not_hide_following_field(self):
        old={P: "class Model implements ClipInfo { char marker='}'; int value=1; }"}
        new={P: "class Model implements ClipInfo { char marker='}'; int value=2; }"}
        self.assertEqual(self.check(old,new)['status'],'待确认')

    def test_multiple_declarators_with_calls_are_not_silently_ignored(self):
        old={P:'class Model implements ClipInfo { Foo a = make(), b = make(); }'}
        new={P:'class Model implements ClipInfo { Foo a = make(), b = changed(); }'}
        self.assertEqual(self.check(old,new)['status'],'待确认')

    def test_qualified_annotation_does_not_hide_field(self):
        old={P:'class Model implements ClipInfo { @com.google.gson.annotations.SerializedName("x") int value=1; }'}
        new={P:'class Model implements ClipInfo { @com.google.gson.annotations.SerializedName("y") int value=1; }'}
        self.assertEqual(self.check(old,new)['status'],'待确认')

    def test_character_parentheses_and_semicolon_preserve_scan(self):
        for character in ('(', ')', '{', '}', ';'):
            old={P: f"class Model implements ClipInfo {{ char marker='{character}'; int value=1; }}"}
            new={P: f"class Model implements ClipInfo {{ char marker='{character}'; int value=2; }}"}
            with self.subTest(character=character):
                self.assertIn('value', [row['field'] for row in self.check(old,new)['changes']])

    def test_qualified_json_key_change_is_reported_precisely(self):
        old={P:'class Model implements ClipInfo { @com.google.gson.annotations.SerializedName("x") int value=1; }'}
        new={P:'class Model implements ClipInfo { @com.google.gson.annotations.SerializedName("y") int value=1; }'}
        row=self.check(old,new)['changes'][0]
        self.assertEqual(row['field'],'value')
        self.assertEqual(row['before']['json_name'],['"x"'])
        self.assertEqual(row['after']['json_name'],['"y"'])
