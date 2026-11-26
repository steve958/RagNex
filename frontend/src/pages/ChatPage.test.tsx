import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { ChatPage } from './ChatPage';
import { createChatSession } from '../services/chatApi';

vi.mock('../services/kbApi', () => ({
  // Only live knowledge bases are listed; "kb-gone" was deleted.
  fetchKnowledgeBases: vi.fn().mockResolvedValue([
    { id: 'kb-live', name: 'Live KB', description: null, template: 'general' },
    { id: 'kb-other', name: 'Other KB', description: null, template: 'general' },
  ]),
}));

vi.mock('../services/chatApi', () => ({
  listChatSessions: vi.fn().mockResolvedValue([
    { id: 's-orphan', name: 'Orphaned chat', system_prompt: null, kb_ids: ['kb-gone'], created_at: '2026-01-01T00:00:00Z' },
    { id: 's-ok', name: 'Healthy chat', system_prompt: null, kb_ids: ['kb-live', 'kb-other'], created_at: '2026-01-01T00:00:00Z' },
  ]),
  getMessageHistory: vi.fn().mockResolvedValue({ items: [], total: 0, offset: 0, limit: 100 }),
  createChatSession: vi.fn().mockResolvedValue({
    id: 's-new',
    name: null,
    system_prompt: null,
    kb_ids: ['kb-live', 'kb-other'],
    created_at: '2026-01-01T00:00:00Z',
  }),
  deleteChatSession: vi.fn(),
  streamChatMessage: vi.fn(),
}));

const renderPage = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ChatPage />
    </QueryClientProvider>,
  );

describe('ChatPage', () => {
  it('explains and disables input when the session knowledge base was deleted', async () => {
    renderPage();

    fireEvent.click(await screen.findByText('Orphaned chat'));
    expect(await screen.findByText(/knowledge base has been deleted/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Ask a question/i)).toBeDisabled();
    expect(screen.getByText(/Searches: deleted knowledge base/)).toBeInTheDocument();

    fireEvent.click(screen.getByText('Healthy chat'));
    expect(screen.queryByText(/knowledge base has been deleted/i)).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Ask a question/i)).not.toBeDisabled();
    expect(screen.getByText('Searches: Live KB, Other KB')).toBeInTheDocument();
  });

  it('creates a chat over every selected knowledge base', async () => {
    renderPage();

    const live = await screen.findByRole('checkbox', { name: 'Live KB' });
    const other = screen.getByRole('checkbox', { name: 'Other KB' });
    // The first knowledge base is preselected, and can't be the last one unchecked.
    await waitFor(() => expect(live).toBeChecked());
    expect(live).toBeDisabled();
    expect(other).not.toBeChecked();

    fireEvent.click(other);
    expect(other).toBeChecked();
    expect(live).not.toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: 'New' }));
    await waitFor(() => expect(createChatSession).toHaveBeenCalled());
    expect(vi.mocked(createChatSession).mock.calls[0][0]).toEqual({ kb_ids: ['kb-live', 'kb-other'] });
  });
});
