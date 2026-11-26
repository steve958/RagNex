import React from 'react';
import { useQuery } from '@tanstack/react-query';

import { listTenants, TenantSummary } from '../../services/tenantsApi';

export const TeamSettingsSection: React.FC = () => {
  const { data, isLoading, isError } = useQuery<TenantSummary[]>({
    queryKey: ['tenants'],
    queryFn: listTenants,
  });

  const tenants = data ?? [];

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-slate-100 mb-1">Team & tenant</h2>
        <p className="text-xs text-slate-400">
          Manage which tenants you belong to. Advanced member and role management will be added in a later phase.
        </p>
      </div>
      <div className="rounded border border-slate-800 bg-slate-950/60 p-3 text-xs">
        <h3 className="mb-2 font-semibold text-slate-100">Tenants</h3>
        {isLoading && <p className="text-slate-400">Loading tenants…</p>}
        {isError && <p className="text-red-400">Failed to load tenants.</p>}
        {!isLoading && !isError && tenants.length === 0 && (
          <p className="text-slate-500">You do not belong to any tenants yet.</p>
        )}
        {!isLoading && !isError && tenants.length > 0 && (
          <ul className="space-y-1">
            {tenants.map((t) => (
              <li key={t.id} className="flex items-center justify-between">
                <span className="text-slate-100 text-xs">{t.name}</span>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-3 text-[11px] text-slate-500">
          Tenant creation, inviting members, and changing roles are currently supported via the API. A richer UI can be
          added later.
        </p>
      </div>
    </div>
  );
};