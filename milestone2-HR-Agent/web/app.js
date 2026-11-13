// Miyo HR Portal — Modern Reactive SPA (Vue 3 + Tailwind CSS + Lucide Icons)
const { createApp, ref, computed, onMounted, nextTick } = Vue;

createApp({
  setup() {
    // --- APP & NAVIGATION STATE ---
    const isSidebarCollapsed = ref(false);
    const activeTab = ref('chat'); // 'chat' | 'my_requests' | 'approvals' | 'calendar' | 'monitoring'
    const isBackendReady = ref(false);
    const isDarkMode = ref(true);
    const showDevAudit = ref(localStorage.getItem('miyo_dev_audit') === 'true');

    function toggleTheme() {
      isDarkMode.value = !isDarkMode.value;
      if (isDarkMode.value) {
        document.documentElement.classList.add('dark');
      } else {
        document.documentElement.classList.remove('dark');
      }
      refreshIcons();
    }

    function toggleDevAudit() {
      showDevAudit.value = !showDevAudit.value;
      localStorage.setItem('miyo_dev_audit', showDevAudit.value);
      refreshIcons();
    }

    // --- LOGIN STATE ---
    const isLoginModalOpen = ref(false);
    const loginUsername = ref('');
    const loginPassword = ref('');
    const loginError = ref('');
    const isLoggingIn = ref(false);

    async function submitPasswordLogin() {
      isLoggingIn.value = true;
      loginError.value = '';
      try {
        const res = await fetch('/api/v1/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: loginUsername.value.trim(), password: loginPassword.value })
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: 'Kredensial tidak valid' }));
          throw new Error(err.detail || 'Login gagal');
        }
        const data = await res.json();
        const token = data.access_token;
        const profile = data.profile;
        
        let existing = personasCatalog.value.find(p => p.employee_id === profile.employee_id);
        if (!existing) {
          existing = {
            employee_id: profile.employee_id,
            label: `${profile.display_name} — ${profile.role}`,
            role: profile.role,
            demo_token: token
          };
          personasCatalog.value.push(existing);
        } else {
          existing.demo_token = token;
        }
        selectedPersonaId.value = profile.employee_id;
        isLoginModalOpen.value = false;
        loginUsername.value = '';
        loginPassword.value = '';
        switchPersona();
      } catch (err) {
        loginError.value = err.message;
      } finally {
        isLoggingIn.value = false;
      }
    }

    // --- PERSONAS & AUTH STATE ---
    const personasCatalog = ref([
      { employee_id: 'EMP-001', label: 'Alya Pratama — Pegawai', role: 'employee', demo_token: 'token-alya' },
      { employee_id: 'EMP-002', label: 'Bima Santoso — Pegawai', role: 'employee', demo_token: 'token-bima' },
      { employee_id: 'MGR-001', label: 'Raka Wijaya — Manajer', role: 'manager', demo_token: 'token-manager' },
      { employee_id: 'ADM-001', label: 'Monitoring Admin — Admin', role: 'monitoring_admin', demo_token: 'token-admin' },
    ]);
    const selectedPersonaId = ref('EMP-001');
    const activePersona = computed(() => {
      return personasCatalog.value.find(p => p.employee_id === selectedPersonaId.value) || personasCatalog.value[0];
    });

    const userInitials = computed(() => {
      const parts = activePersona.value.label.split('—')[0].trim().split(' ');
      return parts.map(p => p[0]).join('').slice(0, 2).toUpperCase();
    });

    const userRoleLabel = computed(() => {
      const r = activePersona.value.role;
      if (r === 'monitoring_admin') return 'Monitoring Admin';
      if (r === 'manager') return 'Engineering Manager';
      return 'Software Engineer';
    });

    const isAdmin = computed(() => activePersona.value.role === 'monitoring_admin');
    const isManager = computed(() => activePersona.value.role === 'manager' || isAdmin.value);

    const roleBadgeClass = computed(() => {
      const r = activePersona.value.role;
      if (r === 'monitoring_admin') return 'bg-purple-500/20 text-purple-400 border border-purple-500/30';
      if (r === 'manager') return 'bg-blue-500/20 text-blue-400 border border-blue-500/30';
      return 'bg-brand-orange-subtle text-brand-orange border border-brand-orange/30';
    });

    const visibleTabs = computed(() => {
      const list = [
        { id: 'chat', label: 'Asisten Kebijakan', icon: 'bot-message-square' },
        { id: 'my_requests', label: 'Permintaan Cuti Saya', icon: 'file-text' },
      ];
      if (isManager.value) {
        list.push({ id: 'approvals', label: 'Persetujuan Manajer', icon: 'user-check' });
      }
      list.push({ id: 'calendar', label: 'Kalender Cuti Tim', icon: 'calendar-days' });
      if (isAdmin.value) {
        list.push({ id: 'monitoring', label: 'Monitoring Telemetri', icon: 'activity' });
      }
      return list;
    });

    const currentTabTitle = computed(() => {
      const t = visibleTabs.value.find(tab => tab.id === activeTab.value);
      return t ? t.label : 'Asisten Kebijakan';
    });

    // Date formatting
    const currentDate = new Date('2026-11-12T00:00:00');
    const currentDateFormatted = computed(() => {
      return currentDate.toLocaleDateString('id-ID', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
    });

    // --- LEAVE BALANCES ---
    const myBalances = ref([]);
    const annualBalanceDays = computed(() => {
      const b = myBalances.value.find(item => item.leave_type === 'annual');
      return b ? b.available_days : 8;
    });

    // --- CHAT STATE ---
    const chatContainer = ref(null);
    const chatMessages = ref([]);
    const userInputText = ref('');
    const isGenerating = ref(false);
    const isConfirming = ref(false);
    const confirmedProposals = ref(new Set());
    const proposalAttachments = ref({});

    const quickQueries = computed(() => {
      const base = [
        'Berapa sisa saldo cuti saya saat ini?',
        'Apa syarat cuti sakit lebih dari 2 hari?',
        'Berapa jatah cuti tahunan dan syarat pengajuannya?',
        'Berapa hari boleh Work From Home (WFH) per minggu?',
      ];
      if (isManager.value) {
        return [
          'Bagaimana tren analitik dan pengajuan cuti tim saya saat ini?',
          'Berapa sisa saldo cuti saya saat ini?',
          'Siapa anggota tim yang saldo cutinya paling rendah?',
          'Berapa hari boleh Work From Home (WFH) per minggu?'
        ];
      }
      return base;
    });

    // --- VOICE RECORDING STATE ---
    const isRecording = ref(false);
    let mediaRecorder = null;
    let audioChunks = [];

    // --- MODAL & LEAVE FORM STATE ---
    const isLeaveModalOpen = ref(false);
    const formLeaveType = ref('annual');
    const formStartDate = ref('2026-11-18');
    const formEndDate = ref('2026-11-18');
    const formMinStartDate = ref('2026-11-18');
    const formWorkingDays = ref(1);
    const formReason = ref('');
    const formAttachment = ref(null);

    // --- REJECT MODAL STATE ---
    const isRejectModalOpen = ref(false);
    const targetRejectRequestId = ref(null);
    const rejectReason = ref('');

    // --- MY REQUESTS & APPROVALS DATA ---
    const myRequests = ref([]);
    const teamRequests = ref([]);
    const monitoringSummary = ref({});
    const monitoringAlerts = ref([]);

    // --- API HELPER ---
    async function apiCall(endpoint, options = {}) {
      const token = activePersona.value.demo_token;
      const headers = {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
        ...(options.headers || {})
      };
      try {
        const resp = await fetch(endpoint, { ...options, headers });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({ detail: resp.statusText }));
          throw new Error(err.detail || `HTTP Error ${resp.status}`);
        }
        return await resp.json();
      } catch (e) {
        console.error(`API Call failed [${endpoint}]:`, e);
        throw e;
      }
    }

    // --- SYSTEM HEALTH CHECK ---
    async function checkHealth() {
      try {
        const res = await fetch('/readyz');
        isBackendReady.value = res.ok;
      } catch {
        isBackendReady.value = false;
      }
    }

    // --- PERSONA SWITCHER ---
    function switchPersona() {
      chatMessages.value = [];
      confirmedProposals.value = new Set();
      proposalAttachments.value = {};
      activeTab.value = 'chat';
      fetchMyRequests();
      if (isManager.value) fetchTeamRequests();
      if (isAdmin.value) fetchMonitoringData();
      refreshIcons();
    }

    // --- CHAT FUNCTIONS ---
    function renderMarkdown(content) {
      if (!content) return '';
      return marked.parse(content);
    }

    function getProposals(msg) {
      if (msg.action_proposals && msg.action_proposals.length > 0) return msg.action_proposals;
      if (msg.action_proposal) return [msg.action_proposal];
      return [];
    }

    function scrollChatToBottom() {
      nextTick(() => {
        if (chatContainer.value) {
          chatContainer.value.scrollTop = chatContainer.value.scrollHeight;
        }
        refreshIcons();
      });
    }

    async function sendChatMessage() {
      const text = userInputText.value.trim();
      if (!text || isGenerating.value) return;

      chatMessages.value.push({ role: 'user', content: text });
      userInputText.value = '';
      isGenerating.value = true;
      scrollChatToBottom();

      try {
        // Send history context
        const historyPayload = chatMessages.value.slice(0, -1).slice(-6).map(m => ({
          role: m.role,
          content: m.content
        }));

        const result = await apiCall('/api/v1/chat', {
          method: 'POST',
          body: JSON.stringify({ message: text, history: historyPayload })
        });

        chatMessages.value.push({
          role: 'assistant',
          content: result.answer,
          citations: result.citations || [],
          showCitations: false,
          action_proposal: result.action_proposal,
          action_proposals: result.action_proposals || [],
          trace_id: result.trace_id,
          usage: result.usage || {}
        });
      } catch (err) {
        chatMessages.value.push({
          role: 'assistant',
          content: `Maaf, terjadi kendala komunikasi dengan server: ${err.message}`,
          citations: []
        });
      } finally {
        isGenerating.value = false;
        scrollChatToBottom();
      }
    }

    function sendQuickPrompt(prompt) {
      userInputText.value = prompt;
      sendChatMessage();
    }

    function clearChat() {
      chatMessages.value = [];
      confirmedProposals.value = new Set();
      proposalAttachments.value = {};
      refreshIcons();
    }

    // --- PROPOSAL CONFIRMATION ---
    async function confirmProposal(proposalId) {
      isConfirming.value = true;
      const idempotencyKey = `idem_${proposalId}_${Date.now()}`;
      try {
        const res = await apiCall(`/api/v1/action-proposals/${proposalId}/confirm`, {
          method: 'POST',
          body: JSON.stringify({ idempotency_key: idempotencyKey })
        });

        confirmedProposals.value.add(proposalId);
        
        // Upload attachment if any
        const att = proposalAttachments.value[proposalId] || formAttachment.value;
        if (att && res.request_id) {
          await apiCall(`/api/v1/leave-requests/${res.request_id}/attachment`, {
            method: 'POST',
            body: JSON.stringify(att)
          }).catch(console.error);
        }

        // Notify user in chat
        chatMessages.value.push({
          role: 'assistant',
          content: `Permohonan cuti **#${res.request_id}** telah berhasil diajukan dengan status \`${res.status}\`. Manajer Anda akan segera meninjau permohonan ini.`
        });
        fetchMyRequests();
      } catch (err) {
        alert(`Gagal mengonfirmasi proposal: ${err.message}`);
      } finally {
        isConfirming.value = false;
        scrollChatToBottom();
      }
    }

    function handleProposalAttachment(event, proposalId) {
      const file = event.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (e) => {
        const b64 = e.target.result.split(',')[1];
        proposalAttachments.value[proposalId] = {
          filename: file.name,
          content_type: file.type || 'application/pdf',
          content_base64: b64
        };
      };
      reader.readAsDataURL(file);
    }

    // --- LEAVE FORM LOGIC ---
    function calculateWorkingDays(startStr, endStr) {
      if (!startStr || !endStr) return 0;
      let start = new Date(startStr);
      const end = new Date(endStr);
      if (start > end) return 0;
      let count = 0;
      let cur = new Date(start);
      while (cur <= end) {
        const day = cur.getDay();
        if (day !== 0 && day !== 6) count++; // Not Saturday (6) or Sunday (0)
        cur.setDate(cur.getDate() + 1);
      }
      return count;
    }

    function calculateMinStartDate(leaveType) {
      const today = new Date('2026-11-12T00:00:00');
      if (leaveType !== 'annual') {
        return today.toISOString().split('T')[0];
      }
      // Annual leave requires min 3 business days notice
      let candidate = new Date(today);
      candidate.setDate(candidate.getDate() + 1);
      while (true) {
        // Count business days strictly between today and candidate
        let leadWorkdays = 0;
        let c = new Date(today);
        c.setDate(c.getDate() + 1);
        while (c < candidate) {
          if (c.getDay() !== 0 && c.getDay() !== 6) leadWorkdays++;
          c.setDate(c.getDate() + 1);
        }
        if (leadWorkdays >= 3 && candidate.getDay() !== 0 && candidate.getDay() !== 6) {
          return candidate.toISOString().split('T')[0];
        }
        candidate.setDate(candidate.getDate() + 1);
      }
    }

    function openLeaveModal() {
      formLeaveType.value = 'annual';
      const minDate = calculateMinStartDate('annual');
      formMinStartDate.value = minDate;
      formStartDate.value = minDate;
      formEndDate.value = minDate;
      formWorkingDays.value = 1;
      formReason.value = '';
      formAttachment.value = null;
      isLeaveModalOpen.value = true;
      refreshIcons();
    }

    function onLeaveTypeChange() {
      const minDate = calculateMinStartDate(formLeaveType.value);
      formMinStartDate.value = minDate;
      if (formStartDate.value < minDate) {
        formStartDate.value = minDate;
      }
      recalculateDuration();
    }

    function recalculateDuration() {
      if (formEndDate.value < formStartDate.value) {
        formEndDate.value = formStartDate.value;
      }
      formWorkingDays.value = calculateWorkingDays(formStartDate.value, formEndDate.value);
    }

    function handleFormAttachment(event) {
      const file = event.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (e) => {
        const b64 = e.target.result.split(',')[1];
        formAttachment.value = {
          filename: file.name,
          content_type: file.type || 'application/pdf',
          content_base64: b64
        };
      };
      reader.readAsDataURL(file);
    }

    function submitLeaveForm() {
      if (formWorkingDays.value === 0) return;
      
      const typeLabels = { annual: 'Cuti Tahunan', sick: 'Cuti Sakit', parental: 'Cuti Orang Tua' };
      const label = typeLabels[formLeaveType.value] || formLeaveType.value;
      const reasonPart = formReason.value.trim() ? ` dengan alasan: ${formReason.value.trim()}` : '';
      const prompt = `Siapkan ${label.toLowerCase()} (${formLeaveType.value}) dari ${formStartDate.value} sampai ${formEndDate.value}${reasonPart}`;

      isLeaveModalOpen.value = false;
      activeTab.value = 'chat';
      userInputText.value = prompt;
      sendChatMessage();
    }

    // --- VOICE RECORDING VIA MEDIARECORDER ---
    async function toggleVoiceRecording() {
      if (isRecording.value) {
        // Stop recording
        if (mediaRecorder && mediaRecorder.state !== 'inactive') {
          mediaRecorder.stop();
        }
        isRecording.value = false;
        return;
      }

      // Start recording
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioChunks = [];
        const mimeType = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/wav';
        mediaRecorder = new MediaRecorder(stream, { credentials: mimeType });

        mediaRecorder.ondataavailable = (e) => {
          if (e.data.size > 0) audioChunks.push(e.data);
        };

        mediaRecorder.onstop = async () => {
          stream.getTracks().forEach(t => t.stop());
          const audioBlob = new Blob(audioChunks, { type: mimeType });
          const reader = new FileReader();
          reader.onload = async () => {
            const b64 = reader.result.split(',')[1];
            try {
              const res = await apiCall('/api/v1/audio/transcribe', {
                method: 'POST',
                body: JSON.stringify({
                  audio_base64: b64,
                  filename: `voice_query.${mimeType.includes('webm') ? 'webm' : 'wav'}`,
                  language: 'id'
                })
              });
              if (res.text) {
                userInputText.value = res.text;
                sendChatMessage();
              } else {
                alert('Tidak ada suara terdeteksi.');
              }
            } catch (err) {
              alert(`Gagal menerjemahkan suara: ${err.message}`);
            }
          };
          reader.readAsDataURL(audioBlob);
        };

        mediaRecorder.start();
        isRecording.value = true;
        refreshIcons();
      } catch (err) {
        alert('Akses mikrofon tidak diizinkan atau tidak tersedia: ' + err.message);
      }
    }

    // --- MY REQUESTS FETCH ---
    async function fetchMyRequests() {
      try {
        const res = await apiCall('/api/v1/leave-requests/me');
        myRequests.value = res || [];
      } catch (err) {
        console.error('Fetch my requests error:', err);
      }
    }

    async function cancelRequest(requestId) {
      if (!confirm(`Batalkan permohonan cuti #${requestId}?`)) return;
      try {
        await apiCall(`/api/v1/leave-requests/${requestId}/cancel`, { method: 'POST' });
        fetchMyRequests();
      } catch (err) {
        alert('Gagal membatalkan cuti: ' + err.message);
      }
    }

    // --- MANAGER APPROVALS FETCH & ACTIONS ---
    async function fetchTeamRequests() {
      if (!isManager.value) return;
      try {
        const res = await apiCall('/api/v1/leave-requests/team');
        teamRequests.value = res || [];
      } catch (err) {
        console.error('Fetch team requests error:', err);
      }
    }

    async function reviewRequest(requestId, decision, reason = '') {
      try {
        await apiCall(`/api/v1/leave-requests/${requestId}/review`, {
          method: 'POST',
          body: JSON.stringify({ decision, rejection_reason: reason || undefined })
        });
        fetchTeamRequests();
        fetchMyRequests();
      } catch (err) {
        alert('Gagal memproses review: ' + err.message);
      }
    }

    function openRejectModal(requestId) {
      targetRejectRequestId.value = requestId;
      rejectReason.value = '';
      isRejectModalOpen.value = true;
    }

    function confirmRejectRequest() {
      if (!targetRejectRequestId.value) return;
      reviewRequest(targetRejectRequestId.value, 'reject', rejectReason.value);
      isRejectModalOpen.value = false;
    }

    // --- MONITORING DATA FETCH ---
    async function fetchMonitoringData() {
      if (!isAdmin.value) return;
      try {
        const [sum, alerts] = await Promise.all([
          apiCall('/api/v1/monitoring/summary'),
          apiCall('/api/v1/monitoring/alerts')
        ]);
        monitoringSummary.value = sum || {};
        monitoringAlerts.value = alerts || [];
      } catch (err) {
        console.error('Fetch monitoring data error:', err);
      }
    }

    // --- CALENDAR DAYS COMPUTATION ---
    const calendarDays = computed(() => {
      // Generate days for November 2026
      const days = [];
      const totalDays = 30;
      const startDayOfWeek = 0; // Nov 1, 2026 is Sunday (0)
      
      // Pad empty days at start (Mon = 0, Sun = 6)
      const offset = (startDayOfWeek === 0) ? 6 : startDayOfWeek - 1;
      for (let i = 0; i < offset; i++) {
        days.push({ dayNum: '', dateStr: `pad-${i}`, isToday: false, isWeekend: false, events: [] });
      }

      for (let d = 1; d <= totalDays; d++) {
        const dStr = `2026-11-${String(d).padStart(2, '0')}`;
        const dateObj = new Date(dStr);
        const dayOfWeek = dateObj.getDay();
        const isWeekend = (dayOfWeek === 0 || dayOfWeek === 6);
        const isToday = (d === 12); // Today is 12 Nov

        const events = [];
        if (d === 10) events.push({ text: 'Alya: Cuti Tahunan', class: 'bg-brand-orange-subtle text-brand-orange border border-brand-orange/30' });
        if (d === 13) events.push({ text: 'Alya: Cuti Sakit', class: 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' });
        if (d === 18) events.push({ text: 'Alya: Cuti Tahunan', class: 'bg-brand-orange-subtle text-brand-orange border border-brand-orange/30' });

        days.push({ dayNum: d, dateStr: dStr, isToday, isWeekend, events });
      }
      return days;
    });

    // Helper status badge formatters
    function formatStatus(st) {
      const map = {
        pending_manager_review: 'Menunggu Manajer',
        approved: 'Disetujui',
        rejected: 'Ditolak',
        cancelled: 'Dibatalkan'
      };
      return map[st] || st;
    }

    function statusBadgeClass(st) {
      if (st === 'approved') return 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30';
      if (st === 'rejected') return 'bg-rose-500/20 text-rose-400 border border-rose-500/30';
      if (st === 'cancelled') return 'bg-brand-border text-brand-muted border border-brand-border';
      return 'bg-amber-500/20 text-amber-400 border border-amber-500/30';
    }

    function refreshIcons() {
      nextTick(() => {
        if (window.lucide) {
          window.lucide.createIcons();
        }
      });
    }

    onMounted(() => {
      checkHealth();
      setInterval(checkHealth, 15000);
      fetchMyRequests();
      refreshIcons();
    });

    return {
      isSidebarCollapsed,
      activeTab,
      isBackendReady,
      isDarkMode,
      toggleTheme,
      showDevAudit,
      toggleDevAudit,
      isLoginModalOpen,
      loginUsername,
      loginPassword,
      loginError,
      isLoggingIn,
      submitPasswordLogin,
      personasCatalog,
      selectedPersonaId,
      activePersona,
      userInitials,
      userRoleLabel,
      isAdmin,
      isManager,
      roleBadgeClass,
      visibleTabs,
      currentTabTitle,
      currentDateFormatted,
      myBalances,
      annualBalanceDays,
      chatContainer,
      chatMessages,
      userInputText,
      isGenerating,
      isConfirming,
      confirmedProposals,
      proposalAttachments,
      quickQueries,
      renderMarkdown,
      getProposals,
      sendChatMessage,
      sendQuickPrompt,
      clearChat,
      confirmProposal,
      handleProposalAttachment,
      isRecording,
      toggleVoiceRecording,
      isLeaveModalOpen,
      formLeaveType,
      formStartDate,
      formEndDate,
      formMinStartDate,
      formWorkingDays,
      formReason,
      formAttachment,
      openLeaveModal,
      onLeaveTypeChange,
      recalculateDuration,
      handleFormAttachment,
      submitLeaveForm,
      isRejectModalOpen,
      rejectReason,
      openRejectModal,
      confirmRejectRequest,
      myRequests,
      teamRequests,
      monitoringSummary,
      monitoringAlerts,
      calendarDays,
      switchPersona,
      fetchMyRequests,
      cancelRequest,
      fetchTeamRequests,
      reviewRequest,
      fetchMonitoringData,
      formatStatus,
      statusBadgeClass
    };
  }
}).mount('#app');
