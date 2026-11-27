import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  deleteDocument,
  downloadDocument,
  DocumentStatus,
  isProcessing,
  listDocumentsForKnowledgeBase,
  reprocessDocument,
  reprocessFailedDocuments,
} from '../../services/documentApi';
import { errorDetail } from '../../services/errors';

interface Props {
  kbId: string;
  onDocumentClick?: (doc: DocumentStatus) => void;
}

export const DocumentList: React.FC<Props> = ({ kbId, onDocumentClick }) => {
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState<{ kind: 'error' | 'info'; text: string } | null>(null);

  const { data, isLoading, isError } = useQuery<DocumentStatus[]>({
    queryKey: ['documents', kbId],
    queryFn: () => listDocumentsForKnowledgeBase(kbId),
    // Keep polling while anything is parsing or indexing (including "done": parsed, not yet indexed).
    refetchInterval: (query) => (query.state.data?.some((d) => isProcessing(d.status)) ? 5000 : false),
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['documents', kbId] });

  const { mutateAsync: deleteAsync, isPending: isDeleting } = useMutation({
    mutationFn: deleteDocument,
    onSuccess: refresh,
  });

  const reprocessOne = useMutation({
    mutationFn: reprocessDocument,
    onSuccess: () => {
      setNotice(null);
      refresh();
    },
    onError: (err) => setNotice({ kind: 'error', text: errorDetail(err) }),
  });

  const reprocessAllFailed = useMutation({
    mutationFn: () => reprocessFailedDocuments(kbId),
    onSuccess: (result) => {
      const parts = [`Reprocessing ${result.queued.length} document${result.queued.length === 1 ? '' : 's'}.`];
      for (const s of result.skipped) parts.push(`Skipped ${s.filename}: ${s.reason}`);
      setNotice({ kind: result.skipped.length ? 'error' : 'info', text: parts.join(' ') });
      refresh();
    },
    onError: (err) => setNotice({ kind: 'error', text: errorDetail(err) }),
  });

  const download = useMutation({
    mutationFn: (doc: DocumentStatus) => downloadDocument(doc.id, doc.filename),
    onError: (err) => setNotice({ kind: 'error', text: errorDetail(err, 'Download failed.') }),
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

  const failedCount = docs.filter((d) => d.status === 'failed').length;
  const smallButton =
    'rounded border border-slate-700 px-2 py-1 text-[11px] text-slate-200 hover:bg-slate-800 disabled:opacity-60';

  return (
    <div className="space-y-2">
      {failedCount > 0 && (
        <div className="flex items-center justify-between gap-2 rounded border border-red-900/60 bg-red-950/20 px-3 py-2 text-[11px] text-red-200">
          <span>
            {failedCount} document{failedCount === 1 ? '' : 's'} failed to process.
          </span>
          <button
            type="button"
            disabled={reprocessAllFailed.isPending}
            onClick={() => reprocessAllFailed.mutate()}
            className={smallButton}
          >
            {reprocessAllFailed.isPending ? 'Queuing…' : `Reprocess ${failedCount} failed`}
          </button>
        </div>
      )}
      {notice && (
        <p role={notice.kind === 'error' ? 'alert' : 'status'} className={`text-[11px] ${notice.kind === 'error' ? 'text-red-400' : 'text-emerald-400'}`}>
          {notice.text}
        </p>
      )}
      <ul className="divide-y divide-slate-800 border border-slate-800 rounded bg-slate-950/60 text-xs">
        {docs.map((doc) => {
          const parsePct = Math.round((doc.parse_progress ?? 0) * 100);
          const indexPct = Math.round((doc.index_progress ?? 0) * 100);
          const failed = doc.status === 'failed';
          return (
            <li key={doc.id} className="flex items-center justify-between gap-3 px-3 py-2">
              <button
                type="button"
                onClick={() => onDocumentClick?.(doc)}
                className="min-w-0 flex-1 text-left focus:outline-none focus:ring-1 focus:ring-sky-500"
              >
                <p className="truncate text-slate-100">{doc.filename}</p>
                <p className="mt-0.5 text-[11px] text-slate-400">
                  Status: <span className={failed ? 'text-red-400' : undefined}>{doc.status}</span>
                </p>
                {doc.error_message ? (
                  <p className="mt-0.5 truncate text-[11px] text-red-300" title={doc.error_message}>
                    {doc.error_message}
                  </p>
                ) : (
                  <p className="mt-0.5 text-[11px] text-slate-500">
                    Parse: {parsePct}% • Index: {indexPct}%
                  </p>
                )}
              </button>
              <div className="flex shrink-0 gap-1">
                {failed && (
                  <button
                    type="button"
                    disabled={reprocessOne.isPending}
                    onClick={() => reprocessOne.mutate(doc.id)}
                    className={smallButton}
                  >
                    Reprocess
                  </button>
                )}
                <button
                  type="button"
                  disabled={download.isPending && download.variables?.id === doc.id}
                  onClick={() => download.mutate(doc)}
                  className={smallButton}
                  aria-label={`Download ${doc.filename}`}
                >
                  Download
                </button>
                <button type="button" disabled={isDeleting} onClick={() => handleDelete(doc)} className={smallButton}>
                  Delete
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
};