import React, { createContext, useContext, useEffect, useState } from 'react';

import { apiClient, registerAccessTokenGetter } from '../services/apiClient';

export interface AuthState {
  user: { email: string } | null;
  accessToken: string | null;
  refreshToken: string | null;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

interface StoredTokens {
  accessToken: string;
  refreshToken: string;
  email: string;
}

const STORAGE_KEY = 'ragnex_auth';

const AuthContext = createContext<AuthState | undefined>(undefined);

const loadStoredAuth = (): StoredTokens | null => {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as StoredTokens;
  } catch {
    return null;
  }
};

const saveStoredAuth = (data: StoredTokens | null) => {
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

export const AuthProvider: React.FC<React.PropsWithChildren> = ({ children }) => {
  const [user, setUser] = useState<AuthState['user']>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState<string | null>(null);

  useEffect(() => {
    const stored = loadStoredAuth();
    if (stored) {
      setUser({ email: stored.email });
      setAccessToken(stored.accessToken);
      setRefreshToken(stored.refreshToken);
    }
  }, []);

  useEffect(() => {
    registerAccessTokenGetter(() => accessToken);
  }, [accessToken]);

  const applyTokens = (email: string, access: string, refresh: string) => {
    setUser({ email });
    setAccessToken(access);
    setRefreshToken(refresh);
    saveStoredAuth({ email, accessToken: access, refreshToken: refresh });
  };

  const login = async (email: string, password: string) => {
    const res = await apiClient.post('/api/v1/auth/login', { email, password });
    const { access_token, refresh_token } = res.data as {
      access_token: string;
      refresh_token: string;
    };
    applyTokens(email, access_token, refresh_token);
  };

  const register = async (email: string, password: string) => {
    const res = await apiClient.post('/api/v1/auth/register', { email, password });
    const { access_token, refresh_token } = res.data as {
      access_token: string;
      refresh_token: string;
    };
    applyTokens(email, access_token, refresh_token);
  };

  const logout = () => {
    setUser(null);
    setAccessToken(null);
    setRefreshToken(null);
    saveStoredAuth(null);
  };

  const value: AuthState = {
    user,
    accessToken,
    refreshToken,
    isAuthenticated: !!user && !!accessToken,
    login,
    register,
    logout,
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
