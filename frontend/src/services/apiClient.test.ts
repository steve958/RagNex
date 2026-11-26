import { AxiosAdapter, AxiosError, InternalAxiosRequestConfig } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { apiClient, setAccessToken, setRefreshHandler, setTenantId } from './apiClient';

/** A fake API: only `validToken` is accepted; /auth/refresh issues the next token. */
class FakeServer {
  validToken = 'token-1';
  refreshCalls = 0;
  refreshFails = false;
  seen: { url?: string; auth?: string }[] = [];

  adapter: AxiosAdapter = async (config: InternalAxiosRequestConfig) => {
    const auth = config.headers.get('Authorization')?.toString();
    this.seen.push({ url: config.url, auth });
    const reply = (status: number, data: unknown) => {
      const response = { status, statusText: String(status), data, headers: {}, config };
      if (status >= 400) {
        throw new AxiosError(`HTTP ${status}`, 'ERR_BAD_REQUEST', config, null, response);
      }
      return response;
    };

    if (config.url?.endsWith('/api/v1/auth/refresh')) {
      this.refreshCalls += 1;
      await new Promise((r) => setTimeout(r, 10)); // let concurrent 401s pile up
      if (this.refreshFails) return reply(401, { detail: 'Invalid token' });
      this.validToken = `token-${this.refreshCalls + 1}`;
      return reply(200, { access_token: this.validToken, refresh_token: 'r' });
    }
    if (config.url?.endsWith('/api/v1/auth/login')) return reply(401, { detail: 'Invalid credentials' });
    if (auth !== `Bearer ${this.validToken}`) return reply(401, { detail: 'Invalid token' });
    return reply(200, { ok: true, url: config.url });
  };
}

let server: FakeServer;
const originalAdapter = apiClient.defaults.adapter;

beforeEach(() => {
  server = new FakeServer();
  apiClient.defaults.adapter = server.adapter;
  setTenantId('t1');
  // What the auth store's handler does: call /auth/refresh and store the new token.
  setRefreshHandler(async () => {
    try {
      const res = await apiClient.post('/api/v1/auth/refresh', { refresh_token: 'r' });
      setAccessToken(res.data.access_token);
      return res.data.access_token;
    } catch {
      return null;
    }
  });
});

afterEach(() => {
  apiClient.defaults.adapter = originalAdapter;
  setRefreshHandler(null);
  setAccessToken(null);
  setTenantId(null);
});

describe('apiClient token refresh', () => {
  it('refreshes once on a 401 and retries the request with the new token', async () => {
    setAccessToken('expired');

    const res = await apiClient.get('/api/v1/knowledgebases');

    expect(res.data.ok).toBe(true);
    expect(server.refreshCalls).toBe(1);
    expect(server.seen.map((s) => [s.url, s.auth])).toEqual([
      ['/api/v1/knowledgebases', 'Bearer expired'],
      ['/api/v1/auth/refresh', 'Bearer expired'], // ignored by /auth/refresh; body carries the refresh token
      ['/api/v1/knowledgebases', 'Bearer token-2'],
    ]);
  });

  it('shares a single refresh between concurrent failing requests', async () => {
    setAccessToken('expired');

    const results = await Promise.all(
      ['/api/v1/a', '/api/v1/b', '/api/v1/c', '/api/v1/d'].map((url) => apiClient.get(url)),
    );

    expect(results.every((r) => r.data.ok)).toBe(true);
    expect(server.refreshCalls).toBe(1);
  });

  it('retries with an already-refreshed token without refreshing again', async () => {
    // The request goes out with the old token, then a refresh happens elsewhere.
    setAccessToken('expired');
    const pending = apiClient.get('/api/v1/x', { headers: { Authorization: 'Bearer expired' } });
    server.validToken = 'token-fresh';
    setAccessToken('token-fresh');

    await expect(pending).resolves.toMatchObject({ data: { ok: true } });
    expect(server.refreshCalls).toBe(0);
  });

  it('gives up with the original 401 when the refresh is rejected', async () => {
    setAccessToken('expired');
    server.refreshFails = true;

    await expect(apiClient.get('/api/v1/knowledgebases')).rejects.toMatchObject({ response: { status: 401 } });
    expect(server.refreshCalls).toBe(1);
    // Not retried after the failed refresh.
    expect(server.seen.filter((s) => s.url === '/api/v1/knowledgebases')).toHaveLength(1);
  });

  it('never refreshes for auth endpoints or requests that opt out', async () => {
    setAccessToken('expired');

    await expect(apiClient.post('/api/v1/auth/login', {})).rejects.toMatchObject({ response: { status: 401 } });
    await expect(apiClient.get('/api/v1/tenants', { skipAuthRefresh: true })).rejects.toMatchObject({
      response: { status: 401 },
    });
    expect(server.refreshCalls).toBe(0);
  });

  it('retries a request at most once even if the new token is rejected too', async () => {
    setAccessToken('expired');
    const handler = vi.fn().mockResolvedValue('also-invalid');
    setRefreshHandler(handler);

    await expect(apiClient.get('/api/v1/x')).rejects.toMatchObject({ response: { status: 401 } });
    expect(handler).toHaveBeenCalledTimes(1);
    expect(server.seen.filter((s) => s.url === '/api/v1/x')).toHaveLength(2);
  });
});
