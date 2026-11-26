import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { DocumentUploadForm } from './DocumentUploadForm';
import { uploadDocumentToKnowledgeBase } from '../../services/documentApi';

vi.mock('../../services/documentApi', () => ({ uploadDocumentToKnowledgeBase: vi.fn() }));

const renderForm = () =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <DocumentUploadForm kbId="kb1" />
    </QueryClientProvider>,
  );

const choose = (file: File) => fireEvent.change(screen.getByLabelText('Document file'), { target: { files: [file] } });
const submit = () => fireEvent.submit(screen.getByLabelText('Document file').closest('form')!);

// Braces matter: a function returned from beforeEach is run as cleanup after the test.
beforeEach(() => {
  vi.mocked(uploadDocumentToKnowledgeBase).mockReset();
});

describe('DocumentUploadForm', () => {
  it('asks for a file before uploading', async () => {
    renderForm();
    submit();
    expect(await screen.findByText('Please choose a file to upload.')).toBeInTheDocument();
    expect(uploadDocumentToKnowledgeBase).not.toHaveBeenCalled();
  });

  it('uploads the chosen file to the knowledge base', async () => {
    vi.mocked(uploadDocumentToKnowledgeBase).mockResolvedValue({} as never);
    renderForm();
    const file = new File(['# hi'], 'notes.md', { type: 'text/markdown' });
    choose(file);
    submit();
    await waitFor(() => expect(uploadDocumentToKnowledgeBase).toHaveBeenCalledWith('kb1', file));
  });

  it("shows the server's reason for refusing a file", async () => {
    vi.mocked(uploadDocumentToKnowledgeBase).mockImplementation(async () => { throw {
      response: { status: 400, data: { detail: 'Unsupported file type .doc. Supported: .csv, .docx' } },
    }; });
    renderForm();
    choose(new File(['x'], 'old.doc'));
    submit();
    expect(await screen.findByRole('alert')).toHaveTextContent('Unsupported file type .doc');
  });

  it('shows validation errors as text, not "[object Object]"', async () => {
    vi.mocked(uploadDocumentToKnowledgeBase).mockImplementation(async () => { throw {
      response: { status: 422, data: { detail: [{ loc: ['body', 'file'], msg: 'Field required' }] } },
    }; });
    renderForm();
    choose(new File(['x'], 'a.md'));
    submit();
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Field required');
    expect(alert).not.toHaveTextContent('[object Object]');
  });

  it('only offers supported file types in the picker', () => {
    renderForm();
    expect(screen.getByLabelText('Document file')).toHaveAttribute('accept', expect.stringContaining('.docx'));
    expect(screen.getByLabelText('Document file').getAttribute('accept')).not.toContain('.doc,');
  });
});
