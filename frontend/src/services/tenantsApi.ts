import { apiClient } from './apiClient';

export type WorkspaceRole = 'owner' | 'member';

export interface TenantSummary {
  id: string;
  name: string;
  /** The signed-in user's role in this workspace (missing from older servers). */
  role?: WorkspaceRole;
}

export interface Member {
  user_id: string;
  email: string;
  role: WorkspaceRole;
}

export const listTenants = async (): Promise<TenantSummary[]> => {
  const res = await apiClient.get<TenantSummary[]>('/api/v1/tenants');
  return res.data;
};

export const createTenant = async (name: string): Promise<TenantSummary> => {
  const res = await apiClient.post<TenantSummary>('/api/v1/tenants', { name });
  return { ...res.data, role: 'owner' };
};

export const listMembers = async (tenantId: string): Promise<Member[]> => {
  const res = await apiClient.get<Member[]>(`/api/v1/tenants/${tenantId}/members`);
  return res.data;
};

/** Adds a user who has an account (or changes their role if already a member). */
export const addMember = async (tenantId: string, email: string, role: WorkspaceRole): Promise<Member> => {
  const res = await apiClient.post<Member>(`/api/v1/tenants/${tenantId}/members`, { email, role });
  return res.data;
};

export const updateMemberRole = async (tenantId: string, userId: string, role: WorkspaceRole): Promise<void> => {
  await apiClient.put(`/api/v1/tenants/${tenantId}/members/${userId}`, { role });
};

export const removeMember = async (tenantId: string, userId: string): Promise<void> => {
  await apiClient.delete(`/api/v1/tenants/${tenantId}/members/${userId}`);
};
