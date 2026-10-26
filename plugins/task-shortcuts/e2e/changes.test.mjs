import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
const script=new URL('../scripts/open-changes.sh',import.meta.url).pathname;
const root=mkdtempSync(join(tmpdir(),'changes-check-'));
const repo=join(root,"project ' with spaces");mkdirSync(repo);
execFileSync('git',['init','-b','feature/test',repo],{stdio:'pipe'});
const bin=join(root,'bin');mkdirSync(bin);
const capture=join(root,'zed-args');
// 在进入 UI 自动化前结束，用于独立核对参数，不伪称验证了 UI。
writeFileSync(join(bin,'zed'),'#!/bin/bash\nprintf "%s\\n" "$@" > "$CAPTURE"\nexit 37\n',{mode:0o755});
const invoke=args=>spawnSync('bash',[script,...args],{encoding:'utf8',env:{...process.env,PATH:bin+':'+process.env.PATH,CAPTURE:capture}});
test('含空格单引号路径正确传给 Zed，不拆分参数',()=>{
 const r=invoke([repo]);assert.equal(r.status,37);assert.equal(readFileSync(capture,'utf8').trim(),execFileSync('git',['-C',repo,'rev-parse','--show-toplevel'],{encoding:'utf8'}).trim());
});
test('失效路径返回实际目录，不误报用法',()=>{
 const path=join(root,'deleted-worktree');const r=invoke([path]);assert.equal(r.status,2);assert.ok(r.stderr.includes(path));assert.ok(r.stderr.includes('目录不存在'));assert.ok(!r.stderr.includes('用法'));
});
test('非 Git 目录明确报错，参数缺失才报告用法',()=>{
 assert.ok(invoke([root]).stderr.includes('不是有效 Git'));assert.ok(invoke([]).stderr.includes('用法'));
});
console.log('测试目录：'+root);
