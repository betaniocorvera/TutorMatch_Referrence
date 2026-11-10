/* ==========================================================
   TutorMatch A.I. — dashboard shell, user chip, hash routing
   ========================================================== */
(function (global) {
  'use strict';

  const auth = global.TutorMatchAuth;

  (async function initDashboard() {
    /* Ask Flask who is logged in. The server session cookie is the
       source of truth, not a localStorage value. */
    const session = await auth.requireSession();
    if (!session) return;

    const $ = (sel) => document.querySelector(sel);
    const sections = ['search', 'profile', 'messages', 'notifications'];
    const sidebar = $('#sidebar');
    const scrim = $('#sidebar-scrim');
    const openButton = $('#sidebar-open');
    const closeButton = $('#sidebar-close');
    const toast = $('#toast');
    let toastTimer;

    function showToast(message) {
      if (!toast) return;
      toast.textContent = message;
      toast.dataset.show = 'true';
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => {
        toast.dataset.show = 'false';
      }, 3200);
    }

    function initials(name) {
      return String(name || '?')
        .trim()
        .split(/\s+/)
        .slice(0, 2)
        .map((part) => part.charAt(0).toUpperCase())
        .join('');
    }

    function setUserChip() {
      const name = session.name || session.email || 'Student Name';
      const role = session.role === 'tutor' ? 'Tutor' : 'Student';
      const nameEl = $('#sidebar-name');
      const roleEl = $('#sidebar-role');
      const avatar = $('#sidebar-avatar');

      if (nameEl) nameEl.textContent = name;
      if (roleEl) roleEl.textContent = role;
      if (avatar) avatar.textContent = initials(name);
    }

    function setSidebar(open, options) {
      const focus = !options || options.focus !== false;
      if (!sidebar) return;

      sidebar.dataset.open = String(open);
      if (scrim) scrim.dataset.open = String(open);
      if (openButton) openButton.setAttribute('aria-expanded', String(open));
      document.body.classList.toggle('drawer-open', open);

      if (focus) {
        if (open && closeButton) closeButton.focus();
        else if (!open && openButton && openButton.offsetParent !== null) openButton.focus();
      }
    }

    function applySection(name) {
      sections.forEach((section) => {
        const el = document.getElementById('section-' + section);
        if (el) el.classList.toggle('hidden', section !== name);
      });

      document.querySelectorAll('.side-link').forEach((link) => {
        const active = link.dataset.section === name;
        link.classList.toggle('active', active);
        if (active) link.setAttribute('aria-current', 'page');
        else link.removeAttribute('aria-current');
      });

      if (name === 'profile' && global.TutorMatchProfile) global.TutorMatchProfile.render();
      if (name === 'messages' && global.TutorMatchMessages) global.TutorMatchMessages.render();
      if (name === 'notifications' && global.TutorMatchNotifications) {
        global.TutorMatchNotifications.render();
      }

      setSidebar(false, { focus: false });
    }

    function handleHash() {
      if (!global.location.hash) {
        try {
          global.history.replaceState(null, '', '#search');
        } catch {
          global.location.hash = 'search';
        }
      }
      const raw = (global.location.hash || '#search').replace('#', '');
      const name = sections.indexOf(raw) !== -1 ? raw : 'search';
      if (name !== raw) {
        try {
          global.history.replaceState(null, '', '#search');
        } catch {
          global.location.hash = 'search';
        }
      }
      applySection(name);
    }

    setUserChip();

    if (openButton) openButton.addEventListener('click', () => setSidebar(true));
    if (closeButton) closeButton.addEventListener('click', () => setSidebar(false));
    if (scrim) scrim.addEventListener('click', () => setSidebar(false));

    document.querySelectorAll('.side-link').forEach((link) => {
      link.addEventListener('click', () => setSidebar(false, { focus: false }));
    });

    const logoutButton = $('#logout-btn');
    if (logoutButton) {
      logoutButton.addEventListener('click', async () => {
        logoutButton.disabled = true;
        try {
          await auth.logout();
        } catch (err) {
          logoutButton.disabled = false;
          showToast(err.message || 'Could not log out. Try again.');
        }
      });
    }

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && sidebar && sidebar.dataset.open === 'true') {
        setSidebar(false);
      }
    });

    // Load outgoing request state once so Search can render the correct
    // button label without making the search itself automatic.
    await auth.loadSentRequests().catch(() => {});

    if (global.TutorMatchSearch) global.TutorMatchSearch.init();
    if (global.TutorMatchProfile) global.TutorMatchProfile.init();
    if (global.TutorMatchMessages) global.TutorMatchMessages.init();
    if (global.TutorMatchNotifications) global.TutorMatchNotifications.init();

    global.addEventListener('hashchange', handleHash);
    handleHash();

    if (global.lucide) global.lucide.createIcons();
  })();
})(window);
