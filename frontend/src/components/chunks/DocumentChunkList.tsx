import React, { useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';

import { Chunk, listChunksForDocument } from '../../services/chunkApi';

interface Props {
  documentId: string;
  onChunkClick?: (chunk: Chunk) => void;
}

const highlightText = (text: string, query: string) => {
  if (!query.trim()) return text;
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

export const DocumentChunkList: React.FC<Props> = ({ documentId, onChunkClick }) => {
  const [page, setPage] = useState(1);
  const [inputQuery, setInputQuery] = useState('');
  const [searchQuery, setSearchQuery] = useState('');

  const { data, isLoading, isError } = useQuery({
    queryKey: ['document-chunks', documentId, page, searchQuery],
    queryFn: () => listChunksForDocument(documentId, { page, q: searchQuery || undefined }),
    placeholderData: keepPreviousData,
  });

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    setSearchQuery(inputQuery.trim());
  };

  const handlePrev = () => {
    setPage((p) => Math.max(1, p - 1));
  };

  const handleNext = () => {
    if (!data) return;
    const maxPage = Math.max(1, Math.ceil(data.total / data.size));
    setPage((p) => Math.min(maxPage, p + 1));
  };

  if (isLoading && !data) {
    return <p className="text-[11px] text-slate-400">Loading chunks…</p>;
  }

  if (isError) {
    return <p className="text-[11px] text-red-400">Failed to load chunks.</p>;
  }

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const size = data?.size ?? 20;
  const maxPage = Math.max(1, Math.ceil(total / size));

  return (
    <div className="space-y-2">
      <form onSubmit={handleSearchSubmit} className="flex items-center gap-2">
        <input
          type="text"
          value={inputQuery}
          onChange={(e) => setInputQuery(e.target.value)}
          placeholder="Search within chunks…"
          className="flex-1 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-[11px] text-slate-100 focus:outline-none focus:ring-1 focus:ring-sky-500"
        />
        <button
          type="submit"
          className="rounded bg-slate-800 px-2 py-1 text-[11px] text-slate-100 hover:bg-slate-700"
        >
          Search
        </button>
      </form>

      {items.length === 0 ? (
        <p className="text-[11px] text-slate-500">No chunks found for this document.</p>
      ) : (
        <>
          <ul className="max-h-56 overflow-auto rounded border border-slate-800 bg-slate-950/60 text-[11px] divide-y divide-slate-800">
            {items.map((chunk) => (
              <li key={chunk.id} className="px-2 py-1.5">
                <button
                  type="button"
                  onClick={() => onChunkClick?.(chunk)}
                  className="w-full text-left focus:outline-none focus:ring-1 focus:ring-sky-500"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-slate-300">
                        #{chunk.seq}
                        {chunk.page != null && <span className="text-slate-500"> • page {chunk.page}</span>}
                      </p>
                      <p className="mt-0.5 line-clamp-2 text-slate-200">
                        {highlightText(chunk.content, searchQuery).slice(0, 200)}
                      </p>
                    </div>
                  </div>
                </button>
              </li>
            ))}
          </ul>
          <div className="flex items-center justify-between text-[11px] text-slate-500">
            <span>
              Page {page} of {maxPage} • {total} chunks
            </span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={handlePrev}
                disabled={page <= 1}
                className="rounded border border-slate-700 px-2 py-0.5 hover:bg-slate-800 disabled:opacity-50"
              >
                Prev
              </button>
              <button
                type="button"
                onClick={handleNext}
                disabled={page >= maxPage}
                className="rounded border border-slate-700 px-2 py-0.5 hover:bg-slate-800 disabled:opacity-50"
              >
                Next
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
};