import { apiClient } from './apiClient';

export interface KnowledgeBaseSummary {
  id: string;
  name: string;
  description: string | null;
  template: string;
}

export interface KnowledgeBase extends KnowledgeBaseSummary {}

export interface CreateKnowledgeBasePayload {
  name: string;
  description?: string;
  template?: 'general' | 'laws' | 'paper';
}

export const fetchKnowledgeBases = async (): Promise<KnowledgeBaseSummary[]> => {
  const res = await apiClient.get('/api/v1/knowledgebases');
  return res.data as KnowledgeBaseSummary[];
};

export const createKnowledgeBase = async (
  payload: CreateKnowledgeBasePayload,
): Promise<KnowledgeBaseSummary> => {
  const res = await apiClient.post('/api/v1/knowledgebases', payload);
  return res.data as KnowledgeBaseSummary;
};

export const getKnowledgeBase = async (kbId: string): Promise<KnowledgeBase> => {
  const res = await apiClient.get(`/api/v1/knowledgebases/${kbId}`);
  return res.data as KnowledgeBase;
};

export const updateKnowledgeBase = async (
  kbId: string,
  payload: Partial<Pick<KnowledgeBase, 'name' | 'description' | 'template'>>,
): Promise<KnowledgeBase> => {
  const res = await apiClient.put(`/api/v1/knowledgebases/${kbId}`, payload);
  return res.data as KnowledgeBase;
};

export const deleteKnowledgeBase = async (kbId: string): Promise<void> => {
  await apiClient.delete(`/api/v1/knowledgebases/${kbId}`);
};
