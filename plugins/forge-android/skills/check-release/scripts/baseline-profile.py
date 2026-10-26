#!/usr/bin/env python3
"""已有root AVD上的启动Profile候选生成；不写回源码。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_common import load_project, repo_root, verify_identity, new_output, tool_digest, graph_safe, worktree_inputs, digest, inside, strict_json


def profile(project=None):
    return (project or load_project('videoguru'))['baseline']


def invoke(command, timeout=30, env=None):
    return subprocess.run([str(v) for v in command], capture_output=True, text=True, timeout=timeout, env=env)


def sdk_tools(sdk_root=None):
    roots = [sdk_root] if sdk_root is not None else [os.environ.get('ANDROID_SDK_ROOT'), os.environ.get('ANDROID_HOME'), str(Path.home() / 'Library/Android/sdk')]
    for value in roots:
        if value:
            sdk = Path(value)
            if (sdk/'platform-tools/adb').is_file() and (sdk/'emulator/emulator').is_file():
                return sdk/'platform-tools/adb', sdk/'emulator/emulator'
    raise ValueError('未找到SDK adb/emulator；请设置ANDROID_SDK_ROOT，不自动安装')


def serial_value(explicit, bound):
    if not bound:
        raise ValueError('须先设置ANDROID_SERIAL绑定目标虚拟机')
    if explicit and explicit != bound:
        raise ValueError('--serial与ANDROID_SERIAL冲突；先显式绑定目标虚拟机')
    serial = bound
    if not serial or not re.fullmatch(r'emulator-\d+', serial):
        raise ValueError('须使用当前ANDROID_SERIAL绑定的emulator-端口，禁止自动选设备')
    port = int(serial.split('-')[1])
    if port < 5554 or port > 5682 or port % 2:
        raise ValueError('模拟器console端口须为5554至5682的偶数')
    return serial


def adb_call(adb, serial, *args):
    return invoke([adb, '-s', serial, *args])


def identity(adb, serial, avd):
    result = adb_call(adb, serial, 'emu', 'avd', 'name')
    if result.returncode or result.stdout.splitlines()[:1] != [avd]:
        raise ValueError('目标serial的AVD身份不匹配：' + avd)


def ready(adb, serial, avd, timeout, process=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process and process.poll() is not None:
            raise ValueError('虚拟机进程提前退出，请检查emulator.log')
        state = adb_call(adb, serial, 'get-state')
        if state.returncode == 0 and state.stdout.strip() == 'device':
            identity(adb, serial, avd)
            boot = adb_call(adb, serial, 'shell', 'getprop', 'sys.boot_completed')
            pm = adb_call(adb, serial, 'shell', 'pm', 'path', 'android')
            if boot.stdout.strip() == '1' and pm.returncode == 0 and 'package:' in pm.stdout:
                return
        time.sleep(1)
    raise ValueError('等待虚拟机开机/包管理器超时')


def ensure_device(adb, emulator, serial, avd, output, timeout):
    state = adb_call(adb, serial, 'get-state')
    process = None
    if state.returncode == 0:
        identity(adb, serial, avd)
    else:
        available = invoke([emulator, '-list-avds'])
        if available.returncode or avd not in available.stdout.splitlines():
            raise ValueError('已有AVD未登记，不创建或下载：' + avd)
        # 仅用于身份冲突检查，不从列表选择设备。
        listing = invoke([adb, 'devices'])
        if listing.returncode:
            raise ValueError('设备身份清单读取失败，不启动AVD')
        for line in listing.stdout.splitlines()[1:]:
            parts = line.split()
            if parts and parts[0].startswith('emulator-'):
                other = parts[0]
                if other == serial:
                    raise ValueError('目标serial已存在但不可用，不启动副本')
                name = adb_call(adb, other, 'emu', 'avd', 'name')
                if name.returncode:
                    raise ValueError('其他模拟器身份无法确认，不启动同名AVD副本')
                if name.stdout.splitlines()[:1] == [avd]:
                    raise ValueError('同名AVD已在其他serial运行，不自动换绑')
        port = int(serial.split('-')[1])
        for number in (port, port + 1):
            with socket.socket() as probe:
                try:
                    probe.bind(('127.0.0.1', number))
                except OSError as error:
                    raise ValueError('模拟器端口已占用，不启动') from error
        with (output/'emulator.log').open('x') as log:
            process = subprocess.Popen([str(emulator), '-avd', avd, '-port', str(port)], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    ready(adb, serial, avd, timeout, process)
    api = adb_call(adb, serial, 'shell', 'getprop', 'ro.build.version.sdk')
    if api.returncode or not api.stdout.strip().isdigit() or int(api.stdout.strip()) < 28:
        raise ValueError('生成要求API28+且root可用')
    root = adb_call(adb, serial, 'root')
    if root.returncode or 'cannot run as root' in root.stdout + root.stderr:
        raise ValueError('adb root失败；su可用不能替代adb root')
    ready(adb, serial, avd, timeout, process)
    user = adb_call(adb, serial, 'shell', 'id')
    if user.returncode or not re.search(r'\buid=0\(', user.stdout):
        raise ValueError('重连后ADB shell不是root')
    return dict(serial=serial, avd=avd, api=int(api.stdout.strip()), abi=adb_call(adb, serial, 'shell', 'getprop', 'ro.product.cpu.abi').stdout.strip(), started_by_script=process is not None)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def source_hashes(root, project=None):
    b=profile(project);folder=inside(root,b['profile_dir'])
    return {name: sha(inside(folder,name).read_bytes()) if inside(folder,name).exists() else None for name in b['files']}


def input_digest(root):
    return digest(worktree_inputs(Path(root)))


def validate_graph(text, project=None):
    p=project or load_project('videoguru');b=p['baseline']
    tasks=graph_safe(text,p,b['task'],baseline=True)
    if b['connected_task'] not in tasks:
        raise ValueError('任务图缺少预期连接设备测试任务')


def init_script(output, project=None):
    p=project or load_project('videoguru');b=p['baseline']
    path=output/'candidate.gradle'
    tasks=json.dumps([b['task'],b['collect_task'],b['connected_task']])
    # 提前登记afterEvaluate：切换已有连接设备入口，仅重定向候选，不复制回源码。
    path.write_text('gradle.beforeProject { p -> p.afterEvaluate {\n'
        'if (p.path == ":BaselineProfile") { def ext = p.extensions.findByName("baselineProfile"); if (ext != null) { ext.managedDevices.clear(); ext.useConnectedDevices = true } }\n'
        'if (p.path == '+json.dumps(':'+p['module'])+') { def ext = p.extensions.findByName("baselineProfile"); if (ext != null) { ext.saveInSrc = true; ext.automaticGenerationDuringBuild = false } }\n'
        '} }\n'
        'gradle.projectsEvaluated { allprojects { tasks.configureEach { t ->\n'
        'if (t.path == '+json.dumps(b['task'])+') { t.baselineProfileDir.set(file('+json.dumps(str(output/'profiles'))+')) }\n'
        'if (t.path in '+tasks+') { t.outputs.upToDateWhen { false }; t.outputs.cacheIf { false } }\n'
        '} } }\n')
    return path


def verify_outputs(root, output, started_ns, log, project=None):
    b=profile(project)
    task=b['connected_task']
    if not re.search(r'^> Task ' + re.escape(task) + r'\s*$', log, re.M):
        raise ValueError('没有本轮设备测试执行证据（缓存/跳过不接受）')
    folder = inside(root,b['results_dir'])
    suites = []
    for p in folder.glob('TEST-*.xml'):
        if p.stat().st_mtime_ns < started_ns:
            continue
        suite = ET.parse(p).getroot()
        if suite.get('name') == b['test']:
            suites.append(suite)
    if len(suites) != 1:
        raise ValueError('缺少本轮唯一生成器JUnit结果')
    suite = suites[0]
    if any(int(suite.get(k, 0)) for k in ('failures', 'errors', 'skipped')) or int(suite.get('tests', 0)) != 1:
        raise ValueError('生成器失败、跳过或用例数不符')
    info = {}
    for name in b['files']:
        path = output/'profiles'/name
        if not path.is_file() or not path.read_bytes().strip() or path.stat().st_mtime_ns < started_ns:
            raise ValueError('候选产物缺失、为空或过期：' + name)
        data = path.read_bytes()
        current = inside(root,b['profile_dir']+'/'+name)
        before = set(current.read_text().splitlines()) if current.exists() else set()
        after = set(data.decode().splitlines())
        info[name] = dict(sha256=sha(data), lines=len(data.decode().splitlines()), added=len(after-before), removed=len(before-after))
    return info


def load_machine(path):
    if path is None:
        return {}
    machine = strict_json(Path(path).read_text())
    if not isinstance(machine, dict) or machine.get('schema_version') != 1 or set(machine) - {'schema_version', 'avd', 'sdk_root'}:
        raise ValueError('machine配置必须为schema_version=1的对象，只允许avd/sdk_root')
    for key in ('avd', 'sdk_root'):
        if key in machine and (not isinstance(machine[key], str) or not machine[key].strip()):
            raise ValueError('machine配置字段必须为非空字符串：' + key)
    if 'avd' in machine and not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', machine['avd']):
        raise ValueError('machine AVD名称无效')
    return machine


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['check','dry-run','generate'],nargs='?',default='check')
    parser.add_argument('--repo',type=Path);parser.add_argument('--project',required=True)
    parser.add_argument('--avd');parser.add_argument('--serial');parser.add_argument('--machine-config',type=Path)
    parser.add_argument('--inspect-device',action='store_true',help='仅check时显式只读检查绑定AVD')
    parser.add_argument('--output',type=Path);parser.add_argument('--timeout',type=int,default=900)
    args=parser.parse_args();output=None;record=dict(status='未执行',source_updated=False)
    try:
        if args.timeout<=0:raise ValueError('超时必须大于0')
        root=repo_root(args.repo);p=load_project(args.project);verify_identity(root,p);b=p['baseline']
        machine=load_machine(args.machine_config)
        avd=args.avd or machine.get('avd')
        if avd and (not isinstance(avd,str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*',avd)):
            raise ValueError('AVD名称无效，不接受选项或路径')
        if args.inspect_device and args.action!='check':raise ValueError('--inspect-device只允许check')
        if args.action=='check':
            record.update(project=p['id'],source_profiles=source_hashes(root,p),capability=p['capabilities']['baseline'],status='静态盘点完成，生成/性能验证未执行')
            if args.inspect_device:
                if not avd:raise ValueError('设备检查需显式--avd或machine配置')
                serial=serial_value(args.serial,os.environ.get('ANDROID_SERIAL'));adb,_=sdk_tools(machine.get('sdk_root'))
                state=adb_call(adb,serial,'get-state')
                if state.returncode:raise ValueError('绑定设备不可用，不自动选择')
                identity(adb,serial,avd);record['device']=dict(serial=serial,avd=avd,state=state.stdout.strip(),shell=adb_call(adb,serial,'shell','id').stdout.strip())
            print(json.dumps(record,ensure_ascii=False,indent=2));return 2
        if b['generation']!='supported':raise ValueError('本项目Baseline生成尚未适配，不套用其他项目任务')
        if not args.output:raise ValueError('必须指定全新--output目录')
        if args.action=='generate' and not avd:raise ValueError('generate须显式--avd或machine配置，不使用历史设备授权')
        serial=serial_value(args.serial,os.environ.get('ANDROID_SERIAL')) if args.action=='generate' else None
        output=new_output(args.output,root);output.mkdir(parents=True,exist_ok=False)
        before=source_hashes(root,p);source_digest=input_digest(root);contract_digest=tool_digest(p)
        head=invoke(['git','-C',root,'rev-parse','HEAD']).stdout.strip()
        record.update(project=p['id'],serial=serial,avd=avd,input_digest=source_digest,tool_config_digest=contract_digest,head=head,source_before=before)
        init=init_script(output,p);env=dict(os.environ)
        if serial:env['ANDROID_SERIAL']=serial
        command=[str(root/'gradlew'),'-p',str(root),b['task'],'--offline','--console=plain','--no-build-cache','-x',p['gradle']['exclude'][0],'--init-script',str(init),'-Pandroid.testInstrumentationRunnerArguments.class='+b['test']]
        graph=invoke(command+['--dry-run'],args.timeout,env);(output/'task-graph.log').write_text(graph.stdout+graph.stderr)
        if graph.returncode:raise ValueError('Gradle任务图预检失败')
        validate_graph(graph.stdout+graph.stderr,p)
        if args.action=='dry-run':record['status']='预检完成，生成与性能验证未执行';return 2
        adb,emulator=sdk_tools(machine.get('sdk_root'))
        record['device']=ensure_device(adb,emulator,serial,avd,output,args.timeout)
        started=time.time_ns()
        with (output/'gradle.log').open('x') as log:
            process=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=args.timeout,env=env,cwd=root)
        if process.returncode:raise ValueError('Profile生成失败，见gradle.log')
        record['profiles']=verify_outputs(root,output,started,(output/'gradle.log').read_text(),p)
        record['source_after']=source_hashes(root,p)
        record['stable']=source_digest==input_digest(root) and before==record['source_after'] and contract_digest==tool_digest(p) and head==invoke(['git','-C',root,'rev-parse','HEAD']).stdout.strip()
        if not record['stable']:raise ValueError('输入/契约/源码Profile变化，候选过期；不自动恢复')
        record['status']='候选生成通过，未更新源码，完整冷启动性能验证未完成';print(str(output/'manifest.json'));return 0
    except (ValueError,OSError,KeyError,TypeError,subprocess.TimeoutExpired,ET.ParseError) as error:
        record['status']='失败/未完成';record['error']=str(error) if isinstance(error,ValueError) else type(error).__name__
        print(record['error'],file=sys.stderr);return 2
    finally:
        if output and output.exists():
            (output/'manifest.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':sys.exit(main())
