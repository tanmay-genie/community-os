import type { BylawPayload, BylawSection } from '@/lib/types';

function Section({ section }: { section: BylawSection }) {
  return (
    <div className="rounded-lg p-3.5 bg-surface border border-border border-l-[3px] border-l-secondary hover:border-secondary/60 transition-colors">
      <div className="flex items-baseline gap-3 mb-2">
        <span className="font-mono text-[0.78rem] font-bold text-secondary bg-secondary/10 px-2 py-0.5 rounded">
          §{section.section}
        </span>
        <h4 className="text-text font-semibold text-sm">{section.title}</h4>
      </div>
      <p className="text-textSoft text-[0.82rem] leading-relaxed whitespace-pre-line">{section.text}</p>
      <div className="text-textMute italic text-[0.7rem] text-right tracking-wide mt-2">
        — {section.citation}
      </div>
    </div>
  );
}

export function BylawCardList({ payload }: { payload: BylawPayload }) {
  const results = payload.results || [];
  if (!results.length) {
    return (
      <p className="text-textMute text-sm italic">
        No matching bylaw section found. Please check with your property manager.
      </p>
    );
  }
  return (
    <div className="space-y-3">
      {payload.question && (
        <p className="text-textSoft text-sm bg-primary/5 border-l-[3px] border-primary px-3 py-2 rounded-r-md">
          <span className="text-text font-semibold">Q:</span> {payload.question}
        </p>
      )}
      <div className="flex flex-col gap-2.5">
        {results.map((r) => (
          <Section key={`${r.section}-${r.title}`} section={r} />
        ))}
      </div>
    </div>
  );
}
