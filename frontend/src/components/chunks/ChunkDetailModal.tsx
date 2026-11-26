import React from 'react';

import type { Chunk } from '../../services/chunkApi';

interface Props {
  open: boolean;
  chunk: Chunk | null;
  searchTerm?: string;
  onClose: () => void;
}

const highlightText = (text: string, query: string | undefined) => {
  if (!query || !query.trim()) return text;
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const regex = new RegExp(`(${escaped})`, 'gi');
  const parts = text.split(regex);
  return parts.map((part, idx) =>
    regex.test(part) ? (
      <mark key={idx} className="bg-sky-800 text-sky-50">
        {part}
      </mark>
    ) : (
      <span key={idx}>{part}</span>
    ),
  );
};

export const ChunkDetailModal: React.FC<Props> = ({ open, chunk, searchTerm, onClose }) => {
  if (!open || !chunk) return null;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/70">
      <div className="w-full max-w-3xl max-h-[80vh] overflow-auto rounded border border-slate-700 bg-slate-950 p-5 shadow-lg text-sm text-slate-100">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-semibold">Chunk #{chunk.seq}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-slate-700 px-2 py-1 text-xs hover:bg-slate-800"
          >
            Close
          </button>
        </div>
        <p className="mb-2 text-[11px] text-slate-400">
          Document ID: <span className="font-mono">{chunk.document_id}</span>
          {chunk.page != null && <span> • page {chunk.page}</span>}
          {chunk.token_count != null && <span> • tokens {chunk.token_count}</span>}
        </p>
        <div className="whitespace-pre-wrap break-words text-sm leading-relaxed">
          {highlightText(chunk.content, searchTerm)}
        </div>
      </div>
    </div>
  );
};