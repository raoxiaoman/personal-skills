import { expect, test, mock } from 'claude-code/testing'
const event = { origin: { kind: 'composer' as const }, presentation: { isFullscreen: false, columns: 120 } }
const ready = { workspace: '/tmp/worktree with space', title: '验证', command: 'printf ok', prompt: '' }

test('本地 next 只执行一次，并使用任务工作区', async ($, on) => {
  mock.clock(on)
  let calls = 0
  let command = ''
  on('tool.call', (_, e) => { calls++; command = String(e.tool === 'Bash' ? e.command : ''); return { result: {}, text: 'ok' } })
  await $.tool.call({ tool: 'mcp__task-shortcuts__prepare', ...ready })
  const first = await $.command.run({ ...event, command: 'next', args: '' })
  expect(first.text).toBe('ok')
  expect(command.includes("cd '/tmp/worktree with space'")).toBe(true)
  const second = await $.command.run({ ...event, command: 'next', args: '' })
  expect(second.text?.includes('正在根据上下文')).toBe(true)
  expect(calls).toBe(1)
})

test('changes 用预备 worktree 且不消耗 next', async ($, on) => {
  mock.clock(on)
  let command = ''
  on('tool.call', (_, e) => { command = String(e.tool === 'Bash' ? e.command : ''); return { result: {}, text: 'opened' } })
  await $.tool.call({ tool: 'mcp__task-shortcuts__prepare', ...ready })
  await $.command.run({ ...event, command: 'changes', args: '' })
  expect(command.includes("'/tmp/worktree with space'")).toBe(true)
  expect((await $.command.run({ ...event, command: 'next', args: '' })).text).toBe('opened')
})

test('没有缓存时不猜工作区和动作', async ($, on) => {
  mock.clock(on)
  let calls = 0
  on('tool.call', () => { calls++; return { result: {} } })
  expect((await $.command.run({ ...event, command: 'next', args: '' })).text?.includes('正在根据上下文')).toBe(true)
  expect((await $.command.run({ ...event, command: 'changes', args: '' })).text?.includes('正在定位')).toBe(true)
  expect(calls).toBe(0)
})

test('prepare 接收扁平参数，不执行命令', async ($, on) => {
  mock.clock(on)
  on('tool.call', () => ({ result: {}, text: 'opened' }))
  await $.tool.call({ tool: 'mcp__task-shortcuts__prepare', ...ready })
  expect((await $.command.run({ ...event, command: 'changes', args: '' })).text).toBeDefined()
  const bad = await $.tool.call({ tool: 'mcp__task-shortcuts__prepare', ...ready, prompt: '继续' })
  expect(!!bad.deny).toBe(true)
})

test('命令里的路径正确处理单引号', async ($, on) => {
  mock.clock(on)
  let command = ''
  on('tool.call', (_, e) => { command = String(e.tool === 'Bash' ? e.command : ''); return { result: {} } })
  await $.command.run({ ...event, command: 'changes', args: "/tmp/a'b" })
  expect(command.includes("'/tmp/a'\\''b'")).toBe(true)
})

test('新用户指令使动作失效但保留工作区', async ($, on) => {
  mock.clock(on)
  on('prompt.submit', (_, e) => ({ text: e.text }))
  on('tool.call', () => ({ result: {}, text: 'opened' }))
  await $.tool.call({ tool: 'mcp__task-shortcuts__prepare', ...ready })
  await $.prompt.submit({ text: '改做另一个方案', wait: false, origin: { kind: 'composer' } })
  expect((await $.command.run({ ...event, command: 'next', args: '' })).text?.includes('正在根据上下文')).toBe(true)
  expect((await $.command.run({ ...event, command: 'changes', args: '' })).text).toBe('opened')
})

