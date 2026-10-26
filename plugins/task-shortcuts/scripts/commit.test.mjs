import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, mkdirSync, chmodSync } from 'node:fs';
import { tmpdir, homedir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { snapshot, execute } from './commit.mjs';
const helper = join(homedir(), '.claude/bin/safe-git-submit');
const git = (cwd, ...args) => execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'commit-shortcuts-'));
  const cwd = join(root, 'work tree'); mkdirSync(cwd);
  git(cwd, 'init', '-b', 'feature/test');
  git(cwd, 'config', 'user.name', 'Test'); git(cwd, 'config', 'user.email', 'test@example.invalid');
  writeFileSync(join(cwd, 'one.txt'), 'base\n'); git(cwd, 'add', '--', 'one.txt');
  execFileSync(helper, ['--repo', cwd, '--commit', 'test: 初始提交'], { stdio: 'pipe' });
  const bare = join(root, 'remote.git'); git(root, 'init', '--bare', bare);
  git(cwd, 'remote', 'add', 'origin', bare); git(cwd, 'push', '-u', 'origin', 'feature/test');
  writeFileSync(join(cwd, 'one.txt'), 'changed\n'); git(cwd, 'add', '--', 'one.txt');
  const input = { workspace: cwd, files: ['one.txt'], message: 'test: 验证提交入口', kind: 'other', bugId: '', verified: true, remote: 'origin', remoteBranch: 'feature/test' };
  return { cwd, bare, input };
}
function defaultFixture(branch = 'master') {
  const f = fixture();
  git(f.cwd, 'branch', '-m', branch);
  git(f.cwd, 'push', 'origin', branch);
  return { ...f, input: { ...f.input, remoteBranch: branch, mergeBack: true } };
}
function hook(cwd, name, body) {
  const path = join(cwd, '.git/hooks', name);
  writeFileSync(path, '#!/bin/sh\n' + body + '\n');
  chmodSync(path, 0o755);
}
test('--merge-back 从 master 创建分支、提交并快进返回，不推送、不删分支', () => {
  const { cwd, bare, input } = defaultFixture();
  assert.throws(() => snapshot({ ...input, mergeBack: false }), /默认分支/);
  const plan = snapshot(input);
  assert.equal(git(cwd, 'branch', '--show-current'), 'master');
  execute(plan, false);
  assert.equal(git(cwd, 'branch', '--show-current'), 'master');
  assert.equal(git(cwd, 'rev-parse', 'HEAD^'), plan.head);
  assert.equal(git(cwd, 'rev-parse', 'HEAD^{tree}'), plan.tree);
  assert.equal(git(cwd, 'rev-parse', plan.workBranch), git(cwd, 'rev-parse', 'HEAD'));
  assert.equal(git(bare, 'rev-parse', 'refs/heads/master'), plan.head);
  assert.equal(git(cwd, 'status', '--porcelain'), '');
});
test('--merge-back --push 只推本次提交到原 main', () => {
  const { cwd, bare, input } = defaultFixture('main');
  execute(snapshot(input), true);
  assert.equal(git(cwd, 'branch', '--show-current'), 'main');
  assert.equal(git(cwd, 'rev-parse', 'HEAD'), git(bare, 'rev-parse', 'refs/heads/main'));
});
test('--merge-back 拒绝功能分支、未暂存和未跟踪内容', () => {
  const f = fixture();
  assert.throws(() => snapshot({ ...f.input, mergeBack: true }), /默认分支/);
  const { cwd, input } = defaultFixture();
  writeFileSync(join(cwd, 'one.txt'), 'unstaged\n');
  assert.throws(() => snapshot(input), /未暂存/);
  git(cwd, 'add', '--', 'one.txt');
  writeFileSync(join(cwd, 'other.txt'), 'untracked\n');
  assert.throws(() => snapshot(input), /未跟踪/);
  assert.equal(git(cwd, 'branch', '--show-current'), 'master');
});
test('--merge-back 预备后变化或工作分支重名时停止，不切换', () => {
  const { cwd, input } = defaultFixture();
  const plan = snapshot(input);
  git(cwd, 'branch', plan.workBranch);
  assert.throws(() => execute(plan, false), /已存在/);
  assert.equal(git(cwd, 'branch', '--show-current'), 'master');
  const second = snapshot(input);
  writeFileSync(join(cwd, 'one.txt'), 'changed again\n'); git(cwd, 'add', '--', 'one.txt');
  assert.throws(() => execute(second, false), /变化/);
});
test('--merge-back 提交失败保留工作分支和暂存，不合并或重试', () => {
  const { cwd, input } = defaultFixture(); const plan = snapshot(input);
  hook(cwd, 'pre-commit', 'exit 1');
  assert.throws(() => execute(plan, false));
  assert.equal(git(cwd, 'branch', '--show-current'), plan.workBranch);
  assert.equal(git(cwd, 'rev-parse', 'master'), plan.head);
  assert.equal(git(cwd, 'diff', '--cached', '--name-only'), 'one.txt');
});
test('--merge-back 提交 hook 留下改动时保留提交，不合并', () => {
  const { cwd, input } = defaultFixture(); const plan = snapshot(input);
  hook(cwd, 'post-commit', 'printf dirty >> one.txt');
  assert.throws(() => execute(plan, false), /合并前/);
  assert.equal(git(cwd, 'branch', '--show-current'), plan.workBranch);
  assert.equal(git(cwd, 'rev-parse', 'master'), plan.head);
  assert.notEqual(git(cwd, 'rev-parse', 'HEAD'), plan.head);
});
test('--merge-back 原分支被 hook 推进时停止，不自动重置', () => {
  const { cwd, input } = defaultFixture(); const plan = snapshot(input);
  hook(cwd, 'post-commit', 'git update-ref refs/heads/master HEAD');
  assert.throws(() => execute(plan, false), /原分支/);
  assert.equal(git(cwd, 'branch', '--show-current'), plan.workBranch);
});
test('--merge-back --push 远端不同步时不建分支或提交', () => {
  const { cwd, input } = defaultFixture();
  git(cwd, 'remote', 'set-url', '--push', 'origin', input.workspace);
  const plan = snapshot({ ...input, remoteBranch: 'missing' });
  assert.throws(() => execute(plan, true), /远端分支/);
  assert.equal(git(cwd, 'branch', '--show-current'), 'master');
  assert.equal(git(cwd, 'rev-parse', 'HEAD'), plan.head);
});
test('CLI execute 要求显式 --merge-back；授权后真实执行且不推送', () => {
  const { cwd, bare, input } = defaultFixture(); const plan = snapshot(input);
  const script = new URL('./commit.mjs', import.meta.url).pathname;
  assert.throws(() => execFileSync(process.execPath, [script, 'execute', JSON.stringify(plan)], { stdio: 'pipe' }), /显式授权/);
  assert.equal(git(cwd, 'rev-parse', 'HEAD'), plan.head);
  const output = execFileSync(process.execPath, [script, 'execute', JSON.stringify(plan), '--merge-back'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
  assert.match(output, /已快进合并回 master/);
  assert.equal(git(cwd, 'branch', '--show-current'), 'master');
  assert.equal(git(bare, 'rev-parse', 'refs/heads/master'), plan.head);
});
test('只提交预备暂存区，默认不推送', () => {
  const { cwd, bare, input } = fixture(); const plan = snapshot(input);
  execute(plan, false);
  assert.notEqual(git(cwd, 'rev-parse', 'HEAD'), plan.head);
  assert.equal(git(bare, 'rev-parse', 'refs/heads/feature/test'), plan.head);
  assert.throws(() => execute(plan, false));
});
test('--push 仅将本次提交推送到指定分支', () => {
  const { cwd, bare, input } = fixture(); execute(snapshot(input), true);
  assert.equal(git(cwd, 'rev-parse', 'HEAD'), git(bare, 'rev-parse', 'refs/heads/feature/test'));
});
test('暂存内容变化、清单错配、验证缺失和 Bug 编号缺失均阻断', () => {
  const { cwd, input } = fixture(); const plan = snapshot(input);
  assert.throws(() => snapshot({ ...input, files: ['other.txt'] }), /清单/);
  assert.throws(() => snapshot({ ...input, verified: false }), /验证/);
  assert.throws(() => snapshot({ ...input, kind: 'bug' }), /编号/);
  writeFileSync(join(cwd, 'one.txt'), 'new change\n'); git(cwd, 'add', '--', 'one.txt');
  assert.throws(() => execute(plan, false), /发生变化/);
  assert.equal(git(cwd, 'rev-parse', 'HEAD'), plan.head);
});
test('本地有未展示的历史提交时不允许顺带推送', () => {
  const { cwd, input } = fixture(); execute(snapshot(input), false);
  writeFileSync(join(cwd, 'one.txt'), 'another\n'); git(cwd, 'add', '--', 'one.txt');
  const plan = snapshot(input);
  assert.throws(() => execute(plan, true), /远端分支/);
  assert.equal(git(cwd, 'rev-parse', 'HEAD'), plan.head);
});
test('默认分支不自动提交，远端目标变化不执行', () => {
  const { cwd, input } = fixture(); const plan = snapshot(input);
  git(cwd, 'remote', 'set-url', '--push', 'origin', '/tmp/unexpected-remote');
  assert.throws(() => execute(plan, true), /发生变化/);
  git(cwd, 'branch', '-m', 'main');
  assert.throws(() => snapshot(input), /默认分支/);
});
