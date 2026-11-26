import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';

declare module 'axios' {
  interface AxiosRequestConfig {
    /** Don't try to refresh the access token if this request gets a 401. */
    skipAuthRefresh?: boolean;
    /** Set on the one retry after a refresh, so a request is never retried twice. */
    _authRetried?: boolean;
  }
}

// Empty = same origin: the Vite dev proxy (vite.config.ts) or a reverse proxy in production
// forwards /api to the backend. Set VITE_API_URL to call a different origin directly
// (that origin must then be listed in the backend's CORS_ORIGINS).
export const apiBaseUrl: string = import.meta.env.VITE_API_URL ?? '';

// Auth context is held at module level and updated synchronously by the auth store,
// so requests fired during the first render (before any effect runs) are authenticated.
let accessToken: string | null = null;
let tenantId: string | null = null;

export const setAccessToken = (token: string | null) => {
  accessToken = token;
};

export const setTenantId = (id: string | null) => {
  tenantId = id;
};

/** Headers every authenticated request needs; shared by axios and raw fetch (streaming). */
export const getAuthHeaders = (): Record<string, string> => {
  const headers: Record<string, string> = {};
  // FastAPI expects standard Authorization: Bearer <token>
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  // Tenant-scoped endpoints reject requests without this header.
  if (tenantId) headers['X-Tenant-ID'] = tenantId;
  return headers;
};

// --- Access token refresh ---------------------------------------------------------------

/** Exchanges the refresh token for new tokens; resolves to the new access token, or null
 *  if the session can't be refreshed. Provided by the auth store. */
type RefreshHandler = () => Promise<string | null>;

let refreshHandler: RefreshHandler | null = null;
let inflightRefresh: Promise<string | null> | null = null;

export const setRefreshHandler = (fn: RefreshHandler | null) => {
  refreshHandler = fn;
};

/** Refresh the access token. Concurrent callers share one refresh request. */
export const refreshAccessToken = (): Promise<string | null> => {
  if (!refreshHandler) return Promise.resolve(null);
  if (!inflightRefresh) {
    inflightRefresh = refreshHandler()
      .catch(() => null)
      .finally(() => {
        inflightRefresh = null;
      });
  }
  return inflightRefresh;
};

/** A fresh access token after a 401 made with `sentAuthorization`, or null if none. */
export const getTokenAfter401 = async (sentAuthorization: string | undefined): Promise<string | null> => {
  // Another request already refreshed while this one was in flight: just use that token.
  if (accessToken && sentAuthorization !== `Bearer ${accessToken}`) return accessToken;
  return refreshAccessToken();
};

// Never refresh-and-retry these: their 401s mean bad credentials, not an expired token.
const AUTH_ENDPOINTS = ['/api/v1/auth/login', '/api/v1/auth/register', '/api/v1/auth/refresh'];

export const apiClient = axios.create({
  baseURL: apiBaseUrl,
});

apiClient.interceptors.request.use((config) => {
  for (const [name, value] of Object.entries(getAuthHeaders())) {
    // Don't override a header the caller set explicitly (e.g. a token during login).
    if (!config.headers.has(name)) config.headers.set(name, value);
  }
  return config;
});

apiClient.interceptors.response.use(undefined, async (error: AxiosError) => {
  const config = error.config as InternalAxiosRequestConfig | undefined;
  if (
    error.response?.status !== 401 ||
    !config ||
    config._authRetried ||
    config.skipAuthRefresh ||
    AUTH_ENDPOINTS.some((path) => config.url?.endsWith(path))
  ) {
    throw error;
  }

  const token = await getTokenAfter401(config.headers.get('Authorization')?.toString());
  if (!token) throw error;

  // A 401 means the request was rejected before doing anything, so retrying is safe.
  config._authRetried = true;
  config.headers.set('Authorization', `Bearer ${token}`);
  return apiClient(config);
});
