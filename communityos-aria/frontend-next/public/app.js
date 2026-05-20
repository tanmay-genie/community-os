/**
 * ARIA Dashboard — Complete Frontend Logic
 * Features: Markdown, Typewriter, Voice, Theme, i18n, localStorage,
 *           Admin panels, Escalation queue, Moderation, Export, File upload
 */

// ── State ─────────────────────────────────────────────────────────────
const state = {
  role: 'member',
  conversationId: '',
  theme: localStorage.getItem('aria-theme') || 'dark',
  messages: JSON.parse(localStorage.getItem('aria-messages') || '[]'),
  pendingImage: null,
  isRecording: false,
  token: localStorage.getItem('aria-token') || '',
  tokenExp: Number(localStorage.getItem('aria-token-exp') || 0),
};

// ── Auth (Bearer JWT) ─────────────────────────────────────────────────
function genRequestId() {
  return (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2)).slice(0, 32);
}

function isTokenValid() {
  return state.token && state.tokenExp > Math.floor(Date.now() / 1000) + 30;
}

async function login(baseUrl, twinId, apiKey, orgId) {
  const resp = await fetch(`${baseUrl}/aria/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ twin_id: twinId, api_key: apiKey, org_id: orgId }),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || `login failed (${resp.status})`);
  }
  const data = await resp.json();
  state.token = data.access_token;
  state.tokenExp = Math.floor(Date.now() / 1000) + (data.expires_in || 86400);
  localStorage.setItem('aria-token', state.token);
  localStorage.setItem('aria-token-exp', String(state.tokenExp));
  return data;
}

function clearToken() {
  state.token = '';
  state.tokenExp = 0;
  localStorage.removeItem('aria-token');
  localStorage.removeItem('aria-token-exp');
}

async function ensureToken(baseUrl, twinId, apiKey, orgId) {
  if (isTokenValid()) return state.token;
  await login(baseUrl, twinId, apiKey, orgId);
  return state.token;
}

async function authFetch(url, options = {}, baseUrl, twinId, apiKey, orgId) {
  const token = await ensureToken(baseUrl, twinId, apiKey, orgId);
  const headers = {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`,
    'X-Request-ID': genRequestId(),
    ...(options.headers || {}),
  };
  let resp = await fetch(url, { ...options, headers });
  if (resp.status === 401) {
    clearToken();
    const fresh = await ensureToken(baseUrl, twinId, apiKey, orgId);
    resp = await fetch(url, {
      ...options,
      headers: { ...headers, 'Authorization': `Bearer ${fresh}` },
    });
  }
  return resp;
}

// ── Strings (English-only) ────────────────────────────────────────────
const STRINGS = {
  theme: 'Theme', mode: 'Mode', member: 'Member', admin: 'Admin',
  configuration: 'Configuration', checkHealth: 'Check Health', clearChat: 'Clear Chat',
  exportReport: 'Export Report', quickActions: 'Quick Actions', societyInsights: 'Building Insights',
  totalTickets: 'Total Tickets', pendingEscalations: 'Pending Escalations',
  avgResponseTime: 'Avg Response Time', activeResidents: 'Active Residents',
  ticketsThisWeek: 'Tickets This Week', escalationQueue: 'Escalation Queue',
  selectAll: 'Select All', bulkApprove: 'Bulk Approve', bulkDeny: 'Bulk Deny',
  contentModeration: 'Content Moderation', editAnnouncement: 'Edit Announcement',
  cancel: 'Cancel', publish: 'Publish', chat: 'Chat', actions: 'Actions', settings: 'Settings',
  askAria: 'Ask ARIA anything...',
  greeting: "Hi! I'm ARIA, your building assistant. Try asking \"what amenities are here?\" or \"show me all the gyms\" — or tap any quick action above.",
  cleared: 'Chat cleared. Send me a message or click a quick action to begin.',
};

function t(key) { return STRINGS[key] || key; }

function applyI18n() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    const text = t(key);
    if (text) el.textContent = text;
  });
  const chatInput = document.getElementById('chat-input');
  if (chatInput) chatInput.placeholder = t('askAria');
}

// ── DOM ───────────────────────────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const chatMessages   = $('#chat-messages');
const chatInput      = $('#chat-input');
const chatForm       = $('#chat-form');
const actionsGrid    = $('#actions-grid');
const connStatus     = $('#connection-status');
const roleBadge      = $('#topbar-role-badge');
const sidebarToggle  = $('#sidebar-toggle');
const sidebar        = $('#sidebar');
const btnHealth      = $('#btn-health');
const btnClear       = $('#btn-clear');
const btnExport      = $('#btn-export');
const themeToggle    = $('#theme-toggle');
const btnVoice       = $('#btn-voice');
const btnAttach      = $('#btn-attach');
const fileInput      = $('#file-input');
const imagePreview   = $('#image-preview');

const cfgTwin = $('#cfg-twin');
const cfgOrg  = $('#cfg-org');
const cfgKey  = $('#cfg-key');
const cfgUrl  = $('#cfg-url');

// ── Notification Sound ───────────────────────────────────────────────
function playNotificationSound() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.type = 'sine';
    osc.frequency.setValueAtTime(880, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(660, ctx.currentTime + 0.15);
    gain.gain.setValueAtTime(0.08, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.3);
    osc.start(ctx.currentTime);
    osc.stop(ctx.currentTime + 0.3);
  } catch (e) { /* silent fail */ }
}

// ── Structured Payload Parser (AMENITIES_LIST / BOOKING_RESULT) ──────
// ARIA's chat reply may begin with a control prefix that the frontend
// renders as rich cards. The prefix has the shape:
//   AMENITIES_LIST::{json}\n\n<caption>
//   BOOKING_RESULT::{json}\n\n<caption>
// Anything that doesn't match falls through to the normal markdown path.
function extractStructured(text) {
  if (!text) return { kind: null, data: null, caption: text || '' };
  const PREFIX_KIND = {
    'AMENITIES_LIST::': 'amenities',
    'BOOKING_RESULT::': 'booking',
    'BYLAW_RESULT::':   'bylaw',
  };
  for (const p of Object.keys(PREFIX_KIND)) {
    if (text.startsWith(p)) {
      const newlineIdx = text.indexOf('\n');
      const jsonStr = newlineIdx === -1 ? text.slice(p.length) : text.slice(p.length, newlineIdx);
      const caption = newlineIdx === -1 ? '' : text.slice(newlineIdx + 1).trim();
      try {
        const data = JSON.parse(jsonStr);
        return { kind: PREFIX_KIND[p], data, caption };
      } catch (err) {
        console.warn('Failed to parse structured payload:', err, jsonStr.slice(0, 120));
        return { kind: null, data: null, caption: text };
      }
    }
  }
  return { kind: null, data: null, caption: text };
}

