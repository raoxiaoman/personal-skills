"""离线双项目fixture及权限/来源边界，不调用真实Gradle/网络/设备。"""
import copy
import gzip
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

S = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(S/'scripts'))
import release_common as common
import release_config_check as config
import release_apk_check as apk
import release_contract_tests as contracts
spec = importlib.util.spec_from_file_location('safety_entry', S/'scripts/release-check.py')
c = importlib.util.module_from_spec(spec);spec.loader.exec_module(c)


def git(root, *args):
    return subprocess.run(['git','-C',str(root),*args],capture_output=True,text=True,check=True).stdout.strip()


def fixture(root, project):
    p=common.load_project(project)
    git(root,'init','-q');git(root,'config','user.email','fixture@example.invalid');git(root,'config','user.name','Fixture')
    values={p['identity']['settings']:f"include ':{p['module']}'",p['identity']['module_build']:f"applicationId \"{p['identity']['application_id']}\"\nversionCode rootProject.ext.versionCode\nversionName rootProject.ext.versionName\napply from: '../gradle/serverauth.gradle'\npreBuild.dependsOn uploadServerAuthTask",p['version_path']:"versionCode=1\nversionName='one'",p['auth_path']:'task uploadServerAuthTask {}',p['module']+'/src/main/java/X.kt':'class X {}'}
    for name,text in values.items():
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
    git(root,'add','.');git(root,'commit','-qm','baseline');git(root,'tag','published')
    return p


