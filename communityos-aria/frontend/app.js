/**
 * ARIA Dashboard — Complete Frontend Logic
 * Features: Markdown, Typewriter, Voice, Theme, i18n, localStorage,
 *           Admin panels, Escalation queue, Moderation, Export, File upload
 */

// ── State ─────────────────────────────────────────────────────────────
const state = {
  role: 'member',
  conversationId: '',
  lang: localStorage.getItem('aria-lang') || 'en',
  theme: localStorage.getItem('aria-theme') || 'dark',
  messages: JSON.parse(localStorage.getItem('aria-messages') || '[]'),
  pendingImage: null,
  isRecording: false,
};

// ── i18n ──────────────────────────────────────────────────────────────
const I18N = {
  en: {
    theme: 'Theme', language: 'Language', mode: 'Mode', member: 'Member', admin: 'Admin',
    configuration: 'Configuration', checkHealth: 'Check Health', clearChat: 'Clear Chat',
    exportReport: 'Export Report', quickActions: 'Quick Actions', societyInsights: 'Society Insights',
    totalTickets: 'Total Tickets', pendingEscalations: 'Pending Escalations',
    avgResponseTime: 'Avg Response Time', activeResidents: 'Active Residents',
    ticketsThisWeek: 'Tickets This Week', escalationQueue: 'Escalation Queue',
    selectAll: 'Select All', bulkApprove: 'Bulk Approve', bulkDeny: 'Bulk Deny',
    contentModeration: 'Content Moderation', editAnnouncement: 'Edit Announcement',
    cancel: 'Cancel', publish: 'Publish', chat: 'Chat', actions: 'Actions', settings: 'Settings',
    askAria: 'Ask ARIA anything...', greeting: "Hi! I'm ARIA, your society assistant. Send me a message or click a quick action above to get started.",
    cleared: 'Chat cleared. Send me a message or click a quick action to begin.',
  },
  hi: {
    theme: 'थीम', language: 'भाषा', mode: 'मोड', member: 'सदस्य', admin: 'एडमिन',
    configuration: 'कॉन्फ़िगरेशन', checkHealth: 'स्वास्थ्य जांच', clearChat: 'चैट साफ करें',
    exportReport: 'रिपोर्ट डाउनलोड', quickActions: 'त्वरित कार्य', societyInsights: 'सोसायटी इनसाइट्स',
    totalTickets: 'कुल टिकट', pendingEscalations: 'लंबित एस्केलेशन',
    avgResponseTime: 'औसत प्रतिक्रिया समय', activeResidents: 'सक्रिय निवासी',
    ticketsThisWeek: 'इस हफ्ते के टिकट', escalationQueue: 'एस्केलेशन कतार',
    selectAll: 'सभी चुनें', bulkApprove: 'सभी स्वीकृत', bulkDeny: 'सभी अस्वीकृत',
    contentModeration: 'कंटेंट मॉडरेशन', editAnnouncement: 'घोषणा संपादित करें',
    cancel: 'रद्द', publish: 'प्रकाशित करें', chat: 'चैट', actions: 'कार्य', settings: 'सेटिंग्स',
    askAria: 'ARIA से कुछ भी पूछें...', greeting: 'नमस्ते! मैं ARIA हूं, आपकी सोसायटी सहायक। कोई संदेश भेजें या ऊपर कोई एक्शन चुनें।',
    cleared: 'चैट साफ हो गई। कोई संदेश भेजें या एक्शन चुनें।',
  },
};

