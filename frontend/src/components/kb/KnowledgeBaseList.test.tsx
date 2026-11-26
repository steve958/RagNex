import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { KnowledgeBaseList } from './KnowledgeBaseList';
import { fetchKnowledgeBases } from '../../services/kbApi';

vi.mock('../../services/kbApi', () => ({
  fetchKnowledgeBases: vi.fn(),
}));

const renderWithProviders = (ui: React.ReactElement) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
};

describe('KnowledgeBaseList', () => {
  it('renders list of knowledge bases', async () => {
    vi.mocked(fetchKnowledgeBases).mockResolvedValueOnce([
      { id: '1', name: 'KB1', description: 'first', template: 'general' },
      { id: '2', name: 'KB2', description: null, template: 'laws' },
    ] as Awaited<ReturnType<typeof fetchKnowledgeBases>>);

    const onCreate = vi.fn();
    renderWithProviders(<KnowledgeBaseList onCreateClick={onCreate} />);

    // Header
    expect(await screen.findByText('Knowledge bases')).toBeInTheDocument();
    // Items
    expect(screen.getByText('KB1')).toBeInTheDocument();
    expect(screen.getByText('KB2')).toBeInTheDocument();
  });
});
