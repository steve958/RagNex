import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { createApiKey, listApiKeys, revokeApiKey } from '../../services/apiKeysApi';
import { useToast } from '../common/ToastProvider';

export const ApiKeysSection: React.FC = () => {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { data, isLoading, isError } = useQuery({
    queryKey: ['api-keys'],
    queryFn: listApiKeys,
  });

  const [name, setName] = useState('');
  const [scopeRead, setScopeRead] = useState(true);
  const [scopeWrite, setScopeWrite] = useState(false);
  const [createdKey, setCreatedKey] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: createApiKey,
    onSuccess: (res) => {
      setCreatedKey(res.api_key);
      setName('');
      setScopeRead(true);
      setScopeWrite(false);
      queryClient.invalidateQueries({ queryKey: ['api-keys'] });
      showToast('API key created', 'success');
    },
    onError: () => {
      showToast('Failed to create API key', 'error');
    },
  });

  const revokeMutation = useMutation({
    mutationFn: revokeApiKey,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] });
      showToast('API key revoked', 'success');
    },
    onError: () => {
      showToast('Failed to revoke API key', 'error');
    },
  });

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    const scopes: string[] = [];
    if (scopeRead) scopes.push('read');
    if (scopeWrite) scopes.push('write');
    await createMutation.mutateAsync({ name, scopes });
  };

  const keys = data ?? [];

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-slate-100 mb-1">API keys</h2>
        <p className="text-xs text-slate-400">
          Create and manage API keys for programmatic access. Keys are shown only once when created; store them
          securely.
        </p>
      </div>

      <form onSubmit={handleCreate} className="space-y-2 rounded border border-slate-800 bg-slate-950/60 p-3 text-xs">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <div className="flex-1 space-y-1">
            <label className="block text-slate-200" htmlFor="api-key-name">
              Name
            </label>
            <input
              id="api-key-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100 focus:outline-none focus:ring-1 focus:ring-sky-500"
            />
          </div>
          <div className="flex items-center gap-3">
            <label className="inline-flex items-center gap-1">
              <input
                type="checkbox"
                checked={scopeRead}
                onChange={(e) => setScopeRead(e.target.checked)}
                className="h-3 w-3 rounded border-slate-600 bg-slate-900"
              />
              <span>read</span>
            </label>
            <label className="inline-flex items-center gap-1">
              <input
                type="checkbox"
                checked={scopeWrite}
                onChange={(e) => setScopeWrite(e.target.checked)}
                className="h-3 w-3 rounded border-slate-600 bg-slate-900"
              />
              <span>write</span>
            </label>
          </div>
          <p className="text-[11px] text-slate-500">
            read: list and search documents. write: also upload, delete and chat. A key works only in this workspace and
            can't manage members, settings or other keys.
          </p>
          <button
            type="submit"
            disabled={createMutation.isPending || (!scopeRead && !scopeWrite)}
            className="rounded bg-sky-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-sky-500 disabled:opacity-60"
          >
            {createMutation.isPending ? 'Creating…' : 'Create key'}
          </button>
        </div>
        {createdKey && (
          <div className="mt-2 rounded border border-amber-600 bg-amber-950/30 p-2 text-[11px] text-amber-100">
            <p className="font-semibold mb-1">New key created</p>
            <p className="font-mono break-all">{createdKey}</p>
            <p className="mt-1">Copy this key now. You will not be able to see it again.</p>
          </div>
        )}
      </form>

      <div className="rounded border border-slate-800 bg-slate-950/60 p-3 text-xs">
        <h3 className="mb-2 font-semibold text-slate-100">Existing keys</h3>
        {isLoading && <p className="text-slate-400">Loading API keys…</p>}
        {isError && <p className="text-red-400">Failed to load API keys.</p>}
        {!isLoading && !isError && keys.length === 0 && (
          <p className="text-slate-500">No API keys yet.</p>
        )}
        {!isLoading && !isError && keys.length > 0 && (
          <ul className="divide-y divide-slate-800">
            {keys.map((k) => {
              const isRevoked = !!k.revoked_at;
              return (
                <li key={k.id} className="flex items-center justify-between gap-2 py-2">
                  <div className="min-w-0">
                    <p className="text-slate-100 text-xs">{k.name}</p>
                    <p className="text-[11px] text-slate-400">
                      Scopes: {k.scopes.join(', ') || 'none'} • Status:{' '}
                      <span className={isRevoked ? 'text-red-400' : 'text-emerald-400'}>
                        {isRevoked ? 'Revoked' : 'Active'}
                      </span>
                    </p>
                  </div>
                  <button
                    type="button"
                    disabled={isRevoked || revokeMutation.isPending}
                    onClick={() => revokeMutation.mutate(k.id)}
                    className="rounded border border-slate-700 px-2 py-1 text-[11px] text-slate-200 hover:bg-slate-800 disabled:opacity-50"
                  >
                    Revoke
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
};