import React, { createContext, useContext, useEffect, useState } from 'react';

import { apiClient, setAccessToken, setTenantId } from '../services/apiClient';
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

/** Pick the tenant to work in. Users currently get one personal tenant on registration. */
const resolveTenantId = async (token: string): Promise<string | null> => {
  const res = await apiClient.get<TenantSummary[]>('/api/v1/tenants', {
    headers: { Authorization: `Bearer ${token}` },
  });
  return res.data[0]?.id ?? null;
};

export const AuthProvider: React.FC<React.PropsWithChildren> = ({ children }) => {
  // Initialise synchronously from storage so a page reload doesn't briefly look
  // logged-out (which would make ProtectedRoute redirect to /login).
  const [auth, setAuth] = useState<StoredAuth | null>(() => {
    const stored = loadStoredAuth();
    setAccessToken(stored?.accessToken ?? null);
    setTenantId(stored?.tenantId ?? null);
    return stored;
  });

  const apply = (next: StoredAuth | null) => {
    setAccessToken(next?.accessToken ?? null);
    setTenantId(next?.tenantId ?? null);
    saveStoredAuth(next);
    setAuth(next);
  };

  // Sessions stored before tenant support have tokens but no tenant: resolve it once.
  useEffect(() => {
    if (!auth || auth.tenantId) return;
    let cancelled = false;
    resolveTenantId(auth.accessToken)
      .then((tenantId) => {
        if (!cancelled) apply({ ...auth, tenantId });
      })
      .catch(() => {
        // Token likely expired or invalid: force a fresh login.
        if (!cancelled) apply(null);
      });
    return () => {
      cancelled = true;
    };
  }, [auth]);

  const authenticate = async (path: string, email: string, password: string) => {
    const res = await apiClient.post(path, { email, password });
    const { access_token, refresh_token } = res.data as {
      access_token: string;
      refresh_token: string;
    };
    const tenantId = await resolveTenantId(access_token);
    apply({ email, accessToken: access_token, refreshToken: refresh_token, tenantId });
  };

  const value: AuthState = {
    user: auth ? { email: auth.email } : null,
    accessToken: auth?.accessToken ?? null,
    refreshToken: auth?.refreshToken ?? null,
    tenantId: auth?.tenantId ?? null,
    isAuthenticated: !!auth?.accessToken,
    login: (email, password) => authenticate('/api/v1/auth/login', email, password),
    register: (email, password) => authenticate('/api/v1/auth/register', email, password),
    logout: () => apply(null),
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
