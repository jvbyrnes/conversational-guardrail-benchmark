'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const {execFileSync} = require('node:child_process');

const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'benchmark-redirect-'));
let html;
try {
 execFileSync('uv', ['run', 'guardrail-bench', 'export-site', path.join(temporary, 'export')],
  {cwd: path.resolve(__dirname, '../..')});
 html = fs.readFileSync(path.join(temporary, 'export/index.html'), 'utf8');
} finally {
 fs.rmSync(temporary, {recursive: true, force: true});
}

test('root export offers a relative fallback when JavaScript is disabled', () => {
 assert.match(html, /<a href="\.\/site\/">Open benchmark<\/a>/);
 assert.doesNotMatch(html, /http-equiv|<base\b|<script\b[^>]*\bsrc=/i);
});

for (const root of ['https://example.test/', 'https://example.test/project/', 'https://example.test/project/index.html']) {
 for (const suffix of ['', '?task=a%2Fb&result=x&result=y', '#review', '?preview=1&value=%23%26#case%2F1']) {
  test(`root redirect replaces history and preserves suffix at ${root}${suffix}`, () => {
   const current = new URL(root + suffix);
   const calls = [];
   const location = {search: current.search, hash: current.hash,
    replace(target) { calls.push(new URL(target, current).href); },
    assign() { assert.fail('redirect must replace history'); }};
   const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)];
   assert.equal(scripts.length, 1);
   vm.runInNewContext(scripts[0][1], {location});
   assert.deepEqual(calls, [new URL('./site/' + current.search + current.hash, current).href]);
  });
 }
}
