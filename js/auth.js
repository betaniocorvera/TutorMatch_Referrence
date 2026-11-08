/* ==========================================================
   TutorMatch A.I. — shared auth client + local UI helpers
   The Flask session cookie is the source of truth. We only
   cache the current user in memory for the current page.
   ========================================================== */
(function (global) {
  'use strict';

  const SENT_KEY = 'tutormatch_sent_requests';
  const LEGACY_USER_KEY = 'tutormatch_users';
  const LEGACY_SESSION_KEY = 'tutormatch_session';

  let currentUser = null;
  let profileCache = null;
  let csrfToken = '';
  let csrfPromise = null;

  class ApiError extends Error {
    constructor(message, options = {}) {
      super(message || 'Request failed.');
      this.name = 'ApiError';
      this.code = options.code || 'ERROR';
      this.status = options.status || 0;
      this.fields = options.fields || {};
    }
  }

  function safeParse(value, fallback) {
    try {
      return JSON.parse(value);
    } catch {
      return fallback;
    }
  }

  /* Remove the old front-end demo accounts. These keys stored
     password hashes in the browser; the real app never does. */
  function clearLegacyDemoStorage() {
    try {
      localStorage.removeItem(LEGACY_USER_KEY);
      localStorage.removeItem(LEGACY_SESSION_KEY);
      sessionStorage.removeItem(LEGACY_SESSION_KEY);
    } catch {
      /* Storage can be blocked; the server session still works. */
    }
  }
  clearLegacyDemoStorage();

  function normalizeUser(user) {
    if (!user) return null;
    return {
      ...user,
      role: user.role === 'tutor' ? 'tutor' : 'student'
    };
  }

  function getSession() {
    return currentUser;
  }

  function setSessionUser(user) {
    const nextUser = normalizeUser(user);
    if (!currentUser || !nextUser || currentUser.id !== nextUser.id) {
      profileCache = null;
    }
    currentUser = nextUser;
    return currentUser;
  }

  function saveSession(user) {
    return setSessionUser(user);
  }

  function clearSession() {
    currentUser = null;
    profileCache = null;
  }

  function invalidateCsrf() {
    csrfToken = '';
  }

  async function ensureCsrf(force = false) {
    if (csrfToken && !force) return csrfToken;
    if (csrfPromise && !force) return csrfPromise;

    csrfPromise = fetch('/api/csrf', {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' }
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new ApiError('Cannot reach the server. Start the Flask app.', {
            code: 'SERVER_UNAVAILABLE',
            status: response.status
          });
        }
        const data = await response.json();
        csrfToken = data.csrf_token || '';
        if (!csrfToken) {
          throw new ApiError('The server did not return a CSRF token.', {
            code: 'SERVER_UNAVAILABLE'
          });
        }
        return csrfToken;
      })
      .finally(() => {
        csrfPromise = null;
      });

    return csrfPromise;
  }

  async function apiFetch(path, options = {}, canRetry = true) {
    const method = options.method || 'GET';
    const headers = {
      Accept: 'application/json',
      ...(options.headers || {})
    };
    const requestOptions = {
      method,
      credentials: 'same-origin',
      headers
    };

    if (options.body !== undefined && options.body !== null) {
      headers['Content-Type'] = 'application/json';
      requestOptions.body = JSON.stringify(options.body);
    }

    if (method !== 'GET' && method !== 'HEAD') {
      headers['X-CSRFToken'] = await ensureCsrf();
    }

    let response;
    try {
      response = await fetch(path, requestOptions);
    } catch {
      throw new ApiError('Cannot reach the server. Start the Flask app.', {
        code: 'SERVER_UNAVAILABLE'
      });
    }

    if (response.status === 204) return null;

    let data = null;
    try {
      data = await response.json();
    } catch {
      data = null;
    }

    if (!response.ok) {
      const error = (data && data.error) || {};

      /* A stale CSRF token usually means the session cookie expired.
         Fetch a fresh token and retry the request once. */
      if (response.status === 400 && error.code === 'CSRF_ERROR' && canRetry) {
        invalidateCsrf();
        await ensureCsrf(true);
        return apiFetch(path, options, false);
      }

      throw new ApiError(error.message || 'Request failed.', {
        code: error.code,
        status: response.status,
        fields: error.fields
      });
    }

    return data;
  }

  async function fetchMe() {
    try {
      const data = await apiFetch('/api/auth/me');
      return setSessionUser(data && data.user);
    } catch {
      currentUser = null;
      return null;
    }
  }

  async function requireSession(options = {}) {
    const user = await fetchMe();
    if (!user) {
      global.location.replace('index.html?login=1');
      return null;
    }

    if (!options.allowIncomplete) {
      if (user.onboardingRequired) {
        global.location.replace('onboarding.html');
        return null;
      }
      try {
        await fetchProfile(true);
      } catch {
        /* The profile card can retry; the dashboard route already
           checks onboarding completion on the server. */
      }
    }
    return user;
  }

  async function fetchProfile(force = false) {
    if (profileCache && !force) return profileCache;
    const data = await apiFetch('/api/me/profile');
    profileCache = (data && data.profile) || null;
    return profileCache;
  }

  function getProfile() {
    return profileCache;
  }

  async function updateProfile(updates) {
    const data = await apiFetch('/api/me/profile', {
      method: 'PATCH',
      body: updates
    });
    profileCache = (data && data.profile) || null;
    return profileCache;
  }

  async function uploadPhoto(file) {
    async function send(canRetry) {
      const form = new FormData();
      form.append('photo', file);
      const headers = {
        Accept: 'application/json',
        'X-CSRFToken': await ensureCsrf()
      };

      let response;
      try {
        response = await fetch('/api/me/photo', {
          method: 'POST',
          credentials: 'same-origin',
          headers,
          body: form
        });
      } catch {
        throw new ApiError('Cannot reach the server. Start the Flask app.', {
          code: 'SERVER_UNAVAILABLE'
        });
      }

      let data = null;
      try {
        data = await response.json();
      } catch {
        data = null;
      }

      if (!response.ok) {
        const error = (data && data.error) || {};
        if (response.status === 400 && error.code === 'CSRF_ERROR' && canRetry) {
          invalidateCsrf();
          await ensureCsrf(true);
          return send(false);
        }
        throw new ApiError(error.message || 'Could not upload the photo.', {
          code: error.code,
          status: response.status,
          fields: error.fields
        });
      }

      if (profileCache && data) {
        profileCache.photoUrl = data.photoUrl;
      }
      return data;
    }

    return send(true);
  }

  async function getSubjects() {
    const data = await apiFetch('/api/subjects');
    return (data && data.subjects) || [];
  }

  async function getLevels() {
    const data = await apiFetch('/api/levels');
    return (data && data.levels) || [];
  }

  async function login({ email, password, remember }) {
    const data = await apiFetch('/api/auth/login', {
      method: 'POST',
      body: { email, password, remember: !!remember }
    });
    setSessionUser(data && data.user);
    return data;
  }

  async function register({ name, email, password, role }) {
    return apiFetch('/api/auth/register', {
      method: 'POST',
      body: { name, email, password, role }
    });
  }

  async function verifyEmail({ email, otp }) {
    const data = await apiFetch('/api/auth/verify-email', {
      method: 'POST',
      body: { email, otp }
    });
    setSessionUser(data && data.user);
    return data;
  }

  async function resendOtp({ email }) {
    return apiFetch('/api/auth/resend-otp', {
      method: 'POST',
      body: { email }
    });
  }

  async function forgotPassword({ email }) {
    return apiFetch('/api/auth/forgot-password', {
      method: 'POST',
      body: { email }
    });
  }

  async function resetPassword({ token, password }) {
    return apiFetch('/api/auth/reset-password', {
      method: 'POST',
      body: { token, password }
    });
  }

  async function logout(options = {}) {
    await apiFetch('/api/auth/logout', { method: 'POST' });
    currentUser = null;
    profileCache = null;
    if (options.redirect !== false) {
      global.location.href = 'index.html';
    }
  }

  function getSentRequests() {
    const list = safeParse(localStorage.getItem(SENT_KEY), []);
    return Array.isArray(list) ? list : [];
  }

  function hasSentRequest(id) {
    return getSentRequests().some((item) => item.id === id);
  }

  function saveSentRequest(person) {
    if (!person || !person.id || hasSentRequest(person.id)) {
      return getSentRequests();
    }
    const list = getSentRequests();
    list.push({
      id: person.id,
      name: person.name,
      role: person.role,
      subjects: person.subjects || [],
      sentAt: Date.now(),
      status: 'pending'
    });
    localStorage.setItem(SENT_KEY, JSON.stringify(list));
    return list;
  }

  function getProfileCompleteness() {
    if (profileCache && Number.isFinite(Number(profileCache.completeness))) {
      return Math.max(0, Math.min(100, Number(profileCache.completeness)));
    }
    return 0;
  }

  function setProfileCompleteness(value) {
    const n = Math.max(0, Math.min(100, Number(value) || 0));
    if (profileCache) profileCache.completeness = n;
    return n;
  }

  global.TutorMatchAuth = {
    ApiError,
    apiFetch,
    ensureCsrf,
    invalidateCsrf,
    fetchMe,
    requireSession,
    fetchProfile,
    getProfile,
    updateProfile,
    uploadPhoto,
    getSubjects,
    getLevels,
    getSession,
    setSessionUser,
    saveSession,
    clearSession,
    login,
    register,
    verifyEmail,
    resendOtp,
    forgotPassword,
    resetPassword,
    logout,
    getSentRequests,
    hasSentRequest,
    saveSentRequest,
    getProfileCompleteness,
    setProfileCompleteness
  };
})(window);
