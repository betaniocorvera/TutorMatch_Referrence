/* ==========================================================
   TutorMatch A.I. — Notifications and blocked accounts
   ========================================================== */
(function (global) {
  'use strict';

  const auth = global.TutorMatchAuth;
  const POLL_MS = 30000;

  const state = {
    filter: 'all',
    loading: false,
    loaded: false,
    error: '',
    notifications: [],
    unreadCount: 0,
    blocks: [],
    blocksLoading: false,
    blocksError: ''
  };

  let els = null;
  let initialized = false;
  let pollTimer = null;
  let toastTimer = null;

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

  function formatDateTime(timestamp) {
    if (!timestamp) return '';
    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) return '';
    try {
      return new Intl.DateTimeFormat('en', {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit'
      }).format(date);
    } catch {
      return '';
    }
  }

  function relativeTime(timestamp) {
    if (!timestamp) return '';
    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) return '';
    const diff = Date.now() - date.getTime();
    const minutes = Math.floor(diff / 60000);
    if (minutes < 1) return 'Just now';
    if (minutes < 60) return minutes + ' min ago';
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return hours + ' hr ago';
    const days = Math.floor(hours / 24);
    if (days < 7) return days + ' day' + (days === 1 ? '' : 's') + ' ago';
    return formatDateTime(timestamp);
  }

  function showToast(message) {
    const toast = document.getElementById('toast');
    if (!toast) return;
    toast.textContent = message;
    toast.dataset.show = 'true';
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      toast.dataset.show = 'false';
    }, 3200);
  }

  function refreshIcons() {
    if (global.lucide) global.lucide.createIcons();
  }

  function payloadOf(notification) {
    return (notification && notification.payload) || {};
  }

  function notificationCopy(notification) {
    const payload = payloadOf(notification);
    const actor = payload.actorName || payload.fromName || payload.senderName || 'Someone';
    const starts = payload.startsAt ? formatDateTime(payload.startsAt) : '';
    switch (notification.type) {
      case 'request_received':
        return {
          icon: 'inbox',
          label: 'Request',
          title: actor + ' sent you a request',
          body: payload.subjectName
            ? 'Subject: ' + payload.subjectName + '. Review it in Messages.'
            : 'Review the request in Messages.'
        };
      case 'request_accepted':
        return {
          icon: 'check-circle-2',
          label: 'Request',
          title: actor + ' accepted your request',
          body: 'Chat is now open. Say hello and plan your first session.'
        };
      case 'request_declined':
        return {
          icon: 'x-circle',
          label: 'Request',
          title: actor + ' declined your request',
          body: 'Keep searching to find another match.'
        };
      case 'request_cancelled':
        return {
          icon: 'undo-2',
          label: 'Request',
          title: actor + ' cancelled a request',
          body: 'The request is no longer active.'
        };
      case 'message_received':
        return {
          icon: 'message-circle',
          label: 'Message',
          title: 'New message from ' + actor,
          body: payload.preview || 'Open the chat to read the message.'
        };
      case 'session_proposed':
        return {
          icon: 'calendar-plus',
          label: 'Session',
          title: actor + ' proposed a session',
          body: starts ? 'Proposed for ' + starts + '.' : 'Open the chat to review it.'
        };
      case 'session_accepted':
        return {
          icon: 'calendar-check',
          label: 'Session',
          title: actor + ' accepted the session',
          body: starts ? 'Confirmed for ' + starts + '.' : 'The session is confirmed.'
        };
      case 'session_declined':
        return {
          icon: 'calendar-x',
          label: 'Session',
          title: 'Session declined',
          body: actor + ' declined the proposed session.'
        };
      case 'session_rescheduled':
        return {
          icon: 'calendar-clock',
          label: 'Session',
          title: actor + ' rescheduled the session',
          body: starts ? 'New time: ' + starts + '.' : 'Open the chat for the new time.'
        };
      case 'session_cancelled':
        return {
          icon: 'calendar-x-2',
          label: 'Session',
          title: 'Session cancelled',
          body: actor + ' cancelled the session.'
        };
      case 'session_completed':
        return {
          icon: 'calendar-check-2',
          label: 'Session',
          title: 'Session completed',
          body: actor + ' marked the session complete.'
        };
      default:
        return {
          icon: 'bell',
          label: 'Update',
          title: 'New notification',
          body: 'Open TutorMatch to see the latest update.'
        };
    }
  }

  function renderNotifications() {
    if (!els || !els.list) return;
    if (state.loading && !state.loaded) {
      els.list.innerHTML = '<div class="notifications-loading">Loading notifications...</div>';
      return;
    }
    if (state.error && !state.loaded) {
      els.list.innerHTML =
        '<div class="notifications-error">' +
          '<p>' + escapeHtml(state.error) + '</p>' +
          '<button type="button" class="btn-outline" data-notifications-retry>Try again</button>' +
        '</div>';
      return;
    }
    if (!state.notifications.length) {
      els.list.innerHTML =
        '<div class="notifications-empty">' +
          '<div class="empty-icon"><i data-lucide="bell-off"></i></div>' +
          '<h3>' + (state.filter === 'unread' ? 'No unread notifications' : 'No notifications yet') + '</h3>' +
          '<p>' +
            (state.filter === 'unread'
              ? 'You are all caught up.'
              : 'Requests, messages, and session updates will appear here.') +
          '</p>' +
        '</div>';
      refreshIcons();
      return;
    }

    els.list.innerHTML = state.notifications.map((notification) => {
      const copy = notificationCopy(notification);
      const payload = payloadOf(notification);
      const unread = !notification.readAt;
      const conversationId = payload.conversationId;
      return '<article class="notification-item' + (unread ? ' unread' : '') + '">' +
        '<div class="notification-icon"><i data-lucide="' + copy.icon + '"></i></div>' +
        '<div class="notification-main">' +
          '<div class="notification-title-row">' +
            '<div>' +
              '<p class="notification-label">' + escapeHtml(copy.label) + '</p>' +
              '<h3>' + escapeHtml(copy.title) + '</h3>' +
            '</div>' +
            (unread ? '<span class="notification-dot" aria-label="Unread"></span>' : '') +
          '</div>' +
          '<p class="notification-copy">' + escapeHtml(copy.body) + '</p>' +
          '<p class="notification-meta">' +
            escapeHtml(relativeTime(notification.createdAt)) +
          '</p>' +
          '<div class="notification-actions">' +
            (conversationId
              ? '<button type="button" class="btn-dark-sm" data-notification-open="' +
                escapeHtml(notification.id) + '">Open chat</button>'
              : '') +
            (unread
              ? '<button type="button" class="btn-outline" data-notification-read="' +
                escapeHtml(notification.id) + '">Mark read</button>'
              : '') +
          '</div>' +
        '</div>' +
      '</article>';
    }).join('');
    refreshIcons();
  }

  function renderBlocked() {
    if (!els || !els.blockedList) return;
    if (els.blockedCount) els.blockedCount.textContent = state.blocks.length;
    if (state.blocksLoading && !state.blocks.length) {
      els.blockedList.innerHTML = '<div class="notifications-loading">Loading blocked accounts...</div>';
      return;
    }
    if (state.blocksError) {
      els.blockedList.innerHTML = '<div class="notifications-error"><p>' +
        escapeHtml(state.blocksError) + '</p></div>';
      return;
    }
    if (!state.blocks.length) {
      els.blockedList.innerHTML = '<p class="blocked-empty">You have not blocked anyone.</p>';
      return;
    }
    els.blockedList.innerHTML = state.blocks.map((person) => {
      const avatar = person.photoUrl
        ? '<span class="blocked-avatar"><img src="' + escapeHtml(person.photoUrl) +
          '" alt="" /></span>'
        : '<span class="blocked-avatar">' + escapeHtml(initials(person.name)) + '</span>';
      return '<div class="blocked-item">' +
        avatar +
        '<div class="blocked-main">' +
          '<strong>' + escapeHtml(person.name) + '</strong>' +
          '<span>' + escapeHtml(person.role === 'tutor' ? 'Tutor' : 'Student') +
            ' · Blocked ' + escapeHtml(relativeTime(person.blockedAt)) + '</span>' +
        '</div>' +
        '<button type="button" class="btn-outline" data-unblock-user="' +
          escapeHtml(person.userId) + '">Unblock</button>' +
      '</div>';
    }).join('');
  }

  function render() {
    if (!els) return;
    els.filters.querySelectorAll('[data-notification-filter]').forEach((button) => {
      const active = button.dataset.notificationFilter === state.filter;
      button.classList.toggle('active', active);
      button.setAttribute('aria-selected', String(active));
    });
    if (els.unreadLabel) {
      els.unreadLabel.textContent = state.unreadCount
        ? state.unreadCount + ' unread'
        : 'All caught up';
    }
    if (els.markAll) els.markAll.disabled = state.unreadCount === 0;
    const badge = document.getElementById('notifications-badge');
    if (badge) {
      badge.textContent = state.unreadCount > 9 ? '9+' : String(state.unreadCount);
      badge.classList.toggle('hidden', state.unreadCount === 0);
    }
    renderNotifications();
    renderBlocked();
  }

  async function refreshBadge() {
    try {
      const data = await auth.getNotifications({ unread: true, limit: 1 });
      state.unreadCount = Number(data.unreadCount || 0);
      const badge = document.getElementById('notifications-badge');
      if (badge) {
        badge.textContent = state.unreadCount > 9 ? '9+' : String(state.unreadCount);
        badge.classList.toggle('hidden', state.unreadCount === 0);
      }
      if (els && els.unreadLabel) {
        els.unreadLabel.textContent = state.unreadCount
          ? state.unreadCount + ' unread'
          : 'All caught up';
      }
    } catch {
      // Keep the current badge if notifications cannot be loaded.
    }
  }

  async function refreshNotifications(options = {}) {
    if (!els) return;
    const silent = Boolean(options.silent);
    if (!silent) {
      state.loading = true;
      state.error = '';
      render();
    }
    try {
      const params = { limit: 50 };
      if (state.filter === 'unread') params.unread = true;
      const data = await auth.getNotifications(params);
      state.notifications = data.notifications || [];
      state.unreadCount = Number(data.unreadCount || 0);
      state.loaded = true;
      state.loading = false;
      state.error = '';
      render();
    } catch (error) {
      state.loading = false;
      state.error = error.message || 'Could not load notifications.';
      render();
    }
  }

  async function refreshBlocks() {
    if (!els) return;
    state.blocksLoading = true;
    state.blocksError = '';
    renderBlocked();
    try {
      const data = await auth.getBlocks();
      state.blocks = data.blocks || [];
      state.blocksLoading = false;
      renderBlocked();
    } catch (error) {
      state.blocksLoading = false;
      state.blocksError = error.message || 'Could not load blocked accounts.';
      renderBlocked();
    }
  }

  async function refreshAll(options = {}) {
    await Promise.all([
      refreshNotifications(options),
      refreshBlocks()
    ]);
  }

  function notificationById(id) {
    return state.notifications.find(
      (notification) => String(notification.id) === String(id)
    ) || null;
  }

  async function markRead(id) {
    const notification = notificationById(id);
    if (!notification || notification.readAt) return;
    try {
      await auth.markNotificationRead(id);
      notification.readAt = new Date().toISOString();
      state.unreadCount = Math.max(0, state.unreadCount - 1);
      if (state.filter === 'unread') {
        state.notifications = state.notifications.filter(
          (item) => String(item.id) !== String(id)
        );
      }
      render();
    } catch (error) {
      showToast(error.message || 'Could not mark the notification as read.');
    }
  }

  async function markAllRead() {
    if (!state.unreadCount) return;
    els.markAll.disabled = true;
    try {
      await auth.markAllNotificationsRead();
      state.unreadCount = 0;
      state.notifications = state.notifications.map((notification) => ({
        ...notification,
        readAt: notification.readAt || new Date().toISOString()
      }));
      if (state.filter === 'unread') {
        state.notifications = [];
      }
      render();
      showToast('All notifications marked read.');
    } catch (error) {
      els.markAll.disabled = false;
      showToast(error.message || 'Could not mark notifications as read.');
    }
  }

  function openNotification(id) {
    const notification = notificationById(id);
    if (!notification) return;
    const payload = payloadOf(notification);
    markRead(id);
    if (!payload.conversationId) return;
    global.location.hash = '#messages';
    setTimeout(() => {
      global.dispatchEvent(new CustomEvent('tutormatch:open-conversation', {
        detail: { id: payload.conversationId }
      }));
    }, 0);
  }

  async function unblockUser(userId) {
    const person = state.blocks.find(
      (item) => String(item.userId) === String(userId)
    );
    if (!person) return;
    if (!global.confirm('Unblock ' + person.name + '?')) return;
    try {
      await auth.unblockUser(userId);
      state.blocks = state.blocks.filter(
        (item) => String(item.userId) !== String(userId)
      );
      renderBlocked();
      showToast('Unblocked ' + person.name + '.');
      global.dispatchEvent(new CustomEvent('tutormatch:blocks-changed'));
    } catch (error) {
      showToast(error.message || 'Could not unblock this person.');
    }
  }

  function bind() {
    els.filters.addEventListener('click', (event) => {
      const button = event.target.closest('[data-notification-filter]');
      if (!button) return;
      state.filter = button.dataset.notificationFilter;
      state.loaded = false;
      refreshNotifications();
    });

    els.list.addEventListener('click', (event) => {
      const retry = event.target.closest('[data-notifications-retry]');
      if (retry) {
        refreshNotifications();
        return;
      }
      const open = event.target.closest('[data-notification-open]');
      if (open) {
        openNotification(open.dataset.notificationOpen);
        return;
      }
      const read = event.target.closest('[data-notification-read]');
      if (read) markRead(read.dataset.notificationRead);
    });

    if (els.markAll) els.markAll.addEventListener('click', markAllRead);
    if (els.refresh) {
      els.refresh.addEventListener('click', () => {
        refreshAll();
        showToast('Notifications refreshed.');
      });
    }
    if (els.blockedList) {
      els.blockedList.addEventListener('click', (event) => {
        const button = event.target.closest('[data-unblock-user]');
        if (button) unblockUser(button.dataset.unblockUser);
      });
    }

    global.addEventListener('tutormatch:blocks-changed', () => {
      refreshBlocks();
      refreshNotifications({ silent: true });
    });

    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(() => {
      if (document.hidden) return;
      refreshBadge();
      const section = document.getElementById('section-notifications');
      if (section && !section.classList.contains('hidden')) {
        refreshNotifications({ silent: true });
      }
    }, POLL_MS);
  }

  function init() {
    if (initialized) return;
    els = {
      filters: document.querySelector('.notification-filters'),
      list: document.getElementById('notifications-list'),
      unreadLabel: document.getElementById('notifications-unread-label'),
      markAll: document.getElementById('notifications-mark-all'),
      refresh: document.getElementById('notifications-refresh'),
      blockedList: document.getElementById('blocked-list'),
      blockedCount: document.getElementById('blocked-count')
    };
    if (!els.filters || !els.list) return;
    initialized = true;
    bind();
    refreshAll();
  }

  global.TutorMatchNotifications = {
    init,
    render,
    refresh: refreshAll,
    refreshBadge
  };
})(window);
