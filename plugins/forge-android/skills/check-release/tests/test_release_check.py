import sys
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
spec = importlib.util.spec_from_file_location('release_check', Path(__file__).parents[1] / 'scripts/release-check.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class Checks(unittest.TestCase):
    def test_comments_strings_and_multiline(self):
        self.assertEqual(len(c.calls('// x.getOrThrow()\nval s="x.getOrThrow()"\nx.\ngetOrThrow()')), 1)

    def test_version(self):
        guru = 'versionCode rootProject.ext.versionCode\nversionName rootProject.ext.versionName'
        for code, name, expected in [(3, 'new', '通过'), (1, 'new', '异常'), (2, 'old', '异常')]:
            self.assertEqual(c.check_version("versionCode=1\nversionName='old'", f"versionCode={code}\nversionName='{name}'", guru)['status'], expected)
        self.assertIsNone(c.version('versionName = dynamic'))

    def test_auth(self):
        guru = "apply from: '../gradle/serverauth.gradle'\npreBuild.dependsOn uploadServerAuthTask"
        self.assertEqual(c.check_auth(guru, 'task uploadServerAuthTask { }')['status'], '通过')
        self.assertEqual(c.check_auth(guru.replace('preBuild', '// preBuild'), 'task uploadServerAuthTask { }')['status'], '异常')

    def test_increment_and_deletion(self):
        path = 'Guru/src/main/Test.kt'
        plain = 'class Test : ViewModel() { fun a() { x.getOrThrow() } }'
        self.assertEqual(c.check_calls({}, {path: plain})['status'], '异常')
        self.assertEqual(c.check_calls({path: plain}, {path: plain})['status'], '通过')
        self.assertEqual(c.check_calls({path: plain}, {})['status'], '通过')
        self.assertEqual(c.check_calls({path: plain}, {'renamed.kt': plain})['status'], '待确认')

    def test_indirect_class(self):
        self.assertTrue(c.ui_class('class Child : Parent() {}', {'Child': {'Parent'}, 'Parent': {'ViewModel'}}))
        self.assertFalse(c.source('Guru/src/debug/Test.kt'))
        self.assertTrue(c.source('Guru/src/international/Test.kt'))

    def test_dependencies(self):
        prefix = 'googlePlayReleaseRuntimeClasspath\n'
        suffix = '\nBUILD SUCCESSFUL'
        self.assertEqual(c.check_dependencies(None)['status'], '未执行')
        self.assertEqual(c.check_dependencies(prefix + '+--- com.yuvcraft.data:a:1-SNAPSHOT -> 2' + suffix)['status'], '待确认')
        self.assertEqual(c.check_dependencies(prefix + '+--- com.yuvcraft.data:a:2 -> 3-SNAPSHOT' + suffix)['status'], '异常')
        self.assertEqual(c.check_dependencies(prefix + 'FAILED' + suffix)['status'], '待确认')

    def test_trusted_dependencies(self):
        text = 'googlePlayReleaseRuntimeClasspath - runtime\n+--- com.yuvcraft.data:a:1-SNAPSHOT -> 2\nBUILD SUCCESSFUL'
        self.assertEqual(c.check_dependencies(text, trusted=True)['status'], '通过')
        self.assertEqual(c.check_dependencies('googlePlayReleaseRuntimeClasspath\nBUILD SUCCESSFUL', True)['status'], '待确认')
        self.assertEqual(c.check_dependencies(text.replace('-> 2', '-> com.yuvcraft.data:a:2'), True)['status'], '通过')

    def test_timeout(self):
        with patch.object(c.subprocess, 'run', side_effect=subprocess.TimeoutExpired('gradle', 1)):
            text, code = c.resolve_dependencies(Path('.'), 1)
            self.assertEqual(code, -1)
            self.assertIn('BUILD FAILED', text)

    def test_di(self):
        self.assertEqual(c.check_di('config = UtCloudStorageConfig(true)', None, '', '')['status'], '异常')
        self.assertNotEqual(c.check_di('// config = UtCloudStorageConfig(true)', None, '', '')['status'], '异常')
        self.assertEqual(c.check_di('config = UtCloudStorageConfig(variable)', None, '', '')['status'], '待确认')

    def test_di_static_pass_with_runtime_notice(self):
        text = """config = UtCloudStorageConfig(false)
        override fun hookBuildUrl() {
            val debug = DebugManager.isDebugMode() && DebugManager.isAiTaskDebug()
            if (!debug) { return url }
            val domain = "https://speech.inshot.one"
        }
        override fun hookBodyParams() {}
        """
        for version in ((199, '1.630.199L'), (199, '1.630.199')):
            result = c.check_di(text, version, 'isReleaseAppVersion', 'lastIndexOf(versionCode)')
            self.assertEqual(result['status'], '通过')
        result = c.check_di(text, (199, '1.630.199L'), 'isReleaseAppVersion', 'lastIndexOf(versionCode)')
        self.assertTrue(any('提示' in e for e in result['evidence']))
        self.assertEqual(c.check_di(text.replace('&&', '||'), None, 'isReleaseAppVersion', 'lastIndexOf(versionCode)')['status'], '待确认')

    def test_youcut_hook_without_sibling_and_outside_guards(self):
        p = c.load_project('youcut')
        gates = "val debug = DebugManager.isDebugMode() && DebugManager.isAiTaskDebug(); if (!debug) { return url }"
        prefix = 'config = UtCloudStorageConfig(false)\n'
        text = prefix + 'override fun hookBuildUrl(): String { ' + gates + '; return url }'
        self.assertEqual(c.check_di(text, None, 'isReleaseAppVersion', 'lastIndexOf(versionCode)', p)['status'], '通过')
        outside = prefix + 'override fun hookBuildUrl(): String { return url }\nfun other() { ' + gates + ' }'
        self.assertEqual(c.check_di(outside, None, 'isReleaseAppVersion', 'lastIndexOf(versionCode)', p)['status'], '待确认')
        self.assertEqual(c.check_di(text[:-1], None, 'isReleaseAppVersion', 'lastIndexOf(versionCode)', p)['status'], '待确认')
        expression = prefix + 'override fun hookBuildUrl(): String = url\nfun other() { ' + gates + ' }'
        self.assertEqual(c.check_di(expression, None, 'isReleaseAppVersion', 'lastIndexOf(versionCode)', p)['status'], '待确认')

    def test_git_endpoints(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.run(['git', '-C', directory, *args], check=True, capture_output=True)
            git('init'); git('config', 'user.email', 'fixture@example.invalid'); git('config', 'user.name', 'Fixture')
            (root/'build.gradle').write_text("versionCode=1\nversionName='one'")
            git('add', '.'); git('commit', '-m', 'baseline'); git('tag', 'release-one')
            (root/'build.gradle').write_text("versionCode=2\nversionName='two'")
            git('add', '.'); git('commit', '-m', 'target')
            (root/'build.gradle').write_text("versionCode=99\nversionName='dirty'")
            report = c.run(root, 'release-one', 'HEAD')
            self.assertTrue(report['dirty'])
            self.assertIn('two / 2', report['checks'][0]['evidence'][0])
            working = c.run(root, 'release-one', 'HEAD', worktree=True)
            self.assertIn('dirty / 99', working['checks'][0]['evidence'][0])
            self.assertTrue(working['stable'])
            with patch.object(c, 'resolve_dependencies', return_value=('googlePlayReleaseRuntimeClasspath\n+--- com.yuvcraft.data:a:2\nBUILD SUCCESSFUL', 0)):
                working = c.run(root, 'release-one', 'HEAD', worktree=True, resolve=True)
                self.assertEqual(working['checks'][-1]['status'], '通过')
            with self.assertRaises(ValueError):
                c.run(root, 'release-one', 'HEAD', resolve=True)
            with self.assertRaises(ValueError):
                c.run(root, 'missing', 'HEAD')


if __name__ == '__main__':
    unittest.main()
