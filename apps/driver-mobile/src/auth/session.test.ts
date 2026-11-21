/// <reference types="node" />
// Node types only in tests: app code runs on phones, where Node APIs do not exist.
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  describeError,
  errorCode,
  needsRefresh,
  parseStoredSession,
  REFRESH_MARGIN_MS,
  toStoredSession,
} from './session.ts';

const NOW = 1_800_000_000_000;

describe('toStoredSession', () => {
  it('computes the absolute expiry', () => {
    const s = toStoredSession({ accessToken: 'a', refreshToken: 'r', expiresIn: 3600 }, NOW);
    assert.deepEqual(s, { accessToken: 'a', refreshToken: 'r', expiresAt: NOW + 3_600_000 });
  });

  it('keeps the previous refresh token when a refresh response omits it', () => {
    const s = toStoredSession({ accessToken: 'a2', expiresIn: 60 }, NOW, 'r1');
    assert.equal(s.refreshToken, 'r1');
  });

  it('uses a short default lifetime when expiresIn is missing', () => {
    const s = toStoredSession({ accessToken: 'a' }, NOW);
    assert.equal(s.expiresAt, NOW + 300_000);
  });

  it('rejects a response without an access token', () => {
    assert.throws(() => toStoredSession({ accessToken: '' }, NOW));
  });
});

describe('needsRefresh', () => {
  const session = { accessToken: 'a', refreshToken: 'r', expiresAt: NOW + 10 * 60_000 };
  it('is false well before expiry', () => assert.equal(needsRefresh(session, NOW), false));
  it('is true inside the safety margin', () =>
    assert.equal(needsRefresh(session, session.expiresAt - REFRESH_MARGIN_MS + 1), true));
  it('is true after expiry', () => assert.equal(needsRefresh(session, session.expiresAt + 1), true));
});

describe('parseStoredSession', () => {
  it('round-trips a valid session', () => {
    const s = { accessToken: 'a', refreshToken: null, expiresAt: NOW };
    assert.deepEqual(parseStoredSession(JSON.stringify(s)), s);
  });

  it('treats missing, corrupt or wrongly shaped data as signed out', () => {
    assert.equal(parseStoredSession(null), null);
    assert.equal(parseStoredSession('{not json'), null);
    assert.equal(parseStoredSession(JSON.stringify({ accessToken: 1, expiresAt: NOW })), null);
    assert.equal(parseStoredSession(JSON.stringify({ accessToken: 'a', refreshToken: 5, expiresAt: NOW })), null);
  });
});

describe('API errors', () => {
  it('reads the error envelope code', () => {
    assert.equal(errorCode({ error: { code: 'no_membership', message: 'x' } }), 'no_membership');
    assert.equal(errorCode({ detail: 'x' }), null);
    assert.equal(errorCode(null), null);
  });

  it('explains known codes and falls back for unknown ones', () => {
    assert.match(describeError('no_membership'), /not registered/);
    assert.equal(describeError('something_new'), 'Something went wrong. Try again.');
    assert.equal(describeError(null), 'Something went wrong. Try again.');
  });
});
