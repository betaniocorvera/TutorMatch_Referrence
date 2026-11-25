/* ==========================================================
   TutorMatch A.I. — full sign-up flow
   Collects account details, personal information, availability,
   and the 3 recovery questions before email verification.
   ========================================================== */
(function (global) {
  'use strict';

  const auth = global.TutorMatchAuth;
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const DAYS = [
    { id: 'mon', label: 'Mon' },
    { id: 'tue', label: 'Tue' },
    { id: 'wed', label: 'Wed' },
    { id: 'thu', label: 'Thu' },
    { id: 'fri', label: 'Fri' },
    { id: 'sat', label: 'Sat' },
    { id: 'sun', label: 'Sun' }
  ];

  const SLOTS = [
    { id: 'morning', label: 'Morning', start: '08:00', end: '11:00' },
    { id: 'afternoon', label: 'Afternoon', start: '13:00', end: '16:00' },
    { id: 'evening', label: 'Evening', start: '18:00', end: '21:00' }
  ];

  const NAME_PATTERN = new RegExp("^[\\p{L} .'\\-]+$", 'u');
  const LETTER_PATTERN = new RegExp('\\p{L}', 'u');
  const STEP_COUNT = 3;
  const TOTAL_STEPS = 4;

  const state = {
    step: 1,
    role: 'student',
    email: '',
    questionBank: [],
    submitting: false
  };

  function value(name) {
    const field = $(`[name="${name}"]`);
    return field ? String(field.value || '').trim() : '';
  }

  function clearErrors() {
    $$('[data-error-for]').forEach((element) => {
      element.textContent = '';
      element.removeAttribute('data-type');
    });
    $$('[aria-invalid="true"]').forEach((field) => {
      field.removeAttribute('aria-invalid');
    });
  }

  function setError(field, message) {
    const target = document.querySelector(`[data-error-for="${field}"]`);
    if (target) target.textContent = message || '';
    const input = document.querySelector(`[name="${field}"]`);
    if (input) {
      if (message) input.setAttribute('aria-invalid', 'true');
      else input.removeAttribute('aria-invalid');
    }
  }

  function setStatus(id, type, message) {
    const element = $('#' + id);
    if (!element) return;
    element.textContent = message || '';
    if (message) element.dataset.type = type;
    else element.removeAttribute('data-type');
  }

  function setStep(step, options = {}) {
    const next = Math.min(STEP_COUNT, Math.max(1, Number(step) || 1));
    state.step = next;

    $$('.signup-panel').forEach((panel) => {
      panel.classList.toggle('is-active', Number(panel.dataset.stepPanel) === next);
    });
    $$('[data-step-pill]').forEach((pill) => {
      const pillStep = Number(pill.dataset.stepPill);
      pill.classList.toggle('is-active', pillStep === next);
      pill.classList.toggle('is-done', pillStep < next);
    });

    const fill = $('#signup-progress-fill');
    if (fill) fill.style.width = `${(next / STEP_COUNT) * 100}%`;
    const track = $('.signup-progress-track');
    if (track) track.setAttribute('aria-valuenow', String(next));

    const back = $('#signup-back');
    const nextButton = $('#signup-next');
    const submit = $('#signup-submit');
    const note = $('#signup-footer-note');

    if (back) back.classList.toggle('hidden', next === 1);
    if (nextButton) nextButton.classList.toggle('hidden', next === STEP_COUNT);
    if (submit) submit.classList.toggle('hidden', next !== STEP_COUNT);
    if (note) {
      note.textContent = next === 2
        ? 'Everything here can be edited later.'
        : next === 3
          ? 'Your answers are hashed and never shared.'
          : '';
    }

    const heading = $(`.signup-panel[data-step-panel="${next}"] h2`);
    if (options.focus !== false && heading) heading.focus({ preventScroll: false });
  }

  /* ---------- Role ---------- */
  function setRole(role) {
    const normalized = role === 'tutor' ? 'tutor' : 'student';
    state.role = normalized;
    $$('input[name="role"]').forEach((input) => {
      input.checked = input.value === normalized;
    });
    $$('[data-role-card]').forEach((card) => {
      card.dataset.selected = String(card.dataset.roleCard === normalized);
    });
    $$('[data-role-field]').forEach((field) => {
      const isTutorField = field.dataset.roleField === 'tutor';
      const show = normalized === 'tutor' ? isTutorField : !isTutorField;
      field.hidden = !show;
    });
    const explainer = $('#signup-role-explainer');
    if (explainer) {
      explainer.textContent = normalized === 'tutor'
        ? 'These details appear on your public tutor profile.'
        : 'These details appear on your public student profile.';
    }
  }

  /* ---------- Availability grid ---------- */
  function renderAvailability() {
    const target = $('#available-grid');
    if (!target) return;

    let html = '<div class="available-head"></div>';
    DAYS.forEach((day) => {
      html += `<div class="available-head">${day.label}</div>`;
    });

    SLOTS.forEach((slot) => {
      html += `<div class="available-time">${slot.label}<br><small>${slot.start}–${slot.end}</small></div>`;
      DAYS.forEach((day) => {
        const id = `avail-${day.id}-${slot.id}`;
        html += `
          <label class="available-cell" for="${id}">
            <input id="${id}" type="checkbox"
                   data-day="${day.id}" data-start="${slot.start}" data-end="${slot.end}" />
            <span>${slot.label.slice(0, 3)}</span>
          </label>
        `;
      });
    });

    target.innerHTML = html;
    target.addEventListener('change', (event) => {
      const input = event.target.closest('input[type="checkbox"]');
      if (!input) return;
      input.closest('.available-cell').classList.toggle('is-selected', input.checked);
      setError('availability', '');
    });
  }

  function selectedAvailability() {
    return $$('#available-grid input[type="checkbox"]:checked').map((input) => ({
      day: input.dataset.day,
      start: input.dataset.start,
      end: input.dataset.end
    }));
  }

  /* ---------- Security questions ---------- */
  function fillQuestionBank() {
    const selects = $$('[data-security-key]');
    selects.forEach((select) => {
      select.innerHTML = '<option value="">Choose a question</option>' +
        state.questionBank.map((question) =>
          `<option value="${question.key}">${question.text}</option>`
        ).join('');
    });
  }

  function syncQuestionOptions() {
    const selects = $$('[data-security-key]');
    const chosen = selects.map((select) => select.value).filter(Boolean);
    selects.forEach((select) => {
      $$('option', select).forEach((option) => {
        if (!option.value) return;
        const usedElsewhere = chosen.includes(option.value) && select.value !== option.value;
        option.disabled = usedElsewhere;
      });
    });
  }

  function securityQuestions() {
    return $$('[data-security-key]').map((select, index) => ({
      key: select.value,
      answer: $('[data-security-answer="' + (index + 1) + '"]').value
    }));
  }

  /* ---------- Validation ---------- */
  function nameProblem(raw, required) {
    const text = String(raw || '').trim();
    if (!text) return required ? 'Enter this name.' : '';
    if (text.length > 50) return 'Keep this under 50 characters.';
    if (!LETTER_PATTERN.test(text) || !NAME_PATTERN.test(text)) {
      return 'Use letters, spaces, hyphens, apostrophes or periods only (no numbers).';
    }
    return '';
  }

  function validateStep(step) {
    clearErrors();
    let ok = true;
    const fail = (field, message) => {
      setError(field, message);
      ok = false;
    };

    if (step === 1) {
      const firstProblem = nameProblem(value('firstName'), true);
      if (firstProblem) fail('firstName', firstProblem);
      const middleProblem = nameProblem(value('middleName'), false);
      if (middleProblem) fail('middleName', middleProblem);
      const lastProblem = nameProblem(value('lastName'), true);
      if (lastProblem) fail('lastName', lastProblem);

      const email = value('email');
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        fail('email', 'Enter a valid email address.');
      }

      const password = $('#signup-password').value;
      if (password.length < 8) {
        fail('password', 'Use at least 8 characters.');
      } else if (!/[A-Za-z]/.test(password) || !/\d/.test(password)) {
        fail('password', 'Include at least one letter and one number.');
      }
      if ($('#signup-confirm').value !== password || !password) {
        fail('confirmPassword', "Passwords don't match.");
      }
      if (!$('#signup-terms').checked) {
        fail('terms', 'Please accept the terms to continue.');
      }
    }

    if (step === 2) {
      const birthdate = $('#signup-birthdate').value;
      if (!birthdate) {
        fail('birthdate', 'Enter your birthdate.');
      } else {
        const chosen = new Date(birthdate + 'T00:00:00');
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        if (Number.isNaN(chosen.getTime())) fail('birthdate', 'Use a valid date.');
        else if (chosen > today) fail('birthdate', 'Birthdate cannot be in the future.');
      }

      if (!value('barangay')) fail('barangay', 'Enter your barangay.');
      if (!value('city')) fail('city', 'Enter your city or municipality.');

      const bio = $('#signup-bio').value.trim();
      if (bio.length < 10) fail('bio', 'Write a short bio (at least 10 characters).');
      else if (bio.length > 600) fail('bio', 'Keep the bio under 600 characters.');

      const postal = value('postalCode');
      if (postal && !/^\d{4,10}$/.test(postal)) {
        fail('postalCode', 'Use a 4-10 digit ZIP code.');
      }

      const phone = value('phone');
      if (phone) {
        const digits = phone.replace(/\D/g, '');
        if (digits.length < 7 || digits.length > 15 || !/^\+?[0-9 ()\-]+$/.test(phone)) {
          fail('phone', 'Enter a valid phone number.');
        }
      }

      const experience = value('experienceYears');
      if (experience) {
        const years = Number(experience);
        if (!Number.isInteger(years) || years < 0 || years > 60) {
          fail('experienceYears', 'Enter a whole number between 0 and 60.');
        }
      }

      if (!selectedAvailability().length) {
        fail('availability', 'Pick at least one availability slot.');
      }
    }

    if (step === 3) {
      const questions = securityQuestions();
      const keys = questions.map((question) => question.key).filter(Boolean);
      if (keys.length !== 3 || new Set(keys).size !== 3) {
        fail('securityQuestions', 'Choose 3 different questions.');
      } else {
        for (let index = 0; index < questions.length; index += 1) {
          const answer = questions[index].answer.trim();
          if (answer.length < 2) {
            fail('securityQuestions', 'Enter an answer with at least 2 characters.');
            break;
          }
          if (answer.length > 100) {
            fail('securityQuestions', 'Keep each answer under 100 characters.');
            break;
          }
        }
      }
    }

    if (!ok) {
      const invalid = $('[aria-invalid="true"]');
      if (invalid) invalid.focus();
    }
    return ok;
  }

  function showServerErrors(errorFields) {
    if (!errorFields || typeof errorFields !== 'object') return;
    Object.entries(errorFields).forEach(([field, message]) => {
      setError(field, message);
    });
    const invalid = $('[aria-invalid="true"]');
    if (invalid) invalid.focus();
  }

  /* ---------- Submit ---------- */
  function buildPayload() {
    const experience = value('experienceYears');
    return {
      role: state.role,
      firstName: value('firstName'),
      middleName: value('middleName'),
      lastName: value('lastName'),
      email: value('email'),
      password: $('#signup-password').value,
      confirmPassword: $('#signup-confirm').value,
      terms: $('#signup-terms').checked,
      birthdate: value('birthdate'),
      gender: value('gender'),
      phone: value('phone'),
      addressLine: value('addressLine'),
      barangay: value('barangay'),
      city: value('city'),
      province: value('province'),
      postalCode: value('postalCode'),
      headline: value('headline'),
      bio: $('#signup-bio').value.trim(),
      school: value('school'),
      gradeLevel: value('gradeLevel'),
      course: value('course'),
      education: value('education'),
      experienceYears: experience === '' ? null : Number(experience),
      showPhone: $('#signup-show-phone').checked,
      showAddress: $('#signup-show-address').checked,
      availability: selectedAvailability(),
      securityQuestions: securityQuestions()
    };
  }

  function showVerify(email, message) {
    state.email = email;
    $('#signup-app').classList.add('hidden');
    const verify = $('#signup-verify');
    verify.classList.remove('hidden');
    const display = $('#verify-email-display');
    if (display) display.textContent = email;
    if (message) setStatus('verify-status', 'success', message);
    const otp = $('#verify-otp');
    if (otp) otp.focus();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  async function submitSignup(event) {
    event.preventDefault();
    if (state.submitting) return;
    if (!validateStep(1)) { setStep(1); return; }
    if (!validateStep(2)) { setStep(2); return; }
    if (!validateStep(3)) { setStep(3); return; }

    const submit = $('#signup-submit');
    state.submitting = true;
    if (submit) {
      submit.disabled = true;
      submit.textContent = 'Creating account…';
    }
    setStatus('signup-status', 'info', '');

    try {
      const result = await auth.register(buildPayload());
      showVerify(
        value('email'),
        result.message || 'Account created. Check your email for the 6-digit code.'
      );
    } catch (error) {
      if (error && error.fields) {
        showServerErrors(error.fields);
        const fieldNames = Object.keys(error.fields);
        if (fieldNames.some((name) => ['firstName', 'middleName', 'lastName', 'email', 'password', 'confirmPassword', 'terms'].includes(name))) {
          setStep(1);
        } else if (fieldNames.some((name) => ['securityQuestions'].includes(name))) {
          setStep(3);
        } else {
          setStep(2);
        }
      }
      setStatus('signup-status', 'error', (error && error.message) || 'Could not create your account.');
    } finally {
      state.submitting = false;
      if (submit) {
        submit.disabled = false;
        submit.innerHTML = 'Create account <i data-lucide="arrow-up-right" class="h-4 w-4"></i>';
        if (global.lucide) global.lucide.createIcons();
      }
    }
  }

  async function submitVerify(event) {
    event.preventDefault();
    clearErrors();
    const otp = $('#verify-otp').value.trim();
    if (!/^\d{6}$/.test(otp)) {
      setError('otp', 'Enter the 6-digit code.');
      $('#verify-otp').focus();
      return;
    }

    const button = $('#verify-form .signup-btn');
    if (button) {
      button.disabled = true;
      button.textContent = 'Verifying…';
    }

    try {
      await auth.verifyEmail({ email: state.email, otp });
      global.location.href = 'onboarding.html';
    } catch (error) {
      if (error && error.code === 'ALREADY_VERIFIED') {
        setStatus('verify-status', 'success', 'Email already verified. You can log in now.');
      } else {
        setStatus('verify-status', 'error', (error && error.message) || 'That code is invalid or expired.');
      }
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = 'Verify email';
      }
    }
  }

  async function resend() {
    if (!state.email) return;
    const button = $('#resend-otp');
    if (button) {
      button.disabled = true;
      button.textContent = 'Sending…';
    }
    try {
      await auth.resendOtp({ email: state.email });
      setStatus('verify-status', 'success', 'A new code was sent. Check your inbox and spam folder.');
    } catch (error) {
      setStatus('verify-status', 'error', (error && error.message) || 'Could not resend the code.');
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = 'Resend code';
      }
    }
  }

  /* ---------- Bind ---------- */
  function bind() {
    $$('input[name="role"]').forEach((input) => {
      input.addEventListener('change', () => setRole(input.value));
    });

    $('#signup-next').addEventListener('click', () => {
      if (!validateStep(state.step)) return;
      setStep(state.step + 1);
    });

    $('#signup-back').addEventListener('click', () => {
      setStep(state.step - 1);
    });

    $('#signup-form').addEventListener('submit', submitSignup);
    $('#verify-form').addEventListener('submit', submitVerify);
    $('#resend-otp').addEventListener('click', resend);

    const bio = $('#signup-bio');
    const bioCount = $('#signup-bio-count');
    if (bio && bioCount) {
      const update = () => { bioCount.textContent = String(bio.value.length); };
      bio.addEventListener('input', update);
      update();
    }

    $$('.signup-panel .field').forEach((field) => {
      field.addEventListener('input', () => {
        if (field.name) setError(field.name, '');
      });
      field.addEventListener('change', () => {
        if (field.name) setError(field.name, '');
      });
    });

    $$('[data-security-key]').forEach((select) => {
      select.addEventListener('change', () => {
        syncQuestionOptions();
        setError('securityQuestions', '');
      });
    });

    $$('[data-security-answer]').forEach((input) => {
      input.addEventListener('input', () => setError('securityQuestions', ''));
    });

    const birthdate = $('#signup-birthdate');
    if (birthdate) {
      const today = new Date();
      const iso = [
        today.getFullYear(),
        String(today.getMonth() + 1).padStart(2, '0'),
        String(today.getDate()).padStart(2, '0')
      ].join('-');
      birthdate.max = iso;
    }
  }

  async function init() {
    const params = new URLSearchParams(global.location.search);
    setRole(params.get('role') === 'tutor' ? 'tutor' : 'student');
    renderAvailability();
    bind();
    setStep(1, { focus: false });

    try {
      state.questionBank = await auth.getSecurityQuestionBank();
    } catch {
      state.questionBank = [];
    }
    fillQuestionBank();
    syncQuestionOptions();

    if (global.lucide) global.lucide.createIcons();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})(window);
