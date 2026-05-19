
const API = {
    csrfToken: null,
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
        if (!headers['Content-Type'] && !headers['content-type']) headers['Content-Type'] = 'application/json';

        if (!isSafe) {
            const csrf = await this.getCsrfToken();
            if (csrf) headers['X-CSRFToken'] = csrf;
        }

        const response = await fetch('/api' + url, {
            ...options,
            credentials: 'same-origin',
            headers,
        });

        // If CSRF token/cookie got out of sync (common when switching localhost/127.0.0.1),
        // refresh token once and retry the request.
        if (response.status === 403 && !_retried) {
            const text = await response.clone().text().catch(() => '');
            if ((text || '').toLowerCase().includes('csrf')) {
                await this.refreshCsrfToken();
                return this.fetch(url, options, true);
            }
        }

        if (!response.ok) {
            let payload = null;
            try { payload = await response.json(); } catch { payload = { detail: await response.text() }; }
            payload = (payload && typeof payload === 'object') ? payload : { detail: String(payload || '') };
            payload.status = response.status;
            throw payload;
        }
        if (response.status === 204) return null;
        return response.json();
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

const NAV = {
    superadmin: [
        { section: 'Overview' },
        { label: 'Dashboard', icon: 'D', page: 'dashboard' },
        { section: 'Administration' },
        { label: 'User Accounts', icon: 'U', page: 'users' },
        { label: 'Classes', icon: 'C', page: 'classes' },
        { label: 'Teachers', icon: 'T', page: 'teachers' },
        { label: 'Students', icon: 'S', page: 'students' },
        { section: 'Academic' },
        { label: 'Promotions', icon: 'P', page: 'promotions' },
        { label: 'Terms', icon: 'R', page: 'terms' },
        { label: 'Report Cards', icon: 'RC', page: 'reportcards' },
        { label: 'Timetable', icon: 'Ã°Å¸â€”â€œÃ¯Â¸Â', page: 'timetable' },
        { label: 'Teacher Attendance', icon: 'TA', page: 'teacher_attendance' },
        { section: 'School' },
        { label: 'Events', icon: 'Ã°Å¸â€œ...', page: 'events' },
        { label: 'Announcements', icon: 'Ã°Å¸â€œÂ¢', page: 'announcements' },
        { section: 'Finance' },
        { label: 'Fees', icon: 'F', page: 'fees' },
        { label: 'Payments', icon: '$', page: 'finance' },
        { section: 'System' },
        { label: 'Audit Logs', icon: 'L', page: 'auditlogs' },
        { label: 'API Credentials', icon: 'K', page: 'credentials' },
        { label: 'Security', icon: 'Ã°Å¸â€â€™', page: 'security' },
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
        { label: 'Terms', icon: 'R', page: 'terms' },
        { label: 'Report Cards', icon: 'RC', page: 'reportcards' },
        { label: 'Timetable', icon: 'Ã°Å¸â€”â€œÃ¯Â¸Â', page: 'timetable' },
        { label: 'Teacher Attendance', icon: 'TA', page: 'teacher_attendance' },
        { section: 'School' },
        { label: 'Events', icon: 'Ã°Å¸â€œ...', page: 'events' },
        { label: 'Announcements', icon: 'Ã°Å¸â€œÂ¢', page: 'announcements' },
        { section: 'Finance' },
        { label: 'Fees', icon: 'F', page: 'fees' },
        { label: 'Payments', icon: '$', page: 'finance' },
        { section: 'System' },
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
        { label: 'Terms', icon: 'R', page: 'terms' },
        { label: 'Report Cards', icon: 'RC', page: 'reportcards' },
        { label: 'Timetable', icon: 'Ã°Å¸â€”â€œÃ¯Â¸Â', page: 'timetable' },
        { label: 'Teacher Attendance', icon: 'TA', page: 'teacher_attendance' },
        { section: 'School' },
        { label: 'Events', icon: 'Ã°Å¸â€œ...', page: 'events' },
        { label: 'Announcements', icon: 'Ã°Å¸â€œÂ¢', page: 'announcements' },
        { section: 'Finance' },
        { label: 'Fees', icon: 'F', page: 'fees' },
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
        { label: 'Events', icon: 'Ã°Å¸â€œ...', page: 'events' },
        { label: 'Announcements', icon: 'Ã°Å¸â€œÂ¢', page: 'announcements' },
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
        { label: 'Timetable', icon: 'Ã°Å¸â€”â€œÃ¯Â¸Â', page: 'timetable' },
        { label: 'Promotions', icon: 'P', page: 'promotions' },
        { label: 'Terms', icon: 'R', page: 'terms' },
        { label: 'Report Cards', icon: 'RC', page: 'reportcards' },
        { section: 'School' },
        { label: 'Events', icon: 'Ã°Å¸â€œ...', page: 'events' },
        { label: 'Announcements', icon: 'Ã°Å¸â€œÂ¢', page: 'announcements' },
        { section: 'System' },
        { label: 'Settings', icon: 'S', page: 'settings' },
    ],
    bursar: [{ section: 'Finance' }, { label: 'Fees', icon: 'F', page: 'fees' }, { label: 'Payments', icon: '$', page: 'finance' }, { label: 'Settings', icon: 'S', page: 'settings' }],
    teacher: [{ section: 'Overview' }, { label: 'My Dashboard', icon: 'D', page: 'dashboard' }, { label: 'My Timetable', icon: 'Ã°Å¸â€”â€œÃ¯Â¸Â', page: 'timetable' }, { label: 'Events', icon: 'Ã°Å¸â€œ...', page: 'events' }, { label: 'Announcements', icon: 'Ã°Å¸â€œÂ¢', page: 'announcements' }, { label: 'Settings', icon: 'S', page: 'settings' }],
    parent: [{ section: 'Home' }, { label: 'Child Dashboard', icon: 'D', page: 'dashboard' }, { label: 'Timetable', icon: 'Ã°Å¸â€”â€œÃ¯Â¸Â', page: 'timetable' }, { label: 'Events', icon: 'Ã°Å¸â€œ...', page: 'events' }, { label: 'Announcements', icon: 'Ã°Å¸â€œÂ¢', page: 'announcements' }, { label: 'Settings', icon: 'S', page: 'settings' }],
    student: [{ section: 'School' }, { label: 'My Dashboard', icon: 'D', page: 'dashboard' }, { label: 'Timetable', icon: 'Ã°Å¸â€”â€œÃ¯Â¸Â', page: 'timetable' }, { label: 'Events', icon: 'Ã°Å¸â€œ...', page: 'events' }, { label: 'Announcements', icon: 'Ã°Å¸â€œÂ¢', page: 'announcements' }, { label: 'Settings', icon: 'S', page: 'settings' }],
    reception: [
        { section: 'Overview' },
        { label: 'Dashboard', icon: 'D', page: 'dashboard' },
        { label: 'Students', icon: 'S', page: 'students' },
        { label: 'Report Cards', icon: 'RC', page: 'reportcards' },
        { label: 'Timetable', icon: 'Ã°Å¸â€”â€œÃ¯Â¸Â', page: 'timetable' },
        { label: 'Teacher Attendance', icon: 'TA', page: 'teacher_attendance' },
        { label: 'Events', icon: 'Ã°Å¸â€œ...', page: 'events' },
        { label: 'Announcements', icon: 'Ã°Å¸â€œÂ¢', page: 'announcements' },
        { section: 'System' },
        { label: 'Settings', icon: 'S', page: 'settings' }
    ]
};

document.addEventListener('DOMContentLoaded', async () => {
    // Bind Enter key reliably (avoid full-page reloads).
    try {
        const onEnter = (el, fn) => {
            if (!el) return;
            el.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    fn();
                }
            });
        };
        onEnter(document.getElementById('login-user'), () => document.getElementById('login-pass')?.focus());
        onEnter(document.getElementById('login-pass'), doLogin);
        onEnter(document.getElementById('fp-identifier'), requestPasswordReset);
        onEnter(document.getElementById('fp-otp'), confirmPasswordReset);
        onEnter(document.getElementById('fp-new-pass'), confirmPasswordReset);
        onEnter(document.getElementById('fp-confirm-pass'), confirmPasswordReset);
    } catch {}

    // Prime CSRF token early so the first POST/PATCH/DELETE works reliably.
    try { await API.refreshCsrfToken(); } catch {}

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
});

