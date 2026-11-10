/* ==========================================================
   TutorMatch A.I. — Messages section
   Persistent incoming/outgoing requests and unlocked chats.
   ========================================================== */
(function (global) {
  'use strict';

  const auth = global.TutorMatchAuth;
  const POLL_MS = 20000;

  const state = {
    tab: 'incoming',
    loading: false,
    loaded: false,
    error: '',
    incoming: [],
    outgoing: [],
    conversations: [],
    activeId: null,
    active: null,
    messages: [],
    messagesLoading: false,
    sending: false,
    sessionMode: 'propose',
    sessionEditingId: null,
    sessionSaving: false,
    reportSaving: false,
    reportUserId: null
  };

  let els = null;
  let initialized = false;
  let toastTimer = null;
  let pollTimer = null;

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
    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) return '';
    const now = new Date();
    const options = { month: 'short', day: 'numeric' };
    if (date.getFullYear() !== now.getFullYear()) options.year = 'numeric';
    try {
      return new Intl.DateTimeFormat('en', options).format(date);
    } catch {
      return '';
    }
  }

  function formatTime(timestamp) {
    if (!timestamp) return '';
    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) return '';
    try {
      return new Intl.DateTimeFormat('en', {
        hour: 'numeric',
        minute: '2-digit'
      }).format(date);
    } catch {
      return '';
    }
  }

  function formatDateTime(timestamp) {
    if (!timestamp) return 'Date to be confirmed';
    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) return 'Date to be confirmed';
    try {
      return new Intl.DateTimeFormat('en', {
        weekday: 'short',
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit'
      }).format(date);
    } catch {
      return 'Date to be confirmed';
    }
  }

  function toDatetimeLocal(timestamp) {
    const date = timestamp ? new Date(timestamp) : new Date();
    if (Number.isNaN(date.getTime())) return '';
    const pad = (value) => String(value).padStart(2, '0');
    return [
      date.getFullYear(),
      '-',
      pad(date.getMonth() + 1),
      '-',
      pad(date.getDate()),
      'T',
      pad(date.getHours()),
      ':',
      pad(date.getMinutes())
    ].join('');
  }

  function defaultSessionStart() {
    const date = new Date();
    date.setDate(date.getDate() + 1);
    date.setHours(18, 0, 0, 0);
    return toDatetimeLocal(date.toISOString());
  }

  function activeOtherUser() {
    const active = state.active;
    if (!active) return null;
    const me = auth.getSession() || {};
    const participants = active.participants || [];
    return participants.find(
      (participant) => String(participant.id) !== String(me.id)
    ) || null;
  }

  function conversationIsBlocked() {
    const active = state.active;
    if (!active) return false;
    return Boolean(
      active.blockedByMe ||
      active.blockedByOther ||
      active.status === 'blocked'
    );
  }

  function refreshIcons() {
    if (global.lucide) global.lucide.createIcons();
  }

  function statusLabel(status) {
    const labels = {
      pending: 'Pending',
      accepted: 'Accepted',
      declined: 'Declined',
      cancelled: 'Cancelled',
      expired: 'Expired',
      active: 'Chat open',
      locked: 'Locked',
      blocked: 'Blocked',
      archived: 'Archived',
      proposed: 'Proposed',
      rescheduled: 'Rescheduled',
      completed: 'Completed'
    };
    return labels[status] || status || 'Unknown';
  }

  function roleLabel(role) {
    return role === 'tutor' ? 'Tutor' : 'Student';
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

  function renderAvatar(person, className) {
    const name = (person && person.name) || '?';
    if (person && person.photoUrl) {
      return '<span class="' + className + '" aria-hidden="true"><img src="' +
        escapeHtml(person.photoUrl) + '" alt="" /></span>';
    }
    return '<span class="' + className + '" aria-hidden="true">' +
      escapeHtml(initials(name)) + '</span>';
  }

  function renderStatusChip(status) {
    return '<span class="status-chip status-' + escapeHtml(status) + '">' +
      escapeHtml(statusLabel(status)) + '</span>';
  }

  function emptyState(title, copy, action) {
    return '<div class="messages-empty">' +
      '<div class="empty-icon"><i data-lucide="inbox"></i></div>' +
      '<h3>' + escapeHtml(title) + '</h3>' +
      '<p>' + escapeHtml(copy) + '</p>' +
      (action || '') +
    '</div>';
  }

  function renderRequests(list, box) {
    if (!list.length) {
      return box === 'incoming'
        ? emptyState(
            'No incoming requests',
            'When someone asks to connect, their request will appear here.'
          )
        : emptyState(
            'No outgoing requests',
            'Use Search to send a request to a tutor or student.'
          );
    }

    return list.map((request) => {
      const other = box === 'incoming' ? request.from : request.to;
      const subject = request.subject ? request.subject.name : 'General request';
      const pending = request.status === 'pending';
      const canOpen = request.status === 'accepted' && request.conversationId;
      const actions = [];

      if (box === 'incoming' && pending) {
        actions.push(
          '<button type="button" class="btn-dark-sm message-action" data-request-action="accept" data-request-id="' +
            escapeHtml(request.id) + '">Accept</button>'
        );
        actions.push(
          '<button type="button" class="btn-outline message-action" data-request-action="decline" data-request-id="' +
            escapeHtml(request.id) + '">Decline</button>'
        );
      }
      if (box === 'outgoing' && pending) {
        actions.push(
          '<button type="button" class="btn-outline message-action" data-request-action="cancel" data-request-id="' +
            escapeHtml(request.id) + '">Cancel</button>'
        );
      }
      if (canOpen) {
        actions.push(
          '<button type="button" class="btn-dark-sm message-action" data-open-conversation="' +
            escapeHtml(request.conversationId) + '">Open chat</button>'
        );
      }

      return '<article class="message-item' + (pending ? ' is-pending' : '') + '">' +
        renderAvatar(other, 'message-avatar') +
        '<div class="message-main">' +
          '<div class="message-name-row">' +
            '<strong>' + escapeHtml(other ? other.name : 'Unknown') + '</strong>' +
            renderStatusChip(request.status) +
          '</div>' +
          '<p class="message-subject">' + escapeHtml(subject) + '</p>' +
          '<p class="message-preview">' +
            escapeHtml(request.message || 'No introduction message.') +
          '</p>' +
          '<p class="message-meta">' +
            (box === 'incoming' ? 'Received ' : 'Sent ') +
            escapeHtml(formatDate(request.createdAt)) +
            (pending && request.expiresAt
              ? ' · Expires ' + escapeHtml(formatDate(request.expiresAt))
              : '') +
          '</p>' +
          (actions.length
            ? '<div class="message-actions">' + actions.join('') + '</div>'
            : '') +
        '</div>' +
      '</article>';
    }).join('');
  }

  function renderConversations() {
    if (!state.conversations.length) {
      return emptyState(
        'No conversations yet',
        'Chat unlocks only after an incoming request is accepted.'
      );
    }

    return state.conversations.map((conversation) => {
      const other = conversation.otherUser || {};
      const active = String(conversation.id) === String(state.activeId);
      const preview = conversation.lastMessage && conversation.lastMessage.preview
        ? conversation.lastMessage.preview
        : 'No messages yet.';
      const unread = Number(conversation.unreadCount || 0);
      const subject = conversation.subject ? conversation.subject.name : 'Tutoring';

      return '<button type="button" class="message-item message-item-button' +
          (active ? ' active' : '') +
          '" data-open-conversation="' + escapeHtml(conversation.id) + '">' +
        renderAvatar(other, 'message-avatar') +
        '<span class="message-main">' +
          '<span class="message-name-row">' +
            '<strong>' + escapeHtml(other.name || 'Conversation') + '</strong>' +
            (unread
              ? '<span class="unread-badge">' + (unread > 9 ? '9+' : unread) + '</span>'
              : '') +
          '</span>' +
          '<span class="message-subject">' + escapeHtml(subject) + '</span>' +
          '<span class="message-preview">' + escapeHtml(preview) + '</span>' +
          '<span class="message-meta">' +
            escapeHtml(formatDate(conversation.lastMessageAt)) +
          '</span>' +
        '</span>' +
      '</button>';
    }).join('');
  }

  function renderList() {
    if (!els || !els.list) return;

    if (state.loading && !state.loaded) {
      els.list.innerHTML = '<div class="messages-loading">Loading messages...</div>';
      return;
    }
    if (state.error && !state.loaded) {
      els.list.innerHTML = '<div class="messages-error">' +
        '<p>' + escapeHtml(state.error) + '</p>' +
        '<button type="button" class="btn-outline" data-messages-retry>Try again</button>' +
      '</div>';
      return;
    }

    if (state.tab === 'incoming') {
      els.list.innerHTML = renderRequests(state.incoming, 'incoming');
    } else if (state.tab === 'outgoing') {
      els.list.innerHTML = renderRequests(state.outgoing, 'outgoing');
    } else {
      els.list.innerHTML = renderConversations();
    }
  }

  function renderMessage(message, meId, otherName) {
    if (message.type === 'system') {
      return '<div class="chat-system">' + escapeHtml(message.body || '') + '</div>';
    }
    const own = String(message.senderId) === String(meId);
    const body = escapeHtml(message.body || '').replace(/\n/g, '<br>');
    return '<div class="chat-row ' + (own ? 'own' : 'other') + '">' +
      (!own ? '<span class="chat-author">' + escapeHtml(otherName) + '</span>' : '') +
      '<div class="chat-bubble">' + body + '</div>' +
      '<span class="chat-time">' + escapeHtml(formatTime(message.createdAt)) + '</span>' +
    '</div>';
  }

  function renderSessionCard() {
    if (!els || !els.sessionCard) return;
    const active = state.active;
    const session = active && active.latestSession;
    if (!session) {
      els.sessionCard.classList.add('hidden');
      els.sessionCard.innerHTML = '';
      return;
    }

    const me = auth.getSession() || {};
    const other = activeOtherUser() || {};
    const proposedByMe = String(session.proposedBy) === String(me.id);
    const blocked = conversationIsBlocked();
    const status = session.status || 'proposed';
    const formatLabels = {
      online: 'Online',
      in_person: 'In-person',
      both: 'Online or in-person'
    };
    const actions = [];

    if (!blocked) {
      if (!proposedByMe && (status === 'proposed' || status === 'rescheduled')) {
        actions.push(
          '<button type="button" class="btn-dark-sm" data-session-action="accept" data-session-id="' +
            escapeHtml(session.id) + '">Accept</button>'
        );
        actions.push(
          '<button type="button" class="btn-outline" data-session-action="decline" data-session-id="' +
            escapeHtml(session.id) + '">Decline</button>'
        );
      }
      if (status === 'proposed' || status === 'rescheduled' || status === 'accepted') {
        actions.push(
          '<button type="button" class="btn-outline" data-session-action="reschedule" data-session-id="' +
            escapeHtml(session.id) + '">Reschedule</button>'
        );
      }
      if (status === 'accepted') {
        actions.push(
          '<button type="button" class="btn-dark-sm" data-session-action="complete" data-session-id="' +
            escapeHtml(session.id) + '">Mark complete</button>'
        );
      }
      if (status === 'proposed' || status === 'rescheduled' || status === 'accepted') {
        actions.push(
          '<button type="button" class="btn-outline" data-session-action="cancel" data-session-id="' +
            escapeHtml(session.id) + '">Cancel</button>'
        );
      }
    }

    let hint = '';
    if (blocked) {
      hint = 'Session actions are paused while a block is active.';
    } else if (proposedByMe && (status === 'proposed' || status === 'rescheduled')) {
      hint = 'Waiting for ' + (other.name || 'the other participant') + ' to respond.';
    } else if (status === 'accepted') {
      hint = 'The session is confirmed. Use the chat to share final details.';
    } else if (status === 'completed') {
      hint = 'This session is complete.';
    } else if (status === 'declined' || status === 'cancelled') {
      hint = 'You can propose a new session from the chat.';
    }

    els.sessionCard.classList.remove('hidden');
    els.sessionCard.innerHTML =
      '<div class="session-card-head">' +
        '<div>' +
          '<p class="eyebrow">Session plan</p>' +
          '<h3>' + escapeHtml(formatDateTime(session.startsAt)) + '</h3>' +
        '</div>' +
        renderStatusChip(status) +
      '</div>' +
      '<div class="session-card-meta">' +
        '<span><i data-lucide="clock"></i>' +
          escapeHtml(String(session.durationMins || 60)) + ' minutes</span>' +
        '<span><i data-lucide="video"></i>' +
          escapeHtml(formatLabels[session.format] || session.format || 'Format to confirm') +
        '</span>' +
        '<span><i data-lucide="user-round"></i>Proposed by ' +
          escapeHtml(proposedByMe ? 'you' : (session.proposedByName || other.name || 'them')) +
        '</span>' +
      '</div>' +
      (session.location
        ? '<p class="session-card-line"><strong>Location:</strong> ' +
          escapeHtml(session.location) + '</p>'
        : '') +
      (session.note
        ? '<p class="session-card-line"><strong>Note:</strong> ' +
          escapeHtml(session.note).replace(/\n/g, '<br>') + '</p>'
        : '') +
      (hint ? '<p class="session-card-hint">' + escapeHtml(hint) + '</p>' : '') +
      (actions.length
        ? '<div class="session-card-actions">' + actions.join('') + '</div>'
        : '');
    refreshIcons();
  }

  function renderChat() {
    if (!els) return;
    const active = state.active;
    if (!active) {
      els.chatEmpty.classList.remove('hidden');
      els.chatThread.classList.add('hidden');
      if (els.sessionCard) {
        els.sessionCard.classList.add('hidden');
        els.sessionCard.innerHTML = '';
      }
      if (els.chatNotice) els.chatNotice.classList.add('hidden');
      if (els.chatPropose) els.chatPropose.disabled = true;
      if (els.chatReport) els.chatReport.disabled = true;
      if (els.chatBlock) els.chatBlock.disabled = true;
      return;
    }

    els.chatEmpty.classList.add('hidden');
    els.chatThread.classList.remove('hidden');

    const me = auth.getSession() || {};
    const other = activeOtherUser() || {};
    const subject = active.request && active.request.subject
      ? active.request.subject.name
      : 'Tutoring';
    const blocked = conversationIsBlocked();
    const chatOpen = active.status === 'active' && !blocked;

    els.chatTitle.textContent = other.name || 'Conversation';
    els.chatSubtitle.textContent = roleLabel(other.role) + ' · ' + subject;
    els.chatStatus.textContent = statusLabel(active.status);
    els.chatStatus.className = 'status-chip status-' + (blocked ? 'blocked' : active.status);
    els.chatInput.disabled = !chatOpen;
    els.chatSend.disabled = !chatOpen || state.sending;
    els.chatSend.textContent = state.sending ? 'Sending...' : 'Send';
    if (els.chatPropose) els.chatPropose.disabled = !chatOpen;
    if (els.chatReport) els.chatReport.disabled = false;
    if (els.chatBlock) {
      els.chatBlock.disabled = Boolean(active.blockedByOther);
      els.chatBlock.textContent = active.blockedByMe
        ? 'Unblock'
        : active.blockedByOther ? 'Blocked' : 'Block';
    }
    if (els.chatNotice) {
      let notice = '';
      if (active.blockedByMe) {
        notice = 'You blocked this person. Unblock to reopen the conversation.';
      } else if (active.blockedByOther) {
        notice = 'This conversation is read-only because the other person blocked you.';
      } else if (active.status !== 'active') {
        notice = 'This conversation is not open.';
      }
      els.chatNotice.textContent = notice;
      els.chatNotice.classList.toggle('hidden', !notice);
    }

    renderSessionCard();

    if (state.messagesLoading) {
      els.chatMessages.innerHTML = '<div class="messages-loading">Loading conversation...</div>';
      return;
    }
    if (!state.messages.length) {
      els.chatMessages.innerHTML = '<div class="chat-empty-inline">No messages yet. Say hello!</div>';
      return;
    }

    els.chatMessages.innerHTML = state.messages
      .map((message) => renderMessage(message, me.id, other.name || 'Them'))
      .join('');
  }

  function render() {
    if (!els) return;

    els.tabs.querySelectorAll('[data-messages-tab]').forEach((tab) => {
      const active = tab.dataset.messagesTab === state.tab;
      tab.classList.toggle('active', active);
      tab.setAttribute('aria-selected', String(active));
    });

    if (els.incomingCount) els.incomingCount.textContent = state.incoming.length;
    if (els.outgoingCount) els.outgoingCount.textContent = state.outgoing.length;
    if (els.conversationCount) {
      els.conversationCount.textContent = state.conversations.length;
    }

    renderList();
    renderChat();
  }

  function scrollChatToBottom() {
    if (!els || !els.chatMessages) return;
    els.chatMessages.scrollTop = els.chatMessages.scrollHeight;
  }

  async function refreshBadge() {
    const badge = document.getElementById('messages-badge');
    if (!badge) return;
    const count = state.conversations.reduce(
      (total, conversation) => total + Number(conversation.unreadCount || 0),
      0
    );
    badge.textContent = count > 9 ? '9+' : String(count);
    badge.classList.toggle('hidden', count === 0);
  }

  async function refreshActiveConversation() {
    if (!state.activeId) return;
    try {
      const results = await Promise.all([
        auth.getConversation(state.activeId),
        auth.getMessages(state.activeId, { limit: 50 })
      ]);
      state.active = results[0].conversation;
      state.messages = results[1].messages || [];
      const last = state.messages[state.messages.length - 1];
      if (last) {
        await auth.markConversationRead(state.activeId, last.id).catch(() => {});
      }
      const conversation = state.conversations.find(
        (item) => String(item.id) === String(state.activeId)
      );
      if (conversation) conversation.unreadCount = 0;
      render();
      refreshBadge();
      scrollChatToBottom();
    } catch {
      // The next manual refresh will surface any problem.
    }
  }

  function errorMessage(error, fallback) {
    if (error && error.fields && typeof error.fields === 'object') {
      const first = Object.keys(error.fields)
        .map((key) => error.fields[key])
        .find(Boolean);
      if (first) return first;
    }
    return (error && error.message) || fallback;
  }

  function openSessionDialog(mode, session) {
    if (!els.sessionDialog || !state.activeId || conversationIsBlocked()) return;
    state.sessionMode = mode === 'reschedule' ? 'reschedule' : 'propose';
    state.sessionEditingId = state.sessionMode === 'reschedule' && session
      ? session.id
      : null;
    els.sessionDialogTitle.textContent = state.sessionMode === 'reschedule'
      ? 'Reschedule session'
      : 'Propose a session';
    els.sessionSubmit.textContent = state.sessionMode === 'reschedule'
      ? 'Update proposal'
      : 'Send proposal';
    els.sessionError.textContent = '';
    els.sessionStarts.min = toDatetimeLocal(new Date().toISOString());
    els.sessionDuration.value = '60';
    els.sessionFormat.value = 'online';
    els.sessionLocation.value = '';
    els.sessionNote.value = '';
    els.sessionStarts.value = defaultSessionStart();
    if (session) {
      els.sessionStarts.value = toDatetimeLocal(session.startsAt) ||
        defaultSessionStart();
      els.sessionDuration.value = String(session.durationMins || 60);
      els.sessionFormat.value = session.format || 'online';
      els.sessionLocation.value = session.location || '';
      els.sessionNote.value = session.note || '';
    }
    els.sessionDialog.dataset.open = 'true';
    setTimeout(() => els.sessionStarts.focus(), 0);
  }

  function closeSessionDialog() {
    if (!els.sessionDialog) return;
    els.sessionDialog.dataset.open = 'false';
    state.sessionMode = 'propose';
    state.sessionEditingId = null;
  }

  function openReportDialog() {
    if (!els.reportDialog || !state.active) return;
    const other = activeOtherUser();
    if (!other) return;
    state.reportUserId = other.id;
    els.reportForm.reset();
    els.reportError.textContent = '';
    els.reportDialog.dataset.open = 'true';
    setTimeout(() => els.reportReason.focus(), 0);
  }

  function closeReportDialog() {
    if (!els.reportDialog) return;
    els.reportDialog.dataset.open = 'false';
    state.reportUserId = null;
    els.reportError.textContent = '';
  }

  async function handleSessionSubmit(event) {
    event.preventDefault();
    if (!state.activeId || state.sessionSaving) return;
    const starts = new Date(els.sessionStarts.value);
    if (Number.isNaN(starts.getTime())) {
      els.sessionError.textContent = 'Choose a valid date and time.';
      return;
    }
    const payload = {
      startsAt: starts.toISOString(),
      durationMins: Number(els.sessionDuration.value),
      format: els.sessionFormat.value,
      location: els.sessionLocation.value.trim(),
      note: els.sessionNote.value.trim()
    };
    const mode = state.sessionMode;
    state.sessionSaving = true;
    els.sessionSubmit.disabled = true;
    els.sessionSubmit.textContent = 'Saving...';
    els.sessionError.textContent = '';
    try {
      let data;
      if (mode === 'reschedule' && state.sessionEditingId) {
        data = await auth.updateSession(state.sessionEditingId, {
          action: 'reschedule',
          ...payload
        });
      } else {
        data = await auth.createSession({
          conversationId: state.activeId,
          ...payload
        });
      }
      if (state.active) state.active.latestSession = data.session;
      closeSessionDialog();
      await refreshActiveConversation();
      showToast(
        mode === 'reschedule'
          ? 'Session rescheduled.'
          : 'Session proposal sent.'
      );
    } catch (error) {
      els.sessionError.textContent = errorMessage(
        error,
        'Could not save the session proposal.'
      );
    } finally {
      state.sessionSaving = false;
      els.sessionSubmit.disabled = false;
      els.sessionSubmit.textContent = mode === 'reschedule'
        ? 'Update proposal'
        : 'Send proposal';
    }
  }

  async function handleSessionAction(button) {
    const action = button.dataset.sessionAction;
    const sessionId = button.dataset.sessionId;
    if (!action || !sessionId) return;
    if (action === 'reschedule') {
      const session = state.active && state.active.latestSession;
      openSessionDialog('reschedule', session);
      return;
    }
    if (action === 'cancel' && !global.confirm('Cancel this session?')) return;
    if (action === 'complete' && !global.confirm('Mark this session as complete?')) {
      return;
    }
    const original = button.textContent;
    button.disabled = true;
    button.textContent = action === 'accept'
      ? 'Accepting...'
      : action === 'decline'
        ? 'Declining...'
        : action === 'complete' ? 'Completing...' : 'Cancelling...';
    try {
      const data = await auth.updateSession(sessionId, { action });
      if (state.active) state.active.latestSession = data.session;
      await refreshActiveConversation();
      showToast(
        action === 'accept'
          ? 'Session accepted.'
          : action === 'decline'
            ? 'Session declined.'
            : action === 'complete'
              ? 'Session marked complete.'
              : 'Session cancelled.'
      );
    } catch (error) {
      button.disabled = false;
      button.textContent = original;
      showToast(errorMessage(error, 'Could not update the session.'));
    }
  }

  async function handleBlockToggle() {
    if (!state.active) return;
    const other = activeOtherUser();
    if (!other) return;
    if (state.active.blockedByMe) {
      if (!global.confirm('Unblock ' + (other.name || 'this person') + '?')) return;
      try {
        await auth.unblockUser(other.id);
        showToast('Unblocked. Shared conversations are open again.');
        global.dispatchEvent(new CustomEvent('tutormatch:blocks-changed'));
      } catch (error) {
        showToast(errorMessage(error, 'Could not unblock this person.'));
      }
      return;
    }
    if (state.active.blockedByOther) return;
    if (!global.confirm(
      'Block ' + (other.name || 'this person') +
      '? They will disappear from search and this chat becomes read-only.'
    )) {
      return;
    }
    try {
      await auth.blockUser(other.id);
      showToast('Blocked. This conversation is now read-only.');
      global.dispatchEvent(new CustomEvent('tutormatch:blocks-changed'));
    } catch (error) {
      showToast(errorMessage(error, 'Could not block this person.'));
    }
  }

  async function handleReportSubmit(event) {
    event.preventDefault();
    if (!state.activeId || !state.reportUserId || state.reportSaving) return;
    state.reportSaving = true;
    els.reportSubmit.disabled = true;
    els.reportSubmit.textContent = 'Submitting...';
    els.reportError.textContent = '';
    try {
      await auth.reportUser({
        reportedUserId: state.reportUserId,
        reason: els.reportReason.value,
        details: els.reportDetails.value.trim(),
        conversationId: state.activeId
      });
      const alsoBlock = els.reportAlsoBlock.checked;
      if (alsoBlock) {
        await auth.blockUser(state.reportUserId);
        global.dispatchEvent(new CustomEvent('tutormatch:blocks-changed'));
      }
      const name = (activeOtherUser() || {}).name || 'this person';
      closeReportDialog();
      showToast(
        alsoBlock
          ? 'Report submitted and ' + name + ' was blocked.'
          : 'Report submitted. Thank you for helping keep TutorMatch safe.'
      );
    } catch (error) {
      els.reportError.textContent = errorMessage(
        error,
        'Could not submit the report.'
      );
    } finally {
      state.reportSaving = false;
      els.reportSubmit.disabled = false;
      els.reportSubmit.textContent = 'Submit report';
    }
  }

  async function refreshAll(options = {}) {
    if (!els) return;
    const silent = Boolean(options.silent);
    if (!silent) {
      state.loading = true;
      state.error = '';
      render();
    }

    try {
      const results = await Promise.all([
        auth.getRequests({ box: 'incoming', limit: 50 }),
        auth.getRequests({ box: 'outgoing', limit: 50 }),
        auth.getConversations({ limit: 50 })
      ]);
      state.incoming = results[0].requests || [];
      state.outgoing = results[1].requests || [];
      state.conversations = results[2].conversations || [];
      state.loaded = true;
      state.error = '';
      state.loading = false;

      if (state.activeId && !state.conversations.some(
        (item) => String(item.id) === String(state.activeId)
      )) {
        state.activeId = null;
        state.active = null;
        state.messages = [];
      }

      // Keep Search's request buttons in sync with the server.
      auth.loadSentRequests().catch(() => {});
      render();
      refreshBadge();
    } catch (error) {
      state.loading = false;
      state.error = error.message || 'Could not load messages.';
      render();
    }
  }

  async function openConversation(id) {
    if (!id) return;
    state.tab = 'conversations';
    state.activeId = id;
    state.active = state.conversations.find(
      (item) => String(item.id) === String(id)
    ) || null;
    state.messages = [];
    state.messagesLoading = true;
    render();

    try {
      const results = await Promise.all([
        auth.getConversation(id),
        auth.getMessages(id, { limit: 50 })
      ]);
      state.active = results[0].conversation;
      state.messages = results[1].messages || [];
      state.messagesLoading = false;
      render();
      scrollChatToBottom();

      const last = state.messages[state.messages.length - 1];
      if (last) {
        await auth.markConversationRead(id, last.id).catch(() => {});
      }
      const conversation = state.conversations.find(
        (item) => String(item.id) === String(id)
      );
      if (conversation) conversation.unreadCount = 0;
      render();
      refreshBadge();
    } catch (error) {
      state.messagesLoading = false;
      state.error = error.message || 'Could not open the conversation.';
      render();
      showToast(state.error);
    }
  }

  async function handleRequestAction(button) {
    const requestId = button.dataset.requestId;
    const action = button.dataset.requestAction;
    if (!requestId || !action) return;
    const original = button.textContent;
    button.disabled = true;
    button.textContent = action === 'accept'
      ? 'Accepting...'
      : action === 'decline' ? 'Declining...' : 'Cancelling...';

    try {
      const data = await auth.updateRequest(requestId, action);
      await refreshAll({ silent: true });
      if (action === 'accept' && data.conversationId) {
        await openConversation(data.conversationId);
      }
      showToast(
        action === 'accept'
          ? 'Request accepted. Chat is now open.'
          : action === 'decline'
            ? 'Request declined.'
            : 'Request cancelled.'
      );
    } catch (error) {
      button.disabled = false;
      button.textContent = original;
      showToast(error.message || 'Could not update the request.');
    }
  }

  async function handleSend(event) {
    event.preventDefault();
    if (!state.activeId || state.sending) return;
    const body = els.chatInput.value.trim();
    if (!body) return;

    state.sending = true;
    renderChat();
    try {
      const data = await auth.sendMessage(state.activeId, body);
      state.messages.push(data.message);
      els.chatInput.value = '';
      state.sending = false;
      renderChat();
      scrollChatToBottom();

      const conversation = state.conversations.find(
        (item) => String(item.id) === String(state.activeId)
      );
      if (conversation) {
        conversation.lastMessage = {
          preview: body.length > 90 ? body.slice(0, 87) + '...' : body,
          createdAt: data.message.createdAt,
          senderId: data.message.senderId,
          type: data.message.type
        };
        conversation.lastMessageAt = data.message.createdAt;
      }
      renderList();
      refreshBadge();
    } catch (error) {
      state.sending = false;
      renderChat();
      showToast(error.message || 'Could not send the message.');
    }
  }

  function bind() {
    els.tabs.addEventListener('click', (event) => {
      const tab = event.target.closest('[data-messages-tab]');
      if (!tab) return;
      state.tab = tab.dataset.messagesTab;
      render();
    });

    els.list.addEventListener('click', (event) => {
      const retry = event.target.closest('[data-messages-retry]');
      if (retry) {
        refreshAll();
        return;
      }
      const action = event.target.closest('[data-request-action]');
      if (action) {
        handleRequestAction(action);
        return;
      }
      const open = event.target.closest('[data-open-conversation]');
      if (open) {
        openConversation(open.dataset.openConversation);
      }
    });

    if (els.chatForm) {
      els.chatForm.addEventListener('submit', handleSend);
    }
    if (els.sessionCard) {
      els.sessionCard.addEventListener('click', (event) => {
        const action = event.target.closest('[data-session-action]');
        if (action) handleSessionAction(action);
      });
    }
    if (els.chatPropose) {
      els.chatPropose.addEventListener('click', () => openSessionDialog('propose'));
    }
    if (els.chatReport) {
      els.chatReport.addEventListener('click', openReportDialog);
    }
    if (els.chatBlock) {
      els.chatBlock.addEventListener('click', handleBlockToggle);
    }
    if (els.sessionForm) {
      els.sessionForm.addEventListener('submit', handleSessionSubmit);
    }
    if (els.reportForm) {
      els.reportForm.addEventListener('submit', handleReportSubmit);
    }
    if (els.sessionDialog) {
      els.sessionDialog.addEventListener('click', (event) => {
        if (event.target.closest('[data-close-session]')) closeSessionDialog();
      });
    }
    if (els.reportDialog) {
      els.reportDialog.addEventListener('click', (event) => {
        if (event.target.closest('[data-close-report]')) closeReportDialog();
      });
    }
    if (els.refresh) {
      els.refresh.addEventListener('click', () => refreshAll());
    }

    global.addEventListener('tutormatch:request-sent', () => {
      refreshAll({ silent: true });
    });

    global.addEventListener('tutormatch:request-updated', () => {
      refreshAll({ silent: true });
    });

    global.addEventListener('tutormatch:blocks-changed', () => {
      refreshAll({ silent: true }).then(() => {
        if (state.activeId) refreshActiveConversation();
      });
    });

    global.addEventListener('tutormatch:open-conversation', (event) => {
      const id = event.detail && event.detail.id;
      if (id) openConversation(id);
    });

    global.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape') return;
      if (els.sessionDialog && els.sessionDialog.dataset.open === 'true') {
        closeSessionDialog();
      }
      if (els.reportDialog && els.reportDialog.dataset.open === 'true') {
        closeReportDialog();
      }
    });

    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(() => {
      const section = document.getElementById('section-messages');
      if (!section || section.classList.contains('hidden') || document.hidden) return;
      refreshAll({ silent: true });
      if (state.activeId) refreshActiveConversation();
    }, POLL_MS);
  }

  function init() {
    if (initialized) return;
    els = {
      tabs: document.querySelector('.messages-tabs'),
      list: document.getElementById('messages-list'),
      incomingCount: document.getElementById('messages-incoming-count'),
      outgoingCount: document.getElementById('messages-outgoing-count'),
      conversationCount: document.getElementById('messages-conversation-count'),
      chatEmpty: document.getElementById('chat-empty'),
      chatThread: document.getElementById('chat-thread'),
      chatTitle: document.getElementById('chat-title'),
      chatSubtitle: document.getElementById('chat-subtitle'),
      chatStatus: document.getElementById('chat-status'),
      chatMessages: document.getElementById('chat-messages'),
      chatForm: document.getElementById('chat-form'),
      chatInput: document.getElementById('chat-input'),
      chatSend: document.getElementById('chat-send'),
      chatPropose: document.getElementById('chat-propose'),
      chatReport: document.getElementById('chat-report'),
      chatBlock: document.getElementById('chat-block'),
      sessionCard: document.getElementById('session-card'),
      chatNotice: document.getElementById('chat-notice'),
      sessionDialog: document.getElementById('session-dialog'),
      sessionDialogTitle: document.getElementById('session-dialog-title'),
      sessionForm: document.getElementById('session-form'),
      sessionStarts: document.getElementById('session-starts'),
      sessionDuration: document.getElementById('session-duration'),
      sessionFormat: document.getElementById('session-format'),
      sessionLocation: document.getElementById('session-location'),
      sessionNote: document.getElementById('session-note'),
      sessionError: document.getElementById('session-error'),
      sessionSubmit: document.getElementById('session-submit'),
      reportDialog: document.getElementById('report-dialog'),
      reportForm: document.getElementById('report-form'),
      reportReason: document.getElementById('report-reason'),
      reportDetails: document.getElementById('report-details'),
      reportAlsoBlock: document.getElementById('report-also-block'),
      reportError: document.getElementById('report-error'),
      reportSubmit: document.getElementById('report-submit'),
      refresh: document.getElementById('messages-refresh')
    };
    if (!els.tabs || !els.list || !els.chatMessages) return;
    initialized = true;
    bind();
    refreshAll();
  }

  global.TutorMatchMessages = {
    init,
    render,
    refresh: refreshAll
  };
})(window);
