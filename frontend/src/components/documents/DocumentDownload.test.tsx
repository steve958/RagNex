import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { DocumentList } from './DocumentList';
import { DocumentStatus, downloadDocument, listDocumentsForKnowledgeBase } from '../../services/documentApi';

vi.mock('../../services/documentApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/documentApi')>();
  return { ...actual, listDocumentsForKnowledgeBase: vi.fn(), downloadDocument: vi.fn() };
});

const docs = [
  { id: 'd1', kb_id: 'kb1', filename: 'report.docx', status: 'indexed', parse_progress: 1, index_progress: 1 },
  { id: 'd2', kb_id: 'kb1', filename: 'slides.pptx', status: 'failed', parse_progress: 0, index_progress: 0 },
] as DocumentStatus[];

const renderList = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <DocumentList kbId="kb1" />
    </QueryClientProvider>,
  );

describe('DocumentList download', () => {
  it('downloads the chosen document under its own name, failed ones included', async () => {
    vi.mocked(listDocumentsForKnowledgeBase).mockResolvedValue(docs);
    vi.mocked(downloadDocument).mockResolvedValue();
    renderList();

    fireEvent.click(await screen.findByRole('button', { name: 'Download slides.pptx' }));
    await waitFor(() => expect(downloadDocument).toHaveBeenCalledWith('d2', 'slides.pptx'));
  });

  it('shows why a download failed', async () => {
    vi.mocked(listDocumentsForKnowledgeBase).mockResolvedValue(docs);
    vi.mocked(downloadDocument).mockRejectedValue({
      response: { status: 404, data: { detail: "The original file isn't stored for this document" } },
    });
    renderList();

    fireEvent.click(await screen.findByRole('button', { name: 'Download report.docx' }));
    expect(await screen.findByRole('alert')).toHaveTextContent("The original file isn't stored");
  });
});