// Inline SVG icons keyed by amenity type. Falls back to a neutral building icon.
const AMENITY_ICONS = {
  gym:             '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6.5 6.5h11v11h-11z"/><path d="M3 9v6M21 9v6M6.5 12h11"/></svg>',
  pool:            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 17c2 0 2-2 5-2s3 2 5 2 3-2 5-2 3 2 5 2"/><path d="M2 13c2 0 2-2 5-2s3 2 5 2 3-2 5-2 3 2 5 2"/><path d="M8 4h8v9H8z"/></svg>',
  court_badminton: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="6" r="3"/><path d="M8 8l12 12M9 5l5 5"/></svg>',
  court_tennis:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M3.5 12c2.5-3 7-4 8.5-4s6 1 8.5 4"/><path d="M3.5 12c2.5 3 7 4 8.5 4s6-1 8.5-4"/></svg>',
  hall:            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21h18M5 21V7l7-4 7 4v14M9 9h2v3H9zm4 0h2v3h-2zM9 14h2v3H9zm4 0h2v3h-2z"/></svg>',
  studio:          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2C8 6 8 9 12 13c4-4 4-7 0-11z"/><path d="M5 22c0-4 3-7 7-7s7 3 7 7"/></svg>',
  spa:             '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s-3-4-3-9c0-3 1.5-5 3-5s3 2 3 5c0 5-3 9-3 9z"/><path d="M5 13c2-1 4 0 5 2M19 13c-2-1-4 0-5 2"/></svg>',
  library:         '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h6a3 3 0 013 3v13a2 2 0 00-2-2H4zM20 4h-6a3 3 0 00-3 3v13a2 2 0 012-2h7z"/></svg>',
  clubhouse:       '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l2.5 5 5.5.8-4 4 1 5.5L12 14.8l-5 2.5 1-5.5-4-4 5.5-.8z"/></svg>',
  other:           '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21h18M5 21V8l7-5 7 5v13"/></svg>',
};

const TYPE_LABEL = {
  gym: 'Gym', pool: 'Pool',
  court_badminton: 'Badminton Court', court_tennis: 'Tennis Court',
  hall: 'Hall', studio: 'Studio', spa: 'Spa',
  library: 'Library', clubhouse: 'Clubhouse', other: 'Facility',
};

function amenityCardHTML(item) {
  const t = item.type || 'other';
  const icon = AMENITY_ICONS[t] || AMENITY_ICONS.other;
  const features = (item.features || []).slice(0, 3);
  const chipHtml = features.map(f => `<span class="amenity-chip">${escapeHtml(f)}</span>`).join('');
  const locationLine = [item.block, item.floor].filter(Boolean).join(' • ') || (item.location || '');
  const hours = `${item.open_time || ''}-${item.close_time || ''}`;
  return `
    <div class="amenity-card" data-amenity-id="${escapeHtml(item.amenity_id || '')}" data-amenity-name="${escapeHtml(item.display_name || '')}" data-amenity-type="${escapeHtml(t)}">
      <div class="amenity-card-head">
        <div class="amenity-icon amenity-icon-${escapeHtml(t)}">${icon}</div>
        <div class="amenity-card-title">
          <h4>${escapeHtml(item.display_name || item.name || 'Amenity')}</h4>
          <span class="amenity-type-tag">${escapeHtml(TYPE_LABEL[t] || t)}</span>
        </div>
      </div>
      <p class="amenity-card-desc">${escapeHtml(item.description || '')}</p>
      <div class="amenity-card-meta">
        <span class="amenity-meta-item"><svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14"><path fill-rule="evenodd" d="M5.05 4.05a7 7 0 119.9 9.9L10 18.9l-4.95-4.95a7 7 0 010-9.9zM10 11a2 2 0 100-4 2 2 0 000 4z" clip-rule="evenodd"/></svg>${escapeHtml(locationLine)}</span>
        <span class="amenity-meta-item"><svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clip-rule="evenodd"/></svg>${escapeHtml(hours)}</span>
        <span class="amenity-meta-item"><svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14"><path d="M9 6a3 3 0 11-6 0 3 3 0 016 0zM17 6a3 3 0 11-6 0 3 3 0 016 0zM12.93 17c.046-.327.07-.66.07-1a6.97 6.97 0 00-1.5-4.33A5 5 0 0119 16v1h-6.07zM6 11a5 5 0 015 5v1H1v-1a5 5 0 015-5z"/></svg>Cap ${escapeHtml(String(item.capacity_per_slot || ''))}</span>
      </div>
      <div class="amenity-card-chips">${chipHtml}</div>
      <div class="amenity-card-actions">
        <button type="button" class="amenity-btn amenity-btn-info">Details</button>
        <button type="button" class="amenity-btn amenity-btn-book">Book</button>
      </div>
    </div>
  `;
}

function amenityGridHTML(items) {
  if (!items || items.length === 0) return '<p class="amenity-empty">No amenities found.</p>';
  return `<div class="amenity-grid">${items.map(amenityCardHTML).join('')}</div>`;
}

function bookingConfirmationHTML(b) {
  const t = b.type || 'other';
  const icon = AMENITY_ICONS[t] || AMENITY_ICONS.other;
  return `
    <div class="booking-confirmation">
      <div class="booking-icon">${icon}</div>
      <div class="booking-body">
        <div class="booking-title">Booking Confirmed</div>
        <div class="booking-amenity">${escapeHtml(b.amenity || '')}</div>
        <div class="booking-meta">
          <span><strong>Date:</strong> ${escapeHtml(b.date || '')}</span>
          <span><strong>Slot:</strong> ${escapeHtml(b.slot || '')}</span>
          <span><strong>Location:</strong> ${escapeHtml(b.location || '')}</span>
        </div>
        <div class="booking-id">ID: ${escapeHtml((b.booking_id || '').slice(0, 8).toUpperCase())}</div>
      </div>
    </div>
  `;
}

// Resolves the date the user is asking about for the slot picker default.
function defaultBookingISODate() {
  return new Date().toISOString().slice(0, 10);
}

