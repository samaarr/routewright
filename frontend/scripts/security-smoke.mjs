import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { chromium } from 'playwright';
const port = 3197;
const origin = `http://127.0.0.1:${port}`;
const server = spawn(process.execPath, ['node_modules/next/dist/bin/next', 'start', '-p', String(port)], {
  env: { ...process.env, NEXT_PUBLIC_API_URL: 'https://api.routewright.invalid', SECURITY_HSTS_ENABLED: 'true' },
  stdio: ['ignore', 'pipe', 'pipe'],
});
let logs = '';
server.stdout.on('data', chunk => { logs += chunk; });
server.stderr.on('data', chunk => { logs += chunk; });
let browser;
try {
  let ready = false;
  for (let i = 0; i < 100; i++) {
    if (server.exitCode !== null) throw new Error(logs);
    try { if ((await fetch(origin)).ok) { ready = true; break; } } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert(ready, 'Production server did not start');
  const first = await fetch(origin, { headers: { 'x-nonce': 'attacker-controlled' } });
  const second = await fetch(origin);
  const csp = first.headers.get('content-security-policy');
  assert(csp.includes("frame-ancestors 'none'"));
  const scripts = csp.split(';').find(item => item.trim().startsWith('script-src'));
  assert(!scripts.includes('unsafe-inline') && !scripts.includes('unsafe-eval'));
  assert(!csp.includes('attacker-controlled'));
  assert.notEqual(csp, second.headers.get('content-security-policy'));
  assert.equal(first.headers.get('x-content-type-options'), 'nosniff');
  assert.equal(first.headers.get('x-frame-options'), 'DENY');
  assert.equal(first.headers.get('strict-transport-security'), 'max-age=31536000');
  assert(first.headers.get('cache-control').includes('no-store'));
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => {
    window.__cspViolations = [];
    document.addEventListener('securitypolicyviolation', event => window.__cspViolations.push(event.violatedDirective));
  });
  await page.goto(origin);
  await page.getByPlaceholder('Dublin, Ireland').filter({ visible: true }).fill('Dublin');
  const before = await page.locator('input[type="text"]:visible').count();
  await page.getByRole('button', { name: /add another stop/i }).filter({ visible: true }).click();
  await page.locator('input[type="text"]:visible').nth(before).waitFor();
  assert.equal(await page.locator('input[type="text"]:visible').count(), before + 1);
  assert.deepEqual(errors, []);
  assert.deepEqual(await page.evaluate(() => window.__cspViolations), []);
  console.log('Production security headers, nonce isolation, CSP and interactive hydration passed.');
} finally {
  await browser?.close();
  server.kill('SIGTERM');
}
