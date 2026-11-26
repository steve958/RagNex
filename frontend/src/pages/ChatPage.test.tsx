import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';

import { ChatPage } from './ChatPage';

vi.mock('../services/kbApi', () => ({
  // Only live knowledge bases are listed; "kb-gone" was deleted.
  fetchKnowledgeBases: vi.fn().mockResolvedValue([{ id: 'kb-live', name: 'Live KB', description: null, template: 'general' }]),
}));

vi.mock('../services/chatApi', () => ({
  listChatSessions: vi.fn().mockResolvedValue([
    { id: 's-orphan', name: 'Orphaned chat', system_prompt: null, kb_ids: ['kb-gone'], created_at: '2026-01-01T00:00:00Z' },
    { id: 's-ok', name: 'Healthy chat', system_prompt: null, kb_ids: ['kb-live'], created_at: '2026-01-01T00:00:00Z' },
  ]),
  getMessageHistory: vi.fn().mockResolvedValue({ items: [], total: 0, offset: 0, limit: 100 }),
  createChatSession: vi.fn(),
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

    fireEvent.click(screen.getByText('Healthy chat'));
    expect(screen.queryByText(/knowledge base has been deleted/i)).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Ask a question/i)).not.toBeDisabled();
  });
});
