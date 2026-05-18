'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { chat, healthOk } from '@/lib/api';
import { ensureToken } from '@/lib/auth';
import { ChatInput } from './ChatInput';
import { MessageBubble, type Msg } from './MessageBubble';
import { QuickActions } from './QuickActions';

function nowTime(): string {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function uid(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export function ChatPanel() {
  const [messages, setMessages] = useState<Msg[]>([
    {
      id: uid(),
      role: 'assistant',
      reply:
        "Hi! I'm ARIA, your building assistant. Try asking \"what amenities are here?\" or \"can I install hardwood floors?\" — or tap any quick action below.",
      time: nowTime(),
    },
  ]);
  const [status, setStatus] = useState<'connecting' | 'online' | 'offline'>('connecting');
  const [convId] = useState<string>(() => `next-${uid()}`);
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // On mount: warm the token + check backend health
  useEffect(() => {
    (async () => {
      const ok = await healthOk();
      if (!ok) {
        setStatus('offline');
        return;
      }
      try {
        await ensureToken();
        setStatus('online');
      } catch {
        setStatus('offline');
      }
    })();
  }, []);

  // Auto-scroll on new message
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  const send = useCallback(
    async (text: string) => {
      const userMsg: Msg = { id: uid(), role: 'user', reply: text, time: nowTime() };
      setMessages((m) => [...m, userMsg]);
      setBusy(true);
      try {
        const resp = await chat({ message: text, conversation_id: convId });
        const ariaMsg: Msg = {
          id: uid(),
          role: 'assistant',
          reply: resp.reply,
          actionTaken: resp.action_taken || undefined,
          time: nowTime(),
        };
        setMessages((m) => [...m, ariaMsg]);
      } catch (err) {
        setMessages((m) => [
          ...m,
          {
            id: uid(),
            role: 'system',
            reply: `Error: ${err instanceof Error ? err.message : String(err)}`,
            time: nowTime(),
          },
        ]);
      } finally {
        setBusy(false);
      }
    },
    [convId]
  );

  return (
    <div className="flex flex-col h-full max-h-screen">
      {/* Top bar */}
      <header className="flex items-center justify-between px-6 py-3 border-b border-border bg-bg/70 backdrop-blur">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-brand-grad flex items-center justify-center text-bg font-bold text-sm">A</div>
          <div>
            <div className="text-text font-bold text-sm leading-none">ARIA</div>
            <div className="text-textMute text-[0.7rem] mt-0.5">CommunityOS · Next.js reference</div>
          </div>
        </div>
        <div className="flex items-center gap-2 text-[0.75rem]">
          <span
            className={`w-2 h-2 rounded-full ${
              status === 'online' ? 'bg-success' : status === 'connecting' ? 'bg-warning animate-pulse' : 'bg-danger'
            }`}
          />
          <span className="text-textSoft">
            {status === 'online' ? 'Connected' : status === 'connecting' ? 'Connecting…' : 'Offline'}
          </span>
        </div>
      </header>

      <div className="flex-1 grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-0 overflow-hidden">
        {/* Chat column */}
        <section className="flex flex-col min-h-0 overflow-hidden">
          <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
            {messages.map((m) => (
              <MessageBubble key={m.id} msg={m} />
            ))}
          </div>
          <div className="border-t border-border bg-bg/60 px-6 py-3">
            <ChatInput onSend={send} disabled={status !== 'online' || busy} />
            <p className="text-textMute text-[0.7rem] mt-2 text-center">
              Conversation ID: <span className="font-mono">{convId}</span>
            </p>
          </div>
        </section>

        {/* Quick actions sidebar (collapses below 1024px) */}
        <aside className="border-l border-border bg-bg/40 overflow-y-auto p-5 lg:block hidden">
          <h3 className="text-textMute uppercase text-[0.7rem] tracking-wider font-bold mb-3">
            Quick Actions
          </h3>
          <QuickActions onPick={(p) => void send(p)} disabled={status !== 'online' || busy} />
        </aside>
      </div>
    </div>
  );
}
