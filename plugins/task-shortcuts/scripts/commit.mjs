import { execFileSync } from 'node:child_process';
import { createHash, randomBytes } from 'node:crypto';
import { realpathSync, existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';

const helper = resolve(homedir(), '.claude/bin/safe-git-submit');
const fail = message => { throw new Error(message); };
const run = (args, cwd) => execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], maxBuffer: 32 * 1024 * 1024 });
const quiet = (args, cwd) => { try { return run(args, cwd).trim(); } catch { return ''; } };
const check = cwd => execFileSync(helper, ['--repo', cwd, '--check'], { encoding: 'utf8' });

export function snapshot(input) {
  if (!input || typeof input.workspace !== 'string' || !input.workspace.startsWith('/')) fail('需要绝对工作区路径');
  const workspace = realpathSync(input.workspace);
  check(workspace);
  if (realpathSync(run(['rev-parse', '--show-toplevel'], workspace).trim()) !== workspace) fail('必须指定工作区根目录');
  const branch = run(['symbolic-ref', '--short', 'HEAD'], workspace).trim();
  const defaultBranch = quiet(['symbolic-ref', '--short', 'refs/remotes/origin/HEAD'], workspace).replace(/^origin\//, '');
  const isDefault = ['main', 'master', defaultBranch].includes(branch);
  const mergeBack = input.mergeBack === true;
  if (isDefault && !mergeBack) fail('当前为默认分支；请切换工作分支，或使用 /commit --merge-back');
  if (mergeBack && !isDefault) fail('--merge-back 仅支持从默认分支创建工作分支并合回');
  let workBranch = null;
  if (mergeBack) {
    if (run(['diff', '--name-only'], workspace)) fail('--merge-back 要求没有未暂存改动');
    if (run(['ls-files', '--others', '--exclude-standard'], workspace)) fail('--merge-back 要求没有未跟踪文件');
    workBranch = input.workBranch ?? `commit/${branch}-${new Date().toISOString().slice(0, 10).replaceAll('-', '')}-${randomBytes(4).toString('hex')}`;
    if (typeof workBranch !== 'string' || !workBranch.startsWith('commit/')) fail('工作分支名无效');
    run(['check-ref-format', `refs/heads/${workBranch}`], workspace);
    if (quiet(['show-ref', '--verify', `refs/heads/${workBranch}`], workspace)) fail('工作分支已存在；停止，不复用已有分支');
  }
  if (run(['ls-files', '-u'], workspace)) fail('存在未解决冲突');
  for (const marker of ['MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD']) {
    if (quiet(['rev-parse', '--verify', marker], workspace)) fail('存在未完成的 Git 操作');
  }
  for (const marker of ['rebase-merge', 'rebase-apply', 'sequencer']) {
    if (existsSync(resolve(workspace, run(['rev-parse', '--git-path', marker], workspace).trim()))) fail('存在未完成的 Git 操作');
  }
  const files = run(['diff', '--cached', '--name-only', '--no-renames', '-z'], workspace).split('\0').filter(Boolean).sort();
  if (!files.length) fail('没有明确暂存的文件；请先核对并逐项暂存预备清单，不自动全量 add');
  if (!Array.isArray(input.files) || input.files.some(f => typeof f !== 'string') ||
      JSON.stringify([...input.files].sort()) !== JSON.stringify(files)) fail('暂存文件与预备清单不一致');
  if (typeof input.message !== 'string' || !/[㐀-鿿]/u.test(input.message) || /Co-Authored-By:/i.test(input.message)) fail('提交信息须含中文，且不得含 Co-Authored-By');
  if (!['bug', 'other'].includes(input.kind)) fail('需要明确提交类型');
  if (input.kind === 'bug' && (!input.bugId || !input.message.includes(input.bugId))) fail('修复 Bug 必须确认并在提交信息中保留原编号');
  if (input.verified !== true) fail('尚未确认所需验证完成');
  const head = run(['rev-parse', 'HEAD'], workspace).trim();
  const tree = run(['write-tree'], workspace).trim();
  const status = run(['status', '--porcelain=v1', '-uall'], workspace);
  const diff = run(['diff', '--binary', '--no-ext-diff', '--no-textconv'], workspace);
  const workingFingerprint = createHash('sha256').update(diff).update(run(['ls-files', '--others', '--exclude-standard', '-z'], workspace)).digest('hex');
  const fingerprint = createHash('sha256').update(JSON.stringify({ head, branch, tree, status, diff, mergeBack, workBranch })).digest('hex');
  let push = null;
  if (input.remote || input.remoteBranch) {
    if (!input.remote || !input.remoteBranch || input.remote.startsWith('-') || input.remoteBranch.startsWith('-')) fail('推送需同时明确 remote 和远端分支');
    run(['check-ref-format', `refs/heads/${input.remoteBranch}`], workspace);
    const urls = run(['remote', 'get-url', '--push', '--all', input.remote], workspace).trim().split('\n');
    if (urls.length !== 1 || !urls[0] || urls[0].startsWith('-')) fail('只支持单一、明确的推送目标');
    push = { remote: input.remote, branch: input.remoteBranch, url: urls[0] };
  }
  return { ...input, workspace, branch, head, tree, fingerprint, workingFingerprint, files, push, mergeBack, workBranch };
}

function remoteHead(p) {
  const rows = run(['ls-remote', '--heads', p.push.url, `refs/heads/${p.push.branch}`], p.workspace).trim();
  return rows ? rows.split(/\s/)[0] : '';
}

export function execute(p, push) {
  const current = snapshot(p);
  if (current.fingerprint !== p.fingerprint || JSON.stringify(current.push) !== JSON.stringify(p.push)) fail('预备后 Git 内容、分支或推送目标发生变化，请重新准备');
  if (push && !p.push) fail('未预备推送目标；仅能 /commit，或先明确 remote 和分支');
  // 只推本次提交，不把未展示的历史提交一起发布；不自动 fetch/rebase。
  if (push && remoteHead(p) !== p.head) fail('远端分支不存在或与预备 HEAD 不一致；停止，请人工确认同步和推送范围');
  console.log(`工作区：${p.workspace}\n分支：${p.branch}\n暂存清单：\n${p.files.join('\n')}\n提交信息：${p.message}`);
  const latest = snapshot(p);
  if (latest.fingerprint !== p.fingerprint) fail('提交前状态变化，停止');
  if (p.mergeBack) {
    console.log(`工作分支：${p.workBranch}；提交后仅快进合回 ${p.branch}，保留工作分支`);
    run(['switch', '-c', p.workBranch], p.workspace);
    if (run(['rev-parse', 'HEAD'], p.workspace).trim() !== p.head ||
        run(['symbolic-ref', '--short', 'HEAD'], p.workspace).trim() !== p.workBranch ||
        run(['write-tree'], p.workspace).trim() !== p.tree ||
        run(['diff', '--name-only'], p.workspace) ||
        run(['ls-files', '--others', '--exclude-standard'], p.workspace)) fail('创建工作分支后状态变化；保留现场，未提交');
  }
  execFileSync(helper, ['--repo', p.workspace, '--commit', p.message], { stdio: 'inherit' });
  const sha = run(['rev-parse', 'HEAD'], p.workspace).trim();
  console.log(`本地提交成功：${sha}`);
  if (p.mergeBack) {
    if (run(['rev-parse', 'HEAD^'], p.workspace).trim() !== p.head ||
        run(['rev-parse', 'HEAD^{tree}'], p.workspace).trim() !== p.tree ||
        run(['symbolic-ref', '--short', 'HEAD'], p.workspace).trim() !== p.workBranch ||
        run(['status', '--porcelain=v1', '--untracked-files=normal'], p.workspace)) fail('提交已完成，但合并前状态变化；保留工作分支和提交，未合并、未推送');
    if (run(['rev-parse', `refs/heads/${p.branch}`], p.workspace).trim() !== p.head) fail('提交已完成，但原分支已变化；未合并、未推送');
    run(['switch', p.branch], p.workspace);
    if (run(['rev-parse', 'HEAD'], p.workspace).trim() !== p.head ||
        run(['symbolic-ref', '--short', 'HEAD'], p.workspace).trim() !== p.branch ||
        run(['status', '--porcelain=v1', '--untracked-files=normal'], p.workspace)) fail('返回原分支后状态变化；未合并、未推送');
    run(['merge', '--ff-only', sha], p.workspace);
    if (run(['rev-parse', 'HEAD'], p.workspace).trim() !== sha ||
        run(['symbolic-ref', '--short', 'HEAD'], p.workspace).trim() !== p.branch ||
        run(['status', '--porcelain=v1', '--untracked-files=normal'], p.workspace)) fail('合并后状态异常；保留现场，未推送');
    console.log(`已快进合并回 ${p.branch}：${sha}；工作分支 ${p.workBranch} 已保留`);
  }
  if (!push) return;
  // commit hook 可能改变内容或另建提交；推送前再次确认实际提交。
  if (run(['rev-parse', 'HEAD^'], p.workspace).trim() !== p.head ||
      run(['rev-parse', 'HEAD^{tree}'], p.workspace).trim() !== p.tree ||
      run(['symbolic-ref', '--short', 'HEAD'], p.workspace).trim() !== p.branch ||
      run(['diff', '--cached', '--name-only'], p.workspace).trim() ||
      run(['rev-parse', 'HEAD'], p.workspace).trim() !== sha ||
      run(['remote', 'get-url', '--push', '--all', p.push.remote], p.workspace).trim() !== p.push.url ||
      createHash('sha256').update(run(['diff', '--binary', '--no-ext-diff', '--no-textconv'], p.workspace)).update(run(['ls-files', '--others', '--exclude-standard', '-z'], p.workspace)).digest('hex') !== p.workingFingerprint ||
      remoteHead(p) !== p.head) fail('提交已完成，但推送前状态变化；未推送，请人工检查');
  execFileSync('git', ['-c', 'push.followTags=false', 'push', '--no-follow-tags', p.push.url, `${sha}:refs/heads/${p.push.branch}`], { cwd: p.workspace, stdio: 'inherit' });
  console.log(`已推送：${p.push.remote}/${p.push.branch}（非强制推送）`);
}

if (process.argv[1] && realpathSync(process.argv[1]) === realpathSync(new URL(import.meta.url))) {
  try {
    const [mode, payload, ...options] = process.argv.slice(2);
    if (!['prepare', 'execute'].includes(mode) || new Set(options).size !== options.length ||
        options.some(option => !['--push', '--merge-back'].includes(option))) fail('不支持的参数');
    const input = JSON.parse(payload);
    if (mode === 'prepare') console.log(JSON.stringify(snapshot({ ...input, mergeBack: options.includes('--merge-back') || input.mergeBack === true })));
    else {
      if ((input.mergeBack === true) !== options.includes('--merge-back')) fail('合回原分支必须由本次 /commit --merge-back 显式授权');
      execute(input, options.includes('--push'));
    }
  } catch (error) {
    console.error(`停止：${error.message}`);
    process.exitCode = 1;
  }
}
