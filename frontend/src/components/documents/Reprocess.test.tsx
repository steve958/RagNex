import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

import { DocumentList } from './DocumentList';
import { DocumentDetailModal } from './DocumentDetailModal';
import {
  DocumentStatus,
  isProcessing,
  listDocumentsForKnowledgeBase,
  reprocessDocument,
  reprocessFailedDocuments,
} from '../../services/documentApi';

vi.mock('../../services/documentApi', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../services/documentApi')>();
  return {
    ...actual,
    listDocumentsForKnowledgeBase: vi.fn(),
    getDocumentStatus: vi.fn(),
    reprocessDocument: vi.fn(),
    reprocessFailedDocuments: vi.fn(),
    deleteDocument: vi.fn(),
  };
});
// The detail modal embeds the chunk list; its data isn't relevant here.
vi.mock('../chunks/DocumentChunkList', () => ({ DocumentChunkList: () => null }));

const doc = (overrides: Partial<DocumentStatus>): DocumentStatus =>
  ({
    id: 'd1',
    kb_id: 'kb1',
    filename: 'report.docx',
    status: 'indexed',
    parse_progress: 1,
    index_progress: 1,
    error_message: null,
    ...overrides,
  }) as DocumentStatus;

const renderWith = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>);

beforeEach(() => {
  vi.mocked(reprocessDocument).mockReset();
  vi.mocked(reprocessFailedDocuments).mockReset();
});

describe('isProcessing', () => {
  it('treats "done" (parsed, waiting for indexing) as still processing', () => {
    expect(['pending', 'parsing', 'done', 'indexing'].map(isProcessing)).toEqual([true, true, true, true]);
    expect(['indexed', 'failed'].map(isProcessing)).toEqual([false, false]);
  });
});

describe('DocumentList reprocessing', () => {
  const docs = [
    doc({ id: 'f1', filename: 'a.docx', status: 'failed', error_message: 'TypeError: wrong arguments' }),
    doc({ id: 'f2', filename: 'b.xlsx', status: 'failed', error_message: 'Unsupported file type: .csv' }),
    doc({ id: 'ok', filename: 'c.md', status: 'indexed' }),
  ];

  it('shows why documents failed and offers to reprocess only those', async () => {
    vi.mocked(listDocumentsForKnowledgeBase).mockResolvedValue(docs);
    renderWith(<DocumentList kbId="kb1" />);

    expect(await screen.findByText('TypeError: wrong arguments')).toBeInTheDocument();
    expect(screen.getByText('2 documents failed to process.')).toBeInTheDocument();
    const rows = screen.getAllByRole('listitem');
    expect(within(rows[0]).getByRole('button', { name: 'Reprocess' })).toBeInTheDocument();
    expect(within(rows[2]).queryByRole('button', { name: 'Reprocess' })).not.toBeInTheDocument();

    vi.mocked(reprocessDocument).mockResolvedValue(doc({ id: 'f1', status: 'pending' }));
    fireEvent.click(within(rows[0]).getByRole('button', { name: 'Reprocess' }));
    await waitFor(() => expect(reprocessDocument).toHaveBeenCalled());
    expect(vi.mocked(reprocessDocument).mock.calls[0][0]).toBe('f1');
  });

  it('reprocesses all failed documents and reports what was skipped', async () => {
    vi.mocked(listDocumentsForKnowledgeBase).mockResolvedValue(docs);
    vi.mocked(reprocessFailedDocuments).mockResolvedValue({
      queued: ['f1'],
      skipped: [{ id: 'f2', filename: 'b.xlsx', reason: 'The original file is no longer stored. Upload the document again.' }],
    });
    renderWith(<DocumentList kbId="kb1" />);

    fireEvent.click(await screen.findByRole('button', { name: 'Reprocess 2 failed' }));
    await waitFor(() => expect(reprocessFailedDocuments).toHaveBeenCalledWith('kb1'));
    const notice = await screen.findByRole('alert');
    expect(notice).toHaveTextContent('Reprocessing 1 document.');
    expect(notice).toHaveTextContent('Skipped b.xlsx: The original file is no longer stored.');
  });

  it("shows the server's reason when reprocessing is refused", async () => {
    vi.mocked(listDocumentsForKnowledgeBase).mockResolvedValue([docs[0]]);
    vi.mocked(reprocessDocument).mockRejectedValue({
      response: { status: 409, data: { detail: 'The document is already being processed.' } },
    });
    renderWith(<DocumentList kbId="kb1" />);

    fireEvent.click(await screen.findByRole('button', { name: 'Reprocess' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('already being processed');
  });

  it('has no failure banner when nothing failed', async () => {
    vi.mocked(listDocumentsForKnowledgeBase).mockResolvedValue([docs[2]]);
    renderWith(<DocumentList kbId="kb1" />);
    await screen.findByText('c.md');
    expect(screen.queryByText(/failed to process/)).not.toBeInTheDocument();
  });
});

describe('DocumentDetailModal reprocessing', () => {
  it('offers Reprocess for a finished document and sends the request', async () => {
    vi.mocked(reprocessDocument).mockResolvedValue(doc({ status: 'pending' }));
    renderWith(<DocumentDetailModal open document={doc({ status: 'indexed' })} onClose={() => {}} />);

    fireEvent.click(screen.getByRole('button', { name: 'Reprocess' }));
    await waitFor(() => expect(reprocessDocument).toHaveBeenCalledWith('d1'));
  });

  it('hides Reprocess while the document is still processing', () => {
    renderWith(<DocumentDetailModal open document={doc({ status: 'done' })} onClose={() => {}} />);
    expect(screen.queryByRole('button', { name: 'Reprocess' })).not.toBeInTheDocument();
  });
});
