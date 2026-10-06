// Key-exposure check for the production build (Step 9).
//
// Build with a fake SERVER key in the environment, then scan every emitted
// file: the probe value must never appear (the frontend must not read the
// server key), no server-only key variable name may be referenced, and no
// Google key-shaped string may be bundled except the deliberately public
// browser key (NEXT_PUBLIC_GOOGLE_MAPS_API_KEY) when one is configured.
//
//   GOOGLE_MAPS_API_KEY=$SECURITY_BUNDLE_PROBE NEXT_PUBLIC_API_URL=https://api.routewright.invalid npm run build
//   SECURITY_BUNDLE_PROBE=... npm run security:bundle
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

const probe = process.env.SECURITY_BUNDLE_PROBE;
assert(probe && probe.length >= 20, 'Set SECURITY_BUNDLE_PROBE to the fake server key used for the build');
const publicKey = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY ?? '';

function* files(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (name === 'cache') continue; // build cache, never served
    if (statSync(path).isDirectory()) yield* files(path);
    else yield path;
  }
}

let scanned = 0;
const problems = [];
for (const path of files('.next')) {
  const text = readFileSync(path, 'latin1');
  scanned += 1;
  if (text.includes(probe)) problems.push(`server key value in ${path}`);
  if (/(?<!NEXT_PUBLIC_)\bGOOGLE_MAPS_API_KEY\b/.test(text)) problems.push(`server key variable referenced in ${path}`);
  for (const match of text.matchAll(/AIza[0-9A-Za-z_-]{35}/g)) {
    if (match[0] !== publicKey) problems.push(`key-shaped string in ${path}`);
  }
}
assert(scanned > 0, 'No build output found; run the build first');
assert.deepEqual(problems, []);
console.log(`Bundle key-exposure check passed (${scanned} files).`);
