/* ==========================================================
   TutorMatch A.I. — Profile section (Phase 1 shell)
   ========================================================== */
(function (global) {
  'use strict';

  const auth = global.TutorMatchAuth;

  function initials(name) {
    return String(name || '?')
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((part) => part.charAt(0).toUpperCase())
      .join('');
  }

  function render() {
    const session = auth.getSession();
    if (!session) return;

    const name = session.name || session.email || 'Student Name';
    const role = session.role === 'tutor' ? 'Tutor' : 'Student';
    const percent = auth.getProfileCompleteness();

    const avatar = document.getElementById('profile-page-avatar');
    const nameEl = document.getElementById('profile-page-name');
    const roleEl = document.getElementById('profile-page-role');
    const emailEl = document.getElementById('profile-page-email');
    const percentEl = document.getElementById('profile-page-percent');
    const fill = document.getElementById('profile-page-fill');
    const track = document.querySelector('.completeness-track');

    if (avatar) avatar.textContent = initials(name);
    if (nameEl) nameEl.textContent = name;
    if (roleEl) roleEl.textContent = role;
    if (emailEl) emailEl.textContent = session.email || '';
    if (percentEl) percentEl.textContent = percent + '%';
    if (fill) fill.style.width = percent + '%';
    if (track) track.setAttribute('aria-valuenow', String(percent));
  }

  global.TutorMatchProfile = { init: render, render };
})(window);
