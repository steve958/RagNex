import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { createKnowledgeBase } from '../../services/kbApi';
import { useToast } from '../common/ToastProvider';

interface Props {
  open: boolean;
  onClose: () => void;
}

export const KnowledgeBaseCreateModal: React.FC<Props> = ({ open, onClose }) => {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [template, setTemplate] = useState<'general' | 'laws' | 'paper'>('general');
  const queryClient = useQueryClient();
  const { showToast } = useToast();

  const { mutateAsync, isPending, error } = useMutation({
    mutationFn: createKnowledgeBase,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge-bases'] });
      showToast('Knowledge base created', 'success');
    },
    onError: () => {
      showToast('Failed to create knowledge base', 'error');
    },
  });

  if (!open) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await mutateAsync({ name, description: description || undefined, template });
    setName('');
    setDescription('');
    setTemplate('general');
    onClose();
  };

  const errDetail = (error as any)?.response?.data?.detail;

  return (
    <div className="fixed inset-0 z-20 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-md rounded border border-slate-700 bg-slate-950 p-5 shadow-lg">
        <h2 className="text-lg font-semibold mb-3">New knowledge base</h2>
        <form onSubmit={handleSubmit} className="space-y-3">
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
              Description (optional)
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
          {errDetail && <p className="text-sm text-red-400">{String(errDetail)}</p>}
          <div className="flex items-center justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-800"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isPending}
              className="rounded bg-sky-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-sky-500 disabled:opacity-60"
            >
              {isPending ? 'Creating…' : 'Create'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};