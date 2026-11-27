import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';

import { errorDetail } from '../../services/errors';
import {
  addMember,
  createTenant,
  listMembers,
  Member,
  removeMember,
  updateMemberRole,
  WorkspaceRole,
} from '../../services/tenantsApi';
import { useAuth } from '../../store/auth';
import { useWorkspaces } from '../layout/WorkspaceSwitcher';

const input =
  'rounded border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-50 focus:outline-none focus:ring-1 focus:ring-sky-500';
const button = 'rounded border border-slate-700 px-2 py-1 text-[11px] hover:bg-slate-800 disabled:opacity-50';

const RoleSelect: React.FC<{
  id: string;
  value: WorkspaceRole;
  onChange: (role: WorkspaceRole) => void;
  disabled?: boolean;
  label: string;
}> = ({ id, value, onChange, disabled, label }) => (
  <>
    <label htmlFor={id} className="sr-only">
      {label}
    </label>
    <select
      id={id}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value as WorkspaceRole)}
      className={input}
    >
      <option value="member">Member</option>
      <option value="owner">Owner</option>
    </select>
  </>
);

const Members: React.FC<{ tenantId: string; isOwner: boolean; myEmail: string | undefined }> = ({
  tenantId,
  isOwner,
  myEmail,
}) => {
  const queryClient = useQueryClient();
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<WorkspaceRole>('member');
  const [notice, setNotice] = useState<{ kind: 'error' | 'info'; text: string } | null>(null);

  const { data: members, isLoading, isError } = useQuery<Member[]>({
    queryKey: ['members', tenantId],
    queryFn: () => listMembers(tenantId),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['members', tenantId] });
  const fail = (err: unknown) => setNotice({ kind: 'error', text: errorDetail(err, 'That did not work. Please try again.') });

  const add = useMutation({
    mutationFn: () => addMember(tenantId, email.trim(), role),
    onSuccess: (m) => {
      setNotice({ kind: 'info', text: `${m.email} is now ${m.role === 'owner' ? 'an owner' : 'a member'}.` });
      setEmail('');
      setRole('member');
      refresh();
    },
    onError: fail,
  });
  const changeRole = useMutation({
    mutationFn: ({ userId, newRole }: { userId: string; newRole: WorkspaceRole }) =>
      updateMemberRole(tenantId, userId, newRole),
    onSuccess: () => {
      setNotice(null);
      refresh();
    },
    onError: (err) => {
      fail(err);
      refresh(); // put the select back to the real role
    },
  });
  const remove = useMutation({
    mutationFn: (userId: string) => removeMember(tenantId, userId),
    onSuccess: () => {
      setNotice(null);
      refresh();
    },
    onError: fail,
  });

  return (
    <div className="rounded border border-slate-800 bg-slate-950/60 p-3 text-xs">
      <h3 className="mb-2 font-semibold text-slate-100">Members</h3>
      {isLoading && <p className="text-slate-400">Loading members…</p>}
      {isError && <p className="text-red-400">Failed to load members.</p>}
      {members && (
        <ul className="divide-y divide-slate-800">
          {members.map((m) => (
            <li key={m.user_id} className="flex items-center justify-between gap-2 py-1.5">
              <span className="truncate text-slate-100">
                {m.email}
                {m.email === myEmail && <span className="text-slate-500"> (you)</span>}
              </span>
              {isOwner ? (
                <span className="flex shrink-0 items-center gap-1">
                  <RoleSelect
                    id={`role-${m.user_id}`}
                    label={`Role of ${m.email}`}
                    value={m.role}
                    disabled={changeRole.isPending}
                    onChange={(newRole) => changeRole.mutate({ userId: m.user_id, newRole })}
                  />
                  <button
                    type="button"
                    className={button}
                    disabled={remove.isPending}
                    aria-label={`Remove ${m.email}`}
                    onClick={() => {
                      if (window.confirm(`Remove ${m.email} from this workspace?`)) remove.mutate(m.user_id);
                    }}
                  >
                    Remove
                  </button>
                </span>
              ) : (
                <span className="shrink-0 text-slate-400">{m.role === 'owner' ? 'Owner' : 'Member'}</span>
              )}
            </li>
          ))}
        </ul>
      )}

      {isOwner && (
        <form
          className="mt-3 flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (email.trim()) add.mutate();
          }}
        >
          <div className="flex flex-col gap-1">
            <label htmlFor="add-member-email" className="text-slate-300">
              Add someone by email
            </label>
            <input
              id="add-member-email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="name@example.com"
              className={`${input} w-64`}
            />
          </div>
          <RoleSelect id="add-member-role" label="Role for the new member" value={role} onChange={setRole} />
          <button type="submit" className={button} disabled={add.isPending}>
            {add.isPending ? 'Adding…' : 'Add'}
          </button>
          <p className="w-full text-[11px] text-slate-500">
            They need an account already. Owners can also manage members, settings and API keys.
          </p>
        </form>
      )}
      {notice && (
        <p role={notice.kind === 'error' ? 'alert' : 'status'} className={`mt-2 ${notice.kind === 'error' ? 'text-red-400' : 'text-emerald-400'}`}>
          {notice.text}
        </p>
      )}
    </div>
  );
};