test('需要模型时提交预备请求，不执行 Bash', async ($, on) => {
  const clock = mock.clock(on)
  let prompt = ''
  let calls = 0
  on('prompt.submit', (_, e) => { prompt = e.text; return { text: e.text } })
  on('tool.call', () => { calls++; return { result: {} } })
  await $.tool.call({ tool: 'mcp__task-shortcuts__prepare', ...ready, command: '', prompt: '继续修复并验证' })
  const result = await $.command.run({ ...event, command: 'next', args: '' })
  expect(result.text?.includes('需要模型')).toBe(true)
  await clock.advance(0)
  expect(prompt.includes('继续修复并验证')).toBe(true)
  expect(calls).toBe(0)
})

test('Bash 被权限拒绝后不绕过、不重复执行', async ($, on) => {
  mock.clock(on)
  let calls = 0
  on('tool.call', () => { calls++; return { deny: '权限拒绝' } })
  await $.tool.call({ tool: 'mcp__task-shortcuts__prepare', ...ready })
  expect((await $.command.run({ ...event, command: 'next', args: '' })).text).toBe('权限拒绝')
  expect((await $.command.run({ ...event, command: 'next', args: '' })).text?.includes('正在根据上下文')).toBe(true)
  expect(calls).toBe(1)
})

test('--merge-back 无缓存授权传给执行器，兼容 --push 两种顺序且只执行一次', async ($, on) => {
  const clock = mock.clock(on)
  const input = { workspace: ready.workspace, files: ['a'], message: 'test: 分支合回', kind: 'other' as const, bugId: '', verified: true, remote: 'origin', remoteBranch: 'master' }
  let prompt = ''
  let command = ''
  let calls = 0
  let mergeBack = false
  on('prompt.submit', (_, e) => { prompt = e.text; return { text: e.text } })
  on('process.run', (_, e) => {
    mergeBack = JSON.parse(e.argv[3]).mergeBack
    return { value: { exitCode: 0, stdout: JSON.stringify({ ...input, mergeBack, push: { remote: 'origin', branch: 'master', url: '/tmp/remote' } }), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('tool.call', (_, e) => { calls++; command = e.tool === 'Bash' ? e.command : ''; return { result: {}, text: 'done' } })
  for (const args of ['--merge-back --push', '--push --merge-back']) {
    await $.command.run({ ...event, command: 'commit', args })
    await clock.advance(0)
    expect(prompt.includes(args)).toBe(true)
    expect(prompt.includes('不要提前切换分支')).toBe(true)
    await $.tool.call({ tool: 'mcp__task-shortcuts__prepare_commit', ...input })
    expect(mergeBack).toBe(true)
    expect(command.endsWith(' --merge-back --push')).toBe(true)
  }
  expect(calls).toBe(2)
  await $.tool.call({ tool: 'mcp__task-shortcuts__prepare_commit', ...input })
  expect(calls).toBe(2)
  expect(mergeBack).toBe(false)
})

test('--merge-back 不隐含推送，重复或未知参数不执行', async ($, on) => {
  const clock = mock.clock(on)
  const input = { workspace: ready.workspace, files: ['a'], message: 'test: 本地合回', kind: 'other' as const, bugId: '', verified: true, remote: '', remoteBranch: '' }
  let command = ''
  on('prompt.submit', (_, e) => ({ text: e.text }))
  on('process.run', () => ({ value: { exitCode: 0, stdout: JSON.stringify({ ...input, mergeBack: true, push: null }), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
  on('tool.call', (_, e) => { command = e.tool === 'Bash' ? e.command : ''; return { result: {}, text: 'done' } })
  for (const args of ['--merge-back --merge-back', '--push --push', '--merge-back --force']) {
    expect((await $.command.run({ ...event, command: 'commit', args })).text?.includes('用法')).toBe(true)
  }
  expect(command).toBe('')
  await $.command.run({ ...event, command: 'commit', args: '--merge-back' })
  await clock.advance(0)
  await $.tool.call({ tool: 'mcp__task-shortcuts__prepare_commit', ...input })
  expect(command.endsWith(' --merge-back')).toBe(true)
  expect(command.endsWith(' --push')).toBe(false)
})

test('commit 参数校验、显式推送和一次性执行', async ($, on) => {
  mock.clock(on)
  const plan = { workspace: '/tmp/worktree', files: ['a'], message: 'test: 提交', kind: 'other' as const, bugId: '', verified: true, remote: 'origin', remoteBranch: 'feature', push: { remote: 'origin', branch: 'feature', url: '/tmp/remote' } }
  let command = ''
  let calls = 0
  on('process.run', () => ({ value: { exitCode: 0, stdout: JSON.stringify(plan), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
  on('tool.call', (_, e) => { calls++; command = e.tool === 'Bash' ? e.command : ''; return { result: {}, text: 'done' } })
  await $.tool.call({ tool: 'mcp__task-shortcuts__prepare_commit', ...plan })
  expect((await $.command.run({ ...event, command: 'commit', args: '--force' })).text?.includes('用法')).toBe(true)
  expect(calls).toBe(0)
  expect((await $.command.run({ ...event, command: 'commit', args: '--push' })).text).toBe('done')
  expect(command.endsWith(' --push')).toBe(true)
  expect((await $.command.run({ ...event, command: 'commit', args: '' })).text?.includes('正在准备')).toBe(true)
  expect(calls).toBe(1)
})

test('未预备远端不推送，本地提交不带 push 参数', async ($, on) => {
  mock.clock(on)
  const plan = { workspace: '/tmp/worktree', files: ['a'], message: 'test: 提交', kind: 'other' as const, bugId: '', verified: true, remote: '', remoteBranch: '', push: null }
  let command = ''
  on('process.run', () => ({ value: { exitCode: 0, stdout: JSON.stringify(plan), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
  on('tool.call', (_, e) => { command = e.tool === 'Bash' ? e.command : ''; return { result: {}, text: 'done' } })
  await $.tool.call({ tool: 'mcp__task-shortcuts__prepare_commit', ...plan })
  expect((await $.command.run({ ...event, command: 'commit', args: '--push' })).text?.includes('未预备推送')).toBe(true)
  expect(command).toBe('')
  await $.command.run({ ...event, command: 'commit', args: '' })
  expect(command.endsWith(' --push')).toBe(false)
})

test('启动时不重复注册内置 commit，两个准备工具正常注册', async ($, on) => {
  mock.clock(on)
  on('command.list', () => ({ value: [] }))
  const commands: string[] = []
  const tools: string[] = []
  on('command.register', (_, e) => { commands.push(e.name); return { value: { command: e.name } } })
  on('tool.register', (_, e) => { tools.push(e.name); return { value: { tool: `mcp__task-shortcuts__${e.name}` } } })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  await $.session.start({ cwd: '/tmp', surface: 'terminal', isInteractive: true })
  expect(commands.includes('commit')).toBe(false)
  expect(commands.includes('next')).toBe(true)
  expect(tools.includes('prepare_commit')).toBe(true)
  expect(tools.includes('prepare')).toBe(true)
})

test('两个准备工具返回 MCP 可接受的字符串，不返回裸对象', async ($, on) => {
  mock.clock(on)
  const plan = { workspace: ready.workspace, branch: 'feature/test', files: ['a'], message: 'test: 验证', push: null }
  on('process.run', () => ({ value: { exitCode: 0, stdout: JSON.stringify(plan), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
  const next = await $.tool.call({ tool: 'mcp__task-shortcuts__prepare', ...ready })
  expect(typeof next.result).toBe('string')
  const commit = await $.tool.call({ tool: 'mcp__task-shortcuts__prepare_commit', workspace: ready.workspace, files: ['a'], message: plan.message, kind: 'other', bugId: '', verified: true, remote: '', remoteBranch: '' })
  expect(typeof commit.result).toBe('string')
})

test('commit 没有缓存时进入准备流程，而不是让用户自行准备', async ($, on) => {
  const clock = mock.clock(on)
  let prompt = ''
  let calls = 0
  on('prompt.submit', (_, e) => { prompt = e.text; return { text: e.text } })
  on('tool.call', () => { calls++; return { result: {} } })
  const result = await $.command.run({ ...event, command: 'commit', args: '--push' })
  expect(result.text?.includes('正在准备')).toBe(true)
  await clock.advance(0)
  expect(prompt.includes('prepare_commit')).toBe(true)
  expect(prompt.includes('--push')).toBe(true)
  expect(prompt.includes('无需用户再次输入')).toBe(true)
  expect(prompt.includes('execute')).toBe(true)
  expect(calls).toBe(0)
})

test('无缓存 commit 的授权只让下一次准备成功后执行一次', async ($, on) => {
  const clock = mock.clock(on)
  const input = { workspace: ready.workspace, files: ['a'], message: 'test: 单次提交', kind: 'other' as const, bugId: '', verified: true, remote: '', remoteBranch: '' }
  let calls = 0
  let command = ''
  on('prompt.submit', (_, e) => ({ text: e.text }))
  on('process.run', () => ({ value: { exitCode: 0, stdout: JSON.stringify({ ...input, push: null }), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
  on('tool.call', (_, e) => { calls++; command = e.tool === 'Bash' ? e.command : ''; return { result: {}, text: '本地提交成功：test-hash' } })
  await $.command.run({ ...event, command: 'commit', args: '' })
  await clock.advance(0)
  const result = await $.tool.call({ tool: 'mcp__task-shortcuts__prepare_commit', ...input })
  expect(result.result).toBe('本地提交成功：test-hash')
  expect(calls).toBe(1)
  expect(command.includes(' execute ')).toBe(true)
  expect(command.endsWith(' --push')).toBe(false)
  await $.tool.call({ tool: 'mcp__task-shortcuts__prepare_commit', ...input })
  expect(calls).toBe(1)
})

test('用户的新消息取消单次提交授权', async ($, on) => {
  const clock = mock.clock(on)
  let calls = 0
  const input = { workspace: ready.workspace, files: ['a'], message: 'test: 取消授权', kind: 'other' as const, bugId: '', verified: true, remote: '', remoteBranch: '' }
  on('prompt.submit', (_, e) => ({ text: e.text }))
  on('process.run', () => ({ value: { exitCode: 0, stdout: JSON.stringify({ ...input, push: null }), stderr: '', isStdoutTruncated: false, isStderrTruncated: false } }))
  on('tool.call', () => { calls++; return { result: {} } })
  await $.command.run({ ...event, command: 'commit', args: '' })
  await clock.advance(0)
  await $.prompt.submit({ text: '先不要提交', wait: false, origin: { kind: 'composer' } })
  await $.tool.call({ tool: 'mcp__task-shortcuts__prepare_commit', ...input })
  expect(calls).toBe(0)
})

test('changes 没有缓存时定位任务，不要求用户预备', async ($, on) => {
  const clock = mock.clock(on)
  let prompt = ''
  on('prompt.submit', (_, e) => { prompt = e.text; return { text: e.text } })
  const result = await $.command.run({ ...event, command: 'changes', args: '' })
  expect(result.text?.includes('正在定位')).toBe(true)
  await clock.advance(0)
  expect(prompt.includes('open_changes')).toBe(true)
  expect(prompt.includes('worktree')).toBe(true)
})

test('changes 支持用户引用的含空格路径', async ($, on) => {
  let command = ''
  on('tool.call', (_, e) => { command = e.tool === 'Bash' ? e.command : ''; return { result: {}, text: 'opened' } })
  await $.command.run({ ...event, command: 'changes', args: '"/tmp/work tree"' })
  expect(command.endsWith("'/tmp/work tree'")).toBe(true)
})

test('next 无缓存时自动按上下文续做但不扩大权限', async ($, on) => {
  const clock = mock.clock(on)
  let prompt = ''
  on('prompt.submit', (_, e) => { prompt = e.text; return { text: e.text } })
  await $.command.run({ ...event, command: 'next', args: '' })
  await clock.advance(0)
  expect(prompt.includes('最近一次明确推荐')).toBe(true)
  expect(prompt.includes('不再等待第二次')).toBe(true)
  expect(prompt.includes('不授权提交')).toBe(true)
})
