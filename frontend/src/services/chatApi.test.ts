import { afterEach, describe, expect, it, vi } from 'vitest';

import { setAccessToken, setTenantId } from './apiClient';
import { streamChatMessage } from './chatApi';

const sse = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

/** A fetch Response whose body arrives in the given text chunks. */
const streamingResponse = (chunks: string[], init: ResponseInit = { status: 200 }) => {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c));
      controller.close();
    },
  });
  return new Response(body, { ...init, headers: { 'Content-Type': 'text/event-stream' } });
};

const userMsg = { id: 'u1', role: 'user', content: 'hi', citations: [], created_at: '2026-01-01T00:00:00Z' };
const citation = { chunk_id: 'c1', doc_id: 'd1', kb_id: 'k1', score: 1 };
const assistantMsg = {
  id: 'a1',
  role: 'assistant',
  content: 'Hello world',
  citations: [citation],
  created_at: '2026-01-01T00:00:01Z',
};

afterEach(() => {
  vi.unstubAllGlobals();
  setAccessToken(null);
  setTenantId(null);
});

describe('streamChatMessage', () => {
  it('reports meta and deltas, resolves with the saved message, and sends auth headers', async () => {
    const full = sse('meta', { user_message: userMsg, citations: [citation] }) +
      sse('delta', { text: 'Hello' }) +
      sse('delta', { text: ' world' }) +
      sse('done', assistantMsg);
    // Split mid-event to exercise buffering across network chunks.
    const fetchMock = vi.fn().mockResolvedValue(streamingResponse([full.slice(0, 50), full.slice(50)]));
    vi.stubGlobal('fetch', fetchMock);
    setAccessToken('tok');
    setTenantId('tenant-1');

    const onMeta = vi.fn();
    const deltas: string[] = [];
    const result = await streamChatMessage('s1', { content: 'hi' }, { onMeta, onDelta: (t) => deltas.push(t) });

    expect(result).toEqual(assistantMsg);
    expect(onMeta).toHaveBeenCalledWith(userMsg, [citation]);
    expect(deltas).toEqual(['Hello', ' world']);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/chat\/sessions\/s1\/messages\/stream$/);
    expect(init.method).toBe('POST');
    expect(init.headers).toMatchObject({ Authorization: 'Bearer tok', 'X-Tenant-ID': 'tenant-1' });
    expect(JSON.parse(init.body)).toEqual({ content: 'hi' });
  });

  it('rejects with the server detail when an error event arrives', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        streamingResponse([
          sse('meta', { user_message: userMsg, citations: [] }),
          sse('error', { detail: 'Generation failed: ConnectError' }),
        ]),
      ),
    );
    await expect(streamChatMessage('s1', { content: 'hi' })).rejects.toThrow('Generation failed: ConnectError');
  });

  it('rejects with the HTTP error detail before streaming starts', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'Chat session not found' }), { status: 404 }),
      ),
    );
    await expect(streamChatMessage('s1', { content: 'hi' })).rejects.toThrow('Chat session not found');
  });

  it('rejects if the stream ends without a done event', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamingResponse([sse('delta', { text: 'partial' })])));
    await expect(streamChatMessage('s1', { content: 'hi' })).rejects.toThrow(/ended before/);
  });
});