async function doLogin() {
    const identifier = document.getElementById('login-user').value.trim();
    const password = document.getElementById('login-pass').value;
    setLoginError('');
    try {
        const btn = document.getElementById('login-btn');
        if (btn) { btn.disabled = true; btn.textContent = 'Signing in...'; }
        const res = await API.fetch('/auth/login/', { method: 'POST', body: JSON.stringify({ identifier, password }) });
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
    if (!new_password || new_password.length < 8) { setLoginError('Password must be at least 8 characters.'); return; }
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
    document.getElementById('login-screen').classList.remove('show');
    document.getElementById('app').classList.add('show');
    document.getElementById('splash').style.display = 'none';
    document.getElementById('topbar-name').textContent = currentUser.first_name || currentUser.username;
    document.getElementById('topbar-ava').textContent = (currentUser.profile && currentUser.profile.avatar) || 'AD';
    buildSidebar();
    loadPage('dashboard');
    refreshTermChip();
    maybeHandleTeacherQR();
    refreshNotificationsBadge();
}

function buildSidebar() {
    const nav = document.getElementById('sb-nav-content');
    nav.innerHTML = '';
    const role = (currentUser.profile && currentUser.profile.role) || 'superadmin';
    (NAV[role] || NAV.superadmin).forEach(item => {
        if (item.section) nav.innerHTML += `<div class="sb-section">${item.section}</div>`;
        else nav.innerHTML += `<div class="sb-link" onclick="loadPage('${item.page}', this, '${item.label}')"><span class="sb-icon">${item.icon}</span><span class="sb-text">${item.label}</span></div>`;
    });
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

    const main = document.getElementById('main-content');
    try {
    if (page === 'dashboard') {
        const role = (currentUser.profile && currentUser.profile.role) || 'superadmin';

        if (role === 'superadmin') {
            const [students, teachers, classes, payments, creds] = await Promise.all([
              API.fetch('/students/'),
              API.fetch('/teachers/'),
              API.fetch('/classes/'),
              API.fetch('/payments/'),
              API.fetch('/api-credentials/'),
            ]);
            const total = (payments || []).reduce((sum, p) => sum + Number(p.amount || 0), 0);
            const activeCreds = (creds || []).filter(c => c.is_active).length;
            main.innerHTML = `
              <div class="page">
                <div class="page-hero"><div class="page-title">Super Admin Dashboard</div></div>
                <div class="stats stats-4">
                  <div class="stat-card"><div class="stat-num">${students.length}</div><div class="stat-label">Students</div><div class="stat-accent red"></div></div>
                  <div class="stat-card"><div class="stat-num">${teachers.length}</div><div class="stat-label">Teachers</div><div class="stat-accent gold"></div></div>
                  <div class="stat-card"><div class="stat-num">${classes.length}</div><div class="stat-label">Classes</div><div class="stat-accent blue"></div></div>
                  <div class="stat-card"><div class="stat-num">UGX ${fmt(total.toFixed(0))}</div><div class="stat-label">Payments Total</div><div class="stat-accent green"></div></div>
                </div>
                <div class="g21">
                  <div class="card">
                    <div class="card-head"><div class="card-title">Control Center</div></div>
                    <div class="card-body">
                      <div class="qa-grid">
                        <button class="qa-btn" onclick="loadPage('users', null, 'User Accounts')"><span class="qi">Ã°Å¸â€˜Â¤</span><span class="ql">Users</span></button>
                        <button class="qa-btn" onclick="loadPage('credentials', null, 'API Credentials')"><span class="qi">Ã°Å¸â€â€˜</span><span class="ql">API Keys</span></button>
                        <button class="qa-btn" onclick="loadPage('auditlogs', null, 'Audit Logs')"><span class="qi">Ã°Å¸â€œâ€¹</span><span class="ql">Audit Logs</span></button>
                        <button class="qa-btn" onclick="loadPage('finance', null, 'Payments')"><span class="qi">Ã°Å¸â€™Âµ</span><span class="ql">Payments</span></button>
                      </div>
                      <div style="margin-top:12px;font-size:12px;color:var(--99)">Active credentials: <strong style="color:var(--1a)">${activeCreds}</strong></div>
                    </div>
                  </div>
                  <div class="card">
                    <div class="card-head"><div class="card-title">Quick Health</div></div>
                    <div class="card-body">
                      <div class="ri"><div class="ri-info"><div class="rn">Security</div><div class="rd">Audit logs enabled, superuser-only access</div></div><div class="ri-end"><span class="badge green">OK</span></div></div>
                      <div class="ri"><div class="ri-info"><div class="rn">Payments</div><div class="rd">Manual entry enabled</div></div><div class="ri-end"><span class="badge green">OK</span></div></div>
                      <div class="ri"><div class="ri-info"><div class="rn">Backups</div><div class="rd">Not configured</div></div><div class="ri-end"><span class="badge">TODO</span></div></div>
                    </div>
                  </div>
                </div>
              </div>`;
            return;
        }

        if (['admin','headteacher','deputy','dos'].includes(role)) {
            const [students, teachers, classes, events] = await Promise.all([
                API.fetch('/students/'),
                API.fetch('/teachers/'),
                API.fetch('/classes/'),
                API.fetch('/events/').catch(() => []),
            ]);
            main.innerHTML = `
              <div class="page">
                <div class="page-hero"><div class="page-title">${role === 'headteacher' ? 'Headteacher Dashboard' : role === 'dos' ? 'DOS Dashboard' : role === 'deputy' ? 'Deputy Headteacher Dashboard' : 'Admin Dashboard'}</div></div>
                <div class="stats stats-4">
                  <div class="stat-card"><div class="stat-num">${students.length}</div><div class="stat-label">Students</div><div class="stat-accent red"></div></div>
                  <div class="stat-card"><div class="stat-num">${teachers.length}</div><div class="stat-label">Teachers</div><div class="stat-accent gold"></div></div>
                  <div class="stat-card"><div class="stat-num">${classes.length}</div><div class="stat-label">Classes</div><div class="stat-accent blue"></div></div>
                  <div class="stat-card"><div class="stat-num">Ready</div><div class="stat-label">Promotions / Reports</div><div class="stat-accent green"></div></div>
                </div>
                ${(!classes || classes.length === 0) ? `<div class="card" style="border-left:4px solid var(--rd)"><div class="card-body"><strong>No classes configured.</strong> Add class levels before registering students. <button class="btn btn-xs btn-ghost" onclick="loadPage('classes',null,'Classes')">Open Classes</button></div></div><div style="height:12px"></div>` : ''}
                <div class="card"><div class="card-head"><div class="card-title">Quick Actions</div></div>
                  <div class="card-body"><div class="qa-grid">
                    <button class="qa-btn" onclick="loadPage('students', null, 'Students')"><span class="qi">Ã°Å¸â€˜Â§</span><span class="ql">Students</span></button>
                    <button class="qa-btn" onclick="loadPage('teachers', null, 'Teachers')"><span class="qi">Ã°Å¸â€˜Â¨Ã¢â‚¬ÂÃ°Å¸ÂÂ«</span><span class="ql">Teachers</span></button>
                    <button class="qa-btn" onclick="loadPage('promotions', null, 'Promotions')"><span class="qi">Ã°Å¸Å½â€œ</span><span class="ql">Promotions</span></button>
                    <button class="qa-btn" onclick="loadPage('terms', null, 'Terms')"><span class="qi">Ã°Å¸â€”â€œ</span><span class="ql">Terms</span></button>
                  </div></div>
                </div>
                <div style="height:12px"></div>
                <div class="card"><div class="card-head"><div class="card-title">Upcoming Events</div><button class="btn btn-xs btn-ghost" onclick="loadPage('events',null,'Events')">Manage</button></div><div class="card-body">${(events || []).filter(e => e.is_published).slice(0, 3).map(e => `<div class="ri"><div class="ri-info"><div class="rn">${e.title}</div><div class="rd">${e.start_date}${e.end_date ? ' Ã¢â€ â€™ ' + e.end_date : ''}</div></div></div>`).join('') || '<div style="color:var(--99)">No events posted yet.</div>'}</div></div>
              </div>`;
            return;
        }

        if (role === 'parent') {
            const kids = await API.fetch('/students/mine/');
            const list = (kids || []).map(s => `<div class="ri"><div class="ri-info"><div class="rn">${s.first_name} ${s.last_name}</div><div class="rd">${s.student_id} Ã‚· ${s.current_class_level || '-' }${s.section || ''}</div></div></div>`).join('');
            main.innerHTML = `
              <div class="page">
                <div class="page-hero"><div class="page-title">Parent Dashboard</div></div>
                <div class="card"><div class="card-head"><div class="card-title">My Children</div></div><div class="card-body">${list || 'No linked students found.'}</div></div>
              </div>`;
            return;
        }

        if (role === 'bursar') {
            const activeTerm = await API.fetch('/terms/').catch(() => null);
            const defYear = (activeTerm && activeTerm.academic_year) ? activeTerm.academic_year : new Date().getFullYear();
            const defTerm = (activeTerm && activeTerm.term_number) ? activeTerm.term_number : 1;
            const [payments, invoices] = await Promise.all([
                API.fetch('/payments/'),
                API.fetch(`/invoices/?year=${encodeURIComponent(defYear)}&term=${encodeURIComponent(defTerm)}`).catch(() => []),
            ]);
            const total = (payments || []).reduce((sum, p) => sum + Number(p.amount || 0), 0);
            const due = (invoices || []).reduce((sum, i) => sum + Number(i.amount_due || 0), 0);
            const paid = (invoices || []).reduce((sum, i) => sum + Number(i.amount_paid || 0), 0);
            const bal = Math.max(due - paid, 0);
            main.innerHTML = `
              <div class="page">
                <div class="page-hero"><div class="page-title">Finance Dashboard</div></div>
                <div class="stats stats-4">
                  <div class="stat-card"><div class="stat-num">UGX ${fmt(total.toFixed(0))}</div><div class="stat-label">Payments Total</div><div class="stat-accent gold"></div></div>
                  <div class="stat-card"><div class="stat-num">${(payments||[]).length}</div><div class="stat-label">Payment Records</div><div class="stat-accent red"></div></div>
                  <div class="stat-card"><div class="stat-num">UGX ${fmt(bal.toFixed(0))}</div><div class="stat-label">Outstanding (T${defTerm}/${defYear})</div><div class="stat-accent blue"></div></div>
                  <div class="stat-card"><div class="stat-num">${(invoices||[]).filter(i=>i.status!=='paid').length}</div><div class="stat-label">Unpaid/Partial Invoices</div><div class="stat-accent green"></div></div>
                </div>
                <div class="card"><div class="card-head"><div class="card-title">Quick Actions</div></div>
                  <div class="card-body"><div class="qa-grid">
                    <button class="qa-btn" onclick="loadPage('finance', null, 'Payments')"><span class="qi">Ã°Å¸â€™Âµ</span><span class="ql">Record Payment</span></button>
                    <button class="qa-btn" onclick="loadPage('finance', null, 'Payments')"><span class="qi">Ã°Å¸â€Å½</span><span class="ql">Search History</span></button>
                    <button class="qa-btn" onclick="loadPage('settings', null, 'Settings')"><span class="qi">Ã¢Å¡â„¢Ã¯Â¸Â</span><span class="ql">Settings</span></button>
                    <button class="qa-btn" onclick="loadPage('fees', null, 'Fees')"><span class="qi">Ã°Å¸â€™Â³</span><span class="ql">Fee Structure</span></button>
                  </div></div>
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
                <div class="stats stats-4">
                  <div class="stat-card"><div class="stat-num">${students.length}</div><div class="stat-label">Students</div><div class="stat-accent red"></div></div>
                  <div class="stat-card"><div class="stat-num">${classes.length}</div><div class="stat-label">Classes</div><div class="stat-accent blue"></div></div>
                  <div class="stat-card"><div class="stat-num">Reports</div><div class="stat-label">Print individual reports</div><div class="stat-accent gold"></div></div>
                  <div class="stat-card"><div class="stat-num">TT</div><div class="stat-label">Timetable access</div><div class="stat-accent green"></div></div>
                </div>
                <div class="card"><div class="card-head"><div class="card-title">Quick Actions</div></div>
                  <div class="card-body"><div class="qa-grid">
                    <button class="qa-btn" onclick="loadPage('students', null, 'Students')"><span class="qi">Ã°Å¸â€˜Â§</span><span class="ql">Find Student</span></button>
                    <button class="qa-btn" onclick="loadPage('reportcards', null, 'Report Cards')"><span class="qi">Ã°Å¸â€œâ€ž</span><span class="ql">Print Reports</span></button>
                    <button class="qa-btn" onclick="loadPage('timetable', null, 'Timetable')"><span class="qi">Ã°Å¸â€”â€œÃ¯Â¸Â</span><span class="ql">Timetable</span></button>
                    <button class="qa-btn" onclick="loadPage('settings', null, 'Settings')"><span class="qi">Ã¢Å¡â„¢Ã¯Â¸Â</span><span class="ql">Settings</span></button>
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
          <td style="font-size:12px;color:var(--66)">${[c.teacher_a, c.teacher_b].filter(Boolean).join(' Ã‚· ') || '-'}</td>
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
        let rows = (users || []).map(u => `<tr>
          <td>${u.username}</td>
          <td>${u.first_name} ${u.last_name}</td>
          <td><span class="badge">${u.profile ? u.profile.role : 'N/A'}</span></td>
          <td>
            <button class="btn btn-xs btn-ghost" onclick="openUserEdit(${u.id})">Edit</button>
            ${canDelete ? `<button class="btn btn-xs btn-ghost" onclick='deleteUser(${u.id}, ${JSON.stringify((u.username || "").toString())})'>Delete</button>` : ''}
          </td>
        </tr>`).join('');
        main.innerHTML = `
            <div class="page">
                <div class="page-hero"><div class="page-title">User Accounts</div><button class="btn btn-primary" onclick="openUserAdd()">+ Create New Account</button></div>
                <div class="card"><div class="card-body no-pad"><table class="tbl"><thead><tr><th>Username</th><th>Name</th><th>Role</th><th></th></tr></thead><tbody>${rows}</tbody></table></div></div>
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
                ${canEdit ? `<button class="btn btn-xs btn-ghost" onclick="openStudentEdit(${s.id})">Edit</button>` : ''}
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
        const canEdit = ['superadmin', 'admin'].includes(role);
        const canDelete = role === 'superadmin';
        let rows = (teachers || []).map(t => `<tr>
          <td>${t.first_name} ${t.last_name}</td>
          <td>${t.employee_id}</td>
          <td>${t.assigned_class || '-'}</td>
          <td>${t.phone}</td>
          <td>${t.email}</td>
          <td>
            ${canEdit ? `<button class="btn btn-xs btn-ghost" onclick="openTeacherEdit(${t.id})">Edit</button>` : ''}
            ${canDelete ? `<button class="btn btn-xs btn-ghost" onclick="deleteTeacher(${t.id})">Delete</button>` : ''}
          </td>
        </tr>`).join('');
        main.innerHTML = `
            <div class="page">
                <div class="page-hero"><div class="page-title">Teacher Management</div>${canEdit ? `<button class="btn btn-primary" onclick="openTeacherAdd()">+ Register Teacher</button>` : ''}</div>
                <div class="card"><div class="card-body no-pad"><table class="tbl"><thead><tr><th>Name</th><th>ID</th><th>Class</th><th>Phone</th><th>Email</th><th></th></tr></thead><tbody>${rows}</tbody></table></div></div>
            </div>`;
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
        const active = await API.fetch('/terms/').catch(() => null);
        const history = await API.fetch('/terms/history/').catch(() => []);
        const activeHtml = active && active.academic_year ? `<div><strong>Active:</strong> Year ${active.academic_year}, Term ${active.term_number} (${active.start_date} to ${active.end_date})</div>` : `<div><strong>Active:</strong> None</div>`;
        const histRows = Array.isArray(history) ? history.map(t => `<tr><td>${t.academic_year}</td><td>${t.term_number}</td><td>${t.start_date}</td><td>${t.end_date}</td></tr>`).join('') : '';
        main.innerHTML = `
            <div class="page">
                <div class="page-hero"><div class="page-title">Academic Terms</div><button class="btn btn-primary" onclick="openModal('modal-term')">Start New Term</button></div>
                <div class="card"><div class="card-body">${activeHtml}</div></div>
                <div style="height:12px"></div>
                <div class="card"><div class="card-body no-pad">
                  <table class="tbl"><thead><tr><th>Year</th><th>Term</th><th>Start</th><th>End</th></tr></thead><tbody>${histRows}</tbody></table>
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
                    <div class="field" style="margin:0;min-width:240px"><label>Class</label><select class="field-select" id="tt-class">${classOptions}</select></div>
                    <div class="field" style="margin:0;min-width:120px"><label>Section</label><input class="field-input" id="tt-sec" value="A"></div>
                    <div class="field" style="margin:0;min-width:260px"><label>Days (comma)</label><input class="field-input" id="tt-days" value="Mon,Tue,Wed,Thu,Fri"></div>
                    <div class="field" style="margin:0;min-width:320px"><label>Periods (comma)</label><input class="field-input" id="tt-periods" value="1,2,3,4,5,6,7,8"></div>
                    <button class="btn btn-ghost" onclick="ttLoad()">Load</button>
                    <button class="btn btn-primary" onclick="ttSave()">Save</button>
                    <button class="btn btn-ghost" onclick="ttPrint()">Print</button>
                  </div>
                  <div style="height:10px"></div>
                  <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                    <div class="field" style="margin:0;min-width:170px"><label>Auto Times Start</label><input class="field-input" id="tt-auto-start" type="time" value="08:00"></div>
                    <div class="field" style="margin:0;min-width:170px"><label>Minutes / Period</label><input class="field-input" id="tt-auto-dur" type="number" value="40"></div>
                    <button class="btn btn-ghost" onclick="ttAutoFillTimes()">Auto-Fill Times</button>
                    <div style="flex:1"></div>
                    <div class="field" style="margin:0;min-width:240px"><label>Copy From Class</label><select class="field-select" id="tt-copy-class"><option value="">Select...</option>${classOptions}</select></div>
                    <div class="field" style="margin:0;min-width:120px"><label>Copy Section</label><input class="field-input" id="tt-copy-sec" value="A"></div>
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
            await ttLoad();
            return;
        }

        // Read-only view (teacher/parent).
        const [my, classes] = await Promise.all([API.fetch('/timetable/mine/'), API.fetch('/classes/').catch(() => [])]);
        const clsMap = new Map((classes || []).map(c => [c.id, c.level]));
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
                const v = tname ? `${subj}${subj ? '<div class="sub">Teacher: ' + tname + '</div>' : '<div>Teacher: ' + tname + '</div>'}` : subj;
                return `<td class="${isNow ? 'tt-now-cell' : ''}">${v || ''}</td>`;
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
        const today = new Date().toISOString().slice(0, 10);

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
        const items = await API.fetch('/announcements/').catch(() => []);

        const rows = (items || []).slice(0, 120).map(a => {
            const aud = (a.audience_roles && a.audience_roles.length) ? a.audience_roles.join(', ') : 'all';
            const pub = a.is_published ? '<span class="badge green">published</span>' : '<span class="badge">draft</span>';
            const pin = a.is_pinned ? '<span class="badge green">pinned</span>' : '';
            return `<tr>
              <td><strong>${a.title}</strong><div class="sub">${(a.body || '').slice(0, 80)}${(a.body || '').length > 80 ? 'Ã¢â‚¬Â¦' : ''}</div></td>
              <td style="font-size:12px;color:var(--66)">${aud}</td>
              <td>${pub} ${pin}</td>
              <td style="font-size:12px;color:var(--66)">${(a.created_at || '').toString().slice(0, 19).replace('T', ' ')}</td>
              <td>${canEdit ? `<button class="btn btn-xs btn-ghost" onclick="openAnnouncementEdit(${a.id})">Edit</button>` : ''}</td>
            </tr>`;
        }).join('');

        main.innerHTML = `
          <div class="page">
            <div class="page-hero"><div class="page-title">Announcements</div>${canEdit ? `<button class="btn btn-primary" onclick="openAnnouncementAdd()">+ New</button>` : ''}</div>
            ${canEdit ? `
              <div class="card"><div class="card-body">
                <div style="font-weight:900;margin-bottom:8px">Create / Update Announcement</div>
                <input type="hidden" id="an-id" value="">
                <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                  <div class="field" style="margin:0;min-width:260px"><label>Title</label><input class="field-input" id="an-title"></div>
                  <div class="field" style="margin:0;min-width:260px"><label>Audience Roles (comma)</label><input class="field-input" id="an-aud" placeholder="parent,teacher"></div>
                  <div class="field" style="margin:0"><label><input type="checkbox" id="an-pub" checked> Published</label></div>
                  <div class="field" style="margin:0"><label><input type="checkbox" id="an-pin"> Pinned</label></div>
                  <button class="btn btn-primary" onclick="saveAnnouncement()">Save</button>
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
    } else if (page === 'events') {
        const role = (currentUser.profile && currentUser.profile.role) || 'admin';
        const canEdit = ['superadmin', 'admin', 'reception'].includes(role);
        const events = await API.fetch('/events/').catch(() => []);

        const rows = (events || []).slice(0, 80).map(e => {
            const dates = e.end_date ? `${e.start_date} -> ${e.end_date}` : e.start_date;
            const aud = (e.audience_roles && e.audience_roles.length) ? e.audience_roles.join(', ') : 'all';
            return `<tr>
              <td>
                <div style="display:flex;gap:10px;align-items:center">
                  ${e.image_url ? `<div style="width:34px;height:34px;border-radius:10px;overflow:hidden;border:1px solid var(--e);background:#fff;flex-shrink:0"><img alt="" src="${e.image_url}" style="width:34px;height:34px;object-fit:cover"></div>` : `<div style="width:34px;height:34px;border-radius:10px;overflow:hidden;border:1px solid var(--e);background:var(--f0);flex-shrink:0"></div>`}
                  <div><strong>${e.title}</strong><div class="sub">${dates}</div></div>
                </div>
              </td>
              <td style="font-size:12px;color:var(--66)">${aud}</td>
              <td>${e.is_published ? '<span class="badge green">published</span>' : '<span class="badge">draft</span>'}</td>
              <td style="font-size:12px;color:var(--66)">${(e.description || '').slice(0, 60)}${(e.description || '').length > 60 ? '...' : ''}</td>
              <td>
                ${canEdit ? `<button class="btn btn-xs btn-ghost" onclick="openEventEdit(${e.id})">Edit</button>` : ''}
              </td>
            </tr>`;
        }).join('');

        main.innerHTML = `
          <div class="page">
            <div class="page-hero"><div class="page-title">Events</div>${canEdit ? `<button class="btn btn-primary" onclick="openEventAdd()">+ New Event</button>` : ''}</div>
            ${canEdit ? `
              <div class="card"><div class="card-body">
                <div style="font-weight:800;margin-bottom:8px">Create / Update Event</div>
                <input type="hidden" id="ev-id" value="">
                <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                  <div class="field" style="margin:0;min-width:240px"><label>Title</label><input class="field-input" id="ev-title"></div>
                  <div class="field" style="margin:0;min-width:160px"><label>Start Date</label><input class="field-input" id="ev-start" type="date"></div>
                  <div class="field" style="margin:0;min-width:160px"><label>End Date (optional)</label><input class="field-input" id="ev-end" type="date"></div>
                  <div class="field" style="margin:0;min-width:260px"><label>Audience Roles (comma)</label><input class="field-input" id="ev-aud" placeholder="parent,teacher"></div>
                  <div class="field" style="margin:0;min-width:260px"><label>Image URL (optional)</label><input class="field-input" id="ev-img" placeholder="https://..."></div>
                  <div class="field" style="margin:0"><label><input type="checkbox" id="ev-pub" checked> Published</label></div>
                  <button class="btn btn-primary" onclick="saveEvent()">Save</button>
                  <button class="btn btn-ghost" onclick="clearEventForm()">Clear</button>
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
    } else if (page === 'auditlogs') {
        const logs = await API.fetch('/audit-logs/');
        const rows = (logs || []).slice(0, 50).map(l => `<tr><td>${l.timestamp || ''}</td><td>${l.event_type || ''}</td><td>${l.user_username || ''}</td><td>${l.ip_address || ''}</td><td>${l.details || ''}</td></tr>`).join('');
        main.innerHTML = `
            <div class="page">
                <div class="page-hero"><div class="page-title">Audit Logs</div></div>
                <div class="card"><div class="card-body no-pad">
                  <table class="tbl"><thead><tr><th>Time</th><th>Event</th><th>User</th><th>IP</th><th>Details</th></tr></thead><tbody>${rows}</tbody></table>
                </div></div>
            </div>`;
    } else if (page === 'credentials') {
        const creds = await API.fetch('/api-credentials/');
        const rows = (creds || []).map(c => {
            const sid = (c.client_id || '').toString();
            const key = (c.api_key || '').toString();
            const secret = (c.client_secret || '').toString();
            const sidMask = sid ? (sid.length > 10 ? (sid.slice(0, 6) + '...' + sid.slice(-4)) : sid) : '-';
            const keyMask = key ? ('******' + key.slice(-4)) : '-';
            const secMask = secret ? ('******' + secret.slice(-4)) : '-';
            const updated = c.updated_at ? String(c.updated_at).slice(0, 19).replace('T', ' ') : '';
            return `
              <tr>
                <td><strong>${credServiceLabel(c.service_name)}</strong><div class="sub mono">${c.service_name}</div></td>
                <td>${c.is_active ? '<span class="badge green">Active</span>' : '<span class="badge">Inactive</span>'}</td>
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
                    <button class="seg-btn" data-svc="email_smtp" onclick="credPick('email_smtp', this)">Email</button>
                    <button class="seg-btn" data-svc="openai" onclick="credPick('openai', this)">AI Key</button>
                  </div>

                  <div style="height:10px"></div>

                  <div class="field" style="margin:0">
                    <label>Service</label>
                    <select class="field-select" id="cred-service" onchange="credOnServiceChange()">
                      <option value="google_oauth">Google OAuth</option>
                      <option value="mtn_momo">MTN Mobile Money</option>
                      <option value="airtel_money">Airtel Mobile Money</option>
                      <option value="twilio_sms">Twilio SMS</option>
                      <option value="email_smtp">Email SMTP</option>
                      <option value="openai">OpenAI (AI Key)</option>
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
                    <button class="btn btn-ghost" onclick="clearCredentialForm()">Clear</button>
                  </div>
                </div>
              </div>

              <div class="card">
                <div class="card-head"><div class="card-title">Stored Credentials</div><div class="sub">Masked values shown for safety</div></div>
                <div class="card-body no-pad">
                  <div class="tw">
                    <table class="tbl">
                      <thead><tr><th>Service</th><th>Status</th><th>Client ID</th><th>Secret</th><th>API Key</th><th>Updated</th><th>Actions</th></tr></thead>
                      <tbody>${rows}</tbody>
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
          <td>${s.login_time ? new Date(s.login_time).toLocaleString() : ''}</td>
          <td><strong>${s.username || '-'}</strong><div class="sub">${s.user_id || ''}</div></td>
          <td>${s.ip_address || '-'}</td>
          <td style="font-size:12px;color:var(--66)">${(s.user_agent || '').slice(0, 40)}${(s.user_agent || '').length > 40 ? 'Ã¢â‚¬Â¦' : ''}</td>
          <td>
            <button class="btn btn-xs btn-ghost" onclick="terminateSession('${s.session_key}')">Terminate</button>
            <button class="btn btn-xs btn-ghost" onclick="terminateUserSessions(${s.user_id})">Terminate User</button>
          </td>
        </tr>`).join('');

        const userRows = (users || []).slice(0, 120).map(u => `<tr>
          <td><strong>${u.username}</strong></td>
          <td>${(u.profile && u.profile.role) ? u.profile.role : '-'}</td>
          <td style="font-size:12px;color:var(--66)">${(u.profile && u.profile.last_login_ip) ? u.profile.last_login_ip : '-'}</td>
          <td style="font-size:12px;color:var(--66)">${(u.profile && u.profile.last_login_ua) ? (u.profile.last_login_ua.slice(0, 40) + (u.profile.last_login_ua.length > 40 ? 'Ã¢â‚¬Â¦' : '')) : '-'}</td>
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
    } else if (page === 'finance') {
        const activeTerm = await API.fetch('/terms/').catch(() => null);
        const defYear = (activeTerm && activeTerm.academic_year) ? activeTerm.academic_year : new Date().getFullYear();
        const defTerm = (activeTerm && activeTerm.term_number) ? activeTerm.term_number : 1;
        const [payments, students, invoices, classes] = await Promise.all([
            API.fetch('/payments/'),
            API.fetch('/students/'),
            API.fetch(`/invoices/?year=${encodeURIComponent(defYear)}&term=${encodeURIComponent(defTerm)}`).catch(() => []),
            API.fetch('/classes/').catch(() => []),
        ]);
        const invMap = new Map((invoices || []).map(i => [i.student, i]));
        const totalDue = (invoices || []).reduce((s, i) => s + Number(i.amount_due || 0), 0);
        const totalPaid = (invoices || []).reduce((s, i) => s + Number(i.amount_paid || 0), 0);
        const totalBal = Math.max(totalDue - totalPaid, 0);
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
        const rows = (payments || []).slice(0, 60).map(p => `
          <tr>
            <td>${p.received_at ? new Date(p.received_at).toLocaleString() : ''}</td>
            <td><strong>${p.student_name}</strong><div class="sub">${p.student_system_id}</div></td>
            <td style="font-weight:800;color:var(--m)">UGX ${fmt(p.amount)}</td>
            <td>${p.method}</td>
            <td style="font-size:12px;color:var(--66)">${p.reference || '-'}</td>
            <td>${p.received_by_username || '-'}</td>
            <td>${p.status}</td>
            <td>
              <button class="btn btn-xs btn-ghost" onclick="openPaymentEdit(${p.id})">Edit</button>
              ${p.status !== 'reversed' ? `<button class="btn btn-xs btn-ghost" onclick="reversePayment(${p.id})">Reverse</button>` : ''}
              <button class="btn btn-xs btn-ghost" onclick="openStudentHistory(${p.student})">Student</button>
            </td>
          </tr>
        `).join('');
        main.innerHTML = `
          <div class="page">
            <div class="page-hero"><div class="page-title">Payments</div></div>
            ${(!activeTerm || !activeTerm.academic_year) ? `<div class="card" style="border-left:4px solid var(--or)"><div class="card-body"><strong>No active term found.</strong> Payments will still be recorded, but invoice tracking works best after starting a term. <button class="btn btn-xs btn-ghost" onclick="loadPage('terms',null,'Terms')">Start Term</button></div></div><div style="height:12px"></div>` : ''}
            <div class="stats stats-4" style="margin-bottom:12px">
              <div class="stat-card"><div class="stat-num">UGX ${fmt(totalDue.toFixed(0))}</div><div class="stat-label">Total Due (T${defTerm}/${defYear})</div><div class="stat-accent gold"></div></div>
              <div class="stat-card"><div class="stat-num">UGX ${fmt(totalPaid.toFixed(0))}</div><div class="stat-label">Total Paid</div><div class="stat-accent green"></div></div>
              <div class="stat-card"><div class="stat-num">UGX ${fmt(totalBal.toFixed(0))}</div><div class="stat-label">Outstanding</div><div class="stat-accent red"></div></div>
              <div class="stat-card"><div class="stat-num">${(invoices||[]).filter(i => i.status !== 'paid').length}</div><div class="stat-label">Defaulters</div><div class="stat-accent blue"></div></div>
            </div>
            <div class="card"><div class="card-body">
              <div style="font-weight:700;margin-bottom:10px">Manual Payment Entry</div>
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
                <button class="btn btn-primary" onclick="savePayment()">Record Payment</button>
                <button class="btn btn-ghost" onclick="openStudentHistoryFromPaymentSelect()">Student History</button>
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
                  <thead><tr><th>Student</th><th>Due</th><th>Paid</th><th>Balance</th><th>Status</th></tr></thead>
                  <tbody>
                    ${(() => {
                      const grouped = (students || []).reduce((acc, s) => {
                        const key = `${s.current_class_level || 'Unassigned'}${s.section || ''}`;
                        if (!acc[key]) acc[key] = [];
                        acc[key].push(s);
                        return acc;
                      }, {});
                      return Object.keys(grouped).sort().flatMap(key => {
                        const header = `<tr><td colspan="5" style="background:var(--f0);font-weight:900">Class ${key} <span class="sub" style="font-weight:600">(${grouped[key].length} students)</span></td></tr>`;
                        const rows = grouped[key].map(s => {
                          const inv = invMap.get(s.id);
                          const due = inv ? Number(inv.amount_due) : 0;
                          const paid = inv ? Number(inv.amount_paid) : 0;
                          const bal = Math.max(due - paid, 0);
                          const st = inv ? inv.status : 'unpaid';
                          const badge = st === 'paid' ? 'green' : (st === 'partial' ? '' : '');
                          return `<tr>
                            <td><strong>${s.first_name} ${s.last_name}</strong><div class="sub">${s.student_id}</div></td>
                            <td style="font-weight:800;color:var(--m)">UGX ${fmt(due)}</td>
                            <td>UGX ${fmt(paid)}</td>
                            <td>UGX ${fmt(bal)}</td>
                            <td><span class="badge ${badge}">${st}</span> <button class="btn btn-xs btn-ghost" onclick="openStudentHistory(${s.id})">History</button> <button class="btn btn-xs btn-ghost" onclick="smsReminder(${s.id}, ${defTerm}, ${defYear})">SMS</button></td>
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
                <thead><tr><th>Time</th><th>Student</th><th>Amount</th><th>Method</th><th>Reference</th><th>Received By</th><th>Status</th><th></th></tr></thead>
                <tbody id="pay-body">${rows}</tbody>
              </table>
            </div></div>
          </div>`;
    } else if (page === 'settings') {
        const extra = await API.fetch('/auth/sessions/');
        const sessions = (extra && extra.sessions) ? extra.sessions : [];
        const logs = (extra && extra.security_logs) ? extra.security_logs : [];
        const sessHtml = sessions.map(s => `<div class="ri"><div class="ri-info"><div class="rn">${s.is_active ? 'Active session' : 'Session'}</div><div class="rd">${s.ip_address || '-'} Ã‚· ${s.login_time || ''}</div></div><div class="ri-end"><span class="badge ${s.is_active ? 'green' : ''}">${s.is_active ? 'active' : 'closed'}</span></div></div>`).join('');
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
                <div style="font-weight:700;margin-bottom:10px">My Profile</div>
                <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end">
                  <div class="field" style="margin:0;min-width:220px"><label>First Name</label><input class="field-input" id="me-fn" value="${currentUser.first_name || ''}"></div>
                  <div class="field" style="margin:0;min-width:220px"><label>Last Name</label><input class="field-input" id="me-ln" value="${currentUser.last_name || ''}"></div>
                  <div class="field" style="margin:0;min-width:260px"><label>Account Email (Django)</label><input class="field-input" id="me-email" type="email" value="${currentUser.email || ''}"></div>
                  <div class="field" style="margin:0;min-width:220px"><label>Phone Number</label><input class="field-input" id="me-phone" type="tel" value="${(currentUser.profile && currentUser.profile.phone_number) ? currentUser.profile.phone_number : ''}"></div>
                  <div class="field" style="margin:0;min-width:260px"><label>Login Email (profile)</label><input class="field-input" id="me-pemail" type="email" value="${(currentUser.profile && currentUser.profile.email_address) ? currentUser.profile.email_address : ''}"></div>
                  <div class="field" style="margin:0;min-width:320px"><label>Profile Photo URL</label><input class="field-input" id="me-photo" placeholder="https://..." value="${(currentUser.profile && currentUser.profile.photo_url) ? currentUser.profile.photo_url : ''}"></div>
                  <button class="btn btn-ghost" onclick="saveMyProfile()">Save Profile</button>
                </div>
                ${(currentUser.profile && currentUser.profile.photo_url) ? `<div style="height:10px"></div><div class="card" style="border-style:dashed"><div class="card-body" style="padding:12px 14px;display:flex;gap:12px;align-items:center"><div style="width:52px;height:52px;border-radius:12px;overflow:hidden;border:1px solid var(--e);background:#fff;flex-shrink:0"><img alt="Profile" src="${currentUser.profile.photo_url}" style="width:52px;height:52px;object-fit:cover"></div><div><div style="font-weight:900">Preview</div><div class="sub">If the image URL is blocked by the browser, use an HTTPS public image.</div></div></div></div></div>` : ''}
                <div style="height:14px"></div>
                <div style="font-weight:700;margin-bottom:10px">Account</div>
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
                  <button class="btn btn-primary" onclick="doLogout()">Logout</button>
                </div>
              </div></div>
              ${notifHtml}
              <div style="height:12px"></div>
              <div class="card"><div class="card-head"><div class="card-title">Sessions</div></div><div class="card-body">${sessHtml || 'No sessions.'}</div></div>
              <div style="height:12px"></div>
              <div class="card"><div class="card-head"><div class="card-title">Recent Security Events</div></div><div class="card-body">${logHtml || 'No security events.'}</div></div>
              ${sysHtml}
            </div>`;
    }
    } catch (e) {
      const msg = (e && (e.detail || e.status)) ? (e.detail || e.status) : 'Request failed.';
      main.innerHTML = `<div class="page"><div class="card"><div class="card-body"><div style="font-weight:800;color:var(--rd)">Error</div><div style="margin-top:6px;color:var(--66)">${msg}</div></div></div></div>`;
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
    const password = document.getElementById('u-password').value;
    const role = document.getElementById('u-role').value;
    const first_name = document.getElementById('u-fname').value.trim();
    const last_name = document.getElementById('u-lname').value.trim();
    const phone_number = document.getElementById('u-phone').value.trim();
    const email_address = document.getElementById('u-email').value.trim();

    if (!username) { flash('Username required.'); return; }
    if (!id && !password) { flash('Password required for new user.'); return; }
    const payload = { username, role, first_name, last_name, phone_number, email_address };
    if (password) payload.password = password;

    if (id) await API.fetch(`/users/${id}/`, { method: 'PATCH', body: JSON.stringify(payload) });
    else await API.fetch('/users/', { method: 'POST', body: JSON.stringify({ ...payload, password }) });

    closeModal('modal-user');
    loadPage('users');
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

function clearUserForm() {
    document.getElementById('u-id').value = '';
    document.getElementById('u-username').value = '';
    document.getElementById('u-password').value = '';
    document.getElementById('u-role').value = 'admin';
    document.getElementById('u-fname').value = '';
    document.getElementById('u-lname').value = '';
    document.getElementById('u-phone').value = '';
    document.getElementById('u-email').value = '';
}

function openUserAdd() {
    clearUserForm();
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
    openModal('modal-user');
}

function clearTeacherForm() {
    document.getElementById('t-id').value = '';
    document.getElementById('t-fn').value = '';
    document.getElementById('t-ln').value = '';
    document.getElementById('t-ph').value = '';
    document.getElementById('t-em').value = '';
    document.getElementById('t-subj').value = '';
    document.getElementById('t-cls').value = '';
    document.getElementById('t-type').value = 'Permanent';
}

function openTeacherAdd() {
    clearTeacherForm();
    openModal('modal-teacher');
}

async function openTeacherEdit(id) {
    clearTeacherForm();
    const t = await API.fetch(`/teachers/${id}/`);
    document.getElementById('t-id').value = t.id;
    document.getElementById('t-fn').value = t.first_name || '';
    document.getElementById('t-ln').value = t.last_name || '';
    document.getElementById('t-ph').value = t.phone || '';
    document.getElementById('t-em').value = t.email || '';
    document.getElementById('t-subj').value = (t.subjects || []).join(', ');
    document.getElementById('t-cls').value = t.assigned_class || '';
    document.getElementById('t-type').value = t.employment_type || 'Permanent';
    openModal('modal-teacher');
}

async function saveTeacher() {
    const id = document.getElementById('t-id').value;
    const first_name = document.getElementById('t-fn').value.trim();
    const last_name = document.getElementById('t-ln').value.trim();
    const phone = document.getElementById('t-ph').value.trim();
    const email = document.getElementById('t-em').value.trim();
    const subjects = document.getElementById('t-subj').value.split(',').map(s => s.trim()).filter(Boolean);
    const assigned_class = document.getElementById('t-cls').value.trim();
    const employment_type = document.getElementById('t-type').value;
    if (!first_name || !last_name || !phone || !email) { flash('Teacher requires first name, last name, phone and email.'); return; }
    const payload = { first_name, last_name, phone, email, subjects, assigned_class, employment_type };
    if (id) {
        await API.fetch(`/teachers/${id}/`, { method: 'PATCH', body: JSON.stringify(payload) });
        flash('Teacher updated.');
    } else {
        await API.fetch('/teachers/', { method: 'POST', body: JSON.stringify(payload) });
        flash('Teacher registered (credentials generated).');
    }
    closeModal('modal-teacher');
    loadPage('teachers');
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
    document.getElementById('s-pph2').value = s.parent_phone2 || '';
    document.getElementById('s-addr').value = s.home_address || '';
    document.getElementById('s-prev').value = s.previous_school || '';
    document.getElementById('s-alg').value = s.allergies || '';
    document.getElementById('s-med').value = s.medical_conditions || '';
    document.getElementById('s-ecn').value = s.emergency_contact_name || '';
    document.getElementById('s-ecp').value = s.emergency_contact_phone || '';
    document.getElementById('s-tr').value = s.transport_route || '';
    document.getElementById('s-status').value = s.status || 'active';
    openModal('modal-student');
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
        parent_email, // not stored on Student; used to keep parent portal profile updated
    };

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
        if (c.parent_username && c.parent_temp_password) parts.push(`Parent: ${c.parent_username} / ${c.parent_temp_password}`);
        if (c.student_username && c.student_temp_password) parts.push(`Student: ${c.student_username} / ${c.student_temp_password}`);
        if (parts.length) flash('Credentials: ' + parts.join(' | '));
    }
    flash(id ? 'Student updated.' : 'Student registered.');
    loadPage('students');
}

async function refreshTermChip() {
    try {
        const t = await API.fetch('/terms/');
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

async function refreshNotificationsBadge() {
    try {
        const unread = await API.fetch('/notifications/?unread=true');
        const dot = document.getElementById('notif-dot');
        if (dot) dot.style.display = (unread && unread.length) ? 'block' : 'none';
    } catch {}
}

function openNotifications() {
    const d = document.getElementById('notif-drawer');
    const ov = document.getElementById('notif-overlay');
    if (ov) ov.style.display = 'block';
    if (d) d.style.transform = 'translateX(0)';
    loadNotifications('all');
}

function closeNotifications() {
    const d = document.getElementById('notif-drawer');
    const ov = document.getElementById('notif-overlay');
    if (d) d.style.transform = 'translateX(105%)';
    if (ov) ov.style.display = 'none';
}

function iconForCategory(cat) {
    if (cat === 'finance') return 'Ã°Å¸â€™Â°';
    if (cat === 'academic') return 'Ã°Å¸â€œÅ¡';
    if (cat === 'events') return 'Ã°Å¸â€œ...';
    if (cat === 'security') return 'Ã°Å¸â€â€™';
    return 'Ã¢â€žÂ¹Ã¯Â¸Â';
}

async function loadNotifications(cat) {
    const qs = (cat && cat !== 'all') ? `?category=${encodeURIComponent(cat)}` : '';
    const items = await API.fetch(`/notifications/${qs}`).catch(() => []);
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
          <div style="font-weight:${n.is_read ? 700 : 900}">${n.title}</div>
          <div style="font-size:12px;color:var(--66);margin-top:2px">${(n.message || '')}</div>
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
    loadNotifications('all');
}

async function markAllNotificationsRead() {
    await API.fetch('/notifications/mark-all-read/', { method: 'POST' });
    await refreshNotificationsBadge();
    loadNotifications('all');
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
    document.getElementById('an-pub').checked = true;
    document.getElementById('an-pin').checked = false;
    const del = document.getElementById('an-del');
    if (del) del.style.display = 'none';
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
    document.getElementById('an-pub').checked = !!a.is_published;
    document.getElementById('an-pin').checked = !!a.is_pinned;
    const del = document.getElementById('an-del');
    if (del) del.style.display = 'inline-flex';
}

async function saveAnnouncement() {
    const id = document.getElementById('an-id').value;
    const title = document.getElementById('an-title').value.trim();
    const body = document.getElementById('an-body').value.trim();
    const audRaw = document.getElementById('an-aud').value.trim();
    const audience_roles = audRaw ? audRaw.split(',').map(s => s.trim()).filter(Boolean) : [];
    const is_published = !!document.getElementById('an-pub').checked;
    const is_pinned = !!document.getElementById('an-pin').checked;
    if (!title || !body) { flash('Title and body are required.'); return; }
    const payload = { title, body, audience_roles, is_published, is_pinned };
    if (id) await API.fetch(`/announcements/${id}/`, { method: 'PATCH', body: JSON.stringify(payload) });
    else await API.fetch('/announcements/', { method: 'POST', body: JSON.stringify(payload) });
    flash('Announcement saved.');
    loadPage('announcements');
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

function downloadReportCard() {
    const student_id = document.getElementById('rc-stu').value;
    const term_number = document.getElementById('rc-term').value;
    const academic_year = document.getElementById('rc-year').value;
    window.open(`/api/report-cards/generate/${student_id}/${term_number}/${academic_year}/`, '_blank');
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
    window.open(`/api/report-cards/generate/${studentPk}/${term}/${year}/`, '_blank');
}

async function emailAllParents() {
    const class_id = document.getElementById('rc-class').value;
    const term_number = document.getElementById('rc-term2').value;
    const academic_year = document.getElementById('rc-year2').value;
    await API.fetch('/report-cards/email-all-parents/', { method: 'POST', body: JSON.stringify({ class_id, term_number, academic_year }) });
    flash('Emails sent (console backend in dev).');
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
            client_id: 'MoMo API user ID (if applicable).',
            client_secret: 'MoMo API secret (if applicable).',
            api_key: 'Subscription key for MTN MoMo API.',
        },
        extra: [
            { key: 'environment', label: 'Environment', placeholder: 'sandbox or production', type: 'text' },
            { key: 'callback_url', label: 'Callback URL', placeholder: 'https://yourdomain/...', type: 'text' },
        ],
        help: 'Used for receiving payments via MTN MoMo. Verification may fail if the server has no internet access.'
    },
    airtel_money: {
        label: 'Airtel Mobile Money',
        fields: { client_id: true, client_secret: true, api_key: true },
        labels: { client_id: 'Client ID', client_secret: 'Client Secret', api_key: 'API Key' },
        hints: {
            client_id: 'From Airtel developer portal/app.',
            client_secret: 'Keep secret.',
            api_key: 'API key/token (if required by your setup).',
        },
        extra: [
            { key: 'environment', label: 'Environment', placeholder: 'sandbox or production', type: 'text' },
            { key: 'callback_url', label: 'Callback URL', placeholder: 'https://yourdomain/...', type: 'text' },
        ],
        help: 'Used for receiving payments via Airtel Money.'
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
        label: 'Email SMTP',
        fields: { client_id: true, client_secret: true, api_key: false },
        labels: { client_id: 'SMTP Host', client_secret: 'SMTP Password', api_key: 'API Key' },
        hints: {
            client_id: 'e.g. smtp.gmail.com',
            client_secret: 'App password (recommended)',
            api_key: '',
        },
        extra: [
            { key: 'port', label: 'Port', placeholder: '587', type: 'number' },
            { key: 'username', label: 'Username', placeholder: 'school@gmail.com', type: 'text' },
            { key: 'use_tls', label: 'Use TLS (true/false)', placeholder: 'true', type: 'text' },
        ],
        help: 'Used for sending emails (password reset, credentials, reports).'
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
        ],
        help: 'Used for AI analytics/features. Keep disabled if not in use.'
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
    } catch (e) {
        flash(`Verify failed: ${(e && e.detail) ? e.detail : 'Request failed'}`);
    }
}

async function verifyCredentialFromForm() {
    const id = document.getElementById('cred-id')?.value;
    if (!id) { flash('Save the credential first, then verify.'); return; }
    await verifyCredential(id);
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
        <td>${p.received_at ? new Date(p.received_at).toLocaleString() : ''}</td>
        <td><strong>${p.student_name}</strong><div class="sub">${p.student_system_id}</div></td>
        <td style="font-weight:800;color:var(--m)">UGX ${fmt(p.amount)}</td>
        <td>${p.method}</td>
        <td style="font-size:12px;color:var(--66)">${p.reference || '-'}</td>
        <td>${p.received_by_username || '-'}</td>
        <td>${p.status}</td>
        <td>
          <button class="btn btn-xs btn-ghost" onclick="openPaymentEdit(${p.id})">Edit</button>
          ${p.status !== 'reversed' ? `<button class="btn btn-xs btn-ghost" onclick="reversePayment(${p.id})">Reverse</button>` : ''}
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
    document.getElementById('p-id').value = p.id;
    document.getElementById('p-amt').value = p.amount;
    document.getElementById('p-method').value = p.method || 'cash';
    document.getElementById('p-ref').value = p.reference || '';
    document.getElementById('p-notes').value = p.notes || '';
    document.getElementById('p-status').value = p.status || 'received';
    openModal('modal-payment');
}

async function savePaymentEdit() {
    const id = document.getElementById('p-id').value;
    const amount = document.getElementById('p-amt').value;
    const method = document.getElementById('p-method').value;
    const reference = document.getElementById('p-ref').value.trim();
    const notes = document.getElementById('p-notes').value.trim();
    const status = document.getElementById('p-status').value;
    await API.fetch(`/payments/${id}/`, { method: 'PATCH', body: JSON.stringify({ amount, method, reference, notes, status }) });
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

async function openStudentHistory(studentId) {
    const body = document.getElementById('sh-body');
    if (body) body.innerHTML = 'LoadingÃ¢â‚¬Â¦';
    openModal('modal-stuhistory');
    const data = await API.fetch(`/students/${studentId}/history/`);
    const s = data.student;
    const payRows = (data.payments || []).slice(0, 30).map(p => `<tr><td>${p.received_at ? new Date(p.received_at).toLocaleString() : ''}</td><td style="font-weight:800;color:var(--m)">UGX ${fmt(p.amount)}</td><td>${p.method}</td><td>${p.reference || '-'}</td><td>${p.status}</td></tr>`).join('');
    const markRows = (data.marks || []).slice(0, 30).map(m => `<tr><td>${m.year}</td><td>${m.term}</td><td>${m.subject}</td><td>${m.score}</td></tr>`).join('');
    const attRows = (data.attendance || []).slice(0, 30).map(a => `<tr><td>${a.date}</td><td>${a.status}</td></tr>`).join('');
    if (body) body.innerHTML = `
      <div style="display:flex;gap:14px;flex-wrap:wrap;align-items:flex-start">
        <div style="flex:1;min-width:260px">
          <div style="font-weight:900;font-size:16px;color:var(--md)">${s.first_name} ${s.last_name}</div>
          <div style="font-size:12px;color:var(--66);margin-top:2px">${s.student_id} Ã‚· ${s.current_class_level || '-'}${s.section || ''} Ã‚· ${s.status}</div>
          <div style="margin-top:10px;color:var(--66);font-size:13px">
            <div><strong>Parent:</strong> ${s.parent_name} (${s.parent_relationship})</div>
            <div><strong>Phone:</strong> ${s.parent_phone}${s.parent_phone2 ? ' / ' + s.parent_phone2 : ''}</div>
          </div>
        </div>
        <div style="min-width:260px">
          <button class="btn btn-ghost" onclick="editStudentFromHistory(${s.id})">Edit Student</button>
        </div>
      </div>
      <div style="height:12px"></div>
      <div class="tabs">
        <button class="tab-b active" onclick="tabShow('sh-pay',this)">Payments</button>
        <button class="tab-b" onclick="tabShow('sh-marks',this)">Marks</button>
        <button class="tab-b" onclick="tabShow('sh-att',this)">Attendance</button>
      </div>
      <div style="height:10px"></div>
      <div id="sh-pay" class="tab-p active">
        <div class="tw"><table class="tbl"><thead><tr><th>Time</th><th>Amount</th><th>Method</th><th>Reference</th><th>Status</th></tr></thead><tbody>${payRows || ''}</tbody></table></div>
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
        if (res.student_username && res.student_temp_password) parts.push(`Student: ${res.student_username} / ${res.student_temp_password}`);
        flash(parts.length ? ('New credentials: ' + parts.join(' | ')) : 'Passwords reset.');
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
    currentUser = await API.fetch('/auth/me/', { method: 'PATCH', body: JSON.stringify({ first_name, last_name, email, phone_number, email_address, photo_url }) });
    flash('Profile updated.');
    loadPage('settings');
}

async function saveSystemSettings() {
    const items = [
        { key: 'send_credentials_sms', value: !!document.getElementById('ss-cred-sms')?.checked },
        { key: 'send_credentials_email', value: !!document.getElementById('ss-cred-email')?.checked },
        { key: 'send_fee_reminder_sms', value: !!document.getElementById('ss-fee-sms')?.checked },
    ];
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
    if (new_password.length < 8) { flash('Password must be at least 8 characters.'); return; }
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
function toggleSidebar() { document.getElementById('sidebar').classList.toggle('mobile-open'); document.getElementById('sb-overlay').classList.toggle('show'); }
function fmt(n) { return Number(n).toLocaleString(); }

// Timetable builder state (admin/reception).
let TT = { school_class: null, section: 'A', days: [], periods: [], times: {}, cells: {}, teachers: [] };

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
    const teacherOptions = ['<option value=\"\">(No teacher)</option>'].concat(
        teachers.map(t => `<option value=\"${t.id}\">${(t.first_name || '').toString()} ${(t.last_name || '').toString()} (${t.employee_id || ''})</option>`)
    ).join('');
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
            const tid = (cell.teacher_id || '').toString();
            const tname = (cell.teacher_name || '').toString().replace(/"/g, '&quot;');
            return `<td class="${isNow ? 'tt-now-cell' : ''}">
              <div style="display:flex;flex-direction:column;gap:6px">
                <input class="field-input" style="padding:6px 8px;font-size:12px" value="${subj}" placeholder="Subject / Activity" oninput="ttSetCell('${k}', {subject: this.value})">
                <select class="field-select" style="padding:6px 8px;font-size:12px" onchange="ttOnTeacherPick('${k}', this.value)">
                  ${teacherOptions.replace(`value=\"${tid}\"`, `value=\"${tid}\" selected`)}
                </select>
                <input class="field-input" style="padding:6px 8px;font-size:12px;display:none" value="${tname}">
              </div>
            </td>`;
        }).join('')}
      </tr>`).join('');
    el.innerHTML = `<table class="tbl">${head}<tbody>${body}</tbody></table>`;
    ttRenderTimesEditor();
}

async function ttLoad() {
    const cls = document.getElementById('tt-class')?.value;
    const sec = (document.getElementById('tt-sec')?.value || 'A').trim().toUpperCase();
    const days = ttParseList(document.getElementById('tt-days')?.value || 'Mon,Tue,Wed,Thu,Fri');
    const periods = ttParseList(document.getElementById('tt-periods')?.value || '1,2,3,4,5,6,7,8');

    TT = { school_class: cls, section: sec, days, periods, times: {}, cells: {} };

    // Use filtered list endpoint for admins/reception.
    const existing = await API.fetch(`/timetable/?school_class=${encodeURIComponent(cls)}&section=${encodeURIComponent(sec)}`).catch(() => []);
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
}

async function ttSave() {
    const cls = document.getElementById('tt-class')?.value;
    const sec = (document.getElementById('tt-sec')?.value || 'A').trim().toUpperCase();
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
      <div style="margin-bottom:10px">Class ID: ${TT.school_class || ''} Ã‚· Section: ${TT.section || ''}</div>
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
    const srcSec = (document.getElementById('tt-copy-sec')?.value || 'A').trim().toUpperCase();
    if (!srcClass) { flash('Select a source class to copy from.'); return; }
    const existing = await API.fetch(`/timetable/?school_class=${encodeURIComponent(srcClass)}&section=${encodeURIComponent(srcSec)}`).catch(() => []);
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

function clearEventForm() {
    const ids = ['ev-id', 'ev-title', 'ev-start', 'ev-end', 'ev-aud', 'ev-img', 'ev-desc'];
    ids.forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    const pub = document.getElementById('ev-pub'); if (pub) pub.checked = true;
}

function openEventAdd() {
    clearEventForm();
    // Prefill start date.
    const st = document.getElementById('ev-start');
    if (st && !st.value) st.value = new Date().toISOString().slice(0, 10);
}

async function openEventEdit(id) {
    const e = await API.fetch(`/events/${id}/`);
    document.getElementById('ev-id').value = e.id;
    document.getElementById('ev-title').value = e.title || '';
    document.getElementById('ev-start').value = e.start_date || '';
    document.getElementById('ev-end').value = e.end_date || '';
    document.getElementById('ev-aud').value = (e.audience_roles && e.audience_roles.length) ? e.audience_roles.join(',') : '';
    if (document.getElementById('ev-img')) document.getElementById('ev-img').value = e.image_url || '';
    document.getElementById('ev-desc').value = e.description || '';
    document.getElementById('ev-pub').checked = !!e.is_published;
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
