"""登记契约测试的固定离线执行器，不开放支付、设备或任意命令。"""
import json
from pathlib import Path
import re
import subprocess
import tempfile
from release_common import load_project, graph_safe
import xml.etree.ElementTree as ET

def run_tests(root, selectors, timeout, name, project=None):
    project = project or load_project("videoguru")
    if any(not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+", s) for s in selectors):
        raise ValueError("测试选择器必须为完整类名")
    root = Path(root)
    if not selectors:
        return dict(name=name, status='未执行', evidence=['变化无登记测试，不启动Gradle']), ''
    # 结果输出到本轮全新目录，不接受历史XML；配置脚本与结果留本地。
    with tempfile.TemporaryDirectory(prefix='release-contract-') as temp:
        results = Path(temp) / 'results'
        init = Path(temp) / 'results.gradle'
        init.write_text('gradle.projectsEvaluated { allprojects { tasks.withType(org.gradle.api.tasks.testing.Test).configureEach { reports.junitXml.outputLocation = file(' + json.dumps(str(results)) + ') } } }')
        cmd = ['./gradlew', project['gradle']['test_task'], '--offline', '--console=plain', '--rerun-tasks', '--no-build-cache', '-x', project['gradle']['exclude'][0], '--init-script', str(init)]
        for selector in selectors:
            cmd += ['--tests', selector]
        logs = ''
        try:
            dry = subprocess.run(cmd + ['--dry-run'], cwd=root, capture_output=True, text=True, timeout=timeout)
            logs = dry.stdout + dry.stderr
            if dry.returncode:
                return dict(name=name, status='未执行', evidence=['任务图失败或包含鉴权上传，未运行测试']), logs
            graph_safe(logs, project, project['gradle']['test_task'])
            process = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=timeout)
            logs += '\n' + process.stdout + process.stderr
            suites = [ET.parse(p).getroot() for p in results.glob('TEST-*.xml')]
            for suite in suites:
                if suite.tag != 'testsuite':
                    raise ValueError('JUnit根节点不符')
                counts = [int(suite.get(k, 0)) for k in ('tests', 'failures', 'errors', 'skipped')]
                if min(counts) < 0 or sum(counts[1:]) > counts[0]:
                    raise ValueError('JUnit计数不合法')
            if len({s.get('name') for s in suites}) != len(suites):
                raise ValueError('JUnit测试类重复，覆盖来源不明确')
            seen = {s.get('name') for s in suites}
            tests = sum(int(s.get('tests', 0)) for s in suites)
            failures = sum(int(s.get('failures', 0)) + int(s.get('errors', 0)) for s in suites)
            skipped = sum(int(s.get('skipped', 0)) for s in suites)
            complete = all(int(s.get('tests', 0)) > int(s.get('skipped', 0)) for s in suites if s.get('name') in selectors)
            if process.returncode or failures:
                status = '异常'
            elif tests == 0 or skipped or not set(selectors) <= seen or not complete:
                status = '未执行'
            else:
                status = '通过'
            return dict(name=name, status=status, evidence=[f'本轮独立JUnit结果：{tests}项，失败/错误{failures}，跳过{skipped}；登记类覆盖：{set(selectors) <= seen}', '仅表示登记测试覆盖范围；不自动放行业务链路判断。']), logs
        except subprocess.TimeoutExpired:
            return dict(name=name, status='未执行', evidence=['Gradle超时，未得到完整本轮测试证据']), logs + '\nTIMEOUT'
        except OSError as error:
            return dict(name=name, status='未执行', evidence=['Gradle进程或结果文件无法访问：' + type(error).__name__]), logs
        except (ET.ParseError, ValueError) as error:
            return dict(name=name, status='未执行', evidence=['本轮JUnit结果无法校验：' + type(error).__name__]), logs
