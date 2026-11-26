import React from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { deleteDocument, DocumentStatus, listDocumentsForKnowledgeBase } from '../../services/documentApi';

interface Props {
  kbId: string;
  onDocumentClick?: (doc: DocumentStatus) => void;
}

const isInProgress = (status: string) => {
  const s = status.toLowerCase();
  return s === 'pending' || s === 'processing' || s === 'parsing' || s === 'indexing';
};

export const DocumentList: React.FC<Props> = ({ kbId, onDocumentClick }) => {
  const queryClient = useQueryClient();

  const { data, isLoading, isError } = useQuery<DocumentStatus[]>({
    queryKey: ['documents', kbId],
    queryFn: () => listDocumentsForKnowledgeBase(kbId),
    refetchInterval: (query) =>
      query.state.data?.some((d) => isInProgress(d.status)) ? 5000 : false,
  });

  const { mutateAsync: deleteAsync, isPending: isDeleting } = useMutation({
    mutationFn: deleteDocument,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents', kbId] });
    },
  });

  const handleDelete = async (doc: DocumentStatus) => {
    const ok = window.confirm(`Delete document "${doc.filename}"? This will remove it from this knowledge base.`);
    if (!ok) return;
    await deleteAsync(doc.id);
  };

  if (isLoading) {
    return (
      <ul className="divide-y divide-slate-800 border border-slate-800 rounded bg-slate-950/60 text-xs animate-pulse">
        {Array.from({ length: 3 }).map((_, idx) => (
          <li key={idx} className="flex items-center justify-between gap-3 px-3 py-2">
            <div className="flex-1 space-y-1">
              <div className="h-3 w-2/3 rounded bg-slate-800" />
              <div className="h-2 w-1/2 rounded bg-slate-900" />
            </div>
            <div className="h-6 w-12 rounded bg-slate-800" />
          </li>
        ))}
      </ul>
    );
  }

  if (isError) {
    return <p className="text-xs text-red-400">Failed to load documents.</p>;
  }

  const docs = data ?? [];

  if (docs.length === 0) {
    return <p className="text-xs text-slate-400">No documents have been uploaded to this knowledge base yet.</p>;
  }

  return (
    <ul className="divide-y divide-slate-800 border border-slate-800 rounded bg-slate-950/60 text-xs">
      {docs.map((doc) => {
        const parsePct = Math.round((doc.parse_progress ?? 0) * 100);
        const indexPct = Math.round((doc.index_progress ?? 0) * 100);
        const hasError = !!doc.error_message;
        return (
          <li key={doc.id} className="flex items-center justify-between gap-3 px-3 py-2">
            <button
              type="button"
              onClick={() => onDocumentClick?.(doc)}
              className="flex-1 text-left focus:outline-none focus:ring-1 focus:ring-sky-500"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-slate-100">{doc.filename}</p>
                  <p className="mt-0.5 text-[11px] text-slate-400">
                    Status: {doc.status}
                    {hasError && <span className="text-red-400"> • Error</span>}
                  </p>
                  <p className="mt-0.5 text-[11px] text-slate-500">
                    Parse: {parsePct}% • Index: {indexPct}%
                  </p>
                </div>
              </div>
            </button>
            <button
              type="button"
              disabled={isDeleting}
              onClick={() => handleDelete(doc)}
              className="rounded border border-slate-700 px-2 py-1 text-[11px] text-slate-200 hover:bg-slate-800 disabled:opacity-60"
            >
              Delete
            </button>
          </li>
        );
      })}
    </ul>
  );
};