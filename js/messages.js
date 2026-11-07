/* ==========================================================
   TutorMatch A.I. — Messages section (Phase 1)
   Shows the sent-request list saved by Search.
   ========================================================== */
(function (global) {
  'use strict';

  const auth = global.TutorMatchAuth;

  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function initials(name) {
    return String(name || '?')
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((part) => part.charAt(0).toUpperCase())
      .join('');
  }

  function formatDate(timestamp) {
    if (!timestamp) return '';
    try {
      return new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric' }).format(new Date(timestamp));
    } catch {
      return '';
    }
  }

  function render() {
    const target = document.getElementById('sent-requests');
    if (!target) return;

    const list = auth.getSentRequests();
    if (!list.length) {
      target.innerHTML =
        '<div class="empty-state" style="border:0;padding:2rem 1rem;">' +
          '<div class="empty-icon"><i data-lucide="send"></i></div>' +
          '<h2>No requests sent yet</h2>' +
          '<p>Search for a match and press Send Request. It will appear here.</p>' +
        '</div>';
      if (global.lucide) global.lucide.createIcons();
      return;
    }

    target.innerHTML = list.map((item) => {
      const role = item.role === 'tutor' ? 'Tutor' : 'Student';
      const subjects = (item.subjects || []).slice(0, 2).join(' & ');
      return '<div class="sent-item">' +
        '<div class="user-avatar" aria-hidden="true">' + initials(item.name) + '</div>' +
        '<div class="sent-main">' +
          '<strong>' + escapeHtml(item.name) + '</strong>' +
          '<span>' + role + (subjects ? ' · ' + escapeHtml(subjects) : '') + (item.sentAt ? ' · ' + formatDate(item.sentAt) : '') + '</span>' +
        '</div>' +
        '<span class="sent-status">' + escapeHtml(item.status || 'pending') + '</span>' +
      '</div>';
    }).join('');

    if (global.lucide) global.lucide.createIcons();
  }

  function init() {
    render();
    global.addEventListener('tutormatch:request-sent', render);
  }

  global.TutorMatchMessages = { init, render };
})(window);