class Safety(unittest.TestCase):
    def test_dual_project_fingerprints_and_no_fallback(self):
        for project,other in [('videoguru','youcut'),('youcut','videoguru')]:
            with self.subTest(project=project),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);p=fixture(root,project);common.verify_identity(root,p)
                with self.assertRaises((ValueError,FileNotFoundError)):common.verify_identity(root,common.load_project(other))
                report=c.finalize(c.run(root,'published',worktree=True,project=p,drafts=True,purchase=True,enforce_identity=True),p)
                self.assertEqual(len(report['checklist']),15)
                self.assertFalse(report['release_approved'])
                if project=='youcut':
                    self.assertEqual(next(x for x in report['checks'] if x['name']=='购买 label 契约')['status'],'异常')
                    self.assertEqual(next(x for x in report['checks'] if x['name']=='DI 测试环境')['status'],'待确认')
                    self.assertNotEqual(next(x for x in report['checks'] if x['name']=='草稿属性兼容')['status'],'通过')
                    self.assertNotIn('retainA',json.dumps(report));self.assertNotIn('/VideoGuru/',json.dumps(p))

    def test_config_paths_tasks_domains_and_labels_do_not_cross(self):
        a=common.load_project('videoguru');b=common.load_project('youcut')
        self.assertEqual(b['gradle']['dependency_task'],':YouCut:dependencies')
        self.assertNotIn('Guru/',json.dumps(b))
        self.assertTrue(all('Guru/' in row[1] for row in a['configs']['raw']))
        self.assertEqual(json.loads(common.registry_text(b,'purchase'))[0]['labels'],['UserA','UserB'])
        self.assertFalse(json.loads(common.registry_text(b,'purchase'))[0]['tests'])
        self.assertFalse(config.valid_url('https://inshot.cc/VideoGuru/VersionInfo.json',b))

    def test_schema_missing_and_project_escape_fail_closed(self):
        for bad in ('../videoguru','unknown','/tmp/x'):
            with self.assertRaises((ValueError,FileNotFoundError)):common.load_project(bad)
        with patch.object(common.json,'loads',return_value={'schema_version':2,'id':'videoguru'}):
            with self.assertRaises(ValueError):common.load_project('videoguru')
        with patch.object(common.json,'loads',return_value={'schema_version':1,'id':'videoguru'}):
            with self.assertRaises(ValueError):common.load_project('videoguru')

    def test_relative_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'out').symlink_to('/tmp')
            for name in ('../bad','/tmp/bad','out/file','x\\bad'):
                with self.assertRaises(ValueError):common.inside(root,name)

    def test_config_registry_escape_rejected(self):
        p=common.load_project('videoguru');p['configs']['raw'][0][1]='../leak'
        with patch.object(common.json,'loads',side_effect=[p,[],[]]):
            with self.assertRaises(ValueError):common.load_project('videoguru')

    def test_arbitrary_gradle_task_rejected(self):
        p=common.load_project('youcut');p['gradle']['test_task']=':YouCut:publish'
        with patch.object(common.json,'loads',side_effect=[p,[],[]]):
            with self.assertRaises(ValueError):common.load_project('youcut')

    def test_base_equal_head_does_not_use_dirty_baseline(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=fixture(root,'youcut');(root/'build.gradle').write_text("versionCode=2\nversionName='two'")
            report=c.run(root,'published',worktree=True,project=p,enforce_identity=True)
            self.assertIn('one / 1',report['checks'][0]['evidence'][0]);self.assertIn('two / 2',report['checks'][0]['evidence'][0]);self.assertNotEqual(report['base_digest'],report['input_digest'])

    def test_commit_mode_does_not_mix_worktree(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=fixture(root,'youcut');(root/'build.gradle').write_text("versionCode=99\nversionName='dirty'")
            report=c.run(root,'published',project=p)
            self.assertNotIn('dirty',report['checks'][0]['evidence'][0])

    def test_source_and_contract_changes_expire_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=fixture(root,'youcut')
            actual=c.worktree_inputs(root)
            changed=dict(actual);changed['YouCut/src/test/Test.kt']=b'new'
            with patch.object(c,'worktree_inputs',side_effect=[actual,changed]):
                self.assertFalse(c.run(root,'published',worktree=True,project=p)['stable'])
            with patch.object(c,'tool_digest',side_effect=['before','after']):
                self.assertFalse(c.run(root,'published',project=p)['stable'])

    def test_tests_in_all_modules_are_hashed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);fixture(root,'youcut')
            before=common.digest(common.worktree_inputs(root))
            path=root/'VideoEngine/src/test/java/Test.kt';path.parent.mkdir(parents=True);path.write_text('test')
            self.assertNotEqual(before,common.digest(common.worktree_inputs(root)))

    def test_static_defaults_do_not_execute_external_stages(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=fixture(root,'youcut')
            with patch.object(c,'resolve_dependencies') as gradle,patch.object(config,'fetch') as network,patch.object(contracts,'run_tests') as test:
                c.run(root,'published',worktree=True,project=p,drafts=True,purchase=True)
                gradle.assert_not_called();network.assert_not_called();test.assert_not_called()

    def test_historical_target_cannot_execute_gradle(self):
        with self.assertRaisesRegex(ValueError,'worktree'):c.run('.','missing',resolve=True,project=common.load_project('youcut'))

    def test_task_graph_blocks_upload_and_install(self):
        p=common.load_project('youcut')
        for task in (':YouCut:uploadServerAuthTask',':Other:publish',':YouCut:installDebug',':Other:copyReleaseBaselineProfileIntoSrc'):
            with self.assertRaises(ValueError):common.graph_safe(task+' SKIPPED\n',p)
        with self.assertRaises(ValueError):common.graph_safe(':Other:wrong SKIPPED\n',p,p['gradle']['test_task'])

    def test_output_conflict_and_repo_write_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for path in (root,root/'report',S/'tmp/new-report',S.parent/'maestro/new-report',S.parents[1]/'new-report'):
                with self.assertRaises(ValueError):common.new_output(path,root)

    def test_missing_or_skipped_suite_cannot_pass(self):
        for xml in ('<testsuite name="a.Test" tests="0"/>','<testsuite name="a.Other" tests="2"/>','<testsuite name="a.Test" tests="2" skipped="1"/>'):
            def run(cmd,**kw):
                if '--dry-run' not in cmd:
                    import re
                    script=Path(cmd[cmd.index('--init-script')+1]).read_text();out=Path(json.loads(re.search(r'file\(("[^"]+")\)',script)[1]));out.mkdir()
                    (out/'TEST-a.xml').write_text(xml)
                return SimpleNamespace(returncode=0,stdout=':Guru:testGooglePlayDebugUnitTest SKIPPED\n',stderr='')
            with patch.object(contracts.subprocess,'run',side_effect=run):
                self.assertNotEqual(contracts.run_tests('.', ['a.Test'],1,'test')[0]['status'],'通过')

    def test_full_url_allowlist(self):
        for url in ('https://inshot.cc/VideoGuru/../private.json','https://inshot.cc/VideoGuru/unknown.json','https://inshot.cc/VideoGuru/VersionInfo.json?x=1','https://evil.invalid/VideoGuru/VersionInfo.json'):
            self.assertFalse(config.valid_url(url))

    def test_gzip_decompressed_size_limit(self):
        class Response:
            headers={'Content-Encoding':'gzip'}
            def geturl(self):return 'https://inshot.cc/VideoGuru/VersionInfo.json'
            def read(self,n):return gzip.compress(b' '*5000)
            def __enter__(self):return self
            def __exit__(self,*args):pass
        with patch.object(config,'LIMIT',100),patch.object(config.urllib.request,'build_opener',return_value=SimpleNamespace(open=lambda *a,**kw:Response())):
            with self.assertRaises(ValueError):config.fetch('VersionInfo.json')

    def test_partial_model_parser_conservative(self):
        import release_draft_check as draft
        p=common.load_project('videoguru')
        reg='[{"models":["Nested"],"tests":[],"evidence":[]}]'
        result=draft.check({}, {'Guru/src/main/java/X.java':'class Nested { int a,b; }'},reg,c.lexical,p)
        self.assertEqual(result['status'],'待确认')

    def test_external_dependency_report_not_trusted(self):
        value='googlePlayReleaseRuntimeClasspath\n+--- com.yuvcraft.data:a:1\nBUILD SUCCESSFUL'
        self.assertEqual(c.check_dependencies(value)['status'],'待确认')


    def test_recorded_exceptions_skip_get_without_becoming_pass(self):
        p=common.load_project('videoguru');requested=[]
        def fetch(path):
            requested.append(path);raise ValueError('offline fixture')
        result,_=config.check(lambda path:'{}',fetch,project=p)
        skipped={r[2] for r in p['configs']['raw']+p['configs']['assets'] if any(e.get('path')==r[1] for e in p['configs']['exceptions'])}
        self.assertTrue(skipped);self.assertFalse(skipped.intersection(requested))
        self.assertEqual(result['status'],'待确认')
        self.assertEqual(len([r for r in result['details'] if 'exception' in r]),5)

    def test_deferred_evidence_not_a_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=fixture(root,'videoguru')
            report=c.finalize(c.run(root,'published',project=p),p,deferred={8:'用户等待映射确认'})
            for number in (8,13):
                row=report['checklist'][number-1]
                self.assertEqual(row['status'],'未执行');self.assertEqual(row['evidence_level'],'用户暂缓')
            with self.assertRaises(ValueError):c.finalize(c.run(root,'published',project=p),p,deferred={6:'不应覆盖已执行异常'})

    def test_task_graph_must_contain_fixed_test_task(self):
        with patch.object(contracts.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='BUILD SUCCESSFUL',stderr='')) as run:
            self.assertEqual(contracts.run_tests('.', ['a.Test'],1,'test')[0]['status'],'未执行')
            self.assertEqual(run.call_count,1)

    def test_identity_comment_is_not_a_fingerprint(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=fixture(root,'youcut')
            (root/'settings.gradle').write_text("/*\ninclude ':YouCut'\n*/")
            with self.assertRaises(ValueError):common.verify_identity(root,p)

    def test_evals_keep_unauthorized_actions_out(self):
        data=json.loads((S/'evals/evals.json').read_text())
        self.assertEqual([e['id'] for e in data['evals']],[1,2,3,4,5,6,7])
        self.assertTrue(all(e['prompt'] and e['expected_output'] for e in data['evals']))


class ApkAdapter(unittest.TestCase):
    def inputs(self,temp):
        root=Path(temp).resolve();old=root/'old with spaces.apk';new=root/'new with spaces.apk';old.write_bytes(b'old');new.write_bytes(b'new');return old,new,root/'fresh output'

    def test_old_new_pair_required(self):
        with self.assertRaises(ValueError):apk.analyze(None,'new','out')

    def test_missing_skill_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            old,new,out=self.inputs(temp)
            with patch.object(apk,'SKILL',Path(temp)/'unknown-skill'):
                self.assertEqual(apk.analyze(old,new,out)['status'],'未执行')

    def test_argument_order_spaces_and_return_codes(self):
        for code in (0,1,2):
            with tempfile.TemporaryDirectory() as temp:
                old,new,out=self.inputs(temp)
                def run(cmd,**kw):
                    self.assertEqual(Path(cmd[2]), S.parent/'analyze-apk-size/scripts/apk_size_analysis.py')
                    self.assertEqual(cmd[1],'-I');self.assertEqual(cmd[3:5],[str(old),str(new)]);self.assertEqual(cmd[5:],['--output-dir',str(out)])
                    if code!=1:
                        out.mkdir();(out/'report.md').write_text('summary')
                        (out/'report.json').write_text(json.dumps({'schema_version':1,'old':{'path':str(old),'size_bytes':3},'new':{'path':str(new),'size_bytes':3},'delta_bytes':0,'delta_percent':0,'zip_overhead_delta_bytes':0,'reconciled_delta_bytes':0,'categories':[],'files':[]}))
                    return SimpleNamespace(returncode=code,stdout='',stderr='')
                with patch.object(apk.subprocess,'run',side_effect=run):result=apk.analyze(old,new,out)
                self.assertEqual(result['returncode'],code)
                if code==1:self.assertEqual(result['status'],'未执行')
                else:
                    self.assertIn('未知',result['comparability']);self.assertEqual(result['markdown'],str(out/'report.md'));self.assertIn('report_digest',result)
                    self.assertEqual(result['measurement'],'完整' if code==0 else 'ZIP可用，DEX归因不完整')
                    self.assertEqual(result['status'],'待确认')

    def test_existing_output_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            old,new,out=self.inputs(temp);out.mkdir()
            with self.assertRaises(ValueError):apk.analyze(old,new,out)

    def test_missing_reports_or_untrusted_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            old,new,out=self.inputs(temp)
            def run(*a,**kw):
                out.mkdir();(out/'report.md').write_text('old');(out/'report.json').write_text(json.dumps({'schema_version':1,'old':{'path':'/stale.apk'},'new':{'path':str(new)}}));return SimpleNamespace(returncode=0)
            with patch.object(apk.subprocess,'run',side_effect=run):self.assertEqual(apk.analyze(old,new,out)['status'],'未执行')

    def test_apk_concurrent_change_expires(self):
        with tempfile.TemporaryDirectory() as temp:
            old,new,out=self.inputs(temp)
            def run(*a,**kw):new.write_bytes(b'changed');return SimpleNamespace(returncode=0)
            with patch.object(apk.subprocess,'run',side_effect=run):self.assertEqual(apk.analyze(old,new,out)['status'],'未执行')


if __name__=='__main__':unittest.main()


class ApkContextValidation(unittest.TestCase):
    def test_invalid_context_rejected_before_subprocess(self):
        for context in ([], {'old': [], 'new': {}}, {'old': {}, 'new': {}}, {'old': None, 'new': None}):
            with self.subTest(context=context), patch.object(apk.subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    apk.analyze('old.apk', 'new.apk', 'output', context=context)
                run.assert_not_called()


class ConfigInterruptedResponses(unittest.TestCase):
    def test_truncated_gzip_falls_back_to_second_host(self):
        payload=gzip.compress(b'{"version":{}}')[:-5]
        class Response:
            headers={'Content-Encoding':'gzip'}
            def __init__(self,url):self.url=url
            def geturl(self):return self.url
            def read(self,n):return payload if 'https://inshot.cc/' in self.url else gzip.compress(b'{"version":{}}')
            def __enter__(self):return self
            def __exit__(self,*args):pass
        with patch.object(config.urllib.request,'build_opener',return_value=SimpleNamespace(open=lambda url,**kw:Response(url))):
            result=config.fetch('VersionInfo.json')
        self.assertIn('aws.inshot.cc',result['source'])
        self.assertEqual(result['failures'][0]['error'],'EOFError')

    def test_both_truncated_sources_report_failure_not_eof(self):
        class Response:
            headers={'Content-Encoding':'gzip'}
            def __init__(self,url):self.url=url
            def geturl(self):return self.url
            def read(self,n):return gzip.compress(b'{}')[:-5]
            def __enter__(self):return self
            def __exit__(self,*args):pass
        with patch.object(config.urllib.request,'build_opener',return_value=SimpleNamespace(open=lambda url,**kw:Response(url))):
            with self.assertRaisesRegex(ValueError,'两个正式来源均读取失败'):
                config.fetch('VersionInfo.json')

    def test_interrupted_http_body_falls_back(self):
        import http.client
        requests=[]
        def open_response(url,**kw):
            requests.append(url)
            raise http.client.IncompleteRead(b'partial')
        with patch.object(config.urllib.request,'build_opener',return_value=SimpleNamespace(open=open_response)):
            with self.assertRaisesRegex(ValueError,'两个正式来源均读取失败'):
                config.fetch('VersionInfo.json')
        self.assertEqual(len(requests),2)

class ImplicitGetOrThrow(unittest.TestCase):
    def test_implicit_receiver_call_requires_review(self):
        result=c.check_calls({}, {'Guru/src/main/X.kt':'class X : ViewModel() { fun work() = with(result) { getOrThrow() } }'})
        self.assertEqual(result['status'],'待确认')

    def test_local_method_declaration_is_not_a_call(self):
        result=c.check_calls({}, {'Guru/src/main/X.kt':'class X : ViewModel() { fun getOrThrow() = 1 }'})
        self.assertEqual(result['status'],'通过')

    def test_implicit_comment_and_string_are_ignored(self):
        result=c.check_calls({}, {'Guru/src/main/X.kt':'class X : ViewModel() { /* getOrThrow() */ val s="getOrThrow()" }'})
        self.assertEqual(result['status'],'通过')

class DependencyRichVersions(unittest.TestCase):
    def test_selected_snapshot_after_rich_constraint(self):
        text='googlePlayReleaseRuntimeClasspath\n+--- com.yuvcraft.data:a:{strictly 1.0} -> 2.0-SNAPSHOT\nBUILD SUCCESSFUL'
        self.assertEqual(c.check_dependencies(text, trusted=True)['status'], '异常')

    def test_unresolved_rich_constraint_cannot_pass(self):
        text='googlePlayReleaseRuntimeClasspath\n+--- com.yuvcraft.data:a:{strictly 1.0}\nBUILD SUCCESSFUL'
        self.assertEqual(c.check_dependencies(text, trusted=True)['status'], '待确认')

    def test_dynamic_selector_without_selected_version_cannot_pass(self):
        text='googlePlayReleaseRuntimeClasspath\n+--- com.yuvcraft.data:a:1.+\nBUILD SUCCESSFUL'
        self.assertEqual(c.check_dependencies(text, trusted=True)['status'], '待确认')

class VersionExpressionBoundaries(unittest.TestCase):
    def test_computed_code_is_not_literal(self):
        self.assertIsNone(c.version("versionCode = 200 + offset\nversionName = 'new'"))

    def test_concatenated_name_is_not_literal(self):
        self.assertIsNone(c.version("versionCode = 200\nversionName = 'new' + suffix"))

    def test_interpolated_name_is_not_literal(self):
        self.assertIsNone(c.version('versionCode = 200\nversionName = "1.0.${build}"'))

    def test_commented_literal_with_semicolon_is_supported(self):
        self.assertEqual(c.version("versionCode = 200; // release\nversionName = 'new';"), (200, 'new'))

class DiEvidenceSources(unittest.TestCase):
    def test_string_only_gates_cannot_pass(self):
        text='''config = UtCloudStorageConfig(false)
        override fun hookBuildUrl() {
            val example = """DebugManager.isDebugMode() && DebugManager.isAiTaskDebug() if (!debug) return url"""
            return "https://aitest.inshot.one"
        }
        override fun hookBodyParams() {}
        '''
        self.assertEqual(c.check_di(text, None, 'isReleaseAppVersion', 'lastIndexOf(versionCode)')['status'], '待确认')

    def test_commented_supporting_symbols_cannot_pass(self):
        text='''config = UtCloudStorageConfig(false)
        override fun hookBuildUrl() {
            val debug = DebugManager.isDebugMode() && DebugManager.isAiTaskDebug()
            if (!debug) { return url }
        }
        override fun hookBodyParams() {}
        '''
        self.assertEqual(c.check_di(text, None, '// isReleaseAppVersion', '// lastIndexOf(versionCode)')['status'], '待确认')

class EvidenceBatch(unittest.TestCase):
    def test_indented_dangerous_task_is_not_ignored(self):
        p=common.load_project('videoguru')
        with self.assertRaises(ValueError):
            common.graph_safe(':Guru:dependencies SKIPPED\n  :Guru:uploadServerAuthTask SKIPPED\n',p,':Guru:dependencies')

    def test_junit_negative_skip_count_cannot_pass(self):
        import re
        def run(cmd,**kw):
            if '--dry-run' not in cmd:
                text=Path(cmd[cmd.index('--init-script')+1]).read_text()
                folder=Path(json.loads(re.search(r'file\(("[^"]+")\)',text)[1]));folder.mkdir()
                (folder/'TEST-a.Test.xml').write_text('<testsuite name="a.Test" tests="1" failures="0" errors="0" skipped="-1"/>')
            return SimpleNamespace(returncode=0,stdout=':Guru:testGooglePlayDebugUnitTest SKIPPED\n',stderr='')
        with patch.object(contracts.subprocess,'run',side_effect=run):
            self.assertNotEqual(contracts.run_tests('.', ['a.Test'],1,'test')[0]['status'],'通过')

    def test_malformed_apk_report_is_contained(self):
        for raw in ([], {'schema_version':1,'old':None}, {'schema_version':1}):
            with self.subTest(raw=raw),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);old=root/'old.apk';new=root/'new.apk';out=root/'out'
                old.write_bytes(b'old');new.write_bytes(b'new')
                def run(*a,**kw):
                    out.mkdir();(out/'report.md').write_text('report');(out/'report.json').write_text(json.dumps(raw))
                    return SimpleNamespace(returncode=0)
                with patch.object(apk.subprocess,'run',side_effect=run):
                    self.assertEqual(apk.analyze(old,new,out)['status'],'未执行')

    def test_disappearing_apk_is_contained(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);old=root/'old.apk';new=root/'new.apk';out=root/'out'
            old.write_bytes(b'old');new.write_bytes(b'new')
            def run(*a,**kw):
                new.unlink();return SimpleNamespace(returncode=0)
            with patch.object(apk.subprocess,'run',side_effect=run):
                self.assertEqual(apk.analyze(old,new,out)['status'],'未执行')

    def test_apk_size_and_delta_must_match_inputs(self):
        for field,value in [('delta_bytes',99),('reconciled_delta_bytes',99)]:
            with self.subTest(field=field),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);old=root/'old.apk';new=root/'new.apk';out=root/'out'
                old.write_bytes(b'old');new.write_bytes(b'new')
                raw={'schema_version':1,'old':{'path':str(old),'size_bytes':3},'new':{'path':str(new),'size_bytes':3},'delta_bytes':0,'delta_percent':0,'zip_overhead_delta_bytes':0,'reconciled_delta_bytes':0,'categories':[],'files':[]}
                raw[field]=value
                def run(*a,**kw):
                    out.mkdir();(out/'report.md').write_text('report');(out/'report.json').write_text(json.dumps(raw))
                    return SimpleNamespace(returncode=0)
                with patch.object(apk.subprocess,'run',side_effect=run):
                    self.assertEqual(apk.analyze(old,new,out)['status'],'未执行')

    def test_malformed_junit_counts_do_not_pass(self):
        import re
        for xml in ('<testsuite name="a.Test" tests="-1"/>', '<testsuite name="a.Test" tests="1" skipped="2"/>', '<other name="a.Test" tests="1"/>'):
            def run(cmd,**kw):
                if '--dry-run' not in cmd:
                    text=Path(cmd[cmd.index('--init-script')+1]).read_text()
                    folder=Path(json.loads(re.search(r'file\(("[^"]+")\)',text)[1]));folder.mkdir()
                    (folder/'TEST-a.Test.xml').write_text(xml)
                return SimpleNamespace(returncode=0,stdout=':Guru:testGooglePlayDebugUnitTest SKIPPED\n',stderr='')
            with self.subTest(xml=xml),patch.object(contracts.subprocess,'run',side_effect=run):
                self.assertEqual(contracts.run_tests('.', ['a.Test'],1,'test')[0]['status'],'未执行')

class BuildEvidenceBoundaries(unittest.TestCase):
    def test_version_reference_inside_string_is_not_evidence(self):
        module='println "versionCode rootProject.ext.versionCode versionName rootProject.ext.versionName"'
        self.assertEqual(c.check_version("versionCode=1\nversionName='old'", "versionCode=2\nversionName='new'", module)['status'], '待确认')

    def test_auth_link_to_different_task_is_not_evidence(self):
        module="apply from: '../gradle/serverauth.gradle'\npreBuild.dependsOn uploadServerAuthTaskDisabled"
        self.assertNotEqual(c.check_auth(module,'task uploadServerAuthTask {}')['status'],'通过')

    def test_auth_text_inside_string_is_not_evidence(self):
        module='''val example = """apply from: '../gradle/serverauth.gradle'
preBuild.dependsOn uploadServerAuthTask"""'''
        self.assertNotEqual(c.check_auth(module,'task uploadServerAuthTask {}')['status'],'通过')

    def test_identity_only_in_multiline_example_rejected(self):
        p=common.load_project('videoguru')
        files={p['identity']['settings']:b'include ":Guru"', p['identity']['module_build']:('def example = """\napplicationId "'+p['identity']['application_id']+'"\n"""').encode()}
        with self.assertRaises(ValueError):common.verify_identity(Path('.'),p,files)

class RegistryDataBoundaries(unittest.TestCase):
    def test_draft_nonobject_entry_rejected(self):
        import release_draft_check as d
        for raw in ('[null]', '[1]', '[[]]'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):d.registry(raw)

    def test_draft_models_must_be_nonempty_identifiers(self):
        import release_draft_check as d
        for models in ([None], [''], ['A B'], []):
            with self.subTest(models=models),self.assertRaises(ValueError):
                d.registry(json.dumps([dict(models=models, tests=[], evidence=[])]))

    def test_duplicate_contract_json_key_rejected(self):
        import release_draft_check as d
        with self.assertRaises(ValueError):
            d.registry('[{"models":["A"],"models":["B"],"tests":[],"evidence":[]}]')

    def test_purchase_constants_must_be_string_pairs(self):
        import release_purchase_check as p
        row=dict(id='x',labels=['A'],entries=[],tests=[],policy='Policy.kt',constants={'LABEL':None})
        with self.assertRaises(ValueError):p.registry(json.dumps([row]))

    def test_purchase_empty_id_rejected(self):
        import release_purchase_check as p
        row=dict(id='',labels=['A'],entries=[],tests=[],policy='Policy.kt',constants={})
        with self.assertRaises(ValueError):p.registry(json.dumps([row]))

class ProjectStructureValidation(unittest.TestCase):
    def test_invalid_project_structures_fail_at_load(self):
        mutations = [
            lambda p: p.update(sources=[]),
            lambda p: p.update(modules='Guru'),
            lambda p: p.update(di=[]),
            lambda p: p['configs'].update(indexes=[]),
            lambda p: p['configs'].update(hosts=[]),
            lambda p: p['configs'].update(exceptions=[None]),
            lambda p: p['gradle'].update(danger_patterns=['[']),
        ]
        original=common.load_project('videoguru')
        for mutate in mutations:
            with self.subTest(mutation=mutate),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);folder=root/'projects/videoguru';folder.mkdir(parents=True)
                project=copy.deepcopy(original);mutate(project)
                (folder/'project.json').write_text(json.dumps(project))
                for key in ('draft','purchase'):
                    (folder/original[key]['registry']).write_text(common.registry_text(original,key))
                with patch.object(common,'SKILL',root),self.assertRaises(ValueError):
                    common.load_project('videoguru')

