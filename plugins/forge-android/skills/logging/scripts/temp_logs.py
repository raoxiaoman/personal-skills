#!/usr/bin/env python3
"""Delete explicitly managed Java/Kotlin diagnostic blocks, never arbitrary log lines."""
import argparse
import difflib
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

TASK = re.compile(r"[A-Z0-9]+(?:-[A-Z0-9]+)*\Z")
MARKER = re.compile(r"^[ \t]*// TEMP-LOG-(BEGIN|END) ([A-Z0-9]+(?:-[A-Z0-9]+)*)[ \t]*$")
SKIP = {'.git', '.gradle', '.idea', 'build', 'out', 'node_modules', 'vendor', '.venv', '__pycache__'}


def scan(root):
    files, skipped = [], []

    def fail_walk(error):
        raise error

    for directory, dirs, names in os.walk(root, followlinks=False, onerror=fail_walk):
        for name in list(dirs):
            path = Path(directory) / name
            if name in SKIP or path.is_symlink():
                skipped.append(str(path.relative_to(root)))
                dirs.remove(name)
        for name in sorted(names):
            path = Path(directory) / name
            if path.suffix not in {'.java', '.kt', '.kts'}:
                continue
            if path.is_symlink():
                skipped.append(str(path.relative_to(root)))
                continue
            if not path.is_file():
                continue
            files.append(path)
    return sorted(files), skipped


def parse(data, path):
    text = data.decode('utf-8')
    lines = text.splitlines(keepends=True)
    blocks, errors, active = [], [], None
    for index, line in enumerate(lines):
        plain = line.rstrip('\r\n')
        match = MARKER.fullmatch(plain)
        if not match:
            if plain.lstrip().startswith('// TEMP-LOG-'):
                errors.append(f'{path}:{index + 1}: malformed marker')
            continue
        kind, task = match.groups()
        if kind == 'BEGIN':
            if active:
                errors.append(f'{path}:{index + 1}: nested block')
            else:
                active = (task, index)
        elif not active or active[0] != task:
            errors.append(f'{path}:{index + 1}: unmatched END {task}')
        else:
            blocks.append((task, active[1], index + 1))
            active = None
    if active:
        errors.append(f'{path}:{active[1] + 1}: unclosed block {active[0]}')
    return lines, blocks, errors


def identifier_pattern(task):
    # BUG-1 must not accidentally include BUG-10 or BUG-1-OTHER.
    return re.compile(r'(?<![A-Z0-9-])' + re.escape(task) + r'(?![A-Z0-9-])')


def inspect(root, task=None):
    files, skipped = scan(root)
    records, errors = [], []
    for path in files:
        try:
            data = path.read_bytes()
            lines, blocks, problems = parse(data, path.relative_to(root))
        except (OSError, UnicodeError) as exc:
            errors.append(f'{path}: cannot inspect: {exc}')
            continue
        errors.extend(problems)
        selected = [block for block in blocks if task is None or block[0] == task]
        removed = {i for _, begin, end in selected for i in range(begin, end)}
        remaining = ''.join(line for i, line in enumerate(lines) if i not in removed)
        unmanaged = []
        if task:
            pattern = identifier_pattern(task)
            unmanaged = [i + 1 for i, line in enumerate(lines) if i not in removed and pattern.search(line)]
        records.append((path, data, remaining.encode('utf-8'), selected, unmanaged))
    return records, skipped, errors


def apply_changes(changes):
    # Preflight all files; recheck each just before replacement as well.
    for path, before, _ in changes:
        if path.is_symlink() or path.read_bytes() != before:
            raise RuntimeError(f'{path}: changed since inspection; refusing')
    applied = []
    try:
        for path, before, after in changes:
            if path.is_symlink() or path.read_bytes() != before:
                raise RuntimeError(f'{path}: changed since inspection; refusing')
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise RuntimeError(f'{path}: not a regular single-link file')
            fd, temporary = tempfile.mkstemp(prefix='.temp-logs-', dir=path.parent)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(after)
                    stream.flush()
                    os.fsync(stream.fileno())
                    os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode))
                if path.is_symlink() or path.read_bytes() != before:
                    raise RuntimeError(f'{path}: changed before replacement; refusing')
                os.replace(temporary, path)
                applied.append(path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
    except (OSError, RuntimeError) as exc:
        raise RuntimeError(f'{exc}; already applied: {[str(p) for p in applied]}') from exc
    return applied


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('list', 'clean', 'verify'):
        command = sub.add_parser(name)
        if name != 'list':
            command.add_argument('task')
        command.add_argument('--root', type=Path, help='Source root; default: current git worktree root')
        if name == 'clean':
            command.add_argument('--apply', action='store_true', help='Apply the displayed deletions (default: preview only)')
    args = parser.parse_args(argv)
    task = getattr(args, 'task', None)
    if task and not TASK.fullmatch(task):
        parser.error('task must contain uppercase letters/digits separated by hyphens')
    if args.root is None:
        result = subprocess.run(['git', 'rev-parse', '--show-toplevel'], text=True, capture_output=True)
        if result.returncode:
            parser.error('not in a git worktree; specify --root')
        root = Path(result.stdout.strip()).resolve()
    else:
        if args.root.is_symlink():
            parser.error('--root must not be a symlink')
        root = args.root.resolve()
    if not root.is_dir():
        parser.error('--root must be a directory')
    print(f'Root: {root}\nScope: .java/.kt/.kts UTF-8 files; no symlinks; excluded directories: {", ".join(sorted(SKIP))}')
    records, skipped, errors = inspect(root, task)
    for path in skipped:
        print(f'SKIP {path}')
    changes, found = [], False
    for path, before, after, blocks, unmanaged in records:
        relative = path.relative_to(root)
        for block_task, begin, end in blocks:
            print(f'BLOCK {block_task} {relative}:{begin + 1}-{end}')
            found = True
        for line in unmanaged:
            errors.append(f'{relative}:{line}: unmanaged reference to {task}; not deleting')
            found = True
        if before != after:
            changes.append((path, before, after))
            if args.command == 'clean':
                diff = difflib.unified_diff(before.decode('utf-8').splitlines(True), after.decode('utf-8').splitlines(True), fromfile=str(relative), tofile=str(relative))
                sys.stdout.writelines(diff)
    for error in errors:
        print(f'ERROR {error}', file=sys.stderr)
    if errors:
        print('No writes performed.', file=sys.stderr)
        return 2
    if args.command == 'verify':
        print('Residual managed blocks/references found.' if found else 'No task tag/id remains in the reported source scope; compilation not checked.')
        return 1 if found else 0
    if args.command == 'clean':
        if not args.apply:
            print(f'PREVIEW: {len(changes)} file(s); use --apply to delete these blocks.')
        else:
            applied = apply_changes(changes)
            print(f'APPLIED: {len(applied)} file(s).')
            remaining, _, problems = inspect(root, task)
            if problems or any(blocks or unmanaged for _, _, _, blocks, unmanaged in remaining):
                print('ERROR: post-clean verification failed; inspect remaining references.', file=sys.stderr)
                for problem in problems:
                    print(problem, file=sys.stderr)
                return 2
            print('Verified: no task tag/id remains in the reported source scope; compilation not checked.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, RuntimeError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(2)
