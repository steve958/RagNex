import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';

import { getKnowledgeBase, KnowledgeBase } from '../services/kbApi';
import { DocumentDetailModal } from '../components/documents/DocumentDetailModal';
import { DocumentList } from '../components/documents/DocumentList';
import { DocumentUploadForm } from '../components/documents/DocumentUploadForm';
import type { DocumentStatus } from '../services/documentApi';

export const KnowledgeBaseDetailPage: React.FC = () => {
  const { kbId } = useParams<{ kbId: string }>();
  const [selectedDoc, setSelectedDoc] = useState<DocumentStatus | null>(null);

  const { data, isLoading, isError } = useQuery<KnowledgeBase | undefined>({
    queryKey: ['knowledge-base', kbId],
    queryFn: kbId ? () => getKnowledgeBase(kbId) : async () => undefined,
    enabled: !!kbId,
  });

  if (!kbId) {
    return <p className="text-sm text-red-400">Missing knowledge base id in route.</p>;
  }

  if (isLoading) {
    return <p className="text-sm text-slate-300">Loading knowledge base…</p>;
  }

  if (isError || !data) {
    return <p className="text-sm text-red-400">Knowledge base not found.</p>;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold mb-1">{data.name}</h1>
          <p className="text-xs uppercase tracking-wide text-slate-400">Template: {data.template}</p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            to="/"
            className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800"
          >
            Back to dashboard
          </Link>
          <Link
            to={`/knowledgebases/${kbId}/settings`}
            className="rounded bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-100 hover:bg-slate-700"
          >
            Settings
          </Link>
        </div>
      </div>

      {data.description && <p className="text-sm text-slate-200">{data.description}</p>}

      <div className="rounded border border-slate-800 bg-slate-950/60 p-4 text-sm text-slate-300 space-y-3">
        <div className="flex items-center justify-between">
          <p className="font-medium">Documents</p>
        </div>
        {kbId && <DocumentUploadForm kbId={kbId} />}
        {kbId && (
          <div className="pt-2">
            <DocumentList kbId={kbId} onDocumentClick={(doc) => setSelectedDoc(doc)} />
          </div>
        )}
      </div>

      <DocumentDetailModal open={!!selectedDoc} document={selectedDoc} onClose={() => setSelectedDoc(null)} />
    </div>
  );
};