class CrossModuleInputFailures(unittest.TestCase):
    def test_crlf_version_literals_remain_supported(self):
        self.assertEqual(c.version("versionCode = 20\r\nversionName = 'two'\r\n"), (20,'two'))

    def test_gradle_start_error_returns_unexecuted(self):
        with patch.object(contracts.subprocess,'run',side_effect=PermissionError('fixture')):
            result,_=contracts.run_tests('.', ['a.Test'],1,'test')
        self.assertEqual(result['status'],'未执行')

class FinalCliAudit(unittest.TestCase):
    def test_defer_conflicting_execution_rejected_before_runner(self):
        import contextlib,io
        for flag,number in [('--run-draft-tests',5),('--run-purchase-tests',10),('--resolve-dependencies',12)]:
            argv=['release-check','--project','videoguru','--base','candidate','--worktree','--output-dir','/tmp/never-created-release-output',flag,'--defer',f'{number}=later']
            with self.subTest(flag=flag),patch.object(sys,'argv',argv),patch.object(c,'repo_root',side_effect=AssertionError('validation too late')),contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(c.main(),2)

    def test_declared_empty_sdk_does_not_trigger_fallback(self):
        # Explicit machine values are rejected before device discovery.
        spec=importlib.util.spec_from_file_location('baseline_final', S/'scripts/baseline-profile.py')
        baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'machine.json';path.write_text('{"schema_version":1,"sdk_root":" "}')
            with self.assertRaises(ValueError):baseline.load_machine(path)
