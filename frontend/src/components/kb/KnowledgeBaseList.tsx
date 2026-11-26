import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { fetchKnowledgeBases, KnowledgeBaseSummary } from '../../services/kbApi';

interface Props {
  onCreateClick: () => void;
}

export const KnowledgeBaseList: React.FC<Props> = ({ onCreateClick }) => {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['knowledge-bases'],
    queryFn: fetchKnowledgeBases,
  });

  if (isLoading) {
    return (
      <div className="space-y-3">
        <div className="h-4 w-32 rounded bg-slate-800 animate-pulse" />
        <div className="grid gap-3 sm:grid-cols-2">
          {Array.from({ length: 3 }).map((_, idx) => (
            <div
              key={idx}
              className="rounded border border-slate-800 bg-slate-950/60 p-4 animate-pulse space-y-3"
            >
              <div className="h-4 w-3/4 rounded bg-slate-800" />
              <div className="h-3 w-full rounded bg-slate-900" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="space-y-2">
        <p className="text-sm text-red-400">Failed to load knowledge bases.</p>
        <button
          type="button"
          onClick={onCreateClick}
          className="rounded bg-sky-600 px-3 py-2 text-sm font-medium text-white hover:bg-sky-500"
        >
          New knowledge base
        </button>
      </div>
    );
  }

  const items = data ?? [];

  if (items.length === 0) {
    return (
      <div className="rounded border border-dashed border-slate-700 bg-slate-950/40 p-6 text-sm text-slate-300">
        <p className="mb-3">No knowledge bases yet.</p>
        <button
          type="button"
          onClick={onCreateClick}
          className="rounded bg-sky-600 px-3 py-2 text-sm font-medium text-white hover:bg-sky-500"
        >
          Create your first knowledge base
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <h2 className="text-lg font-semibold">Knowledge bases</h2>
      <ul className="grid gap-3 sm:grid-cols-2">
        {items.map((kb: KnowledgeBaseSummary) => (
          <li key={kb.id} className="rounded border border-slate-800 bg-slate-950/60 p-4">
            <Link to={`/knowledgebases/${kb.id}`} className="block focus:outline-none focus:ring-1 focus:ring-sky-500">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h3 className="text-sm font-semibold">{kb.name}</h3>
                  {kb.description && <p className="mt-1 text-xs text-slate-400">{kb.description}</p>}
                </div>
                <span className="rounded bg-slate-800 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-300">
                  {kb.template}
                </span>
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
};