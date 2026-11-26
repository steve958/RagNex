import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { uploadDocumentToKnowledgeBase } from '../../services/documentApi';

export const SUPPORTED_UPLOAD_TYPES =
  '.pdf,.docx,.xlsx,.csv,.pptx,.txt,.md,.markdown,.html,.htm,.json,.jsonl';

interface Props {
  kbId: string;
}

export const DocumentUploadForm: React.FC<Props> = ({ kbId }) => {
  const [file, setFile] = useState<File | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { mutateAsync, isPending, error } = useMutation({
    mutationFn: async (f: File) => uploadDocumentToKnowledgeBase(kbId, f),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents', kbId] });
    },
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLocalError(null);
    if (!file) {
      setLocalError('Please choose a file to upload.');
      return;
    }
    try {
      await mutateAsync(file);
      setFile(null);
      (e.target as HTMLFormElement).reset();
    } catch {
      // error handled below
    }
  };

  const backendError = (error as any)?.response?.data?.detail;

  return (
    <form onSubmit={handleSubmit} className="space-y-2">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <input
          type="file"
          // Keep in step with SUPPORTED_EXTENSIONS in backend/app/services/parsing.py; the
          // server checks too, this just stops the picker offering files that would be refused.
          accept={SUPPORTED_UPLOAD_TYPES}
          aria-label="Document file"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="block w-full text-xs text-slate-200 file:mr-3 file:rounded file:border-0 file:bg-slate-800 file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-slate-100 hover:file:bg-slate-700"
        />
        <button
          type="submit"
          disabled={isPending}
          className="inline-flex items-center justify-center rounded bg-sky-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-sky-500 disabled:opacity-60"
        >
          {isPending ? 'Uploading…' : 'Upload document'}
        </button>
      </div>
      {localError && <p className="text-xs text-red-400">{localError}</p>}
      {backendError && <p className="text-xs text-red-400">{String(backendError)}</p>}
      <p className="text-[11px] text-slate-500">
        Supported: PDF, DOCX, DOC, TXT, MD, HTML, CSV, XLSX, JSON. Large files may take a while to parse and index.
      </p>
    </form>
  );
};