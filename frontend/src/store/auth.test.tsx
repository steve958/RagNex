import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, waitFor } from '@testing-library/react';

import { apiClient, getAuthHeaders, refreshAccessToken } from '../services/apiClient';
import { AuthProvider, AuthState, NoTenantError, useAuth } from './auth';

const STORAGE_KEY = 'ragnex_auth';

const renderAuth = (client = new QueryClient()) => {
  const ref: { current: AuthState | null } = { current: null };
  const Probe = () => {
    ref.current = useAuth();
    return null;
  };
  render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <Probe />
      </AuthProvider>
    </QueryClientProvider>,
  );
  return ref;
};

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('AuthProvider', () => {
  it('logs out once (no request loop) when a stored session has no tenant', async () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ email: 'a@b.c', accessToken: 'tok', refreshToken: 'ref' }),
    );
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: [] });

    const auth = renderAuth();

    await waitFor(() => expect(auth.current?.isAuthenticated).toBe(false));
    // Give a looping effect the chance to fire again before counting.
    await act(() => new Promise((r) => setTimeout(r, 50)));
    expect(get).toHaveBeenCalledTimes(1);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('resolves and stores the tenant for a stored session without one', async () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ email: 'a@b.c', accessToken: 'tok', refreshToken: 'ref' }),
    );
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: [{ id: 't1', name: 'T' }] });

    const auth = renderAuth();

    await waitFor(() => expect(auth.current?.tenantId).toBe('t1'));
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY)!).tenantId).toBe('t1');
  });

  it('rejects login with NoTenantError when the account has no tenant', async () => {
    vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { access_token: 'tok', refresh_token: 'ref' } });
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: [] });

    const auth = renderAuth();

    await expect(auth.current!.login('a@b.c', 'pw')).rejects.toBeInstanceOf(NoTenantError);
    expect(auth.current?.isAuthenticated).toBe(false);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("clears cached queries on logout so the next user can't see them", async () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ email: 'a@b.c', accessToken: 'tok', refreshToken: 'ref', tenantId: 't1' }),
    );
    const client = new QueryClient();
    client.setQueryData(['chat-sessions'], [{ id: 's1', name: "previous user's chat" }]);

    const auth = renderAuth(client);
    act(() => auth.current!.logout());

    expect(client.getQueryData(['chat-sessions'])).toBeUndefined();
    expect(auth.current?.isAuthenticated).toBe(false);
  });

  it('stores refreshed tokens when apiClient asks for a refresh', async () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ email: 'a@b.c', accessToken: 'old', refreshToken: 'ref-old', tenantId: 't1' }),
    );
    const post = vi
      .spyOn(apiClient, 'post')
      .mockResolvedValue({ data: { access_token: 'new', refresh_token: 'ref-new' } });

    const auth = renderAuth();
    let token: string | null = null;
    await act(async () => {
      token = await refreshAccessToken();
    });

    expect(token).toBe('new');
    expect(post).toHaveBeenCalledWith('/api/v1/auth/refresh', { refresh_token: 'ref-old' });
    expect(auth.current?.accessToken).toBe('new');
    expect(auth.current?.isAuthenticated).toBe(true);
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY)!)).toMatchObject({
      accessToken: 'new',
      refreshToken: 'ref-new',
      tenantId: 't1',
    });
  });

  it('logs out when the refresh token is rejected', async () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ email: 'a@b.c', accessToken: 'old', refreshToken: 'ref-old', tenantId: 't1' }),
    );
    vi.spyOn(apiClient, 'post').mockRejectedValue({ response: { status: 401 } });

    const auth = renderAuth();
    await act(async () => {
      expect(await refreshAccessToken()).toBeNull();
    });

    expect(auth.current?.isAuthenticated).toBe(false);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it('stays logged in when the refresh fails for a network reason', async () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ email: 'a@b.c', accessToken: 'old', refreshToken: 'ref-old', tenantId: 't1' }),
    );
    vi.spyOn(apiClient, 'post').mockRejectedValue(new Error('Network Error'));

    const auth = renderAuth();
    await act(async () => {
      expect(await refreshAccessToken()).toBeNull();
    });

    expect(auth.current?.isAuthenticated).toBe(true);
    expect(auth.current?.accessToken).toBe('old');
  });

  it('clears cached queries when a different user logs in', async () => {
    vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { access_token: 'tok2', refresh_token: 'ref2' } });
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: [{ id: 't2', name: 'T2' }] });
    const client = new QueryClient();
    client.setQueryData(['knowledge-bases'], [{ id: 'kb', name: 'stale' }]);

    const auth = renderAuth(client);
    await act(() => auth.current!.login('b@c.d', 'pw'));

    expect(client.getQueryData(['knowledge-bases'])).toBeUndefined();
    expect(auth.current?.tenantId).toBe('t2');
  });

  it('switches workspace: stores it, sends it with requests, and drops the old cached data', async () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ email: 'a@b.c', accessToken: 'tok', refreshToken: 'ref', tenantId: 't1' }),
    );
    const client = new QueryClient();
    client.setQueryData(['knowledgebases'], [{ id: 'kb-of-t1' }]);
    const auth = renderAuth(client);

    act(() => auth.current!.switchTenant('t2'));

    expect(auth.current?.tenantId).toBe('t2');
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY)!).tenantId).toBe('t2');
    expect(client.getQueryData(['knowledgebases'])).toBeUndefined();
    // Every request (axios and the streaming fetch) now names the new workspace.
    expect(getAuthHeaders()['X-Tenant-ID']).toBe('t2');
  });
});

