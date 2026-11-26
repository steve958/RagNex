import axios from 'axios';

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
