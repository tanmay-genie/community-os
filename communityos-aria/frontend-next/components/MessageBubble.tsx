'use client';

import { parseStructured } from '@/lib/structured';
import { AmenityGrid } from './AmenityCard';
import { BookingCard } from './BookingCard';
import { BylawCardList } from './BylawCard';

export interface Msg {
  id: string;
  role: 'user' | 'assistant' | 'system';
  reply: string;
  actionTaken?: string;
  time: string;
}

export function MessageBubble({ msg }: { msg: Msg }) {
  const isUser = msg.role === 'user';
  const parsed = isUser
    ? { kind: 'text' as const, data: null, caption: msg.reply }
    : parseStructured(msg.reply);

  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      <div
        className={`w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center text-xs font-bold ${
          isUser
            ? 'bg-primary/20 text-primary border border-primary/30'
            : 'bg-secondary/15 text-secondary border border-secondary/30'
        }`}
      >
        {isUser ? 'You' : 'AI'}
      </div>
      <div className={`flex-1 max-w-[88%] ${isUser ? 'text-right' : 'text-left'}`}>
        <div className="text-textMute text-[0.7rem] mb-1">
          {isUser ? 'You' : 'ARIA'} • {msg.time}
          {msg.actionTaken && (
            <span className="ml-2 font-mono bg-primary/10 text-primary px-1.5 py-0.5 rounded text-[0.65rem]">
              {msg.actionTaken}
            </span>
          )}
        </div>
        <div
          className={`inline-block w-full rounded-xl px-4 py-3 ${
            isUser
              ? 'bg-primary/10 border border-primary/20'
              : 'bg-surface border border-border'
          }`}
        >
          {parsed.kind === 'amenities' && (
            <div className="space-y-2">
              {parsed.caption && <p className="text-text text-sm mb-2">{parsed.caption}</p>}
              <AmenityGrid items={parsed.data.items || []} />
            </div>
          )}
          {parsed.kind === 'booking' && (
            <div className="space-y-2">
              {parsed.caption && <p className="text-text text-sm mb-2">{parsed.caption}</p>}
              <BookingCard booking={parsed.data} />
            </div>
          )}
          {parsed.kind === 'bylaw' && (
            <div className="space-y-2">
              {parsed.caption && <p className="text-text text-sm mb-2">{parsed.caption}</p>}
              <BylawCardList payload={parsed.data} />
            </div>
          )}
          {parsed.kind === 'text' && (
            <p className="text-text text-sm whitespace-pre-line leading-relaxed">
              {parsed.caption}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
