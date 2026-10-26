import { spawn, execFileSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, appendFileSync } from 'node:fs';
import { tmpdir, homedir } from 'node:os';
import { join } from 'node:path';
import assert from 'node:assert/strict';
const push = process.env.SCENARIO === 'push';
const repo=mkdtempSync(join(tmpdir(),'task-shortcuts-fallback-'));
const git=(...args)=>execFileSync('git',args,{cwd:repo,encoding:'utf8',stdio:['ignore','pipe','pipe']}).trim();
git('init','-b','feature/fallback');git('config','user.name','Test');git('config','user.email','test@example.invalid');
writeFileSync(join(repo,'sample.txt'),'base\n');git('add','--','sample.txt');execFileSync(join(homedir(),'.claude/bin/safe-git-submit'),['--repo',repo,'--commit','test: 初始化'],{stdio:'pipe'});
const remote=repo+'-remote.git';
if(push){git('init','--bare',remote);git('remote','add','origin',remote);git('push','-u','origin','feature/fallback');}
const old=git('rev-parse','HEAD');writeFileSync(join(repo,'sample.txt'),'changed\n');
const env={...process.env};delete env.CLAUDECODE;
const p=spawn(join(homedir(),'.local/bin/claude'),['-p','--input-format','stream-json','--output-format','stream-json','--verbose','--setting-sources','user','--strict-mcp-config','--mcp-config','{"mcpServers":{}}','--permission-mode','auto','--max-budget-usd','2','--max-turns','15'],{cwd:repo,env,stdio:['pipe','pipe','pipe']});
console.log('测试仓库：'+repo);
const send=text=>p.stdin.write(JSON.stringify({type:'user',message:{role:'user',content:text}})+'\n');
let buffer='',stage=0;
p.stderr.on('data',b=>appendFileSync(repo+'-stderr.log',b));
p.stdout.on('data',b=>{buffer+=b;let i;while((i=buffer.indexOf('\n'))>=0){let line=buffer.slice(0,i);buffer=buffer.slice(i+1);appendFileSync(repo+'-transcript.jsonl',line+'\n');let e;try{e=JSON.parse(line)}catch{continue}if(e.type!=='result')continue;
 console.log('阶段 '+stage+': '+JSON.stringify({result:e.result,turns:e.num_turns,error:e.is_error}));
 if(stage===0){stage=1;send(push?'/commit --push':'/commit');}
 else if(stage===1 && e.num_turns===0){stage=2;}
 else if(stage===2){stage=3;p.stdin.end();}
 else p.stdin.end();
}});
const timer=setTimeout(()=>{console.error('fallback 超时');p.kill();},180000);
send(`临时仓库测试，当前任务只有 ${repo}/sample.txt 的 base 改为 changed。测试脚本已核对该纯文本改动且验证通过；明确授权后续提交时逐项暂存并提交 sample.txt，提交信息为 test: 验证无缓存提交。没有 Bug 编号。${push?'本次明确授权提交后推送到 origin 的 feature/fallback 分支，远端是测试用本地裸仓库。':'不推送。'}现在不要 prepare_commit，不执行工具，只回复收到；随后我将输入 /commit 测试无缓存降级。`);
const exit=await new Promise(resolve=>p.on('close',resolve));clearTimeout(timer);
const result={repo,stage,exit,committed:git('rev-parse','HEAD')!==old,status:git('status','--short'),message:git('log','-1','--format=%s')};console.log(JSON.stringify(result,null,2));
assert.equal(result.committed,true,'无缓存路径没有完成提交');assert.equal(result.status,'');assert.equal(result.message,'test: 验证无缓存提交');

if(push) assert.equal(execFileSync('git',['--git-dir',remote,'rev-parse','refs/heads/feature/fallback'],{encoding:'utf8'}).trim(),git('rev-parse','HEAD'));
