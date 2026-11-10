/* ==========================================================
   TutorMatch A.I. — Search section
   Empty state -> skeleton -> API-backed ranked results.
   Search is explicit: the API is only called after the user
   submits the form (or changes a filter after a search).
   ========================================================== */
(function (global) {
  'use strict';

  const auth = global.TutorMatchAuth;
  const data = global.TutorMatchData;
  const PAGE_SIZE = 10;

  let me = null;
  let profile = null;
  let els = null;
  let lastFocus = null;
  let pendingSearch = false;
  let requestSeq = 0;
  let currentPanelResult = null;

  const state = {
    status: 'empty',
    searched: false,
    results: [],
    total: 0,
    page: 1,
    limit: PAGE_SIZE,
    relaxedFilters: [],
    suggestions: [],
    error: '',
    loadingMore: false
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

  function levelLabel(level) {
    return (data.LEVEL_LABELS && data.LEVEL_LABELS[level]) || level || '';
  }

  function formatFormat(format) {
    if (format === 'in_person') return 'In-person';
    if (format === 'both') return 'Online or in-person';
    if (format === 'online') return 'Online';
    return 'Format not set';
  }

  function formatMoney(centavos) {
    if (centavos === null || centavos === undefined || centavos === '') return null;
    const pesos = Number(centavos) / 100;
    if (!Number.isFinite(pesos)) return null;
    const hasCents = Math.round(pesos * 100) % 100 !== 0;
    return '₱' + pesos.toLocaleString('en-PH', {
      minimumFractionDigits: hasCents ? 2 : 0,
      maximumFractionDigits: hasCents ? 2 : 0
    });
  }

  function formatPrice(person) {
    if (!person) return 'Price not set';
    if (person.role === 'tutor') {
      const rate = formatMoney(person.rateCentavos);
      return rate ? rate + ' / hr' : 'Rate not set';
    }
    const min = formatMoney(person.budgetMinCentavos);
    const max = formatMoney(person.budgetMaxCentavos);
    return min && max ? min + '–' + max + ' budget' : 'Budget not set';
  }

  function formatDistance(meters) {
    if (meters === null || meters === undefined || meters === '') {
      return 'Distance unavailable';
    }
    const value = Number(meters);
    if (!Number.isFinite(value)) return 'Distance unavailable';
    if (value === 0) return 'Same barangay';
    if (value < 1000) return value + ' m away';
    return (value / 1000).toFixed(1) + ' km away';
  }

  function formatLastActive(value) {
    if (!value) return '';
    try {
      return new Intl.DateTimeFormat('en', {
        month: 'short',
        day: 'numeric'
      }).format(new Date(value));
    } catch {
      return '';
    }
  }

  function bandForScore(score) {
    const value = Number(score);
    if (value >= 85) return 'excellent';
    if (value >= 70) return 'good';
    if (value >= 50) return 'fair';
    return 'low';
  }

  function bandLabel(band) {
    return {
      excellent: 'Excellent fit',
      good: 'Good fit',
      fair: 'Fair fit',
      low: 'Low match'
    }[band] || 'Match';
  }

  function toMinutes(value) {
    if (value === '24:00') return 24 * 60;
    const parts = String(value || '0:0').split(':');
    const hours = Number(parts[0]) || 0;
    const minutes = Number(parts[1]) || 0;
    return hours * 60 + minutes;
  }

  function overlapsWindow(slot, window) {
    if (!slot || !window) return false;
    const start = Math.max(toMinutes(slot.start), toMinutes(window.start));
    const end = Math.min(toMinutes(slot.end), toMinutes(window.end));
    return end > start;
  }

  function buildAvailabilityGrid(slots) {
    const grid = data.SLOTS.map(() => data.DAY_IDS.map(() => false));
    (slots || []).forEach((slot) => {
      const dayIndex = data.DAY_IDS.indexOf(slot.day);
      if (dayIndex === -1) return;
      data.SLOTS.forEach((window, row) => {
        if (overlapsWindow(slot, window)) grid[row][dayIndex] = true;
      });
    });
    return grid;
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
      level: els.level.value,
      format: els.format.value,
      price: els.price.value,
      availability: els.availability.value,
      distance: els.distance.value,
      sort: els.sort.value
    };
  }

  function updateRoleLabels() {
    if (!els) return;
    const isStudent = me.role === 'student';
    if (els.priceLabel) {
      els.priceLabel.textContent = isStudent ? 'Max rate' : 'Student budget';
    }
    els.price.querySelectorAll('option').forEach((option) => {
      const label = option.dataset[isStudent ? 'studentLabel' : 'tutorLabel'];
      if (label) option.textContent = label;
    });
    const thirdSort = els.sort.querySelector('option[data-sort-third]');
    if (thirdSort) {
      thirdSort.value = isStudent ? 'rate' : 'budget';
      thirdSort.textContent = isStudent ? 'Lowest rate' : 'Highest budget';
    }
  }

  function init() {
    const session = auth.getSession();
    profile = auth.getProfile();
    me = {
      id: (profile && profile.userId) || (session && session.id),
      role: (profile && profile.role) || (session && session.role) || 'student',
      name: (profile && profile.name) || (session && session.name) || ''
    };

    els = {
      title: $('#search-title'),
      subtitle: $('#search-subtitle'),
      form: $('#search-form'),
      input: $('#search-input'),
      subject: $('#filter-subject'),
      level: $('#filter-level'),
      format: $('#filter-format'),
      price: $('#filter-price'),
      priceLabel: $('#filter-price-label'),
      availability: $('#filter-availability'),
      distance: $('#filter-distance'),
      sort: $('#sort-results'),
      count: $('#results-count'),
      clear: $('#clear-filters'),
      banner: $('#profile-banner'),
      meta: $('#results-meta'),
      state: $('#search-state')
    };

    if (!els.form) return;

    els.title.textContent = me.role === 'tutor' ? 'Find students' : 'Find a tutor';
    els.subtitle.textContent = 'Students see tutors · Tutors see students. Results appear only after you search.';

    const completeness = auth.getProfileCompleteness();
    els.banner.textContent = completeness >= 100
      ? 'Profile 100% complete — your profile is ready for search.'
      : 'Profile ' + completeness + '% complete — finish the remaining items in your profile to improve your matches.';

    updateRoleLabels();
    els.clear.addEventListener('click', clearFilters);
    els.state.addEventListener('click', handleStateClick);
    els.sort.addEventListener('change', () => {
      if (state.searched) runSearch();
    });
    [els.subject, els.level, els.format, els.price, els.availability, els.distance]
      .forEach((control) => {
        control.addEventListener('change', () => {
          if (state.searched) runSearch();
        });
      });

    bindProfilePanel();
    renderEmpty();

    if (pendingSearch) {
      pendingSearch = false;
      runSearch();
    }
  }

  function buildSearchParams(page) {
    const params = new URLSearchParams();
    const query = els.input.value.trim();
    if (query) params.set('q', query);
    if (els.subject.value !== 'all') params.set('subjectId', els.subject.value);
    if (els.level.value !== 'any') params.set('level', els.level.value);
    if (els.format.value !== 'any') params.set('format', els.format.value);
    if (els.price.value !== 'any') {
      if (me.role === 'student') params.set('maxRateCentavos', els.price.value);
      else params.set('minBudgetCentavos', els.price.value);
    }
    if (els.availability.value !== 'any') {
      params.set('availability', els.availability.value);
    }
    if (els.distance.value !== 'any') {
      params.set('maxDistanceMeters', String(Number(els.distance.value) * 1000));
    }
    params.set('sort', els.sort.value || 'score');
    params.set('page', String(page));
    params.set('limit', String(PAGE_SIZE));
    return params;
  }

  async function runSearch() {
    if (!els || !me) return;
    state.searched = true;
    state.status = 'loading';
    state.loadingMore = false;
    state.error = '';
    els.meta.hidden = true;
    els.state.innerHTML = renderSkeleton();
    refreshIcons();

    const seq = ++requestSeq;
    const path = me.role === 'student' ? '/api/search/tutors' : '/api/search/students';
    try {
      const payload = await auth.apiFetch(
        path + '?' + buildSearchParams(1).toString()
      );
      if (seq !== requestSeq) return;
      state.results = payload.results || [];
      state.total = payload.total || 0;
      state.page = payload.page || 1;
      state.limit = payload.limit || PAGE_SIZE;
      state.relaxedFilters = payload.relaxedFilters || [];
      state.suggestions = payload.suggestions || [];
      state.status = state.results.length ? 'results' : 'no-results';
      renderResults();
    } catch (err) {
      if (seq !== requestSeq) return;
      state.status = 'error';
      state.error = err.message || 'Could not load matches.';
      renderError();
    }
  }

  async function loadMore() {
    if (!els || state.loadingMore || state.results.length >= state.total) return;
    state.loadingMore = true;
    renderResults();

    const seq = ++requestSeq;
    const path = me.role === 'student' ? '/api/search/tutors' : '/api/search/students';
    try {
      const payload = await auth.apiFetch(
        path + '?' + buildSearchParams(state.page + 1).toString()
      );
      if (seq !== requestSeq) return;
      state.results = state.results.concat(payload.results || []);
      state.total = payload.total || state.total;
      state.page = payload.page || state.page + 1;
      state.relaxedFilters = payload.relaxedFilters || state.relaxedFilters;
      state.suggestions = payload.suggestions || state.suggestions;
      state.loadingMore = false;
      state.status = state.results.length ? 'results' : 'no-results';
      renderResults();
    } catch (err) {
      if (seq !== requestSeq) return;
      state.loadingMore = false;
      showToast(err.message || 'Could not load more matches.');
      renderResults();
    }
  }

  function clearFilters() {
    els.input.value = '';
    els.subject.value = 'all';
    els.level.value = 'any';
    els.format.value = 'any';
    els.price.value = 'any';
    els.availability.value = 'any';
    els.distance.value = '5';
    els.sort.value = 'score';

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
    const loaded = state.results.length;
    const total = state.total;
    els.meta.hidden = false;
    const countText = total + (total === 1 ? ' match' : ' matches');
    const showing = loaded < total ? ' · showing ' + loaded : '';
    els.count.textContent = countText + showing + ' · ranked by ' + sortLabel();

    if (!loaded) {
      els.state.innerHTML = renderNoResults();
      refreshIcons();
      return;
    }

    let html = '';
    if (state.relaxedFilters.length) html += renderRelaxedNotice();
    html += '<div class="result-list">' + state.results.map(renderCard).join('') + '</div>';
    if (loaded < total) {
      html += '<div class="load-more-wrap"><button type="button" class="btn-outline load-more" data-action="more"' +
        (state.loadingMore ? ' disabled' : '') + '>' +
        (state.loadingMore ? 'Loading…' : 'Load more (' + (total - loaded) + ' left)') +
        '</button></div>';
    }
    els.state.innerHTML = html;
    refreshIcons();
  }

  function sortLabel() {
    if (els.sort.value === 'distance') return 'nearest';
    if (els.sort.value === 'rate') return 'lowest rate';
    if (els.sort.value === 'budget') return 'highest budget';
    return 'match score';
  }

  function renderRelaxedNotice() {
    const names = state.relaxedFilters
      .map((item) => item === 'distance' ? 'Distance' : item)
      .join(', ');
    return '<div class="relaxed-notice" role="status">' +
      '<i data-lucide="sliders-horizontal"></i>' +
      '<p>Some filters were relaxed to show more matches: <strong>' + escapeHtml(names) + '</strong>.</p>' +
    '</div>';
  }

  function renderNoResults() {
    const tips = state.suggestions.length
      ? state.suggestions
      : ['Try a broader search or clear a filter.'];
    return '<div class="no-results">' +
      '<div class="empty-icon"><i data-lucide="search-x"></i></div>' +
      '<h2>No matches yet</h2>' +
      '<p>Try a broader search or clear a filter.</p>' +
      '<ul class="no-results-tips">' +
        tips.map((tip) => '<li>' + escapeHtml(tip) + '</li>').join('') +
      '</ul>' +
      '<button type="button" class="btn-outline" data-action="clear">Clear filters</button>' +
    '</div>';
  }

  function renderError() {
    els.meta.hidden = true;
    els.state.innerHTML = '<div class="no-results">' +
      '<div class="empty-icon"><i data-lucide="wifi-off"></i></div>' +
      '<h2>Could not load matches</h2>' +
      '<p>' + escapeHtml(state.error) + '</p>' +
      '<button type="button" class="btn-outline" data-action="retry">Try again</button>' +
    '</div>';
    refreshIcons();
  }

  function renderAvatar(person, className) {
    if (person && person.photoUrl) {
      return '<div class="' + className + '" aria-hidden="true"><img src="' +
        escapeHtml(person.photoUrl) + '" alt="" /></div>';
    }
    return '<div class="' + className + '" aria-hidden="true">' +
      initials(person && person.name) + '</div>';
  }

  function renderCard(result) {
    const person = result.profile || {};
    const match = result.match || {};
    const id = person.userId;
    const sent = auth.hasSentRequest(id);
    const score = Number.isFinite(Number(match.score)) ? Number(match.score) : 0;
    const band = match.band || bandForScore(score);
    const reasons = (match.reasons || []).map((reason) =>
      '<li class="reason"><i data-lucide="check-circle-2"></i><span>' +
        escapeHtml(reason.label || reason) + '</span></li>'
    ).join('');
    const warnings = (match.warnings || []).map((warning) =>
      '<li class="warning"><i data-lucide="alert-circle"></i><span>' +
        escapeHtml(warning) + '</span></li>'
    ).join('');
    const subjects = (person.subjects || []).slice(0, 4).map((subject) =>
      '<span class="subject-chip">' + escapeHtml(subject.name) +
        (subject.level ? ' · ' + escapeHtml(levelLabel(subject.level)) : '') +
      '</span>'
    ).join('');
    const area = person.area || {};
    const areaText = [area.barangay, area.city].filter(Boolean).join(', ');

    return '<article class="result-card" aria-labelledby="result-name-' + escapeHtml(id) + '">' +
      renderAvatar(person, 'avatar-lg') +
      '<div class="result-main">' +
        '<div class="result-name-row">' +
          '<h2 class="result-name" id="result-name-' + escapeHtml(id) + '">' +
            escapeHtml(person.name || 'Profile') + '</h2>' +
          (person.verified
            ? '<span class="verified-badge" title="Verified profile"><i data-lucide="badge-check"></i></span>'
            : '') +
          '<span class="score-pill">' + score + '% match</span>' +
          '<span class="band-chip band-' + escapeHtml(band) + '">' +
            escapeHtml(bandLabel(band)) + '</span>' +
        '</div>' +
        '<p class="result-line">' + escapeHtml(formatFormat(person.format)) +
          ' · ' + escapeHtml(formatPrice(person)) + '</p>' +
        '<p class="result-line result-area">' +
          escapeHtml(areaText || 'Area not set') + ' · ' +
          escapeHtml(formatDistance(person.distanceMeters)) + '</p>' +
        (subjects ? '<div class="result-subjects">' + subjects + '</div>' : '') +
        (reasons
          ? '<p class="why-label">Why this match</p><ul class="reason-list">' + reasons + '</ul>'
          : '') +
        (warnings ? '<ul class="warning-list">' + warnings + '</ul>' : '') +
      '</div>' +
      '<div class="availability" aria-label="Availability for ' +
        escapeHtml(person.name || 'this profile') + '">' +
        '<span class="availability-title">Availability</span>' +
        renderAvailability(person.availability, match.availabilityOverlap) +
      '</div>' +
      '<div class="result-actions">' +
        '<button type="button" class="btn-dark-sm" data-action="request" data-id="' +
          escapeHtml(id) + '"' + (sent ? ' disabled' : '') + '>' +
          (sent ? 'Request sent' : 'Send Request') + '</button>' +
        '<button type="button" class="btn-outline" data-action="profile" data-id="' +
          escapeHtml(id) + '">View Profile</button>' +
      '</div>' +
    '</article>';
  }

  function renderAvailability(availability, overlap) {
    const onGrid = buildAvailabilityGrid(availability);
    const overlapGrid = buildAvailabilityGrid(overlap);
    let open = 0;
    let overlapping = 0;
    onGrid.forEach((row) => row.forEach((cell) => { if (cell) open += 1; }));
    overlapGrid.forEach((row) => row.forEach((cell) => { if (cell) overlapping += 1; }));

    let html = '<div class="avail-grid" role="img" aria-label="' + open +
      ' available slots across the week' +
      (overlapping ? '; ' + overlapping + ' overlap with your availability' : '') +
      '">';

    data.DAYS.forEach((day) => {
      html += '<span class="avail-day" aria-hidden="true">' + day + '</span>';
    });

    for (let slot = 0; slot < data.SLOTS.length; slot += 1) {
      for (let day = 0; day < 7; day += 1) {
        const on = Boolean(onGrid[slot] && onGrid[slot][day]);
        const isOverlap = Boolean(overlapGrid[slot] && overlapGrid[slot][day]);
        const label = data.DAY_LABELS[day] + ' ' + data.SLOTS[slot].label + ': ' +
          (isOverlap ? 'overlaps your availability' : on ? 'available' : 'not available');
        html += '<span class="slot' + (on ? ' on' : '') +
          (isOverlap ? ' overlap' : '') + '" title="' + escapeHtml(label) + '"></span>';
      }
    }

    html += '</div>';
    return html;
  }

  function handleStateClick(event) {
    const button = event.target.closest('[data-action]');
    if (!button) return;

    const action = button.dataset.action;
    if (action === 'clear') {
      clearFilters();
      return;
    }
    if (action === 'retry') {
      runSearch();
      return;
    }
    if (action === 'more') {
      loadMore();
      return;
    }

    const result = state.results.find((item) =>
      String(item.profile.userId) === String(button.dataset.id)
    );
    if (!result) return;

    if (action === 'request') {
      sendRequest(result, button);
      return;
    }
    if (action === 'profile') {
      openProfilePanel(result);
    }
  }

  function pickRequestSubject(result) {
    const subjects = (result.profile && result.profile.subjects) || [];
    if (!subjects.length) return null;
    const selected = els.subject ? els.subject.value : '';
    if (selected) {
      const match = subjects.find((subject) => String(subject.id) === String(selected));
      if (match) return match;
    }
    return subjects[0];
  }

  function setRequestButtonState(personId, label, disabled, sourceButton) {
    document.querySelectorAll('[data-action="request"]').forEach((cardButton) => {
      if (String(cardButton.dataset.id) === String(personId)) {
        cardButton.disabled = disabled;
        cardButton.textContent = label;
      }
    });
    if (sourceButton) {
      sourceButton.disabled = disabled;
      sourceButton.textContent = label;
    }
    const panelButton = document.querySelector('[data-panel-action="request"]');
    if (
      panelButton &&
      currentPanelResult &&
      String(currentPanelResult.profile.userId) === String(personId)
    ) {
      panelButton.disabled = disabled;
      panelButton.textContent = label;
    }
  }

  async function sendRequest(result, button) {
    const person = result.profile || {};
    const subject = pickRequestSubject(result);
    const match = result.match || {};
    const slots = Array.isArray(match.availabilityOverlap)
      ? match.availabilityOverlap.slice(0, 4)
      : [];
    const subjectName = subject ? subject.name : 'tutoring';

    setRequestButtonState(person.userId, 'Sending...', true, button);
    try {
      const data = await auth.createRequest({
        toUserId: person.userId,
        subjectId: subject ? subject.id : null,
        message: 'Hi! I would like to connect about ' + subjectName + '.',
        preferredSlots: slots,
        format: person.format || null
      });
      setRequestButtonState(person.userId, 'Request sent', true, button);
      showToast('Request sent to ' + person.name + '.');
      global.dispatchEvent(new CustomEvent('tutormatch:request-sent', {
        detail: { request: data.request }
      }));
    } catch (error) {
      if (error.code === 'CONFLICT') {
        auth.loadSentRequests().catch(() => {});
        setRequestButtonState(person.userId, 'Request sent', true, button);
        showToast('You already have a pending request with ' + person.name + '.');
        return;
      }
      setRequestButtonState(person.userId, 'Send Request', false, button);
      showToast(error.message || 'Could not send the request.');
    }
  }

  function bindProfilePanel() {
    const panel = $('#profile-panel');
    if (!panel) return;

    panel.addEventListener('click', (event) => {
      if (event.target.closest('[data-close-panel]')) {
        closeProfilePanel();
        return;
      }
      const action = event.target.closest('[data-panel-action]');
      if (action && currentPanelResult && action.dataset.panelAction === 'request') {
        sendRequest(currentPanelResult, action);
      }
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && panel.dataset.open === 'true') {
        closeProfilePanel();
      }
    });
  }

  function openProfilePanel(result) {
    const panel = $('#profile-panel');
    const body = $('#profile-panel-body');
    if (!panel || !body) return;

    currentPanelResult = result;
    lastFocus = document.activeElement;
    $('#profile-panel-title').textContent = (result.profile && result.profile.name) || 'Profile';
    body.innerHTML = renderProfile(result.profile, result.match);
    panel.dataset.open = 'true';
    document.body.style.overflow = 'hidden';
    refreshIcons();

    setTimeout(() => {
      const close = $('.icon-btn', panel);
      if (close) close.focus();
    }, 60);

    const profileId = result.profile && result.profile.id;
    if (profileId === undefined || profileId === null) return;
    auth.apiFetch('/api/profiles/' + encodeURIComponent(profileId))
      .then((payload) => {
        if (!payload || !payload.profile || panel.dataset.open !== 'true') return;
        if (!currentPanelResult || currentPanelResult.profile.id !== profileId) return;
        currentPanelResult = { ...currentPanelResult, profile: payload.profile };
        body.innerHTML = renderProfile(payload.profile, currentPanelResult.match);
        refreshIcons();
      })
      .catch(() => {
        /* The search result already has the public fields; keep it. */
      });
  }

  function closeProfilePanel() {
    const panel = $('#profile-panel');
    if (!panel || panel.dataset.open !== 'true') return;
    panel.dataset.open = 'false';
    document.body.style.overflow = '';
    currentPanelResult = null;
    if (lastFocus && document.contains(lastFocus)) lastFocus.focus();
  }

  function renderProfile(person, match) {
    const subjects = (person.subjects || []).map((subject) =>
      '<span class="subject-chip">' + escapeHtml(subject.name) +
        ' · ' + escapeHtml(levelLabel(subject.level)) + '</span>'
    ).join('');
    const reasons = ((match && match.reasons) || []).map((reason) =>
      '<li class="reason"><i data-lucide="check-circle-2"></i><span>' +
        escapeHtml(reason.label || reason) + '</span></li>'
    ).join('');
    const warnings = ((match && match.warnings) || []).map((warning) =>
      '<li class="warning"><i data-lucide="alert-circle"></i><span>' +
        escapeHtml(warning) + '</span></li>'
    ).join('');
    const sent = auth.hasSentRequest(person.userId);
    const score = match && Number.isFinite(Number(match.score))
      ? Number(match.score)
      : null;
    const band = (match && match.band) || (score != null ? bandForScore(score) : null);
    const area = person.area || {};
    const areaText = [area.barangay, area.city].filter(Boolean).join(', ') || 'Not set';

    return '<div class="profile-hero">' +
        renderAvatar(person, 'profile-avatar') +
        '<div>' +
          '<h3>' + escapeHtml(person.name || 'Profile') +
            (person.verified
              ? ' <span class="verified-badge" title="Verified profile"><i data-lucide="badge-check"></i></span>'
              : '') +
          '</h3>' +
          '<p class="profile-role">' + roleLabel(person.role) + ' · ' +
            escapeHtml(formatFormat(person.format)) + '</p>' +
          (score != null
            ? '<span class="score-pill">' + score + '% match</span> ' +
              '<span class="band-chip band-' + escapeHtml(band) + '">' +
              escapeHtml(bandLabel(band)) + '</span>'
            : '') +
        '</div>' +
      '</div>' +
      '<div class="profile-section">' +
        '<h4>About</h4>' +
        '<p class="profile-bio">' + escapeHtml(person.bio || 'No bio added yet.') + '</p>' +
      '</div>' +
      '<div class="profile-section">' +
        '<h4>Subjects</h4>' +
        '<div class="profile-subjects">' +
          (subjects || '<span class="muted-note">No subjects listed.</span>') +
        '</div>' +
      '</div>' +
      '<div class="profile-section">' +
        '<h4>Availability</h4>' +
        renderAvailability(person.availability, match && match.availabilityOverlap) +
      '</div>' +
      (reasons
        ? '<div class="profile-section"><h4>Why this match</h4>' +
          '<ul class="reason-list">' + reasons + '</ul></div>'
        : '') +
      (warnings
        ? '<div class="profile-section"><h4>Notes</h4>' +
          '<ul class="warning-list">' + warnings + '</ul></div>'
        : '') +
      '<div class="profile-section">' +
        '<h4>Details</h4>' +
        '<div class="profile-meta-grid">' +
          '<div class="meta-box"><span>' + (person.role === 'tutor' ? 'Rate' : 'Budget') +
            '</span><strong>' + escapeHtml(formatPrice(person)) + '</strong></div>' +
          '<div class="meta-box"><span>Format</span><strong>' +
            escapeHtml(formatFormat(person.format)) + '</strong></div>' +
          '<div class="meta-box"><span>Approx. area</span><strong>' +
            escapeHtml(areaText) + '</strong></div>' +
          '<div class="meta-box"><span>Distance</span><strong>' +
            escapeHtml(formatDistance(person.distanceMeters)) + '</strong></div>' +
          (person.responseTimeMins
            ? '<div class="meta-box"><span>Response time</span><strong>About ' +
              escapeHtml(person.responseTimeMins) + ' min</strong></div>'
            : '') +
          (person.lastActiveAt
            ? '<div class="meta-box"><span>Last active</span><strong>' +
              escapeHtml(formatLastActive(person.lastActiveAt)) + '</strong></div>'
            : '') +
        '</div>' +
      '</div>' +
      '<div class="profile-panel-actions">' +
        '<button type="button" class="btn-dark-sm" data-panel-action="request"' +
          (sent ? ' disabled' : '') + '>' +
          (sent ? 'Request sent' : 'Send Request') + '</button>' +
      '</div>' +
      '<p class="profile-note">Location is shown at barangay level only. Exact addresses are never public.</p>';
  }

  global.TutorMatchSearch = {
    init,
    runSearch,
    clearFilters,
    getState: () => state
  };
})(window);
