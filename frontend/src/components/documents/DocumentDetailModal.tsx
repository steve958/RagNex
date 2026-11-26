import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { DocumentStatus, getDocumentStatus } from '../../services/documentApi';
import type { Chunk } from '../../services/chunkApi';
import { DocumentChunkList } from '../chunks/DocumentChunkList';
import { ChunkDetailModal } from '../chunks/ChunkDetailModal';

interface Props {
  open: boolean;
  document: DocumentStatus | null;
  onClose: () => void;
}

const isInProgress = (status: string) => {
  const s = status.toLowerCase();
  return s === 'pending' || s === 'processing' || s === 'parsing' || s === 'indexing';
};

export const DocumentDetailModal: React.FC<Props> = ({ open, document, onClose }) => {
  const docId = document?.id;
  const [selectedChunk, setSelectedChunk] = useState<Chunk | null>(null);
  const [chunkSearch, setChunkSearch] = useState<string>('');

  const { data } = useQuery<DocumentStatus>({
    queryKey: ['document', docId],
    queryFn: () => getDocumentStatus(docId!),
    enabled: open && !!docId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && isInProgress(status) ? 5000 : false;
    },
  });

  if (!open || !document) return null;

  const doc = data ?? document;
  const parsePct = Math.round((doc.parse_progress ?? 0) * 100);
  const indexPct = Math.round((doc.index_progress ?? 0) * 100);

  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-lg rounded border border-slate-700 bg-slate-950 p-5 shadow-lg text-sm text-slate-100">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-semibold">Document details</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-slate-700 px-2 py-1 text-xs hover:bg-slate-800"
          >
            Close
          </button>
        </div>
        <div className="space-y-2">
          <div>
            <p className="font-mono text-xs break-all">{doc.filename}</p>
            <p className="text-[11px] text-slate-400">Status: {doc.status}</p>
          </div>
          <div className="space-y-1">
            <p className="text-xs text-slate-300">Parsing</p>
            <div className="h-2 w-full overflow-hidden rounded bg-slate-800">
              <div
                className="h-full bg-sky-500"
                style={{ width: `${Math.min(100, Math.max(0, parsePct))}%` }}
              />
            </div>
            <p className="text-[11px] text-slate-500">{parsePct}% complete</p>
            {doc.parse_message && <p className="text-[11px] text-slate-400">{doc.parse_message}</p>}
          </div>
          <div className="space-y-1">
            <p className="text-xs text-slate-300">Indexing</p>
            <div className="h-2 w-full overflow-hidden rounded bg-slate-800">
              <div
                className="h-full bg-emerald-500"
                style={{ width: `${Math.min(100, Math.max(0, indexPct))}%` }}
              />
            </div>
            <p className="text-[11px] text-slate-500">{indexPct}% complete</p>
            {doc.index_message && <p className="text-[11px] text-slate-400">{doc.index_message}</p>}
          </div>
          {doc.error_message && (
            <div className="rounded border border-red-700 bg-red-950/30 p-2 text-[11px] text-red-200">
              <p className="font-semibold mb-0.5">Error</p>
              <p>{doc.error_message}</p>
            </div>
          )}
        </div>

        {doc.id && (
          <div className="mt-4 border-t border-slate-800 pt-3">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-xs font-semibold text-slate-200">Chunks</p>
              <p className="text-[11px] text-slate-500">Inspect the chunks generated for this document.</p>
            </div>
            <DocumentChunkList
              documentId={doc.id}
              onChunkClick={(chunk) => setSelectedChunk(chunk)}
            />
          </div>
        )}
      </div>

      <ChunkDetailModal open={!!selectedChunk} chunk={selectedChunk} searchTerm={chunkSearch} onClose={() => setSelectedChunk(null)} />
    </div>
  );
};
