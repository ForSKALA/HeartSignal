// 실제 홈 스크립트의 쿠키 전달·401 이동·네트워크 실패 동작을 검증한다.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../app/static/index.html'), 'utf8');
const code = html.match(/<script>([\s\S]*?)<\/script>/)[1];
async function check(mode) {
  let handler, called, redirected;
  const status = {textContent: ''};
  const config = {auth_base_url: 'https://heartsignal.class-4.skala-us.com', login_url: 'https://heartsignal.class-4.skala-us.com/login?return_to=voice'};
  vm.runInNewContext(code, {
    window: {HEARTSIGNAL_AUTH: config, addEventListener: (_, fn) => {handler = fn;}, location: {replace: url => {redirected = url;}}},
    document: {getElementById: () => status},
    fetch: async (url, options) => {called = {url, options}; if (mode === 'network') throw Error('offline'); return {status: mode, ok: mode === 200};}
  });
  await handler();
  assert.equal(called.url, config.auth_base_url + '/api/auth/check');
  assert.equal(called.options.credentials, 'include');
  if (mode === 401) assert.equal(redirected, config.login_url);
  else assert.equal(redirected, undefined);
  if (mode === 'network' || mode === 503) assert.notEqual(status.textContent, '');
  if (mode === 200) assert.equal(status.textContent, '');
}
(async () => {for (const mode of [200, 401, 503, 'network']) await check(mode); console.log('PASS: 홈 인증 스크립트 4개 시나리오');})().catch(e => {console.error(e); process.exitCode = 1;});
