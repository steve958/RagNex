export interface SseEvent {
  event: string;
  data: string;
}

/**
 * Incremental parser for a text/event-stream body. Feed it decoded text chunks as they
 * arrive (chunk boundaries can fall anywhere, even mid-line); it returns the events
 * completed so far and buffers the remainder.
 */
export class SseParser {
  private buffer = '';

  push(chunk: string): SseEvent[] {
    // Normalise CRLF/CR line endings, which the SSE spec allows.
    this.buffer += chunk.replace(/\r\n?/g, '\n');
    const events: SseEvent[] = [];
    let sep: number;
    while ((sep = this.buffer.indexOf('\n\n')) !== -1) {
      const block = this.buffer.slice(0, sep);
      this.buffer = this.buffer.slice(sep + 2);
      const parsed = parseBlock(block);
      if (parsed) events.push(parsed);
    }
    return events;
  }
}

const parseBlock = (block: string): SseEvent | null => {
  let event = 'message';
  const data: string[] = [];
  for (const line of block.split('\n')) {
    if (!line || line.startsWith(':')) continue; // blank or comment
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'event') event = value;
    else if (field === 'data') data.push(value);
  }
  return data.length > 0 ? { event, data: data.join('\n') } : null;
};
