import React, { createContext, useContext, useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { apiClient, setAccessToken, setRefreshHandler, setTenantId } from '../services/apiClient';
import { TenantSummary } from '../services/tenantsApi';

export interface AuthState {
  user: { email: string } | null;
  accessToken: string | null;
  refreshToken: string | null;
  /** Tenant sent as X-Tenant-ID on every request; null while it is being resolved. */
  tenantId: string | null;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
  /** Work in another workspace. Cached data of the current one is dropped. */
  switchTenant: (tenantId: string) => void;
}

interface StoredAuth {
  accessToken: string;
  refreshToken: string;
  email: string;
  tenantId?: string | null;
}

const STORAGE_KEY = 'ragnex_auth';

const AuthContext = createContext<AuthState | undefined>(undefined);

const loadStoredAuth = (): StoredAuth | null => {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as StoredAuth;
  } catch {
    return null;
  }
};

const saveStoredAuth = (data: StoredAuth | null) => {
  try {
    if (!data) {
      window.localStorage.removeItem(STORAGE_KEY);
    } else {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
    }
  } catch {
    // ignore storage errors
  }
};

/** The account can authenticate but belongs to no tenant, so the app is unusable. */
export class NoTenantError extends Error {
  constructor() {
    super('Your account is not a member of any workspace. Ask an administrator to add you.');
    this.name = 'NoTenantError';
  }
}

/** Pick the tenant to work in. Users currently get one personal tenant on registration.
 *  `allowRefresh=false` for a token that doesn't belong to the stored session (login),
 *  so a 401 can't trigger a refresh with the previous user's refresh token. */
const resolveTenantId = async (token: string, allowRefresh: boolean): Promise<string | null> => {
  const res = await apiClient.get<TenantSummary[]>('/api/v1/tenants', {
    headers: { Authorization: `Bearer ${token}` },
    skipAuthRefresh: !allowRefresh,
  });
  return res.data[0]?.id ?? null;
};

type TokenPair = { access_token: string; refresh_token: string };

export const AuthProvider: React.FC<React.PropsWithChildren> = ({ children }) => {
  const queryClient = useQueryClient();
  // Initialise synchronously from storage so a page reload doesn't briefly look
  // logged-out (which would make ProtectedRoute redirect to /login).
  const [auth, setAuth] = useState<StoredAuth | null>(() => {
    const stored = loadStoredAuth();
    setAccessToken(stored?.accessToken ?? null);
    setTenantId(stored?.tenantId ?? null);
    return stored;
  });
  // Latest auth, readable from async callbacks without waiting for a re-render.
  const authRef = useRef(auth);

  const apply = (next: StoredAuth | null) => {
    authRef.current = next;
    setAccessToken(next?.accessToken ?? null);
    setTenantId(next?.tenantId ?? null);
    saveStoredAuth(next);
    setAuth(next);
  };

  // Drop every cached query when the identity changes, so the next user never sees
  // the previous user's sessions, knowledge bases or messages.
  const switchIdentity = (next: StoredAuth | null) => {
    queryClient.clear();
    apply(next);
  };

  // Exchange the refresh token for new tokens (called by apiClient on a 401). Returns the
  // new access token, or null. Only a rejected refresh token ends the session; a network
  // error just fails the request that triggered it.
  const refreshTokens = async (): Promise<string | null> => {
    const current = authRef.current;
    if (!current) return null;
    try {
      const res = await apiClient.post<TokenPair>('/api/v1/auth/refresh', {
        refresh_token: current.refreshToken,
      });
      // Re-read: the user may have logged out (or in as someone else) meanwhile.
      if (authRef.current?.refreshToken !== current.refreshToken) return null;
      apply({ ...current, accessToken: res.data.access_token, refreshToken: res.data.refresh_token });
      return res.data.access_token;
    } catch (err) {
      const status = (err as { response?: { status?: number } }).response?.status;
      if ((status === 401 || status === 403) && authRef.current === current) switchIdentity(null);
      return null;
    }
  };
  // Registered during render, not in an effect: children's queries start before this
  // component's effects run, and after a reload they may already need a refresh.
  setRefreshHandler(refreshTokens);

  // Sessions stored before tenant support have tokens but no tenant: resolve it once.
  useEffect(() => {
    if (!auth || auth.tenantId) return;
    let cancelled = false;
    resolveTenantId(auth.accessToken, true)
      .then((tenantId) => {
        const latest = authRef.current;
        if (cancelled || !latest) return;
        // No tenant: log out rather than store tenantId=null again, which would re-run
        // this effect forever. The login form then explains the problem.
        // `latest`, not `auth`: a token refresh may have happened during the lookup.
        if (tenantId) apply({ ...latest, tenantId });
        else switchIdentity(null);
      })
      .catch(() => {
        // Token likely expired or invalid: force a fresh login.
        if (!cancelled) switchIdentity(null);
      });
    return () => {
      cancelled = true;
    };
  }, [auth]);

  const authenticate = async (path: string, email: string, password: string) => {
    const res = await apiClient.post<TokenPair>(path, { email, password });
    const { access_token, refresh_token } = res.data;
    const tenantId = await resolveTenantId(access_token, false);
    if (!tenantId) throw new NoTenantError();
    switchIdentity({ email, accessToken: access_token, refreshToken: refresh_token, tenantId });
  };

  const value: AuthState = {
    user: auth ? { email: auth.email } : null,
    accessToken: auth?.accessToken ?? null,
    refreshToken: auth?.refreshToken ?? null,
    tenantId: auth?.tenantId ?? null,
    isAuthenticated: !!auth?.accessToken,
    login: (email, password) => authenticate('/api/v1/auth/login', email, password),
    register: (email, password) => authenticate('/api/v1/auth/register', email, password),
    logout: () => switchIdentity(null),
    switchTenant: (tenantId) => {
      const current = authRef.current;
      if (!current || current.tenantId === tenantId) return;
      // Everything cached (knowledge bases, documents, chats) belongs to the old workspace.
      queryClient.clear();
      apply({ ...current, tenantId });
    },
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = (): AuthState => {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return ctx;
};