// Open the slot-picker modal for a specific amenity.
async function openSlotPicker(amenityId, amenityName) {
  const baseUrl = cfgUrl.value.replace(/\/+$/, '');
  const orgId = cfgOrg.value;
  const twinId = cfgTwin.value;
  const dateISO = defaultBookingISODate();
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay slot-picker-overlay';
  overlay.innerHTML = `
    <div class="modal-content slot-picker-modal">
      <div class="modal-header">
        <h3>Pick a slot — ${escapeHtml(amenityName || '')}</h3>
        <button type="button" class="modal-close-btn" aria-label="Close">&times;</button>
      </div>
      <div class="slot-picker-controls">
        <label>Date <input type="date" class="slot-date-input" value="${dateISO}" /></label>
        <button type="button" class="modal-btn modal-btn-secondary slot-refresh">Refresh</button>
      </div>
      <div class="slot-list" aria-live="polite"><p class="amenity-empty">Loading slots...</p></div>
    </div>
  `;
  document.body.appendChild(overlay);
  const close = () => overlay.remove();
  overlay.querySelector('.modal-close-btn').addEventListener('click', close);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });

  async function loadSlots() {
    const dateInput = overlay.querySelector('.slot-date-input');
    const list = overlay.querySelector('.slot-list');
    list.innerHTML = '<p class="amenity-empty">Loading slots...</p>';
    try {
      const params = new URLSearchParams({ org_id: orgId, date: dateInput.value });
      if (amenityId) params.set('amenity_id', amenityId);
      else if (amenityName) params.set('amenity', amenityName);
      const resp = await fetch(`${baseUrl}/society/amenities/slots?${params}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      if (data.error) {
        list.innerHTML = `<p class="amenity-empty">${escapeHtml(data.error)}</p>`;
        return;
      }
      const slots = data.slots || [];
      if (slots.length === 0) {
        list.innerHTML = '<p class="amenity-empty">No slots configured for this date.</p>';
        return;
      }
      list.innerHTML = slots.map(s => `
        <button type="button" class="slot-chip ${s.available ? '' : 'slot-chip-full'}" data-start="${escapeHtml(s.slot_start)}" ${s.available ? '' : 'disabled'}>
          <span class="slot-time">${escapeHtml(s.slot_start)}–${escapeHtml(s.slot_end)}</span>
          <span class="slot-remaining">${s.remaining}/${s.capacity}</span>
        </button>
      `).join('');
      list.querySelectorAll('.slot-chip:not([disabled])').forEach(btn => {
        btn.addEventListener('click', async () => {
          btn.disabled = true;
          btn.classList.add('slot-chip-loading');
          try {
            const params2 = new URLSearchParams({
              org_id: orgId, twin_id: twinId,
              date: dateInput.value, slot_start: btn.dataset.start,
            });
            if (amenityId) params2.set('amenity_id', amenityId);
            else if (amenityName) params2.set('amenity', amenityName);
            const resp2 = await fetch(`${baseUrl}/society/bookings?${params2}`, { method: 'POST' });
            const data2 = await resp2.json();
            if (resp2.ok && data2.success) {
              showToast(`Booked ${data2.amenity || amenityName} for ${data2.slot}`, 'success');
              appendStructuredMessage('booking', data2, '');
              close();
            } else {
              const detail = (data2.detail && data2.detail.error) || data2.error || data2.detail || `HTTP ${resp2.status}`;
              showToast(`Booking failed: ${detail}`, 'error');
              btn.disabled = false;
              btn.classList.remove('slot-chip-loading');
            }
          } catch (err) {
            showToast(`Booking failed: ${err.message}`, 'error');
            btn.disabled = false;
            btn.classList.remove('slot-chip-loading');
          }
        });
      });
    } catch (err) {
      list.innerHTML = `<p class="amenity-empty">Could not load slots: ${escapeHtml(err.message)}</p>`;
    }
  }

  overlay.querySelector('.slot-refresh').addEventListener('click', loadSlots);
  overlay.querySelector('.slot-date-input').addEventListener('change', loadSlots);
  loadSlots();
}

async function showAmenityDetails(amenityId, amenityName) {
  const baseUrl = cfgUrl.value.replace(/\/+$/, '');
  const orgId = cfgOrg.value;
  let info = null;
  try {
    if (amenityId) {
      const resp = await fetch(`${baseUrl}/society/amenities/${encodeURIComponent(amenityId)}?org_id=${encodeURIComponent(orgId)}`);
      if (resp.ok) info = await resp.json();
    }
  } catch (err) { /* fall through */ }
  if (!info) {
    sendMessage(`Tell me about ${amenityName}`);
    return;
  }
  const features = (info.features || []).map(f => `<span class="amenity-chip">${escapeHtml(f)}</span>`).join('');
  const card = `
    <div class="amenity-detail-card">
      <h4>${escapeHtml(info.display_name)}</h4>
      <p>${escapeHtml(info.description || '')}</p>
      <p><strong>Location:</strong> ${escapeHtml(info.location || '')}</p>
      <p><strong>Hours:</strong> ${escapeHtml(info.open_time || '')}–${escapeHtml(info.close_time || '')}</p>
      <p><strong>Capacity per slot:</strong> ${escapeHtml(String(info.capacity_per_slot || ''))}</p>
      <div class="amenity-card-chips">${features}</div>
    </div>
  `;
  appendRawHTML('system', card, '');
}

// ── Markdown Parser ──────────────────────────────────────────────────
function parseMarkdown(text) {
  if (!text) return '';
  let html = escapeHtml(text);

  // Code blocks (``` ... ```)
  html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) =>
    `<pre><code>${code.trim()}</code></pre>`
  );
  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  // Bold **text** or __text__
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/__(.+?)__/g, '<strong>$1</strong>');
  // Italic *text* or _text_
  html = html.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em>$1</em>');
  html = html.replace(/(?<!_)_([^_]+)_(?!_)/g, '<em>$1</em>');
  // Unordered lists
  html = html.replace(/^[\-\*] (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');
  // Ordered lists
  html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
  // Tables
  html = html.replace(/^(\|.+\|)\n(\|[\-\s|:]+\|)\n((?:\|.+\|\n?)+)/gm, (_, header, sep, body) => {
    const ths = header.split('|').filter(c => c.trim()).map(c => `<th>${c.trim()}</th>`).join('');
    const rows = body.trim().split('\n').map(row => {
      const tds = row.split('|').filter(c => c.trim()).map(c => `<td>${c.trim()}</td>`).join('');
      return `<tr>${tds}</tr>`;
    }).join('');
    return `<table><thead><tr>${ths}</tr></thead><tbody>${rows}</tbody></table>`;
  });
  // Paragraphs (double newline)
  html = html.replace(/\n\n/g, '</p><p>');
  // Single newlines to <br>
  html = html.replace(/\n/g, '<br>');
  // Wrap in paragraph
  html = `<p>${html}</p>`;
  // Clean up empty paragraphs
  html = html.replace(/<p>\s*<\/p>/g, '');

  return html;
}

function escapeHtml(text) {
  const el = document.createElement('span');
  el.textContent = text;
  return el.innerHTML;
}

// ── Time Helper ──────────────────────────────────────────────────────
function timeNow() {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// ── Quick Action Definitions ─────────────────────────────────────────
const MEMBER_ACTIONS = [
  // Discovery first \u2014 these showcase the multi-instance amenity catalogue.
  { id: 'all-amenities',icon: '\u{1F3DB}', iconClass: 'icon-purple', title: 'All Amenities',  desc: 'Browse every facility',      message: 'What amenities are available?' },
  { id: 'all-gyms',     icon: '\u{1F4AA}', iconClass: 'icon-blue',   title: 'All Gyms',       desc: 'See every gym & location',   message: 'Show me all the gyms' },
  { id: 'all-courts',   icon: '\u{1F3BE}', iconClass: 'icon-green',  title: 'All Courts',     desc: 'Tennis & badminton',         message: 'Show me all courts available' },
  { id: 'all-pools',    icon: '\u{1F3CA}', iconClass: 'icon-cyan',   title: 'All Pools',      desc: 'Pools and splash zones',     message: 'Show me all the pools' },
  // Booking magic \u2014 ambiguous "Book Gym" demonstrates disambiguation.
  { id: 'book-gym',     icon: '\u{1F3CB}', iconClass: 'icon-blue',   title: 'Book Gym',       desc: 'ARIA picks the right one',   message: 'Book gym at 7pm tomorrow' },
  { id: 'book-blocka',  icon: '\u{1F3CB}', iconClass: 'icon-purple', title: 'Block A Gym',    desc: 'Direct slot booking',        message: 'Book Block A gym tomorrow at 8am' },
  { id: 'book-club',    icon: '\u{1F3E0}', iconClass: 'icon-purple', title: 'Book Clubhouse', desc: 'Reserve the clubhouse',      message: 'I want to book the clubhouse for Saturday evening' },
  { id: 'spa-info',     icon: '\u{1F4AB}', iconClass: 'icon-yellow', title: 'Spa Details',    desc: 'Hours, features, location',  message: 'Tell me about the wellness spa' },
  // Bylaw lookups — citation-grounded answers from condo rules
  { id: 'bylaw-pets',    icon: '\u{1F415}', iconClass: 'icon-purple', title: 'Pet Rules',       desc: 'Bylaw lookup',               message: 'are pets allowed in the building?' },
  { id: 'bylaw-airbnb',  icon: '\u{1F3D8}', iconClass: 'icon-cyan',   title: 'Airbnb Policy',   desc: 'Short-term rental rule',     message: 'can I list my unit on Airbnb?' },
  { id: 'bylaw-quiet',   icon: '\u{1F507}', iconClass: 'icon-blue',   title: 'Quiet Hours',     desc: 'Noise bylaw',                message: 'what time do quiet hours start?' },
  { id: 'bylaw-floor',   icon: '\u{1FA9C}', iconClass: 'icon-green',  title: 'Hardwood Rule',   desc: 'Flooring bylaw',             message: 'can I install hardwood floors?' },
  // Lifecycle (tickets, dues, events, notices, RSVP).
  { id: 'raise-ticket', icon: '\u{1F527}', iconClass: 'icon-red',    title: 'Raise Ticket',   desc: 'Report maintenance issue',   message: 'AC not working in my flat' },
  { id: 'urgent-ticket',icon: '\u{1F6A8}', iconClass: 'icon-orange', title: 'Urgent Issue',   desc: 'Report an emergency',        message: 'There is a water leakage flooding in my bathroom, urgent!' },
  { id: 'check-events', icon: '\u{1F389}', iconClass: 'icon-pink',   title: 'Events Today',   desc: "What's happening?",          message: 'What events are happening today?' },
  { id: 'check-dues',   icon: '\u{1F4B0}', iconClass: 'icon-yellow', title: 'Check Dues',     desc: 'View pending payments',      message: 'Do I have any pending dues?' },
  { id: 'pay-rent',     icon: '\u{1F4B3}', iconClass: 'icon-green',  title: 'Pay Strata Fee', desc: 'Initiate fee payment',       message: 'Pay my strata fee of $480' },
  { id: 'notices',      icon: '\u{1F4E2}', iconClass: 'icon-purple', title: 'Notices',        desc: 'Latest announcements',       message: 'Any new notices from the society?' },
  { id: 'rsvp',         icon: '\u{270B}',  iconClass: 'icon-cyan',   title: 'RSVP Event',     desc: 'Join an upcoming event',     message: 'Sign me up for the rooftop social' },
];

const ADMIN_ACTIONS = [
  { id: 'insights',      icon: '\u{1F4CA}', iconClass: 'icon-blue',   title: 'Society Insights',    desc: 'AI-powered health report',     message: 'Give me a society summary for last 7 days' },
  { id: 'ticket-trends', icon: '\u{1F4C8}', iconClass: 'icon-cyan',   title: 'Ticket Trends',       desc: 'Complaint pattern detection',  message: 'What are residents complaining about most?' },
  { id: 'escalations',   icon: '\u{26A0}',  iconClass: 'icon-yellow', title: 'Pending Escalations', desc: 'Approval queue',               message: 'Show me all pending escalations' },
  { id: 'approve',       icon: '\u{2705}',  iconClass: 'icon-green',  title: 'Approve Task',        desc: 'Green-light a pending item',   message: 'Approve the most urgent escalation' },
  { id: 'deny',          icon: '\u{274C}',  iconClass: 'icon-red',    title: 'Deny Task',           desc: 'Reject a pending escalation',  message: 'Deny the latest escalation, reason: not justified' },
  { id: 'announcement',  icon: '\u{1F4DD}', iconClass: 'icon-purple', title: 'Draft Announcement',  desc: 'Generate a society notice',    message: 'Write an announcement about water supply disruption tomorrow from 10am to 2pm' },
  { id: 'event-desc',    icon: '\u{1F38A}', iconClass: 'icon-pink',   title: 'Event Description',   desc: 'Auto-generate event post',     message: 'Write a description for Republic Day celebration on 26th Jan at the clubhouse' },
  { id: 'moderate',      icon: '\u{1F6E1}', iconClass: 'icon-orange', title: 'Moderate Content',    desc: 'Check a post for violations',  message: 'Check this message for violations: "The security guard is a fraud and cheat"' },
];

// ── Escalation Data (simulated) ──────────────────────────────────────
const ESCALATION_DATA = [
  { id: 'ESC-001', title: 'Pool pump replacement approval', desc: 'Contractor requesting CAD $4,500 for pump replacement', sla: '2h 15m', slaClass: 'sla-ok' },
  { id: 'ESC-002', title: 'Parking spot reassignment', desc: 'Resident in Tower 2 #404 requesting swap with #201', sla: '45m', slaClass: 'sla-warn' },
  { id: 'ESC-003', title: 'Security camera installation', desc: 'New cameras for parking Level P2 — vendor quote pending', sla: '15m', slaClass: 'sla-critical' },
  { id: 'ESC-004', title: 'Annual rooftop social budget', desc: 'Social committee requesting CAD $2,000 for spring event', sla: '5h 30m', slaClass: 'sla-ok' },
];

// ── Moderation Data (simulated) ──────────────────────────────────────
const MODERATION_DATA = [
  { user: 'Resident T1-203', content: '"The concierge was sleeping again during the night shift!"', severity: 'medium', reason: 'Accusation without evidence' },
  { user: 'Resident T2-101', content: '"This strata council is completely incompetent"', severity: 'high', reason: 'Disparaging language against the board' },
  { user: 'Resident T1-505', content: '"Don\'t park in my spot or face consequences"', severity: 'low', reason: 'Mildly threatening tone' },
];

// ── Render Quick Actions ─────────────────────────────────────────────
function renderActions() {
  const actions = state.role === 'admin' ? ADMIN_ACTIONS : MEMBER_ACTIONS;
  actionsGrid.innerHTML = '';
  actions.forEach((a) => {
    const card = document.createElement('div');
    card.className = 'action-card';
    card.innerHTML = `
      <div class="action-icon ${a.iconClass}">${a.icon}</div>
      <div class="action-title">${a.title}</div>
      <div class="action-desc">${a.desc}</div>
    `;
    card.addEventListener('click', () => sendMessage(a.message));
    actionsGrid.appendChild(card);
  });
}

// ── Admin Panels ─────────────────────────────────────────────────────
function renderAdminPanels() {
  const dashboard = $('#admin-dashboard');
  const escQueue = $('#escalation-queue');
  const modPanel = $('#moderation-panel');

  if (state.role === 'admin') {
    dashboard.classList.remove('hidden');
    escQueue.classList.remove('hidden');
    modPanel.classList.remove('hidden');
    renderEscalations();
    renderModeration();
  } else {
    dashboard.classList.add('hidden');
    escQueue.classList.add('hidden');
    modPanel.classList.add('hidden');
  }
}

function renderEscalations() {
  const container = $('#escalation-cards');
  container.innerHTML = ESCALATION_DATA.map(e => `
    <div class="esc-card" data-id="${e.id}">
      <div class="esc-header">
        <span class="esc-id">${e.id}</span>
        <span class="esc-sla ${e.slaClass}">${e.sla} left</span>
      </div>
      <div class="esc-title">${e.title}</div>
      <div class="esc-desc">${e.desc}</div>
      <div class="esc-actions">
        <input type="checkbox" class="esc-check" data-id="${e.id}" />
        <button class="esc-btn esc-btn-approve" onclick="handleEscalation('${e.id}','approve')">Approve</button>
        <button class="esc-btn esc-btn-deny" onclick="handleEscalation('${e.id}','deny')">Deny</button>
      </div>
    </div>
  `).join('');
}

function renderModeration() {
  const container = $('#moderation-cards');
  container.innerHTML = MODERATION_DATA.map(m => `
    <div class="mod-card">
      <div class="mod-header">
        <span class="mod-user">${m.user}</span>
        <span class="severity-badge severity-${m.severity}">${m.severity}</span>
      </div>
      <div class="mod-content">${m.content}</div>
      <div class="mod-reason">${m.reason}</div>
    </div>
  `).join('');
}

window.handleEscalation = function(id, action) {
  const msg = action === 'approve'
    ? `Approve escalation ${id}`
    : `Deny escalation ${id}, reason: reviewed and rejected`;
  sendMessage(msg);
};

// ── Bulk Actions ─────────────────────────────────────────────────────
const bulkSelectAll = $('#bulk-select-all');
const bulkActions = $('#bulk-actions');
const bulkApproveBtn = $('#bulk-approve-btn');
const bulkDenyBtn = $('#bulk-deny-btn');

if (bulkSelectAll) {
  bulkSelectAll.addEventListener('change', () => {
    const checks = $$('.esc-check');
    checks.forEach(c => c.checked = bulkSelectAll.checked);
    updateBulkVisibility();
  });

  document.addEventListener('change', (e) => {
    if (e.target.classList.contains('esc-check')) updateBulkVisibility();
  });
}

function updateBulkVisibility() {
  const checked = $$('.esc-check:checked');
  if (bulkActions) {
    if (checked.length > 0) bulkActions.classList.remove('hidden');
    else bulkActions.classList.add('hidden');
  }
}

if (bulkApproveBtn) bulkApproveBtn.addEventListener('click', () => {
  const ids = [...$$('.esc-check:checked')].map(c => c.dataset.id);
  sendMessage(`Bulk approve escalations: ${ids.join(', ')}`);
});
if (bulkDenyBtn) bulkDenyBtn.addEventListener('click', () => {
  const ids = [...$$('.esc-check:checked')].map(c => c.dataset.id);
  sendMessage(`Bulk deny escalations: ${ids.join(', ')}, reason: batch review completed`);
});

// ── Role Switching ───────────────────────────────────────────────────
// Each role uses a different twin + API key (the backend authorises admin
// tools strictly by JWT role claim, not by client UI state). Toggling roles
// must therefore swap credentials AND drop the existing token so the next
// request triggers a fresh login under the new identity.
const ROLE_CREDENTIALS = {
  member: { twin_id: 'tanmay_resident',  api_key: 'tanmay-key-001' },
  admin:  { twin_id: 'communityos_ops',  api_key: 'ops-key-001'    },
};

$$('.role-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    const newRole = btn.dataset.role;
    if (newRole === state.role) return;

    $$('.role-btn').forEach((b) => b.classList.remove('active'));
    btn.classList.add('active');
    state.role = newRole;
    roleBadge.textContent = state.role === 'admin' ? t('admin') : t('member');
    roleBadge.className = `role-badge ${state.role === 'admin' ? 'role-admin' : 'role-member'}`;

    const creds = ROLE_CREDENTIALS[newRole];
    if (creds) {
      cfgTwin.value = creds.twin_id;
      cfgKey.value  = creds.api_key;
      clearToken();
    }

    renderActions();
    renderAdminPanels();
    showToast(`Switched to ${state.role} mode — re-authenticating as ${creds ? creds.twin_id : '?'}`, 'info');
  });
});

// ── Theme Toggle ─────────────────────────────────────────────────────
function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  state.theme = theme;
  localStorage.setItem('aria-theme', theme);
}

themeToggle.addEventListener('click', () => {
  applyTheme(state.theme === 'dark' ? 'light' : 'dark');
});

// ── Sidebar Toggle ───────────────────────────────────────────────────
sidebarToggle.addEventListener('click', () => sidebar.classList.toggle('open'));
document.addEventListener('click', (e) => {
  if (window.innerWidth <= 768 && sidebar.classList.contains('open')) {
    if (!sidebar.contains(e.target) && e.target !== sidebarToggle && !sidebarToggle.contains(e.target)) {
      sidebar.classList.remove('open');
    }
  }
});

// ── Mobile Bottom Nav ────────────────────────────────────────────────
$$('.mobile-nav-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    $$('.mobile-nav-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const tab = btn.dataset.tab;

    const chatSection = $('#chat-section');
    const quickActions = $('#quick-actions');
    const adminDash = $('#admin-dashboard');
    const escQueue = $('#escalation-queue');
    const modPanel = $('#moderation-panel');
    const mobileSettings = $('#mobile-settings');

    // Hide all
    [chatSection, quickActions].forEach(s => s.style.display = 'none');
    if (adminDash) adminDash.style.display = 'none';
    if (escQueue) escQueue.style.display = 'none';
    if (modPanel) modPanel.style.display = 'none';
    mobileSettings.classList.add('hidden');

    if (tab === 'chat') {
      chatSection.style.display = 'flex';
    } else if (tab === 'actions') {
      quickActions.style.display = 'block';
      if (state.role === 'admin') {
        if (adminDash) adminDash.style.display = 'block';
        if (escQueue) escQueue.style.display = 'block';
        if (modPanel) modPanel.style.display = 'block';
      }
    } else if (tab === 'settings') {
      mobileSettings.classList.remove('hidden');
      populateMobileSettings();
    }
  });
});

function populateMobileSettings() {
  const body = $('#mobile-settings-body');
  body.innerHTML = `
    <div class="config-section" style="margin-bottom:12px">
      <div class="sidebar-toggle-row">
        <div class="toggle-card"><span class="toggle-label">${t('theme')}</span>
          <button class="theme-btn" id="m-theme">${state.theme === 'dark' ? '\u{1F319}' : '\u{2600}'}</button>
        </div>
      </div>
    </div>
    <div class="config-section">
      <h3 class="config-title">${t('configuration')}</h3>
      <div class="config-field"><label>Twin ID</label><input value="${cfgTwin.value}" onchange="document.getElementById('cfg-twin').value=this.value" /></div>
      <div class="config-field"><label>Org ID</label><input value="${cfgOrg.value}" onchange="document.getElementById('cfg-org').value=this.value" /></div>
      <div class="config-field"><label>API Key</label><input value="${cfgKey.value}" onchange="document.getElementById('cfg-key').value=this.value" /></div>
      <div class="config-field"><label>Chat API URL</label><input value="${cfgUrl.value}" onchange="document.getElementById('cfg-url').value=this.value" /></div>
    </div>
  `;
  const mTheme = body.querySelector('#m-theme');
  if (mTheme) mTheme.addEventListener('click', () => { applyTheme(state.theme === 'dark' ? 'light' : 'dark'); populateMobileSettings(); });
}

$('#mobile-settings-close')?.addEventListener('click', () => {
  $('#mobile-settings').classList.add('hidden');
  $$('.mobile-nav-btn').forEach(b => b.classList.remove('active'));
  $$('.mobile-nav-btn')[0]?.classList.add('active');
  $('#chat-section').style.display = 'flex';
});

// ── Chat Submit ──────────────────────────────────────────────────────
chatForm.addEventListener('submit', (e) => {
  e.preventDefault();
  const msg = chatInput.value.trim();
  if (!msg && !state.pendingImage) return;
  chatInput.value = '';
  sendMessage(msg);
});

// ── File/Image Upload ────────────────────────────────────────────────
btnAttach.addEventListener('click', () => fileInput.click());

fileInput.addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (ev) => {
    state.pendingImage = ev.target.result;
    imagePreview.classList.remove('hidden');
    imagePreview.innerHTML = `
      <img src="${ev.target.result}" alt="preview" />
      <button class="remove-preview" onclick="removePendingImage()">&times;</button>
    `;
  };
  reader.readAsDataURL(file);
  fileInput.value = '';
});

window.removePendingImage = function() {
  state.pendingImage = null;
  imagePreview.classList.add('hidden');
  imagePreview.innerHTML = '';
};

// ── Voice Input ──────────────────────────────────────────────────────
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

if (SpeechRecognition) {
  const recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.lang = 'en-IN';

  recognition.onresult = (event) => {
    let transcript = '';
    for (let i = event.resultIndex; i < event.results.length; i++) {
      transcript += event.results[i][0].transcript;
    }
    chatInput.value = transcript;
  };

  recognition.onend = () => {
    state.isRecording = false;
    btnVoice.classList.remove('recording');
    const msg = chatInput.value.trim();
    if (msg) {
      chatInput.value = '';
      sendMessage(msg);
    }
  };

  recognition.onerror = () => {
    state.isRecording = false;
    btnVoice.classList.remove('recording');
  };

  btnVoice.addEventListener('click', () => {
    if (state.isRecording) {
      recognition.stop();
    } else {
      state.isRecording = true;
      btnVoice.classList.add('recording');
      recognition.start();
    }
  });
} else {
  btnVoice.style.display = 'none';
}

// ── Send Message ─────────────────────────────────────────────────────
async function sendMessage(text) {
  const imageData = state.pendingImage;
  removePendingImage();

  appendMessage('user', text, null, imageData);
  saveMessages();
  const typingEl = showTyping();

  try {
    const baseUrl = cfgUrl.value.replace(/\/+$/, '');
    const resp = await authFetch(
      `${baseUrl}/aria/chat`,
      {
        method: 'POST',
        body: JSON.stringify({
          role: state.role,
          message: text,
          conversation_id: state.conversationId,
        }),
      },
      baseUrl, cfgTwin.value, cfgKey.value, cfgOrg.value,
    );

    removeTyping(typingEl);

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      if (resp.status === 429 && errData.detail && errData.detail.kind) {
        throw new Error(`Rate limit hit (${errData.detail.kind}). Retry in ${errData.detail.retry_after_s || 60}s.`);
      }
      throw new Error(typeof errData.detail === 'string' ? errData.detail : `HTTP ${resp.status}`);
    }

    const data = await resp.json();
    state.conversationId = data.conversation_id || state.conversationId;

    // Detect structured payloads (AMENITIES_LIST::, BOOKING_RESULT::) and
    // render rich cards. Otherwise fall back to the typewriter.
    const parsed = extractStructured(data.reply || '');
    if (parsed.kind === 'amenities') {
      appendStructuredMessage('amenities', parsed.data, parsed.caption || '', data.action_taken);
    } else if (parsed.kind === 'booking') {
      appendStructuredMessage('booking', parsed.data, parsed.caption || '', data.action_taken);
    } else if (parsed.kind === 'bylaw') {
      appendStructuredMessage('bylaw', parsed.data, parsed.caption || '', data.action_taken);
    } else {
      appendMessageTypewriter('system', data.reply, data.action_taken);
    }
    playNotificationSound();
    updateConnection(true);

  } catch (err) {
    removeTyping(typingEl);
    appendMessage('system', `Error: ${err.message}\n\nMake sure the Chat API is running:\nuvicorn chat_api:app --reload --port 8080`);
    updateConnection(false);
  }
}

// ── Message Rendering ────────────────────────────────────────────────
function appendMessage(role, text, actionTaken, imageData) {
  const div = document.createElement('div');
  div.className = `msg msg-${role}`;

  const initials = role === 'user' ? cfgTwin.value.charAt(0).toUpperCase() : '';
  const avatarHTML = role === 'user'
    ? `<div class="msg-avatar user-avatar">${initials}</div>`
    : `<div class="msg-avatar system-avatar">
         <svg viewBox="0 0 32 32" fill="none"><circle cx="16" cy="16" r="14" stroke="url(#g1)" stroke-width="2"/><path d="M16 8v8l5.5 3" stroke="url(#g1)" stroke-width="2" stroke-linecap="round"/></svg>
       </div>`;

  const nameLabel = role === 'user' ? 'You' : 'ARIA';
  const time = timeNow();
  const contentHTML = role === 'system' ? parseMarkdown(text) : `<p>${escapeHtml(text)}</p>`;
  const actionTag = actionTaken ? `<span class="action-badge">\u26A1 ${actionTaken}</span>` : '';
  const imageTag = imageData ? `<img src="${imageData}" class="msg-image" alt="uploaded" />` : '';

  div.innerHTML = `
    ${avatarHTML}
    <div class="msg-body">
      <div class="msg-meta">
        <span class="msg-name">${nameLabel}</span>
        <span class="msg-time">${time}</span>
      </div>
      <div class="msg-content">${contentHTML}</div>
      ${imageTag}
      ${actionTag}
    </div>
  `;

  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;

  // Save to state
  state.messages.push({ role, text, actionTaken, time, image: imageData ? '(image)' : null });
  return div;
}

// ── Structured Card Renderers ────────────────────────────────────────
function appendRawHTML(role, innerHTML, actionTaken) {
  const div = document.createElement('div');
  div.className = `msg msg-${role}`;
  const time = timeNow();
  const actionTag = actionTaken ? `<span class="action-badge">⚡ ${actionTaken}</span>` : '';
  const avatarHTML = `<div class="msg-avatar system-avatar">
    <svg viewBox="0 0 32 32" fill="none"><circle cx="16" cy="16" r="14" stroke="url(#g1)" stroke-width="2"/><path d="M16 8v8l5.5 3" stroke="url(#g1)" stroke-width="2" stroke-linecap="round"/></svg>
  </div>`;
  div.innerHTML = `
    ${avatarHTML}
    <div class="msg-body">
      <div class="msg-meta">
        <span class="msg-name">ARIA</span>
        <span class="msg-time">${time}</span>
      </div>
      <div class="msg-content">${innerHTML}</div>
      ${actionTag}
    </div>
  `;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return div;
}

function bylawCardsHTML(data) {
  const results = (data && data.results) || [];
  const question = (data && data.question) || '';
  if (!results.length) {
    return `<p class="amenity-empty">No matching bylaw section found.</p>`;
  }
  const cards = results.map(r => `
    <div class="bylaw-card">
      <div class="bylaw-card-head">
        <span class="bylaw-section">§${escapeHtml(r.section || '')}</span>
        <h4 class="bylaw-title">${escapeHtml(r.title || '')}</h4>
      </div>
      <p class="bylaw-text">${escapeHtml(r.text || '')}</p>
      <div class="bylaw-citation">${escapeHtml(r.citation || '')}</div>
    </div>
  `).join('');
  const heading = question ? `<p class="bylaw-question"><strong>Q:</strong> ${escapeHtml(question)}</p>` : '';
  return `${heading}<div class="bylaw-grid">${cards}</div>`;
}

function appendStructuredMessage(kind, data, caption, actionTaken) {
  let body = '';
  if (kind === 'amenities') {
    const items = (data && data.items) || [];
    const captionHTML = caption ? `<p class="amenity-caption">${escapeHtml(caption)}</p>` : '';
    body = `${captionHTML}${amenityGridHTML(items)}`;
  } else if (kind === 'booking') {
    const captionHTML = caption ? `<p class="amenity-caption">${escapeHtml(caption)}</p>` : '';
    body = `${captionHTML}${bookingConfirmationHTML(data || {})}`;
  } else if (kind === 'bylaw') {
    const captionHTML = caption ? `<p class="amenity-caption">${escapeHtml(caption)}</p>` : '';
    body = `${captionHTML}${bylawCardsHTML(data || {})}`;
  } else {
    body = `<p>${escapeHtml(caption || '')}</p>`;
  }
  const div = appendRawHTML('system', body, actionTaken);
  // Attach handlers to amenity buttons inside this message.
  div.querySelectorAll('.amenity-card').forEach(card => {
    const id = card.dataset.amenityId || '';
    const name = card.dataset.amenityName || '';
    const bookBtn = card.querySelector('.amenity-btn-book');
    const infoBtn = card.querySelector('.amenity-btn-info');
    if (bookBtn) bookBtn.addEventListener('click', () => openSlotPicker(id, name));
    if (infoBtn) infoBtn.addEventListener('click', () => showAmenityDetails(id, name));
  });
  // Persist as a raw text record (state.messages stays as-is for export).
  let summaryText = '[Structured response]';
  if (kind === 'amenities') summaryText = `[Amenity list — ${(data && data.items || []).length} items]`;
  else if (kind === 'booking') summaryText = `[Booking confirmed]`;
  else if (kind === 'bylaw') summaryText = `[Bylaw lookup — ${(data && data.results || []).length} sections]`;
  state.messages.push({
    role: 'system',
    text: summaryText,
    actionTaken,
    time: timeNow(),
  });
  saveMessages();
}

// ── Typewriter Effect ────────────────────────────────────────────────
function appendMessageTypewriter(role, text, actionTaken) {
  const div = document.createElement('div');
  div.className = `msg msg-${role}`;

  const time = timeNow();
  const actionTag = actionTaken ? `<span class="action-badge">\u26A1 ${actionTaken}</span>` : '';

  div.innerHTML = `
    <div class="msg-avatar system-avatar">
      <svg viewBox="0 0 32 32" fill="none"><circle cx="16" cy="16" r="14" stroke="url(#g1)" stroke-width="2"/><path d="M16 8v8l5.5 3" stroke="url(#g1)" stroke-width="2" stroke-linecap="round"/></svg>
    </div>
    <div class="msg-body">
      <div class="msg-meta">
        <span class="msg-name">ARIA</span>
        <span class="msg-time">${time}</span>
      </div>
      <div class="msg-content"><span class="typewriter-target"></span><span class="typewriter-cursor"></span></div>
      ${actionTag}
    </div>
  `;

  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;

  const target = div.querySelector('.typewriter-target');
  const cursor = div.querySelector('.typewriter-cursor');
  const words = text.split(' ');
  let i = 0;

  function typeNext() {
    if (i < words.length) {
      target.textContent += (i > 0 ? ' ' : '') + words[i];
      i++;
      chatMessages.scrollTop = chatMessages.scrollHeight;
      setTimeout(typeNext, 30 + Math.random() * 30);
    } else {
      // Typing done — render full markdown
      cursor.remove();
      div.querySelector('.msg-content').innerHTML = parseMarkdown(text);
      if (actionTaken) {
        div.querySelector('.msg-content').insertAdjacentHTML('afterend', actionTag);
      }
      chatMessages.scrollTop = chatMessages.scrollHeight;
      saveMessages();
    }
  }

  typeNext();
  state.messages.push({ role, text, actionTaken, time });
}

// ── Typing Indicator ─────────────────────────────────────────────────
function showTyping() {
  const div = document.createElement('div');
  div.className = 'msg msg-system';
  div.id = 'typing-msg';
  div.innerHTML = `
    <div class="msg-avatar system-avatar">
      <svg viewBox="0 0 32 32" fill="none"><circle cx="16" cy="16" r="14" stroke="url(#g1)" stroke-width="2"/><path d="M16 8v8l5.5 3" stroke="url(#g1)" stroke-width="2" stroke-linecap="round"/></svg>
    </div>
    <div class="msg-body">
      <div class="msg-meta"><span class="msg-name">ARIA</span></div>
      <div class="typing-indicator"><span></span><span></span><span></span></div>
    </div>
  `;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return div;
}

function removeTyping(el) {
  if (el && el.parentNode) el.parentNode.removeChild(el);
}

// ── Connection Status ────────────────────────────────────────────────
function updateConnection(online) {
  connStatus.className = `conn-status ${online ? 'conn-online' : 'conn-offline'}`;
  connStatus.querySelector('.conn-text').textContent = online ? 'Connected' : 'Offline';
}

// ── Health Check ─────────────────────────────────────────────────────
btnHealth.addEventListener('click', async () => {
  const baseUrl = cfgUrl.value.replace(/\/+$/, '');
  connStatus.className = 'conn-status conn-checking';
  connStatus.querySelector('.conn-text').textContent = 'Checking...';
  try {
    const resp = await fetch(`${baseUrl}/health`, { signal: AbortSignal.timeout(5000) });
    if (resp.ok) { updateConnection(true); showToast('ARIA Chat API is healthy', 'success'); }
    else { updateConnection(false); showToast(`Health check failed: HTTP ${resp.status}`, 'error'); }
  } catch (err) {
    updateConnection(false);
    showToast(`Cannot reach API: ${err.message}`, 'error');
  }
});

// ── Clear Chat ───────────────────────────────────────────────────────
btnClear.addEventListener('click', () => {
  chatMessages.innerHTML = '';
  state.conversationId = '';
  state.messages = [];
  localStorage.removeItem('aria-messages');
  appendMessage('system', t('cleared'));
  showToast(t('clearChat'), 'info');
});

// ── Export Report ────────────────────────────────────────────────────
btnExport.addEventListener('click', () => {
  let report = `ARIA Chat Report\nExported: ${new Date().toLocaleString()}\nRole: ${state.role}\n\n`;
  report += '='.repeat(50) + '\n\n';
  state.messages.forEach(m => {
    report += `[${m.time}] ${m.role === 'user' ? 'You' : 'ARIA'}:\n${m.text}\n`;
    if (m.actionTaken) report += `  Action: ${m.actionTaken}\n`;
    report += '\n';
  });

  const blob = new Blob([report], { type: 'text/plain' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `aria-report-${Date.now()}.txt`;
  a.click();
  URL.revokeObjectURL(a.href);
  showToast('Report exported', 'success');
});

// ── Announcement Modal ───────────────────────────────────────────────
const announcementModal = $('#announcement-modal');
const announcementText = $('#announcement-text');
$('#modal-close')?.addEventListener('click', () => announcementModal.classList.add('hidden'));
$('#modal-cancel')?.addEventListener('click', () => announcementModal.classList.add('hidden'));
$('#modal-publish')?.addEventListener('click', () => {
  const text = announcementText.value.trim();
  if (text) {
    showToast('Announcement published!', 'success');
    announcementModal.classList.add('hidden');
  }
});

// ── localStorage Persistence ─────────────────────────────────────────
function saveMessages() {
  // Keep last 100 messages only
  const toSave = state.messages.slice(-100).map(m => ({ ...m, image: null }));
  localStorage.setItem('aria-messages', JSON.stringify(toSave));
}

function restoreMessages() {
  if (state.messages.length > 0) {
    chatMessages.innerHTML = '';
    state.messages.forEach(m => {
      const div = document.createElement('div');
      div.className = `msg msg-${m.role}`;
      const initials = m.role === 'user' ? cfgTwin.value.charAt(0).toUpperCase() : '';
      const avatarHTML = m.role === 'user'
        ? `<div class="msg-avatar user-avatar">${initials}</div>`
        : `<div class="msg-avatar system-avatar"><svg viewBox="0 0 32 32" fill="none"><circle cx="16" cy="16" r="14" stroke="url(#g1)" stroke-width="2"/><path d="M16 8v8l5.5 3" stroke="url(#g1)" stroke-width="2" stroke-linecap="round"/></svg></div>`;
      const nameLabel = m.role === 'user' ? 'You' : 'ARIA';
      const contentHTML = m.role === 'system' ? parseMarkdown(m.text) : `<p>${escapeHtml(m.text)}</p>`;
      const actionTag = m.actionTaken ? `<span class="action-badge">\u26A1 ${m.actionTaken}</span>` : '';
      div.innerHTML = `${avatarHTML}<div class="msg-body"><div class="msg-meta"><span class="msg-name">${nameLabel}</span><span class="msg-time">${m.time || ''}</span></div><div class="msg-content">${contentHTML}</div>${actionTag}</div>`;
      chatMessages.appendChild(div);
    });
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }
}

// ── Toast ────────────────────────────────────────────────────────────
let toastContainer = document.querySelector('.toast-container');
if (!toastContainer) {
  toastContainer = document.createElement('div');
  toastContainer.className = 'toast-container';
  document.body.appendChild(toastContainer);
}

function showToast(msg, type = 'info') {
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = msg;
  toastContainer.appendChild(toast);
  setTimeout(() => {
    toast.style.animation = 'toastOut .3s ease forwards';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

// ── Init ─────────────────────────────────────────────────────────────
applyTheme(state.theme);
applyI18n();
renderActions();
renderAdminPanels();

// Restore chat history from localStorage
if (state.messages.length > 0) {
  restoreMessages();
} else {
  // Show initial timestamp on greeting
  const greetingTime = chatMessages.querySelector('.msg-time');
  if (greetingTime) greetingTime.textContent = timeNow();
}

// Desktop: show all sections
if (window.innerWidth > 768) {
  $('#chat-section').style.display = 'flex';
  $('#quick-actions').style.display = 'block';
}
