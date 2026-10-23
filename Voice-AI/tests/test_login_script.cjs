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
  const config = {auth_base_url: '', login_url: '/#/login'};
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
// 실제 TTS 클릭 핸들러를 실행하여 요청 및 MP3 재생 URL이 prefix를 유지하는지 확인한다.
async function checkTts(prefix) {
  const html = fs.readFileSync(path.join(__dirname, '../app/static/tts.html'), 'utf8');
  const code = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  const baseURI = 'https://heartsignal.class-4.skala-us.com' + prefix + '/';
  const elements = {};
  let click, endpoint;
  const element = id => elements[id] ||= {value: '음성 기능 테스트', style: {}, play: () => Promise.resolve(), addEventListener: (_, handler) => {click = handler;}};
  vm.runInNewContext(code, {
    document: {baseURI, getElementById: element}, URL, URLSearchParams, Date, console,
    alert: message => {throw Error(message);},
    fetch: async url => {endpoint = new URL(url, baseURI).pathname; return {ok: true, json: async () => ({file_path: '/uploads/test.mp3'})};}
  });
  await click();
  assert.equal(endpoint, prefix + '/tts/');
  assert.equal(new URL(elements['audio-player'].src).pathname, prefix + '/uploads/test.mp3');
  assert.equal(elements['audio-wrapper'].style.display, 'block');
}
function checkLinks(prefix) {
  const baseURI = 'https://heartsignal.class-4.skala-us.com' + prefix + '/';
  for (const name of ['index', 'stt', 'tts', 'stt-tts']) {
    const html = fs.readFileSync(path.join(__dirname, '../app/static/' + name + '.html'), 'utf8');
    for (const match of html.matchAll(/(?:href|src)="([^"#]+)"/g)) {
      assert.ok(new URL(match[1], baseURI).pathname.startsWith(prefix + '/'), name + ': ' + match[1]);
    }
    if (name !== 'index') {
      const endpoint = html.match(/fetch\("([^" ]+)"/)[1];
      assert.equal(new URL(endpoint, baseURI).pathname, prefix + '/' + name + '/');
    }
  }
}
(async () => {
  for (const mode of [200, 401, 503, 'network']) await check(mode);
  for (const prefix of ['', '/voice']) {await checkTts(prefix); checkLinks(prefix);}
  console.log('PASS: 홈 인증 4개 + 실제 TTS 요청·MP3 2개 + 전체 화면 링크·API prefix 2개');
})().catch(e => {console.error(e); process.exitCode = 1;});
