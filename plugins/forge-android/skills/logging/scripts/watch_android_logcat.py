#!/usr/bin/env python3
"""Collect task-tagged Android logs and target-UID crash evidence without clearing logcat."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import queue
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Iterable, Optional

LOGCAT_LINE = re.compile(
    r"^\d\d-\d\d\s+\d\d:\d\d:\d\d\.\d+\s+\d+\s+\d+\s+([VDIWEFAS])\s+(.+?):\s(.*)$"
)
UID_LINE = re.compile(r"^package:(?P<package>\S+)\s+uid:(?P<uid>\d+)\s*$")
NATIVE_TAGS = {"libc", "DEBUG", "crash_dump32", "crash_dump64"}
NATIVE_MARKERS = ("fatal signal", "native crash", "backtrace:", "tombstone")
STARTUP_GRACE_SECONDS = 0.35
STATUS_INTERVAL_SECONDS = 5.0


class CollectorError(RuntimeError):
    pass


class StatusReporter:
    """Batch notifications by time, including a single log followed by silence."""

    def __init__(self) -> None:
        self.last_report = time.monotonic()
        self.lines_since_report = 0
        self.crashes_since_report = 0

    def emit(self, message: str) -> None:
        print(message, flush=True)

    def record(self, crash=False) -> None:
        self.lines_since_report += 1
        self.crashes_since_report += int(crash)
        self.flush()

    def flush(self, force=False) -> None:
        now = time.monotonic()
        if self.lines_since_report and (force or now - self.last_report >= STATUS_INTERVAL_SECONDS):
            self.emit(f"STATUS captured={self.lines_since_report} crash_lines={self.crashes_since_report}")
            self.lines_since_report = 0
            self.crashes_since_report = 0
            self.last_report = now


def adb_command(adb: str, serial: str, *args: str) -> list[str]:
    return [adb, "-s", serial, *args]


def choose_serial(adb: str, explicit_serial: Optional[str]) -> str:
    environment_serial = os.environ.get("ANDROID_SERIAL")
    if environment_serial and explicit_serial and environment_serial != explicit_serial:
        raise CollectorError("--serial 与当前 ANDROID_SERIAL 绑定不一致；拒绝切换设备。")
    serial = environment_serial or explicit_serial
    if not serial:
        raise CollectorError("未绑定设备；先确认目标并设置 ANDROID_SERIAL 或显式 --serial，不自动选择设备。")
    try:
        result = subprocess.run(
            adb_command(adb, serial, "get-state"), text=True, capture_output=True, check=False, timeout=10
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CollectorError(f"无法校验绑定设备 {serial}：{exc}") from exc
    if result.returncode or result.stdout.strip() != "device":
        detail = result.stderr.strip() or result.stdout.strip()
        raise CollectorError(f"绑定设备 {serial} 不可用；不会换机。详情：{detail}")
    return serial


def default_output_directory() -> str:
    cache = os.environ.get("XDG_CACHE_HOME")
    root = Path(cache) if cache and Path(cache).is_absolute() else Path.home() / ".cache"
    return str(root / "forge-android" / "logcat")


def get_package_uid(adb: str, serial: str, package: str) -> str:
    command = adb_command(adb, serial, "shell", "cmd", "package", "list", "packages", "-U", package)
    try:
        result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CollectorError(f"无法查询 {package} 的 UID：{exc}") from exc
    if result.returncode:
        raise CollectorError(
            f"无法查询 {package} 的 UID（请确认包已安装且 adb shell 有权限）："
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    for line in result.stdout.splitlines():
        match = UID_LINE.match(line.strip())
        if match and match.group("package") == package:
            return match.group("uid")
    raise CollectorError(f"未找到包 {package} 的 UID；请确认包名正确且应用已安装。")


def verify_uid_filter(adb: str, serial: str, uid: str) -> None:
    command = adb_command(adb, serial, "logcat", "--uid", uid, "-d", "-t", "1")
    try:
        result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CollectorError(f"无法验证 logcat --uid 支持：{exc}") from exc
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise CollectorError(
            "目标设备的 logcat 不支持或不允许 --uid 过滤，无法安全采集动态多进程日志；"
            f"不会降级为全局日志采集。详情：{detail}"
        )


def device_start_time(adb: str, serial: str) -> str:
    command = adb_command(adb, serial, "shell", "date", "+%s.%N")
    try:
        result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CollectorError(f"无法读取设备时间：{exc}") from exc
    timestamp = result.stdout.strip()
    if result.returncode or not re.fullmatch(r"\d{10,}\.\d{9}", timestamp):
        detail = result.stderr.strip() or timestamp
        raise CollectorError(f"无法获取可用于 logcat -T 的设备时间：{detail}")
    return timestamp


def create_output_file(output_dir: str, task: str):
    directory = Path(output_dir).expanduser().resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Do not chmod an existing user-supplied directory; isolate each run beneath it.
    session = directory / f"capture-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(8)}"
    session.mkdir(mode=0o700)
    path = session / f"android-logcat-{task}.log"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return path, os.fdopen(fd, "w", encoding="utf-8", buffering=1)


def keep_line(line: str, task: str) -> bool:
    match = LOGCAT_LINE.match(line)
    if not match:
        # Continuation lines are retained only after their tagged crash header is handled by
        # logcat itself; unclassified lines cannot be safely attributed to this collector.
        return False
    tag, message = match.group(2).strip(), match.group(3)
    # Project loggers usually use a class name as the Android tag. The task marker
    # belongs in the message, not necessarily in Android's separate tag field.
    if f"[TEMP:{task}]" in message or tag == f"[TEMP:{task}]":
        return True
    if tag == "AndroidRuntime":
        return True
    return tag in NATIVE_TAGS and (match.group(1) == 'F' or any(marker in message.lower() for marker in NATIVE_MARKERS))


def enqueue_stream(stream: Iterable[str], source: str, output: queue.Queue[tuple[str, Optional[str]]]) -> None:
    try:
        for line in stream:
            output.put((source, line))
    finally:
        output.put((source, None))


def terminate(process: Optional[subprocess.Popen[str]]) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def run(args: argparse.Namespace) -> int:
    reporter = StatusReporter()
    stop = threading.Event()
    process: Optional[subprocess.Popen[str]] = None

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    old_term = signal.signal(signal.SIGTERM, request_stop)
    old_int = signal.signal(signal.SIGINT, request_stop)
    try:
        serial = choose_serial(args.adb, args.serial)
        uid = get_package_uid(args.adb, serial, args.package)
        verify_uid_filter(args.adb, serial, uid)
        start_time = device_start_time(args.adb, serial)
        output_path, log_file = create_output_file(args.output, args.task)
        command = adb_command(
            args.adb, serial, "logcat", "--uid", uid, "-T", start_time, "-v", "threadtime", "*:V"
        )
        try:
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
                encoding='utf-8', errors='replace'
            )
        except OSError as exc:
            log_file.close()
            output_path.unlink(missing_ok=True)
            raise CollectorError(f"无法启动 UID 过滤的 logcat：{exc}") from exc

        # Popen success does not prove logcat accepted its options. Wait briefly for immediate
        # option/permission failures before advertising readiness.
        time.sleep(STARTUP_GRACE_SECONDS)
        if process.poll() is not None:
            stderr = process.stderr.read().strip() if process.stderr else ""
            log_file.close()
            output_path.unlink(missing_ok=True)
            raise CollectorError(f"logcat 启动失败：{stderr or '进程异常退出'}")

        events: queue.Queue[tuple[str, Optional[str]]] = queue.Queue(maxsize=2048)
        threads = [
            threading.Thread(target=enqueue_stream, args=(process.stdout, "stdout", events), daemon=True),
            threading.Thread(target=enqueue_stream, args=(process.stderr, "stderr", events), daemon=True),
        ]
        for thread in threads:
            thread.start()
        reporter.emit(f"READY file={output_path} serial={serial} uid={uid}")
        max_bytes = args.max_bytes
        stderr_count = 0
        stopped_process = False
        closed_streams = set()
        while True:
            if stop.is_set() and not stopped_process:
                terminate(process)
                stopped_process = True
            reporter.flush()
            try:
                source, line = events.get(timeout=0.25)
            except queue.Empty:
                if stopped_process and len(closed_streams) == 2:
                    break
                if not stopped_process and process.poll() is not None:
                    raise CollectorError(f"logcat 意外退出，退出码 {process.returncode}。")
                continue
            if line is None:
                closed_streams.add(source)
                if not stopped_process and process.poll() is not None:
                    raise CollectorError(f"logcat 的 {source} 流已关闭，退出码 {process.returncode}。")
                continue
            if source == "stderr":
                stderr_count += 1
                if stderr_count == 1:
                    reporter.emit(f"STATUS logcat-stderr={line.strip()[:240]}")
                continue
            if keep_line(line, args.task):
                log_file.write(line if line.endswith("\n") else line + "\n")
                log_file.flush()
                if log_file.tell() >= max_bytes:
                    raise CollectorError(f"达到 --max-bytes={max_bytes} 上限，已停止采集以避免磁盘持续增长。")
                reporter.record(crash='AndroidRuntime' in line or any(marker in line.lower() for marker in NATIVE_MARKERS))
        return 0
    except (CollectorError, OSError) as exc:
        reporter.emit(f"ERROR {exc}")
        return 2
    finally:
        terminate(process)
        reporter.flush(force=True)
        signal.signal(signal.SIGTERM, old_term)
        signal.signal(signal.SIGINT, old_int)
        if 'log_file' in locals() and not log_file.closed:
            log_file.close()
        if stop.is_set():
            reporter.emit("STATUS stopped")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="采集 [TEMP:<task-id>] 及目标 UID 的崩溃日志；不清空 logcat。",
        epilog="需要设备支持 logcat --uid 和纳秒 date；不采集系统 UID 的 ANR/tombstone、隔离进程日志。共享 UID 可能包含同 UID 的其他包崩溃；卸载重装后需重启采集。READY 仅表示采集进程已启动。"
    )
    parser.add_argument("--task", required=True, help="任务 id，例如 BUG-12345；精确匹配消息中的 [TEMP:BUG-12345]")
    parser.add_argument("--package", required=True, help="目标 Android applicationId")
    parser.add_argument("--serial", help="已确认的设备序列号；必须与当前 ANDROID_SERIAL 一致，未绑定时可显式指定")
    parser.add_argument("--output", default=default_output_directory(), help="日志父目录；默认用户缓存 forge-android/logcat，每次创建私有会话目录")
    parser.add_argument("--max-bytes", type=int, default=50 * 1024 * 1024, help="日志文件最大字节数，默认 50 MiB")
    parser.add_argument("--adb", default="adb", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.max_bytes <= 0:
        parser.error("--max-bytes 必须大于 0")
    if not re.fullmatch(r'[A-Z0-9]+(?:-[A-Z0-9]+)*', args.task):
        parser.error('--task 必须为大写字母/数字，以连字符分隔')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+', args.package):
        parser.error('--package 必须为实际 Android applicationId')
    return args


if __name__ == "__main__":
    sys.exit(run(parse_args()))
