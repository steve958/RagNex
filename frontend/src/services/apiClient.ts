import axios from 'axios';

const apiBaseUrl = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

let accessTokenGetter: (() => string | null) | null = null;

export const registerAccessTokenGetter = (fn: () => string | null) => {
  accessTokenGetter = fn;
};

export const apiClient = axios.create({
  baseURL: apiBaseUrl,
});

apiClient.interceptors.request.use((config) => {
  if (accessTokenGetter) {
    const token = accessTokenGetter();
    if (token) {
      config.headers = config.headers ?? {};
      // FastAPI expects standard Authorization: Bearer <token>
      (config.headers as any).Authorization = `Bearer ${token}`;
    }
  }
  return config;
});