const NewWorkspace: React.FC = () => {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { switchTenant } = useAuth();
  const [name, setName] = useState('');
  const create = useMutation({
    mutationFn: () => createTenant(name.trim()),
    onSuccess: (w) => {
      setName('');
      queryClient.invalidateQueries({ queryKey: ['tenants'] });
      switchTenant(w.id);
      navigate('/');
    },
  });
  return (
    <form
      className="mt-3 flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (name.trim()) create.mutate();
      }}
    >
      <div className="flex flex-col gap-1">
        <label htmlFor="new-workspace-name" className="text-slate-300">
          New workspace
        </label>
        <input
          id="new-workspace-name"
          required
          maxLength={255}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Legal team"
          className={`${input} w-64`}
        />
      </div>
      <button type="submit" className={button} disabled={create.isPending}>
        {create.isPending ? 'Creating…' : 'Create and switch'}
      </button>
      {create.isError && (
        <p role="alert" className="w-full text-red-400">
          {errorDetail(create.error, 'Creating the workspace failed.')}
        </p>
      )}
    </form>
  );
};

export const TeamSettingsSection: React.FC = () => {
  const { tenantId, switchTenant, user } = useAuth();
  const navigate = useNavigate();
  const { data: workspaces, isLoading, isError } = useWorkspaces();
  const current = workspaces?.find((w) => w.id === tenantId);

  return (
    <div className="space-y-4">
      <div>
        <h2 className="mb-1 text-sm font-semibold text-slate-100">Workspace</h2>
        <p className="text-xs text-slate-400">
          {current
            ? `You're working in ${current.name}${current.role ? ` as ${current.role === 'owner' ? 'an owner' : 'a member'}` : ''}.`
            : 'Loading your workspace…'}
        </p>
      </div>

      {tenantId && current && <Members tenantId={tenantId} isOwner={current.role === 'owner'} myEmail={user?.email} />}

      <div className="rounded border border-slate-800 bg-slate-950/60 p-3 text-xs">
        <h3 className="mb-2 font-semibold text-slate-100">Your workspaces</h3>
        {isLoading && <p className="text-slate-400">Loading workspaces…</p>}
        {isError && <p className="text-red-400">Failed to load workspaces.</p>}
        {workspaces && (
          <ul className="space-y-1">
            {workspaces.map((w) => (
              <li key={w.id} className="flex items-center justify-between gap-2">
                <span className="truncate text-slate-100">
                  {w.name}
                  {w.role && <span className="text-slate-500"> · {w.role}</span>}
                </span>
                {w.id === tenantId ? (
                  <span className="text-emerald-400">Current</span>
                ) : (
                  <button
                    type="button"
                    className={button}
                    onClick={() => {
                      switchTenant(w.id);
                      navigate('/');
                    }}
                  >
                    Switch
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
        <NewWorkspace />
      </div>
    </div>
  );
};
