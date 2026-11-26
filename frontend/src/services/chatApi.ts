import { apiBaseUrl, apiClient, getAuthHeaders } from './apiClient';
import { SseParser } from './sse';

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
  params: { offset?: number; limit?: number; latest?: boolean } = {},
): Promise<MessageHistoryResponse> => {
  const searchParams = new URLSearchParams();
  if (params.offset != null) searchParams.set('offset', String(params.offset));
  if (params.limit != null) searchParams.set('limit', String(params.limit));
  if (params.latest) searchParams.set('latest', 'true');
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

export interface StreamHandlers {
  /** The user message was saved; `citations` are the sources the answer will use. */
  onMeta?: (userMessage: ChatMessage, citations: Citation[]) => void;
  onDelta?: (text: string) => void;
}

/**
 * Send a message and stream the answer (server-sent events over a POST).
 * Resolves with the saved assistant message; rejects on HTTP or generation errors,
 * or with an AbortError if `signal` is aborted.
 */
export const streamChatMessage = async (
  sessionId: string,
  payload: SendMessagePayload,
  handlers: StreamHandlers = {},
  signal?: AbortSignal,
): Promise<ChatMessage> => {
  // axios can't expose a streamed body in the browser, so use fetch directly.
  const res = await fetch(`${apiBaseUrl}/api/v1/chat/sessions/${sessionId}/messages/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...getAuthHeaders() },
    body: JSON.stringify(payload),
    signal,
  });

  if (!res.ok || !res.body) {
    let detail = `Request failed (${res.status})`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      // non-JSON error body
    }
    throw new Error(detail);
  }

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  const parser = new SseParser();
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    for (const evt of parser.push(value)) {
      const data = JSON.parse(evt.data);
      switch (evt.event) {
        case 'meta':
          handlers.onMeta?.(data.user_message as ChatMessage, data.citations as Citation[]);
          break;
        case 'delta':
          handlers.onDelta?.(data.text as string);
          break;
        case 'done':
          await reader.cancel();
          return data as ChatMessage;
        case 'error':
          throw new Error(data.detail ?? 'Generation failed');
      }
    }
  }
  throw new Error('Stream ended before the answer was complete');
};