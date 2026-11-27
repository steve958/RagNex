import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { apiClient } from './apiClient';
import { downloadDocument, filenameFromDisposition } from './documentApi';
import { errorDetail } from './errors';

vi.mock('./apiClient', () => ({ apiClient: { get: vi.fn() } }));

describe('filenameFromDisposition', () => {
  it('prefers the exact UTF-8 name', () => {
    const header = `attachment; filename="_berblick (final).pdf"; filename*=UTF-8''%C3%9Cberblick%20%28final%29.pdf`;
    expect(filenameFromDisposition(header)).toBe('Überblick (final).pdf');
  });

  it('falls back to the plain name', () => {
    expect(filenameFromDisposition('attachment; filename="report.pdf"')).toBe('report.pdf');
    expect(filenameFromDisposition(`attachment; filename="x.pdf"; filename*=UTF-8''%E0%A4%A`)).toBe('x.pdf');
  });

  it('returns null without a name', () => {
    expect(filenameFromDisposition(undefined)).toBeNull();
    expect(filenameFromDisposition('attachment')).toBeNull();
  });
});

describe('downloadDocument', () => {
  let clicked: { href: string; download: string }[];

  beforeEach(() => {
    clicked = [];
    vi.mocked(apiClient.get).mockReset();
    URL.createObjectURL = vi.fn(() => 'blob:ragnex/1');
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push({ href: this.href, download: this.download });
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('fetches the file with the sign-in token and saves it under the server-given name', async () => {
    const blob = new Blob(['hello']);
    vi.mocked(apiClient.get).mockResolvedValue({
      data: blob,
      headers: { 'content-disposition': `attachment; filename="r.pdf"; filename*=UTF-8''r%C3%A9sum%C3%A9.pdf` },
    });

    await downloadDocument('doc-1', 'fallback.pdf');

    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/documents/doc-1/file', { responseType: 'blob' });
    expect(URL.createObjectURL).toHaveBeenCalledWith(blob);
    expect(clicked).toEqual([{ href: 'blob:ragnex/1', download: 'résumé.pdf' }]);
    expect(document.querySelector('a[download]')).toBeNull(); // link removed again
  });

  it("uses the fallback name when the server doesn't give one", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: new Blob(['x']), headers: {} });
    await downloadDocument('doc-1', 'notes.md');
    expect(clicked[0].download).toBe('notes.md');
  });

  it("surfaces the server's error message, which arrives as a Blob", async () => {
    const detail = "The original file isn't stored for this document";
    vi.mocked(apiClient.get).mockRejectedValue({
      response: { status: 404, data: new Blob([JSON.stringify({ detail })], { type: 'application/json' }) },
    });

    const err = await downloadDocument('doc-1').catch((e: unknown) => e);
    expect(errorDetail(err, 'Download failed.')).toBe(detail);
    expect(clicked).toEqual([]);
  });
});
