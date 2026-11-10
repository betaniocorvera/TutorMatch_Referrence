/* ==========================================================
   TutorMatch A.I. — shared auth client + local UI helpers
   The Flask session cookie is the source of truth. We only
   cache the current user in memory for the current page.
   ========================================================== */
(function (global) {
  'use strict';

  const LEGACY_USER_KEY = 'tutormatch_users';
  const LEGACY_SESSION_KEY = 'tutormatch_session';

  let currentUser = null;
  let profileCache = null;
  let csrfToken = '';
  let csrfPromise = null;
  let sentRequestsCache = [];
  let sentRequestIds = new Set();

  class ApiError extends Error {
    constructor(message, options = {}) {
      super(message || 'Request failed.');
      this.name = 'ApiError';
      this.code = options.code || 'ERROR';
      this.status = options.status || 0;
      this.fields = options.fields || {};
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
    sentRequestsCache = [];
    sentRequestIds = new Set();
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
    sentRequestsCache = [];
    sentRequestIds = new Set();
    if (options.redirect !== false) {
      global.location.href = 'index.html';
    }
  }

  function queryString(params = {}) {
    const search = new URLSearchParams();
    Object.keys(params).forEach((key) => {
      const value = params[key];
      if (value !== undefined && value !== null && value !== '') {
        search.set(key, value);
      }
    });
    const text = search.toString();
    return text ? '?' + text : '';
  }

  async function getRequests(params = {}) {
    return apiFetch('/api/requests' + queryString(params));
  }

  async function loadSentRequests() {
    const data = await getRequests({ box: 'outgoing', limit: 50 });
    sentRequestsCache = Array.isArray(data.requests) ? data.requests : [];
    sentRequestIds = new Set(
      sentRequestsCache
        .filter((item) => item.status === 'pending' || item.status === 'accepted')
        .map((item) => String(item.to && item.to.id))
    );
    return sentRequestsCache;
  }

  function getSentRequests() {
    return sentRequestsCache.slice();
  }

  function hasSentRequest(id) {
    return sentRequestIds.has(String(id));
  }

  function rememberSentRequest(request) {
    if (!request) return;
    const index = sentRequestsCache.findIndex((item) => item.id === request.id);
    if (index === -1) sentRequestsCache.unshift(request);
    else sentRequestsCache[index] = request;

    const personId = String(request.to && request.to.id);
    if (request.status === 'pending' || request.status === 'accepted') {
      sentRequestIds.add(personId);
    } else {
      sentRequestIds.delete(personId);
    }
  }

  async function createRequest(payload) {
    const data = await apiFetch('/api/requests', {
      method: 'POST',
      body: payload
    });
    rememberSentRequest(data.request);
    return data;
  }

  async function updateRequest(id, action) {
    const data = await apiFetch('/api/requests/' + encodeURIComponent(id), {
      method: 'PATCH',
      body: { action }
    });
    rememberSentRequest(data.request);
    return data;
  }

  async function getConversations(params = {}) {
    return apiFetch('/api/conversations' + queryString(params));
  }

  async function getConversation(id) {
    return apiFetch('/api/conversations/' + encodeURIComponent(id));
  }

  async function getMessages(id, params = {}) {
    return apiFetch(
      '/api/conversations/' + encodeURIComponent(id) + '/messages' + queryString(params)
    );
  }

  async function sendMessage(id, body) {
    return apiFetch('/api/conversations/' + encodeURIComponent(id) + '/messages', {
      method: 'POST',
      body: { type: 'text', body }
    });
  }

  async function markConversationRead(id, lastMessageId) {
    return apiFetch('/api/conversations/' + encodeURIComponent(id) + '/read', {
      method: 'PATCH',
      body: lastMessageId ? { lastMessageId } : {}
    });
  }

  async function getNotifications(params = {}) {
    return apiFetch('/api/notifications' + queryString(params));
  }

  async function markNotificationRead(id) {
    return apiFetch('/api/notifications/' + encodeURIComponent(id) + '/read', {
      method: 'PATCH',
      body: {}
    });
  }

  async function markAllNotificationsRead() {
    return apiFetch('/api/notifications/read-all', {
      method: 'PATCH',
      body: {}
    });
  }

  async function getSessions(params = {}) {
    return apiFetch('/api/sessions' + queryString(params));
  }

  async function createSession(payload) {
    return apiFetch('/api/sessions', {
      method: 'POST',
      body: payload
    });
  }

  async function updateSession(id, payload) {
    return apiFetch('/api/sessions/' + encodeURIComponent(id), {
      method: 'PATCH',
      body: payload
    });
  }

  async function reportUser(payload) {
    return apiFetch('/api/reports', {
      method: 'POST',
      body: payload
    });
  }

  async function blockUser(id) {
    return apiFetch('/api/blocks/' + encodeURIComponent(id), {
      method: 'POST',
      body: {}
    });
  }

  async function unblockUser(id) {
    return apiFetch('/api/blocks/' + encodeURIComponent(id), {
      method: 'DELETE'
    });
  }

  async function getBlocks() {
    return apiFetch('/api/blocks');
  }

  async function trackEvent(name, payload = {}) {
    return apiFetch('/api/events', {
      method: 'POST',
      body: { name, payload }
    });
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
    getRequests,
    loadSentRequests,
    getSentRequests,
    hasSentRequest,
    rememberSentRequest,
    createRequest,
    updateRequest,
    getConversations,
    getConversation,
    getMessages,
    sendMessage,
    markConversationRead,
    getNotifications,
    markNotificationRead,
    markAllNotificationsRead,
    getSessions,
    createSession,
    updateSession,
    reportUser,
    blockUser,
    unblockUser,
    getBlocks,
    trackEvent,
    getProfileCompleteness,
    setProfileCompleteness
  };
})(window);
