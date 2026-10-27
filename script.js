/* ==========================================================
   TutorMatch — interactions
   Sections: helpers · background video · drawer · showreel ·
             auth modal · auth logic (demo, localStorage) · init
   ========================================================== */
(function () {
  'use strict';

  const $  = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const refreshIcons = () => { if (window.lucide) window.lucide.createIcons(); };
  refreshIcons();

  /* ---------- Scroll lock that supports stacked overlays ---------- */
  let lockCount = 0;
  function lockScroll(on) {
    lockCount = Math.max(0, lockCount + (on ? 1 : -1));
    document.body.style.overflow = lockCount > 0 ? 'hidden' : '';
  }

  /* ---------- Simple focus trap ---------- */
  function trapFocus(container) {
    container.addEventListener('keydown', (e) => {
      if (e.key !== 'Tab') return;
      const items = $$('a[href], button:not([disabled]), input:not([disabled]), video[controls]', container)
        .filter((el) => el.offsetParent !== null);
      if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });
  }

  /* ---------- Toast ---------- */
  const toast = $('#toast');
  let toastTimer;
  function showToast(message) {
    toast.textContent = message;
    toast.dataset.show = 'true';
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.dataset.show = 'false'; }, 3200);
  }

  /* ==========================================================
     Background video — slow ambient playback
     ========================================================== */
  const bg = $('#bg-video');
  const slowBg = () => { bg.playbackRate = 0.7; };
  const playBg = () => bg.play().catch(() => {});
  slowBg();
  bg.addEventListener('loadedmetadata', slowBg);
  bg.addEventListener('play', slowBg);
  playBg();

  /* ==========================================================
     Mobile drawer
     ========================================================== */
  const drawer    = $('#drawer');
  const scrim     = $('#scrim');
  const menuOpen  = $('#menu-open');
  const menuClose = $('#menu-close');

  function setDrawer(open, { focus = true } = {}) {
    if ((drawer.dataset.open === 'true') === open) return;
    drawer.dataset.open = String(open);
    scrim.dataset.open  = String(open);
    menuOpen.setAttribute('aria-expanded', String(open));
    lockScroll(open);
    if (focus) (open ? menuClose : menuOpen).focus();
  }
  menuOpen.addEventListener('click', () => setDrawer(true));
  menuClose.addEventListener('click', () => setDrawer(false));
  scrim.addEventListener('click', () => setDrawer(false));
  $$('.drawer-link').forEach((a) => a.addEventListener('click', () => setDrawer(false, { focus: false })));

  /* ==========================================================
     Showreel modal
     ========================================================== */
  const showreel      = $('#modal');
  const showreelVideo = $('#modal-video');
  const showreelClose = $('#modal-close');
  const showreelBtn   = $('#showreel-open');

  function setShowreel(open) {
    if ((showreel.dataset.open === 'true') === open) return;
    showreel.dataset.open = String(open);
    lockScroll(open);
    if (open) {
      bg.pause();
      showreelVideo.currentTime = 0;
      showreelVideo.play().catch(() => {});
      showreelClose.focus();
    } else {
      showreelVideo.pause();
      playBg();
      showreelBtn.focus();
    }
  }
  showreelBtn.addEventListener('click', () => setShowreel(true));
  showreelClose.addEventListener('click', () => setShowreel(false));
  showreel.addEventListener('click', (e) => { if (e.target === showreel) setShowreel(false); });
  trapFocus(showreel);

  /* ==========================================================
     Auth modal (login / register)
     ========================================================== */
  const authModal = $('#auth-modal');
  const authClose = $('#auth-close');
  const loginForm = $('#login-form');
  const regForm   = $('#register-form');
  const tabs      = $$('.auth-tab');
  const titleLead = $('#auth-title-lead');
  const titleAcc  = $('#auth-title-accent');
  const subtitle  = $('#auth-subtitle');

  const COPY = {
    login: {
      lead: 'Welcome', accent: 'back.',
      sub: 'Log in to pick up where you left off.'
    },
    register: {
      lead: 'Let\u2019s get', accent: 'started.',
      sub: 'Create your TutorMatch account in under a minute.'
    }
  };

  let lastTrigger = null;
  let currentTab = 'login';

  function setTab(name, { focus = true } = {}) {
    currentTab = name;
    tabs.forEach((t) => {
      const active = t.dataset.tab === name;
      t.setAttribute('aria-selected', String(active));
      t.tabIndex = active ? 0 : -1;
    });
    loginForm.classList.toggle('hidden', name !== 'login');
    regForm.classList.toggle('hidden', name !== 'register');
    titleLead.textContent = COPY[name].lead;
    titleAcc.textContent  = COPY[name].accent;
    subtitle.textContent  = COPY[name].sub;
    clearAllErrors();
    if (focus) {
      const form = name === 'login' ? loginForm : regForm;
      $('input', form).focus();
    }
  }

  function openAuth(tab = 'login', trigger = null) {
    lastTrigger = trigger || document.activeElement;
    if (authModal.dataset.open !== 'true') {
      authModal.dataset.open = 'true';
      lockScroll(true);
    }
    setTab(tab, { focus: false });
    // wait a frame so the modal is visible before focusing
    setTimeout(() => $('input', tab === 'login' ? loginForm : regForm).focus(), 60);
  }

  function closeAuth() {
    if (authModal.dataset.open !== 'true') return;
    authModal.dataset.open = 'false';
    lockScroll(false);
    loginForm.reset();
    regForm.reset();
    updateStrength('');
    clearAllErrors();
    if (lastTrigger && document.contains(lastTrigger) && lastTrigger.offsetParent !== null) lastTrigger.focus();
  }

  // Any element with data-auth-open opens the modal on that tab
  document.addEventListener('click', (e) => {
    const trigger = e.target.closest('[data-auth-open]');
    if (trigger) {
      e.preventDefault();
      setDrawer(false, { focus: false });
      openAuth(trigger.dataset.authOpen, trigger);
      return;
    }
    const tabLink = e.target.closest('[data-tab]');
    if (tabLink && authModal.contains(tabLink)) setTab(tabLink.dataset.tab);
  });

  authClose.addEventListener('click', closeAuth);
  authModal.addEventListener('click', (e) => { if (e.target === authModal || e.target.parentElement === authModal) closeAuth(); });
  trapFocus(authModal);

  // Arrow-key navigation between tabs
  $('[role="tablist"]', authModal).addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const next = currentTab === 'login' ? 'register' : 'login';
    setTab(next, { focus: false });
    $(`#tab-${next}`).focus();
  });

  // Show / hide password
  $$('[data-toggle-password]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const input = document.getElementById(btn.dataset.togglePassword);
      const show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
      $('.eye-on', btn).classList.toggle('hidden', show);
      $('.eye-off', btn).classList.toggle('hidden', !show);
    });
  });

  // Forgot password (demo)
  $('#forgot-btn').addEventListener('click', () => {
    const email = $('#login-email').value.trim();
    if (!isEmail(email)) {
      setError('login-email', 'Enter your email first, then tap Forgot.');
      $('#login-email').focus();
      return;
    }
    setStatus('login-status', 'success', 'If an account exists for that email, a reset link is on its way.');
  });

  /* ---------- Validation helpers ---------- */
  const isEmail = (v) => /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v);

  function setError(id, message) {
    const input = document.getElementById(id);
    const out = $(`[data-error-for="${id}"]`);
    if (out) out.textContent = message || '';
    if (input && input.type !== 'checkbox') {
      if (message) input.setAttribute('aria-invalid', 'true'); else input.removeAttribute('aria-invalid');
    }
    return !message;
  }
  function clearAllErrors() {
    $$('.field-error', authModal).forEach((el) => { el.textContent = ''; });
    $$('[aria-invalid]', authModal).forEach((el) => el.removeAttribute('aria-invalid'));
    $$('.form-status', authModal).forEach((el) => { el.textContent = ''; el.removeAttribute('data-type'); });
  }
  function setStatus(id, type, message) {
    const el = document.getElementById(id);
    el.textContent = message;
    if (message) el.dataset.type = type; else el.removeAttribute('data-type');
  }

  // clear a field's error as the user types
  $$('.field', authModal).forEach((input) => {
    input.addEventListener('input', () => setError(input.id, ''));
  });
  $('#reg-terms').addEventListener('change', () => setError('reg-terms', ''));

  /* ---------- Password strength ---------- */
  const strengthBar   = $('.strength');
  const strengthLabel = $('#strength-label');
  const LEVELS = ['Use 8+ characters with letters and numbers.', 'Weak — add more characters.', 'Fair — mix in numbers or symbols.', 'Good — almost there.', 'Strong password.'];

  function scorePassword(pw) {
    if (!pw) return 0;
    let s = 0;
    if (pw.length >= 8) s++;
    if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) s++;
    if (/\d/.test(pw)) s++;
    if (/[^A-Za-z0-9]/.test(pw) || pw.length >= 14) s++;
    return Math.max(1, s);
  }
  function updateStrength(pw) {
    const lvl = scorePassword(pw);
    strengthBar.dataset.level = String(lvl);
    strengthLabel.textContent = LEVELS[lvl];
  }
  $('#reg-password').addEventListener('input', (e) => updateStrength(e.target.value));

  /* ==========================================================
     Auth logic — FRONT-END DEMO ONLY
     Accounts live in this browser's localStorage. Replace the
     functions in the "Backend adapter" block with real API calls
     (fetch to your server) before going to production.
     ========================================================== */
  const USERS_KEY   = 'tutormatch_users';
  const SESSION_KEY = 'tutormatch_session';

  /* ---- Backend adapter (swap these for real API calls) ---- */
  const readUsers  = () => { try { return JSON.parse(localStorage.getItem(USERS_KEY)) || {}; } catch { return {}; } };
  const writeUsers = (u) => localStorage.setItem(USERS_KEY, JSON.stringify(u));

  async function hashPassword(password, salt) {
    const data = new TextEncoder().encode(salt + ':' + password);
    if (window.crypto && crypto.subtle) {
      const buf = await crypto.subtle.digest('SHA-256', data);
      return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, '0')).join('');
    }
    // Fallback (non-secure contexts): simple non-cryptographic hash, demo only
    let h = 5381;
    for (const b of data) h = ((h << 5) + h + b) >>> 0;
    return 'x' + h.toString(16);
  }
  const makeSalt = () => Array.from(crypto.getRandomValues(new Uint8Array(12))).map((b) => b.toString(16).padStart(2, '0')).join('');

  async function apiRegister({ name, email, password }) {
    await delay(500);
    const users = readUsers();
    const key = email.toLowerCase();
    if (users[key]) throw new Error('An account with this email already exists.');
    const salt = makeSalt();
    users[key] = { name, email: key, salt, hash: await hashPassword(password, salt), createdAt: Date.now() };
    writeUsers(users);
    return { name, email: key };
  }

  async function apiLogin({ email, password }) {
    await delay(500);
    const user = readUsers()[email.toLowerCase()];
    // same message for unknown email / wrong password
    const fail = new Error('Incorrect email or password.');
    if (!user) throw fail;
    if ((await hashPassword(password, user.salt)) !== user.hash) throw fail;
    return { name: user.name, email: user.email };
  }
  /* ---- end backend adapter ---- */

  const delay = (ms) => new Promise((r) => setTimeout(r, ms));

  function saveSession(user, remember) {
    clearSession();
    (remember ? localStorage : sessionStorage).setItem(SESSION_KEY, JSON.stringify(user));
  }
  function clearSession() {
    localStorage.removeItem(SESSION_KEY);
    sessionStorage.removeItem(SESSION_KEY);
  }
  function getSession() {
    try { return JSON.parse(sessionStorage.getItem(SESSION_KEY) || localStorage.getItem(SESSION_KEY)); }
    catch { return null; }
  }

  /* ---------- Reflect auth state in the UI ---------- */
  function renderAuthState() {
    const user = getSession();
    const signedIn = !!user;

    $('#auth-guest').classList.toggle('hidden', signedIn);
    $('#auth-user').classList.toggle('hidden', !signedIn);
    $('#auth-user').classList.toggle('flex', signedIn);
    $('#auth-guest').classList.toggle('flex', !signedIn);
    $('#drawer-guest').classList.toggle('hidden', signedIn);
    $('#drawer-user').classList.toggle('hidden', !signedIn);
    $('#hero-join').classList.toggle('hidden', signedIn);

    if (signedIn) {
      const first = (user.name || user.email).trim().split(/\s+/)[0];
      $('#user-name').textContent = first;
      $('#user-initial').textContent = first.charAt(0).toUpperCase();
      $('#drawer-user-name').textContent = user.name || user.email;
    }
  }

  function setBusy(form, busy) {
    const btn = $('.submit-btn', form);
    btn.disabled = busy;
    $('span', btn).textContent = busy
      ? (form === loginForm ? 'Logging in…' : 'Creating account…')
      : (form === loginForm ? 'Log In' : 'Create Account');
  }

  /* ---------- Login submit ---------- */
  loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    clearAllErrors();

    const email = $('#login-email').value.trim();
    const password = $('#login-password').value;

    let ok = true;
    if (!isEmail(email)) ok = setError('login-email', 'Enter a valid email address.') && ok;
    if (!password)       ok = setError('login-password', 'Enter your password.') && ok;
    if (!ok) { $('[aria-invalid="true"]', loginForm)?.focus(); return; }

    setBusy(loginForm, true);
    try {
      const user = await apiLogin({ email, password });
      saveSession(user, $('#login-remember').checked);
      renderAuthState();
      closeAuth();
      showToast(`Welcome back, ${user.name.split(' ')[0]}.`);
    } catch (err) {
      setStatus('login-status', 'error', err.message);
    } finally {
      setBusy(loginForm, false);
    }
  });

  /* ---------- Register submit ---------- */
  regForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    clearAllErrors();

    const name = $('#reg-name').value.trim();
    const email = $('#reg-email').value.trim();
    const password = $('#reg-password').value;
    const confirm = $('#reg-confirm').value;
    const terms = $('#reg-terms').checked;

    let ok = true;
    if (name.length < 2) ok = setError('reg-name', 'Please enter your full name.') && ok;
    if (!isEmail(email)) ok = setError('reg-email', 'Enter a valid email address.') && ok;
    if (password.length < 8 || !/[A-Za-z]/.test(password) || !/\d/.test(password)) {
      ok = setError('reg-password', 'Use at least 8 characters with a letter and a number.') && ok;
    }
    if (confirm !== password || !confirm) ok = setError('reg-confirm', 'Passwords don\u2019t match.') && ok;
    if (!terms) ok = setError('reg-terms', 'Please accept the terms to continue.') && ok;
    if (!ok) { $('[aria-invalid="true"]', regForm)?.focus(); return; }

    setBusy(regForm, true);
    try {
      const user = await apiRegister({ name, email, password });
      saveSession(user, true);
      renderAuthState();
      closeAuth();
      showToast(`Account created. Welcome, ${name.split(' ')[0]}!`);
    } catch (err) {
      setStatus('register-status', 'error', err.message);
    } finally {
      setBusy(regForm, false);
    }
  });

  /* ---------- Logout ---------- */
  $$('[data-auth-logout]').forEach((btn) => {
    btn.addEventListener('click', () => {
      clearSession();
      renderAuthState();
      setDrawer(false, { focus: false });
      showToast('You\u2019ve been logged out.');
    });
  });

  /* ==========================================================
     Global: ESC closes the top-most overlay
     ========================================================== */
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (authModal.dataset.open === 'true') closeAuth();
    else if (showreel.dataset.open === 'true') setShowreel(false);
    else if (drawer.dataset.open === 'true') setDrawer(false);
  });

  /* ---------- Init ---------- */
  updateStrength('');
  renderAuthState();
})();
