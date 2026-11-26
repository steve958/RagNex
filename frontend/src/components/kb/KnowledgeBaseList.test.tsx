import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';

import { KnowledgeBaseList } from './KnowledgeBaseList';
import * as kbApi from '../../services/kbApi';

const renderWithClient = (ui: React.ReactElement) => {
  const client = new QueryClient();
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
};

describe('KnowledgeBaseList', () => {
  it('renders list of knowledge bases', async () => {
    vi.spyOn(kbApi, 'fetchKnowledgeBases').mockResolvedValueOnce([
      { id: '1', name: 'KB1', description: 'first', template: 'general' },
      { id: '2', name: 'KB2', description: null, template: 'laws' },
    ]);

    const onCreate = vi.fn();
    renderWithClient(<KnowledgeBaseList onCreateClick={onCreate} />);

    // Header
    expect(await screen.findByText('Knowledge bases')).toBeInTheDocument();
    // Items
    expect(screen.getByText('KB1')).toBeInTheDocument();
    expect(screen.getByText('KB2')).toBeInTheDocument();
  });
});
