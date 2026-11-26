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

  const GENDERS = {
    male: 'Male',
    female: 'Female',
    other: 'Other',
    prefer_not_to_say: 'Prefer not to say'
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

  function fact(label, value, note) {
    return `
      <div class="profile-fact">
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(value)}</strong>
        ${note ? `<em>${escapeHtml(note)}</em>` : ''}
      </div>
    `;
  }

  function backgroundMarkup(profile) {
    if (!profile) return '<span class="muted-note">No background details yet.</span>';
    const facts = [];
    if (profile.gender) {
      facts.push(fact('Gender', GENDERS[profile.gender] || profile.gender));
    }
    if (profile.school) facts.push(fact('School', profile.school));
    if (profile.gradeLevel) facts.push(fact('Grade / year level', profile.gradeLevel));
    if (profile.course) facts.push(fact('Course / strand', profile.course));
    if (profile.education) facts.push(fact('Highest education', profile.education));
    if (profile.experienceYears !== null && profile.experienceYears !== undefined) {
      const years = Number(profile.experienceYears);
      facts.push(fact('Experience', `${years} ${years === 1 ? 'year' : 'years'}`));
    }
    return facts.length
      ? facts.join('')
      : '<span class="muted-note">No background details yet. Use Edit profile to add them.</span>';
  }

  function contactMarkup(profile) {
    if (!profile) return '<span class="muted-note">No contact details yet.</span>';
    const facts = [];
    if (profile.phone) {
      facts.push(fact(
        'Phone',
        profile.phone,
        profile.showPhone ? 'Shared with accepted matches' : 'Private'
      ));
    } else {
      facts.push(fact('Phone', 'Not added', 'Optional'));
    }

    const hasAddress = Boolean(
      profile.addressLine || profile.province || profile.postalCode
    );
    const address = hasAddress
      ? [
          profile.addressLine,
          profile.area && profile.area.barangay,
          profile.area && profile.area.city,
          profile.province,
          profile.postalCode
        ].filter(Boolean).join(', ')
      : '';
    if (address) {
      facts.push(fact(
        'Full address',
        address,
        profile.showAddress ? 'Shared with accepted matches' : 'Private'
      ));
    } else {
      facts.push(fact('Full address', 'Not added', 'Optional'));
    }
    return facts.join('');
  }

  function renderDetailsBanner(profile) {
    const banner = document.getElementById('profile-details-banner');
    const message = document.getElementById('profile-details-message');
    if (!banner || !message) return;

    const missing = [];
    let step = 6;
    if (!profile || !profile.firstName || !profile.lastName) {
      missing.push('your first and last name');
      step = 1;
    }
    if (profile && !profile.gender) missing.push('gender');
    if (profile && !profile.school && !profile.education) {
      missing.push('school or education');
    }
    if (profile && !(profile.area && profile.area.barangay)) {
      missing.push('barangay');
    }

    if (!missing.length) {
      banner.hidden = true;
      message.textContent = '';
      return;
    }

    const summary = missing.slice(0, 3).join(', ');
    const rest = missing.length > 3 ? ` and ${missing.length - 3} more` : '';
    message.innerHTML =
      `Complete your sign-up details: ${escapeHtml(summary + rest)}. ` +
      `<a href="onboarding.html?edit=1&step=${step}">Update now</a>`;
    banner.hidden = false;
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
    const backgroundEl = document.getElementById('profile-page-background');
    const contactEl = document.getElementById('profile-page-contact');

    renderDetailsBanner(profile);

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
    if (backgroundEl) backgroundEl.innerHTML = backgroundMarkup(profile);
    if (contactEl) contactEl.innerHTML = contactMarkup(profile);
  }

  global.TutorMatchProfile = { init: render, render };
})(window);
