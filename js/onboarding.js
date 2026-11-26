/* ==========================================================
   TutorMatch A.I. — onboarding wizard
   Keeps a local copy of the profile, saves each step to the
   Flask API, and resumes at the saved onboarding step.
   ========================================================== */
(function (global) {
  'use strict';

  const auth = global.TutorMatchAuth;

  const STEPS = [
    { id: 1, label: 'Basics', hint: 'Photo, bio, and status' },
    { id: 2, label: 'Subjects', hint: 'What you teach or need' },
    { id: 3, label: 'Goals & style', hint: 'How you like to work' },
    { id: 4, label: 'Availability', hint: 'When you are free' },
    { id: 5, label: 'Rate & format', hint: 'Budget and session type' },
    { id: 6, label: 'Area & details', hint: 'Barangay-level only' },
    { id: 7, label: 'Preview', hint: 'Review and finish' },
    { id: 8, label: 'Recovery', hint: '3 security questions' }
  ];

  const LEVELS = [
    { id: 'elementary', label: 'Elementary' },
    { id: 'high_school', label: 'High school' },
    { id: 'senior_high', label: 'Senior high' },
    { id: 'college', label: 'College' },
    { id: 'adult', label: 'Adult learner' }
  ];

  const STYLE_TAGS = [
    { id: 'visual', label: 'Visual' },
    { id: 'step_by_step', label: 'Step by step' },
    { id: 'discussion', label: 'Discussion' },
    { id: 'practice', label: 'Practice-heavy' },
    { id: 'real_world', label: 'Real-world examples' },
    { id: 'structured', label: 'Structured plan' }
  ];

  const GOAL_TAGS = [
    { id: 'exam_prep', label: 'Exam preparation' },
    { id: 'conceptual', label: 'Understand concepts' },
    { id: 'confidence', label: 'Build confidence' },
    { id: 'homework', label: 'Homework help' },
    { id: 'skill_building', label: 'Build a skill' },
    { id: 'grades', label: 'Improve grades' }
  ];

  const SLOTS = [
    { id: 'morning', label: 'Morning', time: '8:00–11:00', start: '08:00', end: '11:00' },
    { id: 'afternoon', label: 'Afternoon', time: '1:00–4:00', start: '13:00', end: '16:00' },
    { id: 'evening', label: 'Evening', time: '6:00–9:00', start: '18:00', end: '21:00' }
  ];

  const DAYS = [
    { id: 'mon', label: 'Mon', full: 'Monday' },
    { id: 'tue', label: 'Tue', full: 'Tuesday' },
    { id: 'wed', label: 'Wed', full: 'Wednesday' },
    { id: 'thu', label: 'Thu', full: 'Thursday' },
    { id: 'fri', label: 'Fri', full: 'Friday' },
    { id: 'sat', label: 'Sat', full: 'Saturday' },
    { id: 'sun', label: 'Sun', full: 'Sunday' }
  ];

  const REQUIRED_FIELDS = ['bio', 'subjects', 'availability', 'rate', 'budget', 'format', 'area'];
  const NAME_PATTERN = new RegExp("^[\\p{L} .'\\-]+$", 'u');
  const LETTER_PATTERN = new RegExp('\\p{L}', 'u');

  function namePartProblem(raw, required) {
    const text = String(raw || '').trim();
    if (!text) return required ? 'Enter this name.' : '';
    if (text.length > 50) return 'Keep this under 50 characters.';
    if (!LETTER_PATTERN.test(text) || !NAME_PATTERN.test(text)) {
      return 'Use letters, spaces, hyphens, apostrophes or periods only.';
    }
    return '';
  }

  function composeLocalName(profile) {
    return [profile.firstName, profile.middleName, profile.lastName]
      .map((part) => String(part || '').trim())
      .filter(Boolean)
      .join(' ');
  }

  function syncLocalName() {
    if (!state.profile) return;
    state.profile.name = composeLocalName(state.profile);
  }

  function visibleStepIds() {
    return STEPS
      .filter((step) => !state.skippedSteps.has(step.id))
      .map((step) => step.id);
  }

  function firstVisibleFrom(step) {
    const ids = visibleStepIds();
    if (!ids.length) return 1;
    return ids.find((id) => id >= step) || ids[ids.length - 1];
  }

  function neighbourStep(step, direction) {
    const ids = visibleStepIds();
    const index = ids.indexOf(step);
    if (index === -1) return null;
    return ids[index + direction] ?? null;
  }

  const state = {
    profile: null,
    catalog: [],
    securityBank: [],
    savedSecurityKeys: [],
    subjectQuery: '',
    step: 1,
    maxStep: 1,
    edit: false,
    skippedSteps: new Set(),
    saving: false,
    savePromise: null,
    saveTimer: null,
    revision: 0,
    statusTimer: null,
    toastTimer: null,
    bound: false
  };

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (character) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }[character]));
  }

  function initials(name) {
    const parts = String(name || '').trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return '?';
    return parts.slice(0, 2).map((part) => part[0].toUpperCase()).join('');
  }

  function roleLabel(role) {
    return role === 'tutor' ? 'Tutor' : 'Student';
  }

  function levelLabel(id) {
    const level = LEVELS.find((item) => item.id === id);
    return level ? level.label : id;
  }

  function formatFormat(value) {
    if (value === 'in_person') return 'In-person';
    if (value === 'online') return 'Online';
    if (value === 'both') return 'Online or in-person';
    return 'Not set';
  }

  function formatMoney(centavos) {
    if (centavos === null || centavos === undefined || centavos === '') return null;
    const pesos = Number(centavos) / 100;
    if (!Number.isFinite(pesos)) return null;
    return `₱${pesos.toLocaleString('en-PH', { maximumFractionDigits: 0 })}`;
  }

  function formatPrice(profile) {
    if (profile.role === 'tutor') {
      const rate = formatMoney(profile.rateCentavos);
      return rate ? `${rate} / hour` : 'Rate not set';
    }
    const min = formatMoney(profile.budgetMinCentavos);
    const max = formatMoney(profile.budgetMaxCentavos);
    return min && max ? `${min}–${max}` : 'Budget not set';
  }

  function subjectName(id, fallback) {
    const subject = state.catalog.find((item) => item.id === id);
    return subject ? subject.name : (fallback || id);
  }

  function subjectById(id) {
    return (state.profile.subjects || []).find((subject) => subject.id === id) || null;
  }

  function photoMarkup(profile, className) {
    if (profile.photoUrl) {
      return `<img src="${escapeHtml(profile.photoUrl)}" alt="" class="${className}" />`;
    }
    return `<span class="${className} photo-initials">${escapeHtml(initials(profile.name))}</span>`;
  }

  function availabilityGridMarkup(availability) {
    const selected = new Set(
      (availability || []).map((slot) => `${slot.day}-${slot.start}-${slot.end}`)
    );
    let html = '<div class="preview-grid-wrap"><div class="preview-grid">';
    html += '<div></div>';
    DAYS.forEach((day) => {
      html += `<div class="preview-grid-head">${day.label}</div>`;
    });
    SLOTS.forEach((slot) => {
      html += `<div class="preview-grid-time">${slot.label}</div>`;
      DAYS.forEach((day) => {
        const key = `${day.id}-${slot.start}-${slot.end}`;
        html += `<div class="preview-grid-cell ${selected.has(key) ? 'is-on' : ''}"></div>`;
      });
    });
    html += '</div></div>';
    return html;
  }

  function showToast(message) {
    const toast = $('#toast');
    if (!toast) return;
    toast.textContent = message;
    toast.dataset.show = 'true';
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => {
      toast.dataset.show = 'false';
    }, 3200);
  }

  function setStatus(message, type = 'info', timeout = 0) {
    const element = $('#wizard-status');
    if (!element) return;
    element.textContent = message || '';
    if (message) {
      element.dataset.type = type;
    } else {
      delete element.dataset.type;
    }
    clearTimeout(state.statusTimer);
    if (message && timeout) {
      state.statusTimer = setTimeout(() => {
        element.textContent = '';
        delete element.dataset.type;
      }, timeout);
    }
  }

  function setSaving(status, message) {
    const element = $('#save-indicator');
    if (!element) return;
    element.dataset.state = status;
    element.textContent = message;
  }

  function mergeServerComputed(profile) {
    if (!state.profile) {
      state.profile = profile;
      return;
    }
    ['id', 'completeness', 'requiredComplete', 'missing', 'onboardingStep',
      'onboardingCompleted', 'createdAt', 'updatedAt'].forEach((key) => {
      if (key in profile) state.profile[key] = profile[key];
    });
    auth.setProfileCompleteness(profile.completeness);
  }

  function markInvalid(field, invalid) {
    const map = {
      firstName: ['#ob-first-name'],
      middleName: ['#ob-middle-name'],
      lastName: ['#ob-last-name'],
      name: ['#ob-first-name', '#ob-middle-name', '#ob-last-name'],
      headline: ['#ob-headline'],
      bio: ['#ob-bio'],
      birthdate: ['#ob-birthdate'],
      status: ['#ob-status'],
      rate: ['#ob-rate'],
      budget: ['#ob-budget-min', '#ob-budget-max'],
      area: ['#ob-barangay'],
      city: ['#ob-city'],
      format: ['#format-options'],
      subjects: ['#subject-list'],
      securityQuestions: ['#ob-security-key-1', '#ob-security-key-2', '#ob-security-key-3'],
      availability: ['#availability-grid']
    };
    (map[field] || []).forEach((selector) => {
      const element = $(selector);
      if (!element) return;
      if (invalid) element.setAttribute('aria-invalid', 'true');
      else element.removeAttribute('aria-invalid');
    });
  }

  function setFieldError(field, message) {
    const error = $(`[data-error-for="${field}"]`);
    if (error) error.textContent = message || '';
    markInvalid(field, Boolean(message));
  }

  function clearFieldErrors() {
    $$('.ob-field').forEach((element) => element.removeAttribute('aria-invalid'));
    $$('[data-error-for]').forEach((element) => {
      element.textContent = '';
    });
    markInvalid('format', false);
    markInvalid('subjects', false);
    markInvalid('availability', false);
  }

  function stepForField(field) {
    const map = {
      firstName: 1,
      middleName: 1,
      lastName: 1,
      name: 1,
      headline: 1,
      bio: 1,
      birthdate: 1,
      status: 1,
      photo: 1,
      subjects: 2,
      goalTags: 3,
      styleTags: 3,
      availability: 4,
      rate: 5,
      budget: 5,
      format: 5,
      area: 6,
      city: 6,
      profile: 7,
      securityQuestions: 8,
      onboardingStep: 8
    };
    return map[field] || 0;
  }

  function showApiFields(fields, options = {}) {
    const entries = Object.entries(fields || {});
    if (!entries.length) return;

    entries.forEach(([field, message]) => {
      if (field === 'photo') {
        showToast(message);
      } else if (field === 'profile' || field === 'onboardingStep') {
        setStatus(message, 'error');
      } else {
        setFieldError(field, message);
      }
    });

    if (options.jump) {
      const first = entries.find(([field]) => stepForField(field));
      if (first) goToStep(stepForField(first[0]), { focus: false });
    }
  }

  function computeCompleteness(profile) {
    const missing = [];
    let percent = 0;
    const bio = String(profile.bio || '').trim();
    const subjects = profile.subjects || [];
    const goals = profile.goalTags || [];
    const styles = profile.styleTags || [];
    const availability = profile.availability || [];
    const hasPrice = profile.role === 'tutor'
      ? profile.rateCentavos !== null && profile.rateCentavos !== undefined
      : profile.budgetMinCentavos !== null
        && profile.budgetMinCentavos !== undefined
        && profile.budgetMaxCentavos !== null
        && profile.budgetMaxCentavos !== undefined;

    if (bio.length >= 10) percent += 10;
    else missing.push({ field: 'bio', label: 'Write a short bio (at least 10 characters)', weight: 10, step: 1 });

    if (profile.photoUrl) percent += 5;
    else missing.push({ field: 'photoUrl', label: 'Add a profile photo (optional)', weight: 5, step: 1 });

    if (subjects.length) percent += 20;
    else missing.push({ field: 'subjects', label: 'Add at least one subject', weight: 20, step: 2 });

    if (goals.length) percent += 10;
    else missing.push({ field: 'goalTags', label: 'Choose a learning goal', weight: 10, step: 3 });

    if (styles.length) percent += 5;
    else missing.push({ field: 'styleTags', label: 'Choose a teaching or learning style', weight: 5, step: 3 });

    if (availability.length) percent += 20;
    else missing.push({ field: 'availability', label: 'Add at least one availability slot', weight: 20, step: 4 });

    if (hasPrice) percent += 10;
    else missing.push({
      field: profile.role === 'tutor' ? 'rate' : 'budget',
      label: profile.role === 'tutor' ? 'Add your hourly rate' : 'Add your budget range',
      weight: 10,
      step: 5
    });

    if (profile.format) percent += 5;
    else missing.push({ field: 'format', label: 'Choose a session format', weight: 5, step: 5 });

    if (String(profile.area && profile.area.barangay || '').trim()) percent += 10;
    else missing.push({ field: 'area', label: 'Add your barangay', weight: 10, step: 6 });

    if (profile.verified) percent += 5;
    else missing.push({ field: 'verification', label: 'Verify your tutor profile (optional)', weight: 5, step: 7 });

    const requiredComplete = Boolean(
      bio.length >= 10
      && subjects.length
      && availability.length
      && hasPrice
      && profile.format
      && String(profile.area && profile.area.barangay || '').trim()
    );

    return { percent: Math.min(100, percent), requiredComplete, missing };
  }

  function renderCompleteness() {
    if (!state.profile) return;
    const result = computeCompleteness(state.profile);
    const percentElement = $('#ob-percent');
    const fillElement = $('#ob-fill');
    const trackElement = $('#ob-track');
    const statusElement = $('#ob-status-text');
    const missingElement = $('#missing-list');

    if (percentElement) percentElement.textContent = `${result.percent}%`;
    if (fillElement) fillElement.style.width = `${result.percent}%`;
    if (trackElement) trackElement.setAttribute('aria-valuenow', String(result.percent));
    if (statusElement) {
      statusElement.textContent = result.requiredComplete
        ? 'Your profile meets the minimum for search.'
        : 'Complete the required items to appear in search.';
    }
    if (missingElement) {
      missingElement.innerHTML = result.missing.length
        ? result.missing.map((item) => `
            <li>
              <button type="button" class="missing-item" data-missing-step="${item.step}">
                <span>${escapeHtml(item.label)}</span>
                <span>+${item.weight}%</span>
              </button>
            </li>
          `).join('')
        : '<li class="missing-done">All set.</li>';
    }
  }

  function renderStepList() {
    const list = $('#step-list');
    if (!list) return;
    const ids = visibleStepIds();
    const currentIndex = ids.indexOf(state.step);
    list.innerHTML = STEPS
      .filter((step) => !state.skippedSteps.has(step.id))
      .map((step, index) => {
        const active = step.id === state.step;
        const done = index < currentIndex;
        const locked = step.id > state.maxStep && !state.edit;
        return `
          <li>
            <button type="button"
              class="step-item ${active ? 'is-active' : ''} ${done ? 'is-done' : ''}"
              data-step="${step.id}"
              ${locked ? 'disabled' : ''}
              ${active ? 'aria-current="step"' : ''}>
              <span class="step-index">${done ? '✓' : index + 1}</span>
              <span class="step-copy">
                <strong>${step.label}</strong>
                <span>${step.hint}</span>
              </span>
            </button>
          </li>
        `;
      }).join('');
  }

  function renderProgress() {
    const counter = $('#step-counter');
    const fill = $('#wizard-progress-fill');
    const track = $('.wizard-progress');
    const ids = visibleStepIds();
    const position = Math.max(1, ids.indexOf(state.step) + 1);
    const total = Math.max(1, ids.length);
    if (counter) counter.textContent = `Step ${position} of ${total}`;
    if (fill) fill.style.width = `${(position / total) * 100}%`;
    if (track) track.setAttribute('aria-valuenow', String(position));
  }

  function renderBasics() {
    const profile = state.profile;
    if (!profile) return;
    const firstName = $('#ob-first-name');
    const middleName = $('#ob-middle-name');
    const lastName = $('#ob-last-name');
    const headline = $('#ob-headline');
    const bio = $('#ob-bio');
    const birthdate = $('#ob-birthdate');
    const status = $('#ob-status');
    if (firstName) firstName.value = profile.firstName || '';
    if (middleName) middleName.value = profile.middleName || '';
    if (lastName) lastName.value = profile.lastName || '';
    if (headline) headline.value = profile.headline || '';
    if (bio) bio.value = profile.bio || '';
    if (birthdate) birthdate.value = profile.birthdate || '';
    if (status) status.value = profile.status || 'active';
    const count = $('#ob-bio-count');
    if (count) count.textContent = `${(profile.bio || '').length}/600`;
    renderPhoto();
  }

  function renderPhoto() {
    const target = $('#ob-photo-preview');
    if (!target || !state.profile) return;
    target.innerHTML = photoMarkup(state.profile, 'photo-img');
  }

  function renderSubjects() {
    const target = $('#subject-list');
    if (!target) return;
    const selected = new Map((state.profile.subjects || []).map((subject) => [subject.id, subject]));
    const query = state.subjectQuery.trim().toLowerCase();
    const catalog = state.catalog.filter((subject) => {
      if (!query) return true;
      return `${subject.name} ${subject.category}`.toLowerCase().includes(query);
    });

    const count = $('#subject-count');
    if (count) count.textContent = `${selected.size} selected`;

    if (!catalog.length) {
      target.innerHTML = '<p class="muted-note">No subjects match that search.</p>';
      return;
    }

    const groups = new Map();
    catalog.forEach((subject) => {
      if (!groups.has(subject.category)) groups.set(subject.category, []);
      groups.get(subject.category).push(subject);
    });

    target.innerHTML = Array.from(groups.entries()).map(([category, subjects]) => `
      <div class="subject-group">
        <h4>${escapeHtml(category)}</h4>
        <div class="subject-options">
          ${subjects.map((subject) => {
            const current = selected.get(subject.id);
            const isSelected = Boolean(current);
            return `
              <div class="subject-option ${isSelected ? 'is-selected' : ''}">
                <button type="button"
                  class="subject-toggle"
                  data-subject-toggle="${escapeHtml(subject.id)}"
                  aria-pressed="${isSelected}">
                  <span class="subject-check">${isSelected ? '✓' : ''}</span>
                  <span>${escapeHtml(subject.name)}</span>
                </button>
                ${isSelected ? `
                  <label class="subject-level">
                    <span>Level</span>
                    <select data-subject-level="${escapeHtml(subject.id)}" aria-label="Level for ${escapeHtml(subject.name)}">
                      ${LEVELS.map((level) => `
                        <option value="${level.id}" ${level.id === current.level ? 'selected' : ''}>${level.label}</option>
                      `).join('')}
                    </select>
                  </label>
                ` : ''}
              </div>
            `;
          }).join('')}
        </div>
      </div>
    `).join('');
  }

  function renderTagGroup(targetId, tags, selected) {
    const target = $(targetId);
    if (!target) return;
    target.innerHTML = tags.map((tag) => {
      const isSelected = selected.includes(tag.id);
      return `
        <button type="button"
          class="tag-chip ${isSelected ? 'is-selected' : ''}"
          data-tag-group="${targetId === '#goal-tags' ? 'goals' : 'styles'}"
          data-tag="${tag.id}"
          aria-pressed="${isSelected}">
          ${escapeHtml(tag.label)}
        </button>
      `;
    }).join('');
  }

  function renderTags() {
    if (!state.profile) return;
    renderTagGroup('#goal-tags', GOAL_TAGS, state.profile.goalTags || []);
    renderTagGroup('#style-tags', STYLE_TAGS, state.profile.styleTags || []);
  }

  function renderAvailability() {
    const target = $('#availability-grid');
    if (!target) return;
    const selected = new Set(
      (state.profile.availability || []).map((slot) => `${slot.day}-${slot.start}-${slot.end}`)
    );

    let html = '<div class="avail-corner"></div>';
    DAYS.forEach((day) => {
      html += `<div class="avail-head">${day.label}</div>`;
    });
    SLOTS.forEach((slot) => {
      html += `
        <div class="avail-time">
          <strong>${slot.label}</strong>
          <span>${slot.time}</span>
        </div>
      `;
      DAYS.forEach((day) => {
        const key = `${day.id}-${slot.start}-${slot.end}`;
        const isOn = selected.has(key);
        html += `
          <button type="button"
            class="avail-cell ${isOn ? 'is-on' : ''}"
            data-availability
            data-day="${day.id}"
            data-slot="${slot.id}"
            aria-pressed="${isOn}"
            aria-label="${day.full} ${slot.label} ${isOn ? 'selected' : 'not selected'}">
          </button>
        `;
      });
    });
    target.innerHTML = html;
  }

  function renderFormat() {
    const target = $('#format-options');
    if (!target || !state.profile) return;
    const options = [
      { id: 'online', label: 'Online', description: 'Video call from anywhere' },
      { id: 'in_person', label: 'In-person', description: 'Meet nearby in your city' },
      { id: 'both', label: 'Either', description: 'Online or in-person' }
    ];
    target.innerHTML = options.map((option) => {
      const isSelected = state.profile.format === option.id;
      return `
        <button type="button"
          class="format-card ${isSelected ? 'is-selected' : ''}"
          data-format="${option.id}"
          aria-pressed="${isSelected}">
          <strong>${option.label}</strong>
          <span>${option.description}</span>
        </button>
      `;
    }).join('');
  }

  function renderPriceFields() {
    if (!state.profile) return;
    const isTutor = state.profile.role === 'tutor';
    const tutorWrap = $('#tutor-rate-wrap');
    const studentWrap = $('#student-budget-wrap');
    if (tutorWrap) tutorWrap.classList.toggle('hidden', !isTutor);
    if (studentWrap) studentWrap.classList.toggle('hidden', isTutor);

    const rate = $('#ob-rate');
    if (rate) {
      rate.value = state.profile.rateCentavos !== null && state.profile.rateCentavos !== undefined
        ? String(Math.round(Number(state.profile.rateCentavos) / 100))
        : '';
    }
    const budgetMin = $('#ob-budget-min');
    if (budgetMin) {
      budgetMin.value = state.profile.budgetMinCentavos !== null && state.profile.budgetMinCentavos !== undefined
        ? String(Math.round(Number(state.profile.budgetMinCentavos) / 100))
        : '';
    }
    const budgetMax = $('#ob-budget-max');
    if (budgetMax) {
      budgetMax.value = state.profile.budgetMaxCentavos !== null && state.profile.budgetMaxCentavos !== undefined
        ? String(Math.round(Number(state.profile.budgetMaxCentavos) / 100))
        : '';
    }
  }

  function renderArea() {
    if (!state.profile) return;
    const profile = state.profile;
    const barangay = $('#ob-barangay');
    const city = $('#ob-city');
    if (barangay) barangay.value = (profile.area && profile.area.barangay) || '';
    if (city) city.value = (profile.area && profile.area.city) || 'Cabadbaran City';

    const textFields = {
      'ob-gender': profile.gender || '',
      'ob-phone': profile.phone || '',
      'ob-address-line': profile.addressLine || '',
      'ob-province': profile.province || '',
      'ob-postal-code': profile.postalCode || '',
      'ob-school': profile.school || '',
      'ob-grade-level': profile.gradeLevel || '',
      'ob-course': profile.course || '',
      'ob-education': profile.education || '',
      'ob-experience-years': profile.experienceYears ?? ''
    };
    Object.entries(textFields).forEach(([id, value]) => {
      const field = $('#' + id);
      if (field) field.value = value;
    });

    const showPhone = $('#ob-show-phone');
    const showAddress = $('#ob-show-address');
    if (showPhone) showPhone.checked = !!profile.showPhone;
    if (showAddress) showAddress.checked = !!profile.showAddress;

    $$('[data-role-field]', $('.step-panel[data-panel="6"]')).forEach((field) => {
      const isTutorField = field.dataset.roleField === 'tutor';
      field.hidden = profile.role === 'tutor' ? !isTutorField : isTutorField;
    });
  }

  function renderSecurityStep() {
    const selects = $$('[data-security-key]');
    if (!selects.length) return;
    const saved = (state.savedSecurityKeys || []).slice(0, selects.length);
    selects.forEach((select, index) => {
      const current = select.value || saved[index] || '';
      const options = ['<option value="">Choose a question</option>'];
      (state.securityBank || []).forEach((question) => {
        options.push(
          `<option value="${escapeHtml(question.key)}">${escapeHtml(question.text)}</option>`
        );
      });
      select.innerHTML = options.join('');
      select.value = current;
    });
    refreshSecurityOptions();
  }

  function refreshSecurityOptions() {
    const selects = $$('[data-security-key]');
    const chosen = selects.map((select) => select.value).filter(Boolean);
    selects.forEach((select) => {
      Array.from(select.options).forEach((option) => {
        if (!option.value) return;
        option.disabled = option.value !== select.value && chosen.includes(option.value);
      });
    });
  }

  function securityAnswersFromForm() {
    return $$('[data-security-key]').map((select) => {
      const slot = select.dataset.securityKey;
      const answer = $(`#ob-security-answer-${slot}`);
      return {
        key: select.value,
        answer: answer ? answer.value.trim() : ''
      };
    });
  }

  function validateSecurityStep() {
    if ((state.securityBank || []).length < 3) {
      setFieldError(
        'securityQuestions',
        'Could not load the question list. Reload the page.'
      );
      return false;
    }

    const answers = securityAnswersFromForm();
    if (answers.length !== 3 || answers.some((item) => !item.key)) {
      setFieldError('securityQuestions', 'Choose 3 different questions.');
      return false;
    }
    if (new Set(answers.map((item) => item.key)).size !== 3) {
      setFieldError('securityQuestions', 'Choose 3 different questions.');
      return false;
    }

    const savedKeys = state.savedSecurityKeys || [];
    for (const item of answers) {
      if (!item.answer && savedKeys.includes(item.key)) continue;
      if (item.answer.length < 2) {
        setFieldError(
          'securityQuestions',
          'Enter an answer for each question (at least 2 characters).'
        );
        return false;
      }
      if (item.answer.length > 100) {
        setFieldError('securityQuestions', 'Keep each answer under 100 characters.');
        return false;
      }
    }
    return true;
  }

  function renderPreview() {
    const target = $('#preview-root');
    if (!target || !state.profile) return;
    const profile = state.profile;
    const result = computeCompleteness(profile);
    const area = [profile.area && profile.area.barangay, profile.area && profile.area.city]
      .filter(Boolean)
      .join(', ') || 'Area not set';
    const subjects = (profile.subjects || []).map((subject) => `
      <span class="subject-chip">
        ${escapeHtml(subjectName(subject.id, subject.name))} · ${escapeHtml(levelLabel(subject.level))}
      </span>
    `).join('');
    const goals = (profile.goalTags || [])
      .map((id) => GOAL_TAGS.find((tag) => tag.id === id)?.label || id)
      .map((label) => `<span class="subject-chip">${escapeHtml(label)}</span>`)
      .join('');
    const styles = (profile.styleTags || [])
      .map((id) => STYLE_TAGS.find((tag) => tag.id === id)?.label || id)
      .map((label) => `<span class="subject-chip">${escapeHtml(label)}</span>`)
      .join('');

    target.innerHTML = `
      <article class="preview-card">
        <div class="preview-header">
          <div class="preview-avatar">${photoMarkup(profile, 'preview-avatar-img')}</div>
          <div>
            <h3>${escapeHtml(profile.name || 'Your name')}</h3>
            <p>${escapeHtml(roleLabel(profile.role))}${profile.verified ? ' · Verified' : ''}</p>
            <p class="preview-headline">${escapeHtml(profile.headline || 'Add a headline to stand out')}</p>
          </div>
        </div>
        <p class="preview-bio">${escapeHtml(profile.bio || 'Your bio will appear here.')}</p>
        <div class="preview-meta">
          <div class="preview-meta-item">
            <span>${profile.role === 'tutor' ? 'Rate' : 'Budget'}</span>
            <strong>${escapeHtml(formatPrice(profile))}</strong>
          </div>
          <div class="preview-meta-item">
            <span>Format</span>
            <strong>${escapeHtml(formatFormat(profile.format))}</strong>
          </div>
          <div class="preview-meta-item">
            <span>Area</span>
            <strong>${escapeHtml(area)}</strong>
          </div>
          <div class="preview-meta-item">
            <span>Completeness</span>
            <strong>${result.percent}%</strong>
          </div>
        </div>
        <div class="preview-section">
          <h4>Subjects</h4>
          <div class="preview-subjects">${subjects || '<span class="subject-chip">No subjects yet</span>'}</div>
        </div>
        ${goals ? `<div class="preview-section"><h4>Goals</h4><div class="preview-subjects">${goals}</div></div>` : ''}
        ${styles ? `<div class="preview-section"><h4>Style</h4><div class="preview-subjects">${styles}</div></div>` : ''}
        <div class="preview-section">
          <h4>Weekly availability</h4>
          ${availabilityGridMarkup(profile.availability || [])}
        </div>
      </article>
    `;

    const finishStatus = $('#finish-status');
    if (finishStatus) {
      if (result.requiredComplete) {
        finishStatus.className = 'finish-status is-ready';
        finishStatus.textContent = 'Your profile meets the minimum for search. Finish to save and continue.';
      } else {
        const first = result.missing.find((item) => REQUIRED_FIELDS.includes(item.field));
        finishStatus.className = 'finish-status is-blocked';
        finishStatus.textContent = first
          ? `Before finishing: ${first.label.toLowerCase()}.`
          : 'Complete the required items before finishing.';
      }
    }
  }

  function renderRoleHints() {
    if (!state.profile) return;
    const isTutor = state.profile.role === 'tutor';
    const title = $('#wizard-title');
    const subtitle = $('#wizard-subtitle');
    const subjectsHint = $('#subjects-role-hint');
    const tagsHint = $('#tags-role-hint');
    const priceHint = $('#price-role-hint');

    if (title) {
      title.textContent = state.edit
        ? 'Edit your TutorMatch profile'
        : "Let's build your TutorMatch profile";
    }
    if (subtitle) {
      subtitle.textContent = state.edit
        ? 'Update your details and save when you are done. Your progress saves automatically.'
        : 'A few details help us match you with the right people. Your progress saves automatically.';
    }
    if (subjectsHint) {
      subjectsHint.textContent = isTutor
        ? 'Choose the subjects you teach. Add a level for each one.'
        : 'Choose the subjects you need help with. Add a level for each one.';
    }
    if (tagsHint) {
      tagsHint.textContent = isTutor
        ? 'Tell students how you like to teach. This is recommended, not required.'
        : 'Tell tutors how you like to learn. This is recommended, not required.';
    }
    if (priceHint) {
      priceHint.textContent = isTutor
        ? 'Set your hourly rate and how you want to meet.'
        : 'Set your budget range and how you want to meet.';
    }
  }

  function renderAll() {
    renderRoleHints();
    renderStepList();
    renderProgress();
    renderBasics();
    renderSubjects();
    renderTags();
    renderAvailability();
    renderFormat();
    renderPriceFields();
    renderArea();
    renderSecurityStep();
    renderPreview();
    renderCompleteness();
    const search = $('#subject-search');
    if (search) search.value = state.subjectQuery;
  }

  function goToStep(step, options = {}) {
    let next = clamp(Number(step) || 1, 1, 8);
    if (!state.edit && state.skippedSteps.has(next)) {
      next = firstVisibleFrom(next);
    }
    state.step = next;

    $$('.step-panel').forEach((panel) => {
      panel.classList.toggle('is-active', Number(panel.dataset.panel) === next);
    });

    renderStepList();
    renderProgress();

    const ids = visibleStepIds();
    const position = Math.max(1, ids.indexOf(next) + 1);
    const lastVisible = ids[ids.length - 1];
    const eyebrow = $(`.step-panel[data-panel="${next}"] .eyebrow`);
    if (eyebrow) eyebrow.textContent = `Step ${position}`;

    const nextButton = $('#next-btn');
    const finishButton = $('#finish-btn');
    const footerNote = $('#step-footer-note');
    if (nextButton) {
      nextButton.classList.toggle('hidden', next === lastVisible);
      const upcoming = neighbourStep(next, 1);
      nextButton.textContent = upcoming === 7 ? 'Review profile' : 'Continue';
    }
    if (finishButton) finishButton.classList.toggle('hidden', next !== lastVisible);
    if (footerNote) {
      footerNote.textContent = next === lastVisible
        ? 'You can change these later in your profile.'
        : next === 3
          ? 'Optional step'
          : '';
    }

    if (next === 1) {
      renderBasics();
    } else if (next === 2) {
      renderSubjects();
    } else if (next === 3) {
      renderTags();
    } else if (next === 4) {
      renderAvailability();
    } else if (next === 5) {
      renderPriceFields();
      renderFormat();
    } else if (next === 6) {
      renderArea();
    } else if (next === 7) {
      renderPreview();
    } else if (next === 8) {
      renderSecurityStep();
    }

    renderCompleteness();

    if (options.focus !== false) {
      const heading = $(`.step-panel[data-panel="${next}"] h2`);
      if (heading) heading.focus({ preventScroll: false });
    }
  }

  function validateStep(step) {
    clearFieldErrors();
    let ok = true;
    const profile = state.profile;

    if (step === 1) {
      const firstProblem = namePartProblem(profile.firstName, true);
      if (firstProblem) {
        setFieldError('firstName', firstProblem);
        ok = false;
      }
      const middleProblem = namePartProblem(profile.middleName, false);
      if (middleProblem) {
        setFieldError('middleName', middleProblem);
        ok = false;
      }
      const lastProblem = namePartProblem(profile.lastName, true);
      if (lastProblem) {
        setFieldError('lastName', lastProblem);
        ok = false;
      }
      if (!firstProblem && !lastProblem && composeLocalName(profile).length > 80) {
        setFieldError('lastName', 'Your full name is too long.');
        ok = false;
      }
      const bio = String(profile.bio || '').trim();
      const headline = String(profile.headline || '').trim();
      if (bio.length < 10) {
        setFieldError('bio', 'Write at least 10 characters about yourself.');
        ok = false;
      } else if (bio.length > 600) {
        setFieldError('bio', 'Keep the bio under 600 characters.');
        ok = false;
      }
      if (headline.length > 120) {
        setFieldError('headline', 'Keep the headline under 120 characters.');
        ok = false;
      }
      if (profile.birthdate) {
        const birthdate = new Date(`${profile.birthdate}T00:00:00`);
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        if (Number.isNaN(birthdate.getTime()) || birthdate > today) {
          setFieldError('birthdate', 'Use a valid birthdate that is not in the future.');
          ok = false;
        }
      }
      if (!['active', 'away', 'accepting', 'not_accepting'].includes(profile.status)) {
        setFieldError('status', 'Choose a valid status.');
        ok = false;
      }
    }

    if (step === 2) {
      const subjects = profile.subjects || [];
      if (!subjects.length) {
        setFieldError('subjects', 'Choose at least one subject.');
        ok = false;
      } else if (subjects.length > 8) {
        setFieldError('subjects', 'Choose up to 8 subjects.');
        ok = false;
      } else if (subjects.some((subject) => !LEVELS.some((level) => level.id === subject.level))) {
        setFieldError('subjects', 'Choose a level for each subject.');
        ok = false;
      }
    }

    if (step === 4) {
      if (!(profile.availability || []).length) {
        setFieldError('availability', 'Choose at least one availability slot.');
        ok = false;
      }
    }

    if (step === 5) {
      if (profile.role === 'tutor') {
        if (profile.rateCentavos === null || profile.rateCentavos === undefined) {
          setFieldError('rate', 'Enter your hourly rate.');
          ok = false;
        } else if (profile.rateCentavos < 0 || profile.rateCentavos > 1000000) {
          setFieldError('rate', 'Enter an amount between 0 and 10,000 PHP.');
          ok = false;
        }
      } else {
        if (profile.budgetMinCentavos === null || profile.budgetMinCentavos === undefined
          || profile.budgetMaxCentavos === null || profile.budgetMaxCentavos === undefined) {
          setFieldError('budget', 'Enter your budget range.');
          ok = false;
        } else if (profile.budgetMinCentavos < 0 || profile.budgetMaxCentavos > 1000000) {
          setFieldError('budget', 'Enter an amount between 0 and 10,000 PHP.');
          ok = false;
        } else if (profile.budgetMinCentavos > profile.budgetMaxCentavos) {
          setFieldError('budget', 'The minimum cannot be higher than the maximum.');
          ok = false;
        }
      }
      if (!['online', 'in_person', 'both'].includes(profile.format)) {
        setFieldError('format', 'Choose a session format.');
        ok = false;
      }
    }

    if (step === 6) {
      const barangay = String(profile.area && profile.area.barangay || '').trim();
      const city = String(profile.area && profile.area.city || '').trim();
      if (!barangay) {
        setFieldError('area', 'Enter your barangay.');
        ok = false;
      } else if (barangay.length > 80) {
        setFieldError('area', 'Keep the barangay under 80 characters.');
        ok = false;
      }
      if (!city) {
        setFieldError('city', 'Enter your city or municipality.');
        ok = false;
      } else if (city.length > 80) {
        setFieldError('city', 'Keep the city under 80 characters.');
        ok = false;
      }

      const phone = String(profile.phone || '').trim();
      if (phone) {
        const digits = phone.replace(/\D/g, '');
        if (digits.length < 7 || digits.length > 15 || !/^\+?[0-9 ()\-]+$/.test(phone)) {
          setFieldError('phone', 'Enter a valid phone number.');
          ok = false;
        }
      }
      const postal = String(profile.postalCode || '').trim();
      if (postal && !/^\d{4,10}$/.test(postal)) {
        setFieldError('postalCode', 'Use a 4-10 digit ZIP code.');
        ok = false;
      }
      const experience = profile.experienceYears;
      if (experience !== null && experience !== undefined && experience !== '') {
        const years = Number(experience);
        if (!Number.isInteger(years) || years < 0 || years > 60) {
          setFieldError('experienceYears', 'Enter a whole number between 0 and 60.');
          ok = false;
        }
      }
    }

    if (step === 7) {
      const result = computeCompleteness(profile);
      if (!result.requiredComplete) {
        const first = result.missing.find((item) => REQUIRED_FIELDS.includes(item.field));
        if (first) {
          goToStep(first.step, { focus: false });
          setStatus(`Before finishing: ${first.label.toLowerCase()}.`, 'error');
        } else {
          setStatus('Complete the required profile fields before finishing.', 'error');
        }
        ok = false;
      }
    }

    if (step === 8 && !validateSecurityStep()) {
      ok = false;
    }

    if (!ok) {
      setStatus('Please fix the highlighted fields.', 'error');
      const firstInvalid = $('[aria-invalid="true"]');
      if (firstInvalid && typeof firstInvalid.focus === 'function') {
        firstInvalid.focus({ preventScroll: false });
      }
    }
    return ok;
  }

  function canAutosave(step) {
    if (!state.profile) return false;
    if (step === 1) {
      return !namePartProblem(state.profile.firstName, true)
        && !namePartProblem(state.profile.middleName, false)
        && !namePartProblem(state.profile.lastName, true);
    }
    return true;
  }

  function payloadForStep(step, nextStep) {
    const profile = state.profile;
    const payload = {};

    if (step === 1) {
      payload.name = String(profile.name || '').trim();
      payload.firstName = String(profile.firstName || '').trim();
      payload.middleName = String(profile.middleName || '').trim();
      payload.lastName = String(profile.lastName || '').trim();
      payload.headline = String(profile.headline || '').trim();
      payload.bio = String(profile.bio || '').trim();
      payload.birthdate = profile.birthdate || '';
      payload.status = profile.status || 'active';
    } else if (step === 2) {
      payload.subjects = (profile.subjects || []).map((subject) => ({
        id: subject.id,
        level: subject.level
      }));
    } else if (step === 3) {
      payload.styleTags = profile.styleTags || [];
      payload.goalTags = profile.goalTags || [];
    } else if (step === 4) {
      payload.availability = profile.availability || [];
    } else if (step === 5) {
      if (profile.role === 'tutor') {
        payload.rateCentavos = profile.rateCentavos;
      } else {
        payload.budgetMinCentavos = profile.budgetMinCentavos;
        payload.budgetMaxCentavos = profile.budgetMaxCentavos;
      }
      if (profile.format) payload.format = profile.format;
    } else if (step === 6) {
      payload.area = {
        barangay: String(profile.area && profile.area.barangay || '').trim(),
        city: String(profile.area && profile.area.city || '').trim()
      };
      payload.gender = profile.gender || '';
      payload.phone = profile.phone || '';
      payload.addressLine = profile.addressLine || '';
      payload.province = profile.province || '';
      payload.postalCode = profile.postalCode || '';
      payload.school = profile.school || '';
      payload.gradeLevel = profile.gradeLevel || '';
      payload.course = profile.course || '';
      payload.education = profile.education || '';
      payload.experienceYears = profile.experienceYears ?? '';
      payload.showPhone = !!profile.showPhone;
      payload.showAddress = !!profile.showAddress;
    }

    payload.onboardingStep = nextStep || state.maxStep;
    return payload;
  }

  async function saveStep(options = {}) {
    if (!state.profile) return false;

    if (state.savePromise) {
      try {
        await state.savePromise;
      } catch {
        /* Continue with the next save. */
      }
    }

    if (options.autosave && !canAutosave(state.step)) {
      return false;
    }

    if (state.saveTimer) {
      clearTimeout(state.saveTimer);
      state.saveTimer = null;
    }

    const revision = state.revision;
    const payload = payloadForStep(state.step, options.nextStep);
    setSaving('saving', 'Saving…');
    state.saving = true;

    state.savePromise = auth.updateProfile(payload)
      .then((profile) => {
        if (state.revision === revision) {
          state.profile = profile;
        } else {
          mergeServerComputed(profile);
        }
        state.maxStep = Math.max(
          state.maxStep,
          Number(profile.onboardingStep) || 0,
          Number(options.nextStep) || 0
        );
        setSaving('saved', 'Saved');
        renderCompleteness();
        renderStepList();
        return true;
      })
      .catch((error) => {
        setSaving('error', 'Not saved');
        if (error.fields) showApiFields(error.fields);
        if (!options.autosave) {
          setStatus(error.message || 'Could not save. Try again.', 'error');
        }
        return false;
      })
      .finally(() => {
        state.saving = false;
        state.savePromise = null;
      });

    return state.savePromise;
  }

  async function nextStep() {
    if (!validateStep(state.step)) return;
    const next = neighbourStep(state.step, 1);
    if (!next) {
      await finish();
      return;
    }
    const ok = await saveStep({ nextStep: next });
    if (!ok) return;
    state.maxStep = Math.max(state.maxStep, next);
    goToStep(next);
  }

  async function prevStep() {
    const previous = neighbourStep(state.step, -1);
    if (!previous) return;
    await saveStep({});
    goToStep(previous);
  }

  async function handleStepClick(step) {
    if (!state.profile) return;
    if (step === state.step) return;
    if (state.skippedSteps.has(step)) return;
    if (step > state.maxStep && !state.edit) return;
    await saveStep({});
    goToStep(step);
  }

  async function saveAndExit() {
    if (!state.profile) return;
    const ok = await saveStep({});
    if (!ok) return;
    if (state.edit) {
      global.location.href = 'dashboard.html#search';
    } else {
      global.location.href = 'index.html';
    }
  }

  async function finish() {
    if (!validateStep(7)) return;
    if (!state.skippedSteps.has(8) && !validateStep(8)) return;

    const profile = state.profile;
    const payload = {
      name: String(profile.name || '').trim(),
      firstName: String(profile.firstName || '').trim(),
      middleName: String(profile.middleName || '').trim(),
      lastName: String(profile.lastName || '').trim(),
      headline: String(profile.headline || '').trim(),
      bio: String(profile.bio || '').trim(),
      birthdate: profile.birthdate || '',
      status: profile.status || 'active',
      subjects: (profile.subjects || []).map((subject) => ({
        id: subject.id,
        level: subject.level
      })),
      styleTags: profile.styleTags || [],
      goalTags: profile.goalTags || [],
      availability: profile.availability || [],
      area: {
        barangay: String(profile.area && profile.area.barangay || '').trim(),
        city: String(profile.area && profile.area.city || '').trim()
      },
      onboardingStep: 8,
      onboardingCompleted: true
    };

    if (profile.role === 'tutor') {
      payload.rateCentavos = profile.rateCentavos;
    } else {
      payload.budgetMinCentavos = profile.budgetMinCentavos;
      payload.budgetMaxCentavos = profile.budgetMaxCentavos;
    }
    if (profile.format) payload.format = profile.format;

    setSaving('saving', 'Finishing…');
    try {
      if (!state.skippedSteps.has(8)) {
        await auth.saveSecurityQuestions({
          questions: securityAnswersFromForm()
        });
      }
      const saved = await auth.updateProfile(payload);
      state.profile = saved;
      auth.setProfileCompleteness(saved.completeness);
      global.location.href = 'dashboard.html#search';
    } catch (error) {
      setSaving('error', 'Not saved');
      if (error.fields) {
        showApiFields(error.fields, { jump: true });
      }
      setStatus(error.message || 'Could not finish onboarding. Try again.', 'error');
    }
  }

  function scheduleAutosave() {
    if (!state.profile) return;
    state.revision += 1;
    clearTimeout(state.saveTimer);
    if (!canAutosave(state.step)) {
      setSaving('idle', 'Not saved yet');
      return;
    }
    setSaving('idle', 'Unsaved changes');
    state.saveTimer = setTimeout(() => {
      saveStep({ autosave: true });
    }, 900);
  }

  function toggleSubject(id) {
    if (!state.profile) return;
    const subjects = state.profile.subjects || [];
    const index = subjects.findIndex((subject) => subject.id === id);
    if (index >= 0) {
      subjects.splice(index, 1);
    } else {
      if (subjects.length >= 8) {
        showToast('Choose up to 8 subjects.');
        return;
      }
      subjects.push({
        id,
        name: subjectName(id),
        level: 'senior_high'
      });
    }
    state.profile.subjects = subjects;
    renderSubjects();
    renderCompleteness();
    scheduleAutosave();
  }

  function toggleTag(group, id) {
    if (!state.profile) return;
    const key = group === 'goals' ? 'goalTags' : 'styleTags';
    const current = state.profile[key] || [];
    const index = current.indexOf(id);
    if (index >= 0) {
      current.splice(index, 1);
    } else {
      if (current.length >= 6) {
        showToast('Choose up to 6 options.');
        return;
      }
      current.push(id);
    }
    state.profile[key] = current;
    renderTags();
    renderCompleteness();
    scheduleAutosave();
  }

  function toggleAvailability(day, slotId) {
    if (!state.profile) return;
    const slot = SLOTS.find((item) => item.id === slotId);
    if (!slot) return;
    const availability = state.profile.availability || [];
    const index = availability.findIndex((item) => (
      item.day === day && item.start === slot.start && item.end === slot.end
    ));
    if (index >= 0) {
      availability.splice(index, 1);
    } else {
      availability.push({ day, start: slot.start, end: slot.end });
    }
    state.profile.availability = availability;
    renderAvailability();
    renderCompleteness();
    scheduleAutosave();
  }

  async function handlePhoto(file) {
    if (!file || !state.profile) return;
    const allowed = ['image/jpeg', 'image/png', 'image/webp'];
    if (!allowed.includes(file.type)) {
      showToast('Use a JPG, PNG, or WebP image.');
      return;
    }
    if (file.size > 1024 * 1024) {
      showToast('Keep the photo under 1 MB.');
      return;
    }

    state.revision += 1;
    const preview = $('#ob-photo-preview');
    const objectUrl = URL.createObjectURL(file);
    if (preview) preview.innerHTML = `<img src="${objectUrl}" alt="" class="photo-img" />`;
    setSaving('saving', 'Uploading…');

    try {
      const result = await auth.uploadPhoto(file);
      state.profile.photoUrl = result.photoUrl;
      setSaving('saved', 'Photo saved');
      renderPhoto();
      renderCompleteness();
      showToast('Profile photo updated.');
    } catch (error) {
      setSaving('error', 'Upload failed');
      showToast(error.message || 'Could not upload the photo.');
      renderPhoto();
    } finally {
      URL.revokeObjectURL(objectUrl);
    }
  }

  function handleInput(event) {
    if (!state.profile) return;
    const target = event.target;
    if (!target || !target.id) return;

    switch (target.id) {
      case 'ob-first-name':
        state.profile.firstName = target.value;
        syncLocalName();
        scheduleAutosave();
        break;
      case 'ob-middle-name':
        state.profile.middleName = target.value;
        syncLocalName();
        scheduleAutosave();
        break;
      case 'ob-last-name':
        state.profile.lastName = target.value;
        syncLocalName();
        scheduleAutosave();
        break;
      case 'ob-headline':
        state.profile.headline = target.value;
        scheduleAutosave();
        break;
      case 'ob-bio': {
        state.profile.bio = target.value;
        const count = $('#ob-bio-count');
        if (count) count.textContent = `${target.value.length}/600`;
        scheduleAutosave();
        break;
      }
      case 'ob-birthdate':
        state.profile.birthdate = target.value || null;
        scheduleAutosave();
        break;
      case 'ob-status':
        state.profile.status = target.value;
        scheduleAutosave();
        break;
      case 'ob-rate':
        state.profile.rateCentavos = target.value === '' ? null : Math.round(Number(target.value) * 100);
        if (!Number.isFinite(state.profile.rateCentavos)) state.profile.rateCentavos = null;
        scheduleAutosave();
        break;
      case 'ob-budget-min':
        state.profile.budgetMinCentavos = target.value === '' ? null : Math.round(Number(target.value) * 100);
        if (!Number.isFinite(state.profile.budgetMinCentavos)) state.profile.budgetMinCentavos = null;
        scheduleAutosave();
        break;
      case 'ob-budget-max':
        state.profile.budgetMaxCentavos = target.value === '' ? null : Math.round(Number(target.value) * 100);
        if (!Number.isFinite(state.profile.budgetMaxCentavos)) state.profile.budgetMaxCentavos = null;
        scheduleAutosave();
        break;
      case 'ob-gender':
        state.profile.gender = target.value || null;
        scheduleAutosave();
        break;
      case 'ob-phone':
        state.profile.phone = target.value;
        scheduleAutosave();
        break;
      case 'ob-address-line':
        state.profile.addressLine = target.value;
        scheduleAutosave();
        break;
      case 'ob-province':
        state.profile.province = target.value;
        scheduleAutosave();
        break;
      case 'ob-postal-code':
        state.profile.postalCode = target.value;
        scheduleAutosave();
        break;
      case 'ob-school':
        state.profile.school = target.value;
        scheduleAutosave();
        break;
      case 'ob-grade-level':
        state.profile.gradeLevel = target.value;
        scheduleAutosave();
        break;
      case 'ob-course':
        state.profile.course = target.value;
        scheduleAutosave();
        break;
      case 'ob-education':
        state.profile.education = target.value;
        scheduleAutosave();
        break;
      case 'ob-experience-years':
        state.profile.experienceYears = target.value === '' ? null : Number(target.value);
        scheduleAutosave();
        break;
      case 'ob-show-phone':
        state.profile.showPhone = target.checked;
        scheduleAutosave();
        break;
      case 'ob-show-address':
        state.profile.showAddress = target.checked;
        scheduleAutosave();
        break;
      case 'ob-barangay':
        state.profile.area = {
          ...(state.profile.area || {}),
          barangay: target.value
        };
        scheduleAutosave();
        break;
      case 'ob-city':
        state.profile.area = {
          ...(state.profile.area || {}),
          city: target.value
        };
        scheduleAutosave();
        break;
      case 'subject-search':
        state.subjectQuery = target.value;
        renderSubjects();
        break;
      default:
        break;
    }
  }

  function handleChange(event) {
    if (!state.profile) return;
    const target = event.target;
    if (!target) return;

    if (target.id === 'ob-photo') {
      const file = target.files && target.files[0];
      handlePhoto(file);
      target.value = '';
      return;
    }

    if (target.matches('[data-subject-level]')) {
      const subject = subjectById(target.dataset.subjectLevel);
      if (subject) {
        subject.level = target.value;
        renderCompleteness();
        scheduleAutosave();
      }
      return;
    }

    if (target.id && target.id.startsWith('ob-')) {
      handleInput(event);
    }
  }

  function handleClick(event) {
    if (!state.profile) {
      if (event.target.closest('[data-action="retry"]')) {
        global.location.reload();
      }
      return;
    }

    const actionElement = event.target.closest('[data-action]');
    if (actionElement) {
      const action = actionElement.dataset.action;
      if (action === 'next') {
        event.preventDefault();
        nextStep();
        return;
      }
      if (action === 'back') {
        event.preventDefault();
        prevStep();
        return;
      }
      if (action === 'save-exit') {
        event.preventDefault();
        saveAndExit();
        return;
      }
      if (action === 'finish') {
        event.preventDefault();
        finish();
        return;
      }
      if (action === 'choose-photo') {
        event.preventDefault();
        const input = $('#ob-photo');
        if (input) input.click();
        return;
      }
      if (action === 'retry') {
        global.location.reload();
        return;
      }
    }

    const stepButton = event.target.closest('[data-step]');
    if (stepButton) {
      event.preventDefault();
      if (stepButton.disabled) return;
      handleStepClick(Number(stepButton.dataset.step));
      return;
    }

    const subjectButton = event.target.closest('[data-subject-toggle]');
    if (subjectButton) {
      event.preventDefault();
      toggleSubject(subjectButton.dataset.subjectToggle);
      return;
    }

    const tagButton = event.target.closest('[data-tag]');
    if (tagButton) {
      event.preventDefault();
      toggleTag(tagButton.dataset.tagGroup, tagButton.dataset.tag);
      return;
    }

    const availabilityButton = event.target.closest('[data-availability]');
    if (availabilityButton) {
      event.preventDefault();
      toggleAvailability(availabilityButton.dataset.day, availabilityButton.dataset.slot);
      return;
    }

    const formatButton = event.target.closest('[data-format]');
    if (formatButton) {
      event.preventDefault();
      state.profile.format = formatButton.dataset.format;
      renderFormat();
      renderCompleteness();
      scheduleAutosave();
      return;
    }

    const missingButton = event.target.closest('[data-missing-step]');
    if (missingButton) {
      event.preventDefault();
      goToStep(Number(missingButton.dataset.missingStep));
    }
  }

  function bindEvents() {
    if (state.bound) return;
    state.bound = true;
    document.addEventListener('click', handleClick);
    document.addEventListener('input', handleInput);
    document.addEventListener('change', handleChange);
    document.addEventListener('change', (event) => {
      if (!event.target.matches('[data-security-key]')) return;
      const slot = event.target.dataset.securityKey;
      const savedKey = (state.savedSecurityKeys || [])[Number(slot) - 1];
      if (event.target.value !== savedKey) {
        const answer = $(`#ob-security-answer-${slot}`);
        if (answer) answer.value = '';
      }
      refreshSecurityOptions();
    });
  }

  function applyPostSignupBasics() {
    if (!state.profile) return;
    const profile = state.profile;
    // A full sign-up already collected the name parts, bio, and birthdate.
    // For new accounts the first step only needs the photo and status.
    // Edit mode and legacy profiles without name parts keep the fields
    // visible so existing accounts can complete them.
    const cameFromSignup = Boolean(
      String(profile.firstName || '').trim()
      && String(profile.lastName || '').trim()
      && String(profile.bio || '').trim()
      && profile.birthdate
    );
    const hide = cameFromSignup && !state.edit;
    $$('[data-signup-filled]').forEach((field) => {
      field.hidden = hide;
    });
    const copy = $('.step-panel[data-panel="1"] .step-head p:not(.eyebrow)');
    if (copy && hide) {
      copy.textContent =
        'Add a photo and set your status. Your name, bio, and birthdate ' +
        'came from sign-up and can be edited later from your profile.';
    }
  }

  async function init() {
    bindEvents();

    const user = await auth.fetchMe();
    if (!user) {
      global.location.replace('index.html?login=1');
      return;
    }

    const params = new URLSearchParams(global.location.search);
    state.edit = params.has('edit');

    try {
      const [profile, catalog, securityBank, savedQuestions] = await Promise.all([
        auth.fetchProfile(true),
        auth.getSubjects(),
        auth.getSecurityQuestionBank().catch(() => []),
        auth.getMySecurityQuestions().catch(() => [])
      ]);
      if (!profile) throw new Error('Profile not found.');

      if (profile.onboardingCompleted && !state.edit) {
        global.location.replace('dashboard.html#search');
        return;
      }

      state.profile = profile;
      state.catalog = catalog || [];
      state.securityBank = securityBank || [];
      state.savedSecurityKeys = (savedQuestions || []).map((question) => question.key);
      applyPostSignupBasics();

      // New accounts already gave these during sign-up, so the
      // profile customization only asks for photo, subjects, rate
      // or budget, activeness, tags, and format. Edit mode keeps
      // every step so the details stay editable.
      state.skippedSteps = new Set();
      if (!state.edit) {
        if ((profile.availability || []).length) state.skippedSteps.add(4);
        if (profile.area && String(profile.area.barangay || '').trim()) {
          state.skippedSteps.add(6);
        }
        if (profile.securityQuestionsSet) state.skippedSteps.add(8);
      }

      const requestedStep = state.edit
        ? clamp(Number(params.get('step')) || 1, 1, 8)
        : clamp(Number(profile.onboardingStep) || 1, 1, 8);
      state.step = state.skippedSteps.has(requestedStep)
        ? firstVisibleFrom(requestedStep)
        : requestedStep;
      state.maxStep = state.edit ? 8 : state.step;

      renderAll();
      goToStep(state.step, { focus: false });

      const loading = $('#onboarding-loading');
      const app = $('#onboarding-app');
      if (loading) loading.classList.add('hidden');
      if (app) app.classList.remove('hidden');
      if (global.lucide) global.lucide.createIcons();
    } catch (error) {
      const loading = $('#onboarding-loading');
      if (loading) {
        loading.innerHTML = `
          <div>
            <p style="margin: 0 0 0.65rem;">Could not load your profile. ${escapeHtml(error.message || '')}</p>
            <button type="button" class="btn-dark" data-action="retry">Retry</button>
          </div>
        `;
      }
    }
  }

  init();
})(window);
