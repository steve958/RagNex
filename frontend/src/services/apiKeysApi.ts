import { apiClient } from './apiClient';

export interface ApiKeySummary {
  id: string;
  name: string;
  scopes: string[];
  created_at: string;
  revoked_at: string | null;
}

export interface CreateApiKeyPayload {
  name: string;
  scopes: string[];
}

export interface CreateApiKeyResponse {
  api_key: string;
  id: string;
}

export const listApiKeys = async (): Promise<ApiKeySummary[]> => {
  const res = await apiClient.get<ApiKeySummary[]>('/api/v1/api-keys');
  return res.data;
};

export const createApiKey = async (payload: CreateApiKeyPayload): Promise<CreateApiKeyResponse> => {
  const res = await apiClient.post<CreateApiKeyResponse>('/api/v1/api-keys', payload);
  return res.data;
};

export const revokeApiKey = async (id: string): Promise<void> => {
  await apiClient.post('/api/v1/api-keys/revoke', { id });
};