import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { ApiKeysSection } from './ApiKeysSection';
import { ToastProvider } from '../common/ToastProvider';
import { createApiKey, listApiKeys, revokeApiKey } from '../../services/apiKeysApi';

vi.mock('../../services/apiKeysApi', () => ({
  listApiKeys: vi.fn(),
  createApiKey: vi.fn(),
  revokeApiKey: vi.fn(),
}));

const renderSection = () =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ToastProvider>
        <ApiKeysSection />
      </ToastProvider>
    </QueryClientProvider>,
  );

beforeEach(() => {
  vi.mocked(listApiKeys).mockResolvedValue([
    { id: 'k1', name: 'CI', scopes: ['read'], revoked_at: null, created_at: '2026-01-01T00:00:00Z' },
    { id: 'k2', name: 'Old', scopes: ['write'], revoked_at: '2026-02-01T00:00:00Z', created_at: '2026-01-01T00:00:00Z' },
  ] as never);
  vi.mocked(createApiKey).mockReset();
  vi.mocked(revokeApiKey).mockReset();
});

describe('ApiKeysSection', () => {
  it('creates a key with the chosen scopes and shows it once', async () => {
    vi.mocked(createApiKey).mockResolvedValue({ api_key: 'rk_secret_value', id: 'k3' });
    renderSection();

    fireEvent.change(await screen.findByLabelText(/name/i), { target: { value: 'Importer' } });
    fireEvent.click(screen.getByRole('checkbox', { name: 'write' }));
    fireEvent.click(screen.getByRole('button', { name: 'Create key' }));

    await waitFor(() => expect(createApiKey).toHaveBeenCalled());
    expect(vi.mocked(createApiKey).mock.calls[0][0]).toEqual({ name: 'Importer', scopes: ['read', 'write'] });
    expect(await screen.findByText('rk_secret_value')).toBeInTheDocument();
    expect(screen.getByText(/You will not be able to see it again/)).toBeInTheDocument();
  });

  it("can't create a key without any scope", async () => {
    renderSection();
    fireEvent.change(await screen.findByLabelText(/name/i), { target: { value: 'Useless' } });
    fireEvent.click(screen.getByRole('checkbox', { name: 'read' })); // the only scope checked by default
    expect(screen.getByRole('button', { name: 'Create key' })).toBeDisabled();
  });

  it('revokes active keys; revoked keys cannot be revoked again', async () => {
    vi.mocked(revokeApiKey).mockResolvedValue();
    renderSection();

    const buttons = await screen.findAllByRole('button', { name: 'Revoke' });
    expect(buttons[1]).toBeDisabled(); // k2 is already revoked
    fireEvent.click(buttons[0]);
    await waitFor(() => expect(revokeApiKey).toHaveBeenCalled());
    expect(vi.mocked(revokeApiKey).mock.calls[0][0]).toBe('k1');
  });
});
