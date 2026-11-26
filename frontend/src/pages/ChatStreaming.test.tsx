import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { ChatPage } from './ChatPage';
import { ChatMessage, getMessageHistory, StreamHandlers, streamChatMessage } from '../services/chatApi';

vi.mock('../services/kbApi', () => ({
  fetchKnowledgeBases: vi.fn().mockResolvedValue([{ id: 'kb1', name: 'Docs', description: null, template: 'general' }]),
}));

vi.mock('../services/chatApi', () => ({
  listChatSessions: vi.fn().mockResolvedValue([
    { id: 's1', name: 'My chat', system_prompt: null, kb_ids: ['kb1'], created_at: '2026-01-01T00:00:00Z' },
  ]),
  getMessageHistory: vi.fn(),
  createChatSession: vi.fn(),
  deleteChatSession: vi.fn(),
  streamChatMessage: vi.fn(),
}));

const message = (id: string, role: string, content: string): ChatMessage => ({
  id,
  role,
  content,
  citations: [],
  created_at: '2026-01-01T00:00:00Z',
});

const renderPage = async () => {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ChatPage />
    </QueryClientProvider>,
  );
  fireEvent.click(await screen.findByText('My chat'));
  return screen.findByPlaceholderText(/Ask a question/);
};

// What the server has saved; history refetches return it, like the real API.
let saved: ChatMessage[] = [];

beforeEach(() => {
  saved = [];
  vi.mocked(streamChatMessage).mockReset();
  vi.mocked(getMessageHistory).mockImplementation(async () => ({
    items: saved.map((m) => ({ ...m, token_estimate: 1 })),
    total: saved.length,
    offset: 0,
    limit: 100,
  }));
});

describe('ChatPage sending and streaming', () => {
  it('shows the answer as it streams, then keeps the finished messages', async () => {
    let finish!: (m: ChatMessage) => void;
    vi.mocked(streamChatMessage).mockImplementation(async (_sid, _payload, handlers?: StreamHandlers) => {
      handlers?.onMeta?.(message('u1', 'user', 'What is RagNex?'), []);
      handlers?.onDelta?.('RagNex is ');
      handlers?.onDelta?.('a RAG platform.');
      return new Promise<ChatMessage>((resolve) => {
        finish = resolve;
      });
    });

    const input = await renderPage();
    fireEvent.change(input, { target: { value: '  What is RagNex?  ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));

    // Mid-stream: the question is shown, the partial answer streams in, sending is locked.
    expect(await screen.findByText('RagNex is a RAG platform.')).toBeInTheDocument();
    expect(screen.getByText('Writing…')).toBeInTheDocument();
    expect(screen.getByText('What is RagNex?')).toBeInTheDocument();
    expect(input).toHaveValue('');
    expect(screen.getByRole('button', { name: 'Sending…' })).toBeDisabled();

    const [sessionId, payload] = vi.mocked(streamChatMessage).mock.calls[0];
    expect(sessionId).toBe('s1');
    expect(payload).toEqual({ content: 'What is RagNex?' }); // trimmed

    saved = [message('u1', 'user', 'What is RagNex?'), message('a1', 'assistant', 'RagNex is a RAG platform.')];
    finish(saved[1]);
    await waitFor(() => expect(screen.queryByText('Writing…')).not.toBeInTheDocument());
    expect(screen.getByText('RagNex is a RAG platform.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument();
  });

  it('gives the text back and explains when sending fails before the message is saved', async () => {
    vi.mocked(streamChatMessage).mockRejectedValue(new Error('Request failed (503)'));
    const input = await renderPage();

    fireEvent.change(input, { target: { value: 'Will this work?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Request failed (503)');
    expect(input).toHaveValue('Will this work?');
  });

  it('does not restore the text when the question was saved but the answer failed', async () => {
    vi.mocked(streamChatMessage).mockImplementation(async (_sid, _payload, handlers?: StreamHandlers) => {
      handlers?.onMeta?.(message('u1', 'user', 'Saved question'), []);
      throw new Error('Generation failed: ConnectError');
    });
    const input = await renderPage();

    fireEvent.change(input, { target: { value: 'Saved question' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Generation failed');
    expect(input).toHaveValue(''); // it is in the history already; resending would duplicate it
  });

  it('sends with Ctrl+Enter and ignores blank input', async () => {
    vi.mocked(streamChatMessage).mockResolvedValue(message('a1', 'assistant', 'ok'));
    const input = await renderPage();

    fireEvent.change(input, { target: { value: '   ' } });
    fireEvent.keyDown(input, { key: 'Enter', ctrlKey: true });
    expect(streamChatMessage).not.toHaveBeenCalled();

    fireEvent.change(input, { target: { value: 'Quick question' } });
    fireEvent.keyDown(input, { key: 'Enter', ctrlKey: true });
    await waitFor(() => expect(streamChatMessage).toHaveBeenCalledTimes(1));
  });
});
