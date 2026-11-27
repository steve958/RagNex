import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { ChunkDetailModal } from './ChunkDetailModal';
import { downloadDocument } from '../../services/documentApi';

vi.mock('../../services/documentApi', () => ({ downloadDocument: vi.fn() }));

const chunk = { id: 'c1', document_id: 'doc-9', seq: 3, content: 'Revenue grew.', page: 2, position: {} };

describe('ChunkDetailModal download', () => {
  it('downloads the source document of the chunk (e.g. opened from a citation)', async () => {
    vi.mocked(downloadDocument).mockResolvedValue();
    render(<ChunkDetailModal open chunk={chunk} onClose={() => {}} />);

    fireEvent.click(screen.getByRole('button', { name: 'Download original' }));
    expect(downloadDocument).toHaveBeenCalledWith('doc-9');
    expect(await screen.findByRole('button', { name: 'Download original' })).toBeEnabled();
  });

  it('explains a failed download', async () => {
    vi.mocked(downloadDocument).mockRejectedValue({
      response: { status: 404, data: { detail: "The original file isn't stored for this document" } },
    });
    render(<ChunkDetailModal open chunk={chunk} onClose={() => {}} />);

    fireEvent.click(screen.getByRole('button', { name: 'Download original' }));
    expect(await screen.findByRole('alert')).toHaveTextContent("The original file isn't stored");
  });
});
