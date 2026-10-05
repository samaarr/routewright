import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

// Temporary dev-tool exception only: untrusted glob patterns never enter builds.
const advisory = 'https://github.com/advisories/GHSA-vfj7-8cjw-p6xm';
const expires = Date.parse('2026-11-04T00:00:00Z');
const lock = JSON.parse(readFileSync(new URL('../package-lock.json', import.meta.url)));
function audit(args) {
  const result = spawnSync('npm', ['audit', '--json', ...args], { encoding: 'utf8' });
  const report = JSON.parse(result.stdout || '{}');
  if (result.error || report.error || !report.vulnerabilities) throw new Error('Dependency audit unavailable');
  return report.vulnerabilities;
}
const runtime = audit(['--omit=dev']);
if (Object.keys(runtime).length) throw new Error('Runtime dependency vulnerabilities found');
const all = audit([]);
function excepted(name, visited = new Set()) {
  if (visited.has(name)) return false;
  const item = all[name];
  if (!item || !item.via.length || Date.now() >= expires) return false;
  if (!item.nodes.every(path => lock.packages[path]?.dev === true)) return false;
  const next = new Set([...visited, name]);
  return item.via.every(via => typeof via === 'string' ? excepted(via, next) :
    via.url === advisory && via.name === 'braces' && item.nodes.every(path => lock.packages[path]?.version === '3.0.3'));
}
for (const [name, item] of Object.entries(all)) {
  if (['high', 'critical'].includes(item.severity) && !excepted(name)) throw new Error(`Unaccepted security finding: ${name}`);
}
console.log('Runtime audit clean. Dev-only braces exception expires 2026-11-04; new high/critical findings fail.');
