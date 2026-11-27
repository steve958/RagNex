import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { TeamSettingsSection } from './TeamSettingsSection';
import { WorkspaceSwitcher } from '../layout/WorkspaceSwitcher';
import {
  addMember,
  createTenant,
  listMembers,
  listTenants,
  removeMember,
  TenantSummary,
  updateMemberRole,
} from '../../services/tenantsApi';

const navigate = vi.fn();
vi.mock('react-router-dom', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-router-dom')>()),
  useNavigate: () => navigate,
}));

const switchTenant = vi.fn();
let tenantId = 't1';
vi.mock('../../store/auth', () => ({
  useAuth: () => ({ tenantId, switchTenant, user: { email: 'owner@example.com' } }),
}));

vi.mock('../../services/tenantsApi', () => ({
  listTenants: vi.fn(),
  listMembers: vi.fn(),
  addMember: vi.fn(),
  updateMemberRole: vi.fn(),
  removeMember: vi.fn(),
  createTenant: vi.fn(),
}));

const WORKSPACES: TenantSummary[] = [
  { id: 't1', name: 'Personal', role: 'owner' },
  { id: 't2', name: 'Legal team', role: 'member' },
];
const MEMBERS = [
  { user_id: 'u1', email: 'owner@example.com', role: 'owner' as const },
  { user_id: 'u2', email: 'bob@example.com', role: 'member' as const },
];

const renderWith = (ui: React.ReactElement) =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );

beforeEach(() => {
  vi.clearAllMocks();
  tenantId = 't1';
  vi.mocked(listTenants).mockResolvedValue(WORKSPACES);
  vi.mocked(listMembers).mockResolvedValue(MEMBERS);
});

describe('WorkspaceSwitcher', () => {
  it('switches workspace and goes back to the dashboard', async () => {
    renderWith(<WorkspaceSwitcher />);
    const select = await screen.findByLabelText('Workspace');
    expect(select).toHaveValue('t1');

    fireEvent.change(select, { target: { value: 't2' } });
    expect(switchTenant).toHaveBeenCalledWith('t2');
    expect(navigate).toHaveBeenCalledWith('/');
  });

  it('just names the workspace when there is only one', async () => {
    vi.mocked(listTenants).mockResolvedValue([WORKSPACES[0]]);
    renderWith(<WorkspaceSwitcher />);
    expect(await screen.findByText('Personal')).toBeInTheDocument();
    expect(screen.queryByLabelText('Workspace')).not.toBeInTheDocument();
  });

  it('moves to another workspace when the remembered one is gone', async () => {
    tenantId = 'removed-from-this-one';
    renderWith(<WorkspaceSwitcher />);
    await waitFor(() => expect(switchTenant).toHaveBeenCalledWith('t1'));
  });
});

describe('Workspace settings', () => {
  it('lets owners add people by email', async () => {
    vi.mocked(addMember).mockResolvedValue({ user_id: 'u3', email: 'carol@example.com', role: 'owner' });
    renderWith(<TeamSettingsSection />);

    fireEvent.change(await screen.findByLabelText('Add someone by email'), { target: { value: ' carol@example.com ' } });
    fireEvent.change(screen.getByLabelText('Role for the new member'), { target: { value: 'owner' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));

    await waitFor(() => expect(addMember).toHaveBeenCalledWith('t1', 'carol@example.com', 'owner'));
    expect(await screen.findByRole('status')).toHaveTextContent('carol@example.com is now an owner.');
    expect(listMembers).toHaveBeenCalledTimes(2); // refreshed
  });

  it("explains when the person has no account", async () => {
    vi.mocked(addMember).mockRejectedValue({
      response: { status: 404, data: { detail: 'No account uses that email. They need an account first.' } },
    });
    renderWith(<TeamSettingsSection />);
    fireEvent.change(await screen.findByLabelText('Add someone by email'), { target: { value: 'x@example.com' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('They need an account first');
  });

  it('lets owners change roles and remove members, and shows the server refusing', async () => {
    vi.mocked(updateMemberRole).mockRejectedValue({
      response: { status: 400, data: { detail: 'Cannot demote the last owner; make someone else an owner first' } },
    });
    vi.mocked(removeMember).mockResolvedValue();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderWith(<TeamSettingsSection />);

    fireEvent.change(await screen.findByLabelText('Role of owner@example.com'), { target: { value: 'member' } });
    await waitFor(() => expect(updateMemberRole).toHaveBeenCalledWith('t1', 'u1', 'member'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Cannot demote the last owner');

    fireEvent.click(screen.getByRole('button', { name: 'Remove bob@example.com' }));
    await waitFor(() => expect(removeMember).toHaveBeenCalledWith('t1', 'u2'));
  });

  it('shows members read-only to members', async () => {
    tenantId = 't2'; // a member there
    renderWith(<TeamSettingsSection />);
    const list = await screen.findByText('bob@example.com');
    expect(within(list.closest('li')!).getByText('Member')).toBeInTheDocument();
    expect(screen.queryByLabelText('Add someone by email')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Remove/ })).not.toBeInTheDocument();
    expect(screen.getByText(/as a member/)).toBeInTheDocument();
  });

  it('creates a workspace and switches to it', async () => {
    vi.mocked(createTenant).mockResolvedValue({ id: 't3', name: 'Research', role: 'owner' });
    renderWith(<TeamSettingsSection />);
    fireEvent.change(await screen.findByLabelText('New workspace'), { target: { value: 'Research' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create and switch' }));
    await waitFor(() => expect(switchTenant).toHaveBeenCalledWith('t3'));
    expect(createTenant).toHaveBeenCalledWith('Research');
    expect(navigate).toHaveBeenCalledWith('/');
  });

  it('switches from the list of workspaces', async () => {
    renderWith(<TeamSettingsSection />);
    fireEvent.click(await screen.findByRole('button', { name: 'Switch' }));
    expect(switchTenant).toHaveBeenCalledWith('t2');
  });
});
