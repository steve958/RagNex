import React, { useState } from 'react';

import { KnowledgeBaseList } from '../components/kb/KnowledgeBaseList';
import { KnowledgeBaseCreateModal } from '../components/kb/KnowledgeBaseCreateModal';

export const DashboardPage: React.FC = () => {
  const [showCreate, setShowCreate] = useState(false);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold mb-1">RagNex Dashboard</h1>
          <p className="text-sm text-slate-300">Manage knowledge bases and documents.</p>
        </div>
        <button
          type="button"
          onClick={() => setShowCreate(true)}
          className="rounded bg-sky-600 px-3 py-2 text-sm font-medium text-white hover:bg-sky-500"
        >
          New knowledge base
        </button>
      </div>

      <KnowledgeBaseList onCreateClick={() => setShowCreate(true)} />
      <KnowledgeBaseCreateModal open={showCreate} onClose={() => setShowCreate(false)} />
    </div>
  );
};
