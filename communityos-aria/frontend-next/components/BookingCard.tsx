import type { BookingPayload } from '@/lib/types';

export function BookingCard({ booking }: { booking: BookingPayload }) {
  const shortId = (booking.booking_id || '').slice(0, 8).toUpperCase();
  return (
    <div className="rounded-xl p-4 border border-success/40 bg-gradient-to-br from-success/10 to-secondary/5">
      <div className="flex items-start gap-4">
        <div className="w-12 h-12 rounded-lg flex items-center justify-center bg-success/15 text-success text-xl">
          ✓
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-text font-bold text-sm">Booking Confirmed</div>
          <div className="text-secondary font-semibold mt-0.5">{booking.amenity}</div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-textSoft text-[0.85rem]">
            {booking.date && (
              <span>
                <span className="text-textMute font-semibold">Date:</span> {booking.date}
              </span>
            )}
            {booking.slot && (
              <span>
                <span className="text-textMute font-semibold">Slot:</span> {booking.slot}
              </span>
            )}
            {booking.location && (
              <span>
                <span className="text-textMute font-semibold">Location:</span> {booking.location}
              </span>
            )}
          </div>
          {shortId && (
            <div className="mt-2 font-mono text-[0.72rem] text-textMute">ID: {shortId}</div>
          )}
        </div>
      </div>
    </div>
  );
}
