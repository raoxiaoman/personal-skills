import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import time

spec=importlib.util.spec_from_file_location('baseline',Path(__file__).parents[1]/'scripts/baseline-profile.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
GRAPH=b.profile()['task']+' SKIPPED\n:BaselineProfile:connectedGooglePlayNonMinifiedReleaseAndroidTest SKIPPED\n'

class BaselineChecks(unittest.TestCase):
    def test_serial_conflict_and_physical_device_rejected(self):
        for explicit,bound in [('emulator-5554','phone'),('phone',None),(None,None),('emulator-5555',None)]:
            with self.assertRaises(ValueError):b.serial_value(explicit,bound)
        self.assertEqual(b.serial_value(None,'emulator-5554'),'emulator-5554')

    def test_graph_rejects_upload_copy_and_managed_devices(self):
        b.validate_graph(GRAPH)
        for extra in [':Guru:uploadServerAuthTask',':Guru:copyGooglePlayReleaseBaselineProfileIntoSrc',':BaselineProfile:pixel6Api34Test']:
            with self.assertRaises(ValueError):b.validate_graph(GRAPH+extra+' SKIPPED\n')
        with self.assertRaises(ValueError):b.validate_graph(':Guru:other SKIPPED\n')

    def test_identity_is_mandatory(self):
        with patch.object(b,'adb_call',return_value=SimpleNamespace(returncode=0,stdout='Other\nOK')):
            with self.assertRaises(ValueError):b.identity('adb','emulator-5554','RootDevice')

    def test_boot_timeout_and_crash(self):
        with patch.object(b,'adb_call',return_value=SimpleNamespace(returncode=1,stdout='')):
            with self.assertRaises(ValueError):b.ready('adb','emulator-5554','RootDevice',0)
        process=SimpleNamespace(poll=lambda:1)
        with self.assertRaises(ValueError):b.ready('adb','emulator-5554','RootDevice',10,process)

    def test_running_device_root_failure_stops(self):
        def adb(*args):
            if args[-1]=='root':return SimpleNamespace(returncode=0,stdout='adbd cannot run as root',stderr='')
            return SimpleNamespace(returncode=0,stdout='32',stderr='')
        with patch.object(b,'adb_call',side_effect=adb),patch.object(b,'identity'),patch.object(b,'ready'):
            with tempfile.TemporaryDirectory() as temp:
                with self.assertRaises(ValueError):b.ensure_device('adb','emulator','emulator-5554','RootDevice',Path(temp),10)

    def test_fresh_profiles_and_generator_xml_required(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);out=root/'run';(out/'profiles').mkdir(parents=True)
            folder=root/'BaselineProfile/build/outputs/androidTest-results/connected/nonminifiedrelease/flavors/googlePlay';folder.mkdir(parents=True)
            xml=folder/'TEST-generator.xml'
            xml.write_text(f'<testsuite name="{b.profile()['test']}" tests="1" failures="0" errors="0" skipped="0"/>')
            for name in b.profile()['files']:(out/'profiles'/name).write_text('Lexample/Class;\n')
            log='> Task :BaselineProfile:connectedGooglePlayNonMinifiedReleaseAndroidTest\n'
            self.assertEqual(b.verify_outputs(root,out,0,log)['baseline-prof.txt']['lines'],1)
            with self.assertRaises(ValueError):b.verify_outputs(root,out,time.time_ns()+1000000,log)
            with self.assertRaises(ValueError):b.verify_outputs(root,out,0,log.replace('\n',' FROM-CACHE\n'))
            xml.write_text(f'<testsuite name="{b.profile()['test']}" tests="1" skipped="1"/>')
            with self.assertRaises(ValueError):b.verify_outputs(root,out,0,log)

    def test_generation_init_redirects_without_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            script=b.init_script(Path(temp)).read_text()
            self.assertIn('baselineProfileDir.set',script)
            self.assertIn('upToDateWhen { false }',script)
            self.assertNotIn('copyGooglePlay',script)
            self.assertIn('ext.saveInSrc = true', script)
            self.assertIn('ext.automaticGenerationDuringBuild = false', script)
            self.assertNotIn('ext.saveInSrc = false', script)

    def test_cold_start_uses_fixed_avd_port_and_detaches(self):
        def adb(*args):
            if args[-1]=='get-state':return SimpleNamespace(returncode=1,stdout='',stderr='')
            if args[-1]=='root':return SimpleNamespace(returncode=0,stdout='already root',stderr='')
            if args[-1]=='id':return SimpleNamespace(returncode=0,stdout='uid=0(root)',stderr='')
            return SimpleNamespace(returncode=0,stdout='32',stderr='')
        def invoke(cmd,*args):return SimpleNamespace(returncode=0,stdout='RootDevice\n' if '-list-avds' in cmd else 'List of devices attached\n',stderr='')
        with tempfile.TemporaryDirectory() as temp,patch.object(b,'adb_call',side_effect=adb),patch.object(b,'invoke',side_effect=invoke),patch.object(b,'ready'),patch.object(b.socket,'socket'),patch.object(b.subprocess,'Popen') as spawn:
            result=b.ensure_device('adb','emulator','emulator-5554','RootDevice',Path(temp),10)
            self.assertTrue(result['started_by_script'])
            self.assertEqual(spawn.call_args.args[0],['emulator','-avd','RootDevice','-port','5554'])
            self.assertTrue(spawn.call_args.kwargs['start_new_session'])

    def test_failed_device_listing_does_not_start_emulator(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(b, 'adb_call', return_value=SimpleNamespace(returncode=1, stdout='', stderr='')), patch.object(b, 'invoke', side_effect=[SimpleNamespace(returncode=0, stdout='RootDevice\n'), SimpleNamespace(returncode=1, stdout='')]), patch.object(b.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(ValueError, '清单读取失败'):
                b.ensure_device('adb', 'emulator', 'emulator-5554', 'RootDevice', Path(temp), 10)
            spawn.assert_not_called()

    def test_unknown_other_emulator_identity_stops_startup(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(b, 'adb_call', return_value=SimpleNamespace(returncode=1, stdout='', stderr='')), patch.object(b, 'invoke', side_effect=[SimpleNamespace(returncode=0, stdout='RootDevice\n'), SimpleNamespace(returncode=0, stdout='List of devices attached\nemulator-5556 offline\n')]), patch.object(b.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(ValueError, '身份无法确认'):
                b.ensure_device('adb', 'emulator', 'emulator-5554', 'RootDevice', Path(temp), 10)
            spawn.assert_not_called()

    def test_machine_config_requires_object(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/'machine.json'
            for content in ('[]','null','{"schema_version":1,"sdk_root":42}', '{"schema_version":1,"avd":"x","avd":"y"}'):
                file.write_text(content)
                with self.subTest(content=content), self.assertRaises(ValueError):
                    b.load_machine(file)

    def test_explicit_missing_sdk_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                b.sdk_tools(str(Path(temp)/'missing'))

    def test_valid_machine_config_remains_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'machine.json'
            path.write_text('{"schema_version":1,"avd":"RootDevice","sdk_root":"/sdk"}')
            self.assertEqual(b.load_machine(path)['avd'],'RootDevice')
