import { apiClient } from './apiClient';

export interface Chunk {
  id: string;
  document_id: string;
  seq: number;
  content: string;
  token_count?: number | null;
  page?: number | null;
  position: Record<string, unknown>;
}

export interface ChunkListResponse {
  items: Chunk[];
  page: number;
  size: number;
  total: number;
}

export interface ListChunksParams {
  page?: number;
  size?: number;
  q?: string;
}

export const listChunksForDocument = async (
  documentId: string,
  params: ListChunksParams = {},
): Promise<ChunkListResponse> => {
  const searchParams = new URLSearchParams();
  if (params.page != null) searchParams.set('page', String(params.page));
  if (params.size != null) searchParams.set('size', String(params.size));
  if (params.q) searchParams.set('q', params.q);

  const query = searchParams.toString();
  const url = `/api/v1/documents/${documentId}/chunks${query ? `?${query}` : ''}`;

  const res = await apiClient.get<ChunkListResponse>(url);
  return res.data;
};

export const getChunk = async (chunkId: string): Promise<Chunk> => {
  const res = await apiClient.get<Chunk>(`/api/v1/chunks/${chunkId}`);
  return res.data;
};