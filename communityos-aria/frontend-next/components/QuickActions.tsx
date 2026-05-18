'use client';

interface Action {
  id: string;
  icon: string;
  title: string;
  desc: string;
  prompt: string;
}

const ACTIONS: Action[] = [
  { id: 'all',       icon: '🏛️', title: 'All Amenities', desc: 'Browse every facility',     prompt: 'What amenities are available?' },
  { id: 'gyms',      icon: '💪', title: 'All Gyms',      desc: 'See every gym',             prompt: 'Show me all the gyms' },
  { id: 'pets',      icon: '🐕', title: 'Pet Rules',     desc: 'Bylaw lookup',              prompt: 'are pets allowed in the building?' },
  { id: 'airbnb',    icon: '🏠', title: 'Airbnb Policy', desc: 'Short-term rental rule',    prompt: 'can I list my unit on Airbnb?' },
  { id: 'quiet',     icon: '🔇', title: 'Quiet Hours',   desc: 'Noise bylaw',               prompt: 'what time do quiet hours start?' },
  { id: 'hardwood',  icon: '🪵', title: 'Hardwood Rule', desc: 'Flooring bylaw',            prompt: 'can I install hardwood floors?' },
  { id: 'book',      icon: '🏋️', title: 'Book Gym',      desc: 'Disambiguation demo',       prompt: 'book gym at 7pm tomorrow' },
  { id: 'dues',      icon: '💰', title: 'Check Fees',    desc: 'Strata + parking (CAD)',    prompt: 'any pending fees for me?' },
  { id: 'notices',   icon: '📢', title: 'Notices',       desc: 'Building announcements',    prompt: 'any new notices?' },
];

interface Props {
  onPick: (prompt: string) => void;
  disabled?: boolean;
}

export function QuickActions({ onPick, disabled }: Props) {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-3 gap-2">
      {ACTIONS.map((a) => (
        <button
          key={a.id}
          type="button"
          disabled={disabled}
          onClick={() => onPick(a.prompt)}
          className="text-left bg-surface border border-border rounded-lg p-3 hover:border-primary/40 hover:-translate-y-0.5 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <div className="text-lg mb-1">{a.icon}</div>
          <div className="text-text font-semibold text-sm">{a.title}</div>
          <div className="text-textMute text-[0.72rem] mt-0.5">{a.desc}</div>
        </button>
      ))}
    </div>
  );
}
