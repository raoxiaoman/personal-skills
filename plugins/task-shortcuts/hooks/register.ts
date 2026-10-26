import type { Register, ToolCallResult } from 'claude-code'
import type { Prepared } from '../types'
const ref = { plugin: 'task-shortcuts', key: 'prepared' } as const
const workspaceRef = { plugin: 'task-shortcuts', key: 'workspace' } as const
const intentRef = { plugin: 'task-shortcuts', key: 'commitIntent' } as const
const commitRef = { plugin: 'task-shortcuts', key: 'commit' } as const
const quote = (s: string) => "'" + s.replace(/'/g, "'\\''") + "'"
const output = (r: ToolCallResult) => r.deny ?? r.text ?? JSON.stringify(r.result)

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.tool.register({ name: 'open_changes', description: '在 Zed 打开已确定的任务工作区改动，不提交、不推进任务。传入已核实的绝对工作区路径。', inputSchema: { type: 'object', properties: { workspace: { type: 'string' } }, required: ['workspace'], additionalProperties: false } })
    await $.tool.register({ name: 'prepare_commit', description: '准备本会话提交；如果用户刚调用 /commit 触发无缓存流程，则消耗一次授权并立即提交，--push 同时推送。普通预备调用不执行。先核对文件、验证和目标。', inputSchema: { type: 'object', properties: { workspace: { type: 'string' }, files: { type: 'array', items: { type: 'string' } }, message: { type: 'string' }, kind: { type: 'string', enum: ['bug', 'other'] }, bugId: { type: 'string' }, verified: { type: 'boolean' }, remote: { type: 'string' }, remoteBranch: { type: 'string' } }, required: ['workspace', 'files', 'message', 'kind', 'bugId', 'verified', 'remote', 'remoteBranch'], additionalProperties: false } })
    const existing = await $.command.list()
    if (!existing.some(c => c.name === 'next')) await $.command.register({ name: 'next', description: '执行已准备的下一步，不重新理解上下文' })
    if (!existing.some(c => c.name === 'changes')) await $.command.register({ name: 'changes', description: '直接在 Zed 查看任务工作区', argumentHint: '[绝对路径]' })
    await $.tool.register({
      name: 'prepare',
      description: '预备本会话工作区与向用户明确推荐的下一步，不执行。command 与 prompt 二选一，仅记录工作区时均为空。不得准备提交、推送、删除、发布或覆盖数据。',
      inputSchema: { type: 'object', properties: {
        workspace: { type: 'string' }, title: { type: 'string' }, command: { type: 'string' }, prompt: { type: 'string' }
      }, required: ['workspace', 'title', 'command', 'prompt'], additionalProperties: false }
    })
    return next(e)
  })
  on('prompt.compose', async ($, e, next) => {
    const result = await next(e)
    return { ...result, sections: [...result.sections, {
      id: 'task-shortcuts:prepare', scope: 'session' as const,
      text: '用户要求查看改动且缺少缓存时，从任务上下文和实际操作文件定位，再调用 mcp__task-shortcuts__open_changes，不要求先预备，不扫描哪个 worktree 有改动来猜目标，不覆盖 next。任务工作区明确或改变时用 mcp__task-shortcuts__prepare 记录绝对路径，不使用 session 启动目录猜测 worktree。交付前如推荐下一步，用此工具提前记录并向用户明确展示动作及工作区。确定性验证/打包/安装/启动用 command（正确引用路径、失败即停；Android 设备必须明确绑定，执行前校验当前绑定仍匹配，不能沿用历史序列号），继续分析/写代码用 prompt，两者只能一个非空。没有下一步则均为空。不得准备提交/推送/删除/发布/覆盖用户数据。新任务提示使待执行动作失效，交付前重新准备。只讨论方案或改写文字时不要准备可执行命令。提交用独立 prepare_commit 工具，不放进 next。准备提交前确认所需验证（含用户验收）完成、已获暂存授权，核对逐项暂存的清单，中文信息以及修复 Bug 的原编号；不能全量 add。工作区、文件清单、提交信息、验证情况和可选推送 remote/分支需在交付中明确展示。用户调用 /commit 才授权本地提交，--push 才授权同时推送；/commit --merge-back 额外授权执行器从默认分支自动建工作分支、提交并仅快进合回原分支，保留工作分支；模型不要提前切分支或另行合并。只支持已存在且与当前 HEAD 一致的远端分支，避免带出其他历史提交；未带 --merge-back 时默认分支仍须先明确切换工作分支，不自行切换。'
    }] }
  })
  on('tool.call', { tool: 'mcp__task-shortcuts__prepare_commit' }, async ($, e) => {
    const intent = await $.state.get(intentRef)
    const granted = intent.value
    if (granted) {
      const consumed = await $.state.set(intentRef, null, { ifVersion: intent.version })
      if (!consumed.isSet) return { deny: '本次提交授权已变化，停止。' }
    }
    await $.state.set(commitRef, null)
    const { workspace, files, message, kind, bugId, verified, remote, remoteBranch } = e
    const input = { workspace, files, message, kind, bugId, verified, remote, remoteBranch, mergeBack: granted?.mergeBack === true }
    const result = await $.process.run(['node', ($.plugin.root + '/scripts/commit.mjs'), 'prepare', JSON.stringify(input)])
    if (result.exitCode !== 0) return { deny: result.stderr || '提交准备失败' }
    const plan = JSON.parse(result.stdout)
    if (granted) {
      if (granted.push && !plan.push) return { deny: '本次要求推送，但未确定推送目标；未提交，需明确目标后重试。' }
      const executed = await $.tool.call({ tool: 'Bash', command: 'node ' + quote($.plugin.root + '/scripts/commit.mjs') + ' execute ' + quote(JSON.stringify(plan)) + (granted.mergeBack ? ' --merge-back' : '') + (granted.push ? ' --push' : ''), description: granted.mergeBack ? '按本次授权建分支提交并快进合回原分支' : granted.push ? '按本次授权提交并推送' : '按本次授权创建本地提交', timeout: 600000 })
      return { result: output(executed) }
    }
    await $.state.set(commitRef, JSON.stringify(plan))
    return { result: JSON.stringify({ workspace: plan.workspace, branch: plan.branch, files: plan.files, message: plan.message, push: plan.push ? { remote: plan.push.remote, branch: plan.push.branch } : null }) }
  })
  on('command.run', { command: 'commit' }, async ($, e) => {
    const args = (e.args ?? '').trim()
    const flags = args ? args.split(/\s+/) : []
    if (new Set(flags).size !== flags.length || flags.some(flag => !['--push', '--merge-back'].includes(flag))) return { text: '用法：/commit [--merge-back] [--push]；不支持强推或隐式指定目标。' }
    const push = flags.includes('--push')
    const mergeBack = flags.includes('--merge-back')
    const held = await $.state.get(commitRef)
    if (!held.value) {
      const workspace = (await $.state.get(ref)).value?.workspace
      await $.state.set(intentRef, { push, mergeBack })
      $.clock.after(0, async () => {
        try {
          await $.prompt.submit({ text: '用户调用了 /commit' + (args ? ' ' + args : '') + '，但本会话没有提交准备。本次已授权检查、按明确范围逐项暂存及提交；--push 还授权推送到明确目标。无需用户再次输入命令。' +
            (mergeBack ? '\n本次 --merge-back 明确授权在默认分支准备：由执行器自动创建唯一工作分支、提交并仅快进合回原分支，保留工作分支；模型不要提前切换分支，也不要单独合并。必须没有未暂存或未跟踪文件；失败保留现场，不自动回滚。' : '') +
            '\n任务工作区线索：' + (workspace || '未记录；从本会话任务及实际编辑文件确定，不默认使用 session 主路径') +
            '\n先运行 safe-git-submit 的只读检查，再读取实际 Git 状态与相关规则，核对当前任务改动、已有暂存区和验证证据。展示明确的候选文件清单及中文提交信息；不把其他会话或无关改动纳入提交。只有范围已明确且获得暂存授权时，才逐项 git add -- 具体路径，禁止全量 add；否则先展示清单询问。验证未完成、Bug 编号不明或工作区不唯一时，说明具体缺口，不伪造 verified=true。需要 --push 时核实并展示唯一 remote 与分支。满足条件后先展示确定的文件清单与提交信息（过程说明，不等待第二次确认），然后调用 mcp__task-shortcuts__prepare_commit；该工具将消耗本次授权，通过原执行器 execute 自动提交并按本次 --push 选择推送。核实工具结果并报告实际提交哈希和推送状态，不再提示用户输入第二次命令，不另行重复提交。缺少信息或失败时停止，不编造验证证据、不自动重试。' })
        } catch { await $.state.set(intentRef, null); await $.ui.toast('提交请求未能启动，已取消本次授权；请重试 /commit。') }
      })
      return { text: '正在准备并执行本次提交；条件满足后自动完成，无需再次输入 /commit。' }
    }
    let plan = JSON.parse(held.value)
    if (push && !plan.push) return { text: '未预备推送目标，请先明确 remote 与分支；也可只运行 /commit。' }
    if (mergeBack !== (plan.mergeBack === true)) {
      const result = await $.process.run(['node', $.plugin.root + '/scripts/commit.mjs', 'prepare', JSON.stringify({ ...plan, mergeBack, workBranch: null })])
      if (result.exitCode !== 0) return { text: result.stderr || '提交准备失败；未执行。' }
      const updated = JSON.parse(result.stdout)
      if (['head', 'tree', 'branch', 'workingFingerprint'].some(key => updated[key] !== plan[key]) || JSON.stringify(updated.push) !== JSON.stringify(plan.push)) return { text: '预备后 Git 内容或推送目标发生变化；未执行，请重新准备。' }
      plan = updated
    }
    const consumed = await $.state.set(commitRef, null, { ifVersion: held.version })
    if (!consumed.isSet) return { text: '提交准备已变化，请重新确认。' }
    const result = await $.tool.call({ tool: 'Bash', command: 'node ' + quote(($.plugin.root + '/scripts/commit.mjs')) + ' execute ' + quote(JSON.stringify(plan)) + (mergeBack ? ' --merge-back' : '') + (push ? ' --push' : ''), description: mergeBack ? '按预备清单建分支提交并快进合回原分支' : push ? '按预备清单提交并推送到明确目标' : '按预备清单创建本地提交', timeout: 600000 })
    return { text: output(result), context: ['提交命令结果：' + output(result) + '。失败后不自动重试、重提或强推。'] }
  }).catch(() => ({ text: '提交入口异常，已停止。可能已有本地提交，请先检查状态；不回退执行内置提交、不自动重试。' }))
  on('tool.call', { tool: 'mcp__task-shortcuts__prepare' }, async ($, e) => {
    const { workspace, title, command, prompt } = e
    if (typeof workspace !== 'string' || !workspace.startsWith('/') ||
        typeof title !== 'string' || typeof command !== 'string' || typeof prompt !== 'string' ||
        (command && prompt) || ((command || prompt) && !title.trim()))
      return { deny: '需要绝对工作区路径和动作标题；command 与 prompt 二选一。' }
    const commit = await $.state.get(commitRef)
    if (commit.value && JSON.parse(commit.value).workspace !== workspace) await $.state.set(commitRef, null)
    await $.state.set(workspaceRef, workspace)
    const p: Prepared = { workspace, title, command, prompt }
    await $.state.set(ref, p)
    return { result: JSON.stringify({ prepared: true, workspace, next: title }) }
  })
  on('prompt.submit', async ($, e, next) => {
    // 本地查看命令不消耗待执行动作；新的普通提示则使旧动作失效。
    if (!e.command && !e.isMeta && !(e.origin?.kind === 'plugin' && e.origin.name === 'task-shortcuts' && e.text.startsWith('用户调用 /changes'))) {
      if (!(e.origin?.kind === 'plugin' && e.origin.name === 'task-shortcuts')) await $.state.set(intentRef, null)
      await $.state.set(commitRef, null)
      const held = await $.state.get(ref)
      if (held.value) await $.state.set(ref, { ...held.value, command: '', prompt: '', title: '' })
    }
    return next(e)
  })
  on('tool.call', { tool: 'mcp__task-shortcuts__open_changes' }, async ($, e) => {
    if (typeof e.workspace !== 'string' || !e.workspace.startsWith('/')) return { deny: '需要已核实的绝对工作区路径。' }
    await $.state.set(workspaceRef, e.workspace)
    const result = await $.tool.call({ tool: 'Bash', command: 'bash ' + quote($.plugin.root + '/scripts/open-changes.sh') + ' ' + quote(e.workspace), description: '在 Zed 打开任务工作区改动' })
    return { result: output(result) }
  })
  on('command.run', { command: 'changes' }, async ($, e) => {
    const held = await $.state.get(ref)
    let explicit = (e.args ?? '').trim()
    if ((explicit.startsWith('"') && explicit.endsWith('"')) || (explicit.startsWith("'") && explicit.endsWith("'"))) explicit = explicit.slice(1, -1)
    const workspace = (await $.state.get(workspaceRef)).value
    const path = explicit || workspace || held.value?.workspace
    if (!path) {
      $.clock.after(0, async () => {
        try { await $.prompt.submit({ text: '用户调用 /changes，正在定位本次任务工作区。依据本会话明确的 worktree 和实际编辑文件定位；session 主路径可能不是任务 worktree。不要扫描谁有改动来猜，也不要要求用户先准备缓存。目标确定后用 git -C 核实，再调用 mcp__task-shortcuts__open_changes 一次打开。没有任何任务目标或实际操作线索时才回退到 session 所在仓库。多个目标不唯一或目录失效时说明具体路径，只询问必要问题。仅查看，不提交、不审查、不推进任务、不调用 prepare 覆盖 next。' }) }
        catch { await $.ui.toast('工作区定位未启动，请使用 /changes /工作区绝对路径。') }
      })
      return { text: '正在定位任务工作区，确定后直接在 Zed 打开。' }
    }
    const result = await $.tool.call({ tool: 'Bash', command: 'bash ' + quote($.plugin.root + '/scripts/open-changes.sh') + ' ' + quote(path), description: '在 Zed 打开任务工作区改动' })
    return { text: output(result) }
  })
  on('command.run', { command: 'next' }, async ($) => {
    const held = await $.state.get(ref)
    const p = held.value
    if (!p || (!p.command && !p.prompt)) {
      $.clock.after(0, async () => {
        try { await $.prompt.submit({ text: '用户输入 /next：执行本会话最近一次明确推荐、尚未完成且未失效的下一步。虽然没有本地缓存，但请直接使用上下文确定动作与实际工作区；不要仅要求用户先准备缓存。先简短说明，然后完整执行已推荐的动作组，不再等待第二次 next。不要重复已经完成的操作，不扩展任务；没有明确建议或存在互斥方案时才说明缺口或询问。遵守项目规则和验证要求；安装启动核实本轮绑定设备。此入口不授权提交、推送、删除、发布、覆盖数据等高风险操作。' }) }
        catch { await $.ui.toast('续做请求未启动，请直接输入“继续最近推荐的下一步”。') }
      })
      return { text: '正在根据上下文执行下一步；不会重复已完成的操作。' }
    }
    const consumed = await $.state.set(ref, { ...p, command: '', prompt: '', title: '' }, { ifVersion: held.version })
    if (!consumed.isSet) return { text: '下一步已变化，请重新确认。' }
    if (p.prompt) {
      $.clock.after(0, async () => {
        try { await $.prompt.submit({ text: `执行已明确推荐的下一步：${p.title}\n工作区：${p.workspace}\n${p.prompt}` }) }
        catch { await $.ui.toast("续做请求未提交，请直接输入继续；不会重试执行。") }
      })
      return { text: `继续：${p.title}（此动作需要模型执行）` }
    }
    const result = await $.tool.call({ tool: 'Bash', command: 'cd ' + quote(p.workspace) + ' && ( set -e\n' + p.command + '\n)', description: p.title, timeout: 600000 })
    return { text: output(result), context: [`已尝试下一步：${p.title}；工作区 ${p.workspace}。结果：${output(result)}。启动成功不等于用户验收通过。`] }
  })
}
