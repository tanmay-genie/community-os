/**
 * Parser for ARIA's structured reply prefixes.
 *
 * ARIA's chat replies may begin with one of these markers (followed by a
 * blank line and a human-readable caption):
 *
 *   AMENITIES_LIST::{json}\n\n<caption>
 *   BOOKING_RESULT::{json}\n\n<caption>
 *   BYLAW_RESULT::{json}\n\n<caption>
 *
 * Anything else is rendered as plain conversational text. The contract
 * lives in `communityos-aria/chat_api.py::_structured_prefix`.
 */
import type { StructuredReply } from './types';

const PREFIX_KIND = {
  'AMENITIES_LIST::': 'amenities' as const,
  'BOOKING_RESULT::': 'booking' as const,
  'BYLAW_RESULT::':   'bylaw' as const,
};

export function parseStructured(reply: string): StructuredReply {
  if (!reply) return { kind: 'text', data: null, caption: '' };

  for (const [prefix, kind] of Object.entries(PREFIX_KIND) as Array<
    [keyof typeof PREFIX_KIND, (typeof PREFIX_KIND)[keyof typeof PREFIX_KIND]]
  >) {
    if (reply.startsWith(prefix)) {
      const newlineIdx = reply.indexOf('\n');
      const jsonStr =
        newlineIdx === -1
          ? reply.slice(prefix.length)
          : reply.slice(prefix.length, newlineIdx);
      const caption = newlineIdx === -1 ? '' : reply.slice(newlineIdx + 1).trim();
      try {
        const data = JSON.parse(jsonStr);
        return { kind, data, caption } as StructuredReply;
      } catch {
        // Malformed JSON — fall through to plain text so the user still
        // sees something instead of a silent failure.
        return { kind: 'text', data: null, caption: reply };
      }
    }
  }

  return { kind: 'text', data: null, caption: reply };
}
