import type { Amenity } from '@/lib/types';

const TYPE_LABEL: Record<string, string> = {
  gym: 'Gym',
  pool: 'Pool',
  court_badminton: 'Badminton Court',
  court_tennis: 'Tennis Court',
  hall: 'Hall',
  studio: 'Studio',
  spa: 'Spa',
  library: 'Library',
  clubhouse: 'Clubhouse',
  other: 'Facility',
};

const TYPE_ACCENT: Record<string, string> = {
  gym: 'border-primary/30 text-primary',
  pool: 'border-secondary/30 text-secondary',
  court_badminton: 'border-success/30 text-success',
  court_tennis: 'border-success/30 text-success',
  hall: 'border-warning/30 text-warning',
  studio: 'border-primary/30 text-primary',
  spa: 'border-danger/30 text-danger',
  library: 'border-secondary/30 text-secondary',
  clubhouse: 'border-primary/30 text-primary',
  other: 'border-textMute/30 text-textMute',
};

export function AmenityCard({ amenity }: { amenity: Amenity }) {
  const features = (amenity.features || []).slice(0, 3);
  const locationLine = [amenity.block, amenity.floor].filter(Boolean).join(' • ') || amenity.location;
  const hours = `${amenity.open_time}–${amenity.close_time}`;
  const accent = TYPE_ACCENT[amenity.type] || TYPE_ACCENT.other;

  return (
    <div className="bg-surface border border-border rounded-xl p-4 flex flex-col gap-2 hover:-translate-y-0.5 hover:border-primary/40 transition-all">
      <div className="flex items-start gap-3">
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center bg-primary/10 ${accent.split(' ')[1]}`}>
          <span className="text-lg font-bold">{(TYPE_LABEL[amenity.type] || 'F')[0]}</span>
        </div>
        <div className="flex-1 min-w-0">
          <h4 className="text-text font-bold text-sm truncate">{amenity.display_name}</h4>
          <span className="text-textMute text-[0.65rem] uppercase tracking-wider font-semibold">
            {TYPE_LABEL[amenity.type] || amenity.type}
          </span>
        </div>
      </div>
      {amenity.description && (
        <p className="text-textSoft text-[0.82rem] leading-snug line-clamp-2">{amenity.description}</p>
      )}
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-textMute text-[0.72rem]">
        <span>📍 {locationLine}</span>
        <span>⏱ {hours}</span>
        <span>👥 Cap {amenity.capacity_per_slot}</span>
      </div>
      {features.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-1">
          {features.map((f) => (
            <span key={f} className="text-[0.68rem] px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20">
              {f}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function AmenityGrid({ items }: { items: Amenity[] }) {
  if (!items?.length) {
    return <p className="text-textMute text-sm italic p-3">No amenities found.</p>;
  }
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {items.map((a) => (
        <AmenityCard key={a.amenity_id} amenity={a} />
      ))}
    </div>
  );
}
