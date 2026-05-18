'use client';

import { useState, type FormEvent, type KeyboardEvent } from 'react';

interface Props {
  onSend: (text: string) => Promise<void> | void;
  disabled?: boolean;
}

export function ChatInput({ onSend, disabled }: Props) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit() {
    const trimmed = text.trim();
    if (!trimmed || busy || disabled) return;
    setBusy(true);
    try {
      setText('');
      await onSend(trimmed);
    } finally {
      setBusy(false);
    }
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void submit();
    }
  }

  function onForm(e: FormEvent) {
    e.preventDefault();
    void submit();
  }

  return (
    <form
      onSubmit={onForm}
      className="flex gap-2 items-center bg-surface border border-border rounded-xl p-2"
    >
      <input
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKey}
        placeholder="Ask ARIA anything…  (e.g. 'are pets allowed?')"
        disabled={busy || disabled}
        className="flex-1 bg-transparent text-text placeholder-textMute px-3 py-2 outline-none text-sm disabled:opacity-50"
      />
      <button
        type="submit"
        disabled={busy || disabled || !text.trim()}
        className="px-4 py-2 rounded-lg bg-brand-grad text-bg font-semibold text-sm disabled:opacity-40 disabled:cursor-not-allowed hover:opacity-90 transition-opacity"
      >
        {busy ? 'Sending…' : 'Send'}
      </button>
    </form>
  );
}
