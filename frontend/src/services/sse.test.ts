import { describe, expect, it } from 'vitest';

import { SseParser } from './sse';

describe('SseParser', () => {
  it('parses complete events', () => {
    const p = new SseParser();
    expect(p.push('event: delta\ndata: {"text":"a"}\n\nevent: done\ndata: {}\n\n')).toEqual([
      { event: 'delta', data: '{"text":"a"}' },
      { event: 'done', data: '{}' },
    ]);
  });

  it('buffers events split across chunks at any position', () => {
    const raw = 'event: delta\ndata: {"text":"hello"}\n\nevent: delta\ndata: {"text":"world"}\n\n';
    // Feed one character at a time: the worst case for chunk boundaries.
    const p = new SseParser();
    const events = raw.split('').flatMap((ch) => p.push(ch));
    expect(events.map((e) => JSON.parse(e.data).text)).toEqual(['hello', 'world']);
  });

  it('handles CRLF, comments, default event name and multi-line data', () => {
    const p = new SseParser();
    expect(p.push(': ping\r\n\r\ndata: line1\r\ndata: line2\r\n\r\n')).toEqual([
      { event: 'message', data: 'line1\nline2' },
    ]);
  });

  it('holds back an incomplete trailing event', () => {
    const p = new SseParser();
    expect(p.push('event: delta\ndata: {"text":"x"}\n')).toEqual([]);
    expect(p.push('\n')).toEqual([{ event: 'delta', data: '{"text":"x"}' }]);
  });
});
