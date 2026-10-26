# 真实 CLI 集成验证

从已全局安装的 task-shortcuts 启动真实 Claude Code 子进程，使用正常 auto 权限检查，不设置 Bash 通配放行，也不跳过权限。测试会调用模型并产生少量费用。

```bash
node e2e/cli-commit.mjs
SCENARIO=push node e2e/cli-commit.mjs
SCENARIO=stale node e2e/cli-commit.mjs
SCENARIO=unstaged node e2e/cli-commit.mjs
node e2e/cli-fallback.mjs
SCENARIO=push node e2e/cli-fallback.mjs
```

每次创建全新的临时仓库；push 只向本地裸仓库推送，不访问真实远端。首次提交与正式被测提交都走 safe-git-submit。测试先通过真实 MCP prepare_commit，再在同一个 CLI 进程输入 slash 命令；不是用函数执行代替 slash 入口。

cli-commit 覆盖 session 从主路径启动、实际修改在含空格 worktree、保留无关未跟踪文件、MCP 返回类型、默认不推送、显式推送、预备后改动失效及未暂存时失败。
cli-fallback 覆盖没有任何提交缓存且仅有未暂存改动的场景，明确授权精确文件和验证事实；只输入一次 /commit 或 /commit --push，触发模型检查、逐项暂存和提交，不发送第二次命令。缺失验证、暂存授权或范围不明确时仍应询问，不得伪造测试事实。

临时仓库与 transcript 保留用于追查，不自动清理；测试输出打印所在目录。此组测试尚未覆盖用户交互式 TUI 绘制、真实托管平台认证/网络故障、重启后恢复对话和提交 hook 修改暂存区等所有组合。
