import { apiClient } from './apiClient';

export interface TenantSummary {
  id: string;
  name: string;
}

export const listTenants = async (): Promise<TenantSummary[]> => {
  const res = await apiClient.get<TenantSummary[]>('/api/v1/tenants');
  return res.data;
};