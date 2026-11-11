/* ==========================================================
   TutorMatch — interactions
   Sections: helpers · background video · drawer · showreel ·
             auth modal · auth logic (Flask API) · init
   ========================================================== */
(function () {
  'use strict';

  const $  = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const refreshIcons = () => { if (window.lucide) window.lucide.createIcons(); };
  refreshIcons();

  /* ---------- CSRF token (secure backend) ----------
     The Flask server gives us a token tied to the session cookie.
     Every POST will send it back in the X-CSRFToken header. */
  let csrfToken = '';

  function fillCsrfInputs() {
    $$('input[name="csrf_token"]').forEach((input) => {
      input.value = csrfToken;
      if (csrfToken) input.setAttribute('value', csrfToken);
    });
  }

  async function loadCsrfToken() {
    try {
      const res = await fetch('/api/csrf', { credentials: 'same-origin' });
      if (!res.ok) return;
      const data = await res.json();
      csrfToken = data.csrf_token || '';
      fillCsrfInputs();
    } catch {
      // The page can still be opened as a static file during frontend-only work.
    }
  }

  loadCsrfToken();

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
     Section links — smooth scroll + active highlight
     ========================================================== */
  const SECTION_IDS = ['about', 'services', 'find-my-match', 'how-it-works'];
  const sectionEls = SECTION_IDS
    .map((id) => document.getElementById(id))
    .filter(Boolean);
  const sectionLinks = $$('.nav-link[href^="#"], .drawer-link[href^="#"]');
  const sectionIdSet = new Set(SECTION_IDS);

  function setActiveSection(id) {
    sectionLinks.forEach((link) => {
      const active = link.getAttribute('href') === `#${id}`;
      link.classList.toggle('is-active', active);
      if (active) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    });
  }

  function updateActiveSection() {
    if (!sectionEls.length) return;
    const offset = Math.min(160, window.innerHeight * 0.3);
    let current = '';
    sectionEls.forEach((section) => {
      if (section.getBoundingClientRect().top <= offset) current = section.id;
    });
    setActiveSection(current);
  }

  let activeFrame = 0;
  function queueActiveSection() {
    if (activeFrame) return;
    activeFrame = window.requestAnimationFrame(() => {
      activeFrame = 0;
      updateActiveSection();
    });
  }

  window.addEventListener('scroll', queueActiveSection, { passive: true });
  window.addEventListener('resize', queueActiveSection);
  window.addEventListener('hashchange', updateActiveSection);
  sectionLinks.forEach((link) => {
    link.addEventListener('click', () => {
      const id = (link.getAttribute('href') || '').slice(1);
      if (sectionIdSet.has(id)) setActiveSection(id);
    });
  });
  updateActiveSection();

  /* ==========================================================
     Showreel modal
     ========================================================== */
  const showreel         = $('#modal');
  const showreelVideo    = $('#modal-video');
  const showreelFallback = $('#modal-video-fallback');
  const showreelClose    = $('#modal-close');
  const showreelBtn      = $('#showreel-open');
  let showreelBroken     = false;

  function showVideoFallback() {
    showreelBroken = true;
    if (showreelVideo) {
      showreelVideo.pause();
      showreelVideo.classList.add('hidden');
    }
    if (showreelFallback) {
      showreelFallback.classList.remove('hidden');
      showreelFallback.classList.add('flex');
    }
  }

  function clearVideoFallback() {
    if (showreelVideo) showreelVideo.classList.remove('hidden');
    if (showreelFallback) {
      showreelFallback.classList.add('hidden');
      showreelFallback.classList.remove('flex');
    }
  }

  function resetShowreelVideo() {
    if (!showreelVideo) return;
    try {
      showreelVideo.pause();
      showreelVideo.currentTime = 0;
    } catch {
      // The file may be missing or metadata may not be loaded yet.
    }
  }

  showreelVideo.addEventListener('error', showVideoFallback);
  if (showreelVideo.error) showVideoFallback();

  function setShowreel(open) {
    if ((showreel.dataset.open === 'true') === open) return;
    showreel.dataset.open = String(open);
    lockScroll(open);

    if (open) {
      bg.pause();

      if (showreelBroken) {
        showVideoFallback();
      } else {
        clearVideoFallback();
        try { showreelVideo.currentTime = 0; } catch {}
        const playback = showreelVideo.play();
        if (playback && typeof playback.catch === 'function') {
          playback.catch(() => {
            // A missing file fires the error event. An autoplay block
            // leaves the controls available for the user.
            if (showreelVideo.error) showVideoFallback();
          });
        }
      }

      showreelClose.focus();
    } else {
      resetShowreelVideo();
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
  const verifyForm = $('#verify-form');
  const resetForm  = $('#reset-form');
  const authTabs   = $('#auth-tabs');
  const verifyEmailInput = $('#verify-email');
  const verifyEmailDisplay = $('#verify-email-display');
  const resetTokenInput = $('#reset-token');
  const tabs      = $$('.auth-tab');
  const titleLead = $('#auth-title-lead');
  const titleAcc  = $('#auth-title-accent');
  const subtitle  = $('#auth-subtitle');

  const FORMS = {
    login: loginForm,
    register: regForm,
    verify: verifyForm,
    reset: resetForm
  };

  const COPY = {
    login: {
      lead: 'Welcome', accent: 'back.',
      sub: 'Log in to pick up where you left off.'
    },
    register: {
      lead: 'Let\u2019s get', accent: 'started.',
      sub: 'Create your TutorMatch account in under a minute.'
    },
    verify: {
      lead: 'Check your', accent: 'email.',
      sub: 'Enter the 6-digit code we sent to your inbox.'
    },
    reset: {
      lead: 'Choose a', accent: 'new password.',
      sub: 'Your reset link is single-use and expires soon.'
    }
  };

  const ROLE_HELP = {
    student: "You'll see tutors who match your subject, budget and schedule.",
    tutor: "You'll see students who need your subject and availability."
  };
  const roleHelper = $('#role-helper');

  function setRole(role) {
    const normalized = role === 'tutor' ? 'tutor' : 'student';
    $$('input[name="role"]', regForm).forEach((input) => {
      input.checked = input.value === normalized;
    });
    $$('.role-card', regForm).forEach((card) => {
      card.dataset.selected = String(card.dataset.roleCard === normalized);
    });
    if (roleHelper) roleHelper.textContent = ROLE_HELP[normalized];
  }

  let lastTrigger = null;
  let currentTab = 'login';
  let pendingEmail = '';
  let resetToken = '';

  function setTab(name, { focus = true } = {}) {
    const target = FORMS[name] ? name : 'login';
    currentTab = target;

    tabs.forEach((t) => {
      const active = t.dataset.tab === target;
      t.setAttribute('aria-selected', String(active));
      t.tabIndex = active ? 0 : -1;
    });

    Object.entries(FORMS).forEach(([key, form]) => {
      form.classList.toggle('hidden', key !== target);
    });
    if (authTabs) {
      authTabs.classList.toggle('hidden', target !== 'login' && target !== 'register');
    }

    const copy = COPY[target] || COPY.login;
    titleLead.textContent = copy.lead;
    titleAcc.textContent  = copy.accent;
    subtitle.textContent  = copy.sub;
    clearAllErrors();

    if (focus) {
      const form = FORMS[target];
      const firstField = $$('input:not([type="hidden"]), select, textarea', form)
        .find((el) => el.offsetParent !== null);
      if (firstField) firstField.focus();
    }
  }

  function openAuth(tab = 'login', trigger = null) {
    lastTrigger = trigger || document.activeElement;
    if (authModal.dataset.open !== 'true') {
      authModal.dataset.open = 'true';
      lockScroll(true);
    }
    const target = FORMS[tab] ? tab : 'login';
    setTab(target, { focus: false });
    if (target === 'register') {
      setRole(trigger && trigger.dataset.role ? trigger.dataset.role : 'student');
    }
    // wait a frame so the modal is visible before focusing
    setTimeout(() => {
      const form = FORMS[target];
      const firstField = $$('input:not([type="hidden"]), select, textarea', form)
        .find((el) => el.offsetParent !== null);
      if (firstField) firstField.focus();
    }, 60);
  }

  function openVerify(email, message) {
    pendingEmail = email || '';
    if (verifyEmailInput) verifyEmailInput.value = pendingEmail;
    if (verifyEmailDisplay) verifyEmailDisplay.textContent = pendingEmail || 'your email address';
    openAuth('verify');
    if (message) setStatus('verify-status', 'success', message);
  }

  function openReset(token, message) {
    resetToken = token || '';
    if (resetTokenInput) resetTokenInput.value = resetToken;
    openAuth('reset');
    if (message) setStatus('reset-status', 'success', message);
  }

  function clearAuthQuery() {
    const url = new URL(window.location.href);
    let changed = false;
    ['reset_token', 'login'].forEach((key) => {
      if (url.searchParams.has(key)) {
        url.searchParams.delete(key);
        changed = true;
      }
    });
    if (changed) {
      window.history.replaceState(null, '', url.pathname + url.search + url.hash);
    }
  }

  function closeAuth() {
    if (authModal.dataset.open !== 'true') return;
    authModal.dataset.open = 'false';
    lockScroll(false);
    loginForm.reset();
    regForm.reset();
    verifyForm.reset();
    resetForm.reset();
    pendingEmail = '';
    resetToken = '';
    if (verifyEmailInput) verifyEmailInput.value = '';
    if (resetTokenInput) resetTokenInput.value = '';
    setRole('student');
    fillCsrfInputs();
    updateStrength('');
    setTab('login', { focus: false });
    clearAuthQuery();
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
    if (currentTab !== 'login' && currentTab !== 'register') return;
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

  // Forgot password — sends a real single-use reset link
  $('#forgot-btn').addEventListener('click', async () => {
    const email = $('#login-email').value.trim();
    if (!isEmail(email)) {
      setError('login-email', 'Enter your email first, then tap Forgot.');
      $('#login-email').focus();
      return;
    }

    const button = $('#forgot-btn');
    const label = button.textContent;
    button.disabled = true;
    button.textContent = 'Sending…';
    setStatus('login-status', 'info', '');

    try {
      const data = await window.TutorMatchAuth.forgotPassword({ email });
      setStatus(
        'login-status',
        'success',
        data.message || 'If an account exists for that email, a reset link has been sent.'
      );
    } catch (err) {
      setStatus('login-status', 'error', err.message || 'Could not send the reset link.');
    } finally {
      button.disabled = false;
      button.textContent = label;
    }
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
  $$('input[name="role"]', regForm).forEach((input) => {
    input.addEventListener('change', () => setRole(input.value));
  });

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
     Auth logic — Flask API
     The server session is authoritative. We keep only the
     current user in memory so the page can render immediately.
     ========================================================== */
  const auth = window.TutorMatchAuth;
  const getSession = () => auth.getSession();

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
    $$('[data-guest-only]').forEach((el) => {
      el.classList.toggle('hidden', signedIn);
      el.classList.toggle('flex', !signedIn);
    });
    $$('[data-user-only]').forEach((el) => el.classList.toggle('hidden', !signedIn));

    if (signedIn) {
      const first = (user.name || user.email).trim().split(/\s+/)[0];
      $('#user-name').textContent = first;
      $('#user-initial').textContent = first.charAt(0).toUpperCase();
      $('#drawer-user-name').textContent = user.name || user.email;
    }
  }

  const BUSY_LABELS = {
    login: ['Logging in…', 'Log In'],
    register: ['Creating account…', 'Create Account'],
    verify: ['Verifying…', 'Verify Email'],
    reset: ['Updating…', 'Update Password']
  };

  function setBusy(form, busy) {
    const btn = $('.submit-btn', form);
    if (!btn) return;
    const key = form === loginForm
      ? 'login'
      : form === regForm
        ? 'register'
        : form === verifyForm
          ? 'verify'
          : 'reset';
    btn.disabled = busy;
    $('span', btn).textContent = busy ? BUSY_LABELS[key][0] : BUSY_LABELS[key][1];
  }

  function applyApiError(err, statusId, fieldMap = {}) {
    const fields = (err && err.fields) || {};
    let hasFieldError = false;

    Object.entries(fields).forEach(([key, message]) => {
      const id = fieldMap[key];
      if (id) {
        setError(id, message);
        hasFieldError = true;
      }
    });

    if (hasFieldError) {
      const first = $('[aria-invalid="true"]', authModal);
      if (first) first.focus();
    }
    if (err && err.message) {
      setStatus(statusId, 'error', err.message);
    }
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
      const result = await auth.login({
        email,
        password,
        remember: $('#login-remember').checked
      });
      window.location.href = result && result.onboardingRequired
        ? 'onboarding.html'
        : 'dashboard.html#search';
    } catch (err) {
      if (err.code === 'EMAIL_NOT_VERIFIED') {
        openVerify(
          email,
          'Verify your email to finish signing in. We sent a new code to your email.'
        );
        return;
      }
      applyApiError(err, 'login-status', {
        email: 'login-email',
        password: 'login-password'
      });
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
    const role = $('input[name="role"]:checked', regForm)?.value || 'student';

    let ok = true;
    if (name.length < 2 || name.length > 80) {
      ok = setError('reg-name', 'Enter your full name (2-80 characters).') && ok;
    }
    if (!isEmail(email)) ok = setError('reg-email', 'Enter a valid email address.') && ok;
    if (password.length < 8 || !/[A-Za-z]/.test(password) || !/\d/.test(password)) {
      ok = setError('reg-password', 'Use at least 8 characters with a letter and a number.') && ok;
    }
    if (confirm !== password || !confirm) ok = setError('reg-confirm', 'Passwords don\u2019t match.') && ok;
    if (!terms) ok = setError('reg-terms', 'Please accept the terms to continue.') && ok;
    if (!ok) { $('[aria-invalid="true"]', regForm)?.focus(); return; }

    setBusy(regForm, true);
    try {
      const result = await auth.register({ name, email, password, role });
      openVerify(
        email,
        result.message || 'Account created. Check your email for the 6-digit verification code.'
      );
    } catch (err) {
      applyApiError(err, 'register-status', {
        name: 'reg-name',
        email: 'reg-email',
        password: 'reg-password'
      });
    } finally {
      setBusy(regForm, false);
    }
  });

  /* ---------- Verify email submit ---------- */
  verifyForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    clearAllErrors();

    const email = pendingEmail || (verifyEmailInput && verifyEmailInput.value) || '';
    const otp = $('#verify-otp').value.trim();

    if (!isEmail(email)) {
      setStatus('verify-status', 'error', 'Go back and log in again.');
      return;
    }
    if (!/^\d{6}$/.test(otp)) {
      setError('verify-otp', 'Enter the 6-digit code.');
      $('#verify-otp').focus();
      return;
    }

    setBusy(verifyForm, true);
    try {
      const result = await auth.verifyEmail({ email, otp });
      window.location.href = result && result.onboardingRequired
        ? 'onboarding.html'
        : 'dashboard.html#search';
    } catch (err) {
      if (err.code === 'ALREADY_VERIFIED') {
        setTab('login', { focus: false });
        $('#login-email').value = email;
        setStatus('login-status', 'success', 'Email already verified. Log in with your password.');
        $('#login-password').focus();
        return;
      }
      applyApiError(err, 'verify-status', { otp: 'verify-otp' });
    } finally {
      setBusy(verifyForm, false);
    }
  });

  /* ---------- Resend verification code ---------- */
  $('#resend-otp').addEventListener('click', async () => {
    const email = pendingEmail || (verifyEmailInput && verifyEmailInput.value) || '';
    if (!isEmail(email)) {
      setStatus('verify-status', 'error', 'Go back and log in again.');
      return;
    }

    const button = $('#resend-otp');
    const label = button.textContent;
    button.disabled = true;
    button.textContent = 'Sending…';

    try {
      const data = await auth.resendOtp({ email });
      setStatus(
        'verify-status',
        'success',
        data.message || 'If that account needs verification, a new code has been sent.'
      );
    } catch (err) {
      setStatus('verify-status', 'error', err.message || 'Could not resend the code.');
    } finally {
      button.disabled = false;
      button.textContent = label;
    }
  });

  /* ---------- Reset password submit ---------- */
  resetForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    clearAllErrors();

    const token = resetToken || (resetTokenInput && resetTokenInput.value) || '';
    const password = $('#reset-password').value;
    const confirm = $('#reset-confirm').value;

    let ok = true;
    if (!token) {
      setStatus('reset-status', 'error', 'This reset link is invalid. Request a new one.');
      ok = false;
    }
    if (password.length < 8 || !/[A-Za-z]/.test(password) || !/\d/.test(password)) {
      ok = setError('reset-password', 'Use at least 8 characters with a letter and a number.') && ok;
    }
    if (confirm !== password || !confirm) {
      ok = setError('reset-confirm', 'Passwords don\u2019t match.') && ok;
    }
    if (!ok) {
      $('[aria-invalid="true"]', resetForm)?.focus();
      return;
    }

    setBusy(resetForm, true);
    try {
      const data = await auth.resetPassword({ token, password });
      auth.clearSession();
      renderAuthState();
      resetForm.reset();
      resetToken = '';
      clearAuthQuery();
      setTab('login', { focus: false });
      if (data.email) $('#login-email').value = data.email;
      setStatus(
        'login-status',
        'success',
        data.message || 'Password updated. Please log in with your new password.'
      );
      $('#login-password').focus();
    } catch (err) {
      applyApiError(err, 'reset-status', { password: 'reset-password' });
    } finally {
      setBusy(resetForm, false);
    }
  });

  /* ---------- Logout ---------- */
  $$('[data-auth-logout]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      try {
        await auth.logout({ redirect: false });
        renderAuthState();
        setDrawer(false, { focus: false });
        showToast('You\u2019ve been logged out.');
      } catch (err) {
        showToast(err.message || 'Could not log out. Try again.');
      }
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
  setRole('student');
  updateStrength('');
  renderAuthState();

  const initialParams = new URLSearchParams(window.location.search);
  const initialResetToken = initialParams.get('reset_token');
  if (initialResetToken) {
    openReset(initialResetToken);
  } else if (initialParams.get('login') === '1') {
    openAuth('login');
  }

  auth.fetchMe().then(() => renderAuthState());
})();
