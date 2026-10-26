import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import importlib.util
sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import release_purchase_check as p
spec = importlib.util.spec_from_file_location('release_entry', Path(__file__).parents[1] / 'scripts/release-check.py')
c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
PATH = 'Guru/src/international/java/Buy.kt'
POLICY = 'Guru/src/international/java/Policy.kt'
REG = json.dumps([dict(id='test', labels=['A', 'B'], constants={'NEW': 'A'}, policy=POLICY, entries=[PATH], tests=[])])

class PurchaseChecks(unittest.TestCase):
    def check(self, text, reg=REG, old=None):
        return p.check(old or {}, {PATH:text, POLICY:'const val NEW="A"; val old="B"', p.load_project('videoguru')['purchase']['user']:'replace("_", "") substring(0, 16)'}, reg, c.lexical)

    def test_balanced_arguments_and_comments(self):
        rows=p.calls('// getObfuscatedProfileId(null)\nlaunchBillingFlow(\n accountId = user(), profileId = getObfuscatedProfileId(label)\n)', c.lexical)
        self.assertEqual(len(rows),2)
        self.assertEqual(len(rows[0]['args']),2)

    def test_default_is_not_missing_but_explicit_empty_is_error(self):
        self.assertEqual(self.check('getObfuscatedProfileId()')['status'],'待确认')
        self.assertEqual(self.check('getObfuscatedProfileId("")')['status'],'异常')
        self.assertEqual(self.check('launchBillingFlow(accountId=null, profileId=id)')['status'],'异常')

    def test_contract_mismatch_and_collision(self):
        row=json.loads(REG)[0];row['constants']['NEW']='other'
        self.assertEqual(self.check('',json.dumps([row]))['status'],'异常')
        row=json.loads(REG)[0];row['labels']=['ab_cd','abcd']
        self.assertEqual(self.check('',json.dumps([row]))['status'],'异常')
        row['labels']=['x'*16+'a','x'*16+'b']
        self.assertEqual(self.check('',json.dumps([row]))['status'],'异常')

    def test_deletion_and_unregistered_calls_reported(self):
        result=self.check('',old={PATH:'launchBillingFlow(id)'})
        self.assertEqual(result['changes'][0]['kind'],'删除或替换')
        result=p.check({}, {'Guru/src/main/New.kt':'launchBillingFlow(id)'},REG,c.lexical)
        self.assertTrue(any('未登记' in e for e in result['evidence']))

    def test_registry_rejects_commands(self):
        row=json.loads(REG)[0];row['tests']=['--run anything']
        with self.assertRaises(ValueError):p.registry(json.dumps([row]))

    def test_all_skipped_is_not_pass(self):
        import re
        from types import SimpleNamespace
        def run(cmd, **kw):
            if '--dry-run' not in cmd:
                init=Path(cmd[cmd.index('--init-script')+1]).read_text()
                directory=Path(json.loads(re.search(r'file\(("[^"]+")\)',init)[1]));directory.mkdir()
                (directory/'TEST-a.Test.xml').write_text('<testsuite name="a.Test" tests="1" skipped="1" failures="0"/>')
            return SimpleNamespace(returncode=0,stdout=':Guru:testGooglePlayDebugUnitTest SKIPPED\n',stderr='')
        with patch.object(p.contract_tests.subprocess,'run',side_effect=run):
            self.assertEqual(p.contract_tests.run_tests('.', ['a.Test'],1,'购买契约测试')[0]['status'],'未执行')

    def test_cli_disallows_commit_mode_test_execution(self):
        import subprocess
        result=subprocess.run([sys.executable,'-I','-B',str(Path(__file__).parents[1]/'scripts/release-check.py'),'--project','videoguru','--base','missing','--check-purchase-labels','--run-purchase-tests'],capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertIn('--worktree',result.stderr)

    def test_same_signature_move_is_reported_for_review(self):
        old={PATH:'getObfuscatedProfileId(label)'}
        new={POLICY:'const val NEW="A"; val old="B"; getObfuscatedProfileId(label)'}
        result=p.check(old,new,REG,c.lexical)
        self.assertEqual({x['kind'] for x in result['changes']},{'新增或修改','删除或替换'})
        self.assertEqual(result['status'],'待确认')

    def test_unbalanced_or_dynamic_args_are_not_pass(self):
        self.assertEqual(self.check('launchBillingFlow(profileId = policy.label())')['status'],'待确认')
        result=self.check('launchBillingFlow(profileId = ')
        self.assertTrue(any('无法解析' in e for e in result['evidence']))

    def test_label_string_whitespace_change_is_not_hidden(self):
        old = {PATH: 'getObfuscatedProfileId("a b")'}
        result = self.check('getObfuscatedProfileId("ab")', old=old)
        self.assertEqual(len(result['changes']), 2)

    def test_formatting_only_does_not_create_label_change(self):
        old = {PATH: 'getObfuscatedProfileId( "a b" )'}
        result = self.check('getObfuscatedProfileId(\n "a b"\n)', old=old)
        self.assertEqual(result['changes'], [])

    def test_raw_string_label_whitespace_is_preserved(self):
        before = p.calls('getObfuscatedProfileId("""a b""")', c.lexical)
        after = p.calls('getObfuscatedProfileId("""ab""")', c.lexical)
        self.assertNotEqual(before[0]['signature'], after[0]['signature'])
