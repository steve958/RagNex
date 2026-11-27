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
  // The page range is a query parameter; as form fields the server would ignore it.
  const params: Record<string, number> = {};
  if (options?.from_page != null) params.from_page = options.from_page;
  if (options?.to_page != null) params.to_page = options.to_page;

  const res = await apiClient.post<DocumentUploadResponse>(
    `/api/v1/knowledgebases/${kbId}/documents`,
    formData,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
      params,
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
/** Parse and index the stored file again (e.g. after a failure). 409 if it's already being
 *  processed or the original file is gone. */
export const reprocessDocument = async (docId: string): Promise<DocumentStatus> => {
  const res = await apiClient.post<DocumentStatus>(`/api/v1/documents/${docId}/reprocess`);
  return res.data;
};

export interface ReprocessFailedResult {
  queued: string[];
  skipped: { id: string; filename: string; reason: string }[];
}

export const reprocessFailedDocuments = async (kbId: string): Promise<ReprocessFailedResult> => {
  const res = await apiClient.post<ReprocessFailedResult>(`/api/v1/knowledgebases/${kbId}/documents/reprocess-failed`);
  return res.data;
};

/** Statuses in which parsing/indexing is still running (mirrors the backend's _IN_PROGRESS).
 *  "done" means parsed and waiting for indexing. */
export const isProcessing = (status: string): boolean =>
  ['pending', 'parsing', 'done', 'indexing'].includes(status.toLowerCase());

/** The file name a Content-Disposition header asks for (RFC 6266), or null. */
export const filenameFromDisposition = (header: string | undefined | null): string | null => {
  if (!header) return null;
  const extended = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (extended) {
    try {
      return decodeURIComponent(extended[1].trim());
    } catch {
      // Malformed encoding: fall through to the plain name.
    }
  }
  const plain = /filename="([^"]*)"/i.exec(header);
  return plain ? plain[1] : null;
};

/** Download the original uploaded file and save it in the browser. The request carries the
 *  sign-in token, so a plain link wouldn't work; the file is fetched, then saved. */
export const downloadDocument = async (docId: string, fallbackName = 'document'): Promise<void> => {
  let res;
  try {
    res = await apiClient.get<Blob>(`/api/v1/documents/${docId}/file`, { responseType: 'blob' });
  } catch (err: unknown) {
    // With responseType 'blob', error bodies arrive as a Blob too: turn them back into JSON
    // so the server's message ("isn't stored", "not found") can be shown.
    const response = (err as { response?: { data?: unknown } }).response;
    if (response?.data instanceof Blob) {
      try {
        response.data = JSON.parse(await response.data.text());
      } catch {
        // Not JSON: leave it; the caller shows a generic message.
      }
    }
    throw err;
  }
  const name = filenameFromDisposition(res.headers['content-disposition']) ?? fallbackName;
  const url = URL.createObjectURL(res.data);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revoke later: some browsers start reading the blob only after click() returns.
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
};