function t(key) { return I18N[state.lang]?.[key] || I18N.en[key] || key; }

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
const langToggle     = $('#lang-toggle');
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
  { id: 'book-gym',     icon: '\u{1F3CB}', iconClass: 'icon-blue',   title: 'Book Gym',       desc: 'Reserve a gym slot',         message: 'Book gym at 7pm' },
  { id: 'book-pool',    icon: '\u{1F3CA}', iconClass: 'icon-cyan',   title: 'Book Pool',      desc: 'Reserve pool time',          message: 'Book pool for tomorrow 6am' },
  { id: 'book-club',    icon: '\u{1F3E0}', iconClass: 'icon-purple', title: 'Book Clubhouse', desc: 'Reserve the clubhouse',      message: 'I want to book the clubhouse for Saturday evening' },
  { id: 'raise-ticket', icon: '\u{1F527}', iconClass: 'icon-red',    title: 'Raise Ticket',   desc: 'Report maintenance issue',   message: 'AC not working in my flat' },
  { id: 'urgent-ticket',icon: '\u{1F6A8}', iconClass: 'icon-orange', title: 'Urgent Issue',   desc: 'Report an emergency',        message: 'There is a water leakage flooding in my bathroom, urgent!' },
  { id: 'check-events', icon: '\u{1F389}', iconClass: 'icon-pink',   title: 'Events Today',   desc: "What's happening?",          message: 'What events are happening today?' },
  { id: 'check-dues',   icon: '\u{1F4B0}', iconClass: 'icon-yellow', title: 'Check Dues',     desc: 'View pending payments',      message: 'Do I have any pending dues?' },
  { id: 'pay-rent',     icon: '\u{1F4B3}', iconClass: 'icon-green',  title: 'Pay Rent',       desc: 'Initiate rent payment',      message: 'Pay my rent of \u20B915000' },
  { id: 'notices',      icon: '\u{1F4E2}', iconClass: 'icon-purple', title: 'Notices',        desc: 'Latest announcements',       message: 'Any new notices from the society?' },
  { id: 'rsvp',         icon: '\u{270B}',  iconClass: 'icon-cyan',   title: 'RSVP Event',     desc: 'Join an upcoming event',     message: 'Sign me up for the Holi party' },
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
  { id: 'ESC-001', title: 'Pool maintenance budget approval', desc: 'Contractor requesting \u20B945,000 for pump replacement', sla: '2h 15m', slaClass: 'sla-ok' },
  { id: 'ESC-002', title: 'Parking slot reassignment B-Wing', desc: 'Resident B-404 requesting swap with B-201', sla: '45m', slaClass: 'sla-warn' },
  { id: 'ESC-003', title: 'Security camera installation', desc: 'New cameras for basement level 2 — vendor quote pending', sla: '15m', slaClass: 'sla-critical' },
  { id: 'ESC-004', title: 'Society event budget — Holi', desc: 'Committee requesting \u20B91,20,000 for Holi celebration', sla: '5h 30m', slaClass: 'sla-ok' },
];

// ── Moderation Data (simulated) ──────────────────────────────────────
const MODERATION_DATA = [
  { user: 'Resident A-203', content: '"The security guard is sleeping during night shift again!"', severity: 'medium', reason: 'Accusation without evidence' },
  { user: 'Resident C-101', content: '"This society management is completely corrupt"', severity: 'high', reason: 'Defamatory language against committee' },
  { user: 'Resident B-505', content: '"Don\'t park in my spot or face consequences"', severity: 'low', reason: 'Mildly threatening tone' },
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
$$('.role-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    $$('.role-btn').forEach((b) => b.classList.remove('active'));
    btn.classList.add('active');
    state.role = btn.dataset.role;
    roleBadge.textContent = state.role === 'admin' ? t('admin') : t('member');
    roleBadge.className = `role-badge ${state.role === 'admin' ? 'role-admin' : 'role-member'}`;
    renderActions();
    renderAdminPanels();
    showToast(`Switched to ${state.role} mode`, 'info');
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

// ── Language Toggle ──────────────────────────────────────────────────
function applyLang(lang) {
  state.lang = lang;
  localStorage.setItem('aria-lang', lang);
  langToggle.textContent = lang === 'en' ? 'EN' : 'HI';
  applyI18n();
}

langToggle.addEventListener('click', () => {
  applyLang(state.lang === 'en' ? 'hi' : 'en');
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
        <div class="toggle-card"><span class="toggle-label">${t('language')}</span>
          <button class="lang-btn" id="m-lang">${state.lang === 'en' ? 'EN' : 'HI'}</button>
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
  const mLang = body.querySelector('#m-lang');
  if (mTheme) mTheme.addEventListener('click', () => { applyTheme(state.theme === 'dark' ? 'light' : 'dark'); populateMobileSettings(); });
  if (mLang) mLang.addEventListener('click', () => { applyLang(state.lang === 'en' ? 'hi' : 'en'); populateMobileSettings(); });
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
    const langHint = state.lang === 'hi' ? ' (Reply in Hindi/Hinglish)' : '';
    const resp = await fetch(`${baseUrl}/aria/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        twin_id: cfgTwin.value,
        org_id: cfgOrg.value,
        user_api_key: cfgKey.value,
        role: state.role,
        message: text + langHint,
        conversation_id: state.conversationId,
      }),
    });

    removeTyping(typingEl);

    if (!resp.ok) {
      const errData = await resp.json().catch(() => ({}));
      throw new Error(errData.detail || `HTTP ${resp.status}`);
    }

    const data = await resp.json();
    state.conversationId = data.conversation_id || state.conversationId;

    // Typewriter effect for ARIA reply
    appendMessageTypewriter('system', data.reply, data.action_taken);
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
applyLang(state.lang);
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
