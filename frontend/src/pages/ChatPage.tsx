import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { fetchKnowledgeBases, KnowledgeBaseSummary } from '../services/kbApi';
import {
  ChatMessage,
  ChatSession,
  createChatSession,
  deleteChatSession,
  getMessageHistory,
  listChatSessions,
  MessageHistoryResponse,
  streamChatMessage,
} from '../services/chatApi';
import { Chunk } from '../services/chunkApi';
import { ChunkDetailModal } from '../components/chunks/ChunkDetailModal';

const formatTime = (iso: string) => {
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

export const ChatPage: React.FC = () => {
  const queryClient = useQueryClient();
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [input, setInput] = useState('');
  // User text shown until the server confirms it was saved (first `meta` event).
  const [pendingMessage, setPendingMessage] = useState<string | null>(null);
  // Assistant answer as it streams in; null when no answer is streaming.
  const [streamingText, setStreamingText] = useState<string | null>(null);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const [selectedChunk, setSelectedChunk] = useState<Chunk | null>(null);
  const [selectedKbId, setSelectedKbId] = useState<string | null>(null);

  const { data: kbList } = useQuery<KnowledgeBaseSummary[]>({
    queryKey: ['knowledge-bases'],
    queryFn: fetchKnowledgeBases,
  });

  // Default KB selection to the first available KB
  useEffect(() => {
    if (kbList && kbList.length > 0 && !selectedKbId) {
      setSelectedKbId(kbList[0].id);
    }
  }, [kbList, selectedKbId]);

  const { data: sessions, isLoading: sessionsLoading } = useQuery<ChatSession[]>({
    queryKey: ['chat-sessions'],
    queryFn: listChatSessions,
  });

  const activeSession = useMemo(
    () => sessions?.find((s) => s.id === selectedSessionId) ?? null,
    [sessions, selectedSessionId],
  );

  const { data: historyData, isLoading: historyLoading } = useQuery({
    queryKey: ['chat-history', selectedSessionId],
    // Newest page (the server caps limit at 100), so new messages never fall off the end.
    queryFn: () => getMessageHistory(selectedSessionId!, { limit: 100, latest: true }),
    enabled: !!selectedSessionId,
    // Don't poll mid-stream; the stream itself updates the cache.
    refetchInterval: isSending ? false : 10_000,
  });

  // Stop an in-flight answer when switching sessions or leaving the page.
  useEffect(() => {
    setStreamError(null);
    return () => abortRef.current?.abort();
  }, [selectedSessionId]);

  // Keep the newest content in view as messages arrive and the answer streams.
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView?.({ block: 'end' });
  }, [historyData, pendingMessage, streamingText]);

  const appendToHistory = (sessionId: string, msg: ChatMessage) => {
    queryClient.setQueryData<MessageHistoryResponse>(['chat-history', sessionId], (old) => {
      if (!old || old.items.some((m) => m.id === msg.id)) return old;
      return { ...old, items: [...old.items, { ...msg, token_estimate: 0 }], total: old.total + 1 };
    });
  };

  const createSessionMutation = useMutation({
    mutationFn: createChatSession,
    onSuccess: (session) => {
      queryClient.invalidateQueries({ queryKey: ['chat-sessions'] });
      setSelectedSessionId(session.id);
    },
  });

  const deleteSessionMutation = useMutation({
    mutationFn: deleteChatSession,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['chat-sessions'] });
      setSelectedSessionId(null);
    },
  });

  const handleCreateSession = async () => {
    if (!kbList || kbList.length === 0 || !selectedKbId) return;
    await createSessionMutation.mutateAsync({ kb_ids: [selectedKbId] });
  };

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeSession || !input.trim() || isSending) return;
    const sessionId = activeSession.id;
    const content = input.trim();
    const controller = new AbortController();
    abortRef.current = controller;
    let userSaved = false;

    setInput('');
    setPendingMessage(content);
    setStreamingText('');
    setStreamError(null);
    setIsSending(true);
    try {
      const assistant = await streamChatMessage(
        sessionId,
        { content },
        {
          onMeta: (userMessage) => {
            userSaved = true;
            setPendingMessage(null);
            appendToHistory(sessionId, userMessage);
          },
          onDelta: (text) => setStreamingText((prev) => (prev ?? '') + text),
        },
        controller.signal,
      );
      appendToHistory(sessionId, assistant);
    } catch (err) {
      if (controller.signal.aborted) return; // user navigated away; nothing to report
      setStreamError(err instanceof Error ? err.message : 'Failed to send message');
      // If the server never saved the message, give the text back so it isn't lost.
      if (!userSaved) setInput(content);
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      setPendingMessage(null);
      setStreamingText(null);
      setIsSending(false);
      queryClient.invalidateQueries({ queryKey: ['chat-history', sessionId] });
    }
  };

  const handleDeleteSession = async (session: ChatSession) => {
    const ok = window.confirm(`Delete chat session "${session.name || 'Untitled'}"?`);
    if (!ok) return;
    await deleteSessionMutation.mutateAsync(session.id);
  };

  const renderMessage = (m: ChatMessage) => {
    const isUser = m.role === 'user';
    return (
      <div key={m.id} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
        <div
          className={`max-w-xl rounded px-3 py-2 text-sm shadow-sm ${
            isUser ? 'bg-sky-600 text-white' : 'bg-slate-800 text-slate-50'
          }`}
        >
          <div className="mb-1 flex items-center justify-between gap-2">
            <span className="text-[11px] uppercase tracking-wide text-slate-300">
              {isUser ? 'You' : 'Assistant'}
            </span>
            <span className="text-[10px] text-slate-400">{formatTime(m.created_at)}</span>
          </div>
          <div className="whitespace-pre-wrap break-words text-[13px] leading-relaxed">{m.content}</div>
          {!isUser && m.citations && m.citations.length > 0 && (
            <div className="mt-1 border-t border-slate-700 pt-1 text-[10px] text-slate-300">
              <button
                type="button"
                className="underline underline-offset-2 hover:text-sky-300"
                onClick={() => {
                  // For now, open the first citation's chunk if available.
                  const first = m.citations[0];
                  // Lazy-load the chunk detail via existing chunk viewer API from the parent.
                  // ChatPage manages selectedChunk via a simple fetch in a separate flow.
                  // We pass chunk id up via a custom event-like callback.
                  // To keep things simple here, we store the doc id + chunk id on window and rely on ChatPage's handler.
                  (window as any).__ragnex_open_chunk_from_chat?.(first.chunk_id);
                }}
              >
                {m.citations.length} citation{m.citations.length > 1 ? 's' : ''}
              </button>
            </div>
          )}
        </div>
      </div>
    );
  };

  // Wire global handler for opening chunks from citations.
  (window as any).__ragnex_open_chunk_from_chat = async (chunkId: string) => {
    // Dynamic import to avoid circulars; use existing getChunk helper.
    const { getChunk } = await import('../services/chunkApi');
    const chunk = await getChunk(chunkId);
    setSelectedChunk(chunk);
  };

  return (
    <div className="flex flex-col md:flex-row md:h-[calc(100vh-96px)] gap-4">
      {/* Sidebar: sessions */}
      <aside className="w-full md:w-64 shrink-0 rounded border border-slate-800 bg-slate-950/80 p-3 flex flex-col">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-100">Chat sessions</h2>
          <button
            type="button"
            onClick={handleCreateSession}
            disabled={createSessionMutation.isPending || !kbList || kbList.length === 0 || !selectedKbId}
            className="rounded bg-sky-600 px-2 py-1 text-[11px] font-medium text-white hover:bg-sky-500 disabled:opacity-60"
          >
            New
          </button>
        </div>
        <div className="mb-3 text-[11px] text-slate-400">
          <span className="mr-1">Knowledge base:</span>
          <select
            value={selectedKbId ?? ''}
            onChange={(e) => setSelectedKbId(e.target.value || null)}
            className="mt-1 w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 text-[11px] text-slate-100 focus:outline-none focus:ring-1 focus:ring-sky-500"
          >
            {!kbList || kbList.length === 0 ? (
              <option value="">No knowledge bases available</option>
            ) : (
              kbList.map((kb) => (
                <option key={kb.id} value={kb.id}>
                  {kb.name}
                </option>
              ))
            )}
          </select>
        </div>
        {sessionsLoading ? (
          <p className="text-[11px] text-slate-400">Loading sessions…</p>
        ) : !sessions || sessions.length === 0 ? (
          <p className="text-[11px] text-slate-500">
            No sessions yet. Create one to start chatting with your knowledge bases.
          </p>
        ) : (
          <ul className="flex-1 overflow-auto space-y-1 text-[11px]">
            {sessions.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  onClick={() => setSelectedSessionId(s.id)}
                  className={`flex w-full items-center justify-between rounded px-2 py-1 text-left hover:bg-slate-800 ${
                    s.id === selectedSessionId ? 'bg-slate-800' : ''
                  }`}
                >
                  <span className="truncate text-slate-100">{s.name || 'Untitled session'}</span>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDeleteSession(s);
                    }}
                    className="ml-2 rounded px-1 text-[10px] text-slate-400 hover:bg-slate-900 hover:text-red-300"
                  >
                    ✕
                  </button>
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>

      {/* Main chat window */}
      <section className="flex-1 rounded border border-slate-800 bg-slate-950/80 flex flex-col min-h-[320px]">
        {!activeSession ? (
          <div className="m-auto text-center text-sm text-slate-400">
            <p className="mb-2">Select a chat session or create a new one to begin.</p>
          </div>
        ) : (
          <>
            <header className="flex items-center justify-between border-b border-slate-800 px-4 py-2 text-xs text-slate-300">
              <div>
                <p className="font-semibold text-slate-100">{activeSession.name || 'Untitled session'}</p>
                <p className="text-[11px] text-slate-400">
                  KBs:{' '}
                  {activeSession.kb_ids.length > 0 ? activeSession.kb_ids.join(', ') : 'None'}
                </p>
              </div>
              {activeSession.system_prompt && (
                <div className="max-w-sm truncate text-[11px] text-slate-400" title={activeSession.system_prompt}>
                  System prompt: {activeSession.system_prompt}
                </div>
              )}
            </header>
            <div className="flex-1 overflow-auto px-4 py-3 space-y-2 text-sm">
              {historyLoading && (
                <p className="text-[11px] text-slate-400">Loading messages…</p>
              )}
              {historyData?.items.map((m) => renderMessage(m))}
              {pendingMessage && (
                <div className="flex justify-end">
                  <div className="max-w-xl rounded bg-sky-600/70 px-3 py-2 text-sm text-white opacity-80">
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <span className="text-[11px] uppercase tracking-wide text-slate-200">You</span>
                      <span className="text-[10px] text-slate-200">Sending…</span>
                    </div>
                    <div className="whitespace-pre-wrap break-words text-[13px] leading-relaxed">{pendingMessage}</div>
                  </div>
                </div>
              )}
              {streamingText !== null && (
                <div className="flex justify-start" aria-live="polite">
                  <div className="max-w-xl rounded bg-slate-800 px-3 py-2 text-sm text-slate-50 shadow-sm">
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <span className="text-[11px] uppercase tracking-wide text-slate-300">Assistant</span>
                      <span className="text-[10px] text-slate-400">{streamingText ? 'Writing…' : 'Thinking…'}</span>
                    </div>
                    <div className="whitespace-pre-wrap break-words text-[13px] leading-relaxed">
                      {streamingText}
                      <span className="ml-0.5 inline-block h-3 w-1.5 animate-pulse bg-slate-400 align-middle" />
                    </div>
                  </div>
                </div>
              )}
              {streamError && (
                <p role="alert" className="text-[11px] text-red-400">
                  {streamError}
                </p>
              )}
              <div ref={messagesEndRef} />
            </div>
            <form onSubmit={handleSend} className="border-t border-slate-800 px-4 py-3">
              <div className="flex items-end gap-2">
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                      void handleSend(e);
                    }
                  }}
                  placeholder="Ask a question about your documents… (Ctrl+Enter to send)"
                  rows={2}
                  className="flex-1 resize-none rounded border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-1 focus:ring-sky-500"
                />
                <button
                  type="submit"
                  disabled={!activeSession || !input.trim() || isSending}
                  className="h-9 rounded bg-sky-600 px-3 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-60"
                >
                  {isSending ? 'Sending…' : 'Send'}
                </button>
              </div>
            </form>
          </>
        )}
      </section>

      <ChunkDetailModal open={!!selectedChunk} chunk={selectedChunk} searchTerm={undefined} onClose={() => setSelectedChunk(null)} />
    </div>
  );
};