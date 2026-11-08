/* ==========================================================
   TutorMatch A.I. — Profile section
   Renders the persisted profile from /api/me/profile.
   ========================================================== */
(function (global) {
  'use strict';

  const auth = global.TutorMatchAuth;

  const DAYS = [
    { id: 'mon', label: 'Mon' },
    { id: 'tue', label: 'Tue' },
    { id: 'wed', label: 'Wed' },
    { id: 'thu', label: 'Thu' },
    { id: 'fri', label: 'Fri' },
    { id: 'sat', label: 'Sat' },
    { id: 'sun', label: 'Sun' }
  ];

  const LEVELS = {
    elementary: 'Elementary',
    high_school: 'High school',
    senior_high: 'Senior high',
    college: 'College',
    adult: 'Adult learner'
  };

  const SLOT_LABELS = {
    '08:00': '8a',
    '13:00': '1p',
    '18:00': '6p'
  };

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
    return String(name || '?')
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((part) => part.charAt(0).toUpperCase())
      .join('');
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

  function priceText(profile) {
    if (profile.role === 'tutor') {
      const rate = formatMoney(profile.rateCentavos);
      return rate ? `${rate} / hour` : 'Not set';
    }
    const min = formatMoney(profile.budgetMinCentavos);
    const max = formatMoney(profile.budgetMaxCentavos);
    return min && max ? `${min}–${max}` : 'Not set';
  }

  function availabilityText(availability) {
    const list = availability || [];
    return DAYS.map((day) => {
      const slots = list.filter((slot) => slot.day === day.id);
      const labels = slots
        .map((slot) => SLOT_LABELS[slot.start] || slot.start)
        .join(' ');
      return `
        <div class="profile-avail-day ${slots.length ? 'is-on' : ''}">
          <strong>${day.label}</strong><br>
          ${slots.length ? escapeHtml(labels) : '—'}
        </div>
      `;
    }).join('');
  }

  async function render() {
    const session = auth.getSession();
    if (!session) return;

    let profile = auth.getProfile();
    if (!profile) {
      try {
        profile = await auth.fetchProfile(true);
      } catch {
        profile = null;
      }
    }

    const name = (profile && profile.name) || session.name || session.email || 'Student Name';
    const role = (profile && profile.role) || session.role;
    const roleText = role === 'tutor' ? 'Tutor' : 'Student';
    const percent = profile && Number.isFinite(Number(profile.completeness))
      ? Math.max(0, Math.min(100, Number(profile.completeness)))
      : auth.getProfileCompleteness();

    const avatar = document.getElementById('profile-page-avatar');
    const nameEl = document.getElementById('profile-page-name');
    const roleEl = document.getElementById('profile-page-role');
    const emailEl = document.getElementById('profile-page-email');
    const headlineEl = document.getElementById('profile-page-headline');
    const percentEl = document.getElementById('profile-page-percent');
    const fill = document.getElementById('profile-page-fill');
    const track = document.querySelector('#section-profile .completeness-track');
    const bioEl = document.getElementById('profile-page-bio');
    const subjectsEl = document.getElementById('profile-page-subjects');
    const availabilityEl = document.getElementById('profile-page-availability');
    const priceLabelEl = document.getElementById('profile-page-price-label');
    const priceEl = document.getElementById('profile-page-price');
    const formatEl = document.getElementById('profile-page-format');
    const areaEl = document.getElementById('profile-page-area');

    if (avatar) {
      if (profile && profile.photoUrl) {
        avatar.innerHTML = `<img src="${escapeHtml(profile.photoUrl)}" alt="" />`;
      } else {
        avatar.textContent = initials(name);
      }
    }
    if (nameEl) nameEl.textContent = name;
    if (roleEl) roleEl.textContent = roleText;
    if (emailEl) emailEl.textContent = (profile && profile.email) || session.email || '';
    if (headlineEl) {
      headlineEl.textContent = (profile && profile.headline) || '';
      headlineEl.classList.toggle('hidden', !(profile && profile.headline));
    }
    if (percentEl) percentEl.textContent = `${percent}%`;
    if (fill) fill.style.width = `${percent}%`;
    if (track) track.setAttribute('aria-valuenow', String(percent));

    if (bioEl) {
      bioEl.textContent = (profile && profile.bio) || 'Add a short bio from Edit profile.';
    }

    if (subjectsEl) {
      const subjects = (profile && profile.subjects) || [];
      subjectsEl.innerHTML = subjects.length
        ? subjects.map((subject) => `
            <span class="profile-chip">
              ${escapeHtml(subject.name || subject.id)} · ${escapeHtml(LEVELS[subject.level] || subject.level)}
            </span>
          `).join('')
        : '<span class="muted-note">No subjects yet.</span>';
    }

    if (availabilityEl) {
      availabilityEl.innerHTML = availabilityText(profile && profile.availability);
    }

    if (priceLabelEl) {
      priceLabelEl.textContent = role === 'tutor' ? 'Rate' : 'Budget';
    }
    if (priceEl) {
      priceEl.textContent = profile ? priceText(profile) : 'Not set';
    }
    if (formatEl) {
      formatEl.textContent = formatFormat(profile && profile.format);
    }
    if (areaEl) {
      const area = profile && profile.area;
      const text = [area && area.barangay, area && area.city].filter(Boolean).join(', ');
      areaEl.textContent = text || 'Not set';
    }
  }

  global.TutorMatchProfile = { init: render, render };
})(window);
