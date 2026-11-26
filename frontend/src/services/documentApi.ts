import { apiClient } from './apiClient';

export interface DocumentStatus {
  id: string;
  kb_id: string;
  filename: string;
  status: string;

  parse_task_id?: string | null;
  parse_progress: number;
  parse_message?: string | null;

  index_task_id?: string | null;
  index_progress: number;
  index_message?: string | null;

  error_message?: string | null;

  created_at?: string | null;
  updated_at?: string | null;
}

export interface DocumentListResponse {
  items: DocumentStatus[];
}

export interface DocumentUploadResponse {
  id: string;
  kb_id: string;
  filename: string;
  status: string;
  task_id: string;
}

export const listDocumentsForKnowledgeBase = async (kbId: string): Promise<DocumentStatus[]> => {
  const res = await apiClient.get<DocumentListResponse>(`/api/v1/knowledgebases/${kbId}/documents`);
  return res.data.items ?? [];
};

export const uploadDocumentToKnowledgeBase = async (
  kbId: string,
  file: File,
  options?: { from_page?: number; to_page?: number },
): Promise<DocumentUploadResponse> => {
  const formData = new FormData();
  formData.append('file', file);
  if (options?.from_page != null) {
    formData.append('from_page', String(options.from_page));
  }
  if (options?.to_page != null) {
    formData.append('to_page', String(options.to_page));
  }

  const res = await apiClient.post<DocumentUploadResponse>(
    `/api/v1/knowledgebases/${kbId}/documents`,
    formData,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
    },
  );
  return res.data;
};

export const getDocumentStatus = async (docId: string): Promise<DocumentStatus> => {
  const res = await apiClient.get<DocumentStatus>(`/api/v1/documents/${docId}`);
  return res.data;
};

export const deleteDocument = async (docId: string): Promise<void> => {
  await apiClient.delete(`/api/v1/documents/${docId}`);
};