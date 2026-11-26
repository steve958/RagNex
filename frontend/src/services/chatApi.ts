import { apiClient } from './apiClient';

export interface ChatSession {
  id: string;
  name: string | null;
  system_prompt: string | null;
  kb_ids: string[];
  created_at: string;
}

export interface CreateChatSessionPayload {
  kb_ids: string[];
  system_prompt?: string | null;
  name?: string | null;
}

export interface Citation {
  chunk_id: string;
  doc_id: string;
  kb_id: string;
  score: number;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | string;
  content: string;
  citations: Citation[];
  created_at: string;
}

export interface MessageHistoryItem extends ChatMessage {
  token_estimate: number;
}

export interface MessageHistoryResponse {
  items: MessageHistoryItem[];
  total: number;
  offset: number;
  limit: number;
}

export interface SendMessagePayload {
  content: string;
  top_k?: number;
}

export const listChatSessions = async (): Promise<ChatSession[]> => {
  const res = await apiClient.get<ChatSession[]>('/api/v1/chat/sessions');
  return res.data;
};

export const createChatSession = async (payload: CreateChatSessionPayload): Promise<ChatSession> => {
  const res = await apiClient.post<ChatSession>('/api/v1/chat/sessions', payload);
  return res.data;
};

export const deleteChatSession = async (sessionId: string): Promise<void> => {
  await apiClient.delete(`/api/v1/chat/sessions/${sessionId}`);
};

export const getChatSession = async (sessionId: string): Promise<ChatSession> => {
  const res = await apiClient.get<ChatSession>(`/api/v1/chat/sessions/${sessionId}`);
  return res.data;
};

export const getMessageHistory = async (
  sessionId: string,
  params: { offset?: number; limit?: number } = {},
): Promise<MessageHistoryResponse> => {
  const searchParams = new URLSearchParams();
  if (params.offset != null) searchParams.set('offset', String(params.offset));
  if (params.limit != null) searchParams.set('limit', String(params.limit));
  const query = searchParams.toString();
  const url = `/api/v1/chat/sessions/${sessionId}/messages${query ? `?${query}` : ''}`;
  const res = await apiClient.get<MessageHistoryResponse>(url);
  return res.data;
};

export const sendChatMessage = async (
  sessionId: string,
  payload: SendMessagePayload,
): Promise<ChatMessage> => {
  const res = await apiClient.post<ChatMessage>(`/api/v1/chat/sessions/${sessionId}/messages`, payload);
  return res.data;
};