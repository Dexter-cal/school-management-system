
const API = { 
    csrfToken: null, 
    _offlineQueueKey: 'bjs_offline_queue_v1', 
    _loadOfflineQueue() { 
        try { 
            const raw = localStorage.getItem(this._offlineQueueKey); 
            const arr = raw ? JSON.parse(raw) : []; 
            return Array.isArray(arr) ? arr : []; 
        } catch { 
            return []; 
        } 
    }, 
    _saveOfflineQueue(arr) { 
        try { localStorage.setItem(this._offlineQueueKey, JSON.stringify(arr || [])); } catch {} 
    }, 
    _enqueueOffline(item) { 
        const q = this._loadOfflineQueue(); 
        q.push(item); 
        // Cap queue to avoid unbounded growth. 
        while (q.length > 50) q.shift(); 
        this._saveOfflineQueue(q); 
        try { 
            const el = document.getElementById('offline-badge'); 
            if (el) el.textContent = String(q.length); 
        } catch {} 
    }, 
    async flushOfflineQueue() { 
        const q = this._loadOfflineQueue(); 
        if (!q.length) return; 
        if (!navigator.onLine) return; 
 
        const next = []; 
        for (const it of q) { 
            try { 
                const method = String(it.method || 'POST').toUpperCase(); 
                const headers = { ...(it.headers || {}) }; 
                if (!['GET','HEAD','OPTIONS','TRACE'].includes(method)) { 
                    const csrf = await this.getCsrfToken(); 
                    if (csrf) headers['X-CSRFToken'] = csrf; 
                } 
                const r = await fetch('/api' + it.url, { 
                    method, 
                    credentials: 'same-origin', 
                    headers, 
                    body: it.body || undefined, 
                }); 
                if (!r.ok) throw new Error('HTTP ' + r.status); 
            } catch { 
                next.push(it); 
            } 
        } 
        this._saveOfflineQueue(next); 
        try { 
            const el = document.getElementById('offline-badge'); 
            if (el) el.textContent = String(next.length); 
        } catch {} 
    }, 
    async refreshCsrfToken() { 
        // Ask the backend for a fresh token + cookie pair. 
        const r = await fetch('/api/auth/csrf/', { method: 'GET', credentials: 'same-origin' }); 
        if (!r.ok) return null; 
        const data = await r.json().catch(() => ({})); 
        const token = (data && data.csrfToken) ? String(data.csrfToken).trim() : '';
        if (token) {
            this.csrfToken = token;
            const meta = document.querySelector('meta[name="csrf-token"]');
            if (meta) meta.setAttribute('content', token);
        }
        return this.csrfToken;
    },
    async getCsrfToken() {
        if (this.csrfToken) return this.csrfToken;

        // CSRF token source priority:
        // 1. Fresh /api/auth/csrf/ token
        // 2. Hidden {% csrf_token %} input (works even when CSRF cookie is HttpOnly)
        // 3. Meta tag
        // 4. Cookie (dev fallback when CSRF cookie isn't HttpOnly)
        const hidden = document.querySelector('#csrf-form input[name="csrfmiddlewaretoken"]');
        const hiddenToken = hidden ? (hidden.value || '').trim() : '';
        const meta = document.querySelector('meta[name="csrf-token"]');
        const metaToken = meta ? (meta.getAttribute('content') || '').trim() : '';
        const token = (hiddenToken && hiddenToken !== 'NOTPROVIDED')
            ? hiddenToken
            : ((metaToken && metaToken !== 'NOTPROVIDED') ? metaToken : (this.getCookie('csrftoken') || ''));
        if (token) {
            this.csrfToken = token;
            return token;
        }

        // Last resort: fetch a new token from backend.
        await this.refreshCsrfToken();
        return this.csrfToken;
    },
    async fetch(url, options = {}, _retried = false) { 
        const method = String(options.method || 'GET').toUpperCase(); 
        const isSafe = ['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes(method); 
        const headers = { ...(options.headers || {}) }; 
        // Only force JSON content-type when the body is plain data. 
        // For FormData (uploads), the browser must set the multipart boundary.
        const isFormData = (typeof FormData !== 'undefined') && (options.body instanceof FormData);
        if (!isFormData && !headers['Content-Type'] && !headers['content-type']) headers['Content-Type'] = 'application/json';

        if (!isSafe) {
            const csrf = await this.getCsrfToken();
            if (csrf) headers['X-CSRFToken'] = csrf;
        }

        let response; 
        try { 
            response = await fetch('/api' + url, { 
                ...options, 
                credentials: 'same-origin', 
                headers, 
            }); 
        } catch (err) { 
            // Network failure: queue non-upload write requests for retry. 
            if (!isSafe && !isFormData) { 
                this._enqueueOffline({ 
                    url, 
                    method, 
                    headers: { 'Content-Type': headers['Content-Type'] || headers['content-type'] || 'application/json' }, 
                    body: (typeof options.body === 'string' ? options.body : (options.body ? JSON.stringify(options.body) : null)), 
                    ts: Date.now(), 
                }); 
                throw { detail: 'Network issue: action saved and will retry when online.' }; 
            } 
            throw { detail: 'Network error. Please try again.' }; 
        } 
 
        // If CSRF token/cookie got out of sync (common when switching localhost/127.0.0.1), 
        // refresh token once and retry the request. 
        if (response.status === 403 && !_retried && !isSafe) {
            const text = await response.clone().text().catch(() => '');
            const looksLikeCsrf = (text || '').toLowerCase().includes('csrf');
            // Only retry when it looks like CSRF. Permission-denied 403 should not loop.
            if (looksLikeCsrf) {
                this.csrfToken = null;
                await this.refreshCsrfToken();
                return this.fetch(url, options, true);
            }
        }

        // Always read the response body exactly once.
        // If you call response.text() and later response.json() (or vice versa), the browser will throw:
        // "Failed to execute 'text' on 'Response': body stream already read".
        const raw = await response.text().catch(() => '');
        let data = null;
        if (raw) {
            try { data = JSON.parse(raw); } catch { data = raw; }
        }

        if (!response.ok) {
            const payload = (data && typeof data === 'object')
                ? data
                : { detail: String(data || raw || '') };
            payload.status = response.status;
            throw payload;
        }
        if (response.status === 204) return null;
        return data;
    },
    getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
};

let currentUser = null;
let EV_SHOW_PAST = false;
let AN_SHOW_ARCHIVED = false;
let AN_SHOW_EXPIRED = false;
let CH_FILTER = { class_id: '', year: '', term: '', active: '1', published: '1' };
let FIN_FILTER = { year: '', term: '' };
let DELIVERY_FILTER = { channel: '', status: '', campaign: '', student: '', class_id: '', q: '' };
let APPR_FILTER = { status: 'pending', method: 'bank', q: '' };
let APPR_SELECTED = new Set();
const SCHOOL_TIME_ZONE = 'Africa/Nairobi';
let CASHBOOK_FILTER = { close_date: todayISO(), cashier: '', opening_cash: '0', counted_cash_on_hand: '0' };
let PLAN_FILTER = { year: '', term: '', status: '' };
let PROMISE_FILTER = { year: '', term: '', status: '' };
let GRADING_ROWS = [];
let ACTIVE_NOTIF_CATEGORY = 'all';
let NOTIF_FILTER_TIMER = null;
let PARENT_MATCH_TIMER = null;
let ACTIVE_PARENT_CANDIDATES = [];
let TUTORIAL_STATE = { role: '', index: 0, steps: [] };
let COMMUNICATION_EDITOR_BOOT = null;
const COMMUNICATION_PLACEHOLDERS = [
    '{recipient_name}', '{recipient_email}', '{recipient_phone}', '{student_name}', '{student_id}',
    '{class_label}', '{class_level}', '{section}', '{parent_name}', '{parent_email}', '{parent_phone}',
    '{today}', '{academic_year}', '{term_number}', '{login_url}', '{school_name}',
];
const COMMUNICATION_LIBRARY_SCOPES = [
    { value: 'all', label: 'Whole school' },
    { value: 'admin', label: 'Admin only' },
    { value: 'teacher', label: 'Teacher library' },
    { value: 'bursar', label: 'Bursar library' },
    { value: 'reception', label: 'Reception library' },
];
const COMMUNICATION_HEADER_PRESETS = [
    { value: 'standard', label: 'Standard school header' },
    { value: 'finance', label: 'Finance header' },
    { value: 'academic', label: 'Academic header' },
    { value: 'minimal', label: 'Minimal header' },
];
const COMMUNICATION_FOOTER_PRESETS = [
    { value: 'standard', label: 'Standard footer' },
    { value: 'finance', label: 'Finance footer' },
    { value: 'academic', label: 'Academic footer' },
    { value: 'minimal', label: 'Minimal footer' },
];
const FIRST_LOGIN_TUTORIALS = {
    admin: [
        { title: 'Start from the dashboard', body: 'Use the dashboard to see today’s term, quick alerts, and shortcuts into registration, finance, and communications.', actionLabel: 'Open Dashboard', page: 'dashboard', label: 'See school status first' },
        { title: 'Register students cleanly', body: 'When adding a student, the system can match an existing parent account, issue portal credentials, and prepare printable handover sheets.', actionLabel: 'Open Students', page: 'students', label: 'Admissions and parent linking' },
        { title: 'Work from the communication library', body: 'Templates, drafts, announcements, and mail-merge letters now flow through the Communications Studio so messages stay consistent.', actionLabel: 'Open Communications', page: 'communications', label: 'Templates and campaigns' },
        { title: 'Review your notifications', body: 'Finance, academic, events, security, and system alerts can be tuned in Settings and filtered in the notification drawer.', actionLabel: 'Open Settings', page: 'settings', label: 'Control alerts and account security' },
    ],
    bursar: [
        { title: 'Use finance as a workflow', body: 'Payments, approvals, cashbook, deposits, promises, and installments are split into focused pages so the close-of-day flow is easier to follow.', actionLabel: 'Open Payments', page: 'finance', label: 'Collections workspace' },
        { title: 'Track delivery and reminders', body: 'Fee reminders and scheduled finance communications can now be reviewed from Delivery Logs with resend and retry controls.', actionLabel: 'Open Delivery Logs', page: 'delivery_logs', label: 'Communication visibility' },
        { title: 'Close the day carefully', body: 'Cashbook close, cashier handover, pending deposits, and unresolved promises should be reviewed before end of day.', actionLabel: 'Open Cashbook', page: 'cashbook', label: 'Daily reconciliation' },
    ],
    teacher: [
        { title: 'My Class is your main workspace', body: 'Attendance, marks, class performance, and student history are grouped together so you can manage one class at a time.', actionLabel: 'Open My Class', page: 'my_class', label: 'Teaching workflow' },
        { title: 'Use Communications for letters and parent notices', body: 'Start with a template, then edit in the full document workspace before sending or printing.', actionLabel: 'Open Communications', page: 'communications', label: 'Notices and mail merge' },
        { title: 'Mark your own attendance', body: 'Reception can generate the QR, and you can also review your last 30 days in the Teacher Attendance page.', actionLabel: 'Open My Attendance', page: 'teacher_attendance', label: 'Staff attendance' },
    ],
    reception: [
        { title: 'Student support starts here', body: 'Reception can register students, print credentials, manage teacher attendance records, and keep admission documents moving.', actionLabel: 'Open Students', page: 'students', label: 'Front desk operations' },
        { title: 'Print Queue and Print Desk work together', body: 'Queued credentials, admission letters, report cards, and exam documents can be reviewed before printing.', actionLabel: 'Open Print Queue', page: 'printqueue', label: 'Document handling' },
        { title: 'Use Communications for reusable letters', body: 'Templates with the school logo, merge fields, and approval workflow live in one place and can be reused by role.', actionLabel: 'Open Communications', page: 'communications', label: 'Reusable office templates' },
    ],
};
const COMMUNICATION_DEFAULT_TEMPLATE = [
    '<p><strong>Date:</strong> {today}</p>',
    '<p>Dear {recipient_name},</p>',
    '<p>This message confirms details for <strong>{student_name}</strong> in <strong>{class_label}</strong>.</p>',
    '<p>Please verify the contacts below are correct:</p>',
    '<ul>',
    '<li>Parent email: {parent_email}</li>',
    '<li>Parent phone: {parent_phone}</li>',
    '<li>Student ID: {student_id}</li>',
    '</ul>',
    '<p>Regards,<br><strong>{school_name}</strong></p>',
].join('');
const COMMUNICATION_STARTER_TEMPLATES = [
    {
        key: 'welcome-parent-email',
        label: 'Parent Welcome',
        summary: 'Account creation email for a new parent or guardian.',
        kind: 'message',
        library_scope: 'admin',
        header_preset: 'standard',
        footer_preset: 'academic',
        include_signature_block: true,
        include_school_stamp: false,
        title: 'Welcome to {school_name}, {recipient_name}',
        body: [
            '<p><strong>Date:</strong> {today}</p>',
            '<p>Dear {recipient_name},</p>',
            '<p>Welcome to <strong>{school_name}</strong>. Your portal for <strong>{student_name}</strong> is now ready.</p>',
            '<p><strong>Login details</strong></p>',
            '<table><tbody>',
            '<tr><th>Username</th><td>{recipient_phone}</td></tr>',
            '<tr><th>Recovery email</th><td>{recipient_email}</td></tr>',
            '<tr><th>Portal link</th><td>{login_url}</td></tr>',
            '</tbody></table>',
            '<p>Please sign in and change the temporary password after your first login.</p>',
            '<p>Regards,<br><strong>{school_name}</strong></p>',
        ].join(''),
    },
    {
        key: 'student-account-sms',
        label: 'Account SMS',
        summary: 'Short SMS template for new student or parent account activation.',
        kind: 'message',
        library_scope: 'admin',
        header_preset: 'minimal',
        footer_preset: 'minimal',
        include_signature_block: false,
        include_school_stamp: false,
        title: 'Portal access for {student_name}',
        body: '<p>{school_name}: {student_name} portal is ready. Username: {recipient_phone}. Login: {login_url}. Reset and help contacts stay active on this number.</p>',
    },
    {
        key: 'fee-defaulter-reminder',
        label: 'Fee Defaulter',
        summary: 'Bursar reminder for unpaid balances with class and student details.',
        kind: 'notice',
        library_scope: 'bursar',
        header_preset: 'finance',
        footer_preset: 'finance',
        include_signature_block: true,
        include_school_stamp: true,
        title: 'Fee reminder for {student_name}',
        body: [
            '<p><strong>Date:</strong> {today}</p>',
            '<p>Dear {recipient_name},</p>',
            '<p>This is a friendly reminder that school fees for <strong>{student_name}</strong> in <strong>{class_label}</strong> still require attention.</p>',
            '<p>Please contact the bursar office to confirm your installment plan, payment promise, or bank/mobile money reference.</p>',
            '<p>Thank you for supporting steady learning progress.</p>',
        ].join(''),
    },
    {
        key: 'installment-follow-up',
        label: 'Installment Follow-up',
        summary: 'Follow-up note for parents with a pending promise or installment plan.',
        kind: 'letter',
        library_scope: 'bursar',
        header_preset: 'finance',
        footer_preset: 'standard',
        include_signature_block: true,
        include_school_stamp: false,
        title: 'Installment follow-up for {student_name}',
        body: [
            '<p>Dear {recipient_name},</p>',
            '<p>We are following up on the payment arrangement for <strong>{student_name}</strong>. Please confirm the next payment date and amount with the bursar office.</p>',
            '<p>If you have already paid, reply with the reference so we can update the account quickly.</p>',
        ].join(''),
    },
    {
        key: 'event-notice',
        label: 'Event Notice',
        summary: 'Starter template that can also be turned into an Event entry.',
        kind: 'notice',
        library_scope: 'reception',
        header_preset: 'academic',
        footer_preset: 'academic',
        include_signature_block: true,
        include_school_stamp: false,
        title: 'School notice for {class_label}',
        body: [
            '<p><strong>Date:</strong> {today}</p>',
            '<p>Dear {recipient_name},</p>',
            '<p>This notice is to share an upcoming school activity for <strong>{student_name}</strong> in <strong>{class_label}</strong>.</p>',
            '<p>Please read the schedule carefully and reach out if anything needs clarification.</p>',
        ].join(''),
    },
];
try { window.ACTIVE_NOTIF_CATEGORY = ACTIVE_NOTIF_CATEGORY; } catch {}

function currentRoleName() {
    return (currentUser && currentUser.profile && currentUser.profile.role) || 'admin';
}

function communicationCanApprove(role = currentRoleName()) {
    return ['superadmin', 'admin', 'headteacher', 'deputy', 'dos'].includes(String(role || '').toLowerCase());
}

function communicationDefaultLibraryScope(role = currentRoleName()) {
    const norm = String(role || '').toLowerCase();
    if (norm === 'teacher') return 'teacher';
    if (norm === 'bursar') return 'bursar';
    if (norm === 'reception') return 'reception';
    return 'all';
}

function communicationAllowedLibraryScopes(role = currentRoleName()) {
    const norm = String(role || '').toLowerCase();
    if (communicationCanApprove(norm)) return COMMUNICATION_LIBRARY_SCOPES;
    if (norm === 'teacher') return COMMUNICATION_LIBRARY_SCOPES.filter(x => ['teacher', 'all'].includes(x.value));
    if (norm === 'bursar') return COMMUNICATION_LIBRARY_SCOPES.filter(x => ['bursar', 'all'].includes(x.value));
    if (norm === 'reception') return COMMUNICATION_LIBRARY_SCOPES.filter(x => ['reception', 'admin', 'all'].includes(x.value));
    return COMMUNICATION_LIBRARY_SCOPES.filter(x => x.value === 'all');
}

function communicationWorkflowPill(status) {
    const s = String(status || 'draft').toLowerCase();
    const cls = s === 'published' ? 'published' : s === 'approved' ? 'approved' : s === 'submitted' ? 'approved' : s === 'printed' ? 'approved' : 'draft';
    return `<span class="comms-pill ${cls}">${escapeHtml(s)}</span>`;
}

function communicationScopePill(scope) {
    const s = String(scope || 'all').toLowerCase();
    return `<span class="comms-pill scope">${escapeHtml(s.replace('_', ' '))}</span>`;
}

function communicationCampaignPill(status) {
    const s = String(status || 'scheduled').toLowerCase();
    const cls = s === 'completed' ? 'published' : s === 'partially_failed' ? 'approved' : s === 'failed' ? 'draft' : s === 'cancelled' ? 'scope' : 'approved';
    return `<span class="comms-pill ${cls}">${escapeHtml(s.replace('_', ' '))}</span>`;
}

function communicationLibraryOptionsHtml(role = currentRoleName(), selected = '') {
    return communicationAllowedLibraryScopes(role).map(opt => `<option value="${opt.value}" ${String(selected) === opt.value ? 'selected' : ''}>${escapeHtml(opt.label)}</option>`).join('');
}

// Lightweight sidebar diagnostic helper.
window.debugSidebar = function() {
    const role = String((currentUser && currentUser.profile && currentUser.profile.role) || 'superadmin').trim().toLowerCase();
    const nav = document.getElementById('sb-nav-content');
    const sidebar = document.getElementById('sidebar');
    return {
        role,
        navItems: (NAV && NAV[role]) ? NAV[role].length : 0,
        renderedLinks: nav ? nav.querySelectorAll('.sb-link').length : 0,
        sidebarDisplay: sidebar ? window.getComputedStyle(sidebar).display : null,
        sidebarCollapsed: sidebar ? sidebar.classList.contains('collapsed') : false,
    };
};

function apprToggleAll(checked) {
    document.querySelectorAll('.appr-cb').forEach(cb => { cb.checked = !!checked; });
    APPR_SELECTED = new Set();
    if (checked) {
        document.querySelectorAll('.appr-cb').forEach(cb => {
            const id = Number(cb.getAttribute('data-id'));
            if (id) APPR_SELECTED.add(id);
        });
    }
    apprUpdateSelectionMeta();
}

function apprToggleOne(id, checked) {
    id = Number(id);
    if (!id) return;
    if (checked) APPR_SELECTED.add(id);
    else APPR_SELECTED.delete(id);
    apprUpdateSelectionMeta();
}

function apprClearSelection() {
    APPR_SELECTED = new Set();
    document.querySelectorAll('.appr-cb').forEach(cb => { cb.checked = false; });
    const all = document.getElementById('appr-all');
    if (all) all.checked = false;
    apprUpdateSelectionMeta();
}

function apprUpdateSelectionMeta() {
    const el = document.getElementById('appr-selmeta');
    if (el) el.textContent = `Selected: ${APPR_SELECTED.size}`;
}

function groupedStudentOptions(students) {
    const groups = (students || []).reduce((acc, s) => {
        const key = `${s.current_class_level || 'Unassigned'}${s.section || ''}`;
        if (!acc[key]) acc[key] = [];
        acc[key].push(s);
        return acc;
    }, {});
    return Object.keys(groups).sort().map(g => {
        const opts = (groups[g] || []).map(s => `<option value="${s.id}">${escapeHtml(s.first_name || '')} ${escapeHtml(s.last_name || '')} (${escapeHtml(s.student_id || '')})</option>`).join('');
        return `<optgroup label="Class ${escapeHtml(g)}">${opts}</optgroup>`;
    }).join('');
}

function statusBadgeClass(status) {
    const s = String(status || '').toLowerCase();
    if (['paid', 'approved', 'received', 'completed', 'kept', 'sent', 'closed'].includes(s)) return 'green';
    if (['partial', 'pending', 'open', 'active'].includes(s)) return '';
    if (['overdue', 'rejected', 'missed', 'defaulted'].includes(s)) return 'red';
    if (['cancelled', 'reversed', 'released'].includes(s)) return 'blue';
    return '';
}

function financeHintCard(title, body, actionsHtml = '') {
    return `
      <div class="card" style="border-left:4px solid var(--bl)">
        <div class="card-body">
          <div style="font-weight:800;color:var(--md)">${title}</div>
          <div class="sub" style="margin-top:4px">${body}</div>
          ${actionsHtml ? `<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px">${actionsHtml}</div>` : ''}
        </div>
      </div>`;
}

function listDataRows(payload) {
    if (Array.isArray(payload)) return payload;
    if (payload && Array.isArray(payload.results)) return payload.results;
    if (payload && Array.isArray(payload.items)) return payload.items;
    return [];
}

function isPastIsoDate(value) {
    const v = String(value || '').trim();
    return !!v && v < todayISO();
}

function openBulkReviewModal() {
    const el = document.getElementById('bulk-meta');
    if (el) el.textContent = `Selected: ${APPR_SELECTED.size}`;
    document.getElementById('bulk-action').value = 'approve';
    document.getElementById('bulk-reason').value = '';
    document.getElementById('bulk-notes').value = '';
    openModal('modal-bulk-approval');
}

async function applyBulkReview() {
    if (!APPR_SELECTED || APPR_SELECTED.size === 0) { flash('Select at least one payment.'); return; }
    const action = (document.getElementById('bulk-action')?.value || '').trim();
    const reason = (document.getElementById('bulk-reason')?.value || '').trim();
    const review_notes = (document.getElementById('bulk-notes')?.value || '').trim();
    try {
        const ids = Array.from(APPR_SELECTED.values());
        const res = await API.fetch('/payments/bulk-review/', { method: 'POST', body: JSON.stringify({ ids, action, reason, review_notes }) });
        closeModal('modal-bulk-approval');
        flash(`Bulk ${action}: updated ${res.updated}, skipped ${res.skipped}.`);
        apprClearSelection();
        loadPage('approvals', null, 'Approvals');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Bulk review failed.');
    }
}
let CURRENT_PAGE = 'dashboard';
let ACTIVE_TERM_CACHE = null;
let ACTIVE_TERM_CACHE_AT = 0;

function currentYear() { return new Date().getFullYear(); }
function pad2(n) { return String(n).padStart(2, '0'); }
function schoolDateParts(value = new Date()) {
    const d = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(d.getTime())) return null;
    const parts = new Intl.DateTimeFormat('en-CA', {
        timeZone: SCHOOL_TIME_ZONE,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
    }).formatToParts(d);
    const pick = type => (parts.find(p => p.type === type) || {}).value || '';
    return { year: pick('year'), month: pick('month'), day: pick('day') };
}
function dateToISO(value = new Date()) {
    const parts = schoolDateParts(value);
    return parts ? `${parts.year}-${parts.month}-${parts.day}` : '';
}
function todayISO() {
    return dateToISO(new Date());
}
function addDaysISO(days) {
    const anchor = new Date(`${todayISO()}T12:00:00Z`);
    anchor.setUTCDate(anchor.getUTCDate() + Number(days || 0));
    return dateToISO(anchor);
}
function formatDateTime(value, fallback = '') {
    if (!value) return fallback;
    const d = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(d.getTime())) return fallback;
    return new Intl.DateTimeFormat('en-UG', {
        timeZone: SCHOOL_TIME_ZONE,
        year: 'numeric',
        month: 'short',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: true,
    }).format(d);
}
function dateFromISO(value) {
    if (!value) return null;
    const d = new Date(`${value}T12:00:00Z`);
    return Number.isNaN(d.getTime()) ? null : d;
}
function formatSchoolDate(value, fallback = '', options = {}) {
    if (!value) return fallback;
    const d = value instanceof Date ? value : (/^\d{4}-\d{2}-\d{2}$/.test(String(value)) ? dateFromISO(String(value)) : new Date(value));
    if (!d || Number.isNaN(d.getTime())) return fallback;
    return new Intl.DateTimeFormat('en-UG', {
        timeZone: SCHOOL_TIME_ZONE,
        weekday: options.weekday || undefined,
        year: options.year || 'numeric',
        month: options.month || 'short',
        day: options.day || '2-digit',
        hour: options.hour,
        minute: options.minute,
        hour12: options.hour12,
    }).format(d);
}
function formatSchoolNow() {
    return formatSchoolDate(new Date(), '', {
        weekday: 'long',
        month: 'long',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: true,
    });
}
function daysUntilISO(value) {
    const d = dateFromISO(value);
    const today = dateFromISO(todayISO());
    if (!d || !today) return null;
    return Math.round((d.getTime() - today.getTime()) / 86400000);
}
function computeTermWeek(term) {
    if (!term || !term.start_date) return null;
    const start = dateFromISO(term.start_date);
    const today = dateFromISO(todayISO());
    if (!start || !today) return null;
    const diffDays = Math.floor((today.getTime() - start.getTime()) / 86400000);
    if (diffDays < 0) return 0;
    return Math.floor(diffDays / 7) + 1;
}
function buildUpcomingDeadlineRows(activeTerm, events = [], extraDeadlines = []) {
    const items = [];
    if (activeTerm && activeTerm.end_date) {
        const days = daysUntilISO(activeTerm.end_date);
        items.push({
            title: `Term ${activeTerm.term_number} closes`,
            date: activeTerm.end_date,
            meta: `${activeTerm.academic_year}${days == null ? '' : days === 0 ? ' · today' : days > 0 ? ` · in ${days} day${days === 1 ? '' : 's'}` : ` · ${Math.abs(days)} day${Math.abs(days) === 1 ? '' : 's'} ago`}`,
        });
    }
    (events || []).filter(ev => ev && ev.start_date).forEach(ev => {
        const days = daysUntilISO(ev.start_date);
        if (days != null && days < 0) return;
        items.push({
            title: ev.title || 'School event',
            date: ev.start_date,
            meta: ev.end_date && ev.end_date !== ev.start_date
                ? `${formatSchoolDate(ev.start_date)} to ${formatSchoolDate(ev.end_date)}`
                : formatSchoolDate(ev.start_date),
        });
    });
    (extraDeadlines || []).forEach(item => {
        if (!item || !item.date) return;
        items.push(item);
    });
    return items
        .filter(item => item && item.date)
        .sort((a, b) => String(a.date).localeCompare(String(b.date)))
        .slice(0, 4)
        .map(item => `
          <div class="ri" style="padding:8px 0">
            <div class="ri-info">
              <div class="rn">${escapeHtml(item.title || 'Deadline')}</div>
              <div class="rd">${escapeHtml(formatSchoolDate(item.date) || String(item.date || ''))}${item.meta ? ' · ' + escapeHtml(item.meta) : ''}</div>
            </div>
          </div>
        `).join('') || `<div class="sub">No upcoming deadlines.</div>`;
}
function renderSchoolCalendarBanner(activeTerm, events = [], extraDeadlines = []) {
    const termWeek = computeTermWeek(activeTerm);
    const termLabel = activeTerm
        ? `Term ${activeTerm.term_number} ${activeTerm.academic_year}${termWeek ? ` · Week ${termWeek}` : ''}`
        : 'No active term';
    return `
      <div class="card" style="border-left:4px solid var(--g);margin-bottom:12px">
        <div class="card-body">
          <div style="display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start;justify-content:space-between">
            <div style="min-width:220px">
              <div style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--m);font-weight:800">School Time</div>
              <div style="font-weight:900;font-size:18px;color:var(--md);margin-top:4px">${escapeHtml(formatSchoolNow())}</div>
              <div class="sub" style="margin-top:4px">Timezone: ${escapeHtml(SCHOOL_TIME_ZONE)} · ${escapeHtml(termLabel)}</div>
            </div>
            <div style="flex:1;min-width:260px">
              <div style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--m);font-weight:800">Upcoming Deadlines</div>
              <div style="margin-top:4px">${buildUpcomingDeadlineRows(activeTerm, events, extraDeadlines)}</div>
            </div>
          </div>
        </div>
      </div>`;
}
function credentialHealthBadgeClass(status) {
    if (status === 'healthy') return 'green';
    if (status === 'inactive') return 'blue';
    if (status === 'failing' || status === 'missing') return 'red';
    return '';
}
function renderCredentialHealthCard(health, role = '') {
    if (!health) {
        return financeHintCard(
            'Credential health unavailable',
            'The dashboard could not load provider health right now. Super Admin can still open API Credentials and run manual checks.'
        );
    }
    const providers = (health.providers || []).map(p => `
      <div class="ri">
        <div class="ri-info">
          <div class="rn">${escapeHtml(p.label || '')}</div>
          <div class="rd">${escapeHtml(p.service_label || 'Not configured')} · ${escapeHtml(p.detail || '')}</div>
        </div>
        <div class="ri-end">
          <span class="badge ${credentialHealthBadgeClass(p.status)}">${escapeHtml(p.status_label || p.status || '')}</span>
        </div>
      </div>
    `).join('');
    const notif = health.notifications || {};
    const failures = (health.recent_failures || []).slice(0, 3).map(f => `
      <div class="ri" style="padding:6px 0">
        <div class="ri-info">
          <div class="rn">${escapeHtml(f.service_label || f.service_name || '')}</div>
          <div class="rd">${escapeHtml(f.detail || 'Verification failed.')} · ${escapeHtml(formatDateTime(f.verified_at, ''))}</div>
        </div>
      </div>
    `).join('') || `<div class="sub">No recent provider failures recorded.</div>`;
    const canManageCredentials = role === 'superadmin';
    return `
      <div class="card">
        <div class="card-head"><div class="card-title">Credential Health</div><div class="sub">${Number((health.summary || {}).healthy_count || 0)}/${Number((health.summary || {}).total_count || 0)} healthy</div></div>
        <div class="card-body">
          ${providers}
          <div style="height:10px"></div>
          <div style="font-weight:900;margin-bottom:6px">Recent failures</div>
          ${failures}
          <div style="height:10px"></div>
          <div class="sub">Credential email: <strong>${notif.send_credentials_email_enabled ? 'on' : 'off'}</strong> · Credential SMS: <strong>${notif.send_credentials_sms_enabled ? 'on' : 'off'}</strong> · Fee SMS: <strong>${notif.send_fee_reminder_sms_enabled ? 'on' : 'off'}</strong></div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px">
            ${canManageCredentials ? `<button class="btn btn-xs btn-ghost" onclick="loadPage('credentials', null, 'API Credentials')">Open Credentials</button>` : ''}
            <button class="btn btn-xs btn-ghost" onclick="loadPage('settings', null, 'Settings')">Notification Settings</button>
          </div>
        </div>
      </div>`;
}
function renderCashierHandoverCard(handover) {
    if (!handover) {
        return financeHintCard(
            'Cashier handover unavailable',
            'The handover summary could not be loaded right now. Open Cashbook to review prior close information and pending deposits.'
        );
    }
    const prior = handover.prior_close || null;
    const depositPreview = (handover.pending_deposits || []).slice(0, 3).map(d => `
      <div class="ri" style="padding:6px 0">
        <div class="ri-info">
          <div class="rn">${escapeHtml(d.batch_name || '')}</div>
          <div class="rd">${escapeHtml(formatSchoolDate(d.deposit_date) || d.deposit_date || '')} · ${Number(d.payments_count || 0)} payment(s)</div>
        </div>
        <div class="ri-end">UGX ${fmt(Number(d.total_amount || 0).toFixed(0))}</div>
      </div>
    `).join('') || `<div class="sub">No pending bank deposits.</div>`;
    const promisePreview = (handover.unresolved_promises || []).slice(0, 3).map(p => `
      <div class="ri" style="padding:6px 0">
        <div class="ri-info">
          <div class="rn">${escapeHtml(p.student_name || '')}</div>
          <div class="rd">${escapeHtml(formatSchoolDate(p.promised_for) || p.promised_for || '')} · ${escapeHtml(p.status || '')}</div>
        </div>
        <div class="ri-end">UGX ${fmt(Number(p.amount || 0).toFixed(0))}</div>
      </div>
    `).join('') || `<div class="sub">No unresolved promises.</div>`;
    const alertRows = (handover.alerts || []).map(a => `
      <div class="ri" style="padding:6px 0">
        <div class="ri-info">
          <div class="rn">${escapeHtml(a.title || '')}</div>
          <div class="rd">${escapeHtml(a.detail || '')}</div>
        </div>
      </div>
    `).join('');
    return `
      <div class="card">
        <div class="card-head"><div class="card-title">Cashier Handover</div><div class="sub">Next-shift readiness</div></div>
        <div class="card-body">
          ${handover.handover_alert_due ? `<div class="card" style="margin:0 0 12px 0;border-left:4px solid var(--or);border-style:solid"><div class="card-body" style="padding:10px 12px"><div style="font-weight:900;color:var(--md)">Handover reminder due by ${escapeHtml(handover.handover_alert_time || '')}</div><div class="sub" style="margin-top:4px">Unposted deposits or unresolved promises still need attention before close of day.</div>${alertRows ? `<div style="margin-top:8px">${alertRows}</div>` : ''}</div></div>` : ''}
          <div class="stats stats-4" style="margin-bottom:12px">
            <div class="stat-card"><div class="stat-num">UGX ${fmt(Number(handover.opening_cash_suggestion || 0).toFixed(0))}</div><div class="stat-label">Suggested opening cash</div><div class="stat-accent gold"></div></div>
            <div class="stat-card"><div class="stat-num">UGX ${fmt(Number((prior && prior.variance_amount) || 0).toFixed(0))}</div><div class="stat-label">Prior variance</div><div class="stat-accent red"></div></div>
            <div class="stat-card"><div class="stat-num">${Number(handover.pending_deposit_count || 0)}</div><div class="stat-label">Pending deposits</div><div class="stat-accent blue"></div></div>
            <div class="stat-card"><div class="stat-num">${Number(handover.unresolved_promise_count || 0)}</div><div class="stat-label">Open promises</div><div class="stat-accent green"></div></div>
          </div>
          <div class="grid-2" style="gap:12px">
            <div>
              <div style="font-weight:900;margin-bottom:6px">Pending Deposits</div>
              ${depositPreview}
            </div>
            <div>
              <div style="font-weight:900;margin-bottom:6px">Unresolved Promises</div>
              ${promisePreview}
            </div>
          </div>
          <div class="sub" style="margin-top:10px">${prior ? `Last close: ${escapeHtml(formatSchoolDate(prior.close_date) || prior.close_date || '')} · counted cash UGX ${fmt(Number(prior.counted_cash_on_hand || 0).toFixed(0))}` : 'No earlier cashbook close found for this scope.'}</div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px">
            <button class="btn btn-xs btn-ghost" onclick="loadPage('cashbook', null, 'Cashbook')">Open Cashbook</button>
            <button class="btn btn-xs btn-ghost" onclick="openCashbookHandoverReport(todayISO(), ${(currentUser && currentUser.profile && currentUser.profile.role === 'bursar') ? 'currentUser.id' : 'null'})">Print Handover</button>
          </div>
        </div>
      </div>`;
}
async function getActiveTermCached() {
    const now = Date.now();
    if (ACTIVE_TERM_CACHE && (now - ACTIVE_TERM_CACHE_AT) < 30_000) return ACTIVE_TERM_CACHE;
    const t = await API.fetch('/terms/').catch(() => null);
    ACTIVE_TERM_CACHE = t;
    ACTIVE_TERM_CACHE_AT = now;
    return t;
}

async function openNewTermModal() {
    try {
        if (!(currentUser && currentUser.caps && currentUser.caps.term_manage)) {
            flash('Only special administrators can start a new term.');
            return;
        }
    } catch {}
    const active = await getActiveTermCached();
    let yr = (active && active.academic_year) ? Number(active.academic_year) : currentYear();
    let term = (active && active.term_number) ? Number(active.term_number) : 1;
    // Suggest the next term by default.
    if (term >= 3) { term = 1; yr = yr + 1; } else { term = term + 1; }

    const yrEl = document.getElementById('nt-yr');
    const numEl = document.getElementById('nt-num');
    const stEl = document.getElementById('nt-st');
    const enEl = document.getElementById('nt-en');
    const brkEl = document.getElementById('nt-brk');
    if (yrEl) yrEl.value = String(yr);
    if (numEl) numEl.value = String(term);
    if (stEl) stEl.value = todayISO();
    if (enEl) enEl.value = addDaysISO(90);
    if (brkEl) brkEl.value = '0';
    const fees = document.getElementById('nt-fees'); if (fees) fees.checked = true;
    const sms = document.getElementById('nt-sms'); if (sms) sms.checked = false;
    const marks = document.getElementById('nt-marks'); if (marks) marks.checked = true;

    openModal('modal-term');
}

const NAV = {
    superadmin: [
        { section: 'Overview' },
        { label: 'Dashboard', icon: 'D', page: 'dashboard' },
        { section: 'Administration' },
        { label: 'User Accounts', icon: 'U', page: 'users' },
        { label: 'Guardian Links', icon: 'GL', page: 'guardian_links' },
        { label: 'Classes', icon: 'C', page: 'classes' },
        { label: 'Teachers', icon: 'T', page: 'teachers' },
        { label: 'Students', icon: 'S', page: 'students' },
        { section: 'Academic' },
        { label: 'Promotions', icon: 'P', page: 'promotions' },
        { label: 'Subjects', icon: 'SB', page: 'subjects' }, 
        { cap: 'term_manage', label: 'Terms', icon: 'R', page: 'terms' }, 
        { label: 'Report Cards', icon: 'RC', page: 'reportcards' }, 
        { label: 'Grading', icon: 'G', page: 'grading' }, 
        { label: 'Timetable', icon: 'TT', page: 'timetable' }, 
        { label: 'Teacher Attendance', icon: 'TA', page: 'teacher_attendance' },
        { section: 'School' },
        { label: 'Events', icon: 'EV', page: 'events' },
        { label: 'Announcements', icon: 'AN', page: 'announcements' },
        { label: 'Communications', icon: 'CM', page: 'communications' },
        { label: 'Delivery Logs', icon: 'DL', page: 'delivery_logs' },
        { section: 'Finance' },
        { label: 'Fees', icon: 'F', page: 'fees' },
        { label: 'Class Charges', icon: 'CH', page: 'charges' },
        { label: 'Payments', icon: '$', page: 'finance' },
        { label: 'Cashbook', icon: 'CB', page: 'cashbook' },
        { label: 'Approvals', icon: 'AP', page: 'approvals' },
        { label: 'Installments', icon: 'IP', page: 'installment_plans' },
        { label: 'Fee Promises', icon: 'FP', page: 'fee_promises' },
        { label: 'Adjustments', icon: 'ADJ', page: 'adjustments' },
        { label: 'Deposits', icon: 'DP', page: 'deposits' },
        { label: 'Expenses', icon: 'EX', page: 'expenses' },
        { section: 'System' },
        { label: 'Audit Logs', icon: 'L', page: 'auditlogs' }, 
        { label: 'API Credentials', icon: 'K', page: 'credentials' }, 
        { label: 'Security', icon: 'SEC', page: 'security' }, 
        { label: 'Print Queue', icon: 'PQ', page: 'printqueue' }, 
        { label: 'Settings', icon: 'S', page: 'settings' }, 
    ], 
    admin: [
        { section: 'Overview' },
        { label: 'Dashboard', icon: 'D', page: 'dashboard' },
        { section: 'Students' },
        { label: 'All Students', icon: 'S', page: 'students' },
        { section: 'Staff' },
        { label: 'Teachers', icon: 'T', page: 'teachers' },
        { label: 'Classes', icon: 'C', page: 'classes' },
        { section: 'Academic' },
        { label: 'Promotions', icon: 'P', page: 'promotions' },
        { label: 'Subjects', icon: 'SB', page: 'subjects' },
        { cap: 'term_manage', label: 'Terms', icon: 'R', page: 'terms' },
        { label: 'Report Cards', icon: 'RC', page: 'reportcards' },
        { label: 'Timetable', icon: 'TT', page: 'timetable' },
        { label: 'Teacher Attendance', icon: 'TA', page: 'teacher_attendance' },
        { section: 'School' },
        { label: 'Events', icon: 'EV', page: 'events' },
        { label: 'Announcements', icon: 'AN', page: 'announcements' },
        { label: 'Communications', icon: 'CM', page: 'communications' },
        { label: 'Delivery Logs', icon: 'DL', page: 'delivery_logs' },
        { section: 'Finance' },
        { label: 'Fees', icon: 'F', page: 'fees' },
        { label: 'Class Charges', icon: 'CH', page: 'charges' },
        { label: 'Payments', icon: '$', page: 'finance' },
        { label: 'Cashbook', icon: 'CB', page: 'cashbook' },
        { label: 'Approvals', icon: 'AP', page: 'approvals' },
        { label: 'Installments', icon: 'IP', page: 'installment_plans' },
        { label: 'Fee Promises', icon: 'FP', page: 'fee_promises' },
        { label: 'Adjustments', icon: 'ADJ', page: 'adjustments' },
        { label: 'Deposits', icon: 'DP', page: 'deposits' },
        { label: 'Expenses', icon: 'EX', page: 'expenses' }, 
        { section: 'System' }, 
        { label: 'Print Queue', icon: 'PQ', page: 'printqueue' }, 
        { label: 'Settings', icon: 'S', page: 'settings' }, 
    ], 
    headteacher: [
        { section: 'Overview' },
        { label: 'Dashboard', icon: 'D', page: 'dashboard' },
        { section: 'Students' },
        { label: 'All Students', icon: 'S', page: 'students' },
        { section: 'Staff' },
        { label: 'Teachers', icon: 'T', page: 'teachers' },
        { label: 'Classes', icon: 'C', page: 'classes' },
        { section: 'Academic' },
        { label: 'Promotions', icon: 'P', page: 'promotions' },
        { label: 'Subjects', icon: 'SB', page: 'subjects' },
        { cap: 'term_manage', label: 'Terms', icon: 'R', page: 'terms' },
        { label: 'Report Cards', icon: 'RC', page: 'reportcards' },
        { label: 'Timetable', icon: 'TT', page: 'timetable' },
        { label: 'Teacher Attendance', icon: 'TA', page: 'teacher_attendance' },
        { section: 'School' },
        { label: 'Events', icon: 'EV', page: 'events' },
        { label: 'Announcements', icon: 'AN', page: 'announcements' },
        { label: 'Communications', icon: 'CM', page: 'communications' },
        { label: 'Delivery Logs', icon: 'DL', page: 'delivery_logs' },
        { section: 'Finance' },
        { label: 'Fees', icon: 'F', page: 'fees' },
        { label: 'Class Charges', icon: 'CH', page: 'charges' },
        { label: 'Payments', icon: '$', page: 'finance' },
        { section: 'System' },
        { label: 'Settings', icon: 'S', page: 'settings' },
    ],
    deputy: [
        { section: 'Overview' },
        { label: 'Dashboard', icon: 'D', page: 'dashboard' },
        { section: 'Students' },
        { label: 'All Students', icon: 'S', page: 'students' },
        { label: 'Report Cards', icon: 'RC', page: 'reportcards' },
        { label: 'Teacher Attendance', icon: 'TA', page: 'teacher_attendance' },
        { section: 'School' },
        { label: 'Events', icon: 'EV', page: 'events' },
        { label: 'Announcements', icon: 'AN', page: 'announcements' },
        { label: 'Communications', icon: 'CM', page: 'communications' },
        { label: 'Delivery Logs', icon: 'DL', page: 'delivery_logs' },
        { section: 'System' },
        { label: 'Settings', icon: 'S', page: 'settings' },
    ],
    dos: [
        { section: 'Overview' },
        { label: 'Dashboard', icon: 'D', page: 'dashboard' },
        { section: 'Academic' },
        { label: 'Students', icon: 'S', page: 'students' },
        { label: 'Teachers', icon: 'T', page: 'teachers' },
        { label: 'Classes', icon: 'C', page: 'classes' },
        { label: 'Timetable', icon: 'TT', page: 'timetable' },
        { label: 'Promotions', icon: 'P', page: 'promotions' },
        { label: 'Subjects', icon: 'SB', page: 'subjects' }, 
        { cap: 'term_manage', label: 'Terms', icon: 'R', page: 'terms' }, 
        { label: 'Report Cards', icon: 'RC', page: 'reportcards' }, 
        { label: 'Grading', icon: 'G', page: 'grading' }, 
        { section: 'School' }, 
        { label: 'Events', icon: 'EV', page: 'events' },
        { label: 'Announcements', icon: 'AN', page: 'announcements' },
        { label: 'Communications', icon: 'CM', page: 'communications' },
        { label: 'Delivery Logs', icon: 'DL', page: 'delivery_logs' },
        { section: 'System' },
        { label: 'Settings', icon: 'S', page: 'settings' },
    ],
    bursar: [{ section: 'Finance' }, { label: 'Fees', icon: 'F', page: 'fees' }, { label: 'Class Charges', icon: 'CH', page: 'charges' }, { label: 'Payments', icon: '$', page: 'finance' }, { label: 'Cashbook', icon: 'CB', page: 'cashbook' }, { label: 'Approvals', icon: 'AP', page: 'approvals' }, { label: 'Installments', icon: 'IP', page: 'installment_plans' }, { label: 'Fee Promises', icon: 'FP', page: 'fee_promises' }, { label: 'Deposits', icon: 'DP', page: 'deposits' }, { label: 'Expenses', icon: 'EX', page: 'expenses' }, { label: 'Adjustments', icon: 'ADJ', page: 'adjustments' }, { label: 'Delivery Logs', icon: 'DL', page: 'delivery_logs' }, { label: 'Settings', icon: 'S', page: 'settings' }],
    teacher: [
        { section: 'Overview' },
        { label: 'My Dashboard', icon: 'D', page: 'dashboard' },
        { label: 'My Timetable', icon: 'TT', page: 'timetable' },
        { section: 'Academic' },
        { label: 'My Class', icon: 'CL', page: 'my_class' },
        { label: 'Gradebook', icon: 'GB', page: 'my_class' },
        { label: 'Exams Upload', icon: 'EX', page: 'exams' },
        { cap: 'ai_tools', label: 'AI Tools', icon: 'AI', page: 'ai_tools' },
        { section: 'School' },
        { label: 'Events', icon: 'EV', page: 'events' },
        { label: 'Announcements', icon: 'AN', page: 'announcements' },
        { label: 'Communications', icon: 'CM', page: 'communications' },
        { label: 'Delivery Logs', icon: 'DL', page: 'delivery_logs' },
        { section: 'System' },
        { label: 'Settings', icon: 'S', page: 'settings' },
    ],
    parent: [{ section: 'Home' }, { label: 'Child Dashboard', icon: 'D', page: 'dashboard' }, { label: 'My Fees', icon: '$', page: 'my_fees' }, { label: 'Timetable', icon: 'TT', page: 'timetable' }, { label: 'Events', icon: 'EV', page: 'events' }, { label: 'Announcements', icon: 'AN', page: 'announcements' }, { label: 'Settings', icon: 'S', page: 'settings' }],
    student: [{ section: 'School' }, { label: 'My Dashboard', icon: 'D', page: 'dashboard' }, { label: 'My Fees', icon: '$', page: 'my_fees' }, { label: 'Timetable', icon: 'TT', page: 'timetable' }, { label: 'Events', icon: 'EV', page: 'events' }, { label: 'Announcements', icon: 'AN', page: 'announcements' }, { label: 'Settings', icon: 'S', page: 'settings' }],
    reception: [
        { section: 'Overview' },
        { label: 'Dashboard', icon: 'D', page: 'dashboard' },
        { label: 'Students', icon: 'S', page: 'students' },
        { label: 'Guardian Links', icon: 'GL', page: 'guardian_links' },
        { label: 'Report Cards', icon: 'RC', page: 'reportcards' }, 
        { label: 'Timetable', icon: 'TT', page: 'timetable' }, 
        { label: 'Teacher Attendance', icon: 'TA', page: 'teacher_attendance' }, 
        { label: 'Print Queue', icon: 'PQ', page: 'printqueue' }, 
        { label: 'Print Desk', icon: 'PR', page: 'printdesk' }, 
        { label: 'Exams Print', icon: 'EX', page: 'printdesk' }, 
        { label: 'Communications', icon: 'CM', page: 'communications' },
        { label: 'Delivery Logs', icon: 'DL', page: 'delivery_logs' },
        { label: 'Events', icon: 'EV', page: 'events' }, 
        { label: 'Announcements', icon: 'AN', page: 'announcements' },
        { section: 'System' },
        { label: 'Settings', icon: 'S', page: 'settings' }
    ]
};

document.addEventListener('DOMContentLoaded', async () => { 
    // Prime CSRF token early so the first POST/PATCH/DELETE works reliably. 
    try { await API.refreshCsrfToken(); } catch {} 
    // Retry any queued offline actions when the connection comes back. 
    window.addEventListener('online', () => { try { API.flushOfflineQueue(); } catch {} }); 
    try { await API.flushOfflineQueue(); } catch {} 
 
    const showLoginScreen = () => { 
        try { document.body.dataset.boot = 'login'; } catch {} 
        // Never block the UI on an API call: if session-check is slow/down, show login anyway.
        setTimeout(() => {
            const sp = document.getElementById('splash');
            if (sp) sp.classList.add('fade-out');
            setTimeout(() => {
                if (sp) sp.style.display = 'none';
                const ls = document.getElementById('login-screen');
                if (ls) ls.classList.add('show');
            }, 500);
        }, 500);
    };

    // Surface JS errors to the user (otherwise it looks like "nothing happens").
    window.addEventListener('error', (ev) => {
        try {
            const msg = (ev && ev.message) ? ev.message : 'Unexpected error';
            setLoginError('UI error: ' + msg);
            showLoginScreen();
        } catch {}
    });
    window.addEventListener('unhandledrejection', (ev) => {
        try {
            const r = ev && ev.reason ? ev.reason : null;
            const msg = (r && (r.detail || r.message)) ? (r.detail || r.message) : 'Unexpected error';
            setLoginError('UI error: ' + msg);
            showLoginScreen();
        } catch {}
    });

    const withTimeout = (p, ms) => {
        return Promise.race([
            p,
            new Promise((_, reject) => setTimeout(() => reject({ detail: 'Session check timed out' }), ms)),
        ]);
    };

    // Absolute failsafe: if anything prevents init, don't strand the user on splash forever.
    setTimeout(() => {
        const sp = document.getElementById('splash');
        const app = document.getElementById('app');
        const ls = document.getElementById('login-screen');
        const splashVisible = sp && sp.style.display !== 'none';
        const appShown = app && app.classList.contains('show');
        const loginShown = ls && ls.classList.contains('show');
        if (splashVisible && !appShown && !loginShown) showLoginScreen();
    }, 3500);

    try {
        // If the backend is still starting/migrating, this can hang for a while in some browsers.
        // Timeout keeps the splash from getting stuck forever.
        currentUser = await withTimeout(API.fetch('/auth/me/'), 2000);
        enterApp();
    } catch (e) {
        showLoginScreen();
    }

    // Enter-to-submit: the login page is not a <form> on purpose, so we bind Enter manually.
    const bindEnter = (id, fn) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.addEventListener('keydown', (ev) => {
            if (ev.key === 'Enter') {
                ev.preventDefault();
                ev.stopPropagation();
                try { fn(); } catch {}
            }
        });
    };
    bindEnter('login-user', doLogin);
    bindEnter('login-pass', doLogin);
    bindEnter('fp-identifier', requestPasswordReset);
    bindEnter('fp-otp', confirmPasswordReset);
    bindEnter('fp-new-pass', confirmPasswordReset);
    bindEnter('fp-confirm-pass', confirmPasswordReset);
});

async function doLogin() {
    const identifier = document.getElementById('login-user').value.trim();
    const password = document.getElementById('login-pass').value;
    setLoginError('');
    try {
        const btn = document.getElementById('login-btn');
        if (btn) { btn.disabled = true; btn.textContent = 'Signing in...'; }
        const res = await API.fetch('/auth/login/', { method: 'POST', body: JSON.stringify({ identifier, password }) });
        if (res && res.status === 'otp_required') {
            const code = prompt('Enter the OTP sent to your email/phone:');
            if (!code) throw { detail: 'OTP required.' };
            await API.fetch('/auth/confirm-2fa/', { method: 'POST', body: JSON.stringify({ otp_code: String(code).trim() }) });
        }
        // Require server-confirmed session identity.
        // If cookies are blocked or you're switching between localhost and 127.0.0.1,
        // the session won't stick and you will appear "logged out" immediately.
        currentUser = await API.fetch('/auth/me/');
        enterApp();
        flash('Logged in.');
    } catch (e) {
        let msg = 'Login failed.';
        if (e && e.detail) msg = e.detail;
        else if (e && e.status) msg = e.status;
        setLoginError(msg + ' (Tip: use only one address: either http://127.0.0.1:8000 or http://localhost:8000, not both)');
    } finally {
        const btn = document.getElementById('login-btn');
        if (btn) { btn.disabled = false; btn.textContent = 'Sign In ->'; }
    }
}

function setLoginError(msg) {
    const el = document.getElementById('login-error');
    if (!el) return;
    if (!msg) { el.style.display = 'none'; el.textContent = ''; return; }
    el.textContent = msg;
    el.style.display = 'block';
}

function showForgot() {
    setLoginError('');
    document.getElementById('login-title').textContent = 'Reset Password';
    document.getElementById('login-form').style.display = 'none';
    document.getElementById('forgot-form').style.display = 'block';
}

function showLogin() {
    setLoginError('');
    document.getElementById('login-title').textContent = 'Sign In';
    document.getElementById('forgot-form').style.display = 'none';
    document.getElementById('login-form').style.display = 'block';
    document.getElementById('fp-step2').style.display = 'none';
}

async function requestPasswordReset() {
    const identifier = document.getElementById('fp-identifier').value.trim();
    setLoginError('');
    try {
        await API.fetch('/auth/request-password-reset/', { method: 'POST', body: JSON.stringify({ identifier }) });
        document.getElementById('fp-step2').style.display = 'block';
        flash('OTP sent. Check your phone/email.');
    } catch (e) {
        setLoginError(e && e.detail ? e.detail : 'Failed to send OTP.');
    }
}

async function confirmPasswordReset() {
    const identifier = document.getElementById('fp-identifier').value.trim();
    const otp_code = document.getElementById('fp-otp').value.trim();
    const new_password = document.getElementById('fp-new-pass').value;
    const confirm_password = document.getElementById('fp-confirm-pass').value;
    setLoginError('');
    if (!otp_code || otp_code.length < 6) { setLoginError('Enter the 6-digit OTP code.'); return; }
    if (!new_password) { setLoginError('Enter a new password.'); return; }
    if (!validateStrongPasswordClient(new_password, 'New password')) { return; }
    if (new_password !== confirm_password) { setLoginError('Passwords do not match.'); return; }
    try {
        await API.fetch('/auth/confirm-password-reset/', { method: 'POST', body: JSON.stringify({ identifier, otp_code, new_password }) });
        flash('Password reset successful. Please sign in.');
        showLogin();
    } catch (e) {
        setLoginError(e && e.detail ? e.detail : 'Failed to reset password.');
    }
}

function doLogout() { API.fetch('/auth/logout/', { method: 'POST' }).then(() => location.reload()); }

function enterApp() {
    try { document.body.dataset.boot = 'app'; } catch {}
    
    try {
        document.getElementById('login-screen').classList.remove('show');
        document.getElementById('app').classList.add('show');
        document.getElementById('splash').style.display = 'none';
    } catch (e) {
        console.error('App shell initialization failed:', e);
    }
    
    try {
        document.getElementById('topbar-name').textContent = currentUser.first_name || currentUser.username;
        document.getElementById('topbar-ava').textContent = (currentUser.profile && currentUser.profile.avatar) || 'AD';
    } catch (e) {
        console.error('Topbar update failed:', e);
    }

    buildSidebar();
    
    try {
        applySidebarCollapseState();
    } catch (e) {
        console.error('Sidebar collapse state failed:', e);
    }

    try {
        loadPage('dashboard');
    } catch (e) {
        console.error('Dashboard load failed:', e);
        const main = document.getElementById('main-content');
        if (main) {
            main.innerHTML = `<div class="page"><div class="page-title">Unable to load dashboard</div><div class="sub">An unexpected error occurred. Open the browser console for details and refresh the page.</div></div>`;
        }
    }
    refreshTermChip();
    maybeHandleTeacherQR();
    refreshNotificationsBadge();
    setTimeout(() => { try { maybeOpenFirstLoginTutorial(); } catch {} }, 250);

    try {
        if (currentUser && currentUser.profile && currentUser.profile.must_change_password) {
            flash('Security: please change your password now.');
            loadPage('settings', null, 'Settings');
        }
    } catch {}
}

function safeIcon(icon, label) {
    const s = (icon == null) ? '' : String(icon);
    // If icon looks like plain ASCII (1-4 chars), keep it; otherwise fall back to label initials.
    if (s && /^[\x20-\x7E]{1,4}$/.test(s)) return s;
    const l = (label == null) ? '' : String(label).trim();
    if (!l) return '??';
    const parts = l.split(/\s+/).filter(Boolean);
    const init = (parts.length >= 2) ? (parts[0][0] + parts[1][0]) : parts[0].slice(0, 2);
    return init.toUpperCase();
}

function escapeHtml(s) {
    const v = (s == null) ? '' : String(s);
    return v.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\"/g, '&quot;').replace(/'/g, '&#39;');
}

function sanitizeCommunicationHtmlClient(value) {
    const raw = String(value || '').trim();
    if (!raw) return '';
    const parser = new DOMParser();
    const doc = parser.parseFromString(`<div>${raw}</div>`, 'text/html');
    const allowed = new Set(['P', 'BR', 'STRONG', 'B', 'EM', 'I', 'U', 'S', 'UL', 'OL', 'LI', 'BLOCKQUOTE', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'TABLE', 'THEAD', 'TBODY', 'TFOOT', 'TR', 'TH', 'TD', 'DIV', 'SPAN', 'A', 'HR', 'SUB', 'SUP']);
    const alignable = new Set(['P', 'DIV', 'BLOCKQUOTE', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'TD', 'TH']);
    const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_ELEMENT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);

    nodes.forEach(node => {
        const tag = String(node.tagName || '').toUpperCase();
        if (!allowed.has(tag)) {
            const parent = node.parentNode;
            if (!parent) return;
            while (node.firstChild) parent.insertBefore(node.firstChild, node);
            parent.removeChild(node);
            return;
        }
        Array.from(node.attributes || []).forEach(attr => {
            const name = String(attr.name || '').toLowerCase();
            const val = String(attr.value || '');
            if (name.startsWith('on')) {
                node.removeAttribute(attr.name);
                return;
            }
            if (tag === 'A' && name === 'href') {
                if (/^\s*(javascript:|data:)/i.test(val)) node.removeAttribute(attr.name);
                else {
                    node.setAttribute('target', '_blank');
                    node.setAttribute('rel', 'noopener noreferrer');
                }
                return;
            }
            if (name === 'style' && alignable.has(tag)) {
                const m = val.match(/text-align\s*:\s*(left|center|right|justify)/i);
                if (m) node.setAttribute('style', `text-align:${m[1].toLowerCase()}`);
                else node.removeAttribute('style');
                return;
            }
            if (!['href', 'target', 'rel', 'style', 'colspan', 'rowspan'].includes(name)) {
                node.removeAttribute(attr.name);
            }
        });
    });
    return (doc.body.innerHTML || '').trim();
}

function communicationEditorEl() {
    return document.getElementById('cm-editor');
}

function syncCommunicationBodyInput() {
    const editor = communicationEditorEl();
    const body = document.getElementById('cm-body');
    if (!editor || !body) return '';
    const clean = sanitizeCommunicationHtmlClient(editor.innerHTML || '');
    body.value = clean;
    return clean;
}

function setCommunicationEditorContent(value) {
    const editor = communicationEditorEl();
    if (!editor) return;
    const safe = sanitizeCommunicationHtmlClient(value || COMMUNICATION_DEFAULT_TEMPLATE) || COMMUNICATION_DEFAULT_TEMPLATE;
    editor.innerHTML = safe;
    syncCommunicationBodyInput();
}

function ensureCommunicationEditor() {
    const editor = communicationEditorEl();
    if (!editor || editor.dataset.bound === '1') return;
    editor.dataset.bound = '1';
    editor.addEventListener('input', () => syncCommunicationBodyInput());
    editor.addEventListener('keyup', () => syncCommunicationBodyInput());
    editor.addEventListener('blur', () => syncCommunicationBodyInput());
    editor.addEventListener('paste', evt => {
        evt.preventDefault();
        const txt = (evt.clipboardData || window.clipboardData)?.getData('text/plain') || '';
        document.execCommand('insertText', false, txt);
        syncCommunicationBodyInput();
    });
    if (!(editor.innerHTML || '').trim()) setCommunicationEditorContent(COMMUNICATION_DEFAULT_TEMPLATE);
}

function execCommunicationCommand(command, value = null) {
    const editor = communicationEditorEl();
    if (!editor) return;
    editor.focus();
    if (command === 'createLink') {
        const url = window.prompt('Enter URL', 'https://');
        if (!url) return;
        document.execCommand('createLink', false, url);
    } else if (command === 'insertTable') {
        document.execCommand('insertHTML', false, '<table><tbody><tr><th>Heading</th><th>Value</th></tr><tr><td>Item</td><td>Details</td></tr></tbody></table><p></p>');
    } else if (command === 'insertRule') {
        document.execCommand('insertHorizontalRule', false, null);
    } else if (command === 'clearFormatting') {
        document.execCommand('removeFormat', false, null);
        document.execCommand('unlink', false, null);
    } else if (command === 'formatBlock') {
        document.execCommand('formatBlock', false, value || 'p');
    } else if (command === 'cut') {
        document.execCommand('cut', false, null);
    } else if (command === 'copy') {
        document.execCommand('copy', false, null);
    } else if (command === 'pasteText') {
        navigator.clipboard.readText().then(txt => {
            document.execCommand('insertText', false, txt || '');
            syncCommunicationBodyInput();
        }).catch(() => flash('Paste blocked by browser permissions.'));
        return;
    } else {
        document.execCommand(command, false, value);
    }
    syncCommunicationBodyInput();
}

function setCommunicationAlignment(mode) {
    const cmd = mode === 'center' ? 'justifyCenter' : mode === 'right' ? 'justifyRight' : mode === 'justify' ? 'justifyFull' : 'justifyLeft';
    execCommunicationCommand(cmd);
}

function insertCommunicationToken(token) {
    const editor = communicationEditorEl();
    if (!editor) return;
    editor.focus();
    document.execCommand('insertText', false, token);
    syncCommunicationBodyInput();
}

function miniBarsFromTrend(trend) {
    const items = Array.isArray(trend) ? trend : [];
    if (!items.length) return '<div class="sub">No attendance marks in the last 7 days.</div>';
    const maxMarked = Math.max(1, ...items.map(x => Number(x.marked || 0)));
    return `<div class="mini-bars">` + items.map(x => {
        const marked = Number(x.marked || 0);
        const present = Number(x.present || 0);
        const pct = marked ? Math.max(0, Math.min(1, present / marked)) : 0;
        const h = Math.round((marked / maxMarked) * 40) + 8;
        const day = String(x.date || '').slice(5); // MM-DD
        const tip = `${day}: ${present}/${marked || 0} present`;
        return `
          <div class="mini-bar-item" title="${escapeHtml(tip)}">
            <div class="mini-bar-bar" style="height:${h}px;opacity:${0.55 + 0.45 * pct}"></div>
            <div class="mini-bar-lbl">${escapeHtml(day)}</div>
          </div>`;
    }).join('') + `</div>`;
}

let ACTIVE_HANDOVER = null;
function showHandover(title, lines, handover) {
    ACTIVE_HANDOVER = handover || null;
    const ttl = document.getElementById('ho-ttl');
    if (ttl) ttl.textContent = title || 'Handover';
    const body = document.getElementById('ho-body');
    if (body) body.innerHTML = (lines || []).map(l => `<div style="padding:6px 0;border-bottom:1px solid var(--f0)">${escapeHtml(l)}</div>`).join('');
    const pc = document.getElementById('ho-print-cred');
    const pa = document.getElementById('ho-print-adm');
    const hasCred = !!(handover && (handover.print_credentials_url || handover.print_teacher_credentials_url));
    const hasAdm = !!(handover && handover.print_admission_letter_url);
    if (pc) pc.style.display = hasCred ? 'inline-flex' : 'none';
    if (pa) pa.style.display = hasAdm ? 'inline-flex' : 'none';
    openModal('modal-handover');
}

function credentialDeliveryLines(delivery) {
    if (!delivery) return [];
    const lines = [];
    if (delivery.email_attempted) {
        const mode = delivery.email_delivery_mode === 'console' ? 'dev console only' : (delivery.email_transport || 'email');
        lines.push(`Email delivery: ${delivery.email_sent ? 'sent' : 'failed'} via ${mode}`);
    } else if (delivery.email_transport) {
        lines.push(`Email route: ${delivery.email_transport}${delivery.email_live_ready ? '' : ' (not live yet)'}`);
    }
    if (delivery.sms_attempted) {
        const mode = delivery.sms_transport || 'SMS gateway';
        lines.push(`SMS delivery: ${delivery.sms_sent ? 'sent' : 'failed'} via ${mode}`);
    } else if (delivery.sms_transport) {
        lines.push(`SMS route: ${delivery.sms_transport}${delivery.sms_live_ready ? '' : ' (not live yet)'}`);
    }
    return lines;
}

function handoverPrint(which) {
    if (!ACTIVE_HANDOVER) return;
    let url = null;
    if (which === 'adm') url = ACTIVE_HANDOVER.print_admission_letter_url || null;
    if (which === 'cred') url = ACTIVE_HANDOVER.print_credentials_url || ACTIVE_HANDOVER.print_teacher_credentials_url || null;
    if (!url) { flash('No print URL available.'); return; }
    window.open(url, '_blank');
}

function tutorialKeyForRole(role) {
    return `bjs_tutorial_seen_${String(role || 'user')}`;
}

function getTutorialStepsForCurrentRole() {
    const role = (((currentUser || {}).profile || {}).role || 'admin');
    return FIRST_LOGIN_TUTORIALS[role] || FIRST_LOGIN_TUTORIALS.admin;
}

function renderTutorialStep() {
    const titleEl = document.getElementById('tt-ttl');
    const bodyEl = document.getElementById('tt-body');
    const metaEl = document.getElementById('tt-meta');
    const prevBtn = document.getElementById('tt-prev');
    const nextBtn = document.getElementById('tt-next');
    const actionBtn = document.getElementById('tt-action');
    const step = (TUTORIAL_STATE.steps || [])[TUTORIAL_STATE.index] || null;
    if (!step || !titleEl || !bodyEl || !metaEl) return;
    titleEl.textContent = step.title || 'Welcome';
    metaEl.textContent = `Step ${TUTORIAL_STATE.index + 1} of ${TUTORIAL_STATE.steps.length}`;
    bodyEl.innerHTML = `
      <div class="tutorial-card">
        <div class="tutorial-kicker">${escapeHtml(step.label || 'Getting started')}</div>
        <div class="tutorial-body">${escapeHtml(step.body || '')}</div>
      </div>
      <div class="tutorial-list">
        ${(TUTORIAL_STATE.steps || []).map((item, idx) => `
          <button class="tutorial-step ${idx === TUTORIAL_STATE.index ? 'active' : ''}" onclick="jumpTutorialStep(${idx})">
            <span>${idx + 1}</span>
            <strong>${escapeHtml(item.title || '')}</strong>
          </button>`).join('')}
      </div>
    `;
    if (prevBtn) prevBtn.disabled = TUTORIAL_STATE.index <= 0;
    if (nextBtn) nextBtn.textContent = TUTORIAL_STATE.index >= TUTORIAL_STATE.steps.length - 1 ? 'Finish' : 'Next';
    if (actionBtn) {
        actionBtn.textContent = step.actionLabel || 'Open';
        actionBtn.style.display = step.page ? 'inline-flex' : 'none';
    }
}

function openTutorial(force = false) {
    const role = (((currentUser || {}).profile || {}).role || 'admin');
    if (!force && localStorage.getItem(tutorialKeyForRole(role))) return;
    TUTORIAL_STATE = { role, index: 0, steps: getTutorialStepsForCurrentRole() };
    renderTutorialStep();
    openModal('modal-tutorial');
}

function maybeOpenFirstLoginTutorial() {
    const role = (((currentUser || {}).profile || {}).role || 'admin');
    if (!['admin', 'bursar', 'teacher', 'reception'].includes(role)) return;
    openTutorial(false);
}

function jumpTutorialStep(idx) {
    if (!Array.isArray(TUTORIAL_STATE.steps) || idx < 0 || idx >= TUTORIAL_STATE.steps.length) return;
    TUTORIAL_STATE.index = idx;
    renderTutorialStep();
}

function moveTutorialStep(delta) {
    const next = TUTORIAL_STATE.index + delta;
    if (next >= TUTORIAL_STATE.steps.length) {
        completeTutorial();
        return;
    }
    if (next < 0) return;
    TUTORIAL_STATE.index = next;
    renderTutorialStep();
}

function tutorialOpenCurrentAction() {
    const step = (TUTORIAL_STATE.steps || [])[TUTORIAL_STATE.index] || null;
    if (!step || !step.page) return;
    closeModal('modal-tutorial');
    loadPage(step.page, null, step.actionLabel || step.title || 'Tutorial');
}

function completeTutorial() {
    const role = TUTORIAL_STATE.role || (((currentUser || {}).profile || {}).role || 'admin');
    try { localStorage.setItem(tutorialKeyForRole(role), String(Date.now())); } catch {}
    closeModal('modal-tutorial');
    flash('Tutorial saved. You can reopen it from Settings.');
}

async function uploadImageFile(file) {
    if (!file) throw { detail: 'No file selected.' };
    const fd = new FormData();
    fd.append('file', file);
    const res = await API.fetch('/uploads/image/', { method: 'POST', body: fd, headers: {} });
    return res.url;
}

async function uploadDocFile(file) {
    if (!file) throw { detail: 'No file selected.' };
    const fd = new FormData();
    fd.append('file', file);
    const res = await API.fetch('/uploads/file/', { method: 'POST', body: fd, headers: {} });
    return res.url;
}

function wireDropZone(zoneEl, inputEl, onFiles) {
    if (!zoneEl || !inputEl) return;
    const stop = (e) => { e.preventDefault(); e.stopPropagation(); };
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(ev => zoneEl.addEventListener(ev, stop));
    zoneEl.addEventListener('dragover', () => zoneEl.classList.add('drag'));
    zoneEl.addEventListener('dragleave', () => zoneEl.classList.remove('drag'));
    zoneEl.addEventListener('drop', (e) => {
        zoneEl.classList.remove('drag');
        const files = (e.dataTransfer && e.dataTransfer.files) ? Array.from(e.dataTransfer.files) : [];
        if (files.length) onFiles(files);
    });
    zoneEl.addEventListener('click', () => inputEl.click());
    inputEl.addEventListener('change', () => {
        const files = inputEl.files ? Array.from(inputEl.files) : [];
        if (files.length) onFiles(files);
    });
}

function buildSidebar() {
    try {
        const nav = document.getElementById('sb-nav-content');
        if (!nav) return;

        nav.innerHTML = '';
        const role = String((currentUser && currentUser.profile && currentUser.profile.role) || 'superadmin').trim().toLowerCase();
        const navItems = (NAV && NAV[role]) ? NAV[role] : (NAV ? NAV.superadmin : []);

        if (!navItems || navItems.length === 0) {
            nav.innerHTML = '<div class="sb-link">No menu items available</div>';
            return;
        }
        
        let htmlContent = '';
        navItems.forEach(item => {
            if (item && item.cap) {
                const caps = (currentUser && currentUser.caps) ? currentUser.caps : {};
                if (!caps || !caps[item.cap]) {
                    return;
                }
            }
            if (item.section) {
                htmlContent += `<div class="sb-section">${item.section}</div>`;
            } else {
                htmlContent += `<div class="sb-link" onclick="loadPage('${item.page}', this, '${item.label}')"><span class="sb-icon">${safeIcon(item.icon, item.label)}</span><span class="sb-text">${item.label}</span></div>`;
            }
        });

        // Always provide a clear logout action outside Settings.
        htmlContent += `<div class="sb-section">Account</div>`;
        htmlContent += `<div class="sb-link" onclick="doLogout()"><span class="sb-icon">LO</span><span class="sb-text">Logout</span></div>`;

        nav.innerHTML = htmlContent;
        if (nav.innerHTML.length === 0) {
            nav.innerHTML = '<div class="sb-link">ERROR: Menu failed to render</div>';
        }
    } catch (e) {
        console.error('Sidebar rendering failed:', e);
        // Fallback: show error message in sidebar
        try {
            const nav = document.getElementById('sb-nav-content');
            if (nav) {
                nav.innerHTML = '<div class="sb-link" style="color:red">ERROR: Menu rendering failed</div>';
            }
        } catch {}
    }
}

async function loadPage(page, el, label) {
    // If a modal was open, close it so it doesn't "stick" when navigating.
    document.querySelectorAll('.modal-overlay.show').forEach(m => m.classList.remove('show'));
    // Close mobile sidebar when navigating.
    document.getElementById('sidebar').classList.remove('mobile-open');
    document.getElementById('sb-overlay').classList.remove('show');

    document.querySelectorAll('.sb-link').forEach(l => l.classList.remove('active'));
    if (el) el.classList.add('active');
    if (label) document.getElementById('topbar-breadcrumb').innerHTML = `<strong>${label}</strong>`;
    CURRENT_PAGE = page;

    const main = document.getElementById('main-content');
    try {
    if (page === 'dashboard') {
        const role = (currentUser.profile && currentUser.profile.role) || 'superadmin';
        const [dashboardActiveTerm, dashboardEvents] = await Promise.all([
            getActiveTermCached().catch(() => null),
            API.fetch('/events/').catch(() => []),
        ]);

        if (role === 'superadmin') {
            const [students, teachers, classes, payments, health] = await Promise.all([
              API.fetch('/students/'),
              API.fetch('/teachers/'),
              API.fetch('/classes/'),
              API.fetch('/payments/'),
              API.fetch('/api-credentials/health/').catch(() => null),
            ]);
            const total = (payments || []).reduce((sum, p) => sum + Number(p.amount || 0), 0);
            const healthSummary = (health && health.summary) ? health.summary : {};
            main.innerHTML = `
              <div class="page">
                <div class="page-hero"><div class="page-title">Super Admin Dashboard</div></div>
                ${renderSchoolCalendarBanner(dashboardActiveTerm, dashboardEvents)}
                <div class="stats stats-4">
                  <div class="stat-card"><div class="stat-num">${students.length}</div><div class="stat-label">Students</div><div class="stat-accent red"></div></div>
                  <div class="stat-card"><div class="stat-num">${teachers.length}</div><div class="stat-label">Teachers</div><div class="stat-accent gold"></div></div>
                  <div class="stat-card"><div class="stat-num">${classes.length}</div><div class="stat-label">Classes</div><div class="stat-accent blue"></div></div>
                  <div class="stat-card"><div class="stat-num">${Number(healthSummary.healthy_count || 0)}/${Number(healthSummary.total_count || 0)}</div><div class="stat-label">Healthy Providers</div><div class="stat-accent green"></div></div>
                </div>
                <div class="g21" style="grid-template-columns:1fr 420px">
                  <div class="card">
                    <div class="card-head"><div class="card-title">Control Center</div></div>
                    <div class="card-body">
                      <div class="qa-grid">
                        <button class="qa-btn" onclick="loadPage('users', null, 'User Accounts')"><span class="qi">U</span><span class="ql">Users</span></button>
                        <button class="qa-btn" onclick="loadPage('credentials', null, 'API Credentials')"><span class="qi">K</span><span class="ql">API Keys</span></button>
                        <button class="qa-btn" onclick="loadPage('auditlogs', null, 'Audit Logs')"><span class="qi">L</span><span class="ql">Audit Logs</span></button>
                        <button class="qa-btn" onclick="loadPage('finance', null, 'Payments')"><span class="qi">$</span><span class="ql">Payments</span></button>
                      </div>
                      <div style="margin-top:12px;font-size:12px;color:var(--99)">Payments total recorded: <strong style="color:var(--1a)">UGX ${fmt(total.toFixed(0))}</strong></div>
                    </div>
                  </div>
                  ${renderCredentialHealthCard(health, role)}
                </div>
              </div>`;
            return;
        }

        if (role === 'teacher') {
            const today = todayISO();
            const [students, ta, anns, mytt] = await Promise.all([
                API.fetch('/students/').catch(() => []),
                API.fetch(`/teacher-attendance/?date=${encodeURIComponent(today)}`).catch(() => []),
                API.fetch('/announcements/').catch(() => []),
                API.fetch('/timetable/mine/').catch(() => []),
            ]);
            const st = (ta && ta.length) ? ta[0] : null;
            const totalStudents = (students || []).length;

            let ttHint = 'Open timetable to see today.';
            try {
                const t = (mytt && mytt.length) ? mytt[0] : null;
                const slots = t ? (t.slots || {}) : null;
                const periods = slots ? (slots.periods || []) : [];
                const times = slots ? (slots.times || {}) : {};
                const nowP = ttCurrentPeriod(periods, times);
                ttHint = nowP ? `Current period: ${escapeHtml(String(nowP))}` : 'No current period.';
            } catch {}

            const caps = (currentUser.caps || {});
            const aiOk = !!caps.ai_tools;
            const ct = (caps.class_teacher)
                ? await API.fetch('/teachers/class-teacher/overview/').catch(() => null)
                : null;

            const upEvents = (dashboardEvents || []).slice(0, 3).map(ev => `
              <div class="ri">
                <div class="ri-info">
                  <div class="rn">${escapeHtml(ev.title || 'Event')}</div>
                  <div class="rd">${escapeHtml((ev.start_date || '').toString())}${ev.end_date ? (' to ' + escapeHtml((ev.end_date || '').toString())) : ''}</div>
                </div>
              </div>`).join('') || `<div class="sub">No upcoming events.</div>`;

            const upAn = (anns || []).filter(a => a.is_archived !== true).slice(0, 3).map(a => `
              <div class="ri">
                <div class="ri-info">
                  <div class="rn">${escapeHtml(a.title || 'Announcement')}</div>
                  <div class="rd">${escapeHtml(((a.body || '') + '').slice(0, 70))}${(a.body || '').length > 70 ? '...' : ''}</div>
                </div>
                <div class="ri-end">${a.is_pinned ? '<span class="badge green">pinned</span>' : ''}</div>
              </div>`).join('') || `<div class="sub">No announcements.</div>`;

            main.innerHTML = `
              <div class="page">
                <div class="page-hero"><div class="page-title">Teacher Dashboard</div></div>
                ${renderSchoolCalendarBanner(dashboardActiveTerm, dashboardEvents)}
                <div class="stats stats-4">
                  <div class="stat-card"><div class="stat-num">${totalStudents}</div><div class="stat-label">My Students</div><div class="stat-accent blue"></div></div>
                  <div class="stat-card"><div class="stat-num">${today}</div><div class="stat-label">Today</div><div class="stat-accent gold"></div></div>
                  <div class="stat-card"><div class="stat-num">${st ? `<span class="badge green">${escapeHtml(st.status || 'present')}</span>` : '<span class="badge">not marked</span>'}</div><div class="stat-label">My Attendance</div><div class="stat-accent green"></div></div>
                  <div class="stat-card"><div class="stat-num">${aiOk ? 'ON' : 'OFF'}</div><div class="stat-label">AI Tools</div><div class="stat-accent red"></div></div>
                </div>
                <div class="g21">
                  <div class="card">
                    <div class="card-head"><div class="card-title">Quick Actions</div></div>
                    <div class="card-body">
                      <div class="qa-grid">
                        <button class="qa-btn" onclick="loadPage('my_class', null, 'My Class')"><span class="qi">CL</span><span class="ql">Attendance</span></button>
                        <button class="qa-btn" onclick="loadPage('my_class', null, 'My Class')"><span class="qi">M</span><span class="ql">Enter Marks</span></button>
                        <button class="qa-btn" onclick="loadPage('timetable', null, 'Timetable')"><span class="qi">TT</span><span class="ql">Timetable</span></button>
                        <button class="qa-btn" onclick="loadPage('teacher_attendance', null, 'Teacher Attendance')"><span class="qi">TA</span><span class="ql">My Attendance</span></button>
                      </div>
                      <div style="margin-top:12px" class="sub">${escapeHtml(ttHint)}</div>
                      <div style="margin-top:10px;font-size:12px;color:var(--66)">Scan the Reception QR while logged in to mark your staff attendance.</div>
                    </div>
                  </div>
                  ${ct ? `
                  <div class="card">
                    <div class="card-head"><div class="card-title">Class Teacher Overview</div></div>
                    <div class="card-body">
                      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;justify-content:space-between">
                        <div>
                          <div style="font-weight:900">Class ${escapeHtml((ct.class && ct.class.level) ? ct.class.level : '-')}${(ct.class && ct.class.section) ? escapeHtml(ct.class.section) : ''}</div>
                          <div class="sub">Term ${escapeHtml(String(ct.term ? ct.term.term_number : ''))} - ${escapeHtml(String(ct.term ? ct.term.academic_year : ''))}</div>
                        </div>
                        <div style="text-align:right">
                          <div style="font-weight:900">${Number(ct.stats ? ct.stats.students : 0)} students</div>
                          <div class="sub">Class avg: ${fmt(Number(ct.stats ? ct.stats.class_average : 0).toFixed(1))}%</div>
                        </div>
                      </div>
                      <div style="height:10px"></div>
                      <div style="font-weight:900;margin-bottom:6px">Attendance (7 days)</div>
                      ${miniBarsFromTrend(ct.attendance_trend || [])}
                      <div style="height:10px"></div>
                      <div class="grid-2" style="gap:10px">
                        <div class="card" style="border-style:dashed;margin:0">
                          <div class="card-body" style="padding:10px 12px">
                            <div style="font-weight:900;margin-bottom:6px">Top</div>
                            ${(ct.top_students || []).map(s => `<div class="ri" style="padding:6px 0"><div class="ri-info"><div class="rn">${escapeHtml(s.student_name || '')}</div><div class="rd">Avg: ${fmt(Number(s.avg || 0).toFixed(1))}%</div></div></div>`).join('') || '<div class="sub">No marks yet.</div>'}
                          </div>
                        </div>
                        <div class="card" style="border-style:dashed;margin:0">
                          <div class="card-body" style="padding:10px 12px">
                            <div style="font-weight:900;margin-bottom:6px">Needs Support</div>
                            ${(ct.bottom_students || []).map(s => `<div class="ri" style="padding:6px 0"><div class="ri-info"><div class="rn">${escapeHtml(s.student_name || '')}</div><div class="rd">Avg: ${fmt(Number(s.avg || 0).toFixed(1))}%</div></div></div>`).join('') || '<div class="sub">No marks yet.</div>'}
                          </div>
                        </div>
                      </div>
                      <div style="height:10px"></div>
                      <button class="btn btn-ghost" onclick="loadPage('students', null, 'Students')">Open Students</button>
                    </div>
                  </div>` : ''}
                  <div class="card">
                    <div class="card-head"><div class="card-title">Upcoming</div></div>
                    <div class="card-body">
                      <div style="font-weight:900;margin-bottom:8px">Events</div>
                      ${upEvents}
                      <div style="height:10px"></div>
                      <div style="font-weight:900;margin-bottom:8px">Announcements</div>
                      ${upAn}
                    </div>
                  </div>
                </div>
              </div>`;
            return;
        }

        if (['admin','headteacher','deputy','dos'].includes(role)) {
            const [students, teachers, classes, health, handover] = await Promise.all([
                API.fetch('/students/'),
                API.fetch('/teachers/'),
                API.fetch('/classes/'),
                API.fetch('/api-credentials/health/').catch(() => null),
                API.fetch(`/cashbook-closes/handover/?close_date=${encodeURIComponent(todayISO())}`).catch(() => null),
            ]);
            main.innerHTML = `
              <div class="page">
                <div class="page-hero"><div class="page-title">${role === 'headteacher' ? 'Headteacher Dashboard' : role === 'dos' ? 'DOS Dashboard' : role === 'deputy' ? 'Deputy Headteacher Dashboard' : 'Admin Dashboard'}</div></div>
                ${renderSchoolCalendarBanner(dashboardActiveTerm, dashboardEvents)}
                <div class="stats stats-4">
                  <div class="stat-card"><div class="stat-num">${students.length}</div><div class="stat-label">Students</div><div class="stat-accent red"></div></div>
                  <div class="stat-card"><div class="stat-num">${teachers.length}</div><div class="stat-label">Teachers</div><div class="stat-accent gold"></div></div>
                  <div class="stat-card"><div class="stat-num">${classes.length}</div><div class="stat-label">Classes</div><div class="stat-accent blue"></div></div>
                  <div class="stat-card"><div class="stat-num">Ready</div><div class="stat-label">Promotions / Reports</div><div class="stat-accent green"></div></div>
                </div>
                ${(!classes || classes.length === 0) ? `<div class="card" style="border-left:4px solid var(--rd)"><div class="card-body"><strong>No classes configured.</strong> Add class levels before registering students. <button class="btn btn-xs btn-ghost" onclick="loadPage('classes',null,'Classes')">Open Classes</button></div></div><div style="height:12px"></div>` : ''}
                <div class="grid-2">
                  <div>
                    <div class="card"><div class="card-head"><div class="card-title">Quick Actions</div></div>
                      <div class="card-body"><div class="qa-grid">
                        <button class="qa-btn" onclick="loadPage('students', null, 'Students')"><span class="qi">S</span><span class="ql">Students</span></button>
                        <button class="qa-btn" onclick="loadPage('teachers', null, 'Teachers')"><span class="qi">T</span><span class="ql">Teachers</span></button>
                        <button class="qa-btn" onclick="loadPage('promotions', null, 'Promotions')"><span class="qi">P</span><span class="ql">Promotions</span></button>
                        <button class="qa-btn" onclick="loadPage('terms', null, 'Terms')"><span class="qi">R</span><span class="ql">Terms</span></button>
                      </div></div>
                    </div>
                    <div style="height:12px"></div>
                    <div class="card"><div class="card-head"><div class="card-title">Upcoming Events</div><button class="btn btn-xs btn-ghost" onclick="loadPage('events',null,'Events')">Manage</button></div><div class="card-body">${(dashboardEvents || []).filter(e => e.is_published).slice(0, 3).map(e => `<div class="ri"><div class="ri-info"><div class="rn">${e.title}</div><div class="rd">${e.start_date}${e.end_date ? ' -> ' + e.end_date : ''}</div></div></div>`).join('') || '<div style="color:var(--99)">No events posted yet.</div>'}</div></div>
                    <div style="height:12px"></div>
                    ${renderCashierHandoverCard(handover)}
                  </div>
                  ${renderCredentialHealthCard(health, role)}
                </div>
              </div>`;
            return;
        }

        if (role === 'parent') {
            const kids = await API.fetch('/students/mine/');
            const byClass = (kids || []).reduce((acc, s) => {
                const k = `${s.current_class_level || '-'}${s.section || ''}`.trim();
                const key = k || '-';
                if (!acc[key]) acc[key] = [];
                acc[key].push(s);
                return acc;
            }, {});
            const keys = Object.keys(byClass).sort((a, b) => a.localeCompare(b));
            const groups = keys.map(k => {
                const arr = (byClass[k] || []).slice().sort((a, b) => (`${a.first_name || ''} ${a.last_name || ''}`).localeCompare(`${b.first_name || ''} ${b.last_name || ''}`));
                const list = arr.map(s => {
                    const ct = s.class_teacher || null;
                    const ctHtml = (ct && (ct.name || ct.phone || ct.email)) ? `
                      <div class="rd">
                        <span class="badge green">Class Teacher</span>
                        ${ct.name ? ` ${escapeHtml(ct.name)}` : ''}
                        ${ct.phone ? ` · ${escapeHtml(ct.phone)}` : ''}
                        ${ct.email ? ` · ${escapeHtml(ct.email)}` : ''}
                      </div>` : '';
                    return `<div class="ri"><div class="ri-info"><div class="rn">${escapeHtml((s.first_name || '') + ' ' + (s.last_name || ''))}</div><div class="rd">${escapeHtml(s.student_id || '')}</div>${ctHtml}</div><div class="ri-end"><button class="btn btn-xs btn-ghost" onclick="openStudentHistory(${s.id})">History</button></div></div>`;
                }).join('');
                return `<div class="card" style="margin-bottom:12px"><div class="card-head"><div class="card-title">Class ${escapeHtml(k)}</div><div class="sub">${arr.length} child(ren)</div></div><div class="card-body">${list || ''}</div></div>`;
            }).join('');
            main.innerHTML = `
              <div class="page">
                <div class="page-hero"><div class="page-title">Parent Dashboard</div></div>
                ${renderSchoolCalendarBanner(dashboardActiveTerm, dashboardEvents)}
                <div class="card" style="border-left:4px solid var(--m)"><div class="card-body">
                  <div style="font-size:12px;color:var(--66)">Your parent username is your phone number: <strong style="color:var(--1a)">${escapeHtml(currentUser.username || '')}</strong>. If you have multiple children, they will all appear below.</div>
                  <div style="height:10px"></div>
                  <button class="btn btn-primary" onclick="loadPage('my_fees',null,'My Fees')">View My Fees</button>
                </div></div>
                <div style="height:12px"></div>
                ${groups || `<div class="card"><div class="card-body">No linked students found.</div></div>`}
              </div>`;
            return;
        }

        if (role === 'bursar') {
            const defYear = (dashboardActiveTerm && dashboardActiveTerm.academic_year) ? dashboardActiveTerm.academic_year : new Date().getFullYear();
            const defTerm = (dashboardActiveTerm && dashboardActiveTerm.term_number) ? dashboardActiveTerm.term_number : 1;
            const [payments, invoices, health, handover] = await Promise.all([
                API.fetch('/payments/'),
                API.fetch(`/invoices/?year=${encodeURIComponent(defYear)}&term=${encodeURIComponent(defTerm)}`).catch(() => []),
                API.fetch('/api-credentials/health/').catch(() => null),
                API.fetch(`/cashbook-closes/handover/?close_date=${encodeURIComponent(todayISO())}&cashier=${encodeURIComponent(currentUser.id)}`).catch(() => null),
            ]);
            const total = (payments || []).reduce((sum, p) => sum + Number(p.amount || 0), 0);
            const due = (invoices || []).reduce((sum, i) => sum + Number(i.amount_due || 0), 0);
            const paid = (invoices || []).reduce((sum, i) => sum + Number(i.amount_paid || 0), 0);
            const bal = Math.max(due - paid, 0);
            const extraDeadlines = [];
            if (handover && Number(handover.unresolved_promise_count || 0) > 0) {
                extraDeadlines.push({
                    title: `${handover.unresolved_promise_count} unresolved fee promise(s)`,
                    date: ((handover.unresolved_promises || [])[0] || {}).promised_for || todayISO(),
                    meta: `${handover.overdue_promise_count || 0} overdue`,
                });
            }
            main.innerHTML = `
              <div class="page">
                <div class="page-hero"><div class="page-title">Finance Dashboard</div></div>
                ${renderSchoolCalendarBanner(dashboardActiveTerm, dashboardEvents, extraDeadlines)}
                <div class="stats stats-4">
                  <div class="stat-card"><div class="stat-num">UGX ${fmt(total.toFixed(0))}</div><div class="stat-label">Payments Total</div><div class="stat-accent gold"></div></div>
                  <div class="stat-card"><div class="stat-num">${(payments||[]).length}</div><div class="stat-label">Payment Records</div><div class="stat-accent red"></div></div>
                  <div class="stat-card"><div class="stat-num">UGX ${fmt(bal.toFixed(0))}</div><div class="stat-label">Outstanding (T${defTerm}/${defYear})</div><div class="stat-accent blue"></div></div>
                  <div class="stat-card"><div class="stat-num">${(invoices||[]).filter(i=>i.status!=='paid').length}</div><div class="stat-label">Unpaid/Partial Invoices</div><div class="stat-accent green"></div></div>
                </div>
                <div class="grid-2">
                  <div>
                    <div class="card"><div class="card-head"><div class="card-title">Quick Actions</div></div>
                      <div class="card-body"><div class="qa-grid">
                        <button class="qa-btn" onclick="loadPage('finance', null, 'Payments')"><span class="qi">$</span><span class="ql">Record Payment</span></button>
                        <button class="qa-btn" onclick="loadPage('finance', null, 'Payments')"><span class="qi">H</span><span class="ql">Search History</span></button>
                        <button class="qa-btn" onclick="loadPage('cashbook', null, 'Cashbook')"><span class="qi">CB</span><span class="ql">Close Cashbook</span></button>
                        <button class="qa-btn" onclick="loadPage('fees', null, 'Fees')"><span class="qi">F</span><span class="ql">Fee Structure</span></button>
                      </div></div>
                    </div>
                    <div style="height:12px"></div>
                    ${renderCashierHandoverCard(handover)}
                  </div>
                  ${renderCredentialHealthCard(health, role)}
                </div>
              </div>`;
            return;
        }

        if (role === 'reception') {
            const [students, classes, activeTerm] = await Promise.all([
                API.fetch('/students/'),
                API.fetch('/classes/'),
                API.fetch('/terms/').catch(() => null),
            ]);
            const termLbl = (activeTerm && activeTerm.academic_year) ? `Term ${activeTerm.term_number} - ${activeTerm.academic_year}` : 'No active term';
            main.innerHTML = `
              <div class="page">
                <div class="page-hero"><div class="page-title">Reception Dashboard</div><div style="color:var(--99);font-size:12px">${termLbl}</div></div>
                ${renderSchoolCalendarBanner(activeTerm, dashboardEvents)}
                <div class="stats stats-4">
                  <div class="stat-card"><div class="stat-num">${students.length}</div><div class="stat-label">Students</div><div class="stat-accent red"></div></div>
                  <div class="stat-card"><div class="stat-num">${classes.length}</div><div class="stat-label">Classes</div><div class="stat-accent blue"></div></div>
                  <div class="stat-card"><div class="stat-num">Reports</div><div class="stat-label">Print individual reports</div><div class="stat-accent gold"></div></div>
                  <div class="stat-card"><div class="stat-num">TT</div><div class="stat-label">Timetable access</div><div class="stat-accent green"></div></div>
                </div>
                <div class="card"><div class="card-head"><div class="card-title">Quick Actions</div></div>
                  <div class="card-body"><div class="qa-grid">
                    <button class="qa-btn" onclick="loadPage('students', null, 'Students')"><span class="qi">S</span><span class="ql">Find Student</span></button>
                    <button class="qa-btn" onclick="loadPage('reportcards', null, 'Report Cards')"><span class="qi">R</span><span class="ql">Print Reports</span></button>
                    <button class="qa-btn" onclick="loadPage('timetable', null, 'Timetable')"><span class="qi">TT</span><span class="ql">Timetable</span></button>
                    <button class="qa-btn" onclick="loadPage('settings', null, 'Settings')"><span class="qi">S</span><span class="ql">Settings</span></button>
                  </div></div>
                </div>
              </div>`;
            return;
        }

        // Fallback dashboard.
        const [students, teachers, classes] = await Promise.all([API.fetch('/students/'), API.fetch('/teachers/'), API.fetch('/classes/')]);
        main.innerHTML = `
            <div class="page">
                <div class="page-hero"><div class="page-title">Dashboard</div></div>
                ${renderSchoolCalendarBanner(dashboardActiveTerm, dashboardEvents)}
                <div class="stats stats-4">
                    <div class="stat-card"><div class="stat-num">${students.length}</div><div class="stat-label">Students</div><div class="stat-accent red"></div></div>
                    <div class="stat-card"><div class="stat-num">${teachers.length}</div><div class="stat-label">Teachers</div><div class="stat-accent gold"></div></div>
                    <div class="stat-card"><div class="stat-num">${classes.length}</div><div class="stat-label">Classes</div><div class="stat-accent blue"></div></div>
                    <div class="stat-card"><div class="stat-num">OK</div><div class="stat-label">Status</div><div class="stat-accent green"></div></div>
                </div>
            </div>`;
    } else if (page === 'classes') {
        const classes = await API.fetch('/classes/');
        const role = (currentUser.profile && currentUser.profile.role) || 'superadmin';
        const canEdit = ['superadmin', 'admin'].includes(role);
        const canDelete = role === 'superadmin';
        let rows = (classes || []).map(c => `<tr>
          <td><strong>${c.level}</strong></td>
          <td>${(c.sections || []).join(', ')}</td>
          <td style="font-weight:800;color:var(--m)">UGX ${fmt(c.annual_fee)}</td>
          <td>${c.max_students_per_section || 40}</td>
          <td style="font-size:12px;color:var(--66)">${[c.teacher_a, c.teacher_b].filter(Boolean).join(' · ') || '-'}</td>
          <td>
            ${canEdit ? `<button class="btn btn-xs btn-ghost" onclick="openClassEdit(${c.id})">Edit</button>` : ''}
            ${canDelete ? `<button class="btn btn-xs btn-ghost" onclick="deleteClass(${c.id})">Delete</button>` : ''}
          </td>
        </tr>`).join('');
        main.innerHTML = `
            <div class="page">
                <div class="page-hero"><div class="page-title">Class Management</div>${canEdit ? `<button class="btn btn-primary" onclick="openClassAdd()">+ Add Class Level</button>` : ''}</div>
                <div class="card"><div class="card-body no-pad">
                  <table class="tbl">
                    <thead><tr><th>Level</th><th>Sections</th><th>Annual Fee</th><th>Max/Section</th><th>Teachers</th><th></th></tr></thead>
                    <tbody>${rows}</tbody>
                  </table>
                </div></div>
            </div>`;
    } else if (page === 'users') {
        const users = await API.fetch('/users/');
        const role = (currentUser.profile && currentUser.profile.role) || 'superadmin';
        const canDelete = role === 'superadmin';

        const normRole = (r) => (r || 'unknown').toString().trim().toLowerCase();
        const bucket = (r) => {
            r = normRole(r);
            if (r === 'teacher') return 'Teachers';
            if (r === 'student') return 'Students';
            if (r === 'parent') return 'Parents';
            if (['superadmin', 'admin', 'headteacher', 'deputy', 'dos', 'bursar', 'reception'].includes(r)) return 'Administrators';
            return 'Other';
        };
        const grouped = (users || []).reduce((acc, u) => {
            const r = u.profile ? u.profile.role : 'unknown';
            const b = bucket(r);
            if (!acc[b]) acc[b] = [];
            acc[b].push(u);
            return acc;
        }, {});

        const renderTbl = (arr) => {
            const rows = (arr || []).map(u => `<tr>
              <td><strong>${escapeHtml(u.username || '')}</strong><div class="sub">${escapeHtml(String(u.id || ''))}</div></td>
              <td>${escapeHtml((u.first_name || '') + ' ' + (u.last_name || ''))}</td>
              <td><span class="badge">${escapeHtml(u.profile ? u.profile.role : 'N/A')}</span></td>
              <td>
                <button class="btn btn-xs btn-ghost" onclick="openUserEdit(${u.id})">Edit</button>
                ${canDelete ? `<button class="btn btn-xs btn-ghost" onclick='deleteUser(${u.id}, ${JSON.stringify((u.username || '').toString())})'>Delete</button>` : ''}
              </td>
            </tr>`).join('');
            return `<div class="card"><div class="card-body no-pad"><table class="tbl"><thead><tr><th>Username</th><th>Name</th><th>Role</th><th></th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
        };

        const parts = ['Administrators', 'Teachers', 'Parents', 'Students', 'Other'].filter(k => (grouped[k] || []).length > 0).map(k => {
            const arr = (grouped[k] || []).slice().sort((a, b) => (a.username || '').localeCompare(b.username || ''));
            return `<div style="margin-bottom:12px"><div class="card"><div class="card-head"><div class="card-title">${k}</div><div class="sub">${arr.length} accounts</div></div></div>${renderTbl(arr)}</div>`;
        }).join('');

        main.innerHTML = `
            <div class="page">
                <div class="page-hero"><div class="page-title">User Accounts</div><button class="btn btn-primary" onclick="openUserAdd()">+ Create New Account</button></div>
                ${parts || '<div class="card"><div class="card-body">No users found.</div></div>'}
            </div>`;
    } else if (page === 'students') {
        const [students, classes] = await Promise.all([API.fetch('/students/'), API.fetch('/classes/').catch(() => [])]);
        const role = (currentUser.profile && currentUser.profile.role) || 'superadmin';
        const canEdit = ['superadmin', 'admin', 'reception'].includes(role);
        const canDelete = role === 'superadmin';
        const qRaw = (document.getElementById('stu-q')?.value || '').trim();
        const q = qRaw.toLowerCase();
        const clsFilter = (document.getElementById('stu-cls')?.value || '').trim();
        const classOptions = (classes || []).map(c => `<option value="${c.level}" ${clsFilter === c.level ? 'selected' : ''}>${c.level}</option>`).join('');
        const filtered = (students || []).filter(s => {
            const name = `${s.first_name || ''} ${s.last_name || ''}`.toLowerCase();
            const sid = (s.student_id || '').toLowerCase();
            const okQ = !q || name.includes(q) || sid.includes(q);
            const okC = !clsFilter || (s.current_class_level === clsFilter);
            return okQ && okC;
        });
        const grouped = (filtered || []).reduce((acc, s) => {
            const cls = (s.current_class_level || 'Unassigned') + (s.section ? s.section : '');
            if (!acc[cls]) acc[cls] = [];
            acc[cls].push(s);
            return acc;
        }, {});
        const groupsHtml = Object.keys(grouped).sort().map(cls => {
            const rows = grouped[cls].map(s => `<tr>
              <td>${s.first_name} ${s.last_name}</td>
              <td>${s.student_id}</td>
              <td><span class="badge ${s.status === 'active' ? 'green' : ''}">${s.status}</span></td>
              <td>
                <button class="btn btn-xs btn-ghost" onclick="openStudentHistory(${s.id})">History</button>
                <button class="btn btn-xs btn-ghost" onclick="printReportCardQuick(${s.id})">Report</button>
                <button class="btn btn-xs btn-ghost" onclick="resetPortals(${s.id})">Reset PW</button>
                ${canEdit ? `<button class="btn btn-xs btn-ghost" onclick="openStudentEdit(${s.id})">Edit</button><button class="btn btn-xs btn-ghost" onclick="openStudentEdit(${s.id})">Move</button>` : ''}
                ${canDelete ? `<button class="btn btn-xs btn-ghost" onclick="deleteStudent(${s.id})">Delete</button>` : ''}
              </td>
            </tr>`).join('');
            return `
              <div class="card" style="margin-bottom:12px">
                <div class="card-head"><div class="card-title">Class ${cls}</div><div style="font-size:12px;color:var(--99)">${grouped[cls].length} students</div></div>
                <div class="card-body no-pad"><table class="tbl"><thead><tr><th>Name</th><th>ID</th><th>Status</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
              </div>
            `;
        }).join('');
        main.innerHTML = `
            <div class="page">
                <div class="page-hero"><div class="page-title">Students</div>${canEdit ? `<button class="btn btn-primary" onclick="openStudentAdd()">+ Register Student</button>` : ''}</div>
                <div class="card"><div class="card-body">
                  <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                    <div class="field" style="margin:0;min-width:260px"><label>Search</label><input class="field-input" id="stu-q" placeholder="Name or ID" value="${qRaw.replace(/\"/g,'&quot;')}" oninput="loadPage('students')"></div>
                    <div class="field" style="margin:0;min-width:200px"><label>Class</label><select class="field-select" id="stu-cls" onchange="loadPage('students')"><option value=\"\">All</option>${classOptions}</select></div>
                    <button class="btn btn-ghost" onclick="document.getElementById('stu-q').value='';document.getElementById('stu-cls').value='';loadPage('students')">Reset</button>
                  </div>
                </div></div>
                <div style="height:12px"></div>
                ${groupsHtml || '<div class="card"><div class="card-body">No students found.</div></div>'}
            </div>`;
    } else if (page === 'teachers') {
        const teachers = await API.fetch('/teachers/');
        const role = (currentUser.profile && currentUser.profile.role) || 'superadmin';
        const canEdit = ['superadmin', 'admin', 'headteacher', 'deputy', 'dos'].includes(role);
        const canDelete = role === 'superadmin';
        const byCls = (teachers || []).reduce((acc, t) => {
            const k = (t.assigned_class || '').trim() || '(Unassigned)';
            if (!acc[k]) acc[k] = [];
            acc[k].push(t);
            return acc;
        }, {});
        const keys = Object.keys(byCls).sort((a, b) => a.localeCompare(b));
        const groups = keys.map(k => {
            const arr = (byCls[k] || []).slice().sort((a, b) => (`${a.first_name || ''} ${a.last_name || ''}`).localeCompare(`${b.first_name || ''} ${b.last_name || ''}`));
            const rows = arr.map(t => `<tr>
              <td><strong>${escapeHtml((t.first_name || '') + ' ' + (t.last_name || ''))}</strong><div class="sub">${escapeHtml(t.employee_id || '')}</div></td>
              <td>${escapeHtml(t.username || '-')}</td>
              <td>${t.is_class_teacher ? `<span class="badge green">Yes</span><div class="sub">Class ${escapeHtml(t.class_teacher_class_level || '-')}${t.class_teacher_section ? escapeHtml(String(t.class_teacher_section)) : ''}</div>` : `<span class="badge">No</span>`}</td>
              <td>${escapeHtml(t.phone || '-')}</td>
              <td>${escapeHtml(t.email || '-')}</td>
              <td style="font-size:12px">${(t.subjects && t.subjects.length) ? escapeHtml(t.subjects.join(', ')) : '<span class=\"sub\">No subjects</span>'}</td>
              <td>
                ${canEdit ? `<button class="btn btn-xs btn-ghost" onclick="openTeacherEdit(${t.id})">Edit</button>` : ''}
                ${canDelete ? `<button class="btn btn-xs btn-ghost" onclick="deleteTeacher(${t.id})">Delete</button>` : ''}
              </td>
            </tr>`).join('');
            return `
              <div class="card" style="margin-bottom:12px">
                <div class="card-head"><div class="card-title">${escapeHtml(k)}</div><div class="sub">${arr.length} teacher(s)</div></div>
                <div class="card-body no-pad"><div class="tw">
                  <table class="tbl">
                    <thead><tr><th>Teacher</th><th>Username</th><th>Class Teacher</th><th>Phone</th><th>Email</th><th>Subjects</th><th></th></tr></thead>
                    <tbody>${rows || ''}</tbody>
                  </table>
                </div></div>
              </div>`;
        }).join('');
        main.innerHTML = `
            <div class="page">
                <div class="page-hero"><div class="page-title">Teacher Management</div>${canEdit ? `<button class="btn btn-primary" onclick="openTeacherAdd()">+ Register Teacher</button>` : ''}</div>
                <div class="card" style="border-left:4px solid var(--m)"><div class="card-body">
                  <div style="font-size:12px;color:var(--66)">Teacher login username defaults to a readable real-name format like <strong>grace.nabwire</strong>. If a similar name already exists, the system safely adds a number such as <strong>grace.nabwire.2</strong>.</div>
                </div></div>
                <div style="height:12px"></div>
                ${groups || '<div class=\"card\"><div class=\"card-body\">No teachers found.</div></div>'}
            </div>`;
    } else if (page === 'subjects') {
        const role = (currentUser.profile && currentUser.profile.role) || 'superadmin';
        const canEdit = ['superadmin', 'admin', 'headteacher', 'deputy', 'dos', 'reception', 'bursar'].includes(role);
        const [subjects, classes, links] = await Promise.all([
            API.fetch('/subjects/'),
            API.fetch('/classes/').catch(() => []),
            API.fetch('/class-subjects/').catch(() => []),
        ]);

        const subRows = (subjects || []).slice().sort((a, b) => (a.name || '').localeCompare(b.name || '')).map(s => `
          <tr>
            <td><strong>${escapeHtml(s.name || '')}</strong><div class="sub">${escapeHtml(s.code || '')}</div></td>
            <td>${s.is_active === false ? '<span class="badge">Inactive</span>' : '<span class="badge green">Active</span>'}</td>
            <td style="font-size:12px;color:var(--66)">${s.updated_at ? String(s.updated_at).slice(0, 19).replace('T', ' ') : ''}</td>
            <td>
              ${canEdit ? `<button class="btn btn-xs btn-ghost" onclick="toggleSubjectActive(${s.id}, ${s.is_active === false ? 'true' : 'false'})">${s.is_active === false ? 'Activate' : 'Disable'}</button>` : ''}
              ${canEdit ? `<button class="btn btn-xs btn-ghost" onclick="deleteSubject(${s.id})">Delete</button>` : ''}
            </td>
          </tr>`).join('');

        const classOpts = (classes || []).map(c => `<option value="${c.id}">${escapeHtml(c.level)}</option>`).join('');
        const subjOpts = (subjects || []).filter(s => s.is_active !== false).map(s => `<option value="${s.id}">${escapeHtml(s.name)}</option>`).join('');

        const byClass = (links || []).reduce((acc, l) => {
            const cid = l.school_class;
            if (!acc[cid]) acc[cid] = [];
            acc[cid].push(l);
            return acc;
        }, {});

        const linksHtml = (classes || []).map(c => {
            const arr = (byClass[c.id] || []).slice().sort((a, b) => (a.subject_name || '').localeCompare(b.subject_name || ''));
            if (!arr.length) return '';
            const rows = arr.map(l => `<tr>
              <td>${escapeHtml(l.subject_name || '')}</td>
              <td>${Number(l.periods_per_week || 0)}</td>
              <td>${l.is_active === false ? '<span class="badge">Inactive</span>' : '<span class="badge green">Active</span>'}</td>
              <td>${canEdit ? `<button class="btn btn-xs btn-ghost" onclick="deleteClassSubject(${l.id})">Remove</button>` : ''}</td>
            </tr>`).join('');
            return `
              <div class="card" style="margin-bottom:12px">
                <div class="card-head"><div class="card-title">Class ${escapeHtml(c.level)}</div><div class="sub">${arr.length} subjects</div></div>
                <div class="card-body no-pad"><div class="tw">
                  <table class="tbl"><thead><tr><th>Subject</th><th>Periods/Week</th><th>Status</th><th></th></tr></thead><tbody>${rows}</tbody></table>
                </div></div>
              </div>`;
        }).join('') || '<div class="card"><div class="card-body">No class subjects configured yet.</div></div>';

        main.innerHTML = `
          <div class="page">
            <div class="page-hero"><div class="page-title">Subjects</div></div>

            <div class="grid-2">
              <div class="card">
                <div class="card-head"><div class="card-title">Add Subject</div></div>
                <div class="card-body">
                  <div class="field" style="margin:0 0 10px 0"><label>Name</label><input class="field-input" id="sub-name" placeholder="Mathematics"></div>
                  <div class="field" style="margin:0 0 10px 0"><label>Code (optional)</label><input class="field-input" id="sub-code" placeholder="MATH"></div>
                  <button class="btn btn-primary" onclick="createSubject()">Create</button>
                </div>
              </div>

              <div class="card">
                <div class="card-head"><div class="card-title">Attach Subject To Class</div></div>
                <div class="card-body">
                  <div class="field" style="margin:0 0 10px 0"><label>Class</label><select class="field-select" id="cs-class">${classOpts}</select></div>
                  <div class="field" style="margin:0 0 10px 0"><label>Subject</label><select class="field-select" id="cs-subject">${subjOpts}</select></div>
                  <div class="field" style="margin:0 0 10px 0"><label>Periods per week</label><input class="field-input" id="cs-ppw" type="number" value="0"></div>
                  <button class="btn btn-primary" onclick="attachSubject()">Attach</button>
                </div>
              </div>
            </div>

            <div style="height:12px"></div>
            <div class="card">
              <div class="card-head"><div class="card-title">All Subjects</div><div class="sub">${(subjects || []).length} total</div></div>
              <div class="card-body no-pad"><div class="tw">
                <table class="tbl"><thead><tr><th>Subject</th><th>Status</th><th>Updated</th><th></th></tr></thead><tbody>${subRows}</tbody></table>
              </div></div>
            </div>

            <div style="height:12px"></div>
            ${linksHtml}
          </div>`;
    } else if (page === 'my_class') {
        const role = (currentUser.profile && currentUser.profile.role) || 'admin';
        if (role !== 'teacher') {
            main.innerHTML = `<div class="page"><div class="card"><div class="card-body">Only teachers can access this page.</div></div></div>`;
            return;
        }

        const today = todayISO();
        const activeTerm = await API.fetch('/terms/').catch(() => null);
        const defYear = (activeTerm && activeTerm.academic_year) ? Number(activeTerm.academic_year) : Number(new Date().getFullYear());
        const defTerm = (activeTerm && activeTerm.term_number) ? Number(activeTerm.term_number) : 1;

        const [students, subjects] = await Promise.all([
            API.fetch('/students/').catch(() => []),
            API.fetch('/subjects/').catch(() => []),
        ]);

        const subjList = (subjects || []).filter(s => s.is_active !== false).slice().sort((a, b) => (a.name || '').localeCompare(b.name || '')).map(s => `<option value="${escapeHtml(s.name)}"></option>`).join('');
        const rows = (students || []).slice().sort((a, b) => (String(a.student_id || '')).localeCompare(String(b.student_id || ''))).map(s => `
          <tr data-stu="${s.id}">
            <td><strong>${escapeHtml((s.first_name || '') + ' ' + (s.last_name || ''))}</strong><div class="sub">${escapeHtml(s.student_id || '')}</div></td>
            <td style="width:160px">
              <select class="field-select mc-att-status">
                <option value="present">present</option>
                <option value="late">late</option>
                <option value="excused">excused</option>
                <option value="absent">absent</option>
              </select>
            </td>
            <td style="width:120px">
              <input class="field-input mc-mark-score" type="number" min="0" max="100" placeholder="0-100">
            </td>
            <td>
              <input class="field-input mc-mark-remarks" placeholder="Optional remarks">
            </td>
            <td style="width:160px">
              <button class="btn btn-xs btn-ghost" onclick="openStudentHistory(${s.id})">History</button>
            </td>
          </tr>`).join('');

        main.innerHTML = `
          <div class="page">
            <div class="page-hero"><div class="page-title">My Class</div></div>

            <div class="card" style="border-left:4px solid var(--m)"><div class="card-body">
              <div id="mc-stats" class="sub" style="margin-bottom:8px">Loading summary...</div>
              <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                <div class="field" style="margin:0;min-width:170px"><label>Date</label><input class="field-input" id="mc-date" type="date" value="${today}"></div>
                <div class="field" style="margin:0;min-width:170px"><label>Academic Year</label><input class="field-input" id="mc-year" type="number" value="${defYear}"></div>
                <div class="field" style="margin:0;min-width:140px"><label>Term</label>
                  <select class="field-select" id="mc-term">
                    <option value="1" ${defTerm === 1 ? 'selected' : ''}>Term 1</option>
                    <option value="2" ${defTerm === 2 ? 'selected' : ''}>Term 2</option>
                    <option value="3" ${defTerm === 3 ? 'selected' : ''}>Term 3</option>
                  </select>
                </div>
                <div class="field" style="margin:0;min-width:280px"><label>Subject (for marks)</label>
                  <input class="field-input" id="mc-subject" list="mc-subj-list" placeholder="e.g. Mathematics">
                  <datalist id="mc-subj-list">${subjList}</datalist>
                </div>
                <div style="flex:1"></div>
                <button class="btn btn-ghost" onclick="mcLoadAttendance()">Load Attendance</button>
                <button class="btn btn-primary" onclick="mcSaveAttendance()">Save Attendance</button>
                <button class="btn btn-ghost" onclick="mcLoadMarks()">Load Marks</button>
                <button class="btn btn-primary" onclick="mcSaveMarks()">Save Marks</button>
              </div>
              <div style="height:10px"></div>
              <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
                <div class="sub" style="font-weight:800">Attendance quick:</div>
                <button class="btn btn-xs btn-ghost" onclick="mcSetAllAttendance('present')">All present</button>
                <button class="btn btn-xs btn-ghost" onclick="mcSetAllAttendance('absent')">All absent</button>
                <button class="btn btn-xs btn-ghost" onclick="mcSetAllAttendance('late')">All late</button>
                <button class="btn btn-xs btn-ghost" onclick="mcSetAllAttendance('excused')">All excused</button>
                <div class="sub">Marks are saved per student, subject, year and term.</div>
              </div>
            </div></div>

            <div style="height:12px"></div>
            <div class="card"><div class="card-body no-pad"><div class="tw">
              <table class="tbl">
                <thead><tr><th>Student</th><th>Attendance</th><th>Score</th><th>Remarks</th><th></th></tr></thead>
                <tbody id="mc-body">${rows || ''}</tbody>
              </table>
            </div></div></div>
          </div>`;

        await mcLoadAttendance();
        setTimeout(() => { try { mcRefreshStats(); } catch {} }, 0);
        return;
    } else if (page === 'promotions') {
        const classes = await API.fetch('/classes/');
        main.innerHTML = `
            <div class="page">
                <div class="page-hero"><div class="page-title">Promotions / Failures</div></div>
                <div class="card"><div class="card-body">
                    <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                      <div class="field" style="margin:0;min-width:220px"><label>Class</label><select class="field-select" id="promo-class"></select></div>
                      <div class="field" style="margin:0;min-width:120px"><label>Section</label><input class="field-input" id="promo-sec" value="A"></div>
                      <button class="btn btn-primary" onclick="loadPromotionList()">Load Students</button>
                      <button class="btn btn-ghost" onclick="autoPromote()">Auto-Suggest</button>
                      <button class="btn btn-ghost" onclick="confirmPromotions()">Confirm</button>
                    </div>
                    <div style="margin-top:14px;overflow:auto">
                      <table class="tbl">
                        <thead><tr><th>Student</th><th>System ID</th><th>Average</th><th>Position</th><th>Decision</th><th>Notes</th></tr></thead>
                        <tbody id="promo-body"></tbody>
                      </table>
                    </div>
                </div></div>
            </div>`;
        const sel = document.getElementById('promo-class');
        sel.innerHTML = classes.map(c => `<option value="${c.id}">${c.level}</option>`).join('');
    } else if (page === 'terms') {
        const [active, all] = await Promise.all([
            API.fetch('/terms/').catch(() => null),
            API.fetch('/terms/all').catch(() => []),
        ]);
        const activeHtml = active && active.academic_year ? `<div><strong>Active:</strong> Year ${active.academic_year}, Term ${active.term_number} (${active.start_date} to ${active.end_date})</div>` : `<div><strong>Active:</strong> None</div>`;
        const role = (currentUser.profile && currentUser.profile.role) || 'admin';
        const canManage = !!(currentUser && currentUser.caps && currentUser.caps.term_manage);
        const rows = Array.isArray(all) ? all.map(t => {
            const st = t.is_archived ? '<span class="badge">Archived</span>' : '<span class="badge green">Active</span>';
            const act = (t.is_archived && role === 'superadmin') ? `<button class="btn btn-xs btn-ghost" onclick="deleteTerm(${t.id})">Delete</button>` : '';
            const mk = t.marks_locked ? `<span class="badge red">Locked</span>` : `<span class="badge green">Open</span>`;
            const mkBtn = canManage ? (t.marks_locked
              ? `<button class="btn btn-xs btn-ghost" onclick="unlockMarks(${t.id})">Unlock Marks</button>`
              : `<button class="btn btn-xs btn-ghost" onclick="lockMarks(${t.id})">Lock Marks</button>`) : '';
            return `<tr>
              <td>${t.academic_year}</td>
              <td>${t.term_number}</td>
              <td>${t.start_date}</td>
              <td>${t.end_date}</td>
              <td>${st}</td>
              <td>${mk}</td>
              <td>
                ${canManage ? `<button class="btn btn-xs btn-ghost" onclick="openTermEdit(${t.id})">Edit</button>` : ''}
                ${mkBtn}
                ${act}
              </td>
            </tr>`;
        }).join('') : '';
        main.innerHTML = ` 
            <div class="page"> 
                <div class="page-hero"><div class="page-title">Academic Terms</div>${canManage ? `<button class="btn btn-primary" onclick="openNewTermModal()">Start New Term</button>` : ''}</div> 
                <div class="card"><div class="card-body">${activeHtml}</div></div> 
                <div style="height:12px"></div> 
                <div class="card"><div class="card-body no-pad"> 
                  <table class="tbl"><thead><tr><th>Year</th><th>Term</th><th>Start</th><th>End</th><th>Status</th><th>Marks</th><th></th></tr></thead><tbody>${rows}</tbody></table> 
                </div></div> 
            </div>`; 
    } else if (page === 'reportcards') {
        const [students, classes] = await Promise.all([API.fetch('/students/'), API.fetch('/classes/')]);
        const studentOptions = students.map(s => `<option value="${s.id}">${s.first_name} ${s.last_name} (${s.student_id})</option>`).join('');
        const classOptions = classes.map(c => `<option value="${c.id}">${c.level}</option>`).join('');
        main.innerHTML = `
            <div class="page">
                <div class="page-hero"><div class="page-title">Report Cards</div></div>
                <div class="card"><div class="card-body">
                  <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                    <div class="field" style="margin:0;min-width:280px"><label>Student</label><select class="field-select" id="rc-stu">${studentOptions}</select></div> 
                    <div class="field" style="margin:0;min-width:120px"><label>Term</label><select class="field-select" id="rc-term"><option value="1">1</option><option value="2">2</option><option value="3">3</option></select></div> 
                    <div class="field" style="margin:0;min-width:120px"><label>Year</label><input class="field-input" id="rc-year" type="number" value="${new Date().getFullYear()}"></div> 
                    <button class="btn btn-primary" onclick="downloadReportCard()">Download PDF</button> 
                    <button class="btn btn-ghost" onclick="queueReportCard()">Queue For Printing</button> 
                  </div> 
                </div></div> 
                <div style="height:12px"></div>
                <div class="card"><div class="card-body">
                  <div style="font-weight:700;margin-bottom:8px">Email All Parents (by class)</div>
                  <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                    <div class="field" style="margin:0;min-width:220px"><label>Class</label><select class="field-select" id="rc-class">${classOptions}</select></div>
                    <div class="field" style="margin:0;min-width:120px"><label>Term</label><select class="field-select" id="rc-term2"><option value="1">1</option><option value="2">2</option><option value="3">3</option></select></div>
                    <div class="field" style="margin:0;min-width:120px"><label>Year</label><input class="field-input" id="rc-year2" type="number" value="${new Date().getFullYear()}"></div>
                    <button class="btn btn-ghost" onclick="emailAllParents()">Email PDFs</button>
                  </div>
                </div></div> 
            </div>`; 
    } else if (page === 'grading') { 
        const role = (currentUser.profile && currentUser.profile.role) || 'admin'; 
        if (!(role === 'superadmin' || role === 'dos')) { 
            throw { detail: 'Only DOS and Super Admin can manage grading scales.' }; 
        } 
        const [scales, classes] = await Promise.all([ 
            API.fetch('/grading-scales/').catch(() => []), 
            API.fetch('/classes/').catch(() => []), 
        ]); 
        const rows = (scales || []).map(s => `<tr> 
          <td><strong>${escapeHtml(s.name || '')}</strong>${s.is_default ? ' <span class="badge green">Default</span>' : ''}<div class="sub">${s.school_class ? 'Class-linked' : 'Global'}</div></td> 
          <td>${s.school_class ? (classes.find(c => Number(c.id) === Number(s.school_class))?.level || s.school_class) : '-'}</td> 
          <td>${gradingBandSummary(s.scale_data || [])}</td>
          <td style="white-space:nowrap"> 
            <button class="btn btn-xs btn-ghost" onclick="openGradingEdit(${s.id})">Edit</button> 
            ${s.is_default ? '' : `<button class="btn btn-xs btn-ghost" onclick="setDefaultGradingScale(${s.id})">Set Default</button>`} 
          </td> 
        </tr>`).join('') || `<tr><td colspan="4" style="color:var(--99)">No grading scales yet.</td></tr>`; 
        main.innerHTML = ` 
          <div class="page"> 
            <div class="page-hero"><div class="page-title">Grading Scales</div><button class="btn btn-primary" onclick="openGradingCreate()">New Scale</button></div> 
            <div class="grid-2">
              <div class="card"><div class="card-body"> 
                <div style="font-weight:900;margin-bottom:8px">Simple table editor</div>
                <div class="sub">Each row is one band: <strong>From score</strong>, <strong>To score</strong>, <strong>Grade</strong>, and optional <strong>Points</strong>. This powers report-card averages, grades, aggregates, and positions without touching raw JSON.</div> 
                <div class="sub" style="margin-top:8px">Example: <strong>0</strong> to <strong>30</strong> = <strong>F9</strong>. Add as many bands as you want.</div>
                <div class="help-box" style="margin-top:12px">
                  <div style="font-weight:800;margin-bottom:6px">Recommended for deployment</div>
                  <div class="sub">Keep one global default scale, then create class-specific overrides only when a class genuinely needs a different grading policy.</div>
                </div>
              </div></div> 
              <div class="card"><div class="card-body">
                <div style="font-weight:900;margin-bottom:8px">What this now supports</div>
                <div class="ri"><div class="ri-info"><div class="rn">Easy band editing</div><div class="rd">No more typing JSON by hand.</div></div></div>
                <div class="ri"><div class="ri-info"><div class="rn">Aggregate points</div><div class="rd">Points flow into report cards and merit summaries.</div></div></div>
                <div class="ri"><div class="ri-info"><div class="rn">Readable previews</div><div class="rd">You immediately see bands like 80-100 = A1.</div></div></div>
              </div></div>
            </div>
            <div style="height:12px"></div> 
            <div class="card"><div class="card-body no-pad"><div class="tw"> 
              <table class="tbl"><thead><tr><th>Scale</th><th>Class</th><th>Band Preview</th><th></th></tr></thead><tbody>${rows}</tbody></table> 
            </div></div></div> 
          </div> 
 
          <div class="modal" id="modal-grading"> 
            <div class="modal-card" style="max-width:900px"> 
              <div class="modal-head"><div style="font-weight:900">Grading Scale</div><button class="x" onclick="closeModal('modal-grading')">X</button></div> 
              <div class="modal-body"> 
                <input type="hidden" id="g-id" value=""> 
                <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end"> 
                  <div class="field" style="margin:0;min-width:260px"><label>Name</label><input class="field-input" id="g-name" placeholder="Default Scale"></div> 
                  <div class="field" style="margin:0;min-width:240px"><label>Attach to class (optional)</label><select class="field-select" id="g-class"><option value=\"\">(Global)</option>${(classes||[]).map(c=>`<option value=\"${c.id}\">${escapeHtml(c.level)}</option>`).join('')}</select></div> 
                </div> 
                <div style="height:10px"></div> 
                <div class="card"><div class="card-body no-pad"><div class="tw">
                  <table class="tbl">
                    <thead><tr><th>From</th><th>To</th><th>Grade</th><th>Points</th><th>Remark</th><th>Preview</th><th></th></tr></thead>
                    <tbody id="g-rows-body"></tbody>
                  </table>
                </div></div></div>
                <textarea id="g-json" style="display:none"></textarea>
                <div style="height:10px"></div> 
                <div style="display:flex;gap:8px;flex-wrap:wrap">
                  <button class="btn btn-ghost" onclick="addGradingRow()">+ Add Band</button>
                  <button class="btn btn-ghost" onclick="loadGradingStarter()">Load Starter</button>
                </div>
                <div class="help-box" style="margin-top:10px">
                  <div style="font-weight:800;margin-bottom:4px">Live preview</div>
                  <div id="g-preview" class="sub">Bands will appear here.</div>
                </div>
                <div style="height:10px"></div>
                <button class="btn btn-primary" onclick="saveGradingScale()">Save</button> 
              </div> 
            </div> 
          </div>`; 
    } else if (page === 'printqueue') { 
        const role = (currentUser.profile && currentUser.profile.role) || 'admin'; 
        if (!(role === 'reception' || role === 'superadmin' || role === 'admin' || role === 'headteacher' || role === 'deputy' || role === 'dos')) { 
            throw { detail: 'Permission denied.' }; 
        } 
        const statusV = (document.getElementById('pq-status')?.value) || 'queued'; 
        const kindV = (document.getElementById('pq-kind')?.value) || ''; 
        const qs = `?status=${encodeURIComponent(statusV)}&kind=${encodeURIComponent(kindV)}`; 
        const items = await API.fetch('/print-queue/' + qs).catch(() => []); 
        const rows = (items || []).slice(0, 250).map(x => { 
            const who = x.requested_by_username ? escapeHtml(x.requested_by_username) : '-'; 
            const when = formatDateTime(x.created_at); 
            const exp = formatDateTime(x.expires_at); 
            const target = x.student_name || x.teacher_name || '-'; 
            const st = x.status === 'printed' ? '<span class="badge green">Printed</span>' : (x.status === 'queued' ? '<span class="badge">Queued</span>' : `<span class="badge">${escapeHtml(x.status||'')}</span>`); 
            const sens = x.is_sensitive ? '<span class="badge red">Sensitive</span>' : ''; 
            return `<tr> 
              <td>${when}</td> 
              <td><strong>${escapeHtml(x.title || '')}</strong><div class="sub">${escapeHtml(x.kind || '')} ${sens}</div></td> 
              <td>${escapeHtml(target)}</td> 
              <td>${who}</td> 
              <td>${st}</td> 
              <td>${exp || '-'}</td> 
              <td style="white-space:nowrap"> 
                <button class="btn btn-xs btn-ghost" onclick="pqOpenPdf(${x.id})">Open</button> 
                ${x.status === 'queued' ? `<button class="btn btn-xs btn-ghost" onclick="pqMarkPrinted(${x.id})">Mark Printed</button> <button class="btn btn-xs btn-ghost" onclick="pqCancel(${x.id})">Cancel</button>` : ''} 
              </td> 
            </tr>`; 
        }).join('') || `<tr><td colspan="7" style="color:var(--99)">No items.</td></tr>`; 
 
        main.innerHTML = ` 
          <div class="page"> 
            <div class="page-hero"><div class="page-title">Print Queue</div><button class="btn btn-ghost" onclick="loadPage('printqueue')">Refresh</button></div> 
            <div class="card"><div class="card-body"> 
              <div class="sub">Unified queue for admission letters, credentials, and report cards. Sensitive items auto-expire and wipe after printing.</div> 
              <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin-top:10px"> 
                <div class="field" style="margin:0;min-width:160px"><label>Status</label> 
                  <select class="field-select" id="pq-status" onchange="loadPage('printqueue')"> 
                    <option value="queued">Queued</option> 
                    <option value="printed">Printed</option> 
                    <option value="cancelled">Cancelled</option> 
                    <option value="expired">Expired</option> 
                  </select> 
                </div> 
                <div class="field" style="margin:0;min-width:220px"><label>Kind</label> 
                  <select class="field-select" id="pq-kind" onchange="loadPage('printqueue')"> 
                    <option value="">All</option> 
                    <option value="admission_letter">Admission Letter</option> 
                    <option value="parent_credentials">Parent Credentials</option> 
                    <option value="student_credentials">Student Credentials</option> 
                    <option value="mail_merge_letter">Mail Merge Letter</option> 
                    <option value="teacher_credentials">Teacher Credentials</option> 
                    <option value="staff_credentials">Staff Credentials</option> 
                    <option value="report_card">Report Card</option> 
                  </select> 
                </div> 
              </div> 
            </div></div> 
            <div style="height:12px"></div> 
            <div class="card"><div class="card-body no-pad"><div class="tw"> 
              <table class="tbl"><thead><tr><th>Created</th><th>Item</th><th>Target</th><th>Requested By</th><th>Status</th><th>Expires</th><th></th></tr></thead><tbody>${rows}</tbody></table> 
            </div></div></div> 
          </div>`; 
        const stEl = document.getElementById('pq-status'); 
        const kdEl = document.getElementById('pq-kind'); 
        if (stEl) stEl.value = statusV; 
        if (kdEl) kdEl.value = kindV; 
    } else if (page === 'printdesk') { 
        const role = (currentUser.profile && currentUser.profile.role) || 'admin'; 
        if (!(role === 'reception' || role === 'superadmin')) { 
            throw { detail: 'Only reception/superadmin can access Print Desk.' }; 
        }
        const [drafts, exams] = await Promise.all([
            API.fetch('/document-drafts/').catch(() => []),
            API.fetch('/exam-papers/').catch(() => []),
        ]);
        const submitted = (drafts || []).filter(d => d.status === 'submitted').slice(0, 200);
        const printed = (drafts || []).filter(d => d.status === 'printed').slice(0, 120);
        const rows = submitted.map(d => `<tr>
          <td>${formatDateTime(d.submitted_at, '-')}</td>
          <td><strong>${escapeHtml(d.title || '')}</strong><div class="sub">${escapeHtml(d.kind || '')}</div></td>
          <td>${escapeHtml(d.created_by_username || '')}</td>
          <td>${escapeHtml(d.school_class_level || '-')}</td>
          <td>${escapeHtml(d.subject_name || '-')}</td>
          <td>
            <button class="btn btn-xs btn-ghost" onclick="openDocModalFromId(${d.id})">View</button>
            <button class="btn btn-xs btn-ghost" onclick="markDocPrinted(${d.id})">Mark Printed</button>
          </td>
        </tr>`).join('');

        const printedRows = (printed || []).map(d => `<tr>
          <td>${formatDateTime(d.printed_at, '-')}</td>
          <td><strong>${escapeHtml(d.title || '')}</strong><div class="sub">${escapeHtml(d.kind || '')}</div></td>
          <td>${escapeHtml(d.created_by_username || '')}</td>
          <td>${escapeHtml(d.printed_by_username || '-') }</td>
          <td><button class="btn btn-xs btn-ghost" onclick="openDocModalFromId(${d.id})">Reprint</button></td>
        </tr>`).join('') || `<tr><td colspan="5" style="color:var(--99)">No printed drafts yet.</td></tr>`;

        const exSubmitted = (exams || []).filter(x => x.status === 'submitted').slice(0, 200);
        const exPrinted = (exams || []).filter(x => x.status === 'printed').slice(0, 120);

        const exRows = exSubmitted.map(x => `<tr>
          <td>${formatDateTime(x.submitted_at, '-')}</td>
          <td><strong>${escapeHtml(x.title || '')}</strong><div class="sub">${escapeHtml(x.description || '')}</div></td>
          <td>${escapeHtml(x.teacher_name || '-')}</td>
          <td>${escapeHtml(x.school_class_level || '-')} ${escapeHtml(x.section || '')}</td>
          <td>${escapeHtml(x.subject_name || '-')}</td>
          <td>
            <a class="btn btn-xs btn-ghost" href="${escapeHtml(x.file_url)}" target="_blank" rel="noopener">Open File</a>
            <button class="btn btn-xs btn-ghost" onclick="markExamPrinted(${x.id})">Mark Printed</button>
          </td>
        </tr>`).join('');

        const exPrintedRows = exPrinted.map(x => `<tr>
          <td>${formatDateTime(x.printed_at, '-')}</td>
          <td><strong>${escapeHtml(x.title || '')}</strong></td>
          <td>${escapeHtml(x.teacher_name || '-')}</td>
          <td>${escapeHtml(x.printed_by_username || '-') }</td>
          <td><a class="btn btn-xs btn-ghost" href="${escapeHtml(x.file_url)}" target="_blank" rel="noopener">Reprint</a></td>
        </tr>`).join('') || `<tr><td colspan="5" style="color:var(--99)">No printed exams yet.</td></tr>`;
        main.innerHTML = `
          <div class="page">
            <div class="page-hero"><div class="page-title">Print Desk</div><button class="btn btn-ghost" onclick="loadPage('printdesk')">Refresh</button></div>
            <div class="card"><div class="card-body">
              <div style="font-weight:800;color:var(--md)">Queue</div>
              <div class="sub">Teachers submit drafts and exam files here. Reception prints and marks as printed.</div>
            </div></div>
            <div style="height:12px"></div>
            <div class="card"><div class="card-body">
              <div style="font-weight:900;margin-bottom:6px">Teacher Drafts</div>
              <div class="sub">AI tools and teacher drafts submitted for printing.</div>
              <div class="sub" style="margin-top:6px">Queue: ${submitted.length} | Printed (recent): ${printed.length}</div>
            </div></div>
            <div class="card"><div class="card-body no-pad"><div class="tw">
              <table class="tbl"><thead><tr><th>Submitted</th><th>Document</th><th>Teacher</th><th>Class</th><th>Subject</th><th></th></tr></thead><tbody>${rows || ''}</tbody></table>
            </div></div></div>

            <div style="height:12px"></div>
            <div class="card"><div class="card-body">
              <div style="font-weight:900;margin-bottom:6px">Printed Drafts (Recent)</div>
              <div class="sub">Print logs with reprint control.</div>
            </div></div>
            <div class="card"><div class="card-body no-pad"><div class="tw">
              <table class="tbl"><thead><tr><th>Printed</th><th>Document</th><th>Teacher</th><th>Printed By</th><th></th></tr></thead><tbody>${printedRows}</tbody></table>
            </div></div></div>

            <div style="height:12px"></div>
            <div class="card"><div class="card-body">
              <div style="font-weight:900;margin-bottom:6px">Exam Papers</div>
              <div class="sub">Teacher-uploaded PDFs/DOCX to print.</div>
              <div class="sub" style="margin-top:6px">Queue: ${exSubmitted.length} | Printed (recent): ${exPrinted.length}</div>
            </div></div>
            <div class="card"><div class="card-body no-pad"><div class="tw">
              <table class="tbl"><thead><tr><th>Submitted</th><th>Exam</th><th>Teacher</th><th>Class</th><th>Subject</th><th></th></tr></thead><tbody>${exRows || ''}</tbody></table>
            </div></div></div>

            <div style="height:12px"></div>
            <div class="card"><div class="card-body">
              <div style="font-weight:900;margin-bottom:6px">Printed Exams (Recent)</div>
              <div class="sub">Print logs with reprint control.</div>
            </div></div>
            <div class="card"><div class="card-body no-pad"><div class="tw">
              <table class="tbl"><thead><tr><th>Printed</th><th>Exam</th><th>Teacher</th><th>Printed By</th><th></th></tr></thead><tbody>${exPrintedRows}</tbody></table>
            </div></div></div>
          </div>`;
    } else if (page === 'exams') {
        const role = (currentUser.profile && currentUser.profile.role) || 'admin';
        if (role !== 'teacher') throw { detail: 'Only teachers can upload exams.' };
        const [classes, subjects, mine] = await Promise.all([
            API.fetch('/classes/').catch(() => []),
            API.fetch('/subjects/').catch(() => []),
            API.fetch('/exam-papers/').catch(() => []),
        ]);
        const classOpts = (classes || []).map(c => `<option value="${c.id}">${escapeHtml(c.level)}</option>`).join('');
        const subjOpts = (subjects || []).filter(s => s.is_active !== false).map(s => `<option value="${s.id}">${escapeHtml(s.name)}</option>`).join('');
        const rows = (mine || []).slice(0, 80).map(x => `<tr>
          <td>${formatDateTime(x.created_at)}</td>
          <td><strong>${escapeHtml(x.title || '')}</strong><div class="sub">${escapeHtml(x.status || '')}</div></td>
          <td>${escapeHtml(x.school_class_level || '-')} ${escapeHtml(x.section || '')}</td>
          <td>${escapeHtml(x.subject_name || '-')}</td>
          <td>
            <a class="btn btn-xs btn-ghost" href="${escapeHtml(x.file_url)}" target="_blank" rel="noopener">Open</a>
            ${x.status === 'draft' ? `<button class="btn btn-xs btn-ghost" onclick="submitExam(${x.id})">Submit To Reception</button>` : ''}
          </td>
        </tr>`).join('');

        main.innerHTML = `
          <div class="page">
            <div class="page-hero"><div class="page-title">Exams Upload</div></div>
            <div class="card"><div class="card-body">
              <div style="font-weight:900;margin-bottom:8px">Upload Exam Paper</div>
              <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                <div class="field" style="margin:0;min-width:260px"><label>Title</label><input class="field-input" id="ex-title" placeholder="P.5 Maths Midterm"></div>
                <div class="field" style="margin:0;min-width:220px"><label>Class</label><select class="field-select" id="ex-class"><option value=\"\">(optional)</option>${classOpts}</select></div>
                <div class="field" style="margin:0;min-width:120px"><label>Section</label><input class="field-input" id="ex-sec" placeholder="A (optional)"></div>
                <div class="field" style="margin:0;min-width:220px"><label>Subject</label><select class="field-select" id="ex-subj"><option value=\"\">(optional)</option>${subjOpts}</select></div>
              </div>
              <div style="height:10px"></div>
              <div class="field" style="margin:0"><label>Description (optional)</label><input class="field-input" id="ex-desc" placeholder="Instructions, time allowed, etc."></div>
              <div style="height:10px"></div>
              <input type="hidden" id="ex-file-url" value="">
              <input type="file" id="ex-file" accept=\"application/pdf,.pdf,application/msword,.doc,application/vnd.openxmlformats-officedocument.wordprocessingml.document,.docx\" style="display:none">
              <div class="dropzone" id="ex-drop">
                <div style="font-weight:800">Click or drop a PDF/DOCX</div>
                <div class="sub">Max 10MB. After upload, reception can print.</div>
              </div>
              <div id="ex-file-wrap" style="display:none;margin-top:10px">
                <div class="card" style="border-style:dashed"><div class="card-body" style="padding:12px 14px;display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap">
                  <div>
                    <div style="font-weight:900">File ready</div>
                    <div class="sub"><a id="ex-file-link" href="#" target="_blank" rel="noopener">Open uploaded file</a></div>
                  </div>
                  <button class="btn btn-xs btn-ghost" onclick="clearExamFile()">Remove</button>
                </div></div>
              </div>
              <div style="height:10px"></div>
              <button class="btn btn-primary" onclick="saveExam()">Save Exam</button>
            </div></div>

            <div style="height:12px"></div>
            <div class="card"><div class="card-head"><div class="card-title">My Uploaded Exams</div></div>
              <div class="card-body no-pad"><div class="tw">
                <table class="tbl"><thead><tr><th>Created</th><th>Exam</th><th>Class</th><th>Subject</th><th></th></tr></thead><tbody>${rows || ''}</tbody></table>
              </div></div>
            </div>
          </div>`;
        setTimeout(() => { try { wireExamUpload(); } catch {} }, 0);
    } else if (page === 'ai_tools') {
        const role = (currentUser.profile && currentUser.profile.role) || 'admin';
        if (role !== 'teacher') throw { detail: 'AI Tools are for teachers only.' };
        if (!(currentUser && currentUser.caps && currentUser.caps.ai_tools)) {
            main.innerHTML = `
              <div class="page">
                <div class="page-hero"><div class="page-title">AI Tools</div></div>
                <div class="card" style="border-left:4px solid var(--or)"><div class="card-body">
                  <strong>AI Tools are not available.</strong>
                  <div class="sub" style="margin-top:6px">Super Admin must enable AI Tools and verify an AI key (OpenAI or Gemini).</div>
                </div></div>
              </div>`;
            return;
        }

        const [classes, subjects, drafts] = await Promise.all([
            API.fetch('/classes/').catch(() => []),
            API.fetch('/subjects/').catch(() => []),
            API.fetch('/document-drafts/').catch(() => []),
        ]);
        const classOpts = (classes || []).map(c => `<option value="${c.id}">${escapeHtml(c.level)}</option>`).join('');
        const subjOpts = (subjects || []).filter(s => s.is_active !== false).map(s => `<option value="${s.id}">${escapeHtml(s.name)}</option>`).join('');

        const my = (drafts || []).slice(0, 40);
        const rows = my.map(d => `<tr>
          <td>${formatDateTime(d.created_at)}</td>
          <td><strong>${escapeHtml(d.title || '')}</strong><div class="sub">${escapeHtml(d.kind || '')} · ${escapeHtml(d.status || '')}</div></td>
          <td>${escapeHtml(d.school_class_level || '-')}</td>
          <td>${escapeHtml(d.subject_name || '-')}</td>
          <td>
            <button class="btn btn-xs btn-ghost" onclick="openDocModalFromId(${d.id})">View</button>
            ${d.status === 'draft' ? `<button class="btn btn-xs btn-ghost" onclick="submitDraft(${d.id})">Submit</button>` : ''}
          </td>
        </tr>`).join('');

        main.innerHTML = `
          <div class="page">
            <div class="page-hero"><div class="page-title">AI Tools (Teacher)</div></div>
            <div class="grid-2">
              <div class="card">
                <div class="card-head"><div class="card-title">Generate Draft</div><div class="sub">Creates a draft only. Nothing is auto-printed.</div></div>
                <div class="card-body">
                  <div class="field" style="margin:0 0 10px 0"><label>Kind</label>
                    <select class="field-select" id="ai-kind"><option value="test">Test</option><option value="exam">Exam</option><option value="notes">Notes</option></select>
                  </div>
                  <div class="field" style="margin:0 0 10px 0"><label>Title</label><input class="field-input" id="ai-title" placeholder="P.5 Mathematics Test"></div>
                  <div class="field" style="margin:0 0 10px 0"><label>Class (optional)</label><select class="field-select" id="ai-class"><option value="">None</option>${classOpts}</select></div>
                  <div class="field" style="margin:0 0 10px 0"><label>Subject (optional)</label><select class="field-select" id="ai-subject"><option value="">None</option>${subjOpts}</select></div>
                  <div class="field" style="margin:0 0 10px 0"><label>Instructions</label><textarea class="field-input" id="ai-ins" style="min-height:120px" placeholder="Topic, number of questions, difficulty, marking guide, etc."></textarea></div>
                  <button class="btn btn-primary" onclick="aiGenerateDraft()">Generate</button>
                </div>
              </div>
              <div class="card">
                <div class="card-head"><div class="card-title">My Drafts</div></div>
                <div class="card-body no-pad"><div class="tw">
                  <table class="tbl"><thead><tr><th>Created</th><th>Document</th><th>Class</th><th>Subject</th><th></th></tr></thead><tbody>${rows || ''}</tbody></table>
                </div></div>
              </div>
            </div>
          </div>`;
    } else if (page === 'communications') {
        const role = (currentUser.profile && currentUser.profile.role) || 'admin';
        const allowed = ['teacher', 'reception', 'superadmin', 'admin', 'headteacher', 'deputy', 'dos'];
        if (!allowed.includes(role)) throw { detail: 'Only staff roles can manage communications.' };

        const [drafts, campaigns] = await Promise.all([
            API.fetch('/document-drafts/').catch(() => []),
            API.fetch('/communication-campaigns/').catch(() => []),
        ]);
        const communicationKinds = ['letter', 'notice', 'message'];
        const items = (drafts || []).filter(d => communicationKinds.includes(String(d.kind || '').toLowerCase())).slice(0, 160);
        const publishedTemplates = items.filter(d => String(d.workflow_status || '').toLowerCase() === 'published').slice(0, 16);
        const workingTemplates = items.filter(d => String(d.workflow_status || '').toLowerCase() !== 'published').slice(0, 18);
        const recentCampaigns = (campaigns || []).slice(0, 12);
        const publishedHtml = publishedTemplates.map(d => `
          <button class="comms-library-item" onclick="launchCommunicationEditor({ id: ${d.id} })">
            <div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start">
              <div class="comms-library-item-title">${escapeHtml(d.title || 'Untitled template')}</div>
              ${communicationWorkflowPill(d.workflow_status)}
            </div>
            <div style="display:flex;gap:6px;flex-wrap:wrap">${communicationScopePill(d.library_scope)}<span class="comms-pill scope">${escapeHtml(d.kind || 'template')}</span></div>
            <div class="comms-library-item-meta">${escapeHtml(d.school_class_level || 'Whole school')} · v${Number(d.version_number || 1)} · ${escapeHtml(d.created_by_username || '-')}</div>
          </button>`).join('') || `<div class="sub">No published templates yet. Publish a document from the editor and it will appear here for Announcements, Events, and campaigns.</div>`;
        const workingHtml = workingTemplates.map(d => `
          <button class="comms-library-item" onclick="launchCommunicationEditor({ id: ${d.id} })">
            <div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start">
              <div class="comms-library-item-title">${escapeHtml(d.title || 'Untitled draft')}</div>
              ${communicationWorkflowPill(d.workflow_status)}
            </div>
            <div class="comms-library-item-meta">${escapeHtml(d.kind || 'template')} · ${escapeHtml(d.school_class_level || 'No class')} · ${formatDateTime(d.updated_at || d.created_at)}</div>
          </button>`).join('') || `<div class="sub">No working drafts yet. Start from a template card and continue in the full editor.</div>`;
        const starterCards = COMMUNICATION_STARTER_TEMPLATES.map(t => `
          <button class="comms-action-card" onclick="launchCommunicationEditor({ starterKey: '${t.key}' })">
            <div class="badge">${escapeHtml(t.kind)}</div>
            <h3>${escapeHtml(t.label)}</h3>
            <p>${escapeHtml(t.summary)}</p>
            <div style="display:flex;gap:6px;flex-wrap:wrap">${communicationScopePill(t.library_scope)}</div>
          </button>`).join('');
        const campaignHtml = recentCampaigns.map(c => `
          <div class="comms-campaign-card">
            <div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
              <div class="title">${escapeHtml(c.document_title || 'Campaign')}</div>
              ${communicationCampaignPill(c.status)}
            </div>
            <div class="meta">${escapeHtml((c.channel || 'email').toUpperCase())} · ${formatDateTime(c.scheduled_for)} · ${escapeHtml(c.school_class_level || c.student_name || c.audience || 'Targeted')}</div>
            <div class="sub" style="margin:0 0 8px 0">Sent ${Number(c.sent_count || 0)} · Failed ${Number(c.failed_count || 0)} · Skipped ${Number(c.skipped_count || 0)}</div>
            <div class="comms-actions">
              <button class="btn btn-xs btn-ghost" onclick="openCommunicationCampaignReport(${c.id})">Report</button>
              <button class="btn btn-xs btn-ghost" onclick="runCommunicationCampaign(${c.id})">Run now</button>
              <button class="btn btn-xs btn-ghost" onclick="cancelCommunicationCampaign(${c.id})">Cancel</button>
            </div>
          </div>`).join('') || `<div class="sub">No scheduled campaigns yet.</div>`;

        main.innerHTML = `
          <div class="page">
            <div class="comms-hero page-hero">
              <div class="comms-hero-copy">
                <div class="comms-hero-kicker">Communications Studio</div>
                <div class="page-title">Templates, Campaigns & Mail Merge</div>
                <div class="sub" style="margin-top:8px;font-size:13px">Pick a starter, open a saved template, or review campaigns here. The full editor now opens on its own page so writing documents feels more like a proper workspace and less like a squeezed sidebar tool.</div>
              </div>
              <div class="comms-actions">
                <button class="btn btn-primary" onclick="launchCommunicationEditor()">Open Full Editor</button>
                <button class="btn btn-ghost" onclick="launchCommunicationEditor({ starterKey: 'fee-defaulter-reminder' })">Fee Reminder</button>
                <button class="btn btn-ghost" onclick="launchCommunicationEditor({ starterKey: 'welcome-parent-email' })">Welcome Email</button>
                <button class="btn btn-ghost" onclick="loadPage('delivery_logs', null, 'Delivery Logs')">Delivery Logs</button>
              </div>
            </div>
            <div class="comms-home-grid">
              <div class="comms-column">
                <div class="card">
                  <div class="card-head"><div class="card-title">Start With a Template</div><div class="sub">Open one in the dedicated editor</div></div>
                  <div class="card-body"><div class="comms-action-grid">${starterCards}</div></div>
                </div>
                <div class="card">
                  <div class="card-head"><div class="card-title">Published Library</div><div class="sub">Approved templates available across the system</div></div>
                  <div class="card-body"><div class="comms-library">${publishedHtml}</div></div>
                </div>
                <div class="card">
                  <div class="card-head"><div class="card-title">Working Drafts</div><div class="sub">Continue editing without losing context</div></div>
                  <div class="card-body"><div class="comms-library">${workingHtml}</div></div>
                </div>
              </div>
              <div class="comms-column">
                <div class="help-box">
                  <strong style="display:block;color:var(--md);margin-bottom:6px">How this now works</strong>
                  <div class="sub">1. Choose a starter or saved template here.</div>
                  <div class="sub">2. The full editor opens on its own page with room for formatting and mail merge.</div>
                  <div class="sub">3. Save, approve, publish, print, email, or schedule campaigns from there.</div>
                </div>
                <div class="card">
                  <div class="card-head"><div class="card-title">Recent Campaigns</div><div class="sub">Delivery visibility and retries</div></div>
                  <div class="card-body"><div class="comms-campaign-list">${campaignHtml}</div></div>
                </div>
              </div>
            </div>
          </div>`;
    } else if (page === 'communications_editor') {
        const role = (currentUser.profile && currentUser.profile.role) || 'admin';
        const allowed = ['teacher', 'reception', 'superadmin', 'admin', 'headteacher', 'deputy', 'dos'];
        if (!allowed.includes(role)) throw { detail: 'Only staff roles can manage communications.' };

        const [classes, students, drafts, campaigns] = await Promise.all([
            API.fetch('/classes/').catch(() => []),
            API.fetch('/students/').catch(() => []),
            API.fetch('/document-drafts/').catch(() => []),
            API.fetch('/communication-campaigns/').catch(() => []),
        ]);
        const communicationKinds = ['letter', 'notice', 'message'];
        const items = (drafts || []).filter(d => communicationKinds.includes(String(d.kind || '').toLowerCase())).slice(0, 160);
        const publishedTemplates = items.filter(d => String(d.workflow_status || '').toLowerCase() === 'published').slice(0, 16);
        const workingTemplates = items.filter(d => String(d.workflow_status || '').toLowerCase() !== 'published').slice(0, 18);
        const recentCampaigns = (campaigns || []).slice(0, 12);
        const classOpts = (classes || []).map(c => `<option value="${c.id}">${escapeHtml(c.level)}</option>`).join('');
        const stuOpts = groupedStudentOptions(students || []);
        const scopeOpts = communicationLibraryOptionsHtml(role, communicationDefaultLibraryScope(role));
        const headerOpts = COMMUNICATION_HEADER_PRESETS.map(opt => `<option value="${opt.value}">${escapeHtml(opt.label)}</option>`).join('');
        const footerOpts = COMMUNICATION_FOOTER_PRESETS.map(opt => `<option value="${opt.value}">${escapeHtml(opt.label)}</option>`).join('');
        const publishedHtml = publishedTemplates.map(d => `
          <button class="comms-library-item" onclick="launchCommunicationEditor({ id: ${d.id} })">
            <div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start">
              <div class="comms-library-item-title">${escapeHtml(d.title || 'Untitled template')}</div>
              ${communicationWorkflowPill(d.workflow_status)}
            </div>
            <div style="display:flex;gap:6px;flex-wrap:wrap">${communicationScopePill(d.library_scope)}<span class="comms-pill scope">${escapeHtml(d.kind || 'template')}</span></div>
            <div class="comms-library-item-meta">${escapeHtml(d.school_class_level || 'Whole school')} · v${Number(d.version_number || 1)} · ${escapeHtml(d.created_by_username || '-')}</div>
          </button>`).join('') || `<div class="sub">No published templates yet. Publish a letter in this workspace and it becomes available to Announcements and Events.</div>`;
        const workingHtml = workingTemplates.map(d => `
          <button class="comms-library-item" onclick="launchCommunicationEditor({ id: ${d.id} })">
            <div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start">
              <div class="comms-library-item-title">${escapeHtml(d.title || 'Untitled draft')}</div>
              ${communicationWorkflowPill(d.workflow_status)}
            </div>
            <div class="comms-library-item-meta">${escapeHtml(d.kind || 'template')} · ${escapeHtml(d.school_class_level || 'No class')} · ${formatDateTime(d.updated_at || d.created_at)}</div>
          </button>`).join('') || `<div class="sub">No working drafts yet. Start from the editor and your drafts will appear here.</div>`;
        const starterHtml = COMMUNICATION_STARTER_TEMPLATES.map(t => `
          <button class="comms-library-item" onclick="launchCommunicationEditor({ starterKey: '${t.key}' })">
            <div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start">
              <div class="comms-library-item-title">${escapeHtml(t.label)}</div>
              ${communicationScopePill(t.library_scope)}
            </div>
            <div class="sub" style="margin:0">${escapeHtml(t.summary)}</div>
            <div class="comms-library-item-meta">${escapeHtml(t.kind)} starter · opens in the editor for customization</div>
          </button>`).join('');
        const campaignHtml = recentCampaigns.map(c => `
          <div class="comms-campaign-card">
            <div style="display:flex;justify-content:space-between;gap:10px;align-items:flex-start">
              <div class="title">${escapeHtml(c.document_title || 'Campaign')}</div>
              ${communicationCampaignPill(c.status)}
            </div>
            <div class="meta">${escapeHtml((c.channel || 'email').toUpperCase())} · ${formatDateTime(c.scheduled_for)} · ${escapeHtml(c.school_class_level || c.student_name || c.audience || 'Targeted')}</div>
            <div class="sub" style="margin:0 0 8px 0">Sent ${Number(c.sent_count || 0)} · Failed ${Number(c.failed_count || 0)} · Skipped ${Number(c.skipped_count || 0)}</div>
            <div class="comms-actions">
              <button class="btn btn-xs btn-ghost" onclick="openCommunicationCampaignReport(${c.id})">Report</button>
              <button class="btn btn-xs btn-ghost" onclick="runCommunicationCampaign(${c.id})">Run now</button>
              <button class="btn btn-xs btn-ghost" onclick="cancelCommunicationCampaign(${c.id})">Cancel</button>
            </div>
          </div>`).join('') || `<div class="sub">No scheduled campaigns yet.</div>`;
        const canApprove = communicationCanApprove(role);

        main.innerHTML = `
          <div class="page">
            <div class="comms-hero page-hero">
              <div class="comms-hero-copy">
                <div class="comms-hero-kicker">Communications Studio</div>
                <div class="page-title">Communication Editor</div>
                <div class="sub" style="margin-top:8px;font-size:13px">This is the full-page editor for letters, notices, SMS, and email templates. Save here, then reuse the approved versions across Announcements, Events, registration messages, and finance reminders.</div>
              </div>
              <div class="comms-actions">
                <button class="btn btn-ghost" onclick="loadPage('communications', null, 'Communications')">Back to Library</button>
                <button class="btn btn-ghost" onclick="launchCommunicationEditor({ starterKey: 'welcome-parent-email' })">Load Welcome Email</button>
                <button class="btn btn-ghost" onclick="launchCommunicationEditor({ starterKey: 'fee-defaulter-reminder' })">Load Fee Reminder</button>
                <button class="btn btn-ghost" onclick="loadPage('delivery_logs', null, 'Delivery Logs')">Delivery Logs</button>
              </div>
            </div>
            <div class="comms-editor-layout comms-editor-page">
              <div class="comms-column">
                <div class="comms-studio">
                  <div class="comms-studio-head">
                    <div>
                      <div class="card-title" style="font-size:18px">Document Editor</div>
                      <div class="meta">The header, footer, signature block, and school stamp are applied during preview, print, email, campaigns, and template-driven announcements or events.</div>
                    </div>
                    <div id="cm-status-chip">${communicationWorkflowPill('draft')}</div>
                  </div>

                  <div style="padding:18px 20px 10px">
                    <input type="hidden" id="cm-id" value="">
                    <div class="comms-data-grid" style="margin-bottom:12px">
                      <div class="field" style="margin:0"><label>Template type</label>
                        <select class="field-select" id="cm-kind">
                          <option value="letter">Letter</option>
                          <option value="notice">Notice</option>
                          <option value="message">Message</option>
                        </select>
                      </div>
                      <div class="field" style="margin:0"><label>Title / subject</label><input class="field-input" id="cm-title" placeholder="Fee reminder for {student_name}"></div>
                      <div class="field" style="margin:0"><label>Class target</label><select class="field-select" id="cm-class"><option value="">Whole school / manual target</option>${classOpts}</select></div>
                      <div class="field" style="margin:0"><label>Single student</label><select class="field-select" id="cm-student"><option value="">Choose one student for preview or delivery</option>${stuOpts}</select></div>
                      <div class="field" style="margin:0"><label>Audience</label><select class="field-select" id="cm-audience"><option value="guardians">Parents / guardians</option><option value="students">Students</option></select></div>
                      <div class="field" style="margin:0"><label>Library scope</label><select class="field-select" id="cm-library-scope">${scopeOpts}</select></div>
                      <div class="field" style="margin:0"><label>Header preset</label><select class="field-select" id="cm-header">${headerOpts}</select></div>
                      <div class="field" style="margin:0"><label>Footer preset</label><select class="field-select" id="cm-footer">${footerOpts}</select></div>
                    </div>
                    <div style="display:flex;gap:14px;flex-wrap:wrap;align-items:center">
                      <label style="display:flex;gap:8px;align-items:center"><input type="checkbox" id="cm-signature" checked> Include signature block</label>
                      <label style="display:flex;gap:8px;align-items:center"><input type="checkbox" id="cm-stamp" checked> Include school stamp placeholder</label>
                    </div>
                  </div>

                  <div class="comms-toolbar">
                    <div class="comms-toolgroup">
                      <span class="comms-toolgroup-label">Edit</span>
                      <button class="btn btn-xs btn-ghost" type="button" onclick="execCommunicationCommand('undo')">Undo</button>
                      <button class="btn btn-xs btn-ghost" type="button" onclick="execCommunicationCommand('redo')">Redo</button>
                      <button class="btn btn-xs btn-ghost" type="button" onclick="execCommunicationCommand('cut')">Cut</button>
                      <button class="btn btn-xs btn-ghost" type="button" onclick="execCommunicationCommand('copy')">Copy</button>
                      <button class="btn btn-xs btn-ghost" type="button" onclick="execCommunicationCommand('pasteText')">Paste</button>
                    </div>
                    <div class="comms-toolgroup">
                      <span class="comms-toolgroup-label">Style</span>
                      <button class="btn btn-xs btn-ghost" type="button" onclick="execCommunicationCommand('bold')"><strong>B</strong></button>
                      <button class="btn btn-xs btn-ghost" type="button" onclick="execCommunicationCommand('italic')"><em>I</em></button>
                      <button class="btn btn-xs btn-ghost" type="button" onclick="execCommunicationCommand('underline')"><u>U</u></button>
                      <button class="btn btn-xs btn-ghost" type="button" onclick="execCommunicationCommand('strikeThrough')"><s>S</s></button>
                      <button class="btn btn-xs btn-ghost" type="button" onclick="execCommunicationCommand('superscript')">x²</button>
                      <button class="btn btn-xs btn-ghost" type="button" onclick="execCommunicationCommand('subscript')">x₂</button>
                    </div>
                    <div class="comms-toolgroup">
                      <span class="comms-toolgroup-label">Blocks</span>
                      <button class="btn btn-xs btn-ghost" type="button" onclick="execCommunicationCommand('formatBlock','h1')">H1</button>
                      <button class="btn btn-xs btn-ghost" type="button" onclick="execCommunicationCommand('formatBlock','h2')">H2</button>
                      <button class="btn btn-xs btn-ghost" type="button" onclick="execCommunicationCommand('formatBlock','p')">Paragraph</button>
                      <button class="btn btn-xs btn-ghost" type="button" onclick="execCommunicationCommand('formatBlock','blockquote')">Quote</button>
                    </div>
                    <div class="comms-toolgroup">
                      <span class="comms-toolgroup-label">Layout</span>
                      <button class="btn btn-xs btn-ghost" type="button" onclick="setCommunicationAlignment('left')">Left</button>
                      <button class="btn btn-xs btn-ghost" type="button" onclick="setCommunicationAlignment('center')">Center</button>
                      <button class="btn btn-xs btn-ghost" type="button" onclick="setCommunicationAlignment('right')">Right</button>
                      <button class="btn btn-xs btn-ghost" type="button" onclick="setCommunicationAlignment('justify')">Justify</button>
                    </div>
                    <div class="comms-toolgroup">
                      <span class="comms-toolgroup-label">Insert</span>
                      <button class="btn btn-xs btn-ghost" type="button" onclick="execCommunicationCommand('insertUnorderedList')">Bullets</button>
                      <button class="btn btn-xs btn-ghost" type="button" onclick="execCommunicationCommand('insertOrderedList')">Numbering</button>
                      <button class="btn btn-xs btn-ghost" type="button" onclick="execCommunicationCommand('createLink')">Link</button>
                      <button class="btn btn-xs btn-ghost" type="button" onclick="execCommunicationCommand('insertTable')">Table</button>
                      <button class="btn btn-xs btn-ghost" type="button" onclick="execCommunicationCommand('insertRule')">Rule</button>
                      <button class="btn btn-xs btn-ghost" type="button" onclick="execCommunicationCommand('clearFormatting')">Clear</button>
                    </div>
                  </div>

                  <div class="comms-token-cloud">
                    ${COMMUNICATION_PLACEHOLDERS.map(token => `<button class="btn btn-xs btn-ghost" type="button" onclick="insertCommunicationToken('${token}')">${token}</button>`).join('')}
                  </div>

                  <div class="comms-editor-stage">
                    <div class="comms-paper">
                      <div class="comms-paper-meta">Bitende Junior School · Mail merge template</div>
                      <div id="cm-editor" contenteditable="true" spellcheck="true" class="comms-editor"></div>
                      <textarea id="cm-body" style="display:none"></textarea>
                    </div>
                  </div>
                </div>
              </div>

              <div class="comms-column">
                <div class="card">
                  <div class="card-head"><div class="card-title">Workflow & Actions</div><div class="sub">Versioning, approvals, print and send</div></div>
                  <div class="card-body">
                    <div class="comms-data-grid">
                      <div class="comms-data-cell"><div class="k">Workflow</div><div class="v" id="cm-meta-status">Draft</div></div>
                      <div class="comms-data-cell"><div class="k">Version</div><div class="v" id="cm-meta-version">v1</div></div>
                      <div class="comms-data-cell"><div class="k">Library</div><div class="v" id="cm-meta-library">Whole school</div></div>
                      <div class="comms-data-cell"><div class="k">Updated</div><div class="v" id="cm-meta-updated">New draft</div></div>
                    </div>
                    <div class="field" style="margin:12px 0 0 0"><label>Workflow notes</label><textarea class="field-input" id="cm-workflow-notes" style="min-height:86px" placeholder="Approval notes, usage guidance, or revision comments"></textarea></div>
                    <div class="comms-actions" style="margin-top:12px">
                      <button class="btn btn-primary" onclick="saveCommunicationTemplate()">Save</button>
                      <button class="btn btn-ghost" onclick="cloneCommunicationVersion()">New version</button>
                      ${canApprove ? `<button class="btn btn-ghost" onclick="approveCommunicationTemplate()">Approve</button>` : ''}
                      ${canApprove ? `<button class="btn btn-ghost" onclick="publishCommunicationTemplate()">Publish</button>` : ''}
                      <button class="btn btn-ghost" onclick="previewCommunicationMerge()">Preview</button>
                      <button class="btn btn-ghost" onclick="queueCommunicationMerge()">Print pack</button>
                      <button class="btn btn-ghost" onclick="sendCommunicationMerge('email')">Email now</button>
                      <button class="btn btn-ghost" onclick="sendCommunicationMerge('sms')">SMS now</button>
                      <button class="btn btn-ghost" onclick="clearCommunicationForm()">Clear</button>
                    </div>
                  </div>
                </div>

                <div class="card">
                  <div class="card-head"><div class="card-title">Campaign Scheduler</div><div class="sub">Send later with retries and reports</div></div>
                  <div class="card-body">
                    <div class="field" style="margin:0 0 10px 0"><label>Channel</label><select class="field-select" id="cm-campaign-channel"><option value="email">Email campaign</option><option value="sms">SMS campaign</option></select></div>
                    <div class="field" style="margin:0 0 10px 0"><label>Scheduled date & time</label><input class="field-input" id="cm-schedule-at" type="datetime-local"></div>
                    <div class="comms-data-grid">
                      <div class="field" style="margin:0"><label>Retry limit</label><input class="field-input" id="cm-retry-limit" type="number" min="0" max="10" value="2"></div>
                      <div class="field" style="margin:0"><label>Retry delay (mins)</label><input class="field-input" id="cm-retry-delay" type="number" min="1" max="1440" value="30"></div>
                    </div>
                    <div class="field" style="margin:10px 0 0 0"><label>Campaign notes</label><textarea class="field-input" id="cm-campaign-notes" style="min-height:76px" placeholder="What this campaign is for, retry expectations, or handover notes"></textarea></div>
                    <div class="comms-actions" style="margin-top:12px">
                      <button class="btn btn-primary" onclick="scheduleCommunicationCampaign()">Schedule</button>
                      <button class="btn btn-ghost" onclick="runDueCommunicationCampaigns()">Run due</button>
                    </div>
                  </div>
                </div>

                <div class="card">
                  <div class="card-head"><div class="card-title">Recent Campaigns</div><div class="sub">Delivery visibility</div></div>
                  <div class="card-body"><div class="comms-campaign-list">${campaignHtml}</div></div>
                </div>
              </div>
            </div>
          </div>`;
        ensureCommunicationEditor();
        const boot = COMMUNICATION_EDITOR_BOOT;
        COMMUNICATION_EDITOR_BOOT = null;
        clearCommunicationForm();
        if (boot && boot.id) {
            await openCommunicationEdit(boot.id);
        } else if (boot && boot.starterKey) {
            loadCommunicationStarter(boot.starterKey);
        }
    } else if (page === 'delivery_logs') {
        await renderDeliveryLogsPage(main);
    } else if (page === 'timetable') {
        const role = (currentUser.profile && currentUser.profile.role) || 'admin';
        const canEdit = ['superadmin', 'admin', 'headteacher', 'deputy', 'dos', 'reception'].includes(role);

        if (canEdit) {
            const classes = await API.fetch('/classes/');
            const teachers = await API.fetch('/teachers/').catch(() => []);
            const classOptions = (classes || []).map(c => `<option value="${c.id}">${c.level}</option>`).join('');
            main.innerHTML = `
              <div class="page">
                <div class="page-hero"><div class="page-title">Timetable Builder</div></div>
                <div class="card"><div class="card-body">
                  <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                    <div class="field" style="margin:0;min-width:240px"><label>Class</label><select class="field-select" id="tt-class" onchange="ttOnClassChanged()">${classOptions}</select></div>
                    <div class="field" id="tt-sec-wrap" style="margin:0;min-width:120px"><label>Section</label><input class="field-input" id="tt-sec" value="A"></div>
                    <div class="field" style="margin:0;min-width:260px"><label>Days (comma)</label><input class="field-input" id="tt-days" value="Mon,Tue,Wed,Thu,Fri"></div>
                    <div class="field" style="margin:0;min-width:320px"><label>Periods (comma)</label><input class="field-input" id="tt-periods" value="1,2,3,4,5,6,7,8"></div>
                    <button class="btn btn-ghost" onclick="ttLoad()">Load</button>
                    <button class="btn btn-primary" onclick="ttSave()">Save</button>
                    <span class="sub" id="tt-dirty" style="min-width:120px">Saved</span>
                    <button class="btn btn-ghost" onclick="ttPrint()">Print</button>
                  </div>
                  <div style="height:10px"></div>
                  <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                    <div class="field" style="margin:0;min-width:170px"><label>Auto Times Start</label><input class="field-input" id="tt-auto-start" type="time" value="08:00"></div>
                    <div class="field" style="margin:0;min-width:170px"><label>Minutes / Period</label><input class="field-input" id="tt-auto-dur" type="number" value="40"></div>
                    <button class="btn btn-ghost" onclick="ttAutoFillTimes()">Auto-Fill Times</button>
                    <div style="flex:1"></div>
                    <div class="field" style="margin:0;min-width:240px"><label>Copy From Class</label><select class="field-select" id="tt-copy-class"><option value="">Select...</option>${classOptions}</select></div>
                    <div class="field" style="margin:0;min-width:120px"><label>Copy Section</label><input class="field-input" id="tt-copy-sec" value=""></div>
                    <button class="btn btn-ghost" onclick="ttCopyFrom()">Copy</button>
                  </div>
                  <div style="height:10px"></div>
                  <div class="card" style="border:1px dashed #ddd"><div class="card-body" style="padding:12px">
                    <div style="font-weight:700;margin-bottom:8px">Period Times</div>
                    <div id="tt-times-editor"></div>
                  </div></div>
                </div></div>
                <div style="height:12px"></div>
                <div class="card"><div class="card-body no-pad"><div class="tw" id="tt-grid"></div></div></div>
              </div>`;
            TT.teachers = Array.isArray(teachers) ? teachers : [];
            TT._classes = Array.isArray(classes) ? classes : [];
            await ttLoad();
            return;
        }

        // Read-only view (teacher/parent).
        const [my, classes] = await Promise.all([API.fetch('/timetable/mine/'), API.fetch('/classes/').catch(() => [])]);
        const clsMap = new Map((classes || []).map(c => [c.id, c.level]));
        const role2 = (currentUser.profile && currentUser.profile.role) || 'parent';
        const myName = `${(currentUser.first_name || '').toString()} ${(currentUser.last_name || '').toString()}`.trim().toLowerCase();
        if (!my || my.length === 0) {
            main.innerHTML = `<div class="page"><div class="card"><div class="card-body">No timetable found for your account.</div></div></div>`;
            return;
        }
        const todayLabel = ttCurrentDayLabel();
        const cards = (my || []).map(t => {
            const slots = t.slots || {};
            const days = slots.days || ['Mon','Tue','Wed','Thu','Fri'];
            const periods = slots.periods || ['1','2','3','4','5','6','7','8'];
            const times = slots.times || {};
            const nowP = ttCurrentPeriod(periods, times);
            const cells = t.cells || {};
            const head = `<thead><tr><th>Day</th>${periods.map(p => {
                const tt = times[p] || times[String(p)] || null;
                const range = (tt && tt.start && tt.end) ? `<div style="font-size:10px;color:#666;margin-top:2px">${tt.start} - ${tt.end}</div>` : '';
                const cls = (nowP && String(p) === String(nowP)) ? 'tt-now-col' : '';
                return `<th class="${cls}">${p}${range}</th>`;
            }).join('')}</tr></thead>`;
            const body = days.map(d => `<tr class="${d === todayLabel ? 'tt-today-row' : ''}"><td><strong>${d}</strong></td>${periods.map(p => {
                const isNow = (d === todayLabel) && (nowP && String(p) === String(nowP));
                const cell = ttNormCell(cells[`${d}-${p}`]);
                const subj = (cell.subject || '').toString();
                const tname = (cell.teacher_name || '').toString();
                const isMine = (role2 === 'teacher' && myName && tname && tname.trim().toLowerCase() === myName);
                const v = tname ? `${subj}${subj ? '<div class="sub">Teacher: ' + tname + '</div>' : '<div>Teacher: ' + tname + '</div>'}` : subj;
                return `<td class="${isNow ? 'tt-now-cell' : ''} ${isMine ? 'tt-mine-cell' : ''}">${v || ''}</td>`;
            }).join('')}</tr>`).join('');
            const lvl = clsMap.get(t.school_class) || t.school_class;
            return `<div class="card" style="margin-bottom:12px">
              <div class="card-head"><div class="card-title">Class ${lvl} ${t.section}</div></div>
              <div class="card-body no-pad"><div class="tw"><table class="tbl">${head}<tbody>${body}</tbody></table></div></div>
            </div>`;
        }).join('');
        main.innerHTML = `<div class="page"><div class="page-hero"><div class="page-title">Timetable</div></div>${cards}</div>`;
    } else if (page === 'teacher_attendance') {
        const role = (currentUser.profile && currentUser.profile.role) || 'admin';
        const canEdit = ['superadmin', 'admin', 'headteacher', 'deputy', 'dos', 'reception'].includes(role);
        const today = todayISO();

        if (canEdit) {
            main.innerHTML = `
              <div class="page">
                <div class="page-hero"><div class="page-title">Teacher Attendance</div></div>
                <div class="card"><div class="card-body">
                  <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                    <div class="field" style="margin:0;min-width:180px"><label>Date</label><input class="field-input" id="ta-date" type="date" value="${today}"></div>
                    <div class="field" style="margin:0;min-width:220px"><label>Search</label><input class="field-input" id="ta-q" placeholder="Type teacher name..." oninput="taFilter()"></div>
                    <button class="btn btn-ghost" onclick="taLoad()">Load</button>
                    <button class="btn btn-primary" onclick="taSave()">Save</button>
                    <button class="btn btn-ghost" onclick="taGenerateQR()">Generate QR</button>
                  </div>
                  <div style="height:10px"></div>
                  <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
                    <div class="sub" style="font-weight:800">Quick actions:</div>
                    <button class="btn btn-xs btn-ghost" onclick="taSetAll('present')">All present</button>
                    <button class="btn btn-xs btn-ghost" onclick="taSetAll('absent')">All absent</button>
                    <button class="btn btn-xs btn-ghost" onclick="taApplySelected('present')">Selected present</button>
                    <button class="btn btn-xs btn-ghost" onclick="taOnlySelectedPresent()">Only selected present</button>
                    <button class="btn btn-xs btn-ghost" onclick="taApplySelected('late')">Selected late</button>
                    <button class="btn btn-xs btn-ghost" onclick="taApplySelected('excused')">Selected excused</button>
                    <button class="btn btn-xs btn-ghost" onclick="taApplySelected('absent')">Selected absent</button>
                    <span class="sub">Tip: Reception can manually mark only the teachers who are around, then save.</span>
                  </div>
                  <div id="ta-qr" style="margin-top:12px;display:none"></div>
                </div></div>
                <div style="height:12px"></div>
                <div class="card"><div class="card-body no-pad"><div class="tw">
                  <table class="tbl">
                    <thead><tr><th style="width:34px"><input type="checkbox" onclick="taToggleAll(this.checked)"></th><th>Teacher</th><th>Status</th><th>Marked</th><th>Notes</th></tr></thead>
                    <tbody id="ta-body"></tbody>
                  </table>
                </div></div></div>
              </div>`;
            await taLoad();
            return;
        }

        // Teacher read-only view.
        if (role === 'teacher') {
            const d = today;
            const mineToday = await API.fetch(`/teacher-attendance/?date=${d}`).catch(() => []);
            const st = (mineToday && mineToday.length) ? mineToday[0] : null;
            const hist = await API.fetch('/teacher-attendance/mine/?days=30').catch(() => []);
            const histRows = (hist || []).slice(0, 30).map(a => {
                const badge = a.status === 'present' ? 'green' : (a.status === 'late' ? '' : '');
                return `<tr>
                  <td>${a.date || ''}</td>
                  <td><span class="badge ${badge}">${a.status || ''}</span></td>
                  <td style="font-size:12px;color:var(--66)">${a.method || 'manual'}</td>
                  <td style="font-size:12px;color:var(--66)">${a.notes || '-'}</td>
                </tr>`;
            }).join('');
            main.innerHTML = `
              <div class="page">
                <div class="page-hero"><div class="page-title">My Attendance</div></div>
                <div class="card"><div class="card-body">
                  <div style="font-weight:800">Today (${d})</div>
                  <div style="margin-top:8px">
                    ${st ? `<span class="badge green">${st.status}</span> <span class="sub">method: ${st.method}</span>` : `<span class="badge">not marked</span>`}
                  </div>
                  <div style="height:10px"></div>
                  <div style="font-size:12px;color:var(--66)">Scan the QR code displayed at school (Reception) while logged in to mark your attendance.</div>
                </div></div>
                <div style="height:12px"></div>
                <div class="card"><div class="card-head"><div class="card-title">Last 30 Days</div></div>
                  <div class="card-body no-pad"><div class="tw">
                    <table class="tbl">
                      <thead><tr><th>Date</th><th>Status</th><th>Method</th><th>Notes</th></tr></thead>
                      <tbody>${histRows || ''}</tbody>
                    </table>
                  </div></div>
                </div>
              </div>`;
            return;
        }

        main.innerHTML = `<div class="page"><div class="card"><div class="card-body">You do not have access to this page.</div></div></div>`;
    } else if (page === 'announcements') {
        const role = (currentUser.profile && currentUser.profile.role) || 'admin';
        const canEdit = ['superadmin', 'admin', 'reception'].includes(role);
        const annQs = new URLSearchParams();
        if (canEdit && AN_SHOW_ARCHIVED) annQs.set('include_archived', '1');
        if (canEdit && AN_SHOW_EXPIRED) annQs.set('include_expired', '1');
        const [items, communicationTemplates] = await Promise.all([
            API.fetch(`/announcements/${annQs.toString() ? ('?' + annQs.toString()) : ''}`).catch(() => []),
            API.fetch('/document-drafts/?workflow_status=published&latest=1').catch(() => []),
        ]);
        const announcementTemplates = (communicationTemplates || []).filter(t => ['notice', 'message', 'letter'].includes(String(t.kind || '').toLowerCase()));
        const announcementTemplateOpts = announcementTemplates.map(t => `<option value="${t.id}">${escapeHtml(t.title || 'Untitled')} · ${escapeHtml(t.kind || 'template')}</option>`).join('');

            const rows = (items || []).slice(0, 120).map(a => {
            const aud = (a.audience_roles && a.audience_roles.length) ? a.audience_roles.join(', ') : 'all';
            const pub = a.is_published ? '<span class="badge green">published</span>' : '<span class="badge">draft</span>';
            const pin = a.is_pinned ? '<span class="badge green">pinned</span>' : '';
            const arch = a.is_archived ? '<span class="badge red">archived</span>' : '';
            const exp = a.expires_at ? `<span class="badge">expires</span> <span class="sub mono">${String(a.expires_at).slice(0, 16).replace('T',' ')}</span>` : '';
            return `<tr>
              <td>
                <div style="display:flex;gap:10px;align-items:center">
                  ${a.image_url ? `<div style="width:34px;height:34px;border-radius:10px;overflow:hidden;border:1px solid var(--e);background:#fff;flex-shrink:0"><img alt="" src="${a.image_url}" style="width:34px;height:34px;object-fit:cover"></div>` : `<div style="width:34px;height:34px;border-radius:10px;overflow:hidden;border:1px solid var(--e);background:var(--f0);flex-shrink:0"></div>`}
                  <div><strong>${a.title}</strong><div class="sub">${(a.body || '').slice(0, 80)}${(a.body || '').length > 80 ? '...' : ''}</div></div>
                </div>
              </td>
              <td style="font-size:12px;color:var(--66)">${aud}</td>
              <td>${pub} ${pin} ${arch}<div class="sub" style="margin-top:3px">${exp}</div></td>
              <td style="font-size:12px;color:var(--66)">${(a.created_at || '').toString().slice(0, 19).replace('T', ' ')}</td>
              <td>${canEdit ? `<button class="btn btn-xs btn-ghost" onclick="openAnnouncementEdit(${a.id})">Edit</button>` : ''}</td>
            </tr>`;
        }).join('');

        main.innerHTML = `
          <div class="page">
            <div class="page-hero">
              <div>
                <div class="page-title">Announcements</div>
                ${canEdit ? `<div class="sub" style="margin-top:4px;display:flex;gap:10px;flex-wrap:wrap;align-items:center">
                  <label style="display:flex;gap:7px;align-items:center"><input type="checkbox" ${AN_SHOW_ARCHIVED ? 'checked' : ''} onchange="AN_SHOW_ARCHIVED=this.checked; loadPage('announcements',null,'Announcements')"> Show archived</label>
                  <label style="display:flex;gap:7px;align-items:center"><input type="checkbox" ${AN_SHOW_EXPIRED ? 'checked' : ''} onchange="AN_SHOW_EXPIRED=this.checked; loadPage('announcements',null,'Announcements')"> Show expired</label>
                </div>` : ''}
              </div>
              ${canEdit ? `<button class="btn btn-primary" onclick="openAnnouncementAdd()">+ New</button>` : ''}
            </div>
            ${canEdit ? `
              <div class="card"><div class="card-body">
                <div style="font-weight:900;margin-bottom:8px">Create / Update Announcement</div>
                <input type="hidden" id="an-id" value="">
                <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                  <div class="field" style="margin:0;min-width:260px"><label>Title</label><input class="field-input" id="an-title"></div>
                  <div class="field" style="margin:0;min-width:260px"><label>Audience Roles (comma)</label><input class="field-input" id="an-aud" placeholder="parent,teacher"></div>
                  <div class="field" style="margin:0;min-width:220px"><label>Expires At (optional)</label><input class="field-input" id="an-exp" type="datetime-local"></div>
                  <div class="field" style="margin:0;min-width:320px"><label>Published communication template</label><select class="field-select" id="an-tpl"><option value="">Choose template from Communications</option>${announcementTemplateOpts}</select></div>
                  <div class="field" style="margin:0;min-width:320px"><label>Announcement Image (optional)</label>
                    <input class="field-input" id="an-img" placeholder="https://...">
                    <input type="file" id="an-file" accept="image/*" style="display:none">
                    <div class="dropzone" id="an-drop" style="margin-top:8px">
                      <div style="font-weight:800">Click or drop an image</div>
                      <div class="sub">JPG/PNG, max 2MB</div>
                    </div>
                    <div id="an-prev-wrap" style="display:none;margin-top:8px">
                      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
                        <div style="width:62px;height:62px;border-radius:12px;overflow:hidden;border:1px solid var(--e);background:#fff">
                          <img id="an-prev" alt="Announcement" src="" style="width:62px;height:62px;object-fit:cover">
                        </div>
                        <button class="btn btn-xs btn-ghost" onclick="clearAnnouncementImage()">Remove Image</button>
                      </div>
                    </div>
                  </div>
                  <div class="field" style="margin:0"><label><input type="checkbox" id="an-pub" checked> Published</label></div>
                  <div class="field" style="margin:0"><label><input type="checkbox" id="an-pin"> Pinned</label></div>
                  <div class="field" style="margin:0"><label><input type="checkbox" id="an-arch"> Archived</label></div>
                  <button class="btn btn-primary" onclick="saveAnnouncement()">Save</button>
                  <button class="btn btn-ghost" onclick="createAnnouncementFromTemplate()">Create From Template</button>
                  <button class="btn btn-ghost" onclick="loadPage('communications',null,'Communications')">Open Communications</button>
                  <button class="btn btn-ghost" onclick="clearAnnouncementForm()">Clear</button>
                  <button class="btn btn-ghost" onclick="deleteAnnouncement()" id="an-del" style="display:none">Delete</button>
                </div>
                <div style="height:10px"></div>
                <div class="field" style="margin:0"><label>Body</label><textarea class="field-input" id="an-body" style="min-height:90px"></textarea></div>
              </div></div>
              <div style="height:12px"></div>
            ` : ''}
            <div class="card"><div class="card-body no-pad"><div class="tw">
              <table class="tbl">
                <thead><tr><th>Announcement</th><th>Audience</th><th>Status</th><th>Created</th><th></th></tr></thead>
                <tbody>${rows}</tbody>
              </table>
            </div></div></div>
          </div>`;
        if (canEdit) setTimeout(() => { try { wireAnnouncementImageControls(); } catch {} }, 0);
    } else if (page === 'events') {
        const role = (currentUser.profile && currentUser.profile.role) || 'admin';
        const canEdit = ['superadmin', 'admin', 'reception'].includes(role);
        const evQs = new URLSearchParams();
        if (canEdit && EV_SHOW_PAST) evQs.set('include_past', '1');
        const [events, communicationTemplates] = await Promise.all([
            API.fetch(`/events/${evQs.toString() ? ('?' + evQs.toString()) : ''}`).catch(() => []),
            API.fetch('/document-drafts/?workflow_status=published&latest=1').catch(() => []),
        ]);
        const eventTemplates = (communicationTemplates || []).filter(t => ['notice', 'message', 'letter'].includes(String(t.kind || '').toLowerCase()));
        const eventTemplateOpts = eventTemplates.map(t => `<option value="${t.id}">${escapeHtml(t.title || 'Untitled')} · ${escapeHtml(t.kind || 'template')}</option>`).join('');

        const rows = (events || []).slice(0, 80).map(e => {
            const dates = e.end_date ? `${e.start_date} -> ${e.end_date}` : e.start_date;
            const aud = (e.audience_roles && e.audience_roles.length) ? e.audience_roles.join(', ') : 'all';
            const today = todayISO();
            const ended = (e.end_date ? (String(e.end_date) < today) : (String(e.start_date) < today));
            return `<tr>
              <td>
                <div style="display:flex;gap:10px;align-items:center">
                  ${e.image_url ? `<div style="width:34px;height:34px;border-radius:10px;overflow:hidden;border:1px solid var(--e);background:#fff;flex-shrink:0"><img alt="" src="${e.image_url}" style="width:34px;height:34px;object-fit:cover"></div>` : `<div style="width:34px;height:34px;border-radius:10px;overflow:hidden;border:1px solid var(--e);background:var(--f0);flex-shrink:0"></div>`}
                  <div><strong>${e.title}</strong><div class="sub">${dates}</div></div>
                </div>
              </td>
              <td style="font-size:12px;color:var(--66)">${aud}</td>
              <td>${e.is_published ? '<span class="badge green">published</span>' : '<span class="badge">draft</span>'} ${ended ? '<span class="badge">ended</span>' : ''}</td>
              <td style="font-size:12px;color:var(--66)">${(e.description || '').slice(0, 60)}${(e.description || '').length > 60 ? '...' : ''}</td>
              <td>
                ${canEdit ? `<button class="btn btn-xs btn-ghost" onclick="openEventEdit(${e.id})">Edit</button>` : ''}
              </td>
            </tr>`;
        }).join('');

        main.innerHTML = `
          <div class="page">
            <div class="page-hero">
              <div>
                <div class="page-title">Events</div>
                ${canEdit ? `<div class="sub" style="margin-top:4px;display:flex;gap:10px;flex-wrap:wrap;align-items:center">
                  <label style="display:flex;gap:7px;align-items:center"><input type="checkbox" ${EV_SHOW_PAST ? 'checked' : ''} onchange="EV_SHOW_PAST=this.checked; loadPage('events',null,'Events')"> Show past events</label>
                </div>` : ''}
              </div>
              ${canEdit ? `<button class="btn btn-primary" onclick="openEventAdd()">+ New Event</button>` : ''}
            </div>
            ${canEdit ? `
              <div class="card"><div class="card-body">
                <div style="font-weight:800;margin-bottom:8px">Create / Update Event</div>
                <input type="hidden" id="ev-id" value="">
                <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                  <div class="field" style="margin:0;min-width:240px"><label>Title</label><input class="field-input" id="ev-title"></div>
                  <div class="field" style="margin:0;min-width:160px"><label>Start Date</label><input class="field-input" id="ev-start" type="date"></div>
                  <div class="field" style="margin:0;min-width:160px"><label>End Date (optional)</label><input class="field-input" id="ev-end" type="date"></div>
                  <div class="field" style="margin:0;min-width:260px"><label>Audience Roles (comma)</label><input class="field-input" id="ev-aud" placeholder="parent,teacher"></div>
                  <div class="field" style="margin:0;min-width:320px"><label>Published communication template</label><select class="field-select" id="ev-tpl"><option value="">Choose template from Communications</option>${eventTemplateOpts}</select></div>
                  <div class="field" style="margin:0;min-width:320px"><label>Event Image (optional)</label>
                    <input class="field-input" id="ev-img" placeholder="https://...">
                    <input type="file" id="ev-file" accept="image/*" style="display:none">
                    <div class="dropzone" id="ev-drop" style="margin-top:8px">
                      <div style="font-weight:800">Click or drop an image</div>
                      <div class="sub">JPG/PNG, max 2MB</div>
                    </div>
                    <div id="ev-prev-wrap" style="display:none;margin-top:8px">
                      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
                        <div style="width:62px;height:62px;border-radius:12px;overflow:hidden;border:1px solid var(--e);background:#fff">
                          <img id="ev-prev" alt="Event" src="" style="width:62px;height:62px;object-fit:cover">
                        </div>
                        <button class="btn btn-xs btn-ghost" onclick="clearEventImage()">Remove Image</button>
                      </div>
                    </div>
                  </div>
                  <div class="field" style="margin:0"><label><input type="checkbox" id="ev-pub" checked> Published</label></div>
                  <button class="btn btn-primary" onclick="saveEvent()">Save</button>
                  <button class="btn btn-ghost" onclick="createEventFromTemplate()">Create From Template</button>
                  <button class="btn btn-ghost" onclick="loadPage('communications',null,'Communications')">Open Communications</button>
                  <button class="btn btn-ghost" onclick="clearEventForm()">Clear</button>
                  <button class="btn btn-ghost" onclick="deleteEvent()" id="ev-del" style="display:none">Delete</button>
                </div>
                <div style="height:10px"></div>
                <div class="field" style="margin:0"><label>Description</label><input class="field-input" id="ev-desc" placeholder="Details..."></div>
              </div></div>
              <div style="height:12px"></div>
            ` : ''}
            <div class="card"><div class="card-body no-pad"><div class="tw">
              <table class="tbl">
                <thead><tr><th>Event</th><th>Audience</th><th>Status</th><th>Description</th><th></th></tr></thead>
                <tbody>${rows || ''}</tbody>
              </table>
            </div></div></div>
          </div>`;
        if (canEdit) setTimeout(() => { try { wireEventImageControls(); } catch {} }, 0);
    } else if (page === 'auditlogs') {
        const q = (document.getElementById('al-q')?.value || '').trim();
        const ev = (document.getElementById('al-ev')?.value || '').trim();
        const days = (document.getElementById('al-days')?.value || '').trim();
        const qs = new URLSearchParams();
        if (q) qs.set('q', q);
        if (ev) qs.set('event_type', ev);
        if (days) qs.set('since_days', days);
        qs.set('limit', '200');
        const logs = await API.fetch(`/audit-logs/${qs.toString() ? ('?' + qs.toString()) : ''}`);
        const rows = (logs || []).slice(0, 200).map(l => `<tr><td>${l.timestamp || ''}</td><td>${l.event_type || ''}</td><td>${l.user_username || ''}</td><td>${l.ip_address || ''}</td><td style="font-size:12px;color:var(--66)">${escapeHtml(l.details || '')}</td></tr>`).join('');
        main.innerHTML = `
            <div class="page">
                <div class="page-hero"><div class="page-title">Audit Logs</div></div>
                <div class="card"><div class="card-body">
                  <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                    <div class="field" style="margin:0;min-width:280px"><label>Search</label><input class="field-input" id="al-q" placeholder="student id / username / keyword" value="${escapeHtml(q)}" oninput="loadPage('auditlogs',null,'Audit Logs')"></div>
                    <div class="field" style="margin:0;min-width:240px"><label>Event</label>
                      <select class="field-select" id="al-ev" onchange="loadPage('auditlogs',null,'Audit Logs')">
                        <option value="">All</option>
                        <option value="RESULTS_BLOCKED">RESULTS_BLOCKED</option>
                        <option value="RESULTS_UNBLOCKED">RESULTS_UNBLOCKED</option>
                        <option value="RESULTS_BULK_HELD">RESULTS_BULK_HELD</option>
                        <option value="RESULTS_BULK_RELEASED">RESULTS_BULK_RELEASED</option>
                        <option value="RESULTS_AUTO_HELD">RESULTS_AUTO_HELD</option>
                        <option value="LOGIN_FAILURE">LOGIN_FAILURE</option>
                        <option value="PAYMENT_APPROVED">PAYMENT_APPROVED</option>
                      </select>
                    </div>
                    <div class="field" style="margin:0;min-width:160px"><label>Since (days)</label><input class="field-input" id="al-days" type="number" value="${escapeHtml(days || '7')}" onchange="loadPage('auditlogs',null,'Audit Logs')"></div>
                    <button class="btn btn-ghost" onclick="document.getElementById('al-q').value='';document.getElementById('al-ev').value='';document.getElementById('al-days').value='7';loadPage('auditlogs',null,'Audit Logs')">Reset</button>
                  </div>
                </div></div>
                <div style="height:12px"></div>
                <div class="card"><div class="card-body no-pad">
                  <table class="tbl"><thead><tr><th>Time</th><th>Event</th><th>User</th><th>IP</th><th>Details</th></tr></thead><tbody>${rows}</tbody></table>
                </div></div>
            </div>`;
    } else if (page === 'credentials') {
        const [creds, credHistory] = await Promise.all([
            API.fetch('/api-credentials/'),
            API.fetch('/api-credentials/history/?limit=15').catch(() => []),
        ]);
        const rows = (creds || []).map(c => {
            const sid = (c.client_id || '').toString();
            const key = (c.api_key || '').toString();
            const secret = (c.client_secret || '').toString();
            const sidMask = sid ? (sid.length > 10 ? (sid.slice(0, 6) + '...' + sid.slice(-4)) : sid) : '-';
            const keyMask = key ? ('******' + key.slice(-4)) : '-';
            const secMask = secret ? ('******' + secret.slice(-4)) : '-';
            const updated = c.updated_at ? String(c.updated_at).slice(0, 19).replace('T', ' ') : '';
            const vOk = (typeof c.last_verify_ok === 'boolean') ? c.last_verify_ok : null;
            const vAt = c.last_verified_at ? String(c.last_verified_at).slice(0, 19).replace('T', ' ') : '';
            const vBadge = (vOk === true) ? '<span class="badge green">Verified</span>' : (vOk === false) ? '<span class="badge red">Failed</span>' : '<span class="badge">Never</span>';
            const vText = vAt ? `<div class="sub mono">${vAt}</div>` : '';
            return `
              <tr>
                <td><strong>${credServiceLabel(c.service_name)}</strong><div class="sub mono">${c.service_name}</div></td>
                <td>${c.is_active ? '<span class="badge green">Active</span>' : '<span class="badge">Inactive</span>'}</td>
                <td>${vBadge}${vText}</td>
                <td class="mono" style="font-size:12px;color:var(--66)">${sidMask}</td>
                <td class="mono" style="font-size:12px;color:var(--66)">${secMask}</td>
                <td class="mono" style="font-size:12px;color:var(--66)">${keyMask}</td>
                <td style="font-size:12px;color:var(--66)">${updated}</td>
                <td>
                  <button class="btn btn-xs btn-ghost" onclick="toggleCredentialActive(${c.id}, ${c.is_active ? 'false' : 'true'})">${c.is_active ? 'Disable' : 'Enable'}</button>
                  <button class="btn btn-xs btn-ghost" onclick="prefillCredential(${c.id})">Edit</button>
                  <button class="btn btn-xs btn-ghost" onclick="verifyCredential(${c.id})">Verify</button>
                  <button class="btn btn-xs btn-ghost" onclick="deleteCredential(${c.id})">Delete</button>
                </td>
              </tr>`;
        }).join('');

        main.innerHTML = `
          <div class="page">
            <div class="page-hero">
              <div>
                <div class="page-title">API Credentials</div>
                <div class="sub">Keys are stored in the database and used by server integrations (Google login, SMS, Mobile Money, Email, AI). Only Super Admin can edit.</div>
              </div>
            </div>

            <div class="grid-2">
              <div class="card">
                <div class="card-head"><div class="card-title">Configure A Service</div></div>
                <div class="card-body">
                  <input type="hidden" id="cred-id" value="">

                  <div class="seg" id="cred-seg">
                    <button class="seg-btn active" data-svc="google_oauth" onclick="credPick('google_oauth', this)">Google</button>
                    <button class="seg-btn" data-svc="mtn_momo" onclick="credPick('mtn_momo', this)">MTN MoMo</button>
                    <button class="seg-btn" data-svc="airtel_money" onclick="credPick('airtel_money', this)">Airtel Money</button>
                    <button class="seg-btn" data-svc="twilio_sms" onclick="credPick('twilio_sms', this)">Twilio</button>
                    <button class="seg-btn" data-svc="gmail_smtp" onclick="credPick('gmail_smtp', this)">Gmail SMTP</button>
                    <button class="seg-btn" data-svc="email_smtp" onclick="credPick('email_smtp', this)">SMTP</button>
                    <button class="seg-btn" data-svc="megasms" onclick="credPick('megasms', this)">MegaSMS</button>
                    <button class="seg-btn" data-svc="zapier_webhook" onclick="credPick('zapier_webhook', this)">Zapier</button>
                    <button class="seg-btn" data-svc="openai" onclick="credPick('openai', this)">AI Key</button>
                    <button class="seg-btn" data-svc="gemini" onclick="credPick('gemini', this)">Gemini</button>
                  </div>

                  <div style="height:10px"></div>

                  <div class="field" style="margin:0">
                    <label>Service</label>
                    <select class="field-select" id="cred-service" onchange="credOnServiceChange()">
                      <option value="google_oauth">Google OAuth</option>
                      <option value="mtn_momo">MTN Mobile Money</option>
                      <option value="airtel_money">Airtel Mobile Money</option>
                      <option value="twilio_sms">Twilio SMS</option>
                      <option value="gmail_smtp">Gmail SMTP (App Password)</option>
                      <option value="email_smtp">Email SMTP</option>
                      <option value="megasms">MegaSMS Uganda (SMS)</option>
                      <option value="zapier_webhook">Zapier Webhook</option>
                      <option value="openai">OpenAI (AI Key)</option>
                      <option value="gemini">Google Gemini (AI Key)</option>
                    </select>
                  </div>

                  <div style="height:10px"></div>

                  <div class="kv-grid">
                    <div class="kv-item" id="cred-client-id-wrap">
                      <div class="k" id="cred-client-id-label">Client ID</div>
                      <input class="field-input mono" id="cred-client-id" placeholder="">
                      <div class="sub" id="cred-client-id-hint"></div>
                    </div>
                    <div class="kv-item" id="cred-client-secret-wrap">
                      <div class="k" id="cred-client-secret-label">Client Secret</div>
                      <input class="field-input mono" id="cred-client-secret" type="password" placeholder="">
                      <div class="sub" id="cred-client-secret-hint"></div>
                    </div>
                    <div class="kv-item" id="cred-api-key-wrap">
                      <div class="k" id="cred-api-key-label">API Key</div>
                      <input class="field-input mono" id="cred-api-key" type="password" placeholder="">
                      <div class="sub" id="cred-api-key-hint"></div>
                    </div>
                    <div class="kv-item">
                      <div class="k">Options</div>
                      <label style="display:flex;gap:8px;align-items:center;font-size:13px;color:var(--1a);font-weight:700;text-transform:none;letter-spacing:0">
                        <input type="checkbox" id="cred-active" checked> Active
                      </label>
                      <label style="display:flex;gap:8px;align-items:center;font-size:13px;color:var(--1a);font-weight:700;text-transform:none;letter-spacing:0;margin-top:8px">
                        <input type="checkbox" id="cred-show" onchange="credToggleSecrets()"> Show secrets
                      </label>
                    </div>
                  </div>

                  <div style="height:12px"></div>

                  <div class="help-box">
                    <div style="font-weight:900;color:var(--md);margin-bottom:6px">Service Notes</div>
                    <div id="cred-help" style="font-size:12px;color:var(--66);line-height:1.5"></div>
                    <div style="height:10px"></div>
                    <div style="font-weight:900;color:var(--md);margin-bottom:6px">Extra Fields</div>
                    <div id="cred-extra-fields"></div>
                    <details style="margin-top:10px">
                      <summary style="cursor:pointer;font-weight:800">Advanced JSON (optional)</summary>
                      <div style="height:8px"></div>
                      <textarea class="field-input mono" id="cred-extra-raw" style="min-height:90px" placeholder="{ }"></textarea>
                      <div class="sub">Advanced JSON overrides the extra fields above.</div>
                    </details>
                  </div>

                  <div style="height:12px"></div>
                  <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;justify-content:flex-end">
                    <button class="btn btn-primary" onclick="saveCredential()">Save</button>
                    <button class="btn btn-ghost" onclick="verifyCredentialFromForm()">Verify</button>
                    <button class="btn btn-ghost" onclick="sendTestCredentialFromForm()">Test</button>
                    <button class="btn btn-ghost" onclick="clearCredentialForm()">Clear</button>
                  </div>
                </div>
              </div>

              <div class="card">
                <div class="card-head"><div class="card-title">Stored Credentials</div><div class="sub">Masked values shown for safety</div></div>
                <div class="card-body no-pad">
                  <div class="tw">
                    <table class="tbl">
                      <thead><tr><th>Service</th><th>Status</th><th>Verify</th><th>Client ID</th><th>Secret</th><th>API Key</th><th>Updated</th><th>Actions</th></tr></thead>
                      <tbody>${rows || `<tr><td colspan="8" style="color:var(--99)">No credentials saved yet.</td></tr>`}</tbody>
                    </table>
                  </div>
                </div>
                <div class="card-head" style="border-top:1px solid var(--f0)"><div class="card-title">Verification History</div><div class="sub">Recent checks and failure reasons</div></div>
                <div class="card-body no-pad">
                  <div class="tw">
                    <table class="tbl">
                      <thead><tr><th>Service</th><th>Result</th><th>Time</th><th>Verified By</th><th>Detail</th></tr></thead>
                      <tbody>${historyRows || `<tr><td colspan="5" style="color:var(--99)">No verification history yet.</td></tr>`}</tbody>
                    </table>
                  </div>
                </div>
              </div>
            </div>
          </div>`;
        try { credPick('google_oauth'); } catch {}
    } else if (page === 'security') {
        const role = (currentUser.profile && currentUser.profile.role) || 'admin';
        if (role !== 'superadmin') throw { detail: 'Only super admin can access Security.' };

        const [ov, sessions, users] = await Promise.all([
            API.fetch('/security/overview/'),
            API.fetch('/security/active-sessions/'),
            API.fetch('/users/'),
        ]);

        const eventRows = Object.entries((ov && ov.events_24h) ? ov.events_24h : {}).slice(0, 12).map(([k, v]) => `<tr><td>${k}</td><td style="font-weight:900;color:var(--m)">${v}</td></tr>`).join('');
        const sessRows = (sessions || []).slice(0, 80).map(s => `<tr>
          <td>${formatDateTime(s.login_time)}</td>
          <td><strong>${s.username || '-'}</strong><div class="sub">${s.user_id || ''}</div></td>
          <td>${s.ip_address || '-'}</td>
          <td style="font-size:12px;color:var(--66)">${(s.user_agent || '').slice(0, 40)}${(s.user_agent || '').length > 40 ? '...' : ''}</td>
          <td>
            <button class="btn btn-xs btn-ghost" onclick="terminateSession('${s.session_key}')">Terminate</button>
            <button class="btn btn-xs btn-ghost" onclick="terminateUserSessions(${s.user_id})">Terminate User</button>
          </td>
        </tr>`).join('');

        const userRows = (users || []).slice(0, 120).map(u => `<tr>
          <td><strong>${u.username}</strong></td>
          <td>${(u.profile && u.profile.role) ? u.profile.role : '-'}</td>
          <td style="font-size:12px;color:var(--66)">${(u.profile && u.profile.last_login_ip) ? u.profile.last_login_ip : '-'}</td>
          <td style="font-size:12px;color:var(--66)">${(u.profile && u.profile.last_login_ua) ? (u.profile.last_login_ua.slice(0, 40) + (u.profile.last_login_ua.length > 40 ? '...' : '')) : '-'}</td>
          <td>
            <button class="btn btn-xs btn-ghost" onclick="openUserEdit(${u.id})">Edit</button>
            <button class="btn btn-xs btn-ghost" onclick="disableUser(${u.id})">Disable</button>
          </td>
        </tr>`).join('');

        main.innerHTML = `
          <div class="page">
            <div class="page-hero"><div class="page-title">Security</div></div>
            <div class="stats stats-4">
              <div class="stat-card"><div class="stat-num">${ov.active_sessions || 0}</div><div class="stat-label">Active Sessions</div><div class="stat-accent blue"></div></div>
              <div class="stat-card"><div class="stat-num">${ov.failed_logins_24h || 0}</div><div class="stat-label">Failed Logins (24h)</div><div class="stat-accent red"></div></div>
              <div class="stat-card"><div class="stat-num">RL</div><div class="stat-label">Login rate limiting enabled</div><div class="stat-accent gold"></div></div>
              <div class="stat-card"><div class="stat-num">OK</div><div class="stat-label">Security console</div><div class="stat-accent green"></div></div>
            </div>

            <div class="g21" style="grid-template-columns:1fr 420px">
              <div class="card">
                <div class="card-head"><div class="card-title">Active Sessions</div><button class="btn btn-xs btn-ghost" onclick="loadPage('security')">Refresh</button></div>
                <div class="card-body no-pad"><div class="tw">
                  <table class="tbl"><thead><tr><th>Login</th><th>User</th><th>IP</th><th>UA</th><th></th></tr></thead><tbody>${sessRows || ''}</tbody></table>
                </div></div>
              </div>
              <div>
                <div class="card">
                  <div class="card-head"><div class="card-title">Events (24h)</div></div>
                  <div class="card-body no-pad"><table class="tbl"><thead><tr><th>Event</th><th>Count</th></tr></thead><tbody>${eventRows || ''}</tbody></table></div>
                </div>
                <div style="height:12px"></div>
                <div class="card" style="border-left:4px solid var(--m)">
                  <div class="card-body">
                    <div style="font-weight:900;color:var(--md)">Emergency actions</div>
                    <div style="margin-top:6px;color:var(--66);font-size:13px">Use these if you suspect a compromised account.</div>
                    <div style="height:10px"></div>
                    <button class="btn btn-ghost" onclick="logoutOtherSessions()">Logout My Other Sessions</button>
                  </div>
                </div>
              </div>
            </div>

            <div style="height:12px"></div>
            <div class="card">
              <div class="card-head"><div class="card-title">Users (Quick Controls)</div></div>
              <div class="card-body no-pad"><div class="tw">
                <table class="tbl"><thead><tr><th>User</th><th>Role</th><th>Last IP</th><th>Last UA</th><th></th></tr></thead><tbody>${userRows || ''}</tbody></table>
              </div></div>
            </div>
          </div>`;
    } else if (page === 'fees') {
        const role = (currentUser.profile && currentUser.profile.role) || 'superadmin';
        const canEdit = ['superadmin', 'admin', 'bursar'].includes(role);
        const [fees, classes, activeTerm] = await Promise.all([
            API.fetch('/fees/'),
            API.fetch('/classes/'),
            API.fetch('/terms/').catch(() => null),
        ]);
        const defYear = (activeTerm && activeTerm.academic_year) ? activeTerm.academic_year : new Date().getFullYear();
        const defTerm = (activeTerm && activeTerm.term_number) ? activeTerm.term_number : 1;
        const byKey = new Map((fees || []).map(f => [`${f.school_class}-${f.year}-${f.term}`, f]));

        const rows = (classes || []).map(c => {
            const key = `${c.id}-${defYear}-${defTerm}`;
            const fee = byKey.get(key);
            const amt = fee ? `UGX ${fmt(fee.amount)}` : `<span style="color:var(--99)">Not set</span>`;
            const actions = canEdit
              ? (fee
                  ? `<button class="btn btn-xs btn-ghost" onclick="openFeeEdit(${fee.id})">Edit</button>`
                  : `<button class="btn btn-xs btn-ghost" onclick="openFeeAdd(${c.id}, ${defYear}, ${defTerm})">Set</button>`)
              : '';
            return `<tr>
              <td><strong>${c.level}</strong></td>
              <td>${defYear}</td>
              <td>${defTerm}</td>
              <td style="font-weight:800;color:var(--m)">${fee ? `UGX ${fmt(fee.amount)}` : '-'}</td>
              <td>${actions}</td>
            </tr>`;
        }).join('');

        main.innerHTML = `
          <div class="page">
            <div class="page-hero"><div class="page-title">Fee Structure</div>${canEdit ? `<button class="btn btn-primary" onclick="openFeeAdd(null, ${defYear}, ${defTerm})">+ Add Fee Row</button>` : ''}</div>
            <div class="card"><div class="card-body">
              <div style="color:var(--66);font-size:13px">Editing fees here affects the configured fee schedule. Existing invoices/payments are not automatically recalculated.</div>
            </div></div>
            <div style="height:12px"></div>
            <div class="card"><div class="card-body no-pad">
              <table class="tbl">
                <thead><tr><th>Class</th><th>Year</th><th>Term</th><th>Amount</th><th></th></tr></thead>
                <tbody>${rows}</tbody>
              </table>
            </div></div>
          </div>`;

        // Populate fee modal class options (used by Add Fee Row).
        const sel = document.getElementById('f-class');
        if (sel) sel.innerHTML = (classes || []).map(c => `<option value="${c.id}">${c.level}</option>`).join('');
    } else if (page === 'charges') {
        const role = (currentUser.profile && currentUser.profile.role) || 'superadmin';
        const canEdit = ['superadmin', 'bursar', 'admin', 'headteacher', 'deputy', 'dos'].includes(role);
        const activeTerm = await API.fetch('/terms/').catch(() => null);
        const defYear = (activeTerm && activeTerm.academic_year) ? activeTerm.academic_year : new Date().getFullYear();
        const defTerm = (activeTerm && activeTerm.term_number) ? activeTerm.term_number : 1;

        if (!CH_FILTER.year) CH_FILTER.year = String(defYear);
        if (!CH_FILTER.term) CH_FILTER.term = String(defTerm);

        const [classes] = await Promise.all([
            API.fetch('/classes/').catch(() => []),
        ]);

        const qs = new URLSearchParams();
        if (CH_FILTER.class_id) qs.set('class_id', CH_FILTER.class_id);
        if (CH_FILTER.year) qs.set('year', CH_FILTER.year);
        if (CH_FILTER.term) qs.set('term', CH_FILTER.term);
        if (CH_FILTER.active) qs.set('active', CH_FILTER.active);
        if (CH_FILTER.published) qs.set('published', CH_FILTER.published);
        const charges = await API.fetch(`/class-charges/${qs.toString() ? ('?' + qs.toString()) : ''}`).catch(() => []);

        const rows = (charges || []).slice(0, 200).map(c => {
            const scope = `${c.school_class_level || ''}${c.section || ''}`;
            const y = c.academic_year ? String(c.academic_year) : 'any';
            const t = c.term_number ? `T${c.term_number}` : 'any';
            const st = `${c.is_active ? '<span class="badge green">active</span>' : '<span class="badge">inactive</span>'} ${c.is_published ? '<span class="badge green">published</span>' : '<span class="badge">draft</span>'}`;
            return `<tr>
              <td><strong>${escapeHtml(c.title || '')}</strong><div class="sub">${escapeHtml(scope || '-')}</div></td>
              <td style="font-weight:900;color:var(--m)">UGX ${fmt(c.amount || 0)}</td>
              <td style="font-size:12px;color:var(--66)">${escapeHtml(`${y} / ${t}`)}</td>
              <td style="font-size:12px;color:var(--66)">${c.due_date || '-'}</td>
              <td>${st}</td>
              <td>${c.image_url ? `<button class="btn btn-xs btn-ghost" onclick="viewImage('${escapeHtml(c.image_url)}')">Image</button>` : '-'}</td>
              <td>${canEdit ? `<button class="btn btn-xs btn-ghost" onclick="openChargeEdit(${c.id})">Edit</button>` : ''}</td>
            </tr>`;
        }).join('');

        main.innerHTML = `
          <div class="page">
            <div class="page-hero"><div class="page-title">Class Charges</div>${canEdit ? `<button class="btn btn-primary" onclick="clearChargeForm()">+ New Charge</button>` : ''}</div>
            <div class="card"><div class="card-body">
              <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                <div class="field" style="margin:0;min-width:220px"><label>Class</label>
                  <select class="field-select" id="ch-f-class" onchange="CH_FILTER.class_id=this.value; loadPage('charges',null,'Class Charges')">
                    <option value="">All</option>
                    ${(classes || []).map(c => `<option value="${c.id}" ${String(CH_FILTER.class_id)===String(c.id)?'selected':''}>${c.level}</option>`).join('')}
                  </select>
                </div>
                <div class="field" style="margin:0;min-width:130px"><label>Year</label><input class="field-input" id="ch-f-year" value="${escapeHtml(CH_FILTER.year || '')}" oninput="CH_FILTER.year=this.value"></div>
                <div class="field" style="margin:0;min-width:120px"><label>Term</label>
                  <select class="field-select" id="ch-f-term" onchange="CH_FILTER.term=this.value">
                    <option value="">Any</option>
                    <option value="1" ${CH_FILTER.term==='1'?'selected':''}>T1</option>
                    <option value="2" ${CH_FILTER.term==='2'?'selected':''}>T2</option>
                    <option value="3" ${CH_FILTER.term==='3'?'selected':''}>T3</option>
                  </select>
                </div>
                <div class="field" style="margin:0;min-width:120px"><label>Active</label>
                  <select class="field-select" id="ch-f-active" onchange="CH_FILTER.active=this.value">
                    <option value="" ${!CH_FILTER.active?'selected':''}>All</option>
                    <option value="1" ${CH_FILTER.active==='1'?'selected':''}>Yes</option>
                    <option value="0" ${CH_FILTER.active==='0'?'selected':''}>No</option>
                  </select>
                </div>
                <div class="field" style="margin:0;min-width:140px"><label>Published</label>
                  <select class="field-select" id="ch-f-pub" onchange="CH_FILTER.published=this.value">
                    <option value="" ${!CH_FILTER.published?'selected':''}>All</option>
                    <option value="1" ${CH_FILTER.published==='1'?'selected':''}>Yes</option>
                    <option value="0" ${CH_FILTER.published==='0'?'selected':''}>No</option>
                  </select>
                </div>
                <button class="btn btn-ghost" onclick="CH_FILTER.year=document.getElementById('ch-f-year').value; CH_FILTER.term=document.getElementById('ch-f-term').value; CH_FILTER.active=document.getElementById('ch-f-active').value; CH_FILTER.published=document.getElementById('ch-f-pub').value; loadPage('charges',null,'Class Charges')">Load</button>
                <button class="btn btn-ghost" onclick="CH_FILTER={class_id:'',year:String(defYear),term:String(defTerm),active:'1',published:'1'}; loadPage('charges',null,'Class Charges')">Reset</button>
              </div>
              <div class="sub" style="margin-top:8px">Use class charges for tours, requirements, trips, special contributions. Parents/students only see charges for their class.</div>
            </div></div>
            ${canEdit ? `
              <div style="height:12px"></div>
              <div class="card"><div class="card-body">
                <div style="font-weight:900;margin-bottom:8px">Create / Update Charge</div>
                <input type="hidden" id="ch-id" value="">
                <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                  <div class="field" style="margin:0;min-width:200px"><label>Class</label><select class="field-select" id="ch-class">${(classes||[]).map(c => `<option value="${c.id}">${c.level}</option>`).join('')}</select></div>
                  <div class="field" style="margin:0;min-width:110px"><label>Section (optional)</label><input class="field-input" id="ch-sec" placeholder="A"></div>
                  <div class="field" style="margin:0;min-width:240px"><label>Title</label><input class="field-input" id="ch-title" placeholder="Tour contribution"></div>
                  <div class="field" style="margin:0;min-width:160px"><label>Amount (UGX)</label><input class="field-input" id="ch-amt" type="number" min="0" step="1"></div>
                  <div class="field" style="margin:0;min-width:160px"><label>Due Date (optional)</label><input class="field-input" id="ch-due" type="date"></div>
                  <div class="field" style="margin:0;min-width:140px"><label>Year (optional)</label><input class="field-input" id="ch-year" type="number" placeholder="${defYear}"></div>
                  <div class="field" style="margin:0;min-width:120px"><label>Term (optional)</label>
                    <select class="field-select" id="ch-term">
                      <option value="">Any</option><option value="1">T1</option><option value="2">T2</option><option value="3">T3</option>
                    </select>
                  </div>
                  <div class="field" style="margin:0;min-width:320px"><label>Image (optional)</label>
                    <input class="field-input" id="ch-img" type="hidden">
                    <input type="file" id="ch-file" accept="image/*" style="display:none">
                    <div class="dropzone" id="ch-drop" style="margin-top:8px">
                      <div style="font-weight:800">Click or drop an image</div>
                      <div class="sub">JPG/PNG, max 2MB</div>
                    </div>
                    <div id="ch-prev-wrap" style="display:none;margin-top:8px">
                      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
                        <div style="width:62px;height:62px;border-radius:12px;overflow:hidden;border:1px solid var(--e);background:#fff">
                          <img id="ch-prev" alt="Charge" src="" style="width:62px;height:62px;object-fit:cover">
                        </div>
                        <button class="btn btn-xs btn-ghost" onclick="clearChargeImage()">Remove Image</button>
                      </div>
                    </div>
                  </div>
                  <div class="field" style="margin:0"><label><input type="checkbox" id="ch-active" checked> Active</label></div>
                  <div class="field" style="margin:0"><label><input type="checkbox" id="ch-pub" checked> Published</label></div>
                  <button class="btn btn-primary" onclick="saveCharge()">Save</button>
                  <button class="btn btn-ghost" onclick="clearChargeForm()">Clear</button>
                  <button class="btn btn-ghost" onclick="deleteCharge()" id="ch-del" style="display:none">Delete</button>
                </div>
                <div style="height:10px"></div>
                <div class="field" style="margin:0"><label>Description</label><textarea class="field-input" id="ch-desc" style="min-height:70px" placeholder="Optional details..."></textarea></div>
              </div></div>
            ` : ''}
            <div style="height:12px"></div>
            <div class="card"><div class="card-body no-pad"><div class="tw">
              <table class="tbl">
                <thead><tr><th>Charge</th><th>Amount</th><th>Scope</th><th>Due</th><th>Status</th><th>Image</th><th></th></tr></thead>
                <tbody>${rows || ''}</tbody>
              </table>
            </div></div></div>
          </div>`;
        if (canEdit) setTimeout(() => { try { wireChargeImageControls(); } catch {} }, 0);
    } else if (page === 'finance') {
        const activeTerm = await API.fetch('/terms/').catch(() => null);
        const defYear = (activeTerm && activeTerm.academic_year) ? activeTerm.academic_year : new Date().getFullYear();
        const defTerm = (activeTerm && activeTerm.term_number) ? activeTerm.term_number : 1;
        const role = (currentUser.profile && currentUser.profile.role) || 'superadmin';
        const canApprove = ['superadmin', 'bursar'].includes(role);
        const canHoldResults = ['superadmin', 'bursar', 'headteacher', 'admin'].includes(role);
        if (!FIN_FILTER.year) FIN_FILTER.year = String(defYear);
        if (!FIN_FILTER.term) FIN_FILTER.term = String(defTerm);
        const selYear = parseInt(FIN_FILTER.year || defYear, 10) || defYear;
        const selTerm = parseInt(FIN_FILTER.term || defTerm, 10) || defTerm;

        const [payments, students, ledger, classes, plansRaw, promisesRaw] = await Promise.all([
            API.fetch('/payments/'),
            API.fetch('/students/'),
            API.fetch(`/invoices/ledger/?year=${encodeURIComponent(selYear)}&term=${encodeURIComponent(selTerm)}`).catch(() => ({ year: selYear, term: selTerm, students: [] })),
            API.fetch('/classes/').catch(() => []),
            API.fetch(`/installment-plans/?year=${encodeURIComponent(selYear)}&term=${encodeURIComponent(selTerm)}`).catch(() => []),
            API.fetch(`/fee-promises/?year=${encodeURIComponent(selYear)}&term=${encodeURIComponent(selTerm)}`).catch(() => []),
        ]);
        const planRows = listDataRows(plansRaw);
        const promiseRows = listDataRows(promisesRaw);
        const classOptionsSimple = (classes || []).map(c => `<option value="${c.id}">${escapeHtml(c.level || '')}</option>`).join('');
        const ledArr = (ledger && ledger.students) ? ledger.students : [];
        const ledMap = new Map(ledArr.map(x => [x.student_id, x]));
        const totalDue = ledArr.reduce((s, x) => s + Number(x.term_due || 0) + Number(x.arrears_brought_forward || 0), 0);
        const totalPaid = ledArr.reduce((s, x) => s + Number(x.paid_applied || 0), 0);
        const totalBal = ledArr.reduce((s, x) => s + Number(x.balance_due || 0), 0);
        const overdueInstallments = planRows.reduce((count, plan) => count + ((plan.items || []).filter(it => String(it.status || '').toLowerCase() === 'overdue').length), 0);
        const dueSoonInstallments = planRows.reduce((count, plan) => count + ((plan.items || []).filter(it => {
            const status = String(it.status || '').toLowerCase();
            return !['paid', 'cancelled'].includes(status) && String(it.due_date || '') >= todayISO() && String(it.due_date || '') <= addDaysISO(7);
        }).length), 0);
        const openPromises = promiseRows.filter(p => String(p.status || '').toLowerCase() === 'open');
        const overduePromises = openPromises.filter(p => isPastIsoDate(p.promised_for));
        const outstandingCommitmentsAmount = openPromises.reduce((sum, p) => sum + Number(p.amount || 0), 0);
        const noFinanceData = !(students || []).length && !(payments || []).length && !planRows.length && !promiseRows.length;
        const stuGroups = (students || []).reduce((acc, s) => {
            const g = `${s.current_class_level || 'Unassigned'}${s.section || ''}`;
            if (!acc[g]) acc[g] = [];
            acc[g].push(s);
            return acc;
        }, {});
        const studentOptions = Object.keys(stuGroups).sort().map(g => {
            const opts = (stuGroups[g] || []).map(s => `<option value="${s.id}">${s.first_name} ${s.last_name} (${s.student_id})</option>`).join('');
            return `<optgroup label="Class ${g}">${opts}</optgroup>`;
        }).join('');
        // Pending approvals are only for bank slips submitted for review.
        const pending = (payments || []).filter(p => (p.method || '').toLowerCase() === 'bank' && (p.status || '').toLowerCase() === 'pending');
        // Pending list is handled on the dedicated Approvals page.

        const rows = (payments || []).slice(0, 60).map(p => `
          <tr>
            <td>${formatDateTime(p.received_at)}</td>
            <td><strong>${p.student_name}</strong><div class="sub">${p.student_system_id}</div></td>
            <td style="font-weight:800;color:var(--m)">UGX ${fmt(p.amount)}</td>
            <td>${p.method}</td>
            <td>
              ${p.receipt_image_url ? `<button class="btn btn-xs btn-ghost" onclick="viewImage('${escapeHtml(p.receipt_image_url)}')">Image</button>` : '-'}
              ${((p.status === 'approved' || p.status === 'received') ? `<button class="btn btn-xs btn-ghost" onclick="openReceiptPdf(${p.id})">PDF</button>` : '')}
              ${p.receipt_number ? `<div class="sub mono">${escapeHtml(p.receipt_number)}</div>` : ''}
            </td>
            <td style="font-size:12px;color:var(--66)">${p.reference || '-'}</td>
            <td>${p.received_by_username || '-'}</td>
            <td>${p.approved_by_username || '-'}</td>
            <td>${p.status}</td>
            <td>
              <button class="btn btn-xs btn-ghost" onclick="openPaymentEdit(${p.id})">Edit</button>
              ${(canApprove && p.status !== 'reversed') ? `<button class="btn btn-xs btn-ghost" onclick="reversePayment(${p.id})">Reverse</button>` : ''}
              ${(canApprove && (p.status === 'pending' || p.status === 'rejected')) ? `<button class="btn btn-xs btn-ghost" onclick="approvePayment(${p.id})">Approve</button>` : ''}
              ${(canApprove && p.status === 'pending') ? `<button class="btn btn-xs btn-ghost" onclick="rejectPayment(${p.id})">Reject</button>` : ''}
              <button class="btn btn-xs btn-ghost" onclick="openStudentHistory(${p.student})">Student</button>
            </td>
          </tr>
        `).join('');
        main.innerHTML = `
          <div class="page">
            <div class="page-hero"><div class="page-title">Payments</div></div>
            ${(!activeTerm || !activeTerm.academic_year) ? `<div class="card" style="border-left:4px solid var(--or)"><div class="card-body"><strong>No active term found.</strong> Payments will still be recorded, but invoice tracking works best after starting a term. <button class="btn btn-xs btn-ghost" onclick="loadPage('terms',null,'Terms')">Start Term</button></div></div><div style="height:12px"></div>` : ''}
            ${noFinanceData ? financeHintCard(
                'Finance workspace is empty',
                'No students or finance records are available yet. Register students first, or use the local demo seed so we can walk through payments, cashbook, installments, promises, and results holds end to end.',
                `<button class="btn btn-xs btn-ghost" onclick="loadPage('students', null, 'Students')">Open Students</button><button class="btn btn-xs btn-ghost" onclick="loadPage('cashbook', null, 'Cashbook')">Open Cashbook</button>`
            ) + '<div style="height:12px"></div>' : ''}
            <div class="card" style="margin-bottom:12px"><div class="card-head"><div class="card-title">Finance Navigator</div><div class="sub">Open a focused page instead of staying in one crowded workspace</div></div><div class="card-body">
              <div class="qa-grid">
                <button class="qa-btn" onclick="loadPage('approvals', null, 'Approvals')"><span class="qi">AP</span><span class="ql">Approvals</span></button>
                <button class="qa-btn" onclick="loadPage('cashbook', null, 'Cashbook')"><span class="qi">CB</span><span class="ql">Cashbook Close</span></button>
                <button class="qa-btn" onclick="loadPage('installment_plans', null, 'Installments')"><span class="qi">IP</span><span class="ql">Installments</span></button>
                <button class="qa-btn" onclick="loadPage('fee_promises', null, 'Fee Promises')"><span class="qi">FP</span><span class="ql">Fee Promises</span></button>
                <button class="qa-btn" onclick="loadPage('deposits', null, 'Deposits')"><span class="qi">DP</span><span class="ql">Deposits</span></button>
                <button class="qa-btn" onclick="loadPage('adjustments', null, 'Adjustments')"><span class="qi">ADJ</span><span class="ql">Adjustments</span></button>
              </div>
            </div></div>
            <div class="card" style="border-left:4px solid var(--m)"><div class="card-body">
              <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                <div class="field" style="margin:0;min-width:160px"><label>Academic Year</label><input class="field-input" id="fin-year" type="number" value="${selYear}"></div>
                <div class="field" style="margin:0;min-width:140px"><label>Term</label>
                  <select class="field-select" id="fin-term">
                    <option value="1" ${selTerm===1?'selected':''}>Term 1</option>
                    <option value="2" ${selTerm===2?'selected':''}>Term 2</option>
                    <option value="3" ${selTerm===3?'selected':''}>Term 3</option>
                  </select>
                </div>
                <button class="btn btn-primary" onclick="setFinanceFilterAndReload()">Load Term Dashboard</button>
                <div class="sub" style="flex:1;min-width:240px">Includes arrears carried forward and credits paid in advance for this term.</div>
              </div>
            </div></div>
            <div class="stats stats-4" style="margin-bottom:12px">
              <div class="stat-card"><div class="stat-num">UGX ${fmt(totalDue.toFixed(0))}</div><div class="stat-label">Due (T${selTerm}/${selYear})</div><div class="stat-accent gold"></div></div>
              <div class="stat-card"><div class="stat-num">UGX ${fmt(totalPaid.toFixed(0))}</div><div class="stat-label">Paid Applied</div><div class="stat-accent green"></div></div>
              <div class="stat-card"><div class="stat-num">UGX ${fmt(totalBal.toFixed(0))}</div><div class="stat-label">Outstanding</div><div class="stat-accent red"></div></div>
              <div class="stat-card"><div class="stat-num">${ledArr.filter(i => i.status !== 'paid').length}</div><div class="stat-label">Defaulters</div><div class="stat-accent blue"></div></div>
            </div>
            ${(planRows.length || promiseRows.length) ? `<div class="stats stats-4" style="margin-bottom:12px">
              <div class="stat-card"><div class="stat-num">${overdueInstallments}</div><div class="stat-label">Overdue Installments</div><div class="stat-accent red"></div></div>
              <div class="stat-card"><div class="stat-num">${dueSoonInstallments}</div><div class="stat-label">Due In 7 Days</div><div class="stat-accent gold"></div></div>
              <div class="stat-card"><div class="stat-num">${openPromises.length}</div><div class="stat-label">Open Promises</div><div class="stat-accent blue"></div></div>
              <div class="stat-card"><div class="stat-num">UGX ${fmt(outstandingCommitmentsAmount.toFixed(0))}</div><div class="stat-label">Promised Amount Open</div><div class="stat-accent green"></div></div>
            </div>` : ''}
            ${(overdueInstallments || overduePromises.length) ? financeHintCard(
                'Collections need attention',
                `There are ${overdueInstallments} overdue installment lines and ${overduePromises.length} overdue fee promises for this term.`,
                `<button class="btn btn-xs btn-ghost" onclick="loadPage('installment_plans', null, 'Installments')">Review Installments</button><button class="btn btn-xs btn-ghost" onclick="loadPage('fee_promises', null, 'Fee Promises')">Review Promises</button>`
            ) + '<div style="height:12px"></div>' : ''}
            <div class="card"><div class="card-body">
              <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
                <button class="btn btn-ghost" onclick="loadPage('approvals', null, 'Approvals')">Open Approvals ${pending.length ? `(${pending.length})` : ''}</button>
                <button class="btn btn-ghost" onclick="loadPage('cashbook', null, 'Cashbook')">Close Cashbook</button>
                <button class="btn btn-ghost" onclick="loadPage('installment_plans', null, 'Installments')">Installments</button>
                <button class="btn btn-ghost" onclick="loadPage('fee_promises', null, 'Fee Promises')">Fee Promises</button>
                <button class="btn btn-ghost" onclick="loadPage('deposits', null, 'Deposits')">Bank Deposits</button>
                <button class="btn btn-ghost" onclick="loadPage('expenses', null, 'Expenses')">Expenses</button>
                <button class="btn btn-ghost" onclick="loadPage('adjustments', null, 'Adjustments')">Adjustments</button>
                <button class="btn btn-ghost" onclick="loadPage('students', null, 'Students')">Student Search</button>
                <div class="sub" style="margin-left:auto">Bursar workspace: record payments, close the day, track commitments, reconcile deposits, and follow every student finance event in one area.</div>
              </div>
            </div></div>
            <div style="height:12px"></div>

            ${canHoldResults ? `
            <div class="card" style="border-left:4px solid var(--bl)"><div class="card-head"><div class="card-title">Results Hold Controls</div><div class="sub">Bulk hold/release by class for the selected term</div></div>
              <div class="card-body">
                <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                  <div class="field" style="margin:0;min-width:240px"><label>Class</label><select class="field-select" id="rh-class"><option value="">All classes</option>${classOptionsSimple}</select></div>
                  <div class="field" style="margin:0;min-width:320px"><label>Hold reason (optional)</label><input class="field-input" id="rh-reason" placeholder="Outstanding fees"></div>
                  <button class="btn btn-ghost" onclick="holdResultsForClass()">Hold Results</button>
                  <button class="btn btn-ghost" onclick="releaseResultsForClass()">Release Results</button>
                  <div style="flex:1"></div>
                  <button class="btn btn-ghost" onclick="loadPage('auditlogs',null,'Audit Logs')">View Audit</button>
                </div>
                <div style="margin-top:8px" class="sub">Partial-release is enabled: parents can see the summary, but the PDF stays blocked until released.</div>
              </div>
            </div>
            <div style="height:12px"></div>` : ''}

            ${(pending.length) ? `
            <div class="card" style="border-left:4px solid var(--or)"><div class="card-head"><div class="card-title">Bank Slip Approvals</div><div class="sub">${pending.length} pending</div></div>
              <div class="card-body" style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;justify-content:space-between">
                <div class="sub">Approvals are handled by the Bursar (or Super Admin) only.</div>
                <button class="btn btn-ghost" onclick="loadPage('approvals', null, 'Approvals')">Open Approvals</button>
              </div>
            </div>
            <div style="height:12px"></div>` : ''}

            <div class="card"><div class="card-body">
              <div style="font-weight:700;margin-bottom:10px">Manual Payment Entry</div>
              ${!(students || []).length ? `<div class="sub" style="margin-bottom:10px;color:var(--66)">No students are available for manual payment entry yet. Register students or seed demo data, then come back here to record cash, bank, MTN, or Airtel collections.</div>` : ''}
              <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                <div class="field" style="margin:0;min-width:320px"><label>Student</label><select class="field-select" id="pay-stu">${studentOptions}</select></div>
                <div class="field" style="margin:0;min-width:160px"><label>Amount (UGX)</label><input class="field-input" id="pay-amt" type="number" min="0"></div>
                <div class="field" style="margin:0;min-width:120px"><label>Term</label><input class="field-input" id="pay-term" type="number" min="1" max="3" value="${defTerm}"></div>
                <div class="field" style="margin:0;min-width:140px"><label>Year</label><input class="field-input" id="pay-year" type="number" value="${defYear}"></div>
                <div class="field" style="margin:0;min-width:180px"><label>Method</label>
                  <select class="field-select" id="pay-method">
                    <option value="cash">cash</option>
                    <option value="bank">bank</option>
                    <option value="mtn_momo">mtn_momo</option>
                    <option value="airtel_money">airtel_money</option>
                    <option value="other">other</option>
                  </select>
                </div>
                <div class="field" style="margin:0;min-width:220px"><label>Reference</label><input class="field-input" id="pay-ref" placeholder="Receipt / Txn ID"></div>
                <div class="field" style="margin:0;min-width:260px"><label>Notes</label><input class="field-input" id="pay-notes" placeholder="Optional"></div>
                <button class="btn btn-primary" onclick="savePayment()" ${!(students || []).length ? 'disabled' : ''}>Record Payment</button>
                <button class="btn btn-ghost" onclick="openStudentHistoryFromPaymentSelect()" ${!(students || []).length ? 'disabled' : ''}>Student History</button>
              </div>
              <div style="height:10px"></div>
              <div class="card" style="border-style:dashed"><div class="card-body" style="padding:12px 14px">
                <div style="font-weight:800;color:var(--md)">Term summary</div>
                <div style="font-size:12px;color:var(--66);margin-top:4px">Showing invoice status for Term <strong>${defTerm}</strong>, Year <strong>${defYear}</strong>.</div>
              </div></div>
              <div style="height:12px"></div>
              <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                <div class="field" style="margin:0;min-width:260px"><label>Search</label><input class="field-input" id="pay-q" placeholder="Student name / ID / reference"></div>
                <div class="field" style="margin:0;min-width:190px"><label>Method</label>
                  <select class="field-select" id="pay-f-method">
                    <option value="">All</option>
                    <option value="cash">cash</option>
                    <option value="bank">bank</option>
                    <option value="mtn_momo">mtn_momo</option>
                    <option value="airtel_money">airtel_money</option>
                    <option value="other">other</option>
                  </select>
                </div>
                <div class="field" style="margin:0;min-width:170px"><label>Status</label>
                  <select class="field-select" id="pay-f-status">
                    <option value="">All</option>
                    <option value="pending">pending</option>
                    <option value="approved">approved</option>
                    <option value="rejected">rejected</option>
                    <option value="received">received</option>
                    <option value="reversed">reversed</option>
                  </select>
                </div>
                <div class="field" style="margin:0;min-width:220px"><label>Class</label>
                  <select class="field-select" id="pay-f-class">
                    <option value="">All</option>
                    ${(classes || []).map(c => `<option value="${c.id}">${c.level}</option>`).join('')}
                  </select>
                </div>
                <div class="field" style="margin:0;min-width:170px"><label>Date From</label><input class="field-input" id="pay-f-from" type="date"></div>
                <div class="field" style="margin:0;min-width:170px"><label>Date To</label><input class="field-input" id="pay-f-to" type="date"></div>
                <button class="btn btn-ghost" onclick="searchPayments()">Search</button>
                <button class="btn btn-ghost" onclick="loadPage('finance')">Reset</button>
              </div>
            </div></div>
            <div style="height:12px"></div>
            <div class="card"><div class="card-head"><div class="card-title">Invoice Status (This Term)</div></div>
              <div class="card-body no-pad"><div class="tw">
                <table class="tbl">
                  <thead><tr><th>Student</th><th>Opening</th><th>Term Due</th><th>Paid Applied</th><th>Balance</th><th>Status</th></tr></thead>
                  <tbody>
                    ${(() => {
                      const grouped = (students || []).reduce((acc, s) => {
                        const key = `${s.current_class_level || 'Unassigned'}${s.section || ''}`;
                        if (!acc[key]) acc[key] = [];
                        acc[key].push(s);
                        return acc;
                      }, {});
                      return Object.keys(grouped).sort().flatMap(key => {
                        const header = `<tr><td colspan="6" style="background:var(--f0);font-weight:900">Class ${key} <span class="sub" style="font-weight:600">(${grouped[key].length} students)</span></td></tr>`;
                        const rows = grouped[key].map(s => {
                          const x = ledMap.get(s.id) || null;
                          const opening = x ? Number(x.opening_balance || 0) : 0;
                          const arrears = x ? Number(x.arrears_brought_forward || 0) : 0;
                          const termDue = x ? Number(x.term_due || 0) : 0;
                          const adj = x ? Number(x.adjustments_total || 0) : 0;
                          const paid = x ? Number(x.paid_applied || 0) : 0;
                          const bal = x ? Number(x.balance_due || 0) : 0;
                          const st = x ? x.status : 'unpaid';
                          const badge = st === 'paid' ? 'green' : (st === 'partial' ? '' : '');
                          const rb = x ? !!x.results_blocked : false;
                          const rbBadge = rb ? `<span class="badge red" title="${escapeHtml(x.results_block_reason || '')}">results held</span>` : '';
                          const rbBtn = (canHoldResults && x && x.invoice_id)
                            ? (rb
                              ? `<button class="btn btn-xs btn-ghost" onclick="unblockResults(${x.invoice_id})">Unblock Results</button>`
                              : `<button class="btn btn-xs btn-ghost" onclick="blockResults(${x.invoice_id}, '${escapeHtml(s.first_name + ' ' + s.last_name)}')">Block Results</button>`)
                            : '';
                          const openLbl = (opening < 0) ? `Arrears UGX ${fmt(Math.abs(opening).toFixed(0))}` : (opening > 0 ? `Credit UGX ${fmt(opening.toFixed(0))}` : '0');
                          const adjLbl = adj ? `<div class="sub" style="margin-top:3px">Adj: <span class="mono">${adj > 0 ? '+' : ''}${fmt(adj.toFixed(0))}</span></div>` : '';
                           return `<tr>
                             <td><strong>${s.first_name} ${s.last_name}</strong><div class="sub">${s.student_id}</div></td>
                             <td style="font-size:12px">${openLbl}</td>
                             <td style="font-weight:800;color:var(--m)">UGX ${fmt((termDue + arrears).toFixed(0))}${adjLbl}</td>
                             <td>UGX ${fmt(paid.toFixed(0))}</td>
                             <td>UGX ${fmt(bal.toFixed(0))}</td>
                             <td>
                               <span class="badge ${badge}">${st}</span>
                               ${rbBadge}
                               <button class="btn btn-xs btn-ghost" onclick="openStudentHistory(${s.id})">History</button>
                               <button class="btn btn-xs btn-ghost" onclick="smsReminder(${s.id}, ${selTerm}, ${selYear})">SMS</button>
                               ${canApprove ? `<button class="btn btn-xs btn-ghost" onclick="openAdjustmentAdd(${s.id}, ${selYear}, ${selTerm})">Adjust</button>` : ''}
                               ${rbBtn}
                             </td>
                           </tr>`;
                         }).join('');
                         return [header, rows];
                       }).join('');
                     })()}
                  </tbody>
                </table>
              </div></div>
            </div>
            <div style="height:12px"></div>
            <div class="card"><div class="card-body no-pad">
              <table class="tbl">
                <thead><tr><th>Time</th><th>Student</th><th>Amount</th><th>Method</th><th>Receipt</th><th>Reference</th><th>Received By</th><th>Approved By</th><th>Status</th><th></th></tr></thead>
                <tbody id="pay-body">${rows}</tbody>
              </table>
            </div></div>
          </div>`;
    } else if (page === 'cashbook') {
        const role = (currentUser.profile && currentUser.profile.role) || 'admin';
        const canFinance = ['superadmin', 'bursar', 'admin', 'headteacher', 'dos', 'deputy'].includes(role);
        if (!canFinance) {
            main.innerHTML = `<div class="page"><div class="card"><div class="card-body">Permission denied.</div></div></div>`;
            return;
        }
        if (!CASHBOOK_FILTER.close_date) CASHBOOK_FILTER.close_date = todayISO();
        const qs = new URLSearchParams({
            close_date: CASHBOOK_FILTER.close_date || todayISO(),
            opening_cash: CASHBOOK_FILTER.opening_cash || '0',
            counted_cash_on_hand: CASHBOOK_FILTER.counted_cash_on_hand || '0',
        });
        if (CASHBOOK_FILTER.cashier) qs.set('cashier', CASHBOOK_FILTER.cashier);
        const closeListQs = new URLSearchParams({ close_date: CASHBOOK_FILTER.close_date || todayISO() });
        if (CASHBOOK_FILTER.cashier) closeListQs.set('cashier', CASHBOOK_FILTER.cashier);
        const [summary, closes, users, handover] = await Promise.all([
            API.fetch(`/cashbook-closes/summary/?${qs.toString()}`).catch(() => null),
            API.fetch(`/cashbook-closes/?${closeListQs.toString()}`).catch(() => []),
            API.fetch('/users/').catch(() => []),
            API.fetch(`/cashbook-closes/handover/?${closeListQs.toString()}`).catch(() => null),
        ]);
        const financeUsers = (users || []).filter(u => ['superadmin', 'bursar', 'admin'].includes((((u || {}).profile || {}).role || '')) || (u && u.id === currentUser.id));
        const cashierOptions = `<option value="">All cashiers</option>` + financeUsers.map(u => `<option value="${u.id}" ${String(CASHBOOK_FILTER.cashier || '') === String(u.id) ? 'selected' : ''}>${escapeHtml(u.username || '')} ${(((u || {}).profile || {}).role ? '· ' + escapeHtml(u.profile.role) : '')}</option>`).join('');
        const byMethodRows = ((summary && summary.by_method) ? summary.by_method : []).map(r => `<tr><td>${escapeHtml(r.method_label || '')}</td><td>${r.count || 0}</td><td style="font-weight:800">UGX ${fmt(Number(r.total_amount || 0).toFixed(0))}</td></tr>`).join('') || `<tr><td colspan="3" style="color:var(--99)">No payments found for this date.</td></tr>`;
        const byCashierRows = ((summary && summary.by_cashier) ? summary.by_cashier : []).map(r => `<tr><td>${escapeHtml(r.cashier_name || '')}</td><td>${r.count || 0}</td><td style="font-weight:800">UGX ${fmt(Number(r.total_amount || 0).toFixed(0))}</td></tr>`).join('') || `<tr><td colspan="3" style="color:var(--99)">No cashier totals yet.</td></tr>`;
        const batchRows = ((summary && summary.deposit_batches) ? summary.deposit_batches : []).map(r => `<tr><td><strong>${escapeHtml(r.batch_name || '')}</strong><div class="sub">${escapeHtml(r.reference || '')}</div></td><td>${r.payments_count || 0}</td><td style="font-weight:800">UGX ${fmt(Number(r.total_amount || 0).toFixed(0))}</td><td><span class="badge ${r.is_posted ? 'green' : ''}">${r.is_posted ? 'posted' : 'open'}</span></td></tr>`).join('') || `<tr><td colspan="4" style="color:var(--99)">No deposit batches on this date.</td></tr>`;
        const expenseRows = ((summary && summary.expenses_by_category) ? summary.expenses_by_category : []).map(r => `<tr><td>${escapeHtml(r.category || '')}</td><td>${r.count || 0}</td><td style="font-weight:800">UGX ${fmt(Number(r.total_amount || 0).toFixed(0))}</td></tr>`).join('') || `<tr><td colspan="3" style="color:var(--99)">No approved expenses on this date.</td></tr>`;
        const closeRows = (closes || []).map(c => `<tr><td>${escapeHtml(c.close_date || '')}</td><td>${escapeHtml(c.cashier_username || 'All cashiers')}</td><td>UGX ${fmt(Number(c.expected_cash_on_hand || 0).toFixed(0))}</td><td>UGX ${fmt(Number(c.counted_cash_on_hand || 0).toFixed(0))}</td><td><span class="badge ${Number(c.variance_amount || 0) === 0 ? 'green' : 'red'}">${Number(c.variance_amount || 0) === 0 ? 'balanced' : 'variance'}</span></td><td style="white-space:nowrap"><button class="btn btn-xs btn-ghost" onclick="openCashbookReport(${c.id})">Print</button></td></tr>`).join('') || `<tr><td colspan="6" style="color:var(--99)">No cashbook closes saved for this filter.</td></tr>`;
        const hasCashbookActivity = Number((summary && summary.payment_count) || 0) > 0 || Number((summary && summary.expense_count) || 0) > 0;
        const hasVariance = Math.abs(Number((summary && summary.variance_amount) || 0)) > 0.009;

        main.innerHTML = `
          <div class="page">
            <div class="page-hero"><div class="page-title">Close-of-Day Cashbook</div><div class="sub">Reconcile by cashier, payment method, deposit batch, and approved expenses.</div></div>
            ${!hasCashbookActivity ? financeHintCard(
                'No finance activity for this date yet',
                'There are no approved payments or expenses matching the current filter. Change the date, clear the cashier filter, or record a few transactions before saving the close.',
                `<button class="btn btn-xs btn-ghost" onclick="loadPage('finance', null, 'Payments')">Open Payments</button><button class="btn btn-xs btn-ghost" onclick="loadPage('expenses', null, 'Expenses')">Open Expenses</button>`
            ) + '<div style="height:12px"></div>' : ''}
            ${hasVariance ? financeHintCard(
                'Variance detected',
                `Expected cash and counted cash do not match for this preview. Add a note before saving so the handover report explains the variance.`,
                `<button class="btn btn-xs btn-ghost" onclick="document.getElementById('cb-notes') && document.getElementById('cb-notes').focus()">Write Variance Note</button>`
            ) + '<div style="height:12px"></div>' : ''}
            <div class="card"><div class="card-body">
              <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                <div class="field" style="margin:0;min-width:180px"><label>Close date</label><input class="field-input" id="cb-date" type="date" value="${escapeHtml(CASHBOOK_FILTER.close_date || todayISO())}"></div>
                <div class="field" style="margin:0;min-width:220px"><label>Cashier</label><select class="field-select" id="cb-cashier">${cashierOptions}</select></div>
                <div class="field" style="margin:0;min-width:180px"><label>Opening cash</label><input class="field-input" id="cb-opening" type="number" min="0" value="${escapeHtml(CASHBOOK_FILTER.opening_cash || '0')}"></div>
                <div class="field" style="margin:0;min-width:180px"><label>Counted cash</label><input class="field-input" id="cb-counted" type="number" min="0" value="${escapeHtml(CASHBOOK_FILTER.counted_cash_on_hand || '0')}"></div>
                <button class="btn btn-primary" onclick="loadCashbookPreview()">Preview</button>
                <button class="btn btn-ghost" onclick="saveCashbookClose()">Save Close</button>
                <button class="btn btn-ghost" onclick="openCashbookHandoverReport()">Print Handover</button>
              </div>
              <div class="field" style="margin:10px 0 0 0"><label>Notes</label><textarea class="field-input" id="cb-notes" style="min-height:80px" placeholder="Any variance explanation, missing slips, or handover notes"></textarea></div>
            </div></div>
            <div style="height:12px"></div>
            ${renderCashierHandoverCard(handover)}
            <div style="height:12px"></div>
            <div class="stats stats-4">
              <div class="stat-card"><div class="stat-num">UGX ${fmt(Number((summary && summary.cash_received_total) || 0).toFixed(0))}</div><div class="stat-label">Cash received</div><div class="stat-accent gold"></div></div>
              <div class="stat-card"><div class="stat-num">UGX ${fmt(Number((summary && summary.approved_expense_total) || 0).toFixed(0))}</div><div class="stat-label">Approved expenses</div><div class="stat-accent red"></div></div>
              <div class="stat-card"><div class="stat-num">UGX ${fmt(Number((summary && summary.expected_cash_on_hand) || 0).toFixed(0))}</div><div class="stat-label">Expected cash</div><div class="stat-accent green"></div></div>
              <div class="stat-card"><div class="stat-num">UGX ${fmt(Number((summary && summary.variance_amount) || 0).toFixed(0))}</div><div class="stat-label">Variance</div><div class="stat-accent blue"></div></div>
            </div>
            <div class="grid-2">
              <div class="card"><div class="card-head"><div class="card-title">By Method</div></div><div class="card-body no-pad"><div class="tw"><table class="tbl"><thead><tr><th>Method</th><th>Count</th><th>Total</th></tr></thead><tbody>${byMethodRows}</tbody></table></div></div></div>
              <div class="card"><div class="card-head"><div class="card-title">By Cashier</div></div><div class="card-body no-pad"><div class="tw"><table class="tbl"><thead><tr><th>Cashier</th><th>Count</th><th>Total</th></tr></thead><tbody>${byCashierRows}</tbody></table></div></div></div>
            </div>
            <div style="height:12px"></div>
            <div class="grid-2">
              <div class="card"><div class="card-head"><div class="card-title">Deposit Batches</div></div><div class="card-body no-pad"><div class="tw"><table class="tbl"><thead><tr><th>Batch</th><th>Count</th><th>Total</th><th>Status</th></tr></thead><tbody>${batchRows}</tbody></table></div></div></div>
              <div class="card"><div class="card-head"><div class="card-title">Approved Expenses</div></div><div class="card-body no-pad"><div class="tw"><table class="tbl"><thead><tr><th>Category</th><th>Count</th><th>Total</th></tr></thead><tbody>${expenseRows}</tbody></table></div></div></div>
            </div>
            <div style="height:12px"></div>
            <div class="card"><div class="card-head"><div class="card-title">Saved Closes</div></div><div class="card-body no-pad"><div class="tw"><table class="tbl"><thead><tr><th>Date</th><th>Cashier</th><th>Expected</th><th>Counted</th><th>Status</th><th></th></tr></thead><tbody>${closeRows}</tbody></table></div></div></div>
          </div>`;
        return;
    } else if (page === 'installment_plans') {
        const role = (currentUser.profile && currentUser.profile.role) || 'admin';
        const canFinance = ['superadmin', 'bursar', 'admin', 'headteacher', 'dos', 'deputy'].includes(role);
        if (!canFinance) {
            main.innerHTML = `<div class="page"><div class="card"><div class="card-body">Permission denied.</div></div></div>`;
            return;
        }
        const yearDefault = Number(FIN_FILTER.year || new Date().getFullYear());
        const termDefault = Number(FIN_FILTER.term || 1);
        if (!PLAN_FILTER.year) PLAN_FILTER.year = String(yearDefault);
        if (!PLAN_FILTER.term) PLAN_FILTER.term = String(termDefault);
        const qs = new URLSearchParams({ year: PLAN_FILTER.year, term: PLAN_FILTER.term });
        if (PLAN_FILTER.status) qs.set('status', PLAN_FILTER.status);
        const [plans, students] = await Promise.all([
            API.fetch(`/installment-plans/?${qs.toString()}`).catch(() => []),
            API.fetch('/students/').catch(() => []),
        ]);
        const planList = listDataRows(plans);
        const studentOptions = groupedStudentOptions(students);
        const activePlans = planList.filter(plan => String(plan.status || '').toLowerCase() === 'active').length;
        const overdueLines = planList.reduce((count, plan) => count + ((plan.items || []).filter(it => String(it.status || '').toLowerCase() === 'overdue').length), 0);
        const dueSoonLines = planList.reduce((count, plan) => count + ((plan.items || []).filter(it => {
            const status = String(it.status || '').toLowerCase();
            return !['paid', 'cancelled'].includes(status) && String(it.due_date || '') >= todayISO() && String(it.due_date || '') <= addDaysISO(7);
        }).length), 0);
        const committedTotal = planList.reduce((sum, plan) => sum + Number(plan.total_amount || 0), 0);
        const rows = planList.map(plan => {
            const items = (plan.items || []).map(it => `<div class="sub">${escapeHtml(it.label || 'Installment')} · ${escapeHtml(it.due_date || '')} · <strong>UGX ${fmt(Number(it.amount || 0).toFixed(0))}</strong> · <span class="badge ${statusBadgeClass(it.status)}">${escapeHtml(it.status || '')}</span></div>`).join('') || `<div class="sub">No schedule lines.</div>`;
            const nextItem = (plan.items || []).find(it => !['paid', 'cancelled'].includes(String(it.status || '').toLowerCase()));
            return `<tr>
              <td><strong>${escapeHtml(plan.student_name || '')}</strong><div class="sub">${escapeHtml(plan.student_system_id || '')}</div></td>
              <td><strong>${escapeHtml(plan.title || '')}</strong><div class="sub">T${plan.term_number}/${plan.academic_year}</div></td>
              <td style="font-weight:800">UGX ${fmt(Number(plan.total_amount || 0).toFixed(0))}</td>
              <td><span class="badge ${statusBadgeClass(plan.status)}">${escapeHtml(plan.status || '')}</span></td>
              <td>${nextItem ? `${escapeHtml(nextItem.due_date || '')} · UGX ${fmt(Number(nextItem.amount || 0).toFixed(0))}` : '-'}</td>
              <td>${items}</td>
              <td style="white-space:nowrap">
                <button class="btn btn-xs btn-ghost" onclick="sendInstallmentReminder(${plan.id})">Remind</button>
                <button class="btn btn-xs btn-ghost" onclick="openStudentHistory(${plan.student})">Timeline</button>
              </td>
            </tr>`;
        }).join('') || `<tr><td colspan="7" style="color:var(--99)">No installment plans found.</td></tr>`;

        main.innerHTML = `
          <div class="page">
            <div class="page-hero"><div class="page-title">Installment Plans</div><div class="sub">Build staged payment schedules and keep reminder history tied to each student.</div></div>
            ${!(students || []).length ? financeHintCard(
                'No students available yet',
                'Installment plans are created per student. Add students first, or seed the local demo dataset so we can test overdue schedules and reminders end to end.',
                `<button class="btn btn-xs btn-ghost" onclick="loadPage('students', null, 'Students')">Open Students</button>`
            ) + '<div style="height:12px"></div>' : ''}
            <div class="stats stats-4" style="margin-bottom:12px">
              <div class="stat-card"><div class="stat-num">${activePlans}</div><div class="stat-label">Active Plans</div><div class="stat-accent blue"></div></div>
              <div class="stat-card"><div class="stat-num">${overdueLines}</div><div class="stat-label">Overdue Lines</div><div class="stat-accent red"></div></div>
              <div class="stat-card"><div class="stat-num">${dueSoonLines}</div><div class="stat-label">Due In 7 Days</div><div class="stat-accent gold"></div></div>
              <div class="stat-card"><div class="stat-num">UGX ${fmt(committedTotal.toFixed(0))}</div><div class="stat-label">Committed Total</div><div class="stat-accent green"></div></div>
            </div>
            ${!planList.length ? financeHintCard(
                'No installment plans match this filter',
                'Create a plan from the form below to spread a balance across scheduled due dates, then send reminders from the plan table.',
                ''
            ) + '<div style="height:12px"></div>' : ''}
            <div class="card"><div class="card-body">
              <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                <div class="field" style="margin:0;min-width:320px"><label>Student</label><select class="field-select" id="ip-student">${studentOptions}</select></div>
                <div class="field" style="margin:0;min-width:150px"><label>Year</label><input class="field-input" id="ip-year" type="number" value="${escapeHtml(PLAN_FILTER.year || String(yearDefault))}"></div>
                <div class="field" style="margin:0;min-width:120px"><label>Term</label><select class="field-select" id="ip-term"><option value="1" ${String(PLAN_FILTER.term) === '1' ? 'selected' : ''}>Term 1</option><option value="2" ${String(PLAN_FILTER.term) === '2' ? 'selected' : ''}>Term 2</option><option value="3" ${String(PLAN_FILTER.term) === '3' ? 'selected' : ''}>Term 3</option></select></div>
                <div class="field" style="margin:0;min-width:220px"><label>Plan title</label><input class="field-input" id="ip-title" value="Fee installment plan"></div>
                <div class="field" style="margin:0;min-width:160px"><label>Total amount</label><input class="field-input" id="ip-total" type="number" min="0"></div>
                <div class="field" style="margin:0;min-width:160px"><label>First due date</label><input class="field-input" id="ip-first-date" type="date" value="${todayISO()}"></div>
                <div class="field" style="margin:0;min-width:130px"><label>Installments</label><input class="field-input" id="ip-count" type="number" min="1" value="3"></div>
                <div class="field" style="margin:0;min-width:140px"><label>Interval days</label><input class="field-input" id="ip-gap" type="number" min="1" value="30"></div>
                <button class="btn btn-primary" onclick="createInstallmentPlan()">Create Plan</button>
              </div>
              <div class="field" style="margin:10px 0 0 0"><label>Notes</label><textarea class="field-input" id="ip-notes" style="min-height:76px" placeholder="Terms agreed with the parent, exceptions, or approval notes"></textarea></div>
            </div></div>
            <div style="height:12px"></div>
            <div class="card"><div class="card-body">
              <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                <div class="field" style="margin:0;min-width:150px"><label>Year</label><input class="field-input" id="ip-f-year" type="number" value="${escapeHtml(PLAN_FILTER.year || String(yearDefault))}"></div>
                <div class="field" style="margin:0;min-width:120px"><label>Term</label><select class="field-select" id="ip-f-term"><option value="1" ${String(PLAN_FILTER.term) === '1' ? 'selected' : ''}>Term 1</option><option value="2" ${String(PLAN_FILTER.term) === '2' ? 'selected' : ''}>Term 2</option><option value="3" ${String(PLAN_FILTER.term) === '3' ? 'selected' : ''}>Term 3</option></select></div>
                <div class="field" style="margin:0;min-width:180px"><label>Status</label><select class="field-select" id="ip-f-status"><option value="">All</option><option value="active" ${PLAN_FILTER.status === 'active' ? 'selected' : ''}>Active</option><option value="completed" ${PLAN_FILTER.status === 'completed' ? 'selected' : ''}>Completed</option><option value="defaulted" ${PLAN_FILTER.status === 'defaulted' ? 'selected' : ''}>Defaulted</option><option value="cancelled" ${PLAN_FILTER.status === 'cancelled' ? 'selected' : ''}>Cancelled</option></select></div>
                <button class="btn btn-ghost" onclick="loadInstallmentPlansFiltered()">Load</button>
              </div>
            </div></div>
            <div style="height:12px"></div>
            <div class="card"><div class="card-body no-pad"><div class="tw"><table class="tbl"><thead><tr><th>Student</th><th>Plan</th><th>Total</th><th>Status</th><th>Next Due</th><th>Schedule</th><th></th></tr></thead><tbody>${rows}</tbody></table></div></div></div>
          </div>`;
        return;
    } else if (page === 'fee_promises') {
        const role = (currentUser.profile && currentUser.profile.role) || 'admin';
        const canFinance = ['superadmin', 'bursar', 'admin', 'headteacher', 'dos', 'deputy'].includes(role);
        if (!canFinance) {
            main.innerHTML = `<div class="page"><div class="card"><div class="card-body">Permission denied.</div></div></div>`;
            return;
        }
        const yearDefault = Number(FIN_FILTER.year || new Date().getFullYear());
        const termDefault = Number(FIN_FILTER.term || 1);
        if (!PROMISE_FILTER.year) PROMISE_FILTER.year = String(yearDefault);
        if (!PROMISE_FILTER.term) PROMISE_FILTER.term = String(termDefault);
        const qs = new URLSearchParams({ year: PROMISE_FILTER.year, term: PROMISE_FILTER.term });
        if (PROMISE_FILTER.status) qs.set('status', PROMISE_FILTER.status);
        const [promises, students] = await Promise.all([
            API.fetch(`/fee-promises/?${qs.toString()}`).catch(() => []),
            API.fetch('/students/').catch(() => []),
        ]);
        const promiseList = listDataRows(promises);
        const studentOptions = groupedStudentOptions(students);
        const openPromiseCount = promiseList.filter(p => String(p.status || '').toLowerCase() === 'open').length;
        const keptPromiseCount = promiseList.filter(p => String(p.status || '').toLowerCase() === 'kept').length;
        const overduePromiseCount = promiseList.filter(p => String(p.status || '').toLowerCase() === 'open' && isPastIsoDate(p.promised_for)).length;
        const openPromiseAmount = promiseList.filter(p => String(p.status || '').toLowerCase() === 'open').reduce((sum, p) => sum + Number(p.amount || 0), 0);
        const rows = promiseList.map(p => `<tr>
          <td><strong>${escapeHtml(p.student_name || '')}</strong><div class="sub">${escapeHtml(p.student_system_id || '')}</div></td>
          <td>${escapeHtml(p.promised_for || '')}</td>
          <td style="font-weight:800">UGX ${fmt(Number(p.amount || 0).toFixed(0))}</td>
          <td><span class="badge ${statusBadgeClass(p.status)}">${escapeHtml(p.status || '')}</span></td>
          <td>${p.reminder_count || 0}</td>
          <td>${escapeHtml(p.notes || '-')}</td>
          <td style="white-space:nowrap">
            <button class="btn btn-xs btn-ghost" onclick="sendFeePromiseReminder(${p.id})">Remind</button>
            ${String(p.status || '').toLowerCase() === 'open' ? `<button class="btn btn-xs btn-ghost" onclick="markFeePromise(${p.id}, 'kept')">Mark Kept</button><button class="btn btn-xs btn-ghost" onclick="markFeePromise(${p.id}, 'missed')">Mark Missed</button>` : ''}
            <button class="btn btn-xs btn-ghost" onclick="openStudentHistory(${p.student})">Timeline</button>
          </td>
        </tr>`).join('') || `<tr><td colspan="7" style="color:var(--99)">No fee promises found.</td></tr>`;
        main.innerHTML = `
          <div class="page">
            <div class="page-hero"><div class="page-title">Fee Promises</div><div class="sub">Track parent commitments, overdue promises, and reminder follow-ups.</div></div>
            ${!(students || []).length ? financeHintCard(
                'No students available yet',
                'Fee promises are recorded against individual students. Add students first, or seed the local demo dataset so we can test reminders and follow-up workflows.',
                `<button class="btn btn-xs btn-ghost" onclick="loadPage('students', null, 'Students')">Open Students</button>`
            ) + '<div style="height:12px"></div>' : ''}
            <div class="stats stats-4" style="margin-bottom:12px">
              <div class="stat-card"><div class="stat-num">${openPromiseCount}</div><div class="stat-label">Open Promises</div><div class="stat-accent blue"></div></div>
              <div class="stat-card"><div class="stat-num">${overduePromiseCount}</div><div class="stat-label">Overdue Promises</div><div class="stat-accent red"></div></div>
              <div class="stat-card"><div class="stat-num">${keptPromiseCount}</div><div class="stat-label">Kept Promises</div><div class="stat-accent green"></div></div>
              <div class="stat-card"><div class="stat-num">UGX ${fmt(openPromiseAmount.toFixed(0))}</div><div class="stat-label">Amount Still Promised</div><div class="stat-accent gold"></div></div>
            </div>
            ${!promiseList.length ? financeHintCard(
                'No fee promises match this filter',
                'Record promises whenever a parent commits to a future payment date so the bursar can follow up and track which commitments were kept.',
                ''
            ) + '<div style="height:12px"></div>' : ''}
            <div class="card"><div class="card-body">
              <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                <div class="field" style="margin:0;min-width:320px"><label>Student</label><select class="field-select" id="fp-student">${studentOptions}</select></div>
                <div class="field" style="margin:0;min-width:150px"><label>Year</label><input class="field-input" id="fp-year" type="number" value="${escapeHtml(PROMISE_FILTER.year || String(yearDefault))}"></div>
                <div class="field" style="margin:0;min-width:120px"><label>Term</label><select class="field-select" id="fp-term"><option value="1" ${String(PROMISE_FILTER.term) === '1' ? 'selected' : ''}>Term 1</option><option value="2" ${String(PROMISE_FILTER.term) === '2' ? 'selected' : ''}>Term 2</option><option value="3" ${String(PROMISE_FILTER.term) === '3' ? 'selected' : ''}>Term 3</option></select></div>
                <div class="field" style="margin:0;min-width:160px"><label>Promised amount</label><input class="field-input" id="fp-amount" type="number" min="0"></div>
                <div class="field" style="margin:0;min-width:170px"><label>Promise date</label><input class="field-input" id="fp-date" type="date" value="${todayISO()}"></div>
                <button class="btn btn-primary" onclick="createFeePromise()">Save Promise</button>
              </div>
              <div class="field" style="margin:10px 0 0 0"><label>Notes</label><textarea class="field-input" id="fp-notes" style="min-height:76px" placeholder="Who committed, any partial conditions, and agreed follow-up date"></textarea></div>
            </div></div>
            <div style="height:12px"></div>
            <div class="card"><div class="card-body">
              <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                <div class="field" style="margin:0;min-width:150px"><label>Year</label><input class="field-input" id="fp-f-year" type="number" value="${escapeHtml(PROMISE_FILTER.year || String(yearDefault))}"></div>
                <div class="field" style="margin:0;min-width:120px"><label>Term</label><select class="field-select" id="fp-f-term"><option value="1" ${String(PROMISE_FILTER.term) === '1' ? 'selected' : ''}>Term 1</option><option value="2" ${String(PROMISE_FILTER.term) === '2' ? 'selected' : ''}>Term 2</option><option value="3" ${String(PROMISE_FILTER.term) === '3' ? 'selected' : ''}>Term 3</option></select></div>
                <div class="field" style="margin:0;min-width:180px"><label>Status</label><select class="field-select" id="fp-f-status"><option value="">All</option><option value="open" ${PROMISE_FILTER.status === 'open' ? 'selected' : ''}>Open</option><option value="kept" ${PROMISE_FILTER.status === 'kept' ? 'selected' : ''}>Kept</option><option value="missed" ${PROMISE_FILTER.status === 'missed' ? 'selected' : ''}>Missed</option><option value="cancelled" ${PROMISE_FILTER.status === 'cancelled' ? 'selected' : ''}>Cancelled</option></select></div>
                <button class="btn btn-ghost" onclick="loadFeePromisesFiltered()">Load</button>
              </div>
            </div></div>
            <div style="height:12px"></div>
            <div class="card"><div class="card-body no-pad"><div class="tw"><table class="tbl"><thead><tr><th>Student</th><th>Due</th><th>Amount</th><th>Status</th><th>Reminders</th><th>Notes</th><th></th></tr></thead><tbody>${rows}</tbody></table></div></div></div>
          </div>`;
        return;
    } else if (page === 'my_fees') {
        const role = (currentUser.profile && currentUser.profile.role) || 'parent';
        if (!['parent', 'student'].includes(role)) {
            main.innerHTML = `<div class="page"><div class="card"><div class="card-body">You do not have access to this page.</div></div></div>`;
            return;
        }
        const [inv, pays] = await Promise.all([
            API.fetch('/invoices/mine/').catch(() => ({ term: null, students: [] })),
            API.fetch('/payments/mine/').catch(() => []),
        ]);
        const term = inv ? inv.term : null;
        const termLbl = term ? `Term ${term.term_number} - ${term.academic_year}` : 'No active term';
        const payByStu = (pays || []).reduce((acc, p) => {
            const sid = p.student;
            if (!acc[sid]) acc[sid] = [];
            acc[sid].push(p);
            return acc;
        }, {});

        const cards = ((inv && inv.students) ? inv.students : []).map(x => {
            const s = x.student || {};
            const items = x.charge_items || [];
            const base = Number(x.base_due || 0);
            const extras = Number(x.extras_total || 0);
            const adj = Number(x.adjustments_total || 0);
            const total = Number(x.total_due || 0);
            const paid = Number(x.paid || 0);
            const bal = Number(x.balance || 0);
            const recent = (payByStu[s.id] || []).slice(0, 6).map(p => `<div class="ri"><div class="ri-info"><div class="rn">UGX ${fmt(p.amount || 0)} <span class="sub">${escapeHtml(p.method || '')}</span></div><div class="rd">${(p.received_at || '').toString().slice(0, 19).replace('T',' ')}</div></div><div class="ri-end"><span class="badge ${p.status==='approved'||p.status==='received'?'green':''}">${escapeHtml(p.status || '')}</span></div></div>`).join('') || `<div class="sub">No payments recorded yet.</div>`;
            const itemRows = (items || []).map(c => `<tr><td><strong>${escapeHtml(c.title || '')}</strong><div class="sub">${escapeHtml(c.description || '')}</div></td><td style="font-weight:900;color:var(--m)">UGX ${fmt(c.amount || 0)}</td><td style="font-size:12px;color:var(--66)">${c.due_date || '-'}</td></tr>`).join('') || `<tr><td colspan="3" style="color:var(--99)">No additional class charges.</td></tr>`;
            const slipItems = (payByStu[s.id] || []).filter(p => (p.method || '').toLowerCase() === 'bank').slice(0, 6).map(p => `
              <div class="ri">
                <div class="ri-info">
                  <div class="rn">Bank slip: UGX ${fmt(p.amount || 0)} <span class="sub">${escapeHtml(p.status || '')}</span></div>
                  <div class="rd">${(p.received_at || '').toString().slice(0, 19).replace('T',' ')}</div>
                </div>
                <div class="ri-end">
                  ${p.receipt_image_url ? `<button class="btn btn-xs btn-ghost" onclick="viewImage('${escapeHtml(p.receipt_image_url)}','Bank Slip')">View</button>` : ''}
                  ${(p.status === 'approved' || p.status === 'received') ? `<button class="btn btn-xs btn-ghost" onclick="openReceiptPdf(${p.id})">Receipt PDF</button>` : ''}
                </div>
              </div>`).join('') || `<div class="sub">No bank slip submissions.</div>`;
            const statementYear = term ? Number(term.academic_year || 0) : currentYear();
            return `
              <div class="card" style="border-left:4px solid var(--m);margin-bottom:12px">
                <div class="card-head"><div class="card-title">${escapeHtml((s.first_name||'') + ' ' + (s.last_name||''))}</div><div class="sub">${escapeHtml(s.student_id || '')} · ${escapeHtml((s.current_class_level||'-') + (s.section||''))}</div></div>
                <div class="card-body">
                  <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;justify-content:flex-end;margin-bottom:8px">
                    <button class="btn btn-xs btn-ghost" onclick="openStatementPdf(${s.id}, ${statementYear})">Statement PDF (${statementYear})</button>
                  </div>
                  <div class="stats stats-4" style="margin:0">
                    <div class="stat-card"><div class="stat-num">UGX ${fmt(base)}</div><div class="stat-label">Base Fees</div><div class="stat-accent gold"></div></div>
                    <div class="stat-card"><div class="stat-num">UGX ${fmt(extras)}</div><div class="stat-label">Extras</div><div class="stat-accent blue"></div></div>
                    <div class="stat-card"><div class="stat-num">UGX ${fmt(paid)}</div><div class="stat-label">Paid</div><div class="stat-accent green"></div></div>
                    <div class="stat-card"><div class="stat-num">UGX ${fmt(bal)}</div><div class="stat-label">Balance</div><div class="stat-accent red"></div></div>
                  </div>
                  ${adj ? `<div class="sub" style="margin-top:10px">Adjustments applied this term: <span class="mono">${adj > 0 ? '+' : ''}${fmt(adj)}</span></div>` : ''}
                  <div style="height:12px"></div>
                  <div class="card" style="margin:0"><div class="card-head"><div class="card-title">Additional Requirements</div></div>
                    <div class="card-body no-pad"><div class="tw"><table class="tbl"><thead><tr><th>Item</th><th>Amount</th><th>Due</th></tr></thead><tbody>${itemRows}</tbody></table></div></div>
                  </div>
                  <div style="height:12px"></div>
                  <div class="card" style="margin:0"><div class="card-head"><div class="card-title">Recent Payments</div></div><div class="card-body">${recent}</div></div>
                  <div style="height:12px"></div>
                  <div class="card" style="margin:0"><div class="card-head"><div class="card-title">Submit Bank Slip (For Approval)</div></div>
                    <div class="card-body">
                      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                        <div class="field" style="margin:0;min-width:180px"><label>Amount (UGX)</label><input class="field-input" id="bs-amt-${s.id}" type="number" min="0" placeholder="e.g. 50000"></div>
                        <div class="field" style="margin:0;min-width:220px"><label>Reference (optional)</label><input class="field-input" id="bs-ref-${s.id}" placeholder="Bank ref / transaction id"></div>
                        <div class="field" style="margin:0;min-width:320px"><label>Slip Photo</label>
                          <input type="hidden" id="bs-img-${s.id}" value="">
                          <input type="file" id="bs-file-${s.id}" accept="image/*" style="display:none">
                          <div class="dropzone" id="bs-drop-${s.id}">
                            <div style="font-weight:800">Click or drop the bank slip image</div>
                            <div class="sub">JPG/PNG, max 2MB</div>
                          </div>
                          <div id="bs-prev-wrap-${s.id}" style="display:none;margin-top:8px">
                            <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
                              <div style="width:62px;height:62px;border-radius:12px;overflow:hidden;border:1px solid var(--e);background:#fff">
                                <img id="bs-prev-${s.id}" alt="Bank Slip" src="" style="width:62px;height:62px;object-fit:cover">
                              </div>
                              <button class="btn btn-xs btn-ghost" onclick="clearBankSlipImage(${s.id})">Remove Image</button>
                            </div>
                          </div>
                        </div>
                        <button class="btn btn-primary" onclick="submitBankSlip(${s.id}, ${term ? Number(term.academic_year || 0) : 0}, ${term ? Number(term.term_number || 0) : 0})">Submit</button>
                      </div>
                      <div style="height:10px"></div>
                      <div style="font-weight:900;margin-bottom:8px">My Bank Slip Submissions</div>
                      ${slipItems}
                    </div>
                  </div>
                  <div class="sub" style="margin-top:10px">Total due = base fees + extras for this term. If you think something is wrong, contact the bursar.</div>
                </div>
              </div>`;
        }).join('');

        main.innerHTML = `
          <div class="page">
            <div class="page-hero"><div><div class="page-title">My Fees</div><div class="sub">${termLbl}</div></div></div>
            ${cards || `<div class="card"><div class="card-body">No linked students found.</div></div>`}
          </div>`;
        setTimeout(() => { try { wireBankSlipZones(); } catch {} }, 0);
    } else if (page === 'approvals') {
        const role = (currentUser.profile && currentUser.profile.role) || 'admin';
        const canFinance = ['superadmin', 'bursar', 'admin', 'headteacher', 'dos', 'deputy'].includes(role);
        const canAct = ['superadmin', 'bursar'].includes(role);
        if (!canFinance) {
            main.innerHTML = `<div class="page"><div class="card"><div class="card-body">Permission denied.</div></div></div>`;
            return;
        }

        const statusSel = (APPR_FILTER.status || 'pending');
        const methodSel = (APPR_FILTER.method || 'bank');
        const q = (APPR_FILTER.q || '').trim();
        const qs = new URLSearchParams();
        if (statusSel) qs.set('status', statusSel);
        if (methodSel) qs.set('method', methodSel);
        if (q) qs.set('q', q);

        const items = await API.fetch(`/payments/?${qs.toString()}`).catch(() => []);
        const pending = (items || []).filter(p => (p.status || '').toLowerCase() === 'pending');
        const pendingBank = pending.filter(p => (p.method || '').toLowerCase() === 'bank');
        const totalAmt = pendingBank.reduce((s, p) => s + Number(p.amount || 0), 0);

        const rows = (items || []).slice(0, 240).map(p => {
            const dt = formatDateTime(p.received_at, '-');
            const termLbl2 = (p.academic_year && p.term_number) ? `T${p.term_number}/${p.academic_year}` : '-';
            const sb = escapeHtml(p.submitted_by_username || '');
            const slipBtn = p.receipt_image_url ? `<button class="btn btn-xs btn-ghost" onclick="viewImage('${escapeHtml(p.receipt_image_url)}','Bank Slip')">View Slip</button>` : '';
            const pdfBtn = (p.status === 'approved' || p.status === 'received') ? `<button class="btn btn-xs btn-ghost" onclick="openReceiptPdf(${p.id})">PDF</button>` : '';
            const reviewBtn = (canAct && (p.status === 'pending' || p.status === 'rejected')) ? `<button class="btn btn-xs btn-ghost" onclick="openApprovalModal(${p.id})">Review</button>` : '';
            const canSelect = (canAct && (p.status === 'pending' || p.status === 'rejected'));
            const sel = canSelect ? `<input class="appr-cb" type="checkbox" data-id="${p.id}" ${APPR_SELECTED.has(p.id) ? 'checked' : ''} onchange="apprToggleOne(${p.id}, this.checked)">` : '';
            return `<tr>
              <td style="width:34px">${sel}</td>
              <td style="white-space:nowrap">${dt}</td>
              <td><strong>${escapeHtml(p.student_system_id || '')}</strong><div class="sub">${escapeHtml(p.student_name || '')}</div></td>
              <td style="font-weight:900">UGX ${fmt(Number(p.amount || 0).toFixed(0))}</td>
              <td>${escapeHtml(p.method || '')}<div class="sub">${escapeHtml(p.status || '')}</div></td>
              <td>${escapeHtml(p.reference || '')}</td>
              <td>${termLbl2}</td>
              <td>${sb || '-'}</td>
              <td style="white-space:nowrap">${slipBtn} ${pdfBtn}</td>
              <td style="white-space:nowrap">${reviewBtn}</td>
            </tr>`;
        }).join('');

        main.innerHTML = `
          <div class="page">
            <div class="page-hero"><div class="page-title">Payment Approvals</div></div>

            <div class="stats stats-4">
              <div class="stat-card"><div class="stat-num">${pendingBank.length}</div><div class="stat-label">Pending bank slips</div><div class="stat-accent gold"></div></div>
              <div class="stat-card"><div class="stat-num">UGX ${fmt(totalAmt.toFixed(0))}</div><div class="stat-label">Total pending amount</div><div class="stat-accent blue"></div></div>
              <div class="stat-card"><div class="stat-num">${pending.length}</div><div class="stat-label">All pending methods</div><div class="stat-accent red"></div></div>
              <div class="stat-card"><div class="stat-num">PDF</div><div class="stat-label">Receipt on approve</div><div class="stat-accent green"></div></div>
            </div>

            <div class="card"><div class="card-body">
              <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                <div class="field" style="margin:0;min-width:170px"><label>Status</label>
                  <select class="field-select" id="appr-status">
                    <option value="">All</option>
                    <option value="pending" ${statusSel === 'pending' ? 'selected' : ''}>Pending</option>
                    <option value="approved" ${statusSel === 'approved' ? 'selected' : ''}>Approved</option>
                    <option value="rejected" ${statusSel === 'rejected' ? 'selected' : ''}>Rejected</option>
                    <option value="received" ${statusSel === 'received' ? 'selected' : ''}>Received</option>
                    <option value="reversed" ${statusSel === 'reversed' ? 'selected' : ''}>Reversed</option>
                  </select>
                </div>
                <div class="field" style="margin:0;min-width:170px"><label>Method</label>
                  <select class="field-select" id="appr-method">
                    <option value="">All</option>
                    <option value="bank" ${methodSel === 'bank' ? 'selected' : ''}>Bank</option>
                    <option value="mtn_momo" ${methodSel === 'mtn_momo' ? 'selected' : ''}>MTN MoMo</option>
                    <option value="airtel_money" ${methodSel === 'airtel_money' ? 'selected' : ''}>Airtel</option>
                    <option value="cash" ${methodSel === 'cash' ? 'selected' : ''}>Cash</option>
                    <option value="other" ${methodSel === 'other' ? 'selected' : ''}>Other</option>
                  </select>
                </div>
                <div class="field" style="margin:0;min-width:260px;flex:1"><label>Search</label><input class="field-input" id="appr-q" placeholder="Student ID / name / reference" value="${escapeHtml(q)}"></div>
                <button class="btn btn-primary" onclick="APPR_FILTER.status=document.getElementById('appr-status').value; APPR_FILTER.method=document.getElementById('appr-method').value; APPR_FILTER.q=document.getElementById('appr-q').value; loadPage('approvals', null, 'Approvals')">Load</button>
                <button class="btn btn-ghost" onclick="APPR_FILTER={status:'pending',method:'bank',q:''}; loadPage('approvals', null, 'Approvals')">Reset</button>
                <div style="flex:1"></div>
                <div id="appr-selmeta" class="sub" style="margin-bottom:2px">Selected: ${APPR_SELECTED.size || 0}</div>
                ${canAct ? `<button class="btn btn-ghost" onclick="openBulkReviewModal()">Bulk Review</button>` : ''}
                ${canAct ? `<button class="btn btn-ghost" onclick="apprClearSelection()">Clear</button>` : ''}
                <button class="btn btn-ghost" onclick="window.open('/api/payments/export-csv/?'+new URLSearchParams({status:document.getElementById('appr-status').value, method:document.getElementById('appr-method').value, q:document.getElementById('appr-q').value}).toString(), '_blank')">Export CSV</button>
              </div>
              <div class="sub" style="margin-top:10px">Only bank slip payments should be approved here. Approve generates a receipt number and updates the invoice automatically.</div>
            </div></div>

            <div style="height:12px"></div>
            <div class="card"><div class="card-body no-pad"><div class="tw">
              <table class="tbl">
                <thead><tr>
                  <th style="width:34px">${canAct ? `<input id="appr-all" type="checkbox" onchange="apprToggleAll(this.checked)">` : ''}</th>
                  <th>Date</th><th>Student</th><th>Amount</th><th>Method/Status</th><th>Reference</th><th>Term</th><th>Submitted By</th><th>Slip</th><th></th>
                </tr></thead>
                <tbody>${rows || ''}</tbody>
              </table>
            </div></div></div>
          </div>`;
        setTimeout(() => { try { apprUpdateSelectionMeta(); } catch {} }, 0);
    } else if (page === 'deposits') {
        const role = (currentUser.profile && currentUser.profile.role) || 'admin';
        const canFinance = ['superadmin', 'bursar', 'admin', 'headteacher', 'dos', 'deputy'].includes(role);
        if (!canFinance) {
            main.innerHTML = `<div class="page"><div class="card"><div class="card-body">Permission denied.</div></div></div>`;
            return;
        }

        const [batches, unbatched] = await Promise.all([
            API.fetch('/deposit-batches/').catch(() => []),
            API.fetch('/payments/?method=bank&status=approved&unbatched=1').catch(() => []),
        ]);

        const batchRows = (batches || []).slice(0, 200).map(b => `
          <tr>
            <td>${escapeHtml(b.deposit_date || '')}</td>
            <td><strong>${escapeHtml(b.name || ('Batch #' + b.id))}</strong><div class="sub">${escapeHtml(b.bank_name || '')}</div></td>
            <td>${escapeHtml(b.reference || '')}</td>
            <td>${b.total_amount ? `UGX ${fmt(Number(b.total_amount || 0).toFixed(0))}` : '-'}</td>
            <td>${b.payments_count ?? '-'}</td>
            <td>${b.is_posted ? '<span class="badge red">Posted</span>' : '<span class="badge green">Open</span>'}</td>
            <td style="white-space:nowrap">
              <button class="btn btn-xs btn-ghost" onclick="openDepositBatch(${b.id})">Open</button>
              ${b.slip_image_url ? `<button class="btn btn-xs btn-ghost" onclick="viewImage('${escapeHtml(b.slip_image_url)}','Deposit Slip')">Slip</button>` : ''}
              ${!b.is_posted ? `<button class="btn btn-xs btn-ghost" onclick="markDepositPosted(${b.id})">Mark Posted</button>` : ''}
            </td>
          </tr>`).join('') || `<tr><td colspan="7" style="color:var(--99)">No deposit batches yet.</td></tr>`;

        const payRows = (unbatched || []).slice(0, 300).map(p => `
          <tr>
            <td style="width:34px"><input class="dep-cb" type="checkbox" data-id="${p.id}"></td>
            <td>${formatDateTime(p.received_at, '-')}</td>
            <td><strong>${escapeHtml(p.student_system_id || '')}</strong><div class="sub">${escapeHtml(p.student_name || '')}</div></td>
            <td style="font-weight:900">UGX ${fmt(Number(p.amount || 0).toFixed(0))}</td>
            <td>${escapeHtml(p.reference || '')}</td>
            <td style="white-space:nowrap">${p.receipt_image_url ? `<button class="btn btn-xs btn-ghost" onclick="viewImage('${escapeHtml(p.receipt_image_url)}','Bank Slip')">Slip</button>` : ''}</td>
          </tr>`).join('') || `<tr><td colspan="6" style="color:var(--99)">No approved unbatched bank payments.</td></tr>`;

        main.innerHTML = `
          <div class="page">
            <div class="page-hero"><div class="page-title">Bank Deposits</div></div>

            <div class="grid-2">
              <div class="card">
                <div class="card-head"><div class="card-title">Create Deposit Batch</div></div>
                <div class="card-body">
                  <div class="field" style="margin:0 0 10px 0"><label>Name</label><input class="field-input" id="dep-name" placeholder="e.g. Banking ${todayISO()}"></div>
                  <div class="field" style="margin:0 0 10px 0"><label>Bank Name</label><input class="field-input" id="dep-bank" placeholder="e.g. Stanbic"></div>
                  <div class="field" style="margin:0 0 10px 0"><label>Deposit Date</label><input class="field-input" id="dep-date" type="date" value="${todayISO()}"></div>
                  <div class="field" style="margin:0 0 10px 0"><label>Deposit Reference (optional)</label><input class="field-input" id="dep-ref" placeholder="Bank deposit reference"></div>
                  <div class="field" style="margin:0 0 10px 0"><label>Deposit Slip Photo (optional)</label>
                    <input type="file" id="dep-slip-file" accept="image/*">
                    <div class="sub">You can upload after creating too.</div>
                  </div>
                  <div class="field" style="margin:0"><label>Notes (optional)</label><textarea class="field-input" id="dep-notes" style="min-height:90px"></textarea></div>
                  <div style="height:10px"></div>
                  <button class="btn btn-primary" onclick="createDepositBatchFromSelected()">Create Batch From Selected Payments</button>
                  <button class="btn btn-ghost" onclick="document.querySelectorAll('.dep-cb').forEach(cb=>cb.checked=false); flash('Selection cleared.');">Clear Selection</button>
                </div>
              </div>

              <div class="card">
                <div class="card-head"><div class="card-title">Unbatched Approved Bank Payments</div><div class="sub">${(unbatched||[]).length} items</div></div>
                <div class="card-body no-pad"><div class="tw">
                  <table class="tbl"><thead><tr><th style="width:34px"></th><th>Date</th><th>Student</th><th>Amount</th><th>Reference</th><th></th></tr></thead><tbody>${payRows}</tbody></table>
                </div></div>
              </div>
            </div>

            <div style="height:12px"></div>
            <div class="card">
              <div class="card-head"><div class="card-title">Deposit Batches</div><div class="sub">${(batches||[]).length} total</div></div>
              <div class="card-body no-pad"><div class="tw">
                <table class="tbl"><thead><tr><th>Date</th><th>Batch</th><th>Ref</th><th>Total</th><th>Count</th><th>Status</th><th></th></tr></thead><tbody>${batchRows}</tbody></table>
              </div></div>
            </div>
          </div>`;
        return;
    } else if (page === 'expenses') {
        const role = (currentUser.profile && currentUser.profile.role) || 'admin';
        const canFinance = ['superadmin', 'bursar', 'admin', 'headteacher', 'dos', 'deputy'].includes(role);
        if (!canFinance) {
            main.innerHTML = `<div class="page"><div class="card"><div class="card-body">Permission denied.</div></div></div>`;
            return;
        }

        const now = new Date();
        const defY = now.getFullYear();
        const defM = now.getMonth() + 1;
        const statusSel = (document.getElementById('ex-f-status')?.value || 'pending').trim();
        const qs = new URLSearchParams({ year: String(defY), month: String(defM) });
        if (statusSel) qs.set('status', statusSel);

        const [cats, exps] = await Promise.all([
            API.fetch('/expense-categories/').catch(() => []),
            API.fetch(`/expenses/?${qs.toString()}`).catch(() => []),
        ]);

        const catOpts = (cats || []).filter(c => c.is_active !== false).map(c => `<option value="${c.id}">${escapeHtml(c.name || '')}</option>`).join('');
        const rows = (exps || []).slice(0, 260).map(e => `
          <tr>
            <td>${escapeHtml(e.expense_date || '')}</td>
            <td><strong>${escapeHtml(e.category_name || '-')}</strong><div class="sub">${escapeHtml(e.vendor || '')}</div></td>
            <td style="font-weight:900">UGX ${fmt(Number(e.amount || 0).toFixed(0))}</td>
            <td>${escapeHtml(e.status || '')}</td>
            <td style="white-space:nowrap">
              ${e.receipt_image_url ? `<button class="btn btn-xs btn-ghost" onclick="viewImage('${escapeHtml(e.receipt_image_url)}','Expense Receipt')">Receipt</button>` : ''}
              ${e.status === 'pending' ? `<button class="btn btn-xs btn-ghost" onclick="approveExpense(${e.id})">Approve</button>` : ''}
              ${e.status === 'pending' ? `<button class="btn btn-xs btn-ghost" onclick="rejectExpense(${e.id})">Reject</button>` : ''}
            </td>
          </tr>`).join('') || `<tr><td colspan="5" style="color:var(--99)">No expenses found.</td></tr>`;

        main.innerHTML = `
          <div class="page">
            <div class="page-hero"><div class="page-title">Expenses</div></div>

            <div class="grid-2">
              <div class="card">
                <div class="card-head"><div class="card-title">Add Expense</div></div>
                <div class="card-body">
                  <div class="field" style="margin:0 0 10px 0"><label>Date</label><input class="field-input" id="ex-date" type="date" value="${todayISO()}"></div>
                  <div class="field" style="margin:0 0 10px 0"><label>Category</label><select class="field-select" id="ex-cat">${catOpts}</select></div>
                  <div class="field" style="margin:0 0 10px 0"><label>Amount (UGX)</label><input class="field-input" id="ex-amt" type="number" min="0"></div>
                  <div class="field" style="margin:0 0 10px 0"><label>Vendor (optional)</label><input class="field-input" id="ex-vendor"></div>
                  <div class="field" style="margin:0 0 10px 0"><label>Description</label><textarea class="field-input" id="ex-desc" style="min-height:90px"></textarea></div>
                  <div class="field" style="margin:0 0 10px 0"><label>Receipt Photo (optional)</label><input type="file" id="ex-receipt" accept="image/*"></div>
                  <button class="btn btn-primary" onclick="createExpense()">Save Expense</button>
                </div>
              </div>

              <div class="card">
                <div class="card-head"><div class="card-title">Categories</div></div>
                <div class="card-body">
                  <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                    <div class="field" style="margin:0;flex:1"><label>New category</label><input class="field-input" id="ex-cat-name" placeholder="e.g. Utilities"></div>
                    <button class="btn btn-ghost" onclick="createExpenseCategory()">Add</button>
                  </div>
                  <div class="sub" style="margin-top:10px">${(cats||[]).length} categories</div>
                </div>
              </div>
            </div>

            <div style="height:12px"></div>
            <div class="card"><div class="card-head"><div class="card-title">This Month</div><div class="sub">${defY}-${pad2(defM)}</div></div>
              <div class="card-body no-pad"><div class="tw">
                <table class="tbl"><thead><tr><th>Date</th><th>Category</th><th>Amount</th><th>Status</th><th></th></tr></thead><tbody>${rows}</tbody></table>
              </div></div>
            </div>
          </div>`;
        return;
    } else if (page === 'adjustments') {
        const role = (currentUser.profile && currentUser.profile.role) || 'admin';
        const canEdit = ['superadmin', 'bursar', 'admin', 'headteacher', 'deputy', 'dos'].includes(role);
        if (!canEdit) {
            main.innerHTML = `<div class="page"><div class="card"><div class="card-body">You do not have access to this page.</div></div></div>`;
            return;
        }

        const activeTerm = await API.fetch('/terms/').catch(() => null);
        const defYear = (activeTerm && activeTerm.academic_year) ? activeTerm.academic_year : new Date().getFullYear();
        const defTerm = (activeTerm && activeTerm.term_number) ? activeTerm.term_number : 1;

        const year = (document.getElementById('adj-f-year')?.value || '').trim() || String(defYear);
        const term = (document.getElementById('adj-f-term')?.value || '').trim() || String(defTerm);
        const kind = (document.getElementById('adj-f-kind')?.value || '').trim();
        const q = (document.getElementById('adj-f-q')?.value || '').trim();
        const active = (document.getElementById('adj-f-act')?.value || '1').trim();

        const qs = new URLSearchParams();
        if (year) qs.set('year', year);
        if (term) qs.set('term', term);
        if (kind) qs.set('kind', kind);
        if (active) qs.set('active', active);

        const [items, students] = await Promise.all([
            API.fetch(`/invoice-adjustments/?${qs.toString()}`).catch(() => []),
            API.fetch('/students/').catch(() => []),
        ]);

        const byId = new Map((students || []).map(s => [s.id, s]));
        const filtered = (items || []).filter(a => {
            if (!q) return true;
            const s = byId.get(a.student) || {};
            const name = `${s.first_name || ''} ${s.last_name || ''} ${s.student_id || ''}`.toLowerCase();
            const t = `${a.title || ''} ${a.notes || ''} ${a.kind || ''}`.toLowerCase();
            return name.includes(q.toLowerCase()) || t.includes(q.toLowerCase());
        });

        const rows = (filtered || []).slice().sort((a, b) => (b.id || 0) - (a.id || 0)).map(a => {
            const s = byId.get(a.student) || {};
            const amt = Number(a.amount || 0);
            const badge = amt < 0 ? 'green' : (amt > 0 ? 'red' : '');
            return `<tr>
              <td><strong>${escapeHtml((s.first_name || '') + ' ' + (s.last_name || ''))}</strong><div class="sub">${escapeHtml(s.student_id || '')}</div></td>
              <td>${escapeHtml(String(a.academic_year || ''))} / T${escapeHtml(String(a.term_number || ''))}</td>
              <td><span class="badge">${escapeHtml(a.kind || '')}</span></td>
              <td style="font-weight:900;color:var(--m)"><span class="badge ${badge}">${amt < 0 ? '-' : '+'}</span> UGX ${fmt(Math.abs(amt).toFixed(0))}</td>
              <td style="font-size:12px;color:var(--66)">${escapeHtml(a.title || '-')}<div class="sub">${escapeHtml((a.notes || '').slice(0, 80))}${(a.notes || '').length > 80 ? '...' : ''}</div></td>
              <td>${a.is_active ? '<span class="badge green">active</span>' : '<span class="badge">inactive</span>'}</td>
              <td>
                <button class="btn btn-xs btn-ghost" onclick="openAdjustmentAdd(${a.student}, ${a.academic_year}, ${a.term_number}); document.getElementById('adj-id').value='${a.id}'; document.getElementById('adj-kind').value='${escapeHtml(a.kind || '')}'; document.getElementById('adj-amount').value='${Math.abs(amt)}'; document.getElementById('adj-title').value=${JSON.stringify(a.title || '')}; document.getElementById('adj-notes').value=${JSON.stringify(a.notes || '')};">Edit</button>
                <button class="btn btn-xs btn-ghost" onclick="toggleAdjustmentActive(${a.id}, ${a.is_active ? 'false' : 'true'})">${a.is_active ? 'Deactivate' : 'Activate'}</button>
              </td>
            </tr>`;
        }).join('') || `<tr><td colspan="7" style="color:var(--99)">No adjustments found.</td></tr>`;

        main.innerHTML = `
          <div class="page">
            <div class="page-hero"><div class="page-title">Fee Adjustments</div><button class="btn btn-primary" onclick="openAdjustmentAdd('', ${defYear}, ${defTerm})">+ Add Adjustment</button></div>
            <div class="card"><div class="card-body">
              <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                <div class="field" style="margin:0;min-width:160px"><label>Year</label><input class="field-input" id="adj-f-year" type="number" value="${escapeHtml(year)}"></div>
                <div class="field" style="margin:0;min-width:140px"><label>Term</label>
                  <select class="field-select" id="adj-f-term">
                    <option value="1" ${String(term)==='1'?'selected':''}>Term 1</option>
                    <option value="2" ${String(term)==='2'?'selected':''}>Term 2</option>
                    <option value="3" ${String(term)==='3'?'selected':''}>Term 3</option>
                  </select>
                </div>
                <div class="field" style="margin:0;min-width:190px"><label>Type</label>
                  <select class="field-select" id="adj-f-kind">
                    <option value="" ${!kind?'selected':''}>all</option>
                    <option value="discount" ${kind==='discount'?'selected':''}>discount</option>
                    <option value="waiver" ${kind==='waiver'?'selected':''}>waiver</option>
                    <option value="penalty" ${kind==='penalty'?'selected':''}>penalty</option>
                    <option value="correction" ${kind==='correction'?'selected':''}>correction</option>
                  </select>
                </div>
                <div class="field" style="margin:0;min-width:160px"><label>Status</label>
                  <select class="field-select" id="adj-f-act">
                    <option value="1" ${active==='1'?'selected':''}>active</option>
                    <option value="0" ${active==='0'?'selected':''}>inactive</option>
                  </select>
                </div>
                <div class="field" style="margin:0;min-width:220px"><label>Search</label><input class="field-input" id="adj-f-q" value="${escapeHtml(q)}" placeholder="student, title, notes"></div>
                <button class="btn btn-ghost" onclick="loadPage('adjustments', null, 'Adjustments')">Search</button>
              </div>
            </div></div>
            <div style="height:12px"></div>
            <div class="card"><div class="card-body no-pad"><div class="tw">
              <table class="tbl"><thead><tr><th>Student</th><th>Term</th><th>Kind</th><th>Amount</th><th>Details</th><th>Status</th><th></th></tr></thead><tbody>${rows}</tbody></table>
            </div></div></div>
          </div>`;
    } else if (page === 'guardian_links') {
        const role = (currentUser.profile && currentUser.profile.role) || 'admin';
        const canEdit = ['superadmin', 'admin', 'reception', 'bursar', 'headteacher', 'deputy', 'dos'].includes(role);
        const canDelete = role === 'superadmin';
        if (!canEdit) {
            main.innerHTML = `<div class="page"><div class="card"><div class="card-body">You do not have access to this page.</div></div></div>`;
            return;
        }

        const [users, students, links] = await Promise.all([
            API.fetch('/users/').catch(() => []),
            API.fetch('/students/').catch(() => []),
            API.fetch('/guardian-links/').catch(() => []),
        ]);

        const parents = (users || []).filter(u => (u.profile && u.profile.role) === 'parent');
        const parentOpts = parents.slice().sort((a, b) => (a.username || '').localeCompare(b.username || '')).map(u => {
            const name = `${u.first_name || ''} ${u.last_name || ''}`.trim();
            const phone = (u.profile && u.profile.phone_number) ? ` · ${u.profile.phone_number}` : '';
            return `<option value="${u.id}">${escapeHtml(u.username || '')}${name ? (' · ' + escapeHtml(name)) : ''}${escapeHtml(phone)}</option>`;
        }).join('');

        const stuOpts = (students || []).slice().sort((a, b) => (a.student_id || '').localeCompare(b.student_id || '')).map(s => {
            const cls = `${s.current_class_level || '-'}${s.section || ''}`;
            return `<option value="${s.id}">${escapeHtml(s.student_id || '')} · ${escapeHtml((s.first_name || '') + ' ' + (s.last_name || ''))} · ${escapeHtml(cls)}</option>`;
        }).join('');

        const userMap = new Map((users || []).map(u => [u.id, u]));
        const stuMap = new Map((students || []).map(s => [s.id, s]));

        const q = (document.getElementById('gl-q')?.value || '').trim().toLowerCase();
        const filtered = (links || []).filter(l => {
            if (!q) return true;
            const pu = userMap.get(l.parent_user) || {};
            const st = stuMap.get(l.student) || {};
            const t = `${pu.username || ''} ${(pu.first_name || '')} ${(pu.last_name || '')} ${(pu.profile && pu.profile.phone_number) ? pu.profile.phone_number : ''} ${st.student_id || ''} ${st.first_name || ''} ${st.last_name || ''} ${l.relationship || ''}`.toLowerCase();
            return t.includes(q);
        });

        const rows = (filtered || []).slice().sort((a, b) => (b.id || 0) - (a.id || 0)).map(l => {
            const pu = userMap.get(l.parent_user) || {};
            const st = stuMap.get(l.student) || {};
            const pName = `${pu.username || ''}`;
            const sName = `${st.student_id || ''} ${(st.first_name || '')} ${(st.last_name || '')}`.trim();
            const badge = l.is_active ? 'green' : '';
            return `<tr>
              <td><strong>${escapeHtml(pName)}</strong><div class="sub">${escapeHtml((pu.first_name || '') + ' ' + (pu.last_name || ''))}</div></td>
              <td><strong>${escapeHtml(sName)}</strong><div class="sub">Class ${(st.current_class_level || '-')}${(st.section || '')}</div></td>
              <td><span class="badge">${escapeHtml(l.relationship || 'parent')}</span></td>
              <td>${l.is_active ? `<span class="badge green">active</span>` : `<span class="badge">inactive</span>`}</td>
              <td>
                <button class="btn btn-xs btn-ghost" onclick="toggleGuardianLink(${l.id}, ${l.is_active ? 'false' : 'true'})">${l.is_active ? 'Deactivate' : 'Activate'}</button>
                ${canDelete ? `<button class="btn btn-xs btn-ghost" onclick="deleteGuardianLink(${l.id})">Delete</button>` : ''}
              </td>
            </tr>`;
        }).join('') || `<tr><td colspan="5" style="color:var(--99)">No links found.</td></tr>`;

        main.innerHTML = `
          <div class="page">
            <div class="page-hero"><div class="page-title">Guardian Links (Parents with Multiple Children)</div></div>
            <div class="card"><div class="card-body">
              <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                <div class="field" style="margin:0;min-width:300px"><label>Parent account</label><select class="field-select" id="gl-parent">${parentOpts}</select></div>
                <div class="field" style="margin:0;min-width:360px;flex:1"><label>Student</label><select class="field-select" id="gl-student">${stuOpts}</select></div>
                <div class="field" style="margin:0;min-width:170px"><label>Relationship</label><input class="field-input" id="gl-rel" value="parent"></div>
                <button class="btn btn-primary" onclick="createGuardianLink()">Link</button>
              </div>
              <div style="height:10px"></div>
              <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                <div class="field" style="margin:0;min-width:280px"><label>Search</label><input class="field-input" id="gl-q" value="${escapeHtml(q)}" placeholder="parent username/phone or student id/name"></div>
                <button class="btn btn-ghost" onclick="loadPage('guardian_links', null, 'Guardian Links')">Search</button>
              </div>
            </div></div>
            <div style="height:12px"></div>
            <div class="card"><div class="card-body no-pad"><div class="tw">
              <table class="tbl"><thead><tr><th>Parent</th><th>Student</th><th>Relationship</th><th>Status</th><th></th></tr></thead><tbody>${rows}</tbody></table>
            </div></div></div>
          </div>`;
        return;
    } else if (page === 'settings') {
        const extra = await API.fetch('/auth/sessions/');
        const sessions = (extra && extra.sessions) ? extra.sessions : [];
        const logs = (extra && extra.security_logs) ? extra.security_logs : [];
        const sessHtml = sessions.map(s => `<div class="ri"><div class="ri-info"><div class="rn">${s.is_active ? 'Active session' : 'Session'}</div><div class="rd">${s.ip_address || '-'} · ${s.login_time || ''}</div></div><div class="ri-end"><span class="badge ${s.is_active ? 'green' : ''}">${s.is_active ? 'active' : 'closed'}</span></div></div>`).join('');
        const logHtml = logs.slice(0, 8).map(l => `<div class="ri"><div class="ri-info"><div class="rn">${l.event_type}</div><div class="rd">${l.timestamp || ''}</div></div></div>`).join('');
        const role = (currentUser.profile && currentUser.profile.role) || 'admin';

        const prefs = (currentUser.profile && currentUser.profile.notification_prefs) ? currentUser.profile.notification_prefs : {};
        const np = (k, def=true) => (prefs && Object.prototype.hasOwnProperty.call(prefs, k)) ? !!prefs[k] : def;
        const notifHtml = `
          <div style="height:12px"></div>
          <div class="card"><div class="card-head"><div class="card-title">Notifications</div></div>
            <div class="card-body">
              <div class="ri"><div class="ri-info"><div class="rn">Enable in-app notifications</div><div class="rd">Turn the bell alerts on/off</div></div><div class="ri-end"><label class="tog"><input type="checkbox" id="np-in_app" ${np('in_app', true) ? 'checked' : ''}><div class="tog-sl"></div></label></div></div>
              <div class="ri"><div class="ri-info"><div class="rn">Finance notifications</div><div class="rd">Payments, invoices, defaulters</div></div><div class="ri-end"><label class="tog"><input type="checkbox" id="np-finance" ${np('finance', true) ? 'checked' : ''}><div class="tog-sl"></div></label></div></div>
              <div class="ri"><div class="ri-info"><div class="rn">Academic notifications</div><div class="rd">Marks, promotions, report cards</div></div><div class="ri-end"><label class="tog"><input type="checkbox" id="np-academic" ${np('academic', true) ? 'checked' : ''}><div class="tog-sl"></div></label></div></div>
              <div class="ri"><div class="ri-info"><div class="rn">Events notifications</div><div class="rd">New events and updates</div></div><div class="ri-end"><label class="tog"><input type="checkbox" id="np-events" ${np('events', true) ? 'checked' : ''}><div class="tog-sl"></div></label></div></div>
              <div class="ri"><div class="ri-info"><div class="rn">Security notifications</div><div class="rd">Login alerts, critical security</div></div><div class="ri-end"><label class="tog"><input type="checkbox" id="np-security" ${np('security', true) ? 'checked' : ''}><div class="tog-sl"></div></label></div></div>
              <div style="height:10px"></div>
              <button class="btn btn-primary" onclick="saveNotificationPrefs()">Save Notification Preferences</button>
            </div>
          </div>
        `;

        let sysHtml = '';
        if (role === 'superadmin') {
            const settings = await API.fetch('/system-settings/').catch(() => []);
            const map = new Map((settings || []).map(s => [s.key, s.value]));
            const send_credentials_sms = (map.get('send_credentials_sms') ?? true) === true;
            const send_credentials_email = (map.get('send_credentials_email') ?? true) === true;
            const send_fee_reminder_sms = (map.get('send_fee_reminder_sms') ?? true) === true;
            const ai_raw = map.get('ai_tools_enabled');
            const ai_tools_enabled = (typeof ai_raw === 'object' && ai_raw !== null) ? !!ai_raw.enabled : (ai_raw === undefined || ai_raw === null ? true : !!ai_raw); 
            const adm_tpl_raw = map.get('admission_letter_template'); 
            const admission_letter_text = (adm_tpl_raw && typeof adm_tpl_raw === 'object' && adm_tpl_raw !== null) ? (adm_tpl_raw.text || '') : (typeof adm_tpl_raw === 'string' ? adm_tpl_raw : ''); 
            const branding_raw = map.get('school_branding'); 
            const branding = (branding_raw && typeof branding_raw === 'object') ? branding_raw : {}; 
            const b_name = branding.school_name || ''; 
            const b_tag = branding.tagline || ''; 
            const b_contact = branding.contact || ''; 
            const b_logo = branding.logo_url || ''; 
            const rp_raw = map.get('results_policy'); 
            const rp = (rp_raw && typeof rp_raw === 'object') ? rp_raw : {}; 
            const rp_auto = !!rp.auto_hold_on_term_end; 
            const rp_reason = rp.default_reason || 'Outstanding fees'; 
 
            sysHtml = ` 
              <div style="height:12px"></div> 
              <div class="card"><div class="card-head"><div class="card-title">System Settings (Super Admin)</div></div> 
                <div class="card-body"> 
                  <div class="ri">
                    <div class="ri-info"><div class="rn">Send credentials by SMS</div><div class="rd">On student registration and password reset</div></div>
                    <div class="ri-end"><label class="tog"><input type="checkbox" id="ss-cred-sms" ${send_credentials_sms ? 'checked' : ''}><div class="tog-sl"></div></label></div>
                  </div>
                  <div class="ri">
                    <div class="ri-info"><div class="rn">Send credentials by email</div><div class="rd">Only when parent email exists</div></div>
                    <div class="ri-end"><label class="tog"><input type="checkbox" id="ss-cred-email" ${send_credentials_email ? 'checked' : ''}><div class="tog-sl"></div></label></div>
                  </div>
                  <div class="ri">
                    <div class="ri-info"><div class="rn">Enable fee reminder SMS</div><div class="rd">Finance can send SMS reminders from invoice table</div></div>
                    <div class="ri-end"><label class="tog"><input type="checkbox" id="ss-fee-sms" ${send_fee_reminder_sms ? 'checked' : ''}><div class="tog-sl"></div></label></div>
                  </div>
                  <div class="ri">
                    <div class="ri-info"><div class="rn">Enable AI Tools (Teachers)</div><div class="rd">Allows teachers to generate drafts (tests/exams/notes) if a verified AI key exists</div></div>
                    <div class="ri-end"><label class="tog"><input type="checkbox" id="ss-ai" ${ai_tools_enabled ? 'checked' : ''}><div class="tog-sl"></div></label></div>
                  </div>
                  <div style="height:12px"></div>
                  <div style="font-weight:800;margin-bottom:6px">Admission Letter Template</div> 
                  <div class="sub" style="margin-bottom:8px">Placeholders: {student_name}, {student_id}, {class_label}, {parent_name}, {parent_phone}, {today}, {login_url}</div> 
                  <textarea class="field-input" id="ss-adm-tpl" style="min-height:130px;white-space:pre-wrap" placeholder="Leave empty to use the default letter.">${escapeHtml(admission_letter_text || '')}</textarea> 
                  <div style="height:12px"></div> 
                  <div style="font-weight:800;margin-bottom:6px">School Branding (PDFs)</div> 
                  <div class="sub" style="margin-bottom:8px">This affects admission letters, credentials, and report cards.</div> 
                  <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end"> 
                    <div class="field" style="margin:0;min-width:260px"><label>School Name</label><input class="field-input" id="ss-b-name" value="${escapeHtml(b_name)}"></div> 
                    <div class="field" style="margin:0;min-width:260px"><label>Tagline</label><input class="field-input" id="ss-b-tag" value="${escapeHtml(b_tag)}"></div> 
                    <div class="field" style="margin:0;min-width:320px"><label>Contact</label><input class="field-input" id="ss-b-contact" value="${escapeHtml(b_contact)}"></div> 
                  </div> 
                  <div style="height:10px"></div> 
                  <div class="field" style="margin:0"><label>Logo</label> 
                    <input class="field-input" id="ss-b-logo" placeholder="/media/uploads/..." value="${escapeHtml(b_logo)}"> 
                    <input type="file" id="ss-b-logo-file" accept="image/*" style="display:none"> 
                    <div class="dropzone" id="ss-b-logo-drop" style="margin-top:8px"> 
                      <div style="font-weight:800">Click or drop a logo</div> 
                      <div class="sub">JPG/PNG, max 2MB</div> 
                    </div> 
                  </div> 
                  <div style="height:12px"></div> 
                  <div style="font-weight:800;margin-bottom:6px">Results Policy</div> 
                  <div class="ri"> 
                    <div class="ri-info"><div class="rn">Auto-hold results at term end</div><div class="rd">When a term is archived, unpaid/partial invoices get results blocked automatically.</div></div> 
                    <div class="ri-end"><label class="tog"><input type="checkbox" id="ss-rp-auto" ${rp_auto ? 'checked' : ''}><div class="tog-sl"></div></label></div> 
                  </div> 
                  <div class="field" style="margin:0"><label>Default hold reason</label><input class="field-input" id="ss-rp-reason" value="${escapeHtml(rp_reason)}"></div> 
                  <div style="height:10px"></div> 
                  <button class="btn btn-primary" onclick="saveSystemSettings()">Save System Settings</button> 
                </div> 
              </div> 
            `; 
        }
        main.innerHTML = `
            <div class="page">
              <div class="page-hero"><div class="page-title">Settings</div></div>
              <div class="card"><div class="card-body">
                <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;justify-content:space-between">
                  <div>
                    <div style="font-weight:900">My Profile</div>
                    <div class="sub">Update your profile, photo, and contact details.</div>
                  </div>
                  <button class="btn btn-primary" onclick="saveMyProfile()">Save Profile</button>
                </div>
                <div style="height:10px"></div>
                <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                  <div class="field" style="margin:0;min-width:220px"><label>First Name</label><input class="field-input" id="me-fn" value="${currentUser.first_name || ''}"></div>
                  <div class="field" style="margin:0;min-width:220px"><label>Last Name</label><input class="field-input" id="me-ln" value="${currentUser.last_name || ''}"></div>
                  <div class="field" style="margin:0;min-width:260px"><label>Account Email (Django)</label><input class="field-input" id="me-email" type="email" value="${currentUser.email || ''}"></div>
                  <div class="field" style="margin:0;min-width:220px"><label>Phone Number</label><input class="field-input" id="me-phone" type="tel" value="${(currentUser.profile && currentUser.profile.phone_number) ? currentUser.profile.phone_number : ''}"></div>
                  <div class="field" style="margin:0;min-width:260px"><label>Login Email (profile)</label><input class="field-input" id="me-pemail" type="email" value="${(currentUser.profile && currentUser.profile.email_address) ? currentUser.profile.email_address : ''}"></div>
                  <div class="field" style="margin:0;min-width:220px"><label>Job Title (optional)</label><input class="field-input" id="me-job" value="${(currentUser.profile && currentUser.profile.profile_data && currentUser.profile.profile_data.job_title) ? escapeHtml(currentUser.profile.profile_data.job_title) : ''}"></div>
                  <div class="field" style="margin:0;min-width:360px"><label>Address (optional)</label><input class="field-input" id="me-addr" value="${(currentUser.profile && currentUser.profile.profile_data && currentUser.profile.profile_data.address) ? escapeHtml(currentUser.profile.profile_data.address) : ''}"></div>
                  <div class="field" style="margin:0;min-width:360px"><label>Bio (optional)</label><input class="field-input" id="me-bio" value="${(currentUser.profile && currentUser.profile.profile_data && currentUser.profile.profile_data.bio) ? escapeHtml(currentUser.profile.profile_data.bio) : ''}"></div>
                  <div class="field" style="margin:0;min-width:360px"><label>Profile Photo</label>
                    <input type="hidden" id="me-photo" value="${(currentUser.profile && currentUser.profile.photo_url) ? currentUser.profile.photo_url : ''}">
                    <input type="file" id="me-photo-file" accept="image/*" style="display:none">
                    <div class="dropzone" id="me-photo-drop" style="margin-top:8px">
                      <div style="font-weight:800">Click or drop an image</div>
                      <div class="sub">JPG/PNG, max 2MB</div>
                    </div>
                  </div>
                </div>
                ${(currentUser.profile && currentUser.profile.photo_url) ? `<div style="height:10px"></div><div class="card" style="border-style:dashed"><div class="card-body" style="padding:12px 14px;display:flex;gap:12px;align-items:center"><div style="width:52px;height:52px;border-radius:12px;overflow:hidden;border:1px solid var(--e);background:#fff;flex-shrink:0"><img alt="Profile" src="${currentUser.profile.photo_url}" style="width:52px;height:52px;object-fit:cover"></div><div><div style="font-weight:900">Preview</div><div class="sub">Uploaded image will be saved to the server and used everywhere (events, profile, receipts).</div></div></div></div></div>` : ''}
                <div style="height:14px"></div>
                <div style="font-weight:900;margin-bottom:6px">Security</div>
                <div class="sub" style="margin-bottom:10px">Change your password and manage sessions.</div>
                <div class="ri" style="margin-bottom:10px">
                  <div class="ri-info"><div class="rn">Two-factor authentication (OTP)</div><div class="rd">Require an OTP at login for this account.</div></div>
                  <div class="ri-end"><label class="tog"><input type="checkbox" id="me-2fa" ${(currentUser.profile && currentUser.profile.two_factor_enabled) ? 'checked' : ''}><div class="tog-sl"></div></label></div>
                </div>
                <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                  <div class="field" style="margin:0;min-width:220px"><label>Current Password</label><input class="field-input" id="sp-cur" type="password" autocomplete="current-password"></div>
                  <div class="field" style="margin:0;min-width:220px"><label>New Password</label><input class="field-input" id="sp-new" type="password" autocomplete="new-password"></div>
                  <div class="field" style="margin:0;min-width:220px"><label>Confirm Password</label><input class="field-input" id="sp-conf" type="password" autocomplete="new-password"></div>
                  <button class="btn btn-primary" onclick="changePassword()">Change Password</button>
                </div>
                <div style="height:12px"></div>
                <div style="display:flex;gap:10px;flex-wrap:wrap">
                  <button class="btn btn-ghost" onclick="toggleTheme()">Toggle Theme</button>
                  <button class="btn btn-ghost" onclick="logoutOtherSessions()">Logout Other Sessions</button>
                  <button class="btn btn-ghost" onclick="openTutorial(true)">Open Guided Tutorial</button>
                </div>
              </div></div>
              ${notifHtml}
              <div style="height:12px"></div>
              <div class="card"><div class="card-head"><div class="card-title">Sessions</div></div><div class="card-body">${sessHtml || 'No sessions.'}</div></div>
              <div style="height:12px"></div>
              <div class="card"><div class="card-head"><div class="card-title">Recent Security Events</div></div><div class="card-body">${logHtml || 'No security events.'}</div></div>
              ${sysHtml}
            </div>`;
        setTimeout(() => { 
            try { wireProfilePhotoUpload(); } catch {} 
            try { wireBrandingLogoUpload(); } catch {} 
        }, 0); 
    }
    } catch (e) {
      const msg = (e && (e.detail || e.status)) ? (e.detail || e.status) : 'Request failed.';
      main.innerHTML = `<div class="page"><div class="card"><div class="card-body"><div style="font-weight:800;color:var(--rd)">Error</div><div style="margin-top:6px;color:var(--66)">${msg}</div></div></div></div>`;
    }
}

async function renderDeliveryLogsPage(main) {
    const role = (currentUser.profile && currentUser.profile.role) || 'admin';
    const allowed = ['teacher', 'reception', 'superadmin', 'admin', 'headteacher', 'deputy', 'dos', 'bursar'];
    if (!allowed.includes(role)) throw { detail: 'Only staff roles can access delivery logs.' };

    const params = new URLSearchParams();
    if (DELIVERY_FILTER.channel) params.set('channel', DELIVERY_FILTER.channel);
    if (DELIVERY_FILTER.status) params.set('status', DELIVERY_FILTER.status);
    if (DELIVERY_FILTER.campaign) params.set('campaign', DELIVERY_FILTER.campaign);
    if (DELIVERY_FILTER.student) params.set('student', DELIVERY_FILTER.student);
    if (DELIVERY_FILTER.class_id) params.set('class_id', DELIVERY_FILTER.class_id);
    if (DELIVERY_FILTER.q) params.set('q', DELIVERY_FILTER.q);

    const [deliveries, campaigns, classes, students] = await Promise.all([
        API.fetch(`/communication-deliveries/${params.toString() ? '?' + params.toString() : ''}`).catch(() => []),
        API.fetch('/communication-campaigns/').catch(() => []),
        API.fetch('/classes/').catch(() => []),
        API.fetch('/students/').catch(() => []),
    ]);

    const rows = Array.isArray(deliveries) ? deliveries : [];
    const counts = rows.reduce((acc, item) => {
        const key = String(item.status || 'pending').toLowerCase();
        acc.total += 1;
        acc[key] = (acc[key] || 0) + 1;
        if (item.opened_at) acc.opened += 1;
        if (item.confirmed_at) acc.confirmed += 1;
        return acc;
    }, { total: 0, pending: 0, retry_pending: 0, failed: 0, skipped: 0, sent: 0, opened: 0, confirmed: 0, replied: 0 });

    const classOpts = `<option value="">All classes</option>` + (classes || []).map(c => `<option value="${c.id}" ${String(DELIVERY_FILTER.class_id || '') === String(c.id) ? 'selected' : ''}>${escapeHtml(c.level || '')}</option>`).join('');
    const campaignOpts = `<option value="">All campaigns</option>` + (campaigns || []).slice(0, 80).map(c => `<option value="${c.id}" ${String(DELIVERY_FILTER.campaign || '') === String(c.id) ? 'selected' : ''}>${escapeHtml(c.document_title || 'Campaign')} · ${escapeHtml((c.channel || '').toUpperCase())}</option>`).join('');
    const studentOpts = `<option value="">All students</option>` + groupedStudentOptions(students || []).replace(/<option value="([^"]+)"/g, (m, id) => `<option value="${id}" ${String(DELIVERY_FILTER.student || '') === String(id) ? 'selected' : ''}`);
    const tableRows = rows.slice(0, 200).map(d => {
        const retryable = ['failed', 'retry_pending', 'skipped'].includes(String(d.status || '').toLowerCase());
        const sentLike = ['sent', 'opened', 'confirmed', 'replied'].includes(String(d.status || '').toLowerCase());
        return `
          <tr>
            <td>${formatDateTime(d.created_at)}</td>
            <td><strong>${escapeHtml(d.campaign_title || d.message_subject || 'Delivery')}</strong><div class="sub">${escapeHtml((d.channel || '').toUpperCase())} · ${escapeHtml(d.campaign_status || '-')}</div></td>
            <td>${escapeHtml(d.student_name || '-')}<div class="sub">${escapeHtml(d.recipient_name || d.recipient_email || d.recipient_phone || '-')}</div></td>
            <td>${escapeHtml(d.recipient_email || d.recipient_phone || '-')}</td>
            <td><span class="badge ${statusBadgeClass(d.status)}">${escapeHtml(d.status || '')}</span><div class="sub">Attempts: ${Number(d.attempt_count || 0)}</div></td>
            <td>${d.last_error ? `<div style="max-width:260px;white-space:normal">${escapeHtml(d.last_error)}</div>` : '<span class="sub">No error</span>'}</td>
            <td style="white-space:nowrap">
              ${retryable ? `<button class="btn btn-xs btn-ghost" onclick="retryDelivery(${d.id})">Retry</button>` : ''}
              ${sentLike || retryable ? `<button class="btn btn-xs btn-ghost" onclick="resendDelivery(${d.id})">Resend</button>` : ''}
            </td>
          </tr>`;
    }).join('') || `<tr><td colspan="7"><div class="sub">No deliveries match the current filter.</div></td></tr>`;

    main.innerHTML = `
      <div class="page">
        <div class="page-hero">
          <div class="page-title">Delivery Logs</div>
          <div class="sub">Track email and SMS campaign deliveries, filter by class or student, and trigger resend/retry without reopening the original template.</div>
        </div>
        <div class="stats stats-4">
          <div class="stat-card"><div class="stat-num">${counts.total}</div><div class="stat-label">Visible Deliveries</div><div class="stat-accent blue"></div></div>
          <div class="stat-card"><div class="stat-num">${counts.sent + counts.opened + counts.confirmed + counts.replied}</div><div class="stat-label">Sent / Reached</div><div class="stat-accent green"></div></div>
          <div class="stat-card"><div class="stat-num">${counts.retry_pending + counts.failed}</div><div class="stat-label">Need Attention</div><div class="stat-accent red"></div></div>
          <div class="stat-card"><div class="stat-num">${counts.confirmed}</div><div class="stat-label">Confirmed</div><div class="stat-accent gold"></div></div>
        </div>
        <div class="card">
          <div class="card-head"><div class="card-title">Filters</div><div class="sub">Class, student, campaign, channel, and status</div></div>
          <div class="card-body">
            <div class="field-inline-row">
              <select class="field-select" id="dl-channel" style="min-width:150px">
                <option value="">All channels</option>
                <option value="email" ${DELIVERY_FILTER.channel === 'email' ? 'selected' : ''}>Email</option>
                <option value="sms" ${DELIVERY_FILTER.channel === 'sms' ? 'selected' : ''}>SMS</option>
              </select>
              <select class="field-select" id="dl-status" style="min-width:170px">
                <option value="">All statuses</option>
                <option value="pending" ${DELIVERY_FILTER.status === 'pending' ? 'selected' : ''}>Pending</option>
                <option value="retry_pending" ${DELIVERY_FILTER.status === 'retry_pending' ? 'selected' : ''}>Retry pending</option>
                <option value="failed" ${DELIVERY_FILTER.status === 'failed' ? 'selected' : ''}>Failed</option>
                <option value="skipped" ${DELIVERY_FILTER.status === 'skipped' ? 'selected' : ''}>Skipped</option>
                <option value="sent" ${DELIVERY_FILTER.status === 'sent' ? 'selected' : ''}>Sent</option>
                <option value="opened" ${DELIVERY_FILTER.status === 'opened' ? 'selected' : ''}>Opened</option>
                <option value="confirmed" ${DELIVERY_FILTER.status === 'confirmed' ? 'selected' : ''}>Confirmed</option>
                <option value="replied" ${DELIVERY_FILTER.status === 'replied' ? 'selected' : ''}>Replied</option>
              </select>
              <select class="field-select" id="dl-class" style="min-width:170px">${classOpts}</select>
              <select class="field-select" id="dl-student" style="min-width:260px">${studentOpts}</select>
              <select class="field-select" id="dl-campaign" style="min-width:260px">${campaignOpts}</select>
              <input class="field-input" id="dl-q" placeholder="Search recipient, student, or subject" value="${escapeHtml(DELIVERY_FILTER.q || '')}" style="min-width:240px">
              <button class="btn btn-primary" onclick="applyDeliveryLogFilters()">Apply</button>
              <button class="btn btn-ghost" onclick="resetDeliveryLogFilters()">Reset</button>
              <button class="btn btn-ghost" onclick="loadPage('communications', null, 'Communications')">Back to Communications</button>
            </div>
          </div>
        </div>
        <div style="height:12px"></div>
        <div class="card"><div class="card-body no-pad"><div class="tw">
          <table class="tbl">
            <thead><tr><th>Created</th><th>Campaign</th><th>Student / Recipient</th><th>Route</th><th>Status</th><th>Last Error</th><th></th></tr></thead>
            <tbody>${tableRows}</tbody>
          </table>
        </div></div></div>
      </div>`;
}

function applyDeliveryLogFilters() {
    DELIVERY_FILTER = {
        channel: document.getElementById('dl-channel')?.value || '',
        status: document.getElementById('dl-status')?.value || '',
        campaign: document.getElementById('dl-campaign')?.value || '',
        student: document.getElementById('dl-student')?.value || '',
        class_id: document.getElementById('dl-class')?.value || '',
        q: document.getElementById('dl-q')?.value?.trim() || '',
    };
    loadPage('delivery_logs', null, 'Delivery Logs');
}

function resetDeliveryLogFilters() {
    DELIVERY_FILTER = { channel: '', status: '', campaign: '', student: '', class_id: '', q: '' };
    loadPage('delivery_logs', null, 'Delivery Logs');
}

async function retryDelivery(id) {
    try {
        await API.fetch(`/communication-deliveries/${id}/retry/`, { method: 'POST', body: JSON.stringify({}) });
        flash('Delivery retry requested.');
        loadPage('delivery_logs', null, 'Delivery Logs');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to retry delivery.');
    }
}

async function resendDelivery(id) {
    try {
        await API.fetch(`/communication-deliveries/${id}/resend/`, { method: 'POST', body: JSON.stringify({}) });
        flash('Delivery resent.');
        loadPage('delivery_logs', null, 'Delivery Logs');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to resend delivery.');
    }
}

function clearClassForm() {
    document.getElementById('c-id').value = '';
    document.getElementById('c-level').value = '';
    document.getElementById('c-sections').value = 'A, B';
    document.getElementById('c-fee').value = '';
    document.getElementById('c-max').value = '40';
    document.getElementById('c-ta').value = '';
    document.getElementById('c-tb').value = '';
}

function openClassAdd() {
    clearClassForm();
    openModal('modal-class');
}

async function openClassEdit(id) {
    clearClassForm();
    const c = await API.fetch(`/classes/${id}/`);
    document.getElementById('c-id').value = c.id;
    document.getElementById('c-level').value = c.level || '';
    document.getElementById('c-sections').value = (c.sections || []).join(', ');
    document.getElementById('c-fee').value = c.annual_fee || '';
    document.getElementById('c-max').value = c.max_students_per_section || 40;
    document.getElementById('c-ta').value = c.teacher_a || '';
    document.getElementById('c-tb').value = c.teacher_b || '';
    openModal('modal-class');
}

async function saveClass() {
    const id = document.getElementById('c-id').value;
    const level = document.getElementById('c-level').value.trim();
    const sections = document.getElementById('c-sections').value.split(',').map(s => s.trim()).filter(Boolean);
    const annual_fee = document.getElementById('c-fee').value;
    const max_students_per_section = parseInt(document.getElementById('c-max').value, 10) || 40;
    const teacher_a = document.getElementById('c-ta').value.trim();
    const teacher_b = document.getElementById('c-tb').value.trim();
    if (!level) { flash('Enter class level.'); return; }
    const payload = { level, sections, annual_fee, max_students_per_section, teacher_a, teacher_b };
    if (id) await API.fetch(`/classes/${id}/`, { method: 'PATCH', body: JSON.stringify(payload) });
    else await API.fetch('/classes/', { method: 'POST', body: JSON.stringify(payload) });
    closeModal('modal-class');
    flash('Class saved.');
    loadPage('classes');
}

async function saveUser() {
    const id = document.getElementById('u-id').value;
    const username = document.getElementById('u-username').value.trim();
    const pwMode = (document.getElementById('u-pw-mode')?.value || 'auto').toLowerCase();
    const password = document.getElementById('u-password').value;
    const role = document.getElementById('u-role').value;
    const first_name = document.getElementById('u-fname').value.trim();
    const last_name = document.getElementById('u-lname').value.trim();
    const phone_number = document.getElementById('u-phone').value.trim();
    const email_address = document.getElementById('u-email').value.trim();

    if (id && !username) { flash('Username required when editing an existing account.'); return; }
    const payload = { role, first_name, last_name, phone_number, email_address };
    if (username) payload.username = username;

    let handover = null;
    let initialPassword = null;
    let credentialResult = null;
    let finalUsername = username;

    if (!id) {
        if (pwMode === 'manual') {
            if (!password) { flash('Password required (or choose auto-generate).'); return; }
            if (!validateStrongPasswordClient(password, 'Manual password')) return;
            payload.password_mode = 'manual';
            payload.password = password;
        } else {
            payload.password_mode = 'auto';
            payload.auto_password = true;
        }
        const created = await API.fetch('/users/', { method: 'POST', body: JSON.stringify(payload) });
        credentialResult = created;
        finalUsername = (created && created.credentials && created.credentials.username) || created.username || username;
        initialPassword = (created && created._initial_password) ? created._initial_password : (pwMode === 'manual' ? password : null);
        handover = (created && created.handover) ? created.handover : null;
    } else {
        // Update details first.
        await API.fetch(`/users/${id}/`, { method: 'PATCH', body: JSON.stringify(payload) });
        finalUsername = username;

        // Optional password reset.
        if (pwMode === 'manual' && password) {
            if (!validateStrongPasswordClient(password, 'Manual password')) return;
            const r = await API.fetch(`/users/${id}/reset-password/`, { method: 'POST', body: JSON.stringify({ password_mode: 'manual', password }) });
            credentialResult = r;
            finalUsername = (r && r.credentials && r.credentials.username) || finalUsername;
            initialPassword = r && r._initial_password ? r._initial_password : null;
            handover = r && r.handover ? r.handover : null;
        }
        if (pwMode === 'auto') {
            const ok = confirm('Auto-generate a NEW temporary password for this user?');
            if (ok) {
                const r = await API.fetch(`/users/${id}/reset-password/`, { method: 'POST', body: JSON.stringify({ password_mode: 'auto', auto_password: true }) });
                credentialResult = r;
                finalUsername = (r && r.credentials && r.credentials.username) || finalUsername;
                initialPassword = r && r._initial_password ? r._initial_password : null;
                handover = r && r.handover ? r.handover : null;
            }
        }
    }

    closeModal('modal-user');
    loadPage('users');

    if (initialPassword) {
        const lines = [
            `Username: ${finalUsername}`,
            `Temporary Password: ${initialPassword}`,
            `Role: ${role}`,
        ];
        const creds = credentialResult && credentialResult.credentials ? credentialResult.credentials : null;
        if (creds && creds.email_address) lines.push(`Email: ${creds.email_address}`);
        if (creds && creds.phone_number) lines.push(`Phone: ${creds.phone_number}`);
        lines.push(...credentialDeliveryLines(credentialResult && credentialResult.delivery));
        showHandover(
            'Account Credentials',
            lines,
            handover
        );
    } else {
        flash('User saved.');
    }
}

async function deleteUser(id, username) {
    if (!id) return;
    const me = currentUser && currentUser.id ? currentUser.id : null;
    if (me && Number(me) === Number(id)) { flash('You cannot delete your own account.'); return; }
    const ok = confirm(`Delete user '${username || id}'? This cannot be undone.`);
    if (!ok) return;
    try {
        await API.fetch(`/users/${id}/`, { method: 'DELETE' });
        flash('User deleted.');
        loadPage('users');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to delete user.');
    }
}

function recommendedUsername(firstName, lastName, role = 'user') {
    const parts = [
        normUserPart(firstName).replace(/\./g, ''),
        normUserPart(lastName).replace(/\./g, ''),
    ].filter(Boolean);
    if (parts.length >= 2) return `${parts[0]}.${parts[1]}`.slice(0, 30);
    return (parts[0] || normUserPart(role).replace(/\./g, '') || 'user').slice(0, 30);
}

function syncUserUsernamePreview() {
    const firstName = document.getElementById('u-fname')?.value || '';
    const lastName = document.getElementById('u-lname')?.value || '';
    const role = document.getElementById('u-role')?.value || 'user';
    const preview = document.getElementById('u-un-preview');
    if (!preview) return;
    const candidate = recommendedUsername(firstName, lastName, role);
    preview.innerHTML = `Recommended: <strong>${escapeHtml(candidate || 'user')}</strong> <span class="sub">(the system adds a number only if needed)</span>`;
}

function applySuggestedUserUsername() {
    const input = document.getElementById('u-username');
    if (!input) return;
    input.value = recommendedUsername(
        document.getElementById('u-fname')?.value || '',
        document.getElementById('u-lname')?.value || '',
        document.getElementById('u-role')?.value || 'user',
    );
    syncUserUsernamePreview();
}

function generateSuggestedPassword(length = 14) {
    const uppers = 'ABCDEFGHJKLMNPQRSTUVWXYZ';
    const lowers = 'abcdefghijkmnopqrstuvwxyz';
    const digits = '23456789';
    const symbols = '!@#$%^&*_-+=?';
    const all = uppers + lowers + digits + symbols;
    const picks = [
        uppers[Math.floor(Math.random() * uppers.length)],
        lowers[Math.floor(Math.random() * lowers.length)],
        digits[Math.floor(Math.random() * digits.length)],
        symbols[Math.floor(Math.random() * symbols.length)],
    ];
    const target = Math.max(12, length);
    const cryptoObj = (typeof window !== 'undefined' && window.crypto && typeof window.crypto.getRandomValues === 'function') ? window.crypto : null;
    for (let i = picks.length; i < target; i += 1) {
        if (cryptoObj) {
            const arr = new Uint32Array(1);
            cryptoObj.getRandomValues(arr);
            picks.push(all[arr[0] % all.length]);
        } else {
            picks.push(all[Math.floor(Math.random() * all.length)]);
        }
    }
    for (let i = picks.length - 1; i > 0; i -= 1) {
        const j = cryptoObj
            ? (() => {
                const arr = new Uint32Array(1);
                cryptoObj.getRandomValues(arr);
                return arr[0] % (i + 1);
            })()
            : Math.floor(Math.random() * (i + 1));
        [picks[i], picks[j]] = [picks[j], picks[i]];
    }
    return picks.join('');
}

function suggestStrongPasswordFor(inputId, modeId, label = 'Password') {
    const input = document.getElementById(inputId);
    const mode = document.getElementById(modeId);
    if (!input) return;
    if (mode) mode.value = 'manual';
    if (modeId === 'u-pw-mode') toggleUserPasswordMode();
    if (modeId === 't-pw-mode') toggleTeacherPasswordMode();
    if (modeId === 's-ppw-mode' || modeId === 's-spw-mode') toggleStudentPasswordMode();
    input.value = generateSuggestedPassword(14);
    flash(`${label} suggestion inserted.`);
}

function clearUserForm() {
    document.getElementById('u-id').value = '';
    document.getElementById('u-username').value = '';
    document.getElementById('u-password').value = '';
    const pm = document.getElementById('u-pw-mode');
    if (pm) pm.value = 'auto';
    toggleUserPasswordMode();
    document.getElementById('u-role').value = 'admin';
    document.getElementById('u-fname').value = '';
    document.getElementById('u-lname').value = '';
    document.getElementById('u-phone').value = '';
    document.getElementById('u-email').value = '';
    syncUserUsernamePreview();
}

function toggleUserPasswordMode() {
    const mode = (document.getElementById('u-pw-mode')?.value || 'auto').toLowerCase();
    const pw = document.getElementById('u-password');
    if (!pw) return;
    pw.style.display = (mode === 'manual') ? '' : 'none';
}

function openUserAdd() {
    clearUserForm();
    const fn = document.getElementById('u-fname');
    const ln = document.getElementById('u-lname');
    const role = document.getElementById('u-role');
    if (fn) fn.oninput = syncUserUsernamePreview;
    if (ln) ln.oninput = syncUserUsernamePreview;
    if (role) role.onchange = syncUserUsernamePreview;
    openModal('modal-user');
}

async function openUserEdit(id) {
    clearUserForm();
    const u = await API.fetch(`/users/${id}/`);
    document.getElementById('u-id').value = u.id;
    document.getElementById('u-username').value = u.username || '';
    document.getElementById('u-role').value = (u.profile && u.profile.role) ? u.profile.role : 'admin';
    document.getElementById('u-fname').value = u.first_name || '';
    document.getElementById('u-lname').value = u.last_name || '';
    document.getElementById('u-phone').value = (u.profile && u.profile.phone_number) ? u.profile.phone_number : '';
    document.getElementById('u-email').value = (u.profile && u.profile.email_address) ? u.profile.email_address : '';
    // Leave password empty; if provided, it resets the password.
    const pm = document.getElementById('u-pw-mode');
    if (pm) pm.value = 'manual';
    toggleUserPasswordMode();
    const fn = document.getElementById('u-fname');
    const ln = document.getElementById('u-lname');
    const role = document.getElementById('u-role');
    if (fn) fn.oninput = syncUserUsernamePreview;
    if (ln) ln.oninput = syncUserUsernamePreview;
    if (role) role.onchange = syncUserUsernamePreview;
    syncUserUsernamePreview();
    openModal('modal-user');
}

function clearTeacherForm() {
    document.getElementById('t-id').value = '';
    document.getElementById('t-fn').value = '';
    document.getElementById('t-ln').value = '';
    document.getElementById('t-ph').value = '';
    document.getElementById('t-em').value = '';
    const subj = document.getElementById('t-subj');
    if (subj) Array.from(subj.options || []).forEach(o => { o.selected = false; });
    document.getElementById('t-cls').value = '';
    document.getElementById('t-type').value = 'Permanent';
    const pm = document.getElementById('t-pw-mode');
    if (pm) pm.value = 'auto';
    const pw = document.getElementById('t-pw');
    if (pw) { pw.value = ''; pw.style.display = 'none'; }
    const un = document.getElementById('t-un-preview');
    if (un) un.innerHTML = 'Username preview: <strong>...</strong>';
}

function normUserPart(s) {
    return String(s || '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '.').replace(/\.+/g, '.').replace(/^\.|\.$/g, '');
}

function updateTeacherUsernamePreview() {
    const fn = String(document.getElementById('t-fn')?.value || '').trim();
    const ln = String(document.getElementById('t-ln')?.value || '').trim();
    const el = document.getElementById('t-un-preview');
    if (!el) return;
    if (!fn || !ln) {
        el.innerHTML = 'Username preview: <strong>...</strong>';
        return;
    }
    const u = recommendedUsername(fn, ln, 'teacher') || '';
    if (!u) {
        el.innerHTML = 'Username preview: <strong>...</strong>';
        return;
    }
    el.innerHTML = `Username preview: <strong>${escapeHtml(u)}</strong> <span class="sub">(system may add a number if taken)</span>`;
}

async function populateTeacherSubjects(selected = []) {
    const sel = document.getElementById('t-subj');
    if (!sel) return;
    const chosen = new Set((selected || []).map(x => String(x)));
    const subs = await API.fetch('/subjects/').catch(() => []);
    const active = (subs || []).filter(s => s && s.is_active !== false);
    sel.innerHTML = active.map(s => {
        const nm = String(s.name || '');
        return `<option value="${escapeHtml(nm)}" ${chosen.has(nm) ? 'selected' : ''}>${escapeHtml(nm)}</option>`;
    }).join('');
    if (!active.length) {
        sel.innerHTML = '';
        flash('No subjects configured yet. Add subjects first under Academic -> Subjects.');
    }
}

function classAssignedOptions(classes) {
    const out = [];
    (classes || []).forEach(c => {
        const level = String(c.level || '').trim();
        if (!level) return;
        const secs = Array.isArray(c.sections) ? c.sections : [];
        if (!secs.length) {
            out.push({ v: level, t: level });
        } else {
            secs.forEach(s => {
                const sec = String(s || '').trim();
                if (!sec) return;
                out.push({ v: `${level}${sec}`, t: `${level}${sec}` });
            });
        }
    });
    return out;
}

async function populateTeacherClassSelect(selectedValue = '') {
    const sel = document.getElementById('t-cls');
    if (!sel) return;
    const classes = await API.fetch('/classes/').catch(() => []);
    const opts = classAssignedOptions(classes);
    const selected = String(selectedValue || '').trim();
    const html = ['<option value="">Not assigned yet</option>'].concat(
        opts.map(o => `<option value="${escapeHtml(o.v)}" ${selected && o.v === selected ? 'selected' : ''}>${escapeHtml(o.t)}</option>`)
    ).join('');
    sel.innerHTML = html;
    if (selected && !opts.some(o => o.v === selected)) {
        // Preserve existing assigned_class even if class/sections changed.
        sel.innerHTML = `<option value="${escapeHtml(selected)}" selected>${escapeHtml(selected)} (custom)</option>` + sel.innerHTML;
    }
}

function toggleTeacherPasswordMode() {
    const mode = (document.getElementById('t-pw-mode')?.value || 'auto').toLowerCase();
    const pw = document.getElementById('t-pw');
    if (!pw) return;
    pw.style.display = (mode === 'manual') ? '' : 'none';
}

function openTeacherAdd() {
    clearTeacherForm();
    populateTeacherSubjects([]).catch(() => {});
    populateTeacherClassSelect('').catch(() => {});
    try {
        const box = document.getElementById('t-ct-box');
        if (box) box.style.display = 'none';
    } catch {}
    updateTeacherUsernamePreview();
    const fn = document.getElementById('t-fn');
    const ln = document.getElementById('t-ln');
    if (fn) fn.oninput = updateTeacherUsernamePreview;
    if (ln) ln.oninput = updateTeacherUsernamePreview;
    openModal('modal-teacher');
}

async function populateClassTeacherClassSelect(selectedId = '') {
    const sel = document.getElementById('t-ct-class');
    if (!sel) return;
    const classes = await API.fetch('/classes/').catch(() => []);
    const chosen = String(selectedId || '').trim();
    sel.innerHTML = ['<option value="">Select class...</option>'].concat(
        (classes || []).map(c => `<option value="${c.id}" ${chosen && String(c.id) === chosen ? 'selected' : ''}>${escapeHtml(c.level || '')}</option>`)
    ).join('');
}

async function refreshClassTeacherBox(teacher) {
    const role = (currentUser.profile && currentUser.profile.role) || 'superadmin';
    const box = document.getElementById('t-ct-box');
    if (!box) return;
    if (!['superadmin', 'dos'].includes(role)) { box.style.display = 'none'; return; }
    if (!teacher || !teacher.id) { box.style.display = 'none'; return; }
    box.style.display = '';
    await populateClassTeacherClassSelect(teacher.class_teacher_class || '');
    const sec = document.getElementById('t-ct-section');
    if (sec) sec.value = teacher.class_teacher_section || '';
    const cur = document.getElementById('t-ct-current');
    if (cur) {
        if (teacher.is_class_teacher) {
            cur.innerHTML = `Current: <strong>Class ${escapeHtml(teacher.class_teacher_class_level || '-')}${teacher.class_teacher_section ? escapeHtml(String(teacher.class_teacher_section)) : ''}</strong>`;
        } else {
            cur.textContent = 'Not assigned as class teacher.';
        }
    }
}

async function assignClassTeacherFromModal() {
    const id = Number(document.getElementById('t-id')?.value || 0);
    if (!id) { flash('Save teacher first.'); return; }
    const class_id = Number(document.getElementById('t-ct-class')?.value || 0);
    const section = (document.getElementById('t-ct-section')?.value || '').trim().toUpperCase();
    if (!class_id) { flash('Select a class.'); return; }
    try {
        const t = await API.fetch(`/teachers/${id}/assign-class-teacher/`, { method: 'POST', body: JSON.stringify({ class_id, section }) });
        flash('Class teacher assigned.');
        await refreshClassTeacherBox(t);
        if (CURRENT_PAGE === 'teachers') loadPage('teachers');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to assign class teacher.');
    }
}

async function unassignClassTeacherFromModal() {
    const id = Number(document.getElementById('t-id')?.value || 0);
    if (!id) return;
    if (!confirm('Remove class teacher assignment for this teacher?')) return;
    try {
        const t = await API.fetch(`/teachers/${id}/unassign-class-teacher/`, { method: 'POST', body: JSON.stringify({}) });
        flash('Class teacher unassigned.');
        await refreshClassTeacherBox(t);
        if (CURRENT_PAGE === 'teachers') loadPage('teachers');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to unassign class teacher.');
    }
}

async function openTeacherEdit(id) {
    clearTeacherForm();
    const t = await API.fetch(`/teachers/${id}/`);
    document.getElementById('t-id').value = t.id;
    document.getElementById('t-fn').value = t.first_name || '';
    document.getElementById('t-ln').value = t.last_name || '';
    document.getElementById('t-ph').value = t.phone || '';
    document.getElementById('t-em').value = t.email || '';
    await populateTeacherSubjects(t.subjects || []);
    await populateTeacherClassSelect(t.assigned_class || '');
    document.getElementById('t-type').value = t.employment_type || 'Permanent';
    updateTeacherUsernamePreview();
    const fn = document.getElementById('t-fn');
    const ln = document.getElementById('t-ln');
    if (fn) fn.oninput = updateTeacherUsernamePreview;
    if (ln) ln.oninput = updateTeacherUsernamePreview;
    openModal('modal-teacher');
}

async function saveTeacher() {
    try {
        const id = document.getElementById('t-id').value;
        const first_name = document.getElementById('t-fn').value.trim();
        const last_name = document.getElementById('t-ln').value.trim();
        const phone = document.getElementById('t-ph').value.trim();
        const emailRaw = document.getElementById('t-em').value.trim();
        const email = emailRaw ? emailRaw : null;
        const subjSel = document.getElementById('t-subj');
        const subjects = subjSel ? Array.from(subjSel.selectedOptions || []).map(o => (o.value || '').trim()).filter(Boolean) : [];
        const assigned_class = document.getElementById('t-cls').value.trim();
        const employment_type = document.getElementById('t-type').value;
        const password_mode = (document.getElementById('t-pw-mode')?.value || 'auto').toLowerCase();
        const password = (document.getElementById('t-pw')?.value || '');
        if (!first_name || !last_name || !phone) { flash('Teacher requires first name, last name and phone.'); return; }
        if (password_mode === 'manual') {
            if (!password) { flash('Manual password is required.'); return; }
            if (!validateStrongPasswordClient(password, 'Teacher password')) return;
        }
        const payload = { first_name, last_name, phone, email, subjects, assigned_class, employment_type, password_mode };
        if (password_mode === 'manual') payload.password = password;
        if (id) {
            await API.fetch(`/teachers/${id}/`, { method: 'PATCH', body: JSON.stringify(payload) });
            flash('Teacher updated.');
        } else {
            const res = await API.fetch('/teachers/', { method: 'POST', body: JSON.stringify(payload) });
            flash('Teacher registered.');
            if (res && res.credentials) {
                const lines = [
                    `Username: ${res.credentials.username}`,
                    `Temp password: ${res.credentials.temp_password}`,
                ];
                if (res.credentials.email_address) lines.push(`Email: ${res.credentials.email_address}`);
                if (res.credentials.phone_number) lines.push(`Phone: ${res.credentials.phone_number}`);
                lines.push(...credentialDeliveryLines(res.delivery));
                showHandover('Teacher Credentials', lines, res.handover || null);
            }
        }
        closeModal('modal-teacher');
        loadPage('teachers');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to save teacher.');
    }
}

// ----- Sidebar collapse (desktop) -----
function applySidebarCollapseState() {
    const sb = document.getElementById('sidebar');
    const btn = document.getElementById('sb-collapse-btn');
    if (!sb) return;
    let collapsed = false;
    try { collapsed = (localStorage.getItem('bjs_sidebar_collapsed') || '0') === '1'; } catch {}
    // Never collapse in mobile mode; it should slide in/out full width.
    if (window.innerWidth <= 900) collapsed = false;
    sb.classList.toggle('collapsed', collapsed);
    if (btn) btn.textContent = collapsed ? 'Expand' : 'Collapse';
}

function toggleSidebarCollapse() {
    if (window.innerWidth <= 900) return;
    const sb = document.getElementById('sidebar');
    if (!sb) return;
    const next = !sb.classList.contains('collapsed');
    try { localStorage.setItem('bjs_sidebar_collapsed', next ? '1' : '0'); } catch {}
    applySidebarCollapseState();
}

// Override the existing toggleSidebar to behave smartly:
// - mobile: slide in/out
// - desktop: collapse/expand
function toggleSidebar() {
    if (window.innerWidth <= 900) {
        document.getElementById('sidebar').classList.toggle('mobile-open');
        document.getElementById('sb-overlay').classList.toggle('show');
        return;
    }
    toggleSidebarCollapse();
}

try {
    window.addEventListener('resize', () => applySidebarCollapseState());
} catch {}

// Warn before leaving the page when timetable has unsaved changes.
try {
    window.addEventListener('beforeunload', (e) => {
        if (TT && TT._dirty) {
            e.preventDefault();
            e.returnValue = '';
            return '';
        }
    });
} catch {}

// ----- Subjects -----
async function createSubject() {
    const name = (document.getElementById('sub-name')?.value || '').trim();
    const code = (document.getElementById('sub-code')?.value || '').trim() || null;
    if (!name) { flash('Subject name is required.'); return; }
    await API.fetch('/subjects/', { method: 'POST', body: JSON.stringify({ name, code }) });
    flash('Subject created.');
    loadPage('subjects');
}

async function toggleSubjectActive(id, is_active) {
    await API.fetch(`/subjects/${id}/`, { method: 'PATCH', body: JSON.stringify({ is_active }) });
    flash('Updated.');
    loadPage('subjects');
}

async function deleteSubject(id) {
    if (!confirm('Delete this subject? This may affect teachers/class setups.')) return;
    await API.fetch(`/subjects/${id}/`, { method: 'DELETE' });
    flash('Deleted.');
    loadPage('subjects');
}

async function attachSubject() {
    const school_class = document.getElementById('cs-class')?.value;
    const subject = document.getElementById('cs-subject')?.value;
    const periods_per_week = parseInt(document.getElementById('cs-ppw')?.value || '0', 10) || 0;
    if (!school_class || !subject) { flash('Pick class and subject.'); return; }
    await API.fetch('/class-subjects/', { method: 'POST', body: JSON.stringify({ school_class, subject, periods_per_week, is_active: true }) });
    flash('Attached.');
    loadPage('subjects');
}

async function deleteClassSubject(id) {
    if (!confirm('Remove this subject from the class?')) return;
    await API.fetch(`/class-subjects/${id}/`, { method: 'DELETE' });
    flash('Removed.');
    loadPage('subjects');
}

// ----- Terms -----
async function openTermEdit(id) {
    const t = await API.fetch(`/terms/all`).then(all => (all || []).find(x => x.id === id)).catch(() => null);
    if (!t) { flash('Term not found.'); return; }
    document.getElementById('et-id').value = String(t.id);
    document.getElementById('et-yr').value = String(t.academic_year || '');
    document.getElementById('et-num').value = String(t.term_number || '');
    document.getElementById('et-st').value = t.start_date || '';
    document.getElementById('et-en').value = t.end_date || '';
    document.getElementById('et-brk').value = String(t.holiday_break_days || 0);
    document.getElementById('et-fees').checked = !!t.auto_generate_invoices_on_start;
    document.getElementById('et-sms').checked = !!t.sms_parents_on_start;
    document.getElementById('et-marks').checked = !!t.open_mark_entry_on_start;
    document.getElementById('et-arch').checked = !!t.is_archived;
    openModal('modal-term-edit');
}

async function saveTermEdit() {
    const id = document.getElementById('et-id').value;
    const start_date = document.getElementById('et-st').value;
    const end_date = document.getElementById('et-en').value;
    const holiday_break_days = parseInt(document.getElementById('et-brk').value || '0', 10) || 0;
    const auto_generate_invoices_on_start = !!document.getElementById('et-fees').checked;
    const sms_parents_on_start = !!document.getElementById('et-sms').checked;
    const open_mark_entry_on_start = !!document.getElementById('et-marks').checked;
    const is_archived = !!document.getElementById('et-arch').checked;
    if (!id) return;
    await API.fetch(`/terms/${id}/edit/`, { method: 'PATCH', body: JSON.stringify({ start_date, end_date, holiday_break_days, auto_generate_invoices_on_start, sms_parents_on_start, open_mark_entry_on_start, is_archived }) });
    closeModal('modal-term-edit');
    flash('Term updated.');
    loadPage('terms');
}

async function lockMarks(id) {
    const reason = prompt('Reason (optional):') || '';
    await API.fetch(`/terms/${id}/lock-marks/`, { method: 'POST', body: JSON.stringify({ reason }) });
    flash('Marks locked.');
    loadPage('terms', null, 'Terms');
}

async function unlockMarks(id) {
    await API.fetch(`/terms/${id}/unlock-marks/`, { method: 'POST', body: JSON.stringify({}) });
    flash('Marks unlocked.');
    loadPage('terms', null, 'Terms');
}

async function createDepositBatchFromSelected() {
    const ids = Array.from(document.querySelectorAll('.dep-cb')).filter(cb => cb.checked).map(cb => Number(cb.getAttribute('data-id'))).filter(Boolean);
    if (!ids.length) { flash('Select at least one approved payment to batch.'); return; }
    const name = (document.getElementById('dep-name')?.value || '').trim() || null;
    const bank_name = (document.getElementById('dep-bank')?.value || '').trim() || null;
    const deposit_date = (document.getElementById('dep-date')?.value || '').trim() || todayISO();
    const reference = (document.getElementById('dep-ref')?.value || '').trim() || null;
    const notes = (document.getElementById('dep-notes')?.value || '').trim() || null;
    let slip_image_url = null;
    try {
        const f = document.getElementById('dep-slip-file')?.files?.[0] || null;
        if (f) slip_image_url = await uploadImageFile(f);
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Slip upload failed.');
        return;
    }

    try {
        const batch = await API.fetch('/deposit-batches/', {
            method: 'POST',
            body: JSON.stringify({ name, bank_name, deposit_date, reference, slip_image_url, notes }),
        });
        await API.fetch(`/deposit-batches/${batch.id}/add-payments/`, { method: 'POST', body: JSON.stringify({ ids }) });
        flash(`Batch created (#${batch.id}) and added ${ids.length} payments.`);
        loadPage('deposits', null, 'Deposits');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to create batch.');
    }
}

async function markDepositPosted(id) {
    await API.fetch(`/deposit-batches/${id}/mark-posted/`, { method: 'POST', body: JSON.stringify({}) });
    flash('Batch marked posted.');
    loadPage('deposits', null, 'Deposits');
}

let depbState = { batch: null, payments: [] };

async function openDepositBatch(id) {
    const ttl = document.getElementById('depb-ttl');
    const meta = document.getElementById('depb-meta');
    const rows = document.getElementById('depb-rows');
    const hid = document.getElementById('depb-id');
    const all = document.getElementById('depb-all');
    const removeBtn = document.getElementById('depb-remove-btn');

    if (hid) hid.value = String(id);
    if (ttl) ttl.textContent = `Deposit Batch #${id}`;
    if (meta) meta.textContent = 'Loading...';
    if (rows) rows.innerHTML = `<tr><td colspan="7" style="color:var(--99)">Loading...</td></tr>`;
    if (all) all.checked = false;
    if (removeBtn) removeBtn.disabled = true;

    openModal('modal-deposit-batch');

    try {
        const [batch, payments] = await Promise.all([
            API.fetch(`/deposit-batches/${id}/`),
            API.fetch(`/deposit-batches/${id}/payments/`).catch(() => []),
        ]);
        depbState = { batch, payments: payments || [] };

        const total = (depbState.payments || []).reduce((s, p) => s + (Number(p.amount || 0) || 0), 0);
        const posted = !!(batch && batch.is_posted);
        if (removeBtn) removeBtn.disabled = posted;

        if (meta) {
            const parts = [
                `<strong>${escapeHtml(batch.name || ('Batch #' + batch.id))}</strong>`,
                batch.bank_name ? `Bank: ${escapeHtml(batch.bank_name)}` : null,
                batch.deposit_date ? `Deposit Date: ${escapeHtml(batch.deposit_date)}` : null,
                batch.reference ? `Ref: ${escapeHtml(batch.reference)}` : null,
                `Status: ${posted ? '<span class="badge red">Posted</span>' : '<span class="badge green">Open</span>'}`,
                `Payments: <strong>${depbState.payments.length}</strong>`,
                `Total: <strong>UGX ${fmt(total.toFixed(0))}</strong>`,
            ].filter(Boolean);
            meta.innerHTML = parts.join(' &nbsp; | &nbsp; ');
        }

        const payRows = (depbState.payments || []).map(p => {
            const dt = formatDateTime(p.received_at, '-');
            const stu = `<strong>${escapeHtml(p.student_system_id || '')}</strong><div class="sub">${escapeHtml(p.student_name || '')}</div>`;
            const slipBtn = p.receipt_image_url ? `<button class="btn btn-xs btn-ghost" onclick="viewImage('${escapeHtml(p.receipt_image_url)}','Bank Slip')">Slip</button>` : '';
            return `
              <tr>
                <td style="width:34px"><input class="depb-cb" type="checkbox" data-id="${p.id}" ${posted ? 'disabled' : ''}></td>
                <td>${dt}</td>
                <td>${stu}</td>
                <td style="font-weight:900">UGX ${fmt(Number(p.amount || 0).toFixed(0))}</td>
                <td>${escapeHtml(p.receipt_number || '')}</td>
                <td>${escapeHtml(p.reference || '')}</td>
                <td style="white-space:nowrap">${slipBtn}</td>
              </tr>`;
        }).join('') || `<tr><td colspan="7" style="color:var(--99)">No payments in this batch.</td></tr>`;

        if (rows) rows.innerHTML = payRows;
    } catch (e) {
        if (meta) meta.textContent = 'Failed to load batch.';
        if (rows) rows.innerHTML = `<tr><td colspan="7" style="color:var(--99)">Failed to load.</td></tr>`;
        flash((e && e.detail) ? e.detail : 'Failed to load batch.');
    }
}

function depbToggleAll(checked) {
    document.querySelectorAll('#depb-rows .depb-cb').forEach(cb => {
        if (!cb.disabled) cb.checked = !!checked;
    });
}

function depbSelectedIds() {
    return Array.from(document.querySelectorAll('#depb-rows .depb-cb'))
        .filter(cb => cb.checked && !cb.disabled)
        .map(cb => Number(cb.getAttribute('data-id')))
        .filter(Boolean);
}

async function removeSelectedPaymentsFromBatch() {
    const batch = depbState.batch;
    if (!batch) { flash('Batch not loaded.'); return; }
    if (batch.is_posted) { flash('Cannot modify a posted batch.'); return; }

    const ids = depbSelectedIds();
    if (!ids.length) { flash('Select payments to remove.'); return; }
    if (!confirm(`Remove ${ids.length} payment(s) from this batch?`)) return;

    try {
        const res = await API.fetch(`/deposit-batches/${batch.id}/remove-payments/`, { method: 'POST', body: JSON.stringify({ ids }) });
        flash(`Removed ${res.removed || 0} payment(s).`);
        await openDepositBatch(batch.id);
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to remove payments.');
    }
}

function printDepositBatchReportFromModal() {
    const batch = depbState.batch;
    if (!batch) { flash('Batch not loaded.'); return; }
    window.open(`/api/deposit-batches/${batch.id}/report/`, '_blank');
}

async function createExpenseCategory() {
    const name = (document.getElementById('ex-cat-name')?.value || '').trim();
    if (!name) { flash('Enter category name.'); return; }
    await API.fetch('/expense-categories/', { method: 'POST', body: JSON.stringify({ name, is_active: true }) });
    flash('Category added.');
    loadPage('expenses', null, 'Expenses');
}

async function createExpense() {
    const expense_date = (document.getElementById('ex-date')?.value || '').trim() || todayISO();
    const category = Number(document.getElementById('ex-cat')?.value || 0) || null;
    const amount = Number((document.getElementById('ex-amt')?.value || '').trim() || 0);
    const vendor = (document.getElementById('ex-vendor')?.value || '').trim() || null;
    const description = (document.getElementById('ex-desc')?.value || '').trim() || null;
    if (!amount || !Number.isFinite(amount) || amount <= 0) { flash('Enter a valid amount.'); return; }
    let receipt_image_url = null;
    try {
        const f = document.getElementById('ex-receipt')?.files?.[0] || null;
        if (f) receipt_image_url = await uploadImageFile(f);
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Receipt upload failed.');
        return;
    }
    await API.fetch('/expenses/', { method: 'POST', body: JSON.stringify({ expense_date, category, amount, vendor, description, receipt_image_url }) });
    flash('Expense saved.');
    loadPage('expenses', null, 'Expenses');
}

async function approveExpense(id) {
    const review_notes = prompt('Internal review notes (optional):') || '';
    await API.fetch(`/expenses/${id}/approve/`, { method: 'POST', body: JSON.stringify({ review_notes }) });
    flash('Expense approved.');
    loadPage('expenses', null, 'Expenses');
}

async function rejectExpense(id) {
    const review_notes = prompt('Reason / notes (optional):') || '';
    await API.fetch(`/expenses/${id}/reject/`, { method: 'POST', body: JSON.stringify({ review_notes }) });
    flash('Expense rejected.');
    loadPage('expenses', null, 'Expenses');
}

async function blockResults(invoiceId, studentName) {
    const reason = prompt(`Block results for ${studentName || 'this student'}?\nReason (optional):`, 'Fees not cleared') || '';
    try {
        await API.fetch(`/invoices/${invoiceId}/block-results/`, { method: 'POST', body: JSON.stringify({ reason }) });
        flash('Results blocked.');
        loadPage('finance', null, 'Payments');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to block results.');
    }
}

async function unblockResults(invoiceId) {
    if (!confirm('Unblock results for this term?')) return;
    try {
        await API.fetch(`/invoices/${invoiceId}/unblock-results/`, { method: 'POST', body: JSON.stringify({}) });
        flash('Results unblocked.');
        loadPage('finance', null, 'Payments');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to unblock results.');
    }
}

async function holdResultsForClass() {
    const year = Number(document.getElementById('fin-year')?.value || 0) || null;
    const term = Number(document.getElementById('fin-term')?.value || 0) || null;
    const class_id_raw = (document.getElementById('rh-class')?.value || '').trim();
    const class_id = class_id_raw ? Number(class_id_raw) : null;
    const reason = (document.getElementById('rh-reason')?.value || '').trim() || 'Outstanding fees';
    if (!year || !term) { flash('Pick year and term.'); return; }
    try {
        const res = await API.fetch('/invoices/hold-results/', { method: 'POST', body: JSON.stringify({ year, term, class_id, reason }) });
        flash(`Held results for ${res.held || 0} invoice(s).`);
        loadPage('finance', null, 'Payments');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to hold results.');
    }
}

async function releaseResultsForClass() {
    const year = Number(document.getElementById('fin-year')?.value || 0) || null;
    const term = Number(document.getElementById('fin-term')?.value || 0) || null;
    const class_id_raw = (document.getElementById('rh-class')?.value || '').trim();
    const class_id = class_id_raw ? Number(class_id_raw) : null;
    if (!year || !term) { flash('Pick year and term.'); return; }
    if (!confirm('Release results for this scope?')) return;
    try {
        const res = await API.fetch('/invoices/release-results/', { method: 'POST', body: JSON.stringify({ year, term, class_id }) });
        flash(`Released results for ${res.released || 0} invoice(s).`);
        loadPage('finance', null, 'Payments');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to release results.');
    }
}

async function deleteTerm(id) {
    if (!confirm('Delete this archived term? This cannot be undone.')) return;
    try {
        const role = (currentUser.profile && currentUser.profile.role) || 'superadmin';
        let force = false;
        if (role === 'superadmin') {
            force = confirm('Force delete term data too?\nThis will delete marks/invoices for this term/year.');
        }
        const qs = force ? '?force=true' : '';
        await API.fetch(`/terms/${id}/delete/${qs}`, { method: 'DELETE' });
        flash('Term deleted.');
        loadPage('terms');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to delete term.');
    }
}

function resetStudentParentMatch() {
    ACTIVE_PARENT_CANDIDATES = [];
    const hid = document.getElementById('s-existing-parent-user');
    if (hid) hid.value = '';
    const box = document.getElementById('s-parent-match');
    if (box) box.innerHTML = '';
}

function renderParentCandidateMatches(items) {
    ACTIVE_PARENT_CANDIDATES = Array.isArray(items) ? items : [];
    const box = document.getElementById('s-parent-match');
    if (!box) return;
    if (!ACTIVE_PARENT_CANDIDATES.length) {
        box.innerHTML = '';
        return;
    }
    box.innerHTML = `
      <div class="tutorial-kicker" style="margin-bottom:8px">Possible existing parent account</div>
      ${ACTIVE_PARENT_CANDIDATES.map(item => `
        <button class="parent-match-card" type="button" onclick="selectParentCandidate(${Number(item.user_id)})">
          <strong>${escapeHtml(item.name || item.username || 'Parent account')}</strong>
          <span>${escapeHtml(item.username || '')}${item.phone_number ? ' · ' + escapeHtml(item.phone_number) : ''}${item.email_address ? ' · ' + escapeHtml(item.email_address) : ''}</span>
          <span>${(item.linked_students || []).length ? 'Linked: ' + escapeHtml((item.linked_students || []).join(', ')) : 'No linked students yet'}</span>
        </button>`).join('')}
      <div class="sub" style="margin-top:8px">Choose one if this is the same parent/guardian so we keep one portal account for the whole family.</div>
    `;
}

async function lookupParentCandidates() {
    const studentId = document.getElementById('s-id')?.value || '';
    if (studentId) return;
    const currentSelected = document.getElementById('s-existing-parent-user')?.value || '';
    if (currentSelected) return;
    const q = (
        document.getElementById('s-pn')?.value?.trim()
        || document.getElementById('s-pem')?.value?.trim()
        || document.getElementById('s-pph')?.value?.trim()
        || ''
    );
    if (q.length < 2) {
        resetStudentParentMatch();
        return;
    }
    try {
        const rows = await API.fetch(`/students/parent-candidates/?q=${encodeURIComponent(q)}`);
        renderParentCandidateMatches(rows || []);
    } catch {
        resetStudentParentMatch();
    }
}

function queueParentCandidateLookup() {
    clearTimeout(PARENT_MATCH_TIMER);
    PARENT_MATCH_TIMER = setTimeout(() => { lookupParentCandidates(); }, 250);
}

function selectParentCandidate(userId) {
    const selected = ACTIVE_PARENT_CANDIDATES.find(item => Number(item.user_id) === Number(userId));
    const hid = document.getElementById('s-existing-parent-user');
    const box = document.getElementById('s-parent-match');
    if (!selected || !hid || !box) return;
    hid.value = String(selected.user_id);
    if (selected.name) document.getElementById('s-pn').value = selected.name;
    if (selected.phone_number) document.getElementById('s-pph').value = selected.phone_number;
    if (selected.email_address) document.getElementById('s-pem').value = selected.email_address;
    box.innerHTML = `
      <div class="parent-match-selected">
        <strong>Linked to existing parent portal:</strong> ${escapeHtml(selected.name || selected.username || '')}
        <div class="sub">${escapeHtml(selected.username || '')}${selected.phone_number ? ' · ' + escapeHtml(selected.phone_number) : ''}${selected.email_address ? ' · ' + escapeHtml(selected.email_address) : ''}</div>
        <button class="btn btn-xs btn-ghost" type="button" onclick="clearParentCandidateSelection()">Choose a different parent</button>
      </div>
    `;
}

function clearParentCandidateSelection() {
    const hid = document.getElementById('s-existing-parent-user');
    if (hid) hid.value = '';
    queueParentCandidateLookup();
}

function setStudentPhotoValue(url) {
    const input = document.getElementById('s-photo');
    const wrap = document.getElementById('s-photo-preview-wrap');
    const img = document.getElementById('s-photo-preview');
    if (input) input.value = url || '';
    if (wrap) wrap.style.display = url ? '' : 'none';
    if (img) img.src = url || '';
}

function clearStudentPhoto() {
    setStudentPhotoValue('');
}

function wireStudentPhotoUpload() {
    const drop = document.getElementById('s-photo-drop');
    const file = document.getElementById('s-photo-file');
    if (!drop || !file || drop.dataset.wired === '1') return;
    drop.dataset.wired = '1';
    wireDropZone(drop, file, async (files) => {
        if (!files || !files.length) return;
        try {
            const url = await uploadImageFile(files[0]);
            setStudentPhotoValue(url);
            flash('Student photo uploaded.');
        } catch (e) {
            flash((e && e.detail) ? e.detail : 'Failed to upload student photo.');
        }
    });
}

function clearStudentForm() {
    document.getElementById('s-id').value = '';
    document.getElementById('s-sid').value = '';
    document.getElementById('s-fn').value = '';
    document.getElementById('s-ln').value = '';
    document.getElementById('s-dob').value = '';
    document.getElementById('s-gen').value = 'Female';
    document.getElementById('s-dist').value = '';
    document.getElementById('s-rel').value = '';
    document.getElementById('s-sec').value = 'A';
    document.getElementById('s-pn').value = '';
    document.getElementById('s-prel').value = '';
    document.getElementById('s-pph').value = '';
    document.getElementById('s-pem').value = '';
    document.getElementById('s-pph2').value = '';
    document.getElementById('s-addr').value = '';
    document.getElementById('s-prev').value = '';
    document.getElementById('s-alg').value = '';
    document.getElementById('s-med').value = '';
    document.getElementById('s-ecn').value = '';
    document.getElementById('s-ecp').value = '';
    document.getElementById('s-tr').value = '';
    document.getElementById('s-status').value = 'active';
    const pm = document.getElementById('s-ppw-mode');
    if (pm) pm.value = 'auto';
    const sm = document.getElementById('s-spw-mode');
    if (sm) sm.value = 'auto';
    const ppw = document.getElementById('s-ppw');
    if (ppw) { ppw.value = ''; ppw.style.display = 'none'; }
    const spw = document.getElementById('s-spw');
    if (spw) { spw.value = ''; spw.style.display = 'none'; }
    const sPhoto = document.getElementById('s-photo');
    if (sPhoto) sPhoto.value = '';
    resetStudentParentMatch();
    clearStudentPhoto();
}

function toggleStudentPasswordMode() {
    const pm = (document.getElementById('s-ppw-mode')?.value || 'auto').toLowerCase();
    const sm = (document.getElementById('s-spw-mode')?.value || 'auto').toLowerCase();
    const ppw = document.getElementById('s-ppw');
    const spw = document.getElementById('s-spw');
    if (ppw) ppw.style.display = (pm === 'manual') ? '' : 'none';
    if (spw) spw.style.display = (sm === 'manual') ? '' : 'none';
}

function validateStrongPasswordClient(password, label = 'Password') {
    const value = String(password || '');
    const checks = [
        { ok: value.length >= 10, label: 'at least 10 characters' },
        { ok: /[A-Z]/.test(value), label: 'an uppercase letter' },
        { ok: /[a-z]/.test(value), label: 'a lowercase letter' },
        { ok: /\d/.test(value), label: 'a number' },
        { ok: /[^A-Za-z0-9]/.test(value), label: 'a symbol' },
    ];
    const failed = checks.filter(c => !c.ok).map(c => c.label);
    if (failed.length) {
        flash(`${label} must include ${failed.join(', ')}.`);
        return false;
    }
    return true;
}

async function openStudentAdd() {
    clearStudentForm();
    const classes = await API.fetch('/classes/');
    if (!classes || classes.length === 0) {
        flash('No classes configured yet. Add classes first.');
        loadPage('classes', null, 'Classes');
        return;
    }
    const sel = document.getElementById('s-class');
    sel.innerHTML = (classes || []).map(c => `<option value="${c.id}">${c.level}</option>`).join('');
    openModal('modal-student');
    setTimeout(() => { try { wireStudentPhotoUpload(); } catch {} }, 0);
}

async function openStudentEdit(id) {
    clearStudentForm();
    const [classes, s] = await Promise.all([API.fetch('/classes/'), API.fetch(`/students/${id}/`)]);
    const sel = document.getElementById('s-class');
    sel.innerHTML = (classes || []).map(c => `<option value="${c.id}">${c.level}</option>`).join('');
    document.getElementById('s-id').value = s.id;
    document.getElementById('s-sid').value = s.student_id || '';
    document.getElementById('s-fn').value = s.first_name || '';
    document.getElementById('s-ln').value = s.last_name || '';
    document.getElementById('s-dob').value = s.dob || '';
    document.getElementById('s-gen').value = s.gender || 'Female';
    document.getElementById('s-dist').value = s.district || '';
    document.getElementById('s-rel').value = s.religion || '';
    document.getElementById('s-class').value = s.current_class || (sel.options[0] ? sel.options[0].value : '');
    document.getElementById('s-sec').value = (s.section || 'A').toUpperCase();
    document.getElementById('s-pn').value = s.parent_name || '';
    document.getElementById('s-prel').value = s.parent_relationship || '';
    document.getElementById('s-pph').value = s.parent_phone || '';
    document.getElementById('s-pem').value = s.parent_email || '';
    document.getElementById('s-pph2').value = s.parent_phone2 || '';
    document.getElementById('s-addr').value = s.home_address || '';
    document.getElementById('s-prev').value = s.previous_school || '';
    document.getElementById('s-alg').value = s.allergies || '';
    document.getElementById('s-med').value = s.medical_conditions || '';
    document.getElementById('s-ecn').value = s.emergency_contact_name || '';
    document.getElementById('s-ecp').value = s.emergency_contact_phone || '';
    document.getElementById('s-tr').value = s.transport_route || '';
    document.getElementById('s-status').value = s.status || 'active';
    setStudentPhotoValue(s.photo_url || '');
    openModal('modal-student');
    setTimeout(() => { try { wireStudentPhotoUpload(); } catch {} }, 0);
}

// Backwards-compat: keep the old function name used in some earlier UI.
async function openStudentModal() { return openStudentAdd(); }

async function saveStudent() {
    const id = document.getElementById('s-id').value;
    const first_name = document.getElementById('s-fn').value.trim();
    const last_name = document.getElementById('s-ln').value.trim();
    const dob = document.getElementById('s-dob').value || null;
    const gender = document.getElementById('s-gen').value;
    const district = document.getElementById('s-dist').value.trim();
    const religion = document.getElementById('s-rel').value.trim();
    const current_class = document.getElementById('s-class').value;
    const section = (document.getElementById('s-sec').value.trim() || 'A').toUpperCase();
    const parent_name = document.getElementById('s-pn').value.trim();
    const parent_relationship = document.getElementById('s-prel').value.trim();
    const parent_phone = document.getElementById('s-pph').value.trim();
    const parent_email = document.getElementById('s-pem').value.trim();
    const parent_phone2 = document.getElementById('s-pph2').value.trim();
    const home_address = document.getElementById('s-addr').value.trim();
    const previous_school = document.getElementById('s-prev').value.trim();
    const allergies = document.getElementById('s-alg').value.trim();
    const medical_conditions = document.getElementById('s-med').value.trim();
    const emergency_contact_name = document.getElementById('s-ecn').value.trim();
    const emergency_contact_phone = document.getElementById('s-ecp').value.trim();
    const transport_route = document.getElementById('s-tr').value.trim();
    const status = document.getElementById('s-status').value;
    const photo_url = document.getElementById('s-photo')?.value?.trim() || '';
    const existing_parent_user = document.getElementById('s-existing-parent-user')?.value?.trim() || '';

    try {
        if (!first_name || !last_name || !parent_name || !parent_relationship || !parent_phone) {
            flash('Student requires name + parent details.');
            return;
        }

    const payload = {
        first_name, last_name, dob, gender, district, religion,
        current_class, section,
        parent_name, parent_relationship, parent_phone, parent_phone2,
        home_address, previous_school,
        allergies, medical_conditions,
        emergency_contact_name, emergency_contact_phone,
        transport_route, status,
        photo_url,
        parent_email, // not stored on Student; used to keep parent portal profile updated
    };
        if (!id && existing_parent_user) payload.existing_parent_user = existing_parent_user;

        // Optional password modes (only used when accounts are newly created).
        const parent_password_mode = (document.getElementById('s-ppw-mode')?.value || 'auto').toLowerCase();
        const parent_password = (document.getElementById('s-ppw')?.value || '');
        const student_password_mode = (document.getElementById('s-spw-mode')?.value || 'auto').toLowerCase();
        const student_password = (document.getElementById('s-spw')?.value || '');
        if (parent_password_mode === 'manual') {
            if (!parent_password) { flash('Manual parent password is required.'); return; }
            if (!validateStrongPasswordClient(parent_password, 'Parent password')) return;
        }
        if (student_password_mode === 'manual') {
            if (!student_password) { flash('Manual student password is required.'); return; }
            if (!validateStrongPasswordClient(student_password, 'Student password')) return;
        }
        payload.parent_password_mode = parent_password_mode;
        payload.student_password_mode = student_password_mode;
        if (parent_password_mode === 'manual') payload.parent_password = parent_password;
        if (student_password_mode === 'manual') payload.student_password = student_password;

        let res = null;
        if (id) {
            await API.fetch(`/students/${id}/`, { method: 'PATCH', body: JSON.stringify(payload) });
        } else {
            res = await API.fetch('/students/', { method: 'POST', body: JSON.stringify(payload) });
        }
        closeModal('modal-student');
        if (!id && res && res.credentials) {
            const c = res.credentials;
            const parts = [];
            if (c.parent_username) parts.push(`Parent: ${c.parent_username} / ${c.parent_temp_password || '(unchanged)'}`);
            if (c.parent_email) parts.push(`Parent email: ${c.parent_email}`);
            if (c.student_username) parts.push(`Student: ${c.student_username} / ${c.student_temp_password || '(unchanged)'}`);
            if (parts.length) flash('Credentials: ' + parts.join(' | '));
            if (res.handover) {
                const lines = [];
                if (c.parent_username) lines.push(`Parent phone: ${c.parent_username} / ${c.parent_temp_password || '(unchanged)'}`);
                if (c.parent_email) lines.push(`Parent email: ${c.parent_email}`);
                if (c.student_username) lines.push(`Student: ${c.student_username} / ${c.student_temp_password || '(unchanged)'}`);
                lines.push(...credentialDeliveryLines(res.delivery));
                showHandover('Student Handover', lines, res.handover);
            }
            if (res.delivery) {
                const deliveryBits = [];
                if (res.delivery.email_sent) deliveryBits.push('email sent');
                if (res.delivery.sms_sent) deliveryBits.push('SMS sent');
                if (deliveryBits.length) flash('Registration notice: ' + deliveryBits.join(' + ') + '.');
            }
        }
        flash(id ? 'Student updated.' : 'Student registered.');
        loadPage('students');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to save student.');
    }
}

async function refreshTermChip() {
    try {
        const t = await API.fetch('/terms/');
        ACTIVE_TERM_CACHE = t;
        ACTIVE_TERM_CACHE_AT = Date.now();
        const el = document.getElementById('tb-term');
        if (el && t && t.academic_year) el.textContent = `Term ${t.term_number} - ${t.academic_year}`;
    } catch {
        const el = document.getElementById('tb-term');
        if (el) el.textContent = 'No active term';
    }
}

function clearQueryParam(name) {
    try {
        const url = new URL(window.location.href);
        url.searchParams.delete(name);
        window.history.replaceState({}, document.title, url.toString());
    } catch {}
}

async function maybeHandleTeacherQR() {
    let token = null;
    try { token = new URLSearchParams(window.location.search).get('teacher_qr'); } catch {}
    if (!token) return;

    const role = (currentUser.profile && currentUser.profile.role) || 'admin';
    if (role !== 'teacher') {
        flash('Teacher QR can only be scanned by teacher accounts.');
        clearQueryParam('teacher_qr');
        return;
    }

    try {
        await API.fetch('/teacher-attendance/qr/scan/', { method: 'POST', body: JSON.stringify({ token }) });
        flash('Attendance marked (QR).');
    } catch (e) {
        flash(e && e.detail ? e.detail : 'Failed to mark attendance.');
    } finally {
        clearQueryParam('teacher_qr');
    }
}

async function taLoad() {
    const d = document.getElementById('ta-date').value;
    const rows = await API.fetch(`/teacher-attendance/for-date/?date=${encodeURIComponent(d)}`);
    const body = document.getElementById('ta-body');
    body.innerHTML = (rows || []).map(r => `
      <tr data-teacher="${r.teacher}">
        <td><input type="checkbox" class="ta-sel"></td>
        <td><strong>${(r.teacher_name || '').toString()}</strong></td>
        <td>
          <select class="field-select ta-status" style="min-width:140px">
            <option value="present" ${r.status === 'present' ? 'selected' : ''}>present</option>
            <option value="late" ${r.status === 'late' ? 'selected' : ''}>late</option>
            <option value="excused" ${r.status === 'excused' ? 'selected' : ''}>excused</option>
            <option value="absent" ${r.status === 'absent' ? 'selected' : ''}>absent</option>
          </select>
        </td>
        <td style="font-size:12px;color:var(--66)">
          ${r.method ? `<span class="badge ${r.method === 'qr' ? 'green' : ''}">${r.method}</span>` : '<span class="badge">manual</span>'}
          ${(r.updated_at || r.created_at) ? `<div class="sub">${String(r.updated_at || r.created_at).slice(0, 19).replace('T', ' ')}</div>` : ''}
        </td>
        <td><input class="field-input ta-notes" value="${(r.notes || '').toString().replace(/\"/g, '&quot;')}" placeholder="Optional"></td>
      </tr>
    `).join('');
    taFilter();
}

async function taSave() {
    const d = document.getElementById('ta-date').value;
    const items = Array.from(document.querySelectorAll('#ta-body tr')).map(tr => ({
        teacher: tr.getAttribute('data-teacher'),
        date: d,
        status: (tr.querySelector('.ta-status') || {}).value || 'present',
        notes: (tr.querySelector('.ta-notes') || {}).value || '',
    }));
    await API.fetch('/teacher-attendance/upsert-bulk/', { method: 'POST', body: JSON.stringify({ items }) });
    flash('Teacher attendance saved.');
}

async function taGenerateQR() {
    const d = document.getElementById('ta-date').value;
    const res = await API.fetch('/teacher-attendance/qr/generate/', { method: 'POST', body: JSON.stringify({ date: d, expires_minutes: 180 }) });
    const el = document.getElementById('ta-qr');
    el.style.display = 'block';
    el.innerHTML = `
      <div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap">
        <div style="width:160px;height:160px;border:1px solid var(--e);border-radius:12px;overflow:hidden;background:#fff;display:flex;align-items:center;justify-content:center">
          <img alt="QR" style="width:160px;height:160px" src="data:image/png;base64,${res.qr_png_base64}">
        </div>
        <div style="flex:1;min-width:240px">
          <div style="font-weight:900">QR ready</div>
          <div class="sub">Expires: ${res.expires_at}</div>
          <div style="height:8px"></div>
          <div style="font-size:12px;color:var(--66);word-break:break-all">${res.scan_url}</div>
        </div>
      </div>`;
    flash('QR generated. Teachers can scan while logged in.');
}

function taToggleAll(checked) {
    document.querySelectorAll('#ta-body .ta-sel').forEach(cb => { cb.checked = !!checked; });
}

function taSetAll(status) {
    document.querySelectorAll('#ta-body tr').forEach(tr => {
        const sel = tr.querySelector('.ta-status');
        if (sel) sel.value = status;
    });
    flash(`Set all: ${status}`);
}

function taApplySelected(status) {
    const selected = Array.from(document.querySelectorAll('#ta-body tr')).filter(tr => (tr.querySelector('.ta-sel') || {}).checked);
    if (!selected.length) { flash('Select at least one teacher.'); return; }
    selected.forEach(tr => {
        const sel = tr.querySelector('.ta-status');
        if (sel) sel.value = status;
    });
    flash(`Set selected: ${status}`);
}

function taOnlySelectedPresent() {
    const selected = Array.from(document.querySelectorAll('#ta-body tr')).filter(tr => (tr.querySelector('.ta-sel') || {}).checked);
    if (!selected.length) { flash('Select at least one teacher.'); return; }
    taSetAll('absent');
    selected.forEach(tr => {
        const sel = tr.querySelector('.ta-status');
        if (sel) sel.value = 'present';
    });
    flash('Set only selected: present (others absent)');
}

function taFilter() {
    const q = (document.getElementById('ta-q')?.value || '').trim().toLowerCase();
    document.querySelectorAll('#ta-body tr').forEach(tr => {
        const name = (tr.querySelector('td strong')?.textContent || '').trim().toLowerCase();
        tr.style.display = (!q || name.includes(q)) ? '' : 'none';
    });
}

function buildNotificationQuery(cat, options = {}) {
    const params = new URLSearchParams();
    if (cat && cat !== 'all') params.set('category', cat);
    if (options.unread) params.set('unread', 'true');
    if (options.includeFilters !== false && notificationFinanceFiltersEnabled()) {
        const classId = (document.getElementById('notif-class-filter')?.value || '').trim();
        const q = (document.getElementById('notif-student-filter')?.value || '').trim();
        if (classId) params.set('class_id', classId);
        if (q) params.set('q', q);
    }
    return params;
}

async function refreshNotificationsBadge() {
    try {
        const unread = await API.fetch(`/notifications/?${buildNotificationQuery('all', { unread: true, includeFilters: false }).toString()}`);
        const dot = document.getElementById('notif-dot');
        if (dot) dot.style.display = (unread && unread.length) ? 'block' : 'none';
    } catch {}
}

function notificationFinanceFiltersEnabled() {
    const role = (currentUser && currentUser.profile && currentUser.profile.role) || '';
    return ['bursar', 'superadmin', 'admin', 'headteacher', 'deputy', 'dos'].includes(role);
}

async function populateNotificationFilters() {
    const wrap = document.getElementById('notif-filters');
    if (!wrap) return;
    if (!notificationFinanceFiltersEnabled()) {
        wrap.style.display = 'none';
        return;
    }
    wrap.style.display = 'block';
    const sel = document.getElementById('notif-class-filter');
    if (!sel || sel.dataset.ready === '1') return;
    const classes = await API.fetch('/classes/').catch(() => []);
    sel.innerHTML = `<option value="">All classes</option>` + (classes || []).map(c => `<option value="${c.id}">${escapeHtml(c.level || '')}</option>`).join('');
    sel.dataset.ready = '1';
}

function debouncedNotificationFilter() {
    if (NOTIF_FILTER_TIMER) clearTimeout(NOTIF_FILTER_TIMER);
    NOTIF_FILTER_TIMER = setTimeout(() => loadNotifications(ACTIVE_NOTIF_CATEGORY || 'all'), 250);
}

function clearNotificationFilters() {
    const classSel = document.getElementById('notif-class-filter');
    const studentInput = document.getElementById('notif-student-filter');
    if (classSel) classSel.value = '';
    if (studentInput) studentInput.value = '';
    loadNotifications(ACTIVE_NOTIF_CATEGORY || 'all');
}

async function loadNotificationSummary(cat) {
    const wrap = document.getElementById('notif-summary');
    if (!wrap) return;
    try {
        const params = buildNotificationQuery(cat || ACTIVE_NOTIF_CATEGORY || 'all');
        const qs = params.toString() ? `?${params.toString()}` : '';
        const summary = await API.fetch(`/notifications/summary/${qs}`);
        const byCategory = summary && summary.by_category ? summary.by_category : {};
        const byClass = Array.isArray(summary && summary.by_class) ? summary.by_class.slice(0, 4) : [];
        wrap.style.display = '';
        wrap.innerHTML = `
          <div class="notif-summary-grid">
            <div class="notif-summary-card">
              <div class="k">Unread</div>
              <div class="v">${Number(summary && summary.unread_count || 0)}</div>
            </div>
            <div class="notif-summary-card">
              <div class="k">Visible Alerts</div>
              <div class="v">${Number(summary && summary.total || 0)}</div>
            </div>
          </div>
          <div class="notif-summary-chip-row">
            ${Object.entries(byCategory).map(([key, value]) => `<span class="badge">${escapeHtml(String(key))}: ${Number(value || 0)}</span>`).join('') || '<span class="sub">No category totals yet.</span>'}
          </div>
          ${byClass.length ? `<div class="notif-summary-chip-row">${byClass.map(row => `<span class="badge blue">${escapeHtml(row.class_level || 'Class')}: ${Number(row.total || 0)}</span>`).join('')}</div>` : ''}
        `;
    } catch {
        wrap.style.display = 'none';
        wrap.innerHTML = '';
    }
}

function openNotifications() {
    const d = document.getElementById('notif-drawer');
    const ov = document.getElementById('notif-overlay');
    if (ov) ov.style.display = 'block';
    if (d) d.style.transform = 'translateX(0)';
    populateNotificationFilters();
    loadNotifications('all');
}

function closeNotifications() {
    const d = document.getElementById('notif-drawer');
    const ov = document.getElementById('notif-overlay');
    if (d) d.style.transform = 'translateX(105%)';
    if (ov) ov.style.display = 'none';
}

function iconForCategory(cat) {
    if (cat === 'finance') return '$';
    if (cat === 'academic') return 'A';
    if (cat === 'events') return 'E';
    if (cat === 'security') return 'S';
    return '*';
}

function openReceiptPdf(paymentId) {
    if (!paymentId) return;
    // Opens a server-generated PDF receipt in a new tab (session-authenticated).
    window.open(`/api/payments/${paymentId}/receipt/`, '_blank');
}

function openStatementPdf(studentId, year) {
    if (!studentId) return;
    const y = year || currentYear();
    window.open(`/api/invoices/statement/?student=${encodeURIComponent(studentId)}&year=${encodeURIComponent(y)}`, '_blank');
}

function openAdjustmentAdd(studentId, year, term) {
    document.getElementById('adj-id').value = '';
    document.getElementById('adj-student').value = String(studentId || '');
    const active = ACTIVE_TERM_CACHE;
    const defYear = year || ((active && active.academic_year) ? active.academic_year : currentYear());
    const defTerm = term || ((active && active.term_number) ? active.term_number : 1);
    document.getElementById('adj-year').value = String(defYear || '');
    document.getElementById('adj-term').value = String(defTerm || '1');
    document.getElementById('adj-kind').value = 'discount';
    document.getElementById('adj-amount').value = '';
    document.getElementById('adj-title').value = '';
    document.getElementById('adj-notes').value = '';
    openModal('modal-adj');
}

async function saveAdjustment() {
    const id = (document.getElementById('adj-id').value || '').trim();
    const student = (document.getElementById('adj-student').value || '').trim();
    const year = (document.getElementById('adj-year').value || '').trim();
    const term = (document.getElementById('adj-term').value || '').trim();
    const kind = (document.getElementById('adj-kind').value || '').trim();
    const amtRaw = (document.getElementById('adj-amount').value || '').trim();
    const title = (document.getElementById('adj-title').value || '').trim();
    const notes = (document.getElementById('adj-notes').value || '').trim();

    if (!student || !year || !term || !kind || !amtRaw) { flash('Fill student/year/term/type/amount.'); return; }
    const amt = Number(amtRaw);
    if (!Number.isFinite(amt) || amt <= 0) { flash('Amount must be a positive number.'); return; }

    let signed = amt;
    if (kind === 'discount' || kind === 'waiver') signed = -Math.abs(amt);
    if (kind === 'penalty') signed = Math.abs(amt);
    if (kind === 'correction') signed = amt; // allow positive; to reduce due, use discount/waiver.

    const payload = {
        student: Number(student),
        academic_year: Number(year),
        term_number: Number(term),
        kind,
        title: title || null,
        amount: signed,
        notes: notes || null,
        is_active: true,
    };

    try {
        if (id) {
            await API.fetch(`/invoice-adjustments/${id}/`, { method: 'PATCH', body: JSON.stringify(payload) });
        } else {
            await API.fetch('/invoice-adjustments/', { method: 'POST', body: JSON.stringify(payload) });
        }
        closeModal('modal-adj');
        flash('Adjustment saved.');
        if (CURRENT_PAGE === 'adjustments') loadPage('adjustments', null, 'Adjustments');
        else loadPage('finance', null, 'Payments');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to save adjustment.');
    }
}

// Teacher: My Class (attendance + marks) helpers.
function mcEachRow(fn) {
    document.querySelectorAll('#mc-body tr[data-stu]').forEach(fn);
}

function mcSetAllAttendance(status) {
    mcEachRow(tr => {
        const sel = tr.querySelector('.mc-att-status');
        if (sel) sel.value = status;
    });
    try { mcRefreshStats(); } catch {}
}

function mcRefreshStats() {
    const el = document.getElementById('mc-stats');
    if (!el) return;
    let total = 0;
    let present = 0, absent = 0, late = 0, excused = 0;
    let marksCount = 0;
    let sum = 0, min = null, max = null;
    mcEachRow(tr => {
        total += 1;
        const st = (tr.querySelector('.mc-att-status')?.value || 'present').toLowerCase();
        if (st === 'absent') absent += 1;
        else if (st === 'late') late += 1;
        else if (st === 'excused') excused += 1;
        else present += 1;

        const scoreRaw = (tr.querySelector('.mc-mark-score')?.value || '').trim();
        const score = Number(scoreRaw);
        if (scoreRaw && Number.isFinite(score)) {
            marksCount += 1;
            sum += score;
            min = (min === null) ? score : Math.min(min, score);
            max = (max === null) ? score : Math.max(max, score);
        }
    });
    const avg = marksCount ? (sum / marksCount) : null;
    el.textContent = `Students: ${total} | Attendance: ${present} present, ${late} late, ${excused} excused, ${absent} absent | Marks entered: ${marksCount}${avg !== null ? ` (avg ${avg.toFixed(1)}, min ${min}, max ${max})` : ''}`;
}

async function mcLoadAttendance() {
    const d = (document.getElementById('mc-date')?.value || '').trim();
    if (!d) return;
    try {
        const items = await API.fetch(`/attendance/?date=${encodeURIComponent(d)}`).catch(() => []);
        const map = new Map((items || []).map(a => [Number(a.student), (a.status || '').toString().toLowerCase()]));
        mcEachRow(tr => {
            const sid = Number(tr.getAttribute('data-stu'));
            const st = map.get(sid) || 'present';
            const sel = tr.querySelector('.mc-att-status');
            if (sel) sel.value = st;
            tr.classList.toggle('row-absent', st === 'absent');
            tr.classList.toggle('row-late', st === 'late');
        });
        try { mcRefreshStats(); } catch {}
        flash('Attendance loaded.');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to load attendance.');
    }
}

async function mcSaveAttendance() {
    const d = (document.getElementById('mc-date')?.value || '').trim();
    if (!d) { flash('Pick a date.'); return; }
    const items = [];
    mcEachRow(tr => {
        const sid = Number(tr.getAttribute('data-stu'));
        const sel = tr.querySelector('.mc-att-status');
        const st = sel ? sel.value : 'present';
        if (sid) items.push({ student: sid, status: st });
    });
    try {
        const res = await API.fetch('/attendance/bulk-upsert/', { method: 'POST', body: JSON.stringify({ date: d, items }) });
        flash(`Attendance saved (${res && res.saved ? res.saved : 0}).`);
        await mcLoadAttendance();
        try { mcRefreshStats(); } catch {}
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to save attendance.');
    }
}

async function mcLoadMarks() {
    const year = (document.getElementById('mc-year')?.value || '').trim();
    const term = (document.getElementById('mc-term')?.value || '').trim();
    const subject = (document.getElementById('mc-subject')?.value || '').trim();
    if (!subject) { flash('Enter/select a subject first.'); return; }
    try {
        const qs = new URLSearchParams({ year, term, subject });
        const marks = await API.fetch(`/marks/?${qs.toString()}`).catch(() => []);
        const map = new Map((marks || []).map(m => [Number(m.student), m]));
        mcEachRow(tr => {
            const sid = Number(tr.getAttribute('data-stu'));
            const m = map.get(sid) || null;
            const score = tr.querySelector('.mc-mark-score');
            const rem = tr.querySelector('.mc-mark-remarks');
            if (score) score.value = (m && m.score !== undefined && m.score !== null) ? String(m.score) : '';
            if (rem) rem.value = (m && m.remarks) ? String(m.remarks) : '';
            const v = (m && m.score !== undefined && m.score !== null) ? Number(m.score) : null;
            tr.classList.toggle('row-low', v !== null && Number.isFinite(v) && v < 50);
            tr.classList.toggle('row-high', v !== null && Number.isFinite(v) && v >= 80);
        });
        try { mcRefreshStats(); } catch {}
        flash('Marks loaded.');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to load marks.');
    }
}

async function mcSaveMarks() {
    const year = (document.getElementById('mc-year')?.value || '').trim();
    const term = (document.getElementById('mc-term')?.value || '').trim();
    const subject = (document.getElementById('mc-subject')?.value || '').trim();
    if (!subject) { flash('Enter/select a subject.'); return; }
    if (!year || !term) { flash('Set year and term.'); return; }

    const items = [];
    mcEachRow(tr => {
        const sid = Number(tr.getAttribute('data-stu'));
        const scoreEl = tr.querySelector('.mc-mark-score');
        const remEl = tr.querySelector('.mc-mark-remarks');
        const scoreRaw = (scoreEl && scoreEl.value !== undefined) ? String(scoreEl.value).trim() : '';
        if (!scoreRaw) return;
        const score = Number(scoreRaw);
        if (!Number.isFinite(score)) return;
        const remarks = remEl ? String(remEl.value || '').trim() : '';
        items.push({ student: sid, score: Math.round(score), remarks });
    });

    if (!items.length) { flash('Enter at least one score to save.'); return; }

    try {
        const res = await API.fetch('/marks/bulk-upsert/', { method: 'POST', body: JSON.stringify({ year, term, subject, items }) });
        flash(`Marks saved (${res && res.saved ? res.saved : 0}).`);
        try { await mcLoadMarks(); } catch {}
        try { mcRefreshStats(); } catch {}
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to save marks.');
    }
}

function clearBankSlipImage(studentId) {
    const hid = document.getElementById(`bs-img-${studentId}`);
    const wrap = document.getElementById(`bs-prev-wrap-${studentId}`);
    const img = document.getElementById(`bs-prev-${studentId}`);
    if (hid) hid.value = '';
    if (img) img.src = '';
    if (wrap) wrap.style.display = 'none';
}

function wireBankSlipZones() {
    document.querySelectorAll("[id^='bs-drop-']").forEach(zone => {
        const sid = String(zone.id).replace('bs-drop-', '');
        const input = document.getElementById(`bs-file-${sid}`);
        const hid = document.getElementById(`bs-img-${sid}`);
        const wrap = document.getElementById(`bs-prev-wrap-${sid}`);
        const prev = document.getElementById(`bs-prev-${sid}`);
        if (!input || !hid) return;
        wireDropZone(zone, input, async (files) => {
            try {
                const file = files && files.length ? files[0] : null;
                const url = await uploadImageFile(file);
                hid.value = url;
                if (prev) prev.src = url;
                if (wrap) wrap.style.display = 'block';
                flash('Slip uploaded.');
            } catch (e) {
                flash((e && e.detail) ? e.detail : 'Failed to upload image.');
            }
        });
    });
}

async function submitBankSlip(studentId, academicYear, termNumber) {
    const amt = (document.getElementById(`bs-amt-${studentId}`)?.value || '').trim();
    const ref = (document.getElementById(`bs-ref-${studentId}`)?.value || '').trim();
    const img = (document.getElementById(`bs-img-${studentId}`)?.value || '').trim();
    if (!amt) { flash('Enter amount.'); return; }
    if (!img) { flash('Upload the slip image.'); return; }
    if (!academicYear || !termNumber) {
        // Still allow submit without term scoping, but warn.
        academicYear = null;
        termNumber = null;
    }
    try {
        await API.fetch('/payment-submissions/bank-slip/', {
            method: 'POST',
            body: JSON.stringify({
                student: studentId,
                amount: amt,
                academic_year: academicYear,
                term_number: termNumber,
                receipt_image_url: img,
                reference: ref || null,
            })
        });
        flash('Submitted for approval.');
        loadPage('my_fees', null, 'My Fees');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to submit bank slip.');
    }
}

async function toggleAdjustmentActive(id, isActive) {
    try {
        await API.fetch(`/invoice-adjustments/${id}/`, { method: 'PATCH', body: JSON.stringify({ is_active: !!isActive }) });
        flash('Adjustment updated.');
        loadPage('adjustments', null, 'Adjustments');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to update adjustment.');
    }
}

async function createGuardianLink() {
    const parent_user = (document.getElementById('gl-parent')?.value || '').trim();
    const student = (document.getElementById('gl-student')?.value || '').trim();
    const relationship = (document.getElementById('gl-rel')?.value || '').trim() || 'parent';
    if (!parent_user || !student) { flash('Select parent and student.'); return; }
    try {
        await API.fetch('/guardian-links/', { method: 'POST', body: JSON.stringify({ parent_user: Number(parent_user), student: Number(student), relationship, is_active: true }) });
        flash('Linked.');
        loadPage('guardian_links', null, 'Guardian Links');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to create link.');
    }
}

async function toggleGuardianLink(id, isActive) {
    try {
        await API.fetch(`/guardian-links/${id}/`, { method: 'PATCH', body: JSON.stringify({ is_active: !!isActive }) });
        flash('Link updated.');
        loadPage('guardian_links', null, 'Guardian Links');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to update link.');
    }
}

async function deleteGuardianLink(id) {
    if (!confirm('Delete this link?')) return;
    try {
        await API.fetch(`/guardian-links/${id}/`, { method: 'DELETE' });
        flash('Deleted.');
        loadPage('guardian_links', null, 'Guardian Links');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to delete link.');
    }
}

async function loadNotifications(cat) {
    ACTIVE_NOTIF_CATEGORY = cat || 'all';
    try { window.ACTIVE_NOTIF_CATEGORY = ACTIVE_NOTIF_CATEGORY; } catch {}
    const params = buildNotificationQuery(cat);
    const qs = params.toString() ? `?${params.toString()}` : '';
    const items = await API.fetch(`/notifications/${qs}`).catch(() => []);
    await loadNotificationSummary(cat);
    const el = document.getElementById('notif-list');
    if (!el) return;
    if (!items || items.length === 0) {
        el.innerHTML = `<div style="padding:16px;color:var(--66)">No notifications.</div>`;
        return;
    }
    el.innerHTML = (items || []).slice(0, 120).map(n => `
      <div style="display:flex;gap:12px;padding:12px 14px;border-bottom:1px solid var(--f0);${n.is_read ? '' : 'background:rgba(122,0,0,0.03)'}">
        <div style="font-size:18px;flex-shrink:0">${iconForCategory(n.category)}</div>
        <div style="flex:1">
          <div style="font-weight:${n.is_read ? 700 : 900}">${escapeHtml(n.title || '')}</div>
          <div style="font-size:12px;color:var(--66);margin-top:2px">${escapeHtml(n.message || '')}</div>
          <div style="margin-top:4px;display:flex;gap:6px;flex-wrap:wrap">
            ${n.school_class_level ? `<span class="badge blue">Class ${escapeHtml(n.school_class_level)}</span>` : ''}
            ${n.student_name ? `<span class="badge">${escapeHtml(n.student_name)}</span>` : ''}
          </div>
          <div class="sub" style="margin-top:4px">${(n.created_at || '').toString().slice(0, 19).replace('T',' ')}</div>
          <div style="margin-top:6px;display:flex;gap:8px;flex-wrap:wrap">
            ${n.link_page ? `<button class="btn btn-xs btn-ghost" onclick="jumpFromNotification('${n.link_page}', ${n.id})">Open</button>` : ''}
            ${n.is_read ? '' : `<button class="btn btn-xs btn-ghost" onclick="markNotificationRead(${n.id})">Mark read</button>`}
          </div>
        </div>
      </div>
    `).join('');
}

async function markNotificationRead(id) {
    await API.fetch(`/notifications/${id}/mark-read/`, { method: 'POST' });
    await refreshNotificationsBadge();
    loadNotifications(ACTIVE_NOTIF_CATEGORY || 'all');
}

async function markAllNotificationsRead() {
    await API.fetch('/notifications/mark-all-read/', { method: 'POST' });
    await refreshNotificationsBadge();
    loadNotifications(ACTIVE_NOTIF_CATEGORY || 'all');
}

async function jumpFromNotification(page, notifId) {
    try { await API.fetch(`/notifications/${notifId}/mark-read/`, { method: 'POST' }); } catch {}
    closeNotifications();
    loadPage(page);
    refreshNotificationsBadge();
}

function getNotifPrefsFromUI() {
    const keys = ['in_app', 'finance', 'academic', 'events', 'security', 'system'];
    const out = {};
    keys.forEach(k => {
        const el = document.getElementById('np-' + k);
        if (el) out[k] = !!el.checked;
    });
    return out;
}

async function saveNotificationPrefs() {
    const notification_prefs = getNotifPrefsFromUI();
    await API.fetch('/auth/me/', { method: 'PATCH', body: JSON.stringify({ notification_prefs }) });
    flash('Notification preferences saved.');
}

function clearAnnouncementForm() {
    document.getElementById('an-id').value = '';
    document.getElementById('an-title').value = '';
    document.getElementById('an-body').value = '';
    document.getElementById('an-aud').value = '';
    const tpl = document.getElementById('an-tpl'); if (tpl) tpl.value = '';
    const exp = document.getElementById('an-exp'); if (exp) exp.value = '';
    document.getElementById('an-pub').checked = true;
    document.getElementById('an-pin').checked = false;
    const arch = document.getElementById('an-arch'); if (arch) arch.checked = false;
    const del = document.getElementById('an-del');
    if (del) del.style.display = 'none';
    clearAnnouncementImage();
}

async function openAnnouncementAdd() {
    clearAnnouncementForm();
    flash('Ready to create announcement.');
}

async function openAnnouncementEdit(id) {
    const a = await API.fetch(`/announcements/${id}/`);
    document.getElementById('an-id').value = a.id;
    document.getElementById('an-title').value = a.title || '';
    document.getElementById('an-body').value = a.body || '';
    document.getElementById('an-aud').value = (a.audience_roles || []).join(', ');
    const tpl = document.getElementById('an-tpl'); if (tpl) tpl.value = '';
    if (document.getElementById('an-img')) document.getElementById('an-img').value = a.image_url || '';
    const exp = document.getElementById('an-exp');
    if (exp) exp.value = a.expires_at ? String(a.expires_at).slice(0, 16) : '';
    document.getElementById('an-pub').checked = !!a.is_published;
    document.getElementById('an-pin').checked = !!a.is_pinned;
    const arch = document.getElementById('an-arch'); if (arch) arch.checked = !!a.is_archived;
    const del = document.getElementById('an-del');
    if (del) del.style.display = 'inline-flex';
    wireAnnouncementImageControls();
    announcementPreviewFromUrl();
}

async function saveAnnouncement() {
    const id = document.getElementById('an-id').value;
    const title = document.getElementById('an-title').value.trim();
    const body = document.getElementById('an-body').value.trim();
    const audRaw = document.getElementById('an-aud').value.trim();
    const audience_roles = audRaw ? audRaw.split(',').map(s => s.trim()).filter(Boolean) : [];
    const expRaw = (document.getElementById('an-exp')?.value || '').trim();
    const expires_at = expRaw ? new Date(expRaw).toISOString() : null;
    const is_published = !!document.getElementById('an-pub').checked;
    const is_pinned = !!document.getElementById('an-pin').checked;
    const is_archived = !!document.getElementById('an-arch')?.checked;
    if (!title || !body) { flash('Title and body are required.'); return; }
    const image_url = (document.getElementById('an-img')?.value || '').trim() || null;
    const payload = { title, body, audience_roles, image_url, is_published, is_pinned, expires_at, is_archived };
    if (id) await API.fetch(`/announcements/${id}/`, { method: 'PATCH', body: JSON.stringify(payload) });
    else await API.fetch('/announcements/', { method: 'POST', body: JSON.stringify(payload) });
    flash('Announcement saved.');
    loadPage('announcements');
}

async function createAnnouncementFromTemplate() {
    const template_id = (document.getElementById('an-tpl')?.value || '').trim();
    if (!template_id) { flash('Choose a published template first.'); return; }
    const payload = {
        template_id,
        title: (document.getElementById('an-title')?.value || '').trim() || undefined,
        body: (document.getElementById('an-body')?.value || '').trim() || undefined,
        audience_roles: ((document.getElementById('an-aud')?.value || '').trim()).split(',').map(s => s.trim()).filter(Boolean),
        image_url: (document.getElementById('an-img')?.value || '').trim() || null,
        is_published: !!document.getElementById('an-pub')?.checked,
        is_pinned: !!document.getElementById('an-pin')?.checked,
        expires_at: (document.getElementById('an-exp')?.value || '').trim() ? new Date(document.getElementById('an-exp').value).toISOString() : null,
    };
    try {
        await API.fetch('/announcements/from-template/', { method: 'POST', body: JSON.stringify(payload) });
        flash('Announcement created from template.');
        loadPage('announcements');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to create announcement from template.');
    }
}

function clearAnnouncementImage() {
    const img = document.getElementById('an-img');
    if (img) img.value = '';
    const wrap = document.getElementById('an-prev-wrap');
    if (wrap) wrap.style.display = 'none';
    const pv = document.getElementById('an-prev');
    if (pv) pv.src = '';
    const f = document.getElementById('an-file');
    if (f) f.value = '';
}

function announcementPreviewFromUrl() {
    const url = (document.getElementById('an-img')?.value || '').trim();
    const wrap = document.getElementById('an-prev-wrap');
    const pv = document.getElementById('an-prev');
    if (!wrap || !pv) return;
    if (!url) { wrap.style.display = 'none'; pv.src = ''; return; }
    pv.src = url;
    wrap.style.display = '';
}

function wireAnnouncementImageControls() {
    const dz = document.getElementById('an-drop');
    const input = document.getElementById('an-file');
    const urlInput = document.getElementById('an-img');
    if (!dz || !input || !urlInput) return;
    wireDropZone(dz, input, async (files) => {
        try {
            dz.style.opacity = '0.7';
            const url = await uploadImageFile(files[0]);
            urlInput.value = url;
            announcementPreviewFromUrl();
            flash('Image uploaded.');
        } catch (e) {
            flash((e && e.detail) ? e.detail : 'Upload failed.');
        } finally {
            dz.style.opacity = '';
        }
    });
    urlInput.addEventListener('input', () => announcementPreviewFromUrl());
}

async function deleteAnnouncement() {
    const id = document.getElementById('an-id').value;
    if (!id) return;
    await API.fetch(`/announcements/${id}/`, { method: 'DELETE' });
    flash('Announcement deleted.');
    loadPage('announcements');
}

async function startNewTerm() {
    const academic_year = parseInt((document.getElementById('nt-yr')?.value || '').trim(), 10);
    const term_number = parseInt((document.getElementById('nt-num')?.value || '').trim(), 10);
    const start_date = (document.getElementById('nt-st')?.value || '').trim();
    const end_date = (document.getElementById('nt-en')?.value || '').trim();
    const holiday_break_days = parseInt(document.getElementById('nt-brk').value, 10) || 0;
    const auto_generate_invoices = document.getElementById('nt-fees').checked;
    const sms_parents = document.getElementById('nt-sms').checked;
    const open_mark_entry = document.getElementById('nt-marks').checked;

    if (!academic_year || !term_number || !start_date || !end_date) {
        flash('Fill Academic Year, Term Number, Start Date, and End Date.');
        return;
    }
    if (term_number < 1 || term_number > 3) {
        flash('Term number must be 1, 2, or 3.');
        return;
    }

    try {
        await API.fetch('/terms/start-new/', { method: 'POST', body: JSON.stringify({ academic_year, term_number, start_date, end_date, holiday_break_days, auto_generate_invoices, sms_parents, open_mark_entry }) });
        closeModal('modal-term');
        flash('New term started.');
        refreshTermChip();
        loadPage('terms');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to start term.');
    }
}

let promoRows = [];
async function loadPromotionList() {
    const class_id = document.getElementById('promo-class').value;
    const section = (document.getElementById('promo-sec').value.trim() || 'A').toUpperCase();
    promoRows = await API.fetch(`/promotions/students-for-promotion/${class_id}/${encodeURIComponent(section)}/`);
    renderPromotionRows();
}

function renderPromotionRows() {
    const body = document.getElementById('promo-body');
    if (!body) return;
    body.innerHTML = promoRows.map(r => `
      <tr>
        <td>${r.first_name} ${r.last_name}</td>
        <td>${r.student_system_id}</td>
        <td>${r.term_average}%</td>
        <td>${r.class_position}</td>
        <td>
          <select class="field-select" onchange="onPromoDecision(${r.student_id}, this.value)" style="min-width:140px">
            <option value="promote" ${r.suggested_decision === 'promote' ? 'selected' : ''}>Promote</option>
            <option value="repeat_year" ${r.suggested_decision === 'repeat_year' ? 'selected' : ''}>Repeat</option>
            <option value="graduate" ${r.suggested_decision === 'graduate' ? 'selected' : ''}>Graduate</option>
            <option value="transfer_out">Transfer</option>
            <option value="withdraw">Withdraw</option>
          </select>
        </td>
        <td><input class="field-input" value="${(r.promotion_notes || '').replace(/\"/g,'&quot;')}" oninput="onPromoNote(${r.student_id}, this.value)"></td>
      </tr>
    `).join('');
}

function onPromoDecision(studentId, decision) {
    promoRows = promoRows.map(r => r.student_id === studentId ? { ...r, suggested_decision: decision } : r);
}

function onPromoNote(studentId, note) {
    promoRows = promoRows.map(r => r.student_id === studentId ? { ...r, promotion_notes: note } : r);
}

async function autoPromote() {
    const class_id = document.getElementById('promo-class').value;
    const section = (document.getElementById('promo-sec').value.trim() || 'A').toUpperCase();
    const suggestions = await API.fetch('/promotions/auto-promote/', { method: 'POST', body: JSON.stringify({ class_id, section }) });
    const map = new Map(suggestions.map(s => [s.student_id, s]));
    promoRows = promoRows.map(r => {
        const s = map.get(r.student_id);
        return s ? { ...r, suggested_decision: s.decision, term_average: s.term_average, promotion_notes: s.notes || r.promotion_notes } : r;
    });
    renderPromotionRows();
    flash('Auto-suggestions applied.');
}

async function confirmPromotions() {
    const promotions = promoRows.map(r => ({ student_id: r.student_id, decision: r.suggested_decision, notes: r.promotion_notes || '' }));
    await API.fetch('/promotions/confirm/', { method: 'POST', body: JSON.stringify({ promotions }) });
    flash('Promotions confirmed.');
}

async function downloadReportCard() { 
    const student_id = document.getElementById('rc-stu').value; 
    const term_number = document.getElementById('rc-term').value; 
    const academic_year = document.getElementById('rc-year').value; 
    const role = (currentUser.profile && currentUser.profile.role) || 'superadmin';

    // Partial-release UX: parents/students can always view summary, but PDF may be blocked.
    if (['parent', 'student'].includes(role)) {
        try {
            const s = await API.fetch(`/report-cards/summary/${student_id}/${term_number}/${academic_year}/`);
            if (s && s.results_blocked) {
                flash(s.results_block_reason || 'Results are held until fees are cleared.');
                flash(`Summary: Avg ${fmt(Number(s.overall_average || 0).toFixed(1))}% · Position ${s.class_position || '-'}`);
                return;
            }
        } catch (e) {
            // If summary fails, fall back to the PDF attempt.
        }
    }

    window.open(`/api/report-cards/generate/${student_id}/${term_number}/${academic_year}/`, '_blank'); 
} 
 
async function queueReportCard() { 
    const student_id = document.getElementById('rc-stu').value; 
    const term_number = document.getElementById('rc-term').value; 
    const academic_year = document.getElementById('rc-year').value; 
    try { 
        await API.fetch('/print-queue/', { 
            method: 'POST', 
            body: JSON.stringify({ 
                kind: 'report_card', 
                student_id, 
                title: '', 
                note: `Term ${term_number} ${academic_year}`, 
                payload: { term_number, academic_year }, 
                is_sensitive: false, 
                expires_hours: 24 * 30, 
            }) 
        }); 
        flash('Queued for Reception printing.'); 
    } catch (e) { 
        flash((e && e.detail) ? e.detail : 'Failed to queue report card.'); 
    } 
} 
 
async function printReportCardQuick(studentPk) { 
    // Reception/Admin quick print: uses active term if available, otherwise current year/term 1.
    let term = 1;
    let year = new Date().getFullYear();
    try {
        const t = await API.fetch('/terms/');
        if (t && t.term_number) term = t.term_number;
        if (t && t.academic_year) year = t.academic_year;
    } catch {}
    const role = (currentUser.profile && currentUser.profile.role) || 'superadmin';
    if (['parent', 'student'].includes(role)) {
        try {
            const s = await API.fetch(`/report-cards/summary/${studentPk}/${term}/${year}/`);
            if (s && s.results_blocked) {
                flash(s.results_block_reason || 'Results are held until fees are cleared.');
                flash(`Summary: Avg ${fmt(Number(s.overall_average || 0).toFixed(1))}% · Position ${s.class_position || '-'}`);
                return;
            }
        } catch {}
    }
    window.open(`/api/report-cards/generate/${studentPk}/${term}/${year}/`, '_blank');
}

async function emailAllParents() { 
    const class_id = document.getElementById('rc-class').value; 
    const term_number = document.getElementById('rc-term2').value; 
    const academic_year = document.getElementById('rc-year2').value; 
    await API.fetch('/report-cards/email-all-parents/', { method: 'POST', body: JSON.stringify({ class_id, term_number, academic_year }) }); 
    flash('Emails sent (console backend in dev).'); 
} 
 
// ----- Grading ----- 
function gradingStarterRows() {
    return [
        { min_score: 0, max_score: 29, grade: 'F9', points: 9, remark: 'Fail' },
        { min_score: 30, max_score: 39, grade: 'P8', points: 8, remark: 'Weak pass' },
        { min_score: 40, max_score: 49, grade: 'P7', points: 7, remark: 'Pass' },
        { min_score: 50, max_score: 59, grade: 'C6', points: 6, remark: 'Fair' },
        { min_score: 60, max_score: 69, grade: 'C5', points: 5, remark: 'Good' },
        { min_score: 70, max_score: 79, grade: 'C4', points: 4, remark: 'Credit' },
        { min_score: 80, max_score: 89, grade: 'C3', points: 3, remark: 'Strong credit' },
        { min_score: 90, max_score: 94, grade: 'D2', points: 2, remark: 'Distinction' },
        { min_score: 95, max_score: 100, grade: 'D1', points: 1, remark: 'Top distinction' },
    ];
}

function normalizeGradingRows(rows) {
    return (Array.isArray(rows) ? rows : []).map((row) => ({
        min_score: Number(row.min_score ?? 0),
        max_score: Number(row.max_score ?? 0),
        grade: String(row.grade || '').trim(),
        points: String(row.points ?? '').trim() === '' ? null : Number(row.points),
        remark: String(row.remark || row.remarks || '').trim(),
    })).sort((a, b) => a.min_score - b.min_score);
}

function gradingRowPreview(row) {
    const min = Number.isFinite(Number(row.min_score)) ? Number(row.min_score) : 0;
    const max = Number.isFinite(Number(row.max_score)) ? Number(row.max_score) : 0;
    const grade = String(row.grade || '').trim() || '?';
    return `${min}-${max} = ${grade}`;
}

function gradingBandSummary(rows) {
    const normalized = normalizeGradingRows(rows);
    if (!normalized.length) return '<span class="sub">No bands</span>';
    const preview = normalized.slice(0, 4).map(row => `<div class="sub" style="margin:0">${escapeHtml(gradingRowPreview(row))}</div>`).join('');
    const extra = normalized.length > 4 ? `<div class="sub" style="margin:0">+${normalized.length - 4} more band(s)</div>` : '';
    return preview + extra;
}

function syncGradingJsonMirror() {
    const json = document.getElementById('g-json');
    if (json) json.value = JSON.stringify(normalizeGradingRows(GRADING_ROWS), null, 2);
    const preview = document.getElementById('g-preview');
    if (preview) preview.innerHTML = gradingBandSummary(GRADING_ROWS);
}

function renderGradingRows() {
    const body = document.getElementById('g-rows-body');
    if (!body) return;
    body.innerHTML = GRADING_ROWS.map((row, idx) => `
      <tr>
        <td><input class="field-input" type="number" min="0" max="100" value="${escapeHtml(row.min_score)}" oninput="updateGradingRow(${idx}, 'min_score', this.value)"></td>
        <td><input class="field-input" type="number" min="0" max="100" value="${escapeHtml(row.max_score)}" oninput="updateGradingRow(${idx}, 'max_score', this.value)"></td>
        <td><input class="field-input" value="${escapeHtml(row.grade)}" oninput="updateGradingRow(${idx}, 'grade', this.value)" placeholder="e.g. F9"></td>
        <td><input class="field-input" type="number" min="0" value="${row.points == null ? '' : escapeHtml(row.points)}" oninput="updateGradingRow(${idx}, 'points', this.value)" placeholder="Optional"></td>
        <td><input class="field-input" value="${escapeHtml(row.remark || '')}" oninput="updateGradingRow(${idx}, 'remark', this.value)" placeholder="Optional remark"></td>
        <td id="g-prev-${idx}" class="mono" style="font-size:12px">${escapeHtml(gradingRowPreview(row))}</td>
        <td><button class="btn btn-xs btn-ghost" onclick="removeGradingRow(${idx})">Remove</button></td>
      </tr>`).join('') || `<tr><td colspan="7" style="color:var(--99)">No bands yet.</td></tr>`;
    syncGradingJsonMirror();
}

function updateGradingRow(index, key, value) {
    if (!GRADING_ROWS[index]) return;
    if (['min_score', 'max_score'].includes(key)) {
        GRADING_ROWS[index][key] = String(value || '').trim() === '' ? 0 : Number(value);
    } else if (key === 'points') {
        GRADING_ROWS[index][key] = String(value || '').trim() === '' ? null : Number(value);
    } else {
        GRADING_ROWS[index][key] = value;
    }
    const previewCell = document.getElementById(`g-prev-${index}`);
    if (previewCell) previewCell.textContent = gradingRowPreview(GRADING_ROWS[index]);
    syncGradingJsonMirror();
}

function addGradingRow() {
    GRADING_ROWS.push({ min_score: 0, max_score: 0, grade: '', points: null, remark: '' });
    renderGradingRows();
}

function removeGradingRow(index) {
    GRADING_ROWS.splice(index, 1);
    renderGradingRows();
}

function loadGradingStarter() {
    GRADING_ROWS = gradingStarterRows();
    renderGradingRows();
}

function openGradingCreate() { 
    const id = document.getElementById('g-id'); 
    const name = document.getElementById('g-name'); 
    const cls = document.getElementById('g-class'); 
    if (id) id.value = ''; 
    if (name) name.value = 'Default scale'; 
    if (cls) cls.value = ''; 
    GRADING_ROWS = gradingStarterRows();
    renderGradingRows();
    openModal('modal-grading'); 
} 
 
async function openGradingEdit(id) { 
    const s = await API.fetch(`/grading-scales/${id}/`); 
    document.getElementById('g-id').value = String(s.id); 
    document.getElementById('g-name').value = s.name || ''; 
    document.getElementById('g-class').value = s.school_class ? String(s.school_class) : ''; 
    GRADING_ROWS = normalizeGradingRows(s.scale_data || []); 
    renderGradingRows();
    openModal('modal-grading'); 
} 
 
async function saveGradingScale() { 
    const id = (document.getElementById('g-id').value || '').trim(); 
    const name = (document.getElementById('g-name').value || '').trim(); 
    const school_class = (document.getElementById('g-class').value || '').trim() || null; 
    if (!name) { flash('Name is required.'); return; } 
    const scale_data = normalizeGradingRows(GRADING_ROWS);
    if (!scale_data.length) { flash('Add at least one grading band.'); return; }
    for (const row of scale_data) {
        if (!row.grade) { flash('Each grading band needs a grade.'); return; }
        if (!Number.isFinite(row.min_score) || !Number.isFinite(row.max_score)) { flash('Every grading band needs valid score limits.'); return; }
        if (row.min_score > row.max_score) { flash(`Invalid band ${gradingRowPreview(row)}. "From" cannot be greater than "To".`); return; }
    }
    const payload = { name, scale_data, school_class }; 
    try { 
        if (id) await API.fetch(`/grading-scales/${id}/`, { method: 'PATCH', body: JSON.stringify(payload) }); 
        else await API.fetch('/grading-scales/', { method: 'POST', body: JSON.stringify(payload) }); 
        flash('Saved grading scale.'); 
        closeModal('modal-grading'); 
        loadPage('grading'); 
    } catch (e) { 
        flash((e && e.detail) ? e.detail : 'Failed to save.'); 
    } 
} 
 
async function setDefaultGradingScale(id) { 
    try { 
        await API.fetch('/grading-scales/set-default/', { method: 'POST', body: JSON.stringify({ id }) }); 
        flash('Default grading scale updated.'); 
        loadPage('grading'); 
    } catch (e) { 
        flash((e && e.detail) ? e.detail : 'Failed to set default.'); 
    } 
} 
 
function flash(msg) { 
    const el = document.createElement('div');
    el.className = 'flash-success';
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3200);
}

const CRED_SERVICE_INFO = {
    google_oauth: {
        label: 'Google OAuth',
        fields: { client_id: true, client_secret: true, api_key: false },
        labels: { client_id: 'Client ID', client_secret: 'Client Secret', api_key: 'API Key' },
        hints: {
            client_id: 'From Google Cloud Console (OAuth client).',
            client_secret: 'Keep secret. Used by server for OAuth flow.',
            api_key: '',
        },
        extra: [
            { key: 'allowed_domains', label: 'Allowed domains (comma)', placeholder: 'bitende.sch.ug', type: 'text' },
        ],
        help: 'Used for Google sign-in via django-allauth. If disabled, Google login will not work.'
    },
    mtn_momo: {
        label: 'MTN Mobile Money',
        fields: { client_id: true, client_secret: true, api_key: true },
        labels: { client_id: 'API User', client_secret: 'API Secret', api_key: 'Subscription Key' },
        hints: {
            client_id: 'MoMo API user ID from MTN MoMo.',
            client_secret: 'MoMo API key/secret paired with the API user.',
            api_key: 'Subscription key for the MoMo product in APIM.',
        },
        extra: [
            { key: 'environment', label: 'Environment', placeholder: 'sandbox or production', type: 'text' },
            { key: 'product', label: 'Product', placeholder: 'collection', type: 'text' },
            { key: 'base_url', label: 'Base URL', placeholder: 'https://sandbox.momodeveloper.mtn.com', type: 'text' },
            { key: 'token_path', label: 'Token Path', placeholder: '/collection/token/', type: 'text' },
            { key: 'callback_url', label: 'Callback URL', placeholder: 'https://yourdomain/...', type: 'text' },
        ],
        help: 'Used for receiving payments via MTN MoMo. Verify now performs a real access-token request when the server has outbound internet.'
    },
    airtel_money: {
        label: 'Airtel Mobile Money',
        fields: { client_id: true, client_secret: true, api_key: true },
        labels: { client_id: 'Client ID', client_secret: 'Client Secret', api_key: 'API Key' },
        hints: {
            client_id: 'From Airtel developer portal/app.',
            client_secret: 'Keep secret.',
            api_key: 'Optional extra API/merchant key if your Airtel setup uses one.',
        },
        extra: [
            { key: 'environment', label: 'Environment', placeholder: 'sandbox or production', type: 'text' },
            { key: 'base_url', label: 'Base URL', placeholder: 'https://openapiuat.airtel.africa', type: 'text' },
            { key: 'token_url', label: 'Token URL', placeholder: 'https://openapiuat.airtel.africa/auth/oauth2/token', type: 'text' },
            { key: 'auth_style', label: 'Auth Style', placeholder: 'body or basic', type: 'text' },
            { key: 'payload_format', label: 'Payload Format', placeholder: 'json or form', type: 'text' },
            { key: 'grant_type', label: 'Grant Type', placeholder: 'client_credentials', type: 'text' },
            { key: 'country', label: 'Country Code', placeholder: 'UG', type: 'text' },
            { key: 'currency', label: 'Currency Code', placeholder: 'UGX', type: 'text' },
            { key: 'callback_url', label: 'Callback URL', placeholder: 'https://yourdomain/...', type: 'text' },
        ],
        help: 'Used for receiving payments via Airtel Money. Verify now performs a real token request using the configured token URL or base URL.'
    },
    twilio_sms: {
        label: 'Twilio SMS',
        fields: { client_id: true, client_secret: true, api_key: false },
        labels: { client_id: 'Account SID', client_secret: 'Auth Token', api_key: 'API Key' },
        hints: {
            client_id: 'Twilio Account SID.',
            client_secret: 'Twilio Auth Token.',
            api_key: '',
        },
        extra: [
            { key: 'from_number', label: 'From number', placeholder: '+15005550006', type: 'text' },
        ],
        help: 'Used for sending SMS notifications (credentials, fee reminders, alerts).'
    },
    email_smtp: {
        label: 'Custom SMTP (Email)',
        fields: { client_id: true, client_secret: true, api_key: false },
        labels: { client_id: 'SMTP Host', client_secret: 'SMTP Password / Token', api_key: 'API Key' },
        hints: {
            client_id: 'Example: smtp.gmail.com',
            client_secret: 'For Gmail, use an App Password (no Google Console needed).',
            api_key: '',
        },
        extra: [
            { key: 'port', label: 'Port', placeholder: '587', type: 'number' },
            { key: 'username', label: 'Username', placeholder: 'school@gmail.com', type: 'text' },
            { key: 'use_tls', label: 'Use TLS (true/false)', placeholder: 'true', type: 'text' },
        ],
        help: 'Alternative SMTP configuration (any provider). Common ports: 587 (TLS) or 465 (SSL).'
    },
    gmail_smtp: {
        label: 'Gmail SMTP (App Password)',
        fields: { client_id: false, client_secret: true, api_key: false },
        labels: { client_secret: 'App Password (16 chars)' },
        hints: { client_secret: 'Create an App Password on myaccount.google.com/apppasswords (no Google Cloud Console needed).' },
        extra: [
            { key: 'username', label: 'Gmail address (username)', placeholder: 'schoolname@gmail.com', type: 'text' },
        ],
        help: 'Send email using Gmail SMTP. Server is fixed: smtp.gmail.com:587 (TLS).'
    },
    megasms: {
        label: 'MegaSMS Uganda (SMS)',
        fields: { client_id: false, client_secret: false, api_key: true },
        labels: { api_key: 'API key' },
        hints: { api_key: 'Paste the API key from MegaSMS.' },
        extra: [
            { key: 'url', label: 'API URL', placeholder: 'https://megasmsug.com/api/v1/send', type: 'text' },
            { key: 'sender', label: 'Sender ID', placeholder: 'StMarysUG', type: 'text' },
            { key: 'payload_format', label: 'Payload format (form/json)', placeholder: 'form', type: 'text' },
        ],
        help: 'Uganda-focused SMS gateway. Used by fee reminders, credentials SMS, and bulk notices (if enabled).'
    },
    zapier_webhook: {
        label: 'Zapier Webhook',
        fields: { client_id: false, client_secret: false, api_key: false },
        labels: { client_id: 'Client ID', client_secret: 'Client Secret', api_key: 'API Key' },
        hints: { client_id: '', client_secret: '', api_key: '' },
        extra: [
            { key: 'url', label: 'Zapier webhook URL', placeholder: 'https://hooks.zapier.com/hooks/catch/...', type: 'text' },
        ],
        help: 'Optional automation: trigger Zapier flows (Gmail, Sheets, etc.) from system events. Store only the webhook URL.'
    },
    openai: {
        label: 'OpenAI (AI Key)',
        fields: { client_id: false, client_secret: false, api_key: true },
        labels: { client_id: 'Client ID', client_secret: 'Client Secret', api_key: 'API Key' },
        hints: {
            client_id: '',
            client_secret: '',
            api_key: 'Paste the API key.',
        },
        extra: [
            { key: 'model', label: 'Default model', placeholder: 'gpt-4.1-mini', type: 'text' },
            { key: 'base_url', label: 'Base URL (optional)', placeholder: 'https://api.openai.com', type: 'text' },
        ],
        help: 'Used for AI analytics/features. Keep disabled if not in use.'
    },
    gemini: {
        label: 'Google Gemini (AI Key)',
        fields: { client_id: false, client_secret: false, api_key: true },
        labels: { client_id: 'Client ID', client_secret: 'Client Secret', api_key: 'API Key' },
        hints: { api_key: 'Paste the Gemini API key.' },
        extra: [
            { key: 'model', label: 'Default model', placeholder: 'gemini-1.5-flash', type: 'text' },
        ],
        help: 'Used for teacher AI tools (draft tests/exams/notes).'
    },
};

function credServiceLabel(service_name) {
    return (CRED_SERVICE_INFO[service_name] && CRED_SERVICE_INFO[service_name].label) ? CRED_SERVICE_INFO[service_name].label : String(service_name || '');
}

function credPick(service_name, btn) {
    document.querySelectorAll('#cred-seg .seg-btn').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
    const sel = document.getElementById('cred-service');
    if (sel) sel.value = service_name;
    credOnServiceChange();
}

function credToggleSecrets() {
    const show = !!document.getElementById('cred-show')?.checked;
    ['cred-client-secret', 'cred-api-key'].forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        el.type = show ? 'text' : 'password';
    });
}

function credRenderExtraFields(service_name, extra_data = {}) {
    const el = document.getElementById('cred-extra-fields');
    if (!el) return;
    const info = CRED_SERVICE_INFO[service_name] || null;
    const fields = (info && info.extra) ? info.extra : [];
    if (!fields.length) {
        el.innerHTML = `<div class="sub">No extra fields for this service.</div>`;
        return;
    }
    el.innerHTML = fields.map(f => {
        const v = (extra_data && Object.prototype.hasOwnProperty.call(extra_data, f.key)) ? (extra_data[f.key] ?? '') : '';
        const safe = String(v).replace(/\"/g, '&quot;');
        const t = f.type || 'text';
        const ph = (f.placeholder || '').toString().replace(/\"/g, '&quot;');
        return `
          <div class="field" style="margin:0 0 10px 0">
            <label>${f.label}</label>
            <input class="field-input mono cred-extra-kv" data-key="${f.key}" type="${t}" value="${safe}" placeholder="${ph}">
          </div>`;
    }).join('');
}

function credCollectExtraData() {
    const out = {};
    document.querySelectorAll('.cred-extra-kv').forEach(inp => {
        const key = inp.getAttribute('data-key');
        if (!key) return;
        const v = (inp.value || '').toString().trim();
        if (v === '') return;
        out[key] = v;
    });

    const raw = (document.getElementById('cred-extra-raw')?.value || '').trim();
    if (!raw) return out;

    let parsed = null;
    try { parsed = JSON.parse(raw); } catch { throw new Error('Advanced JSON must be valid JSON.'); }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('Advanced JSON must be an object (e.g. {\"key\":\"value\"}).');
    }
    return { ...out, ...parsed };
}

function credOnServiceChange(extra_data = null) {
    const service_name = document.getElementById('cred-service')?.value;
    const info = CRED_SERVICE_INFO[service_name] || { fields: { client_id: true, client_secret: true, api_key: true }, labels: {}, hints: {}, help: '' };

    const setWrap = (id, show) => { const w = document.getElementById(id); if (w) w.style.display = show ? '' : 'none'; };
    setWrap('cred-client-id-wrap', !!info.fields.client_id);
    setWrap('cred-client-secret-wrap', !!info.fields.client_secret);
    setWrap('cred-api-key-wrap', !!info.fields.api_key);

    const setText = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v || ''; };
    setText('cred-client-id-label', info.labels.client_id || 'Client ID');
    setText('cred-client-secret-label', info.labels.client_secret || 'Client Secret');
    setText('cred-api-key-label', info.labels.api_key || 'API Key');
    setText('cred-client-id-hint', info.hints.client_id || '');
    setText('cred-client-secret-hint', info.hints.client_secret || '');
    setText('cred-api-key-hint', info.hints.api_key || '');
    setText('cred-help', info.help || '');

    document.querySelectorAll('#cred-seg .seg-btn').forEach(b => {
        b.classList.toggle('active', (b.getAttribute('data-svc') || '') === service_name);
    });

    credRenderExtraFields(service_name, extra_data || {});
    credToggleSecrets();
}

function clearCredentialForm() {
    const ids = ['cred-id', 'cred-client-id', 'cred-client-secret', 'cred-api-key', 'cred-extra-raw'];
    ids.forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    const active = document.getElementById('cred-active'); if (active) active.checked = true;
    const show = document.getElementById('cred-show'); if (show) show.checked = false;
    try { credOnServiceChange({}); } catch {}
}

async function saveCredential() {
    const id = document.getElementById('cred-id').value;
    const service_name = document.getElementById('cred-service').value;
    const client_id = document.getElementById('cred-client-id').value.trim();
    const client_secret = document.getElementById('cred-client-secret').value.trim();
    const api_key = document.getElementById('cred-api-key').value.trim();
    const is_active = document.getElementById('cred-active').checked;
    let extra_data = {};
    try { extra_data = credCollectExtraData(); } catch (e) { flash(e && e.message ? e.message : 'Extra data invalid.'); return; }

    const payload = { service_name, client_id, client_secret, api_key, extra_data, is_active };
    if (id) await API.fetch(`/api-credentials/${id}/`, { method: 'PATCH', body: JSON.stringify(payload) });
    else await API.fetch('/api-credentials/', { method: 'POST', body: JSON.stringify(payload) });

    flash('Credential saved.');
    loadPage('credentials');
}

async function toggleCredentialActive(id, is_active) {
    await API.fetch(`/api-credentials/${id}/`, { method: 'PATCH', body: JSON.stringify({ is_active }) });
    flash(is_active ? 'Enabled.' : 'Disabled.');
    loadPage('credentials');
}

async function prefillCredential(id) {
    const c = await API.fetch(`/api-credentials/${id}/`);
    document.getElementById('cred-id').value = c.id;
    document.getElementById('cred-service').value = c.service_name;
    credOnServiceChange(c.extra_data || {});
    document.getElementById('cred-client-id').value = c.client_id || '';
    document.getElementById('cred-client-secret').value = c.client_secret || '';
    document.getElementById('cred-api-key').value = c.api_key || '';
    const raw = document.getElementById('cred-extra-raw');
    if (raw) raw.value = '';
    document.getElementById('cred-active').checked = !!c.is_active;
    flash('Loaded into form.');
}

async function deleteCredential(id) {
    await API.fetch(`/api-credentials/${id}/`, { method: 'DELETE' });
    flash('Deleted.');
    loadPage('credentials');
}

async function verifyCredential(id) {
    try {
        const res = await API.fetch(`/api-credentials/${id}/verify/`, { method: 'POST', body: JSON.stringify({}) });
        flash(res && res.ok ? `Verified: ${res.detail}` : `Verify failed: ${(res && res.detail) || 'Unknown error'}`);
        // Refresh so the "last verified" status is visible immediately.
        try { loadPage('credentials'); } catch {}
    } catch (e) {
        flash(`Verify failed: ${(e && e.detail) ? e.detail : 'Request failed'}`);
    }
}

async function verifyCredentialFromForm() {
    const id = document.getElementById('cred-id')?.value;
    if (!id) { flash('Save the credential first, then verify.'); return; }
    await verifyCredential(id);
}

async function sendTestCredentialFromForm() {
    const id = document.getElementById('cred-id')?.value;
    if (!id) { flash('Save the credential first, then test.'); return; }
    const svc = document.getElementById('cred-service')?.value || '';
    let payload = {};

    if (svc === 'gmail_smtp' || svc === 'email_smtp') {
        const to_email = (prompt('Test email: send to which email address?') || '').trim();
        if (!to_email) return;
        payload = { to_email };
    } else if (svc === 'megasms' || svc === 'twilio_sms') {
        const to_number = (prompt('Test SMS: send to which phone number? (e.g. +2567...)') || '').trim();
        if (!to_number) return;
        const message = (prompt('Message (optional):', 'Test SMS from School Management System.') || '').trim();
        payload = { to_number, message };
    } else if (svc === 'zapier_webhook') {
        payload = { payload: { event: 'test', source: 'bjs', at: new Date().toISOString() } };
    } else {
        flash('No test action for this service.');
        return;
    }

    try {
        const res = await API.fetch(`/api-credentials/${id}/send-test/`, { method: 'POST', body: JSON.stringify(payload) });
        flash(res && res.detail ? res.detail : 'Test sent.');
        try { loadPage('credentials'); } catch {}
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Test failed.');
    }
}

async function savePayment() {
    const student = document.getElementById('pay-stu').value;
    const amount = document.getElementById('pay-amt').value;
    const academic_year = parseInt(document.getElementById('pay-year')?.value || '', 10) || null;
    const term_number = parseInt(document.getElementById('pay-term')?.value || '', 10) || null;
    const method = document.getElementById('pay-method').value;
    const reference = document.getElementById('pay-ref').value.trim();
    const notes = document.getElementById('pay-notes').value.trim();
    if (!student || !amount) { flash('Select student and amount.'); return; }
    await API.fetch('/payments/', { method: 'POST', body: JSON.stringify({ student, amount, academic_year, term_number, method, reference, notes }) });
    flash('Payment recorded.');
    loadPage('finance');
}

async function terminateSession(session_key) {
    try {
        await API.fetch('/security/terminate-session/', { method: 'POST', body: JSON.stringify({ session_key }) });
        flash('Session terminated.');
        loadPage('security');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to terminate session.');
    }
}

async function terminateUserSessions(user_id) {
    try {
        await API.fetch('/security/terminate-user-sessions/', { method: 'POST', body: JSON.stringify({ user_id }) });
        flash('User sessions terminated.');
        loadPage('security');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to terminate user sessions.');
    }
}

async function disableUser(user_id) {
    try {
        await API.fetch('/security/disable-user/', { method: 'POST', body: JSON.stringify({ user_id }) });
        flash('User disabled.');
        loadPage('security');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to disable user.');
    }
}

async function searchPayments() {
    const role = (currentUser.profile && currentUser.profile.role) || 'admin';
    const canReverse = ['superadmin', 'bursar'].includes(role);
    const q = document.getElementById('pay-q').value.trim();
    const method = (document.getElementById('pay-f-method')?.value || '').trim();
    const status = (document.getElementById('pay-f-status')?.value || '').trim();
    const class_id = (document.getElementById('pay-f-class')?.value || '').trim();
    const date_from = (document.getElementById('pay-f-from')?.value || '').trim();
    const date_to = (document.getElementById('pay-f-to')?.value || '').trim();

    const qs = new URLSearchParams();
    if (q) qs.set('q', q);
    if (method) qs.set('method', method);
    if (status) qs.set('status', status);
    if (class_id) qs.set('class_id', class_id);
    if (date_from) qs.set('date_from', date_from);
    if (date_to) qs.set('date_to', date_to);

    const payments = await API.fetch(`/payments/?${qs.toString()}`);
    const body = document.getElementById('pay-body');
    if (!body) return;
    body.innerHTML = (payments || []).slice(0, 60).map(p => `
      <tr>
        <td>${formatDateTime(p.received_at)}</td>
        <td><strong>${p.student_name}</strong><div class="sub">${p.student_system_id}</div></td>
        <td style="font-weight:800;color:var(--m)">UGX ${fmt(p.amount)}</td>
        <td>${p.method}</td>
        <td style="font-size:12px;color:var(--66)">${p.reference || '-'}</td>
        <td>${p.received_by_username || '-'}</td>
        <td>${p.status}</td>
        <td>
          <button class="btn btn-xs btn-ghost" onclick="openPaymentEdit(${p.id})">Edit</button>
          ${(canReverse && p.status !== 'reversed') ? `<button class="btn btn-xs btn-ghost" onclick="reversePayment(${p.id})">Reverse</button>` : ''}
          <button class="btn btn-xs btn-ghost" onclick="openStudentHistory(${p.student})">Student</button>
        </td>
      </tr>
    `).join('');
}

function openStudentHistoryFromPaymentSelect() {
    const sid = document.getElementById('pay-stu')?.value;
    if (!sid) { flash('Select a student first.'); return; }
    openStudentHistory(parseInt(sid, 10));
}

async function openPaymentEdit(id) {
    const p = await API.fetch(`/payments/${id}/`);
    const role = (currentUser.profile && currentUser.profile.role) || 'admin';
    const canReverse = ['superadmin', 'bursar'].includes(role);
    const submittedBankSlip = String(p.method || '').toLowerCase() === 'bank' && !!(p.receipt_image_url || p.submitted_by || p.submitted_by_username);
    document.getElementById('p-id').value = p.id;
    document.getElementById('p-amt').value = p.amount;
    document.getElementById('p-method').value = p.method || 'cash';
    document.getElementById('p-ref').value = p.reference || '';
    document.getElementById('p-notes').value = p.notes || '';
    document.getElementById('p-method').disabled = submittedBankSlip;
    const lockNote = document.getElementById('p-lock-note');
    if (lockNote) {
        lockNote.style.display = submittedBankSlip ? 'block' : 'none';
        lockNote.textContent = submittedBankSlip
            ? 'Submitted bank-slip payments keep their payment method locked. Use the approval screen to approve or reject them.'
            : '';
    }
    const reverseBtn = document.getElementById('p-reverse-btn');
    if (reverseBtn) reverseBtn.style.display = (canReverse && p.status !== 'reversed') ? '' : 'none';
    openModal('modal-payment');
}

async function savePaymentEdit() {
    const id = document.getElementById('p-id').value;
    const amount = document.getElementById('p-amt').value;
    const method = document.getElementById('p-method').value;
    const reference = document.getElementById('p-ref').value.trim();
    const notes = document.getElementById('p-notes').value.trim();
    await API.fetch(`/payments/${id}/`, { method: 'PATCH', body: JSON.stringify({ amount, method, reference, notes }) });
    flash('Payment updated.');
    closeModal('modal-payment');
    loadPage('finance');
}

async function reversePayment(id) {
    await API.fetch(`/payments/${id}/reverse/`, { method: 'POST', body: JSON.stringify({}) });
    flash('Payment reversed.');
    loadPage('finance');
}

async function reversePaymentFromModal() {
    const id = document.getElementById('p-id').value;
    if (!id) return;
    await reversePayment(id);
    closeModal('modal-payment');
}

function viewImage(url, title = 'Image') {
    const img = document.getElementById('img-view');
    const ttl = document.getElementById('img-ttl');
    if (ttl) ttl.textContent = title;
    if (img) img.src = url || '';
    openModal('modal-image');
}

async function approvePayment(id) {
    // Keep for legacy buttons; prefer openApprovalModal().
    await API.fetch(`/payments/${id}/approve/`, { method: 'POST', body: JSON.stringify({ review_notes: '' }) });
    flash('Payment approved.');
    loadPage(CURRENT_PAGE === 'approvals' ? 'approvals' : 'finance');
}

async function rejectPayment(id) {
    // Keep for legacy buttons; prefer openApprovalModal().
    await API.fetch(`/payments/${id}/reject/`, { method: 'POST', body: JSON.stringify({ reason: '', review_notes: '' }) });
    flash('Payment rejected.');
    loadPage(CURRENT_PAGE === 'approvals' ? 'approvals' : 'finance');
}

let ACTIVE_APPROVAL = null;
async function openApprovalModal(paymentId) {
    if (!paymentId) return;
    try {
        const p = await API.fetch(`/payments/${paymentId}/`);
        ACTIVE_APPROVAL = p || null;
        document.getElementById('appr-id').value = String(paymentId);
        document.getElementById('appr-ref').value = (p && p.reference) ? String(p.reference) : '';
        document.getElementById('appr-reason').value = '';
        document.getElementById('appr-notes').value = (p && p.review_notes) ? String(p.review_notes) : '';

        const meta = document.getElementById('appr-meta');
        const termLbl = (p && p.academic_year && p.term_number) ? `T${p.term_number}/${p.academic_year}` : '-';
        const who = (p && p.submitted_by_username) ? p.submitted_by_username : '-';
        if (meta) meta.innerHTML = `
          <div><strong>${escapeHtml(p.student_system_id || '')}</strong> ${escapeHtml(p.student_name || '')}</div>
          <div class="sub">Amount: UGX ${fmt(Number(p.amount || 0).toFixed(0))} · Method: ${escapeHtml(p.method || '')} · Status: ${escapeHtml(p.status || '')}</div>
          <div class="sub">Term: ${termLbl} · Submitted by: ${escapeHtml(who)}</div>
        `;

        const slip = document.getElementById('appr-slip');
        if (slip) slip.src = (p && p.receipt_image_url) ? String(p.receipt_image_url) : '';

        openModal('modal-approval');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to load payment.');
    }
}

function openApprovalSlipFull() {
    try {
        const url = (ACTIVE_APPROVAL && ACTIVE_APPROVAL.receipt_image_url) ? ACTIVE_APPROVAL.receipt_image_url : '';
        if (!url) { flash('No slip image.'); return; }
        viewImage(String(url), 'Bank Slip');
    } catch {}
}

async function approveFromModal() {
    const id = (document.getElementById('appr-id')?.value || '').trim();
    const ref = (document.getElementById('appr-ref')?.value || '').trim();
    const review_notes = (document.getElementById('appr-notes')?.value || '').trim();
    if (!id) return;
    try {
        // Update reference if edited.
        if (ref !== ((ACTIVE_APPROVAL && ACTIVE_APPROVAL.reference) ? String(ACTIVE_APPROVAL.reference) : '')) {
            await API.fetch(`/payments/${id}/`, { method: 'PATCH', body: JSON.stringify({ reference: ref || null }) });
        }
        await API.fetch(`/payments/${id}/approve/`, { method: 'POST', body: JSON.stringify({ review_notes }) });
        flash('Payment approved.');
        closeModal('modal-approval');
        loadPage('approvals', null, 'Approvals');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to approve.');
    }
}

async function rejectFromModal() {
    const id = (document.getElementById('appr-id')?.value || '').trim();
    const ref = (document.getElementById('appr-ref')?.value || '').trim();
    const reason = (document.getElementById('appr-reason')?.value || '').trim();
    const review_notes = (document.getElementById('appr-notes')?.value || '').trim();
    if (!id) return;
    try {
        if (ref !== ((ACTIVE_APPROVAL && ACTIVE_APPROVAL.reference) ? String(ACTIVE_APPROVAL.reference) : '')) {
            await API.fetch(`/payments/${id}/`, { method: 'PATCH', body: JSON.stringify({ reference: ref || null }) });
        }
        await API.fetch(`/payments/${id}/reject/`, { method: 'POST', body: JSON.stringify({ reason, review_notes }) });
        flash('Payment rejected.');
        closeModal('modal-approval');
        loadPage('approvals', null, 'Approvals');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to reject.');
    }
}

// ----- Documents (AI drafts / Print Desk) -----
async function openDocModalFromId(id) {
    const d = await API.fetch(`/document-drafts/${id}/`);
    const ttl = document.getElementById('doc-ttl');
    const meta = document.getElementById('doc-meta');
    const body = document.getElementById('doc-body');
    const rendered = document.getElementById('doc-rendered');
    if (ttl) ttl.textContent = d.title || 'Document';
    if (meta) meta.textContent = `${d.kind || ''} · ${d.status || ''} · ${d.school_class_level || '-'} · ${d.subject_name || '-'}`;
    if (body) body.value = d.body || '';
    if (rendered) {
        const cleanHtml = sanitizeCommunicationHtmlClient(d.body || '');
        rendered.innerHTML = cleanHtml || `<pre style="white-space:pre-wrap;margin:0">${escapeHtml(d.body || '')}</pre>`;
    }
    openModal('modal-doc');
}

function printDocModal() {
    const ttl = document.getElementById('doc-ttl')?.textContent || 'Document';
    const meta = document.getElementById('doc-meta')?.textContent || '';
    const body = document.getElementById('doc-body')?.value || '';
    const rendered = document.getElementById('doc-rendered')?.innerHTML || '';
    const w = window.open('', '_blank');
    if (!w) { flash('Popup blocked. Allow popups to print.'); return; }
    const printableBody = rendered || `<pre style="white-space:pre-wrap;font-size:13px;line-height:1.45">${escapeHtml(body)}</pre>`;
    w.document.write(`<html><head><title>${escapeHtml(ttl)}</title><style>body{font-family:Arial,sans-serif;padding:24px;color:#1f2937}h1,h2,h3{margin:0 0 10px 0}p,li,td,th{font-size:13px;line-height:1.55}table{width:100%;border-collapse:collapse;margin:12px 0}th,td{border:1px solid #d1d5db;padding:8px;text-align:left}blockquote{border-left:4px solid #991b1b;padding-left:12px;color:#4b5563;margin:12px 0}hr{border:none;border-top:1px solid #d1d5db;margin:16px 0}</style></head><body><h2>${escapeHtml(ttl)}</h2><div style="color:#666;font-size:12px;margin-bottom:12px">${escapeHtml(meta)}</div>${printableBody}</body></html>`);
    w.document.close();
    w.focus();
    w.print();
}

async function submitDraft(id) {
    await API.fetch(`/document-drafts/${id}/submit/`, { method: 'POST', body: JSON.stringify({}) });
    flash('Submitted to Reception for printing.');
    loadPage('ai_tools');
}

async function markDocPrinted(id) { 
    await API.fetch(`/document-drafts/${id}/mark-printed/`, { method: 'POST', body: JSON.stringify({}) }); 
    flash('Marked printed.'); 
    loadPage('printdesk'); 
} 

function launchCommunicationEditor(options = {}) {
    COMMUNICATION_EDITOR_BOOT = options || {};
    loadPage('communications_editor', null, 'Communication Editor');
}

function currentCommunicationEditorDocId() {
    const raw = (document.getElementById('cm-id')?.value || '').trim();
    return raw ? Number(raw) : null;
}

function refreshCommunicationWorkspace(docId = null) {
    if (CURRENT_PAGE === 'communications') {
        loadPage('communications', null, 'Communications');
        return;
    }
    if (CURRENT_PAGE === 'communications_editor') {
        if (docId) launchCommunicationEditor({ id: Number(docId) });
        else launchCommunicationEditor({});
    }
}

function syncCommunicationMetaPanel(doc = null) {
    const normalized = doc || {};
    const workflow = String(normalized.workflow_status || 'draft').toLowerCase();
    const scope = String(normalized.library_scope || document.getElementById('cm-library-scope')?.value || communicationDefaultLibraryScope()).toLowerCase();
    const statusChip = document.getElementById('cm-status-chip');
    const statusEl = document.getElementById('cm-meta-status');
    const versionEl = document.getElementById('cm-meta-version');
    const libraryEl = document.getElementById('cm-meta-library');
    const updatedEl = document.getElementById('cm-meta-updated');
    if (statusChip) statusChip.innerHTML = communicationWorkflowPill(workflow);
    if (statusEl) statusEl.textContent = workflow.charAt(0).toUpperCase() + workflow.slice(1);
    if (versionEl) versionEl.textContent = `v${Number(normalized.version_number || 1)}`;
    if (libraryEl) {
        const scopeDef = COMMUNICATION_LIBRARY_SCOPES.find(x => x.value === scope);
        libraryEl.textContent = scopeDef ? scopeDef.label : scope;
    }
    if (updatedEl) updatedEl.textContent = normalized.updated_at ? formatDateTime(normalized.updated_at) : 'New draft';
}

function loadCommunicationStarter(key) {
    const starter = COMMUNICATION_STARTER_TEMPLATES.find(item => item.key === key);
    if (!starter) return;
    clearCommunicationForm();
    const assignments = {
        'cm-kind': starter.kind || 'letter',
        'cm-title': starter.title || '',
        'cm-library-scope': starter.library_scope || communicationDefaultLibraryScope(),
        'cm-header': starter.header_preset || 'standard',
        'cm-footer': starter.footer_preset || 'standard',
        'cm-workflow-notes': `Starter template: ${starter.label}`,
    };
    Object.entries(assignments).forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
    });
    const signature = document.getElementById('cm-signature');
    const stamp = document.getElementById('cm-stamp');
    if (signature) signature.checked = !!starter.include_signature_block;
    if (stamp) stamp.checked = !!starter.include_school_stamp;
    setCommunicationEditorContent(starter.body || COMMUNICATION_DEFAULT_TEMPLATE);
    syncCommunicationMetaPanel(null);
    flash(`${starter.label} starter loaded.`);
}

function clearCommunicationForm(options = {}) {
    const preserveEditor = !!options.preserveEditor;
    const ids = ['cm-id', 'cm-title', 'cm-workflow-notes', 'cm-campaign-notes'];
    ids.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    const kind = document.getElementById('cm-kind');
    const schoolClass = document.getElementById('cm-class');
    const student = document.getElementById('cm-student');
    const audience = document.getElementById('cm-audience');
    const libraryScope = document.getElementById('cm-library-scope');
    const header = document.getElementById('cm-header');
    const footer = document.getElementById('cm-footer');
    const signature = document.getElementById('cm-signature');
    const stamp = document.getElementById('cm-stamp');
    const schedule = document.getElementById('cm-schedule-at');
    const channel = document.getElementById('cm-campaign-channel');
    const retryLimit = document.getElementById('cm-retry-limit');
    const retryDelay = document.getElementById('cm-retry-delay');
    if (kind) kind.value = 'letter';
    if (schoolClass) schoolClass.value = '';
    if (student) student.value = '';
    if (audience) audience.value = 'guardians';
    if (libraryScope) libraryScope.innerHTML = communicationLibraryOptionsHtml(currentRoleName(), communicationDefaultLibraryScope());
    if (header) header.value = 'standard';
    if (footer) footer.value = 'standard';
    if (signature) signature.checked = true;
    if (stamp) stamp.checked = true;
    if (schedule) schedule.value = '';
    if (channel) channel.value = 'email';
    if (retryLimit) retryLimit.value = '2';
    if (retryDelay) retryDelay.value = '30';
    if (!preserveEditor) setCommunicationEditorContent(COMMUNICATION_DEFAULT_TEMPLATE);
    syncCommunicationMetaPanel(null);
}

async function openCommunicationEdit(id) {
    const d = await API.fetch(`/document-drafts/${id}/`);
    const fields = {
        'cm-id': d.id,
        'cm-kind': d.kind || 'letter',
        'cm-title': d.title || '',
        'cm-class': d.school_class || '',
        'cm-library-scope': d.library_scope || communicationDefaultLibraryScope(),
        'cm-header': d.header_preset || 'standard',
        'cm-footer': d.footer_preset || 'standard',
        'cm-workflow-notes': d.workflow_notes || '',
    };
    Object.entries(fields).forEach(([fieldId, value]) => {
        const el = document.getElementById(fieldId);
        if (el) el.value = value;
    });
    const student = document.getElementById('cm-student');
    if (student) student.value = '';
    const audience = document.getElementById('cm-audience');
    if (audience) audience.value = 'guardians';
    const signature = document.getElementById('cm-signature');
    const stamp = document.getElementById('cm-stamp');
    if (signature) signature.checked = d.include_signature_block !== false;
    if (stamp) stamp.checked = d.include_school_stamp !== false;
    setCommunicationEditorContent(d.body || COMMUNICATION_DEFAULT_TEMPLATE);
    syncCommunicationMetaPanel(d);
    flash('Template loaded into the editor.');
}

function collectCommunicationPayload() {
    const kind = (document.getElementById('cm-kind')?.value || 'letter').trim();
    const title = (document.getElementById('cm-title')?.value || '').trim();
    const body = (syncCommunicationBodyInput() || '').trim();
    const school_class = (document.getElementById('cm-class')?.value || '').trim() || null;
    const library_scope = (document.getElementById('cm-library-scope')?.value || communicationDefaultLibraryScope()).trim();
    const header_preset = (document.getElementById('cm-header')?.value || 'standard').trim();
    const footer_preset = (document.getElementById('cm-footer')?.value || 'standard').trim();
    const include_signature_block = !!document.getElementById('cm-signature')?.checked;
    const include_school_stamp = !!document.getElementById('cm-stamp')?.checked;
    const workflow_notes = (document.getElementById('cm-workflow-notes')?.value || '').trim();
    if (!title || !body) {
        throw new Error('Title and body are required.');
    }
    return {
        kind,
        title,
        body,
        school_class,
        library_scope,
        header_preset,
        footer_preset,
        include_signature_block,
        include_school_stamp,
        workflow_notes,
    };
}

async function saveCommunicationTemplate(options = {}) {
    const quiet = !!options.quiet;
    const stayOnPage = !!options.stayOnPage;
    let payload = null;
    try {
        payload = collectCommunicationPayload();
    } catch (e) {
        if (!quiet) flash(e.message || 'Template is incomplete.');
        throw e;
    }
    const id = (document.getElementById('cm-id')?.value || '').trim();
    let res = null;
    if (id) res = await API.fetch(`/document-drafts/${id}/`, { method: 'PATCH', body: JSON.stringify(payload) });
    else res = await API.fetch('/document-drafts/', { method: 'POST', body: JSON.stringify(payload) });
    const idEl = document.getElementById('cm-id');
    if (idEl) idEl.value = res.id;
    syncCommunicationMetaPanel(res);
    if (!quiet) flash(id ? 'Template updated.' : 'Template saved.');
    if (!stayOnPage && CURRENT_PAGE === 'communications') loadPage('communications', null, 'Communications');
    return res;
}

function collectCommunicationTargeting() {
    return {
        school_class: (document.getElementById('cm-class')?.value || '').trim() || null,
        student: (document.getElementById('cm-student')?.value || '').trim() || null,
        audience: (document.getElementById('cm-audience')?.value || 'guardians').trim() || 'guardians',
    };
}

async function ensureCommunicationTemplateId() {
    const existing = (document.getElementById('cm-id')?.value || '').trim();
    if (existing) return existing;
    const res = await saveCommunicationTemplate({ quiet: true, stayOnPage: true });
    return String(res.id);
}

async function previewCommunicationMerge(id = null) {
    try {
        if (id) await openCommunicationEdit(id);
        const docId = id || await ensureCommunicationTemplateId();
        const res = await API.fetch(`/document-drafts/${docId}/preview-merge/`, { method: 'POST', body: JSON.stringify(collectCommunicationTargeting()) });
        const ttl = document.getElementById('doc-ttl');
        const meta = document.getElementById('doc-meta');
        const body = document.getElementById('doc-body');
        const rendered = document.getElementById('doc-rendered');
        if (ttl) ttl.textContent = res.preview.title || 'Preview';
        if (meta) meta.textContent = `${res.audience || 'guardians'} · ${res.count || 0} recipient(s) · ${res.preview.class_label || '-'}`;
        if (body) body.value = res.preview.body_text || res.preview.body || '';
        if (rendered) {
            const cleanHtml = sanitizeCommunicationHtmlClient(res.preview.body_html || res.preview.body || '');
            rendered.innerHTML = cleanHtml || `<pre style="white-space:pre-wrap;margin:0">${escapeHtml(res.preview.body_text || res.preview.body || '')}</pre>`;
        }
        openModal('modal-doc');
    } catch (e) {
        flash((e && e.detail) ? e.detail : ((e && e.message) ? e.message : 'Preview failed.'));
    }
}

async function queueCommunicationMerge() {
    try {
        const docId = await ensureCommunicationTemplateId();
        const res = await API.fetch(`/document-drafts/${docId}/queue-merge/`, { method: 'POST', body: JSON.stringify(collectCommunicationTargeting()) });
        flash(`Queued ${res.count || 0} personalized letter(s).`);
        refreshCommunicationWorkspace(Number(docId));
    } catch (e) {
        flash((e && e.detail) ? e.detail : ((e && e.message) ? e.message : 'Queue failed.'));
    }
}

async function sendCommunicationMerge(channel) {
    try {
        const docId = await ensureCommunicationTemplateId();
        const payload = collectCommunicationTargeting();
        payload.channel = channel;
        const res = await API.fetch(`/document-drafts/${docId}/send-merge/`, { method: 'POST', body: JSON.stringify(payload) });
        flash(`${channel.toUpperCase()} sent: ${res.sent || 0}, skipped: ${res.skipped || 0}, failed: ${(res.failed || []).length}.`);
    } catch (e) {
        flash((e && e.detail) ? e.detail : ((e && e.message) ? e.message : 'Send failed.'));
    }
}

async function approveCommunicationTemplate() {
    try {
        const docId = await ensureCommunicationTemplateId();
        const workflow_notes = (document.getElementById('cm-workflow-notes')?.value || '').trim();
        await API.fetch(`/document-drafts/${docId}/approve/`, { method: 'POST', body: JSON.stringify({ workflow_notes }) });
        flash('Template approved.');
        refreshCommunicationWorkspace(Number(docId));
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Approval failed.');
    }
}

async function publishCommunicationTemplate(force = false) {
    try {
        const docId = await ensureCommunicationTemplateId();
        await API.fetch(`/document-drafts/${docId}/publish/`, { method: 'POST', body: JSON.stringify({ force: !!force }) });
        flash('Template published.');
        refreshCommunicationWorkspace(Number(docId));
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Publish failed.');
    }
}

async function cloneCommunicationVersion() {
    try {
        const docId = await ensureCommunicationTemplateId();
        const res = await API.fetch(`/document-drafts/${docId}/new-version/`, { method: 'POST', body: JSON.stringify({}) });
        flash('New template version created.');
        refreshCommunicationWorkspace(Number(res.id));
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Versioning failed.');
    }
}

async function scheduleCommunicationCampaign() {
    try {
        const docId = await ensureCommunicationTemplateId();
        const payload = collectCommunicationTargeting();
        payload.channel = (document.getElementById('cm-campaign-channel')?.value || 'email').trim();
        payload.scheduled_for = (document.getElementById('cm-schedule-at')?.value || '').trim();
        payload.retry_limit = Number(document.getElementById('cm-retry-limit')?.value || 2);
        payload.retry_delay_minutes = Number(document.getElementById('cm-retry-delay')?.value || 30);
        payload.notes = (document.getElementById('cm-campaign-notes')?.value || '').trim();
        if (!payload.scheduled_for) throw new Error('Choose a schedule date and time first.');
        await API.fetch(`/document-drafts/${docId}/schedule-campaign/`, { method: 'POST', body: JSON.stringify(payload) });
        flash('Campaign scheduled.');
        refreshCommunicationWorkspace(Number(docId));
    } catch (e) {
        flash((e && e.detail) ? e.detail : ((e && e.message) ? e.message : 'Scheduling failed.'));
    }
}

async function runDueCommunicationCampaigns() {
    try {
        const res = await API.fetch('/communication-campaigns/run-due/', { method: 'POST', body: JSON.stringify({}) });
        flash(`Ran ${Number(res.ran || 0)} due campaign(s).`);
        refreshCommunicationWorkspace(currentCommunicationEditorDocId());
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to run due campaigns.');
    }
}

async function runCommunicationCampaign(id) {
    try {
        await API.fetch(`/communication-campaigns/${id}/run-now/`, { method: 'POST', body: JSON.stringify({}) });
        flash('Campaign executed.');
        refreshCommunicationWorkspace(currentCommunicationEditorDocId());
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Campaign run failed.');
    }
}

async function cancelCommunicationCampaign(id) {
    try {
        await API.fetch(`/communication-campaigns/${id}/cancel/`, { method: 'POST', body: JSON.stringify({}) });
        flash('Campaign cancelled.');
        refreshCommunicationWorkspace(currentCommunicationEditorDocId());
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Cancel failed.');
    }
}

async function openCommunicationCampaignReport(id) {
    try {
        const res = await API.fetch(`/communication-campaigns/${id}/delivery-report/`);
        const ttl = document.getElementById('doc-ttl');
        const meta = document.getElementById('doc-meta');
        const body = document.getElementById('doc-body');
        const rendered = document.getElementById('doc-rendered');
        const totals = res.totals || {};
        if (ttl) ttl.textContent = `${res.campaign?.document_title || 'Campaign'} delivery report`;
        if (meta) meta.textContent = `${(res.campaign?.channel || 'email').toUpperCase()} · ${formatDateTime(res.campaign?.scheduled_for)} · opened ${Number(totals.opened || 0)} · confirmed ${Number(totals.confirmed || 0)}`;
        if (body) body.value = JSON.stringify(totals, null, 2);
        if (rendered) {
            rendered.innerHTML = `
              <div class="kv-grid" style="margin-bottom:14px">
                <div class="kv-item"><div class="k">Total</div><div class="v" style="font-weight:900">${Number(totals.total || 0)}</div></div>
                <div class="kv-item"><div class="k">Sent</div><div class="v" style="font-weight:900">${Number(totals.sent || 0)}</div></div>
                <div class="kv-item"><div class="k">Failed</div><div class="v" style="font-weight:900">${Number(totals.failed || 0)}</div></div>
                <div class="kv-item"><div class="k">Retry pending</div><div class="v" style="font-weight:900">${Number(totals.retry_pending || 0)}</div></div>
                <div class="kv-item"><div class="k">Opened</div><div class="v" style="font-weight:900">${Number(totals.opened || 0)}</div></div>
                <div class="kv-item"><div class="k">Confirmed</div><div class="v" style="font-weight:900">${Number(totals.confirmed || 0)}</div></div>
              </div>
              <div class="tw">
                <table class="tbl">
                  <thead><tr><th>Recipient</th><th>Channel</th><th>Status</th><th>Attempts</th><th>Last update</th></tr></thead>
                  <tbody>
                    ${(res.deliveries || []).map(d => `<tr>
                      <td><strong>${escapeHtml(d.recipient_name || d.student_name || '-')}</strong><div class="sub">${escapeHtml(d.recipient_email || d.recipient_phone || '-')}</div></td>
                      <td>${escapeHtml((d.channel || '').toUpperCase())}</td>
                      <td>${communicationCampaignPill(d.status)}</td>
                      <td>${Number(d.attempt_count || 0)}</td>
                      <td>${formatDateTime(d.updated_at)}</td>
                    </tr>`).join('') || '<tr><td colspan="5" style="color:var(--99)">No deliveries yet.</td></tr>'}
                  </tbody>
                </table>
              </div>`;
        }
        openModal('modal-doc');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to open campaign report.');
    }
}
 
// ----- Print Queue ----- 
function pqOpenPdf(id) { 
    if (!id) return; 
    window.open(`/api/print-queue/${id}/pdf/`, '_blank', 'noopener'); 
} 
 
async function pqMarkPrinted(id) { 
    if (!id) return; 
    try { 
        await API.fetch(`/print-queue/${id}/mark-printed/`, { method: 'POST', body: JSON.stringify({}) }); 
        flash('Marked printed (sensitive items are wiped).'); 
        loadPage('printqueue'); 
    } catch (e) { 
        flash((e && e.detail) ? e.detail : 'Failed to mark printed.'); 
    } 
} 
 
async function pqCancel(id) { 
    if (!id) return; 
    try { 
        await API.fetch(`/print-queue/${id}/cancel/`, { method: 'POST', body: JSON.stringify({}) }); 
        flash('Cancelled.'); 
        loadPage('printqueue'); 
    } catch (e) { 
        flash((e && e.detail) ? e.detail : 'Failed to cancel.'); 
    } 
} 
 
async function aiGenerateDraft() { 
    const kind = document.getElementById('ai-kind')?.value || 'test'; 
    const title = (document.getElementById('ai-title')?.value || '').trim();
    const school_class = document.getElementById('ai-class')?.value || null;
    const subject = document.getElementById('ai-subject')?.value || null;
    const instructions = (document.getElementById('ai-ins')?.value || '').trim();
    if (!instructions) { flash('Instructions are required.'); return; }
    try {
        await API.fetch('/ai-tools/generate/', { method: 'POST', body: JSON.stringify({ kind, title, school_class, subject, instructions }) });
        flash('Draft generated.');
        loadPage('ai_tools');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to generate draft.');
    }
}

async function openStudentHistory(studentId) {
    const body = document.getElementById('sh-body');
    if (body) body.innerHTML = 'Loading...';
    openModal('modal-stuhistory');
    const [data, finance] = await Promise.all([
        API.fetch(`/students/${studentId}/history/`),
        API.fetch(`/students/${studentId}/finance-timeline/`).catch(() => ({ plans: [], promises: [], reminders: [], invoices: [], timeline: [] })),
    ]);
    const s = data.student;
    const payRows = (data.payments || []).slice(0, 30).map(p => `<tr><td>${formatDateTime(p.received_at)}</td><td style="font-weight:800;color:var(--m)">UGX ${fmt(p.amount)}</td><td>${p.method}</td><td>${p.reference || '-'}</td><td>${p.status}</td></tr>`).join('');
    const markRows = (data.marks || []).slice(0, 30).map(m => `<tr><td>${m.year}</td><td>${m.term}</td><td>${m.subject}</td><td>${m.score}</td></tr>`).join('');
    const attRows = (data.attendance || []).slice(0, 30).map(a => `<tr><td>${a.date}</td><td>${a.status}</td></tr>`).join('');
    const invoiceCards = (finance.invoices || []).slice(0, 6).map(inv => `<div class="ri"><div class="ri-info"><div class="rn">Term ${inv.term_number} ${inv.academic_year}</div><div class="rd">Due UGX ${fmt(Number(inv.amount_due || 0).toFixed(0))} · Paid UGX ${fmt(Number(inv.amount_paid || 0).toFixed(0))}</div></div><div class="ri-end"><span class="badge ${statusBadgeClass(inv.status)}">${escapeHtml(inv.status || '')}</span></div></div>`).join('') || `<div class="sub">No invoices yet.</div>`;
    const promiseCards = (finance.promises || []).slice(0, 6).map(p => `<div class="ri"><div class="ri-info"><div class="rn">Promise: UGX ${fmt(Number(p.amount || 0).toFixed(0))}</div><div class="rd">Due ${escapeHtml(p.promised_for || '')}</div></div><div class="ri-end"><span class="badge ${statusBadgeClass(p.status)}">${escapeHtml(p.status || '')}</span></div></div>`).join('') || `<div class="sub">No fee promises recorded.</div>`;
    const planCards = (finance.plans || []).slice(0, 6).map(p => `<div class="ri"><div class="ri-info"><div class="rn">${escapeHtml(p.title || 'Installment plan')}</div><div class="rd">T${p.term_number}/${p.academic_year} · UGX ${fmt(Number(p.total_amount || 0).toFixed(0))}</div></div><div class="ri-end"><span class="badge ${statusBadgeClass(p.status)}">${escapeHtml(p.status || '')}</span></div></div>`).join('') || `<div class="sub">No installment plans recorded.</div>`;
    const reminderCards = (finance.reminders || []).slice(0, 6).map(r => `<div class="ri"><div class="ri-info"><div class="rn">${escapeHtml((r.channel || '').toUpperCase())} reminder</div><div class="rd">${escapeHtml(r.recipient || '-')} · ${formatDateTime(r.created_at)}</div></div><div class="ri-end"><span class="badge ${statusBadgeClass(r.status)}">${escapeHtml(r.status || '')}</span></div></div>`).join('') || `<div class="sub">No reminders logged.</div>`;
    const timelineItems = (finance.timeline || []).slice(0, 80).map(ev => `
      <div class="ri">
        <div class="ri-info">
          <div class="rn">${escapeHtml(ev.title || '')}</div>
          <div class="rd">${formatDateTime(ev.event_at)}${ev.detail ? ' · ' + escapeHtml(ev.detail) : ''}</div>
        </div>
        <div class="ri-end">${ev.amount ? `<div style="font-weight:800;color:var(--m)">UGX ${fmt(Number(ev.amount || 0).toFixed(0))}</div>` : ''}<span class="badge ${statusBadgeClass(ev.kind)}">${escapeHtml(ev.kind || '')}</span></div>
      </div>`).join('') || `<div class="sub">No finance events yet.</div>`;
    if (body) body.innerHTML = `
      <div style="display:flex;gap:14px;flex-wrap:wrap;align-items:flex-start">
        <div style="width:110px;height:130px;border-radius:18px;overflow:hidden;border:1px solid var(--e);background:linear-gradient(135deg,var(--mll),#fff);display:flex;align-items:center;justify-content:center;flex-shrink:0">
          ${s.photo_url ? `<img alt="Student" src="${escapeHtml(s.photo_url)}" style="width:100%;height:100%;object-fit:cover">` : `<div style="font-size:32px;font-weight:900;color:var(--m)">${escapeHtml(((s.first_name || '').slice(0,1) + (s.last_name || '').slice(0,1)).toUpperCase() || 'S')}</div>`}
        </div>
        <div style="flex:1;min-width:260px">
          <div style="font-weight:900;font-size:16px;color:var(--md)">${s.first_name} ${s.last_name}</div>
          <div style="font-size:12px;color:var(--66);margin-top:2px">${s.student_id} · ${s.current_class_level || '-'}${s.section || ''} · ${s.status}</div>
          <div class="kv-grid" style="margin-top:10px">
            <div class="kv-item"><div class="k">Parent</div><div class="v">${escapeHtml(s.parent_name || '-')}</div><div class="sub">${escapeHtml(s.parent_relationship || '')}</div></div>
            <div class="kv-item"><div class="k">Contacts</div><div class="v">${escapeHtml(s.parent_phone || '-')}</div><div class="sub">${escapeHtml(s.parent_email || s.parent_phone2 || '')}</div></div>
            <div class="kv-item"><div class="k">Address</div><div class="v">${escapeHtml(s.home_address || 'Not recorded')}</div></div>
            <div class="kv-item"><div class="k">Health</div><div class="v">${escapeHtml(s.medical_conditions || 'No conditions noted')}</div><div class="sub">${escapeHtml(s.allergies || 'No allergies recorded')}</div></div>
          </div>
          <div style="margin-top:10px;color:var(--66);font-size:13px">
            <div><strong>Parent:</strong> ${s.parent_name} (${s.parent_relationship})</div>
            <div><strong>Phone:</strong> ${s.parent_phone}${s.parent_phone2 ? ' / ' + s.parent_phone2 : ''}</div>
            <div><strong>Emergency:</strong> ${escapeHtml(s.emergency_contact_name || 'Not recorded')}${s.emergency_contact_phone ? ' · ' + escapeHtml(s.emergency_contact_phone) : ''}</div>
          </div>
        </div>
        <div style="min-width:260px">
          <button class="btn btn-ghost" onclick="editStudentFromHistory(${s.id})">Edit Student</button>
        </div>
      </div>
      <div style="height:12px"></div>
      <div class="tabs">
        <button class="tab-b active" onclick="tabShow('sh-pay',this)">Payments</button>
        <button class="tab-b" onclick="tabShow('sh-fin',this)">Finance</button>
        <button class="tab-b" onclick="tabShow('sh-marks',this)">Marks</button>
        <button class="tab-b" onclick="tabShow('sh-att',this)">Attendance</button>
      </div>
      <div style="height:10px"></div>
      <div id="sh-pay" class="tab-p active">
        <div class="tw"><table class="tbl"><thead><tr><th>Time</th><th>Amount</th><th>Method</th><th>Reference</th><th>Status</th></tr></thead><tbody>${payRows || ''}</tbody></table></div>
      </div>
      <div id="sh-fin" class="tab-p">
        <div class="grid-2">
          <div class="card"><div class="card-head"><div class="card-title">Finance Timeline</div></div><div class="card-body">${timelineItems}</div></div>
          <div>
            <div class="card"><div class="card-head"><div class="card-title">Invoices</div></div><div class="card-body">${invoiceCards}</div></div>
            <div style="height:10px"></div>
            <div class="card"><div class="card-head"><div class="card-title">Installment Plans</div></div><div class="card-body">${planCards}</div></div>
            <div style="height:10px"></div>
            <div class="card"><div class="card-head"><div class="card-title">Fee Promises</div></div><div class="card-body">${promiseCards}</div></div>
            <div style="height:10px"></div>
            <div class="card"><div class="card-head"><div class="card-title">Reminder Log</div></div><div class="card-body">${reminderCards}</div></div>
          </div>
        </div>
      </div>
      <div id="sh-marks" class="tab-p">
        <div class="tw"><table class="tbl"><thead><tr><th>Year</th><th>Term</th><th>Subject</th><th>Score</th></tr></thead><tbody>${markRows || ''}</tbody></table></div>
      </div>
      <div id="sh-att" class="tab-p">
        <div class="tw"><table class="tbl"><thead><tr><th>Date</th><th>Status</th></tr></thead><tbody>${attRows || ''}</tbody></table></div>
      </div>
    `;
}

function tabShow(id, btn) {
    const root = btn.closest('.modal-body') || document;
    root.querySelectorAll('.tab-b').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    root.querySelectorAll('.tab-p').forEach(p => p.classList.remove('active'));
    const el = root.querySelector('#' + id);
    if (el) el.classList.add('active');
}

async function editStudentFromHistory(id) {
    closeModal('modal-stuhistory');
    await openStudentEdit(id);
}

async function deleteClass(id) {
    await API.fetch(`/classes/${id}/`, { method: 'DELETE' });
    flash('Class deleted.');
    loadPage('classes');
}

async function deleteTeacher(id) {
    await API.fetch(`/teachers/${id}/`, { method: 'DELETE' });
    flash('Teacher deleted.');
    loadPage('teachers');
}

async function deleteStudent(id) {
    await API.fetch(`/students/${id}/`, { method: 'DELETE' });
    flash('Student deleted.');
    loadPage('students');
}

async function resetPortals(studentId) {
    try {
        const res = await API.fetch(`/students/${studentId}/reset-portals/`, { method: 'POST', body: JSON.stringify({ reset_parent: true, reset_student: true }) });
        const parts = [];
        if (res.parent_username && res.parent_temp_password) parts.push(`Parent: ${res.parent_username} / ${res.parent_temp_password}`);
        if (res.parent_email) parts.push(`Parent email: ${res.parent_email}`);
        if (res.student_username && res.student_temp_password) parts.push(`Student: ${res.student_username} / ${res.student_temp_password}`);
        if (parts.length) {
            flash('New credentials: ' + parts.join(' | '));
            showHandover('Reset Portal Credentials', parts, null);
        } else {
            flash('Passwords reset.');
        }
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to reset passwords.');
    }
}

async function smsReminder(studentId, term_number, academic_year) {
    try {
        await API.fetch(`/students/${studentId}/send-fee-reminder/`, { method: 'POST', body: JSON.stringify({ term_number, academic_year }) });
        flash('Reminder SMS sent.');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to send SMS.');
    }
}

async function saveMyProfile() {
    const first_name = document.getElementById('me-fn')?.value?.trim() || '';
    const last_name = document.getElementById('me-ln')?.value?.trim() || '';
    const email = document.getElementById('me-email')?.value?.trim() || '';
    const phone_number = document.getElementById('me-phone')?.value?.trim() || '';
    const email_address = document.getElementById('me-pemail')?.value?.trim() || '';
    const photo_url = document.getElementById('me-photo')?.value?.trim() || '';
    const profile_data = {
        job_title: document.getElementById('me-job')?.value?.trim() || '',
        address: document.getElementById('me-addr')?.value?.trim() || '',
        bio: document.getElementById('me-bio')?.value?.trim() || '',
    };
    currentUser = await API.fetch('/auth/me/', { method: 'PATCH', body: JSON.stringify({ first_name, last_name, email, phone_number, email_address, photo_url, profile_data }) });
    flash('Profile updated.');
    loadPage('settings');
}

async function saveSystemSettings() { 
    const items = [ 
        { key: 'send_credentials_sms', value: !!document.getElementById('ss-cred-sms')?.checked }, 
        { key: 'send_credentials_email', value: !!document.getElementById('ss-cred-email')?.checked }, 
        { key: 'send_fee_reminder_sms', value: !!document.getElementById('ss-fee-sms')?.checked }, 
    ]; 
    const aiEl = document.getElementById('ss-ai');
    if (aiEl) items.push({ key: 'ai_tools_enabled', value: { enabled: !!aiEl.checked } });
    const tpl = document.getElementById('ss-adm-tpl');
    if (tpl) { 
        const text = (tpl.value || '').toString(); 
        items.push({ key: 'admission_letter_template', value: { text } }); 
    } 
    const bName = document.getElementById('ss-b-name'); 
    const bTag = document.getElementById('ss-b-tag'); 
    const bContact = document.getElementById('ss-b-contact'); 
    const bLogo = document.getElementById('ss-b-logo'); 
    if (bName || bTag || bContact || bLogo) { 
        items.push({ 
            key: 'school_branding', 
            value: { 
                school_name: (bName?.value || '').trim(), 
                tagline: (bTag?.value || '').trim(), 
                contact: (bContact?.value || '').trim(), 
                logo_url: (bLogo?.value || '').trim() || null, 
            } 
        }); 
    } 
    const rpAuto = document.getElementById('ss-rp-auto'); 
    const rpReason = document.getElementById('ss-rp-reason'); 
    if (rpAuto || rpReason) { 
        items.push({ 
            key: 'results_policy', 
            value: { 
                auto_hold_on_term_end: !!rpAuto?.checked, 
                default_reason: (rpReason?.value || '').trim() || 'Outstanding fees', 
            } 
        }); 
    } 
    try { 
        await API.fetch('/system-settings/bulk/', { method: 'POST', body: JSON.stringify({ items }) }); 
        flash('System settings saved.'); 
    } catch (e) { 
        flash((e && e.detail) ? e.detail : 'Failed to save system settings.'); 
    } 
} 

function clearFeeForm() {
    document.getElementById('f-id').value = '';
    if (document.getElementById('f-class')) document.getElementById('f-class').value = '';
    document.getElementById('f-year').value = new Date().getFullYear();
    document.getElementById('f-term').value = '1';
    document.getElementById('f-amt').value = '';
}

async function openFeeAdd(classId = null, year = null, term = null) {
    clearFeeForm();
    const classes = await API.fetch('/classes/');
    const sel = document.getElementById('f-class');
    sel.innerHTML = (classes || []).map(c => `<option value="${c.id}">${c.level}</option>`).join('');
    if (classId) sel.value = String(classId);
    if (year) document.getElementById('f-year').value = year;
    if (term) document.getElementById('f-term').value = String(term);
    openModal('modal-fee');
}

async function openFeeEdit(id) {
    clearFeeForm();
    const [classes, f] = await Promise.all([API.fetch('/classes/'), API.fetch(`/fees/${id}/`)]);
    const sel = document.getElementById('f-class');
    sel.innerHTML = (classes || []).map(c => `<option value="${c.id}">${c.level}</option>`).join('');
    document.getElementById('f-id').value = f.id;
    sel.value = String(f.school_class);
    document.getElementById('f-year').value = f.year;
    document.getElementById('f-term').value = String(f.term);
    document.getElementById('f-amt').value = f.amount;
    openModal('modal-fee');
}

async function saveFee() {
    const id = document.getElementById('f-id').value;
    const school_class = document.getElementById('f-class').value;
    const year = parseInt(document.getElementById('f-year').value, 10);
    const term = parseInt(document.getElementById('f-term').value, 10);
    const amount = document.getElementById('f-amt').value;
    if (!school_class || !year || !term || !amount) { flash('Enter class/year/term/amount.'); return; }
    const payload = { school_class, year, term, amount };
    if (id) await API.fetch(`/fees/${id}/`, { method: 'PATCH', body: JSON.stringify(payload) });
    else await API.fetch('/fees/', { method: 'POST', body: JSON.stringify(payload) });
    closeModal('modal-fee');
    flash('Fee saved.');
    loadPage('fees');
}

async function changePassword() {
    const current_password = document.getElementById('sp-cur').value;
    const new_password = document.getElementById('sp-new').value;
    const confirm_password = document.getElementById('sp-conf').value;
    if (!current_password || !new_password) { flash('Enter current and new password.'); return; }
    if (!validateStrongPasswordClient(new_password, 'New password')) return;
    if (new_password !== confirm_password) { flash('Passwords do not match.'); return; }
    await API.fetch('/auth/change-password/', { method: 'POST', body: JSON.stringify({ current_password, new_password }) });
    flash('Password changed. Please log in again.');
    doLogout();
}

async function logoutOtherSessions() {
    await API.fetch('/auth/logout-other-sessions/', { method: 'POST', body: JSON.stringify({}) });
    flash('Other sessions logged out.');
    loadPage('settings');
}

function toggleTheme() {
    const key = 'bjs_theme';
    const current = localStorage.getItem(key) || 'light';
    const next = current === 'dark' ? 'light' : 'dark';
    localStorage.setItem(key, next);
    document.body.dataset.theme = next;
    flash(`Theme: ${next}`);
}

// Apply theme early when possible.
try { document.body.dataset.theme = localStorage.getItem('bjs_theme') || 'light'; } catch {}

// Close modals when clicking the overlay.
document.querySelectorAll('.modal-overlay').forEach(ov => {
  ov.addEventListener('click', (e) => {
    if (e.target === ov) ov.classList.remove('show');
  });
});

function openModal(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.add('show');

    // Prefill sensible defaults for Start New Term modal.
    if (id === 'modal-term') {
        const now = new Date();
        const yyyy = now.getFullYear();
        const pad2 = (n) => String(n).padStart(2, '0');
        const today = `${yyyy}-${pad2(now.getMonth() + 1)}-${pad2(now.getDate())}`;
        const plusMonths = (m) => {
            const d = new Date(now.getTime());
            d.setMonth(d.getMonth() + m);
            return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
        };
        const yr = document.getElementById('nt-yr');
        const st = document.getElementById('nt-st');
        const en = document.getElementById('nt-en');
        if (yr && !(yr.value || '').trim()) yr.value = String(yyyy);
        if (st && !(st.value || '').trim()) st.value = today;
        if (en && !(en.value || '').trim()) en.value = plusMonths(3);
    }
}
function closeModal(id) { document.getElementById(id).classList.remove('show'); }
// toggleSidebar is defined earlier with responsive behavior.
function fmt(n) { return Number(n).toLocaleString(); }

function loadCashbookPreview() {
    CASHBOOK_FILTER.close_date = document.getElementById('cb-date')?.value || todayISO();
    CASHBOOK_FILTER.cashier = document.getElementById('cb-cashier')?.value || '';
    CASHBOOK_FILTER.opening_cash = document.getElementById('cb-opening')?.value || '0';
    CASHBOOK_FILTER.counted_cash_on_hand = document.getElementById('cb-counted')?.value || '0';
    loadPage('cashbook', null, 'Cashbook');
}

async function saveCashbookClose() {
    const close_date = document.getElementById('cb-date')?.value || todayISO();
    const cashier = document.getElementById('cb-cashier')?.value || null;
    const opening_cash = document.getElementById('cb-opening')?.value || '0';
    const counted_cash_on_hand = document.getElementById('cb-counted')?.value || '0';
    const notes = document.getElementById('cb-notes')?.value || '';
    const payload = { close_date, opening_cash, counted_cash_on_hand, notes };
    if (cashier) payload.cashier = cashier;
    const res = await API.fetch('/cashbook-closes/', { method: 'POST', body: JSON.stringify(payload) });
    flash('Cashbook closed and saved.');
    if (res && res.id) window.open(`/api/cashbook-closes/${res.id}/report/`, '_blank');
    loadPage('cashbook', null, 'Cashbook');
}

function openCashbookReport(id) {
    if (!id) return;
    window.open(`/api/cashbook-closes/${id}/report/`, '_blank');
}

function openCashbookHandoverReport(closeDate = null, cashierId = null) {
    const params = new URLSearchParams();
    const resolvedDate = closeDate || document.getElementById('cb-date')?.value || todayISO();
    const resolvedCashier = cashierId || document.getElementById('cb-cashier')?.value || '';
    if (resolvedDate) params.set('close_date', resolvedDate);
    if (resolvedCashier) params.set('cashier', resolvedCashier);
    window.open(`/api/cashbook-closes/handover-report/?${params.toString()}`, '_blank');
}

function loadInstallmentPlansFiltered() {
    PLAN_FILTER.year = document.getElementById('ip-f-year')?.value || PLAN_FILTER.year;
    PLAN_FILTER.term = document.getElementById('ip-f-term')?.value || PLAN_FILTER.term;
    PLAN_FILTER.status = document.getElementById('ip-f-status')?.value || '';
    loadPage('installment_plans', null, 'Installments');
}

async function createInstallmentPlan() {
    const student = document.getElementById('ip-student')?.value;
    const academic_year = parseInt(document.getElementById('ip-year')?.value || '', 10);
    const term_number = parseInt(document.getElementById('ip-term')?.value || '', 10);
    const title = (document.getElementById('ip-title')?.value || '').trim() || 'Fee installment plan';
    const total = Number(document.getElementById('ip-total')?.value || 0);
    const firstDate = document.getElementById('ip-first-date')?.value || todayISO();
    const count = Math.max(1, parseInt(document.getElementById('ip-count')?.value || '1', 10));
    const gap = Math.max(1, parseInt(document.getElementById('ip-gap')?.value || '30', 10));
    const notes = (document.getElementById('ip-notes')?.value || '').trim();
    if (!student || !academic_year || !term_number || !total) { flash('Student, year, term, and total amount are required.'); return; }

    const items = [];
    let remaining = Math.round(total * 100);
    const base = Math.floor(remaining / count);
    const d = new Date(`${firstDate}T12:00:00Z`);
    for (let i = 0; i < count; i++) {
        const cents = (i === count - 1) ? remaining : base;
        remaining -= cents;
        const due = new Date(d.getTime());
        due.setDate(due.getDate() + (i * gap));
        items.push({
            label: `Installment ${i + 1}`,
            due_date: dateToISO(due),
            amount: (cents / 100).toFixed(2),
            notes: '',
        });
    }

    await API.fetch('/installment-plans/', {
        method: 'POST',
        body: JSON.stringify({
            student,
            academic_year,
            term_number,
            title,
            total_amount: total.toFixed(2),
            start_date: firstDate,
            notes,
            items,
        }),
    });
    flash('Installment plan created.');
    PLAN_FILTER.year = String(academic_year);
    PLAN_FILTER.term = String(term_number);
    loadPage('installment_plans', null, 'Installments');
}

async function sendInstallmentReminder(planId) {
    if (!planId) return;
    try {
        await API.fetch(`/installment-plans/${planId}/send-reminder/`, { method: 'POST', body: JSON.stringify({ channel: 'both' }) });
        flash('Installment reminder sent.');
        loadPage('installment_plans', null, 'Installments');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to send installment reminder.');
    }
}

function loadFeePromisesFiltered() {
    PROMISE_FILTER.year = document.getElementById('fp-f-year')?.value || PROMISE_FILTER.year;
    PROMISE_FILTER.term = document.getElementById('fp-f-term')?.value || PROMISE_FILTER.term;
    PROMISE_FILTER.status = document.getElementById('fp-f-status')?.value || '';
    loadPage('fee_promises', null, 'Fee Promises');
}

async function createFeePromise() {
    const student = document.getElementById('fp-student')?.value;
    const academic_year = parseInt(document.getElementById('fp-year')?.value || '', 10);
    const term_number = parseInt(document.getElementById('fp-term')?.value || '', 10);
    const amount = Number(document.getElementById('fp-amount')?.value || 0);
    const promised_for = document.getElementById('fp-date')?.value || todayISO();
    const notes = (document.getElementById('fp-notes')?.value || '').trim();
    if (!student || !academic_year || !term_number || !amount || !promised_for) { flash('Student, year, term, amount, and promise date are required.'); return; }
    await API.fetch('/fee-promises/', {
        method: 'POST',
        body: JSON.stringify({
            student,
            academic_year,
            term_number,
            amount: amount.toFixed(2),
            promised_for,
            notes,
        }),
    });
    flash('Fee promise saved.');
    PROMISE_FILTER.year = String(academic_year);
    PROMISE_FILTER.term = String(term_number);
    loadPage('fee_promises', null, 'Fee Promises');
}

async function sendFeePromiseReminder(id) {
    if (!id) return;
    try {
        await API.fetch(`/fee-promises/${id}/send-reminder/`, { method: 'POST', body: JSON.stringify({}) });
        flash('Fee promise reminder sent.');
        loadPage('fee_promises', null, 'Fee Promises');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to send fee promise reminder.');
    }
}

async function markFeePromise(id, action) {
    if (!id || !action) return;
    const endpoint = action === 'kept' ? 'mark-kept' : 'mark-missed';
    await API.fetch(`/fee-promises/${id}/${endpoint}/`, { method: 'POST', body: JSON.stringify({}) });
    flash(`Fee promise marked ${action}.`);
    loadPage('fee_promises', null, 'Fee Promises');
}

// Timetable builder state (admin/reception).
let TT = { school_class: null, section: '', days: [], periods: [], times: {}, cells: {}, teachers: [], subjects: [], _classes: [] };
TT._dirty = false;
TT._autosave_timer = null;

function ttSetDirty(v) {
    TT._dirty = !!v;
    const el = document.getElementById('tt-dirty');
    if (el) el.textContent = TT._dirty ? 'Unsaved changes' : 'Saved';
}

function ttMarkDirty() {
    ttSetDirty(true);
    // Auto-save after a short pause to avoid losing edits.
    try {
        if (TT._autosave_timer) clearTimeout(TT._autosave_timer);
        TT._autosave_timer = setTimeout(() => {
            // Best-effort; don't block user typing.
            ttSave().catch(() => {});
        }, 1800);
    } catch {}
}

function ttParseList(v) {
    return (v || '').split(',').map(s => s.trim()).filter(Boolean);
}

function ttKey(day, period) { return `${day}-${period}`; }

function ttNormCell(v) {
    // Backwards-compatible: old values were strings.
    if (!v) return { subject: '', teacher_id: '', teacher_name: '' };
    if (typeof v === 'string') return { subject: v, teacher_id: '', teacher_name: '' };
    if (typeof v === 'object') {
        return {
            subject: (v.subject || '').toString(),
            teacher_id: (v.teacher_id || '').toString(),
            teacher_name: (v.teacher_name || '').toString(),
        };
    }
    return { subject: String(v), teacher_id: '', teacher_name: '' };
}

function ttSetCell(k, patch) {
    const cur = ttNormCell(TT.cells[k]);
    const next = { ...cur, ...(patch || {}) };
    // Keep cells compact: if only subject is filled and no teacher chosen, store as string.
    if (!next.teacher_id && !next.teacher_name) {
        TT.cells[k] = next.subject || '';
    } else {
        TT.cells[k] = next;
    }
    ttMarkDirty();
}

function ttCurrentDayLabel() {
    // Use local timezone; map to our default short labels.
    const d = new Date();
    const map = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    return map[d.getDay()];
}

function ttParseTimeToMinutes(hhmm) {
    const s = String(hhmm || '').trim();
    if (!s || s.indexOf(':') === -1) return null;
    const [h, m] = s.split(':');
    const hh = parseInt(h, 10);
    const mm = parseInt(m, 10);
    if (!Number.isFinite(hh) || !Number.isFinite(mm)) return null;
    return (hh * 60) + mm;
}

function ttCurrentPeriod(periods, times) {
    const now = new Date();
    const nowM = (now.getHours() * 60) + now.getMinutes();
    for (const p of (periods || [])) {
        const key = String(p);
        const t = times && times[key] ? times[key] : null;
        const st = t ? ttParseTimeToMinutes(t.start) : null;
        const en = t ? ttParseTimeToMinutes(t.end) : null;
        if (st === null || en === null) continue;
        if (nowM >= st && nowM <= en) return key;
    }
    return null;
}

function ttSetTime(period, which, value) {
    const p = String(period);
    TT.times = TT.times || {};
    TT.times[p] = TT.times[p] || {};
    TT.times[p][which] = value || '';
    ttMarkDirty();
    ttRender();
}

function ttRenderTimesEditor() {
    const el = document.getElementById('tt-times-editor');
    if (!el) return;
    const periods = TT.periods || [];
    if (!periods.length) { el.innerHTML = `<div style="font-size:12px;color:#666">No periods configured.</div>`; return; }

    const rows = periods.map((p) => {
        const key = String(p);
        const t = (TT.times && TT.times[key]) ? TT.times[key] : {};
        const st = (t && t.start) ? String(t.start) : '';
        const en = (t && t.end) ? String(t.end) : '';
        return `<tr>
          <td style="min-width:90px"><strong>${key}</strong></td>
          <td><input class="field-input" type="time" value="${st}" oninput="ttSetTime('${key}','start',this.value)"></td>
          <td><input class="field-input" type="time" value="${en}" oninput="ttSetTime('${key}','end',this.value)"></td>
        </tr>`;
    }).join('');

    el.innerHTML = `
      <div class="tw">
        <table class="tbl">
          <thead><tr><th>Period</th><th>Start</th><th>End</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
}

function ttRender() {
    const el = document.getElementById('tt-grid');
    if (!el) return;
    const days = TT.days;
    const periods = TT.periods;
    const times = TT.times || {};
    const today = ttCurrentDayLabel();
    const nowP = ttCurrentPeriod(periods, times);
    const teachers = Array.isArray(TT.teachers) ? TT.teachers : [];

    const clsId = TT.school_class;
    const meta = (TT._classes || []).find(c => String(c.id) === String(clsId));
    const level = meta ? String(meta.level || '').trim() : '';
    const sec = String(TT.section || '').trim().toUpperCase();
    const metaSecs = (meta && Array.isArray(meta.sections)) ? meta.sections : [];
    const assignedKey = (level ? (metaSecs.length ? (sec ? (level + sec) : '') : level) : '');
    const normAssigned = (s) => String(s || '').trim().toUpperCase().replace(/\s+/g, '');
    const normName = (s) => String(s || '').trim().toLowerCase();
    const ttTeacherCandidates = (subjectRaw) => {
        const subj = normName(subjectRaw);
        const clsK = normAssigned(assignedKey);
        const byClass = clsK ? teachers.filter(t => normAssigned(t.assigned_class) === clsK) : teachers.slice();
        let cands = byClass;
        if (subj) {
            cands = byClass.filter(t => {
                const ss = Array.isArray(t.subjects) ? t.subjects : [];
                return ss.some(x => normName(x) === subj);
            });
            if (!cands.length) cands = byClass; // relax subject filter if none match
        }
        if (!cands.length) cands = teachers.slice();
        cands.sort((a, b) => {
            const an = `${a.first_name || ''} ${a.last_name || ''}`.trim().toLowerCase();
            const bn = `${b.first_name || ''} ${b.last_name || ''}`.trim().toLowerCase();
            return an.localeCompare(bn);
        });
        return cands;
    };

    const ttTeacherSelectHtml = (cell, candidates) => {
        const tid = String(cell.teacher_id || '').trim();
        const cur = tid ? teachers.find(t => String(t.id) === tid) : null;
        const opt = (t, selected) => {
            const nm = `${(t.first_name || '').toString()} ${(t.last_name || '').toString()}`.trim();
            const label = `${nm}${t.employee_id ? (' (' + t.employee_id + ')') : ''}${t.assigned_class ? (' · ' + t.assigned_class) : ''}`;
            return `<option value="${t.id}" ${selected ? 'selected' : ''}>${escapeHtml(label)}</option>`;
        };
        const set = new Set(candidates.map(t => String(t.id)));
        const rows = ['<option value="">(No teacher)</option>'];
        if (cur && !set.has(String(cur.id))) rows.push(opt(cur, true));
        candidates.forEach(t => rows.push(opt(t, String(t.id) === tid)));
        return rows.join('');
    };

    const subjOptions = (TT.subjects || []).map(s => `<option value="${escapeHtml(s)}"></option>`).join('');
    const head = `<thead><tr><th style="min-width:90px">Day</th>${periods.map(p => {
        const key = String(p);
        const t = times[key] || null;
        const range = (t && t.start && t.end) ? `<div style="font-size:10px;color:#666;margin-top:2px">${t.start}-${t.end}</div>` : '';
        const cls = (nowP && nowP === key) ? 'tt-now-col' : '';
        return `<th class="${cls}" style="min-width:120px">${key}${range}</th>`;
    }).join('')}</tr></thead>`;
    const body = days.map(d => `<tr class="${(d === today) ? 'tt-today-row' : ''}">
        <td><strong>${d}</strong></td>
        ${periods.map(p => {
            const k = ttKey(d, p);
            const isNow = (d === today) && (nowP && String(p) === String(nowP));
            const cell = ttNormCell(TT.cells[k]);
            const subj = (cell.subject || '').toString().replace(/"/g, '&quot;');
            const tname = (cell.teacher_name || '').toString().replace(/"/g, '&quot;');
            const candidates = ttTeacherCandidates(subj);
            return `<td class="${isNow ? 'tt-now-cell' : ''}">
              <div style="display:flex;flex-direction:column;gap:6px">
                <input class="field-input" list="tt-subjects" style="padding:6px 8px;font-size:12px" value="${subj}" placeholder="Subject / Activity" oninput="ttSetCell('${k}', {subject: this.value})">
                <select class="field-select" style="padding:6px 8px;font-size:12px" onchange="ttOnTeacherPick('${k}', this.value)">
                  ${ttTeacherSelectHtml(cell, candidates)}
                </select>
                <input class="field-input" style="padding:6px 8px;font-size:12px;display:none" value="${tname}">
              </div>
            </td>`;
        }).join('')}
      </tr>`).join('');
    el.innerHTML = `<datalist id="tt-subjects">${subjOptions}</datalist><table class="tbl">${head}<tbody>${body}</tbody></table>`;
    ttRenderTimesEditor();
}

function setFinanceFilterAndReload() {
    const y = (document.getElementById('fin-year')?.value || '').trim();
    const t = (document.getElementById('fin-term')?.value || '').trim();
    if (y && !String(y).match(/^\d{4}$/)) { flash('Enter a valid year (e.g. 2026).'); return; }
    if (t && !String(t).match(/^[1-3]$/)) { flash('Term must be 1, 2, or 3.'); return; }
    FIN_FILTER.year = y || FIN_FILTER.year;
    FIN_FILTER.term = t || FIN_FILTER.term;
    loadPage('finance', null, 'Payments');
}

function ttOnClassChanged() {
    try {
        const clsId = document.getElementById('tt-class')?.value;
        const meta = (TT._classes || []).find(c => String(c.id) === String(clsId));
        const secs = (meta && Array.isArray(meta.sections)) ? meta.sections : [];
        const wrap = document.getElementById('tt-sec-wrap');
        const secInput = document.getElementById('tt-sec');
        if (!wrap || !secInput) return;
        if (!secs.length) {
            wrap.style.display = 'none';
            secInput.value = '';
        } else {
            wrap.style.display = '';
            const cur = (secInput.value || '').trim().toUpperCase();
            const ok = secs.map(s => String(s).trim().toUpperCase()).includes(cur);
            secInput.value = ok ? cur : String(secs[0]).trim().toUpperCase();
        }
    } catch {}
}

async function ttLoad() {
    const cls = document.getElementById('tt-class')?.value;
    ttOnClassChanged();
    const sec = (document.getElementById('tt-sec')?.value || '').trim().toUpperCase();
    const days = ttParseList(document.getElementById('tt-days')?.value || 'Mon,Tue,Wed,Thu,Fri');
    const periods = ttParseList(document.getElementById('tt-periods')?.value || '1,2,3,4,5,6,7,8');

    const subs = await API.fetch(`/class-subjects/?school_class=${encodeURIComponent(cls)}`).catch(() => []);
    const subjectNames = (subs || []).map(x => x.subject_name || '').filter(Boolean);
    TT = { ...TT, school_class: cls, section: sec, days, periods, times: {}, cells: {}, subjects: subjectNames };

    // Use filtered list endpoint for admins/reception.
    const qs = new URLSearchParams({ school_class: String(cls || ''), section: String(sec || '') });
    const existing = await API.fetch(`/timetable/?${qs.toString()}`).catch(() => []);
    const tt = (existing && existing.length) ? existing[0] : null;
    if (tt) {
        const slots = tt.slots || {};
        const d2 = slots.days || days;
        const p2 = slots.periods || periods;
        const t2 = slots.times || {};
        TT.days = d2;
        TT.periods = p2;
        TT.times = t2 || {};
        TT.cells = tt.cells || {};
        // Update inputs to match saved config.
        if (document.getElementById('tt-days')) document.getElementById('tt-days').value = TT.days.join(',');
        if (document.getElementById('tt-periods')) document.getElementById('tt-periods').value = TT.periods.join(',');
    }
    ttRender();
    ttSetDirty(false);
}

async function ttSave() {
    const cls = document.getElementById('tt-class')?.value;
    ttOnClassChanged();
    const sec = (document.getElementById('tt-sec')?.value || '').trim().toUpperCase();
    TT.school_class = cls;
    TT.section = sec;
    TT.days = ttParseList(document.getElementById('tt-days')?.value || 'Mon,Tue,Wed,Thu,Fri');
    TT.periods = ttParseList(document.getElementById('tt-periods')?.value || '1,2,3,4,5,6,7,8');
    // Keep only times for current periods.
    const times = {};
    (TT.periods || []).forEach(p => {
        const key = String(p);
        if (TT.times && TT.times[key]) times[key] = TT.times[key];
    });
    TT.times = times;
    const payload = {
        school_class: cls,
        section: sec,
        slots: { days: TT.days, periods: TT.periods, times: TT.times },
        cells: TT.cells || {},
    };
    await API.fetch('/timetable/upsert/', { method: 'POST', body: JSON.stringify(payload) });
    ttSetDirty(false);
    flash('Timetable saved.');
}

function ttPrint() {
    const days = TT.days;
    const periods = TT.periods;
    const times = TT.times || {};
    const cells = TT.cells || {};
    const head = `<tr><th>Day</th>${periods.map(p => {
        const key = String(p);
        const t = times[key] || null;
        const range = (t && t.start && t.end) ? `<div style="font-size:10px;opacity:.85;margin-top:2px">${t.start}-${t.end}</div>` : '';
        return `<th>${key}${range}</th>`;
    }).join('')}</tr>`;
    const rows = days.map(d => `<tr><td><strong>${d}</strong></td>${periods.map(p => {
        const v = ttNormCell(cells[ttKey(d, p)]);
        const subj = (v.subject || '').toString();
        const tname = (v.teacher_name || '').toString();
        const out = tname ? `${subj}${subj ? '<br>' : ''}<span style="color:#555">Teacher: ${tname}</span>` : subj;
        return `<td>${out || ''}</td>`;
    }).join('')}</tr>`).join('');
    const html = `<!doctype html><html><head><meta charset="utf-8"><title>Timetable</title>
      <style>body{font-family:Arial,sans-serif;padding:20px}table{width:100%;border-collapse:collapse}th,td{border:1px solid #ccc;padding:8px;font-size:12px}th{background:#7A0000;color:#fff}td:first-child{background:#f3f3f3}</style>
      </head><body>
      <h2>Timetable</h2>
      <div style="margin-bottom:10px">Class ID: ${TT.school_class || ''}${TT.section ? (' · Section: ' + TT.section) : ''}</div>
      <table><thead>${head}</thead><tbody>${rows}</tbody></table>
      </body></html>`;
    const w = window.open('', '_blank');
    w.document.open();
    w.document.write(html);
    w.document.close();
    setTimeout(() => { try { w.focus(); w.print(); } catch {} }, 250);
}

function ttAutoFillTimes() {
    const start = (document.getElementById('tt-auto-start')?.value || '08:00').trim();
    const dur = parseInt(document.getElementById('tt-auto-dur')?.value || '40', 10);
    if (!start || !dur || dur <= 0) { flash('Enter start time and minutes/period.'); return; }
    const parts = start.split(':');
    if (parts.length !== 2) { flash('Invalid start time.'); return; }
    let mins = (parseInt(parts[0], 10) * 60) + parseInt(parts[1], 10);

    TT.times = TT.times || {};
    (TT.periods || []).forEach((p) => {
        const key = String(p);
        const st = mins;
        const en = mins + dur;
        const fmt2 = (n) => String(n).padStart(2, '0');
        TT.times[key] = {
            start: `${fmt2(Math.floor(st / 60))}:${fmt2(st % 60)}`,
            end: `${fmt2(Math.floor(en / 60))}:${fmt2(en % 60)}`,
        };
        mins = en;
    });
    ttRender();
    flash('Period times filled.');
}

function ttOnTeacherPick(cellKey, teacherId) {
    const teachers = Array.isArray(TT.teachers) ? TT.teachers : [];
    const tid = (teacherId || '').toString();
    if (!tid) {
        ttSetCell(cellKey, { teacher_id: '', teacher_name: '' });
        return;
    }
    const t = teachers.find(x => String(x.id) === tid);
    const name = t ? `${(t.first_name || '').toString()} ${(t.last_name || '').toString()}`.trim() : '';
    ttSetCell(cellKey, { teacher_id: tid, teacher_name: name });
}

async function ttCopyFrom() {
    const srcClass = document.getElementById('tt-copy-class')?.value;
    const srcSec = (document.getElementById('tt-copy-sec')?.value || '').trim().toUpperCase();
    if (!srcClass) { flash('Select a source class to copy from.'); return; }
    const qs = new URLSearchParams({ school_class: String(srcClass || ''), section: String(srcSec || '') });
    const existing = await API.fetch(`/timetable/?${qs.toString()}`).catch(() => []);
    const tt = (existing && existing.length) ? existing[0] : null;
    if (!tt) { flash('No timetable found for that class/section.'); return; }
    const slots = tt.slots || {};
    TT.days = slots.days || TT.days;
    TT.periods = slots.periods || TT.periods;
    TT.times = slots.times || {};
    TT.cells = tt.cells || {};
    if (document.getElementById('tt-days')) document.getElementById('tt-days').value = TT.days.join(',');
    if (document.getElementById('tt-periods')) document.getElementById('tt-periods').value = TT.periods.join(',');
    ttRender();
    flash('Copied timetable.');
}

function clearChargeImage() {
    const img = document.getElementById('ch-img');
    if (img) img.value = '';
    const wrap = document.getElementById('ch-prev-wrap');
    if (wrap) wrap.style.display = 'none';
    const pv = document.getElementById('ch-prev');
    if (pv) pv.src = '';
    const f = document.getElementById('ch-file');
    if (f) f.value = '';
}

function chargePreviewFromUrl() {
    const url = (document.getElementById('ch-img')?.value || '').trim();
    const wrap = document.getElementById('ch-prev-wrap');
    const pv = document.getElementById('ch-prev');
    if (!wrap || !pv) return;
    if (!url) { wrap.style.display = 'none'; pv.src = ''; return; }
    pv.src = url;
    wrap.style.display = '';
}

function wireChargeImageControls() {
    const dz = document.getElementById('ch-drop');
    const input = document.getElementById('ch-file');
    const urlInput = document.getElementById('ch-img');
    if (!dz || !input || !urlInput) return;
    wireDropZone(dz, input, async (files) => {
        try {
            dz.style.opacity = '0.7';
            const url = await uploadImageFile(files[0]);
            urlInput.value = url;
            chargePreviewFromUrl();
            flash('Image uploaded.');
        } catch (e) {
            flash((e && e.detail) ? e.detail : 'Upload failed.');
        } finally {
            dz.style.opacity = '';
        }
    });
}

function clearChargeForm() {
    const ids = ['ch-id', 'ch-sec', 'ch-title', 'ch-amt', 'ch-due', 'ch-year', 'ch-img', 'ch-desc'];
    ids.forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    const t = document.getElementById('ch-term'); if (t) t.value = '';
    const a = document.getElementById('ch-active'); if (a) a.checked = true;
    const p = document.getElementById('ch-pub'); if (p) p.checked = true;
    const del = document.getElementById('ch-del'); if (del) del.style.display = 'none';
    clearChargeImage();
}

async function openChargeEdit(id) {
    const c = await API.fetch(`/class-charges/${id}/`);
    document.getElementById('ch-id').value = c.id;
    const cls = document.getElementById('ch-class'); if (cls) cls.value = String(c.school_class || '');
    document.getElementById('ch-sec').value = c.section || '';
    document.getElementById('ch-title').value = c.title || '';
    document.getElementById('ch-amt').value = c.amount || '';
    document.getElementById('ch-due').value = c.due_date || '';
    document.getElementById('ch-year').value = c.academic_year || '';
    const t = document.getElementById('ch-term'); if (t) t.value = c.term_number ? String(c.term_number) : '';
    document.getElementById('ch-desc').value = c.description || '';
    const img = document.getElementById('ch-img'); if (img) img.value = c.image_url || '';
    const a = document.getElementById('ch-active'); if (a) a.checked = !!c.is_active;
    const p = document.getElementById('ch-pub'); if (p) p.checked = !!c.is_published;
    const del = document.getElementById('ch-del'); if (del) del.style.display = 'inline-flex';
    wireChargeImageControls();
    chargePreviewFromUrl();
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

async function saveCharge() {
    const id = document.getElementById('ch-id')?.value || '';
    const school_class = document.getElementById('ch-class')?.value || '';
    const section = (document.getElementById('ch-sec')?.value || '').trim().toUpperCase() || null;
    const title = (document.getElementById('ch-title')?.value || '').trim();
    const amount = Number(document.getElementById('ch-amt')?.value || 0);
    const due_date = (document.getElementById('ch-due')?.value || '').trim() || null;
    const academic_year = (document.getElementById('ch-year')?.value || '').trim();
    const term_number = (document.getElementById('ch-term')?.value || '').trim();
    const description = (document.getElementById('ch-desc')?.value || '').trim() || null;
    const image_url = (document.getElementById('ch-img')?.value || '').trim() || null;
    const is_active = !!document.getElementById('ch-active')?.checked;
    const is_published = !!document.getElementById('ch-pub')?.checked;

    if (!school_class) { flash('Select a class.'); return; }
    if (!title) { flash('Title required.'); return; }
    if (!(amount >= 0)) { flash('Amount must be a number.'); return; }

    const payload = {
        school_class: parseInt(school_class, 10),
        section,
        title,
        amount,
        due_date,
        academic_year: academic_year ? parseInt(academic_year, 10) : null,
        term_number: term_number ? parseInt(term_number, 10) : null,
        description,
        image_url,
        is_active,
        is_published,
    };
    if (id) await API.fetch(`/class-charges/${id}/`, { method: 'PATCH', body: JSON.stringify(payload) });
    else await API.fetch('/class-charges/', { method: 'POST', body: JSON.stringify(payload) });
    flash('Charge saved.');
    loadPage('charges');
}

async function deleteCharge() {
    const id = document.getElementById('ch-id')?.value || '';
    if (!id) return;
    if (!confirm('Delete this charge?')) return;
    await API.fetch(`/class-charges/${id}/`, { method: 'DELETE' });
    flash('Charge deleted.');
    loadPage('charges');
}

function clearEventForm() {
    const ids = ['ev-id', 'ev-title', 'ev-start', 'ev-end', 'ev-aud', 'ev-img', 'ev-desc'];
    ids.forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    const tpl = document.getElementById('ev-tpl'); if (tpl) tpl.value = '';
    const pub = document.getElementById('ev-pub'); if (pub) pub.checked = true;
    clearEventImage();
    const del = document.getElementById('ev-del');
    if (del) del.style.display = 'none';
}

function openEventAdd() {
    clearEventForm();
    // Prefill start date.
    const st = document.getElementById('ev-start');
    if (st && !st.value) st.value = todayISO();
}

async function openEventEdit(id) {
    const e = await API.fetch(`/events/${id}/`);
    document.getElementById('ev-id').value = e.id;
    document.getElementById('ev-title').value = e.title || '';
    document.getElementById('ev-start').value = e.start_date || '';
    document.getElementById('ev-end').value = e.end_date || '';
    document.getElementById('ev-aud').value = (e.audience_roles && e.audience_roles.length) ? e.audience_roles.join(',') : '';
    const tpl = document.getElementById('ev-tpl'); if (tpl) tpl.value = '';
    if (document.getElementById('ev-img')) document.getElementById('ev-img').value = e.image_url || '';
    document.getElementById('ev-desc').value = e.description || '';
    document.getElementById('ev-pub').checked = !!e.is_published;
    const del = document.getElementById('ev-del');
    if (del) del.style.display = 'inline-flex';
    wireEventImageControls();
    eventPreviewFromUrl();
}

async function saveEvent() {
    const id = document.getElementById('ev-id').value;
    const title = document.getElementById('ev-title').value.trim();
    const start_date = document.getElementById('ev-start').value;
    const end_date = document.getElementById('ev-end').value || null;
    const audience_roles = (document.getElementById('ev-aud').value || '').split(',').map(s => s.trim()).filter(Boolean);
    const image_url = (document.getElementById('ev-img')?.value || '').trim() || null;
    const description = document.getElementById('ev-desc').value.trim();
    const is_published = document.getElementById('ev-pub').checked;
    if (!title || !start_date) { flash('Title and start date are required.'); return; }
    const payload = { title, start_date, end_date, audience_roles, image_url, description, is_published };
    if (id) await API.fetch(`/events/${id}/`, { method: 'PATCH', body: JSON.stringify(payload) });
    else await API.fetch('/events/', { method: 'POST', body: JSON.stringify(payload) });
    flash('Event saved.');
    loadPage('events');
}

async function createEventFromTemplate() {
    const template_id = (document.getElementById('ev-tpl')?.value || '').trim();
    if (!template_id) { flash('Choose a published template first.'); return; }
    const start_date = (document.getElementById('ev-start')?.value || '').trim();
    if (!start_date) { flash('Start date is required for template-based events.'); return; }
    const payload = {
        template_id,
        title: (document.getElementById('ev-title')?.value || '').trim() || undefined,
        start_date,
        end_date: (document.getElementById('ev-end')?.value || '').trim() || null,
        audience_roles: ((document.getElementById('ev-aud')?.value || '').trim()).split(',').map(s => s.trim()).filter(Boolean),
        image_url: (document.getElementById('ev-img')?.value || '').trim() || null,
        description: (document.getElementById('ev-desc')?.value || '').trim() || undefined,
        is_published: !!document.getElementById('ev-pub')?.checked,
    };
    try {
        await API.fetch('/events/from-template/', { method: 'POST', body: JSON.stringify(payload) });
        flash('Event created from template.');
        loadPage('events');
    } catch (e) {
        flash((e && e.detail) ? e.detail : 'Failed to create event from template.');
    }
}

async function deleteEvent() {
    const id = document.getElementById('ev-id').value;
    if (!id) return;
    if (!confirm('Delete this event?')) return;
    await API.fetch(`/events/${id}/`, { method: 'DELETE' });
    flash('Event deleted.');
    loadPage('events');
}

function clearEventImage() {
    const img = document.getElementById('ev-img');
    if (img) img.value = '';
    const wrap = document.getElementById('ev-prev-wrap');
    if (wrap) wrap.style.display = 'none';
    const pv = document.getElementById('ev-prev');
    if (pv) pv.src = '';
    const f = document.getElementById('ev-file');
    if (f) f.value = '';
}

function clearExamFile() {
    const u = document.getElementById('ex-file-url');
    if (u) u.value = '';
    const w = document.getElementById('ex-file-wrap');
    if (w) w.style.display = 'none';
    const l = document.getElementById('ex-file-link');
    if (l) l.href = '#';
    const f = document.getElementById('ex-file');
    if (f) f.value = '';
}

function wireExamUpload() {
    const dz = document.getElementById('ex-drop');
    const input = document.getElementById('ex-file');
    const urlHidden = document.getElementById('ex-file-url');
    const wrap = document.getElementById('ex-file-wrap');
    const link = document.getElementById('ex-file-link');
    if (!dz || !input || !urlHidden || !wrap || !link) return;
    wireDropZone(dz, input, async (files) => {
        try {
            dz.style.opacity = '0.7';
            const url = await uploadDocFile(files[0]);
            urlHidden.value = url;
            link.href = url;
            wrap.style.display = '';
            flash('File uploaded.');
        } catch (e) {
            flash((e && e.detail) ? e.detail : 'Upload failed.');
        } finally {
            dz.style.opacity = '';
        }
    });
}

async function saveExam() {
    const title = (document.getElementById('ex-title')?.value || '').trim();
    const description = (document.getElementById('ex-desc')?.value || '').trim() || null;
    const school_class = (document.getElementById('ex-class')?.value || '').trim() || null;
    const section = (document.getElementById('ex-sec')?.value || '').trim().toUpperCase();
    const subject = (document.getElementById('ex-subj')?.value || '').trim() || null;
    const file_url = (document.getElementById('ex-file-url')?.value || '').trim();
    if (!title || !file_url) { flash('Title and file are required.'); return; }
    const payload = { title, description, file_url };
    if (school_class) payload.school_class = school_class;
    if (section) payload.section = section;
    if (subject) payload.subject = subject;
    await API.fetch('/exam-papers/', { method: 'POST', body: JSON.stringify(payload) });
    flash('Exam saved (draft). Submit it to Reception when ready.');
    loadPage('exams');
}

function wireProfilePhotoUpload() {
    const dz = document.getElementById('me-photo-drop');
    const input = document.getElementById('me-photo-file');
    const urlInput = document.getElementById('me-photo');
    if (!dz || !input || !urlInput) return;
    wireDropZone(dz, input, async (files) => {
        try {
            dz.style.opacity = '0.7';
            const url = await uploadImageFile(files[0]);
            urlInput.value = url;
            flash('Profile photo uploaded. Click Save Profile to apply.');
        } catch (e) {
            flash((e && e.detail) ? e.detail : 'Upload failed.');
        } finally {
            dz.style.opacity = '';
        }
    });
}

function wireBrandingLogoUpload() {
    const dz = document.getElementById('ss-b-logo-drop');
    const input = document.getElementById('ss-b-logo-file');
    const urlInput = document.getElementById('ss-b-logo');
    if (!dz || !input || !urlInput) return;
    wireDropZone(dz, input, async (files) => {
        try {
            dz.style.opacity = '0.7';
            const url = await uploadImageFile(files[0]);
            urlInput.value = url;
            flash('Logo uploaded. Click Save System Settings to apply.');
        } catch (e) {
            flash((e && e.detail) ? e.detail : 'Upload failed.');
        } finally {
            dz.style.opacity = '';
        }
    });
}

async function submitExam(id) {
    await API.fetch(`/exam-papers/${id}/submit/`, { method: 'POST', body: JSON.stringify({}) });
    flash('Submitted to Reception.');
    loadPage('exams');
}

async function markExamPrinted(id) {
    await API.fetch(`/exam-papers/${id}/mark-printed/`, { method: 'POST', body: JSON.stringify({}) });
    flash('Marked printed.');
    loadPage('printdesk');
}

function eventPreviewFromUrl() {
    const url = (document.getElementById('ev-img')?.value || '').trim();
    const wrap = document.getElementById('ev-prev-wrap');
    const pv = document.getElementById('ev-prev');
    if (!wrap || !pv) return;
    if (!url) { wrap.style.display = 'none'; pv.src = ''; return; }
    pv.src = url;
    wrap.style.display = '';
}

function wireEventImageControls() {
    const dz = document.getElementById('ev-drop');
    const input = document.getElementById('ev-file');
    const urlInput = document.getElementById('ev-img');
    if (!dz || !input || !urlInput) return;
    wireDropZone(dz, input, async (files) => {
        try {
            dz.style.opacity = '0.7';
            const url = await uploadImageFile(files[0]);
            urlInput.value = url;
            eventPreviewFromUrl();
            flash('Image uploaded.');
        } catch (e) {
            flash((e && e.detail) ? e.detail : 'Upload failed.');
        } finally {
            dz.style.opacity = '';
        }
    });
    urlInput.addEventListener('input', () => eventPreviewFromUrl());
}
