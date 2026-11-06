import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { canonicalScan } from '../src/lib/physical-labels.ts';
import { inspectionRequest, inspectionError, InspectionError } from '../src/lib/inspection.ts';
const source = await readFile(new URL('../src/components/inspection-workstation.tsx', import.meta.url), 'utf8');
const reference = 'PC-' + 'A'.repeat(32);

test('scanner accepts full QR identity and Enter/newline suffixes without mutations', async () => {
  assert.equal(canonicalScan('SP:PC:1:' + reference + '\r\n'), reference);
  assert.throws(() => canonicalScan('PC-ABC'));
  const calls = [];
  await inspectionRequest('/lookup?reference=' + reference, undefined, async (path, init) => {
    calls.push({ path, init }); return Response.json({ card: { reference } });
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].init.method, 'GET');
  assert.equal(calls[0].init.cache, 'no-store');
});

test('explicit command sends CSRF, optimistic version and stable idempotency identity', async () => {
  const calls = [];
  const payload = { action: 'start', reason: 'Confirmed', version: 0, request_key: 'stable-retry-key' };
  const request = async (path, init) => { calls.push({ path, init }); return Response.json(path.endsWith('/csrf') ? { csrf_token: 'test-csrf' } : { inspection: { status: 'in_progress' } }); };
  const result = await inspectionRequest('/' + reference + '/command', payload, request);
  assert.equal(result.inspection.status, 'in_progress');
  assert.equal(calls[1].init.headers['X-CSRF-Token'], 'test-csrf');
  assert.equal(calls[1].init.headers['X-Spectra-Client'], '1');
  assert.deepEqual(JSON.parse(calls[1].init.body), payload);
  assert.match(source, /window.confirm/);
  assert.match(source, /pendingCommand.current/);
});

test('eligibility rejection preserves detailed French and English reasons', async () => {
  const reasons = [{ code: 'payment_unverified', en: 'Payment unavailable.', fr: 'Paiement indisponible.' }];
  let error;
  try { await inspectionRequest('/lookup', undefined, async () => Response.json({ detail: { eligible: false, reasons } }, { status: 409 })); } catch (e) { error = e; }
  assert.equal(inspectionError(error, 'FR'), reasons[0].fr);
  assert.equal(inspectionError(error, 'EN'), reasons[0].en);
  assert.match(inspectionError(new InspectionError('stale_version'), 'EN'), /changed/);
});

test('expired sessions stop protected writes before command submission', async () => {
  let calls = 0;
  await assert.rejects(inspectionRequest('/command', {}, async () => { calls++; return Response.json({}, { status: 401 }); }), /authentication_required/);
  assert.equal(calls, 1);
});

test('workstation exposes blocked states, both image sides, custody and accessible controls', () => {
  for (const value of ['data.eligibility[action].eligible', 'data-image-status', 'data.custody.map', 'aria-live="polite"', 'htmlFor="inspection-scan"', 'canonicalScan(scan)', 'Historique de garde', 'Custody history', 'Éligibilité', 'Eligibility']) assert.ok(source.includes(value), value);
});
