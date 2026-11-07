/* ==========================================================
   TutorMatch A.I. — Search section
   Empty state -> skeleton -> ranked results -> no-results.
   UI-only: all matching comes from js/data.js.
   ========================================================== */
(function (global) {
  'use strict';

  const auth = global.TutorMatchAuth;
  const data = global.TutorMatchData;

  let me = null;
  let els = null;
  let searchTimer = null;
  let lastFocus = null;
  let pendingSearch = false;

  const state = {
    status: 'empty',
    searched: false,
    results: []
  };

  const $ = (sel, root = document) => root.querySelector(sel);

  /* Attach this immediately, not inside init(). The dashboard waits for
     /api/auth/me before initializing modules, so a very fast click on
     Search could otherwise trigger the form's native GET fallback and
     reload the page. This listener always prevents that reload. */
  const earlyForm = $('#search-form');
  if (earlyForm) {
    earlyForm.addEventListener('submit', (event) => {
      event.preventDefault();
      if (els) runSearch();
      else pendingSearch = true;
    });
  }

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

  function roleLabel(role) {
    return role === 'tutor' ? 'Tutor' : 'Student';
  }

  function formatFormat(format) {
    if (format === 'in-person') return 'In-person';
    if (format === 'either') return 'Online or in-person';
    return 'Online';
  }

  function formatPrice(person) {
    if (person.role === 'tutor') return '$' + person.rate + ' / hr';
    return '$' + person.budget + ' budget';
  }

  function refreshIcons() {
    if (global.lucide) global.lucide.createIcons();
  }

  function showToast(message) {
    const toast = $('#toast');
    if (!toast) return;
    toast.textContent = message;
    toast.dataset.show = 'true';
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(() => { toast.dataset.show = 'false'; }, 3200);
  }

  function getFilters() {
    return {
      subject: els.subject.value,
      format: els.format.value,
      price: els.price.value,
      availability: els.availability.value,
      distance: els.distance.value
    };
  }

  function init() {
    const session = auth.getSession();
    me = data.getMe(session);

    els = {
      title: $('#search-title'),
      subtitle: $('#search-subtitle'),
      form: $('#search-form'),
      input: $('#search-input'),
      subject: $('#filter-subject'),
      format: $('#filter-format'),
      price: $('#filter-price'),
      availability: $('#filter-availability'),
      distance: $('#filter-distance'),
      clear: $('#clear-filters'),
      banner: $('#profile-banner'),
      meta: $('#results-meta'),
      state: $('#search-state')
    };

    if (!els.form) return;

    els.title.textContent = me.role === 'tutor' ? 'Find students' : 'Find a tutor';
    els.subtitle.textContent = 'Students see tutors · Tutors see students. Results appear only after you search.';

    const completeness = auth.getProfileCompleteness();
    els.banner.textContent = 'Profile ' + completeness + '% complete — add your availability and learning goal to improve your matches.';

    els.clear.addEventListener('click', clearFilters);
    els.state.addEventListener('click', handleStateClick);

    bindProfilePanel();
    renderEmpty();

    if (pendingSearch) {
      pendingSearch = false;
      runSearch();
    }
  }

  function runSearch() {
    state.searched = true;
    state.status = 'loading';
    els.meta.hidden = true;
    els.state.innerHTML = renderSkeleton();
    refreshIcons();

    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      const results = data.searchUsers(me, els.input.value.trim(), getFilters());
      state.results = results;
      state.status = results.length ? 'results' : 'no-results';
      renderResults();
    }, 800);
  }

  function clearFilters() {
    els.input.value = '';
    els.subject.value = 'all';
    els.format.value = 'any';
    els.price.value = 'any';
    els.availability.value = 'any';
    els.distance.value = '5';

    if (state.searched) runSearch();
    else renderEmpty();
  }

  function renderEmpty() {
    els.meta.hidden = true;
    els.state.innerHTML =
      '<div class="empty-state">' +
        '<div class="empty-icon"><i data-lucide="search"></i></div>' +
        '<h2>Search to see ranked matches</h2>' +
        '<p>Choose a subject or filter, then press Search. Nothing is matched until you do.</p>' +
      '</div>';
    refreshIcons();
  }

  function renderSkeleton() {
    const card = '<div class="skeleton-card">' +
      '<div class="skeleton-block skeleton-avatar"></div>' +
      '<div><div class="skeleton-block skeleton-line"></div><div class="skeleton-block skeleton-line short"></div><div class="skeleton-block skeleton-line short"></div></div>' +
      '<div class="skeleton-block skeleton-grid"></div>' +
      '<div class="skeleton-block skeleton-actions"></div>' +
    '</div>';
    return '<div class="skeleton-list" aria-label="Loading matches">' + card + card + card + '</div>';
  }

  function renderResults() {
    const count = state.results.length;
    els.meta.hidden = false;
    els.meta.textContent = count + (count === 1 ? ' result' : ' results') + ' · ranked by match score';

    if (!count) {
      els.state.innerHTML = renderNoResults();
      refreshIcons();
      return;
    }

    els.state.innerHTML = '<div class="result-list">' + state.results.map(renderCard).join('') + '</div>';
    refreshIcons();
  }

  function renderNoResults() {
    return '<div class="no-results">' +
      '<div class="empty-icon"><i data-lucide="search-x"></i></div>' +
      '<h2>No matches yet</h2>' +
      '<p>Try a broader search or clear a filter.</p>' +
      '<ul class="no-results-tips">' +
        '<li>Search a broader subject, like Mathematics instead of Algebra.</li>' +
        '<li>Increase the distance or choose Any distance.</li>' +
        '<li>Clear the price or availability filter.</li>' +
      '</ul>' +
      '<button type="button" class="btn-outline" data-action="clear">Clear filters</button>' +
    '</div>';
  }

  function renderCard(person) {
    const sent = auth.hasSentRequest(person.id);
    const reasons = (person.reasons || []).map((reason) =>
      '<li class="reason"><i data-lucide="check-circle-2"></i><span>' + escapeHtml(reason) + '</span></li>'
    ).join('');

    return '<article class="result-card" aria-labelledby="result-name-' + person.id + '">' +
      '<div class="avatar-lg" aria-hidden="true">' + initials(person.name) + '</div>' +
      '<div class="result-main">' +
        '<div class="result-name-row">' +
          '<h2 class="result-name" id="result-name-' + person.id + '">' + escapeHtml(person.name) + '</h2>' +
          '<span class="score-pill">' + person.score + '% match</span>' +
        '</div>' +
        '<p class="result-line">' + formatFormat(person.format) + ' · ' + formatPrice(person) + ' · ' + person.distanceKm.toFixed(1) + ' km</p>' +
        '<p class="why-label">Why this match</p>' +
        '<ul class="reason-list">' + reasons + '</ul>' +
      '</div>' +
      '<div class="availability" aria-label="Availability for ' + escapeHtml(person.name) + '">' +
        '<span class="availability-title">Availability</span>' +
        renderAvailability(person.availability) +
      '</div>' +
      '<div class="result-actions">' +
        '<button type="button" class="btn-dark-sm" data-action="request" data-id="' + person.id + '"' + (sent ? ' disabled' : '') + '>' + (sent ? 'Request sent' : 'Send Request') + '</button>' +
        '<button type="button" class="btn-outline" data-action="profile" data-id="' + person.id + '">View Profile</button>' +
      '</div>' +
    '</article>';
  }

  function renderAvailability(grid) {
    const days = data.DAYS;
    const labels = data.DAY_LABELS;
    const slots = data.SLOTS;
    const open = (grid || []).flat().filter(Boolean).length;
    let html = '<div class="avail-grid" role="img" aria-label="' + open + ' available slots across the week">';

    days.forEach((day) => {
      html += '<span class="avail-day" aria-hidden="true">' + day + '</span>';
    });

    for (let slot = 0; slot < 3; slot += 1) {
      for (let day = 0; day < 7; day += 1) {
        const on = Boolean(grid && grid[slot] && grid[slot][day]);
        html += '<span class="slot' + (on ? ' on' : '') + '" title="' + labels[day] + ' ' + slots[slot] + ': ' + (on ? 'available' : 'not available') + '"></span>';
      }
    }

    html += '</div>';
    return html;
  }

  function handleStateClick(event) {
    const button = event.target.closest('[data-action]');
    if (!button) return;

    if (button.dataset.action === 'clear') {
      clearFilters();
      return;
    }

    const person = state.results.find((item) => item.id === button.dataset.id);
    if (!person) return;

    if (button.dataset.action === 'request') {
      auth.saveSentRequest(person);
      button.disabled = true;
      button.textContent = 'Request sent';
      showToast('Request sent to ' + person.name + '.');
      global.dispatchEvent(new CustomEvent('tutormatch:request-sent'));
      return;
    }

    if (button.dataset.action === 'profile') {
      openProfilePanel(person);
    }
  }

  function bindProfilePanel() {
    const panel = $('#profile-panel');
    if (!panel) return;

    panel.addEventListener('click', (event) => {
      if (event.target.closest('[data-close-panel]')) closeProfilePanel();
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && panel.dataset.open === 'true') closeProfilePanel();
    });
  }

  function openProfilePanel(person) {
    const panel = $('#profile-panel');
    const body = $('#profile-panel-body');
    if (!panel || !body) return;

    lastFocus = document.activeElement;
    $('#profile-panel-title').textContent = person.name;
    body.innerHTML = renderProfile(person);
    panel.dataset.open = 'true';
    document.body.style.overflow = 'hidden';
    refreshIcons();

    setTimeout(() => {
      const close = $('.icon-btn', panel);
      if (close) close.focus();
    }, 60);
  }

  function closeProfilePanel() {
    const panel = $('#profile-panel');
    if (!panel || panel.dataset.open !== 'true') return;
    panel.dataset.open = 'false';
    document.body.style.overflow = '';
    if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
  }

  function renderProfile(person) {
    const subjects = (person.subjects || []).map((subject) =>
      '<span class="subject-chip">' + escapeHtml(subject) + '</span>'
    ).join('');

    return '<div class="profile-hero">' +
        '<div class="profile-avatar" aria-hidden="true">' + initials(person.name) + '</div>' +
        '<div>' +
          '<h3>' + escapeHtml(person.name) + '</h3>' +
          '<p class="profile-role">' + roleLabel(person.role) + ' · ' + formatFormat(person.format) + '</p>' +
          '<span class="score-pill">' + person.score + '% match</span>' +
        '</div>' +
      '</div>' +
      '<div class="profile-section">' +
        '<h4>About</h4>' +
        '<p class="profile-bio">' + escapeHtml(person.bio || 'No bio added yet.') + '</p>' +
      '</div>' +
      '<div class="profile-section">' +
        '<h4>Subjects</h4>' +
        '<div class="profile-subjects">' + subjects + '</div>' +
      '</div>' +
      '<div class="profile-section">' +
        '<h4>Availability</h4>' +
        renderAvailability(person.availability) +
      '</div>' +
      '<div class="profile-section">' +
        '<h4>Details</h4>' +
        '<div class="profile-meta-grid">' +
          '<div class="meta-box"><span>' + (person.role === 'tutor' ? 'Rate' : 'Budget') + '</span><strong>' + formatPrice(person) + '</strong></div>' +
          '<div class="meta-box"><span>Format</span><strong>' + formatFormat(person.format) + '</strong></div>' +
          '<div class="meta-box"><span>Approx. area</span><strong>' + escapeHtml(person.area) + '</strong></div>' +
          '<div class="meta-box"><span>Distance</span><strong>' + person.distanceKm.toFixed(1) + ' km away</strong></div>' +
        '</div>' +
      '</div>' +
      '<p class="profile-note">Location is shown at barangay level only. Exact addresses are never public.</p>';
  }

  global.TutorMatchSearch = { init, runSearch, clearFilters, getState: () => state };
})(window);
