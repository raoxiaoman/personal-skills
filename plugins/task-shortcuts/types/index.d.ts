export type Prepared = { workspace: string; title: string; command: string; prompt: string }
declare module 'claude-code' {
  interface PluginState { 'task-shortcuts': { workspace: string | null; prepared: Prepared | null; commit: string | null; commitIntent: { push: boolean; mergeBack: boolean } | null } }
  interface McpToolInputs { 'mcp__task-shortcuts__open_changes': { workspace: string };  'mcp__task-shortcuts__prepare_commit': { workspace: string; files: string[]; message: string; kind: 'bug' | 'other'; bugId: string; verified: boolean; remote: string; remoteBranch: string };  'mcp__task-shortcuts__prepare': Prepared }
}
