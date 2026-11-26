import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams, Link } from 'react-router-dom';

import {
  deleteKnowledgeBase,
  getKnowledgeBase,
  KnowledgeBase,
  updateKnowledgeBase,
} from '../services/kbApi';

export const KnowledgeBaseSettingsPage: React.FC = () => {
  const { kbId } = useParams<{ kbId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data, isLoading, isError } = useQuery<KnowledgeBase | undefined>({
    queryKey: ['knowledge-base', kbId],
    queryFn: kbId ? () => getKnowledgeBase(kbId) : async () => undefined,
    enabled: !!kbId,
  });

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [template, setTemplate] = useState<'general' | 'laws' | 'paper'>('general');

  const updateMutation = useMutation({
    mutationFn: (payload: Partial<Pick<KnowledgeBase, 'name' | 'description' | 'template'>>) =>
      updateKnowledgeBase(kbId!, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge-bases'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-base', kbId] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => deleteKnowledgeBase(kbId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge-bases'] });
      navigate('/');
    },
  });

  React.useEffect(() => {
    if (data) {
      setName(data.name);
      setDescription(data.description ?? '');
      if (data.template === 'laws' || data.template === 'paper') {
        setTemplate(data.template);
      } else {
        setTemplate('general');
      }
    }
  }, [data]);

  if (!kbId) {
    return <p className="text-sm text-red-400">Missing knowledge base id in route.</p>;
  }

  if (isLoading) {
    return <p className="text-sm text-slate-300">Loading knowledge base…</p>;
  }

  if (isError || !data) {
    return <p className="text-sm text-red-400">Knowledge base not found.</p>;
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    await updateMutation.mutateAsync({ name, description, template });
  };

  const handleDelete = async () => {
    if (!window.confirm('Delete this knowledge base? This cannot be undone.')) return;
    await deleteMutation.mutateAsync();
  };

  const updateError = (updateMutation.error as any)?.response?.data?.detail;
  const deleteError = (deleteMutation.error as any)?.response?.data?.detail;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold mb-1">Knowledge base settings</h1>
          <p className="text-xs uppercase tracking-wide text-slate-400">ID: {kbId}</p>
        </div>
        <Link
          to={`/knowledgebases/${kbId}`}
          className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800"
        >
          Back to detail
        </Link>
      </div>

      <form onSubmit={handleSave} className="space-y-4 max-w-lg">
        <div className="space-y-1">
          <label className="block text-sm text-slate-300" htmlFor="kb-name">
            Name
          </label>
          <input
            id="kb-name"
            type="text"
            className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-50 focus:outline-none focus:ring-1 focus:ring-sky-500"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </div>
        <div className="space-y-1">
          <label className="block text-sm text-slate-300" htmlFor="kb-description">
            Description
          </label>
          <textarea
            id="kb-description"
            className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-50 focus:outline-none focus:ring-1 focus:ring-sky-500"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
          />
        </div>
        <div className="space-y-1">
          <label className="block text-sm text-slate-300" htmlFor="kb-template">
            Template
          </label>
          <select
            id="kb-template"
            className="w-full rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-50 focus:outline-none focus:ring-1 focus:ring-sky-500"
            value={template}
            onChange={(e) => setTemplate(e.target.value as any)}
          >
            <option value="general">General</option>
            <option value="laws">Laws</option>
            <option value="paper">Paper</option>
          </select>
        </div>
        {updateError && <p className="text-sm text-red-400">{String(updateError)}</p>}
        <button
          type="submit"
          disabled={updateMutation.isPending}
          className="rounded bg-sky-600 px-3 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-60"
        >
          {updateMutation.isPending ? 'Saving…' : 'Save changes'}
        </button>
      </form>

      <div className="mt-6 max-w-lg rounded border border-red-800 bg-red-950/40 p-4">
        <h2 className="text-sm font-semibold text-red-200 mb-2">Danger zone</h2>
        <p className="text-xs text-red-200 mb-3">
          Deleting this knowledge base will hide it from the UI. Documents and chunks remain in storage for now,
          but will no longer be reachable via the dashboard.
        </p>
        {deleteError && <p className="text-sm text-red-400 mb-2">{String(deleteError)}</p>}
        <button
          type="button"
          onClick={handleDelete}
          disabled={deleteMutation.isPending}
          className="rounded border border-red-600 px-3 py-2 text-xs font-medium text-red-100 hover:bg-red-900 disabled:opacity-60"
        >
          {deleteMutation.isPending ? 'Deleting…' : 'Delete knowledge base'}
        </button>
      </div>
    </div>
  );
};