import { spawn, execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, appendFileSync } from 'node:fs';
import { tmpdir, homedir } from 'node:os';
import { join } from 'node:path';
import assert from 'node:assert/strict';
const scenario=process.env.SCENARIO || 'local';
if (!['local','push','stale','unstaged'].includes(scenario)) throw new Error('unknown scenario');
const root=mkdtempSync(join(tmpdir(),'task-shortcuts-cli-'));
const repo=join(root,'project');mkdirSync(repo);
const git=(cwd,...args)=>execFileSync('git',args,{cwd,encoding:'utf8',stdio:['ignore','pipe','pipe']}).trim();
git(repo,'init','-b','feature/e2e');git(repo,'config','user.name','Shortcut Test');git(repo,'config','user.email','test@example.invalid');
writeFileSync(join(repo,'sample.txt'),'base\n');git(repo,'add','--','sample.txt');
execFileSync(join(homedir(),'.claude/bin/safe-git-submit'),['--repo',repo,'--commit','test: 初始化临时验证仓库'],{stdio:'pipe'});
const remote=join(root,'remote.git');git(root,'init','--bare',remote);git(repo,'remote','add','origin',remote);git(repo,'push','-u','origin','feature/e2e');
const head=git(repo,'rev-parse','HEAD');
const worktree=join(root,'task worktree');git(repo,'worktree','add','-b','feature/worktree',worktree);
writeFileSync(join(worktree,'sample.txt'),'changed\n');git(worktree,'add','--','sample.txt');
if (scenario==='push') git(repo,'push','origin','feature/worktree');
if (scenario==='unstaged') git(worktree,'restore','--staged','--','sample.txt');
writeFileSync(join(worktree,'unrelated.txt'),'must stay untracked\n');
const plan={workspace:worktree,files:['sample.txt'],message:'test: 验证真实会话提交',kind:'other',bugId:'',verified:true,remote:scenario==='push'?'origin':'',remoteBranch:scenario==='push'?'feature/worktree':''};
const env={...process.env};delete env.CLAUDECODE;
const args=['-p','--input-format','stream-json','--output-format','stream-json','--verbose','--setting-sources','user','--strict-mcp-config','--mcp-config','{"mcpServers":{}}','--permission-mode','auto','--max-budget-usd','1.5','--max-turns','8'];
const child=spawn(join(homedir(),'.local/bin/claude'),args,{cwd:repo,env,stdio:['pipe','pipe','pipe']});
let buffer='',phase=0,toolError='';
const send=text=>child.stdin.write(JSON.stringify({type:'user',message:{role:'user',content:text}})+'\n');
console.log('测试场景：'+scenario+'；目录：'+root);
child.stderr.on('data',b=>appendFileSync(join(root,'stderr.log'),b));
child.stdout.on('data',b=>{buffer+=b;let pos;while((pos=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,pos);buffer=buffer.slice(pos+1);appendFileSync(join(root,'transcript.jsonl'),line+'\n');let e;try{e=JSON.parse(line)}catch{continue}
 if(e.type==='user') for(const block of e.message?.content || []) if(block.type==='tool_result' && block.is_error) toolError+=JSON.stringify(block.content);
 if(e.type==='result'){
  console.log('阶段 '+phase+': '+JSON.stringify({is_error:e.is_error,result:e.result,num_turns:e.num_turns,cost:e.total_cost_usd}));
  if(phase===0 && scenario!=='unstaged'){phase=1;if(scenario==='stale') writeFileSync(join(worktree,'sample.txt'),'changed after prepare\n');send(scenario==='push'?'/commit --push':'/commit');}else child.stdin.end();
 }
}});
const timer=setTimeout(()=>{console.error('超时');child.kill();},120000);
send('这是用户授权的临时仓库提交测试。现在仅调用 mcp__task-shortcuts__prepare_commit，参数为 '+JSON.stringify(plan)+'，必要时用 ToolSearch 加载。文件已逐项暂存，测试脚本已验证纯文本变更；不纳入 unrelated.txt。工具成功后回复准备完成；本轮不提交不推送，后续用户 /commit 将授权提交。不要执行其他操作。');
const code=await new Promise(resolve=>child.on('close',resolve));clearTimeout(timer);
const result={scenario,toolError,root,exitCode:code,committed:git(worktree,'rev-parse','HEAD')!==head,mainUnchanged:git(repo,'rev-parse','HEAD')===head,files:git(worktree,'show','--format=','--name-only','HEAD'),untracked:git(worktree,'status','--short'),remoteUnchanged:git(remote,'rev-parse','refs/heads/feature/e2e')===head};
writeFileSync(join(root,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
assert.equal(result.mainUnchanged,true);assert.equal(result.remoteUnchanged,true);assert.ok(result.untracked.includes('unrelated.txt'));
if(['local','push'].includes(scenario)){assert.equal(result.committed,true,'真实 /commit 未产生提交');assert.equal(result.files,'sample.txt');}
else assert.equal(result.committed,false,'不应产生提交');
if(scenario==='push') assert.equal(git(remote,'rev-parse','refs/heads/feature/worktree'),git(worktree,'rev-parse','HEAD'));
if(scenario==='unstaged') assert.ok(toolError.includes('没有明确暂存'));
if(scenario==='local'||scenario==='push') assert.equal(toolError,'');
