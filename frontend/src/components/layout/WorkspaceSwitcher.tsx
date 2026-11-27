import React, { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';

import { listTenants, TenantSummary } from '../../services/tenantsApi';
import { useAuth } from '../../store/auth';

export const useWorkspaces = () => useQuery<TenantSummary[]>({ queryKey: ['tenants'], queryFn: listTenants });

/** Shows the current workspace, and lets users who belong to several switch between them. */
export const WorkspaceSwitcher: React.FC<{ id?: string }> = ({ id = 'workspace-switcher' }) => {
  const { tenantId, switchTenant } = useAuth();
  const navigate = useNavigate();
  const { data: workspaces } = useWorkspaces();

  // The remembered workspace may be gone (removed from it, or it was deleted): move to
  // the first one the user still belongs to.
  useEffect(() => {
    if (workspaces?.length && tenantId && !workspaces.some((w) => w.id === tenantId)) {
      switchTenant(workspaces[0].id);
    }
  }, [workspaces, tenantId, switchTenant]);

  if (!workspaces?.length) return null;
  if (workspaces.length === 1) {
    return (
      <span className="max-w-[12rem] truncate text-xs text-slate-400" title={`Workspace: ${workspaces[0].name}`}>
        {workspaces[0].name}
      </span>
    );
  }
  return (
    <>
      <label htmlFor={id} className="sr-only">
        Workspace
      </label>
      <select
        id={id}
        value={tenantId ?? ''}
        onChange={(e) => {
          switchTenant(e.target.value);
          // Pages of the old workspace (a knowledge base, a chat) don't exist in the new one.
          navigate('/');
        }}
        className="max-w-[14rem] truncate rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-100"
      >
        {workspaces.map((w) => (
          <option key={w.id} value={w.id}>
            {w.name}
          </option>
        ))}
      </select>
    </>
  );
};
