// Miyo HR Portal — Industrial-Grade Reactive SPA (Vue 3 + Tailwind CSS + Lucide Icons)
const { createApp, ref, computed, onMounted, nextTick, watch } = Vue;

// Dynamic API Base with localStorage persistence and Smart Fallback for GitHub Pages & Localhost
function computeDefaultApiBase() {
  const saved = localStorage.getItem('miyo_api_base');
  if (saved && saved.trim()) {
    const cleanSaved = saved.trim().replace(/\/+$/, '');
    if (cleanSaved === 'https://hr-agent-assistant.vercel.app') {
      localStorage.removeItem('miyo_api_base');
    } else {
      return cleanSaved;
    }
  }
  if (window.location.hostname.endsWith('github.io')) {
    return 'https://aien-rmt-002-bayu-aziz.vercel.app';
  }
  if (window.location.protocol === 'file:' || (window.location.port && window.location.port !== '8000')) {
    return 'http://localhost:8000';
  }
  return '';
}

createApp({
  setup() {
    // --- BACKEND API CONFIGURATION STATE ---
    const apiBaseUrl = ref(computeDefaultApiBase());
    const showSettingsModal = ref(false);
    const showApiSettingsModal = showSettingsModal; // Backward compatibility alias
    const tempApiUrl = ref(apiBaseUrl.value);
    const isTestingConnection = ref(false);
    const connectionTestResult = ref(null);
    const isSettingsMenuOpen = ref(false);

    function getApiBase() {
      return (apiBaseUrl.value || '').trim().replace(/\/+$/, '');
    }

    function openSettingsModal() {
      tempApiUrl.value = apiBaseUrl.value;
      connectionTestResult.value = null;
      showSettingsModal.value = true;
      refreshIcons();
    }

    function closeSettingsModal() {
      showSettingsModal.value = false;
      isSettingsMenuOpen.value = false;
    }

    const openApiSettingsModal = openSettingsModal;

    function toggleSettingsMenu() {
      openSettingsModal();
    }

    function closeSettingsMenu() {
      closeSettingsModal();
    }

    async function testBackendConnection() {
      isTestingConnection.value = true;
      connectionTestResult.value = null;
      const targetUrl = (tempApiUrl.value || '').trim().replace(/\/+$/, '');
      try {
        const resp = await fetch(`${targetUrl}/readyz`, { method: 'GET', headers: { 'Accept': 'application/json' } });
        if (resp.ok) {
          const data = await resp.json();
          connectionTestResult.value = {
            success: true,
            message: `Koneksi Berhasil! Status: ${data.status || 'ready'} (Database: ${data.dependencies?.database ? 'Online' : 'Degraded'})`
          };
        } else {
          connectionTestResult.value = {
            success: false,
            message: `Server merespon HTTP ${resp.status} ${resp.statusText}`
          };
        }
      } catch (err) {
        connectionTestResult.value = {
          success: false,
          message: `Gagal terhubung: ${err.message || 'Network / CORS Error'}`
        };
      } finally {
        isTestingConnection.value = false;
        refreshIcons();
      }
    }

    function saveApiSettings() {
      const cleanUrl = (tempApiUrl.value || '').trim().replace(/\/+$/, '');
      apiBaseUrl.value = cleanUrl;
      localStorage.setItem('miyo_api_base', cleanUrl);
      showApiSettingsModal.value = false;
      notify('Alamat URL Backend berhasil disimpan!', 'success');
      checkHealth();
      fetchSystemInit();
      refreshIcons();
    }

    function resetApiSettings() {
      localStorage.removeItem('miyo_api_base');
      apiBaseUrl.value = computeDefaultApiBase();
      tempApiUrl.value = apiBaseUrl.value;
      connectionTestResult.value = null;
      notify('URL Backend di-reset ke nilai bawaan.', 'info');
      checkHealth();
      fetchSystemInit();
      refreshIcons();
    }

    // --- APP & NAVIGATION STATE ---
    const isAuthenticated = ref(false);
    const isSidebarCollapsed = ref(false);
    const isMobileSidebarOpen = ref(false);
    const showSidebarExpanded = computed(() => isMobileSidebarOpen.value || !isSidebarCollapsed.value);
    const activeTab = ref('chat'); // 'chat' | 'my_requests' | 'approvals' | 'calendar' | 'monitoring'

    function openMobileSidebar() {
      isMobileSidebarOpen.value = true;
      refreshIcons();
    }

    function closeMobileSidebar() {
      isMobileSidebarOpen.value = false;
      refreshIcons();
    }

    function selectTab(tabId) {
      activeTab.value = tabId;
      isMobileSidebarOpen.value = false;
      refreshIcons();
    }
    const isBackendReady = ref(false);
    const isDarkMode = ref(true);
    const showDevAudit = ref(localStorage.getItem('miyo_dev_audit') === 'true');

    // Notification Toast State
    const toast = ref({ show: false, message: '', type: 'info' });
    let toastTimer = null;

    function notify(message, type = 'info') {
      toast.value = { show: true, message, type };
      if (toastTimer) clearTimeout(toastTimer);
      toastTimer = setTimeout(() => {
        toast.value.show = false;
      }, 4500);
      refreshIcons();
    }

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

    // --- LOCAL DATE FORMATTER (NO UTC SHIFT) ---
    function formatLocalDate(dateObj) {
      const y = dateObj.getFullYear();
      const m = String(dateObj.getMonth() + 1).padStart(2, '0');
      const d = String(dateObj.getDate()).padStart(2, '0');
      return `${y}-${m}-${d}`;
    }

    // --- POLICY & SERVER DATE STATE (DYNAMIC FROM AUTHENTICATED BACKEND) ---
    let hasInitializedCalDate = false;
    const policyRules = ref({
      server_date: formatLocalDate(new Date()),
      annual_lead_days: 3,
      earliest_annual_start_date: '',
      sick_doc_threshold: 2
    });

    const currentDateFormatted = computed(() => {
      const d = new Date(`${policyRules.value.server_date}T00:00:00`);
      return d.toLocaleDateString('id-ID', {
        weekday: 'long',
        day: 'numeric',
        month: 'long',
        year: 'numeric'
      });
    });

    // --- DYNAMIC PERSONAS & AUTHENTICATION STATE ---
    const personasCatalog = ref([]);
    const isLoadingPersonas = ref(true);
    const activePersona = ref(null);
    const selectedPersonaId = ref('');

    // Step-Up / Password Login Modal State
    const isLoginModalOpen = ref(false);
    const pendingStepUpPersona = ref(null);
    const loginUsername = ref('');
    const loginPassword = ref('');
    const loginError = ref('');
    const isLoggingIn = ref(false);

    async function refreshPolicyRules() {
      if (!activePersona.value?.demo_token) return null;
      try {
        const rulesRes = await apiCall('/api/v1/policies/rules');
        if (rulesRes) {
          policyRules.value = {
            ...policyRules.value,
            ...rulesRes
          };
          warmPolicyCacheFromRules(rulesRes);
          if (!hasInitializedCalDate && rulesRes.server_date) {
            const d = new Date(`${rulesRes.server_date}T00:00:00`);
            if (!Number.isNaN(d.getTime())) {
              calYear.value = d.getFullYear();
              calMonth.value = d.getMonth() + 1;
              hasInitializedCalDate = true;
            }
          }
          if (isLeaveModalOpen.value) {
            const minDate = calculateMinStartDate(formLeaveType.value);
            formMinStartDate.value = minDate;
            if (formStartDate.value < minDate) {
              formStartDate.value = minDate;
            }
            recalculateDuration();
          }
        }
        return rulesRes;
      } catch (err) {
        console.error('Fetch policy rules error:', err);
        return null;
      }
    }

    async function fetchSystemInit() {
      isLoadingPersonas.value = true;
      try {
        const personasRes = await fetch(`${getApiBase()}/auth/personas`)
          .then(r => (r.ok ? r.json() : []))
          .catch(() => []);

        personasCatalog.value = (personasRes || []).map(p => ({
          ...p,
          label: `${p.display_name} — ${p.department || p.role}`
        }));

        // Validate and restore previous session token against authenticated endpoint
        const savedSession = sessionStorage.getItem('miyo_active_session');
        if (savedSession) {
          try {
            const parsed = JSON.parse(savedSession);
            if (parsed && parsed.demo_token) {
              const validateRes = await fetch(`${getApiBase()}/api/v1/leave-balances/me`, {
                headers: { 'Authorization': `Bearer ${parsed.demo_token}` }
              });
              if (validateRes.ok) {
                const balancesData = await validateRes.json().catch(() => []);
                activePersona.value = parsed;
                selectedPersonaId.value = parsed.employee_id;
                myBalances.value = Array.isArray(balancesData) ? balancesData : [];
                isAuthenticated.value = true;
                hasInitializedCalDate = false;
                await loadAuthenticatedWorkspace();
              } else {
                sessionStorage.removeItem('miyo_active_session');
              }
            } else {
              sessionStorage.removeItem('miyo_active_session');
            }
          } catch {
            sessionStorage.removeItem('miyo_active_session');
          }
        }
      } catch (err) {
        console.error('Failed to load initial system catalog:', err);
      } finally {
        isLoadingPersonas.value = false;
        refreshIcons();
      }
    }

    async function selectSsoPersona(persona) {
      if (persona.requires_password) {
        pendingStepUpPersona.value = persona;
        loginUsername.value = persona.username || persona.employee_id;
        loginPassword.value = '';
        loginError.value = '';
        isLoginModalOpen.value = true;
        refreshIcons();
        return;
      }
      try {
        const res = await fetch(`${getApiBase()}/auth/demo-session`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ employee_id: persona.employee_id })
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: 'Gagal memulai sesi demo' }));
          throw new Error(err.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        const profile = data.profile || {};
        const sessionPersona = {
          ...persona,
          ...profile,
          demo_token: data.access_token,
          label: persona.label || `${profile.display_name || persona.employee_id} — ${profile.department || profile.role || ''}`
        };
        await activateSession(sessionPersona);
        notify(`Sesi ${sessionPersona.display_name || sessionPersona.employee_id} aktif`, 'success');
      } catch (err) {
        notify(`Gagal masuk sesi SSO: ${err.message}`, 'error');
      }
    }

    async function onSidebarPersonaSwitch() {
      const target = personasCatalog.value.find(p => p.employee_id === selectedPersonaId.value);
      if (!target) return;
      if (target.requires_password && activePersona.value?.employee_id !== target.employee_id) {
        selectedPersonaId.value = activePersona.value ? activePersona.value.employee_id : '';
      }
      await selectSsoPersona(target);
    }

    async function activateSession(persona) {
      activePersona.value = persona;
      selectedPersonaId.value = persona.employee_id;
      isAuthenticated.value = true;
      isMobileSidebarOpen.value = false;
      hasInitializedCalDate = false;
      sessionStorage.setItem('miyo_active_session', JSON.stringify(persona));

      chatMessages.value = [];
      confirmedProposals.value = new Set();
      proposalAttachments.value = {};
      myBalances.value = [];
      myRequests.value = [];
      teamAnalytics.value = null;
      ticketsList.value = [];
      policyCache.value = {};
      activeTab.value = 'chat';

      await loadAuthenticatedWorkspace();
      refreshIcons();
    }

    function logoutSession() {
      isAuthenticated.value = false;
      isMobileSidebarOpen.value = false;
      activePersona.value = null;
      selectedPersonaId.value = '';
      chatMessages.value = [];
      confirmedProposals.value = new Set();
      proposalAttachments.value = {};
      myBalances.value = [];
      myRequests.value = [];
      teamAnalytics.value = null;
      ticketsList.value = [];
      policyCache.value = {};
      hasInitializedCalDate = false;
      sessionStorage.removeItem('miyo_active_session');
      fetchSystemInit();
      refreshIcons();
    }

    function openManualLoginModal() {
      pendingStepUpPersona.value = null;
      loginUsername.value = '';
      loginPassword.value = '';
      loginError.value = '';
      isLoginModalOpen.value = true;
      refreshIcons();
    }

    async function submitPasswordLogin() {
      isLoggingIn.value = true;
      loginError.value = '';
      try {
        const res = await fetch(`${getApiBase()}/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            username: loginUsername.value.trim(),
            password: loginPassword.value
          })
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: 'Kredensial tidak valid' }));
          throw new Error(err.detail || 'Autentikasi gagal');
        }
        const data = await res.json();
        const token = data.access_token;
        const profile = data.profile;

        const existing = personasCatalog.value.find(p => p.employee_id === profile.employee_id);
        const sessionPersona = {
          ...(existing || {}),
          employee_id: profile.employee_id,
          username: existing?.username || loginUsername.value.trim(),
          display_name: profile.display_name,
          role: profile.role,
          department: profile.department || existing?.department || '',
          label: `${profile.display_name} — ${profile.department || profile.role}`,
          requires_password: true,
          demo_token: token
        };
        if (!existing) {
          personasCatalog.value.push({
            employee_id: profile.employee_id,
            username: sessionPersona.username,
            display_name: profile.display_name,
            role: profile.role,
            department: sessionPersona.department,
            label: sessionPersona.label,
            requires_password: true
          });
        }

        isLoginModalOpen.value = false;
        pendingStepUpPersona.value = null;
        loginUsername.value = '';
        loginPassword.value = '';
        await activateSession(sessionPersona);
        notify(`Sesi ${profile.display_name} aktif`, 'success');
      } catch (err) {
        loginError.value = err.message;
      } finally {
        isLoggingIn.value = false;
        refreshIcons();
      }
    }

    // --- COMPUTED USER PROFILE HELPERS ---
    const userDisplayName = computed(() => {
      if (!activePersona.value) return '';
      return activePersona.value.display_name || activePersona.value.label.split('—')[0].trim();
    });

    const userInitials = computed(() => {
      if (!userDisplayName.value) return 'U';
      const parts = userDisplayName.value.split(' ').filter(Boolean);
      return parts.map(p => p[0]).join('').slice(0, 2).toUpperCase();
    });

    function getInitials(nameStr) {
      if (!nameStr) return 'U';
      return nameStr.trim().split(/\s+/).map(p => p[0]).join('').slice(0, 2).toUpperCase();
    }

    const userRoleLabel = computed(() => {
      if (!activePersona.value) return '';
      const r = activePersona.value.role;
      if (r === 'monitoring_admin') return 'Monitoring Admin';
      return activePersona.value.department || 'Staff';
    });

    const isAdmin = computed(() => activePersona.value?.role === 'monitoring_admin');

    const roleBadgeClass = computed(() => {
      const r = activePersona.value?.role;
      if (r === 'monitoring_admin') return 'bg-sky-500/15 text-sky-400 border border-sky-500/30';
      return 'bg-zinc-500/15 text-zinc-300 border border-zinc-500/30';
    });

    const visibleTabs = computed(() => {
      const list = [
        { id: 'chat', label: 'Tanya Miyo', icon: 'message-square' },
        { id: 'my_requests', label: 'Permohonan Cuti', icon: 'file-text' },
        { id: 'calendar', label: 'Kalender Cuti', icon: 'calendar' }
      ];
      list.push({
        id: 'tickets',
        label: 'Tickets',
        icon: 'inbox',
        badge: pendingTicketsCount.value > 0 ? pendingTicketsCount.value : null
      });
      if (isAdmin.value) {
        list.push({
          id: 'monitoring',
          label: 'Monitoring Sistem',
          icon: 'activity',
          badge: monitoringAlerts.value.length > 0 ? monitoringAlerts.value.length : null
        });
      }
      return list;
    });

    const currentTabTitle = computed(() => {
      const t = visibleTabs.value.find(tab => tab.id === activeTab.value);
      return t ? t.label : 'Asisten Kebijakan';
    });

    // --- LEAVE BALANCES (DYNAMIC FROM DB) ---
    const myBalances = ref([]);
    const annualBalanceDays = computed(() => {
      const b = myBalances.value.find(item => item.leave_type === 'annual');
      if (b) return b.available_days;
      if (activePersona.value?.balances?.annual !== undefined) {
        return activePersona.value.balances.annual;
      }
      return 0;
    });

    const sickBalanceDays = computed(() => {
      const b = myBalances.value.find(item => item.leave_type === 'sick');
      return b ? b.available_days : (activePersona.value?.balances?.sick ?? 0);
    });

    const parentalBalanceDays = computed(() => {
      const b = myBalances.value.find(item => item.leave_type === 'parental');
      return b ? b.available_days : (activePersona.value?.balances?.parental ?? 0);
    });

    async function fetchMyBalances() {
      if (!activePersona.value) return;
      try {
        const res = await apiCall('/api/v1/leave-balances/me');
        myBalances.value = res || [];
      } catch (err) {
        console.error('Fetch balances error:', err);
      }
    }

    // --- API HELPER ---
    async function apiCall(endpoint, options = {}) {
      const token = activePersona.value?.demo_token;
      if (!token) throw new Error('Sesi belum terautentikasi');
      const headers = {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
        ...(options.headers || {})
      };
      const url = endpoint.startsWith('http') ? endpoint : `${getApiBase()}${endpoint}`;
      const resp = await fetch(url, { ...options, headers });
      if (resp.status === 401) {
        sessionStorage.removeItem('miyo_active_session');
        isAuthenticated.value = false;
        activePersona.value = null;
        selectedPersonaId.value = '';
        throw new Error('Sesi telah berakhir atau tidak valid. Silakan masuk kembali.');
      }
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail || `HTTP Error ${resp.status}`);
      }
      return await resp.json();
    }

    async function checkHealth() {
      try {
        const res = await fetch(`${getApiBase()}/readyz`);
        if (res.ok) {
          const data = await res.json();
          isBackendReady.value = Boolean(data.ready);
        } else {
          isBackendReady.value = false;
        }
      } catch {
        isBackendReady.value = false;
      }
    }

    async function loadAuthenticatedWorkspace() {
      if (!isAuthenticated.value) return;
      await Promise.all([
        refreshPolicyRules(),
        fetchMyBalances(),
        fetchMyRequests(),
        fetchTickets(),
        isAdmin.value ? fetchAnalyticsOverview() : Promise.resolve(),
        isAdmin.value ? fetchMonitoringData() : Promise.resolve()
      ]);
      refreshIcons();
    }

    // --- CHAT STATE & FUNCTIONS ---
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
        `Apa syarat cuti sakit lebih dari ${policyRules.value.sick_doc_threshold} hari?`,
        'Berapa jatah cuti tahunan dan syarat pengajuannya?',
        'Berapa hari boleh Work From Home (WFH) per minggu?'
      ];
      if (isAdmin.value) {
        return [
          'Ringkas distribusi kategori tiket & tren agregat cuti perusahaan',
          'Bagaimana status operasional & tingkat error layanan AI saat ini?',
          'Berapa jatah cuti tahunan dan syarat pengajuannya?',
          'Berapa hari boleh Work From Home (WFH) per minggu?'
        ];
      }
      return base;
    });

    function renderMarkdown(content) {
      if (!content) return '';
      const rawHtml = marked.parse(content);
      if (typeof DOMPurify !== 'undefined') {
        return DOMPurify.sanitize(rawHtml);
      }
      const div = document.createElement('div');
      div.textContent = content;
      return div.innerHTML;
    }

    function getProposals(msg) {
      if (msg.action_proposals && msg.action_proposals.length > 0) return msg.action_proposals;
      if (msg.action_proposal) return [msg.action_proposal];
      return [];
    }

    function getUnconfirmedProposals(msg) {
      return getProposals(msg).filter(p => !confirmedProposals.value.has(p.proposal_id));
    }

    function scrollChatToBottom() {
      nextTick(() => {
        if (chatContainer.value) {
          chatContainer.value.scrollTop = chatContainer.value.scrollHeight;
        }
        refreshIcons();
      });
    }

    async function sendChatMessage(options = {}) {
      const text = userInputText.value.trim();
      if (!text || isGenerating.value) return;
      const modalAtt = options && options.modalAttachment ? options.modalAttachment : null;

      chatMessages.value.push({ role: 'user', content: text });
      userInputText.value = '';
      isGenerating.value = true;
      scrollChatToBottom();

      try {
        const historyPayload = chatMessages.value.slice(0, -1).slice(-6).map(m => ({
          role: m.role,
          content: m.content
        }));

        const result = await apiCall('/api/v1/chat', {
          method: 'POST',
          body: JSON.stringify({ message: text, history: historyPayload })
        });

        const returnedProposals = (result.action_proposals && result.action_proposals.length > 0)
          ? result.action_proposals
          : (result.action_proposal ? [result.action_proposal] : []);

        if (modalAtt) {
          const sickProp = returnedProposals.find(p => p.leave_type === 'sick');
          if (sickProp) {
            proposalAttachments.value[sickProp.proposal_id] = modalAtt;
          }
        }

        chatMessages.value.push({
          role: 'assistant',
          content: result.answer,
          outcome: result.outcome,
          citations: result.citations || [],
          tool_calls: result.tool_calls || [],
          showCitations: false,
          action_proposal: result.action_proposal,
          action_proposals: result.action_proposals || [],
          trace_id: result.trace_id,
          usage: result.usage || {}
        });

        await refreshPolicyRules();
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

    // --- PROPOSAL CONFIRMATION & ATTACHMENT ---
    function handleProposalAttachment(event, proposalId) {
      const file = event.target.files[0];
      if (!file) return;
      let ctype = file.type || '';
      if (!ctype || ctype === 'image/jpg') {
        if (file.name.toLowerCase().endsWith('.pdf')) ctype = 'application/pdf';
        else if (file.name.toLowerCase().endsWith('.png')) ctype = 'image/png';
        else ctype = 'image/jpeg';
      }
      const reader = new FileReader();
      reader.onload = (e) => {
        const b64 = e.target.result.split(',')[1];
        proposalAttachments.value[proposalId] = {
          filename: file.name,
          content_type: ctype,
          content_base64: b64
        };
        notify(`Dokumen ${file.name} siap dilampirkan`, 'info');
      };
      reader.readAsDataURL(file);
    }

    async function confirmProposal(proposal) {
      const proposalId = typeof proposal === 'string' ? proposal : proposal.proposal_id;
      const propObj = typeof proposal === 'object' ? proposal : null;

      const att = proposalAttachments.value[proposalId] || null;
      const sickThreshold = Number(policyRules.value.sick_doc_threshold ?? 2);
      const isSick = propObj ? propObj.leave_type === 'sick' : false;
      const reqAtt = propObj
        ? (propObj.requires_attachment || (isSick && propObj.business_days > sickThreshold))
        : false;

      if (reqAtt && !att) {
        notify(`Sesuai kebijakan HR-LEAVE-002, cuti sakit > ${sickThreshold} hari wajib melampirkan surat dokter.`, 'error');
        return;
      }

      isConfirming.value = true;
      const idempotencyKey = `idem_${proposalId}`;
      try {
        if (att && isSick) {
          await apiCall(`/api/v1/action-proposals/${proposalId}/attachment`, {
            method: 'POST',
            body: JSON.stringify(att)
          });
        }

        const res = await apiCall(`/api/v1/action-proposals/${proposalId}/confirm`, {
          method: 'POST',
          headers: { 'X-Enforce-Sick-Attachment': 'true' },
          body: JSON.stringify({ idempotency_key: idempotencyKey })
        });

        confirmedProposals.value.add(proposalId);
        delete proposalAttachments.value[proposalId];

        chatMessages.value.push({
          role: 'assistant',
          content: `Permohonan cuti **#${res.request_id}** telah berhasil diajukan dengan status \`${res.status}\` (Audit Ref: \`${res.audit_reference}\`). Pengajuan masuk ke antrean tinjauan HRIS manajer.`
        });

        notify(`Permohonan cuti #${res.request_id} berhasil dikonfirmasi`, 'success');
        await Promise.all([fetchMyBalances(), fetchMyRequests()]);
      } catch (err) {
        notify(`Gagal mengonfirmasi proposal: ${err.message}`, 'error');
      } finally {
        isConfirming.value = false;
        scrollChatToBottom();
      }
    }

    async function confirmAllProposals(msg) {
      const unconfirmed = getUnconfirmedProposals(msg);
      for (const p of unconfirmed) {
        await confirmProposal(p);
      }
    }

    // --- LEAVE FORM MODAL LOGIC (DYNAMIC POLICY) ---
    const isLeaveModalOpen = ref(false);
    const formLeaveType = ref('annual');
    const formStartDate = ref('');
    const formEndDate = ref('');
    const formMinStartDate = ref('');
    const formWorkingDays = ref(1);
    const formReason = ref('');
    const formAttachment = ref(null);

    function calculateWorkingDays(startStr, endStr) {
      if (!startStr || !endStr) return 0;
      const start = new Date(`${startStr}T00:00:00`);
      const end = new Date(`${endStr}T00:00:00`);
      if (start > end) return 0;
      let count = 0;
      const cur = new Date(start);
      while (cur <= end) {
        const day = cur.getDay();
        if (day !== 0 && day !== 6) count++;
        cur.setDate(cur.getDate() + 1);
      }
      return count;
    }

    function calculateMinStartDate(leaveType) {
      const serverDate = policyRules.value.server_date || formatLocalDate(new Date());
      if (leaveType !== 'annual') {
        return serverDate;
      }
      if (policyRules.value.earliest_annual_start_date) {
        return policyRules.value.earliest_annual_start_date;
      }
      const today = new Date(`${serverDate}T00:00:00`);
      const requiredLead = Number(policyRules.value.annual_lead_days ?? 3);
      const candidate = new Date(today);
      if (requiredLead > 0) {
        candidate.setDate(candidate.getDate() + 1);
      }
      while (true) {
        let leadWorkdays = 0;
        if (requiredLead > 0) {
          const c = new Date(today);
          c.setDate(c.getDate() + 1);
          while (c <= candidate) {
            if (c.getDay() !== 0 && c.getDay() !== 6) leadWorkdays++;
            c.setDate(c.getDate() + 1);
          }
        }
        const isWeekday = candidate.getDay() !== 0 && candidate.getDay() !== 6;
        if (isWeekday && (requiredLead <= 0 || leadWorkdays >= requiredLead)) {
          return formatLocalDate(candidate);
        }
        candidate.setDate(candidate.getDate() + 1);
      }
    }

    // --- AGENT POLICY GUARDRAIL CACHING & CONSULTATION ---
    const isConsultingAgent = ref(false);
    const agentPolicySummary = ref('');
    const agentPolicyCitation = ref('');
    const policyCache = ref({});

    function warmPolicyCacheFromRules(rules) {
      if (!rules) return;
      if (rules.policy_summaries) {
        policyCache.value = { ...rules.policy_summaries };
      } else {
        const lead = rules.annual_lead_days ?? 3;
        const thresh = rules.sick_doc_threshold ?? 2;
        policyCache.value = {
          annual: {
            citation: '[HR-LEAVE-001]',
            summary: `Berdasarkan kebijakan [HR-LEAVE-001], cuti tahunan wajib diajukan minimal ${lead} hari kerja sebelumnya dan tidak bertumpang tindih dengan permohonan lain.`,
            lead_days: lead,
          },
          sick: {
            citation: '[HR-LEAVE-002]',
            summary: `Berdasarkan kebijakan [HR-LEAVE-002], cuti sakit lebih dari ${thresh} hari kerja berturut-turut wajib melampirkan surat keterangan dokter.`,
            threshold_days: thresh,
          },
          parental: {
            citation: '[HR-LEAVE-003]',
            summary: 'Berdasarkan kebijakan [HR-LEAVE-003], cuti orang tua mengikuti hak cuti melahirkan / hak ayah sesuai undang-undang dan kebijakan perusahaan.',
          }
        };
      }
    }

    async function fetchAgentPolicyGuardrail(leaveType, forceRefresh = false) {
      // 1. Session Cache Check (Zero Token, Zero Latency)
      if (!forceRefresh && policyCache.value && policyCache.value[leaveType]) {
        const cached = policyCache.value[leaveType];
        agentPolicySummary.value = cached.summary;
        agentPolicyCitation.value = cached.citation;
        isConsultingAgent.value = false;
        refreshIcons();
        return;
      }

      // 2. Fetch from Agent LLM (Only when explicitly requested or cache missing)
      const token = activePersona.value?.demo_token || '';
      if (!token) {
        if (!policyCache.value || !policyCache.value[leaveType]) {
          warmPolicyCacheFromRules(policyRules.value);
        }
        const fallback = policyCache.value?.[leaveType];
        const defaultCitation = leaveType === 'annual' ? '[HR-LEAVE-001]' : (leaveType === 'parental' ? '[HR-LEAVE-003]' : '[HR-LEAVE-002]');
        agentPolicySummary.value = fallback?.summary || 'Silakan masuk untuk memuat ringkasan kebijakan dari asisten.';
        agentPolicyCitation.value = fallback?.citation || defaultCitation;
        isConsultingAgent.value = false;
        refreshIcons();
        return;
      }

      isConsultingAgent.value = true;
      agentPolicySummary.value = '';
      agentPolicyCitation.value = '';

      const typeLabels = { annual: 'cuti tahunan', sick: 'cuti sakit', parental: 'cuti orang tua' };
      const label = typeLabels[leaveType] || leaveType;

      try {
        const res = await fetch(`${getApiBase()}/api/v1/chat`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({
            message: `Berapa hari kerja minimal lead time pengajuan untuk ${label} sebelum tanggal mulai dan apa syarat dokumennya berdasarkan kebijakan perusahaan? Sebutkan sitasi dokumen resminya.`
          })
        });

        if (res.ok) {
          const data = await res.json();
          const defaultCitation = leaveType === 'annual' ? '[HR-LEAVE-001]' : (leaveType === 'parental' ? '[HR-LEAVE-003]' : '[HR-LEAVE-002]');
          let citation = defaultCitation;
          if (Array.isArray(data.citations) && data.citations.length > 0) {
            const mapped = data.citations
              .map(c => typeof c === 'string' ? c : (c.document_id ? '[' + c.document_id + ']' : (c.title || '')))
              .filter(Boolean)
              .join(', ');
            if (mapped) citation = mapped;
          } else if (typeof data.answer === 'string') {
            const match = data.answer.match(/\[(HR-LEAVE-[0-9]+)\]/i);
            citation = match ? match[0] : defaultCitation;
          }
          const summary = data.answer || 'Informasi kebijakan berhasil dimuat.';
          agentPolicySummary.value = summary;
          agentPolicyCitation.value = citation;

          // Save to Cache for subsequent opens/switches
          policyCache.value[leaveType] = {
            citation,
            summary
          };
        } else {
          if (!policyCache.value || !policyCache.value[leaveType]) {
            warmPolicyCacheFromRules(policyRules.value);
          }
          if (policyCache.value && policyCache.value[leaveType]) {
            agentPolicySummary.value = policyCache.value[leaveType].summary;
            agentPolicyCitation.value = policyCache.value[leaveType].citation;
          }
        }
      } catch (err) {
        console.warn('Gagal memanggil Agent untuk guardrail kebijakan, menggunakan fallback cache:', err);
        if (!policyCache.value || !policyCache.value[leaveType]) {
          warmPolicyCacheFromRules(policyRules.value);
        }
        if (policyCache.value && policyCache.value[leaveType]) {
          agentPolicySummary.value = policyCache.value[leaveType].summary;
          agentPolicyCitation.value = policyCache.value[leaveType].citation;
        }
      } finally {
        isConsultingAgent.value = false;
        refreshIcons();
      }
    }

    async function openLeaveModal() {
      formLeaveType.value = 'annual';
      formReason.value = '';
      formAttachment.value = null;
      const initialMin = calculateMinStartDate('annual');
      formMinStartDate.value = initialMin;
      formStartDate.value = initialMin;
      formEndDate.value = initialMin;
      formWorkingDays.value = calculateWorkingDays(initialMin, initialMin);
      isLeaveModalOpen.value = true;
      refreshIcons();

      await refreshPolicyRules();
      const minDate = calculateMinStartDate(formLeaveType.value);
      formMinStartDate.value = minDate;
      if (formStartDate.value === initialMin || formStartDate.value < minDate) {
        formStartDate.value = minDate;
      }
      if (formEndDate.value === initialMin || formEndDate.value < formStartDate.value) {
        formEndDate.value = formStartDate.value;
      }
      formWorkingDays.value = calculateWorkingDays(formStartDate.value, formEndDate.value);
      fetchAgentPolicyGuardrail(formLeaveType.value);
      refreshIcons();
    }

    function onLeaveTypeChange() {
      if (formLeaveType.value !== 'sick') {
        formAttachment.value = null;
      }
      const minDate = calculateMinStartDate(formLeaveType.value);
      formMinStartDate.value = minDate;
      if (formStartDate.value < minDate) {
        formStartDate.value = minDate;
      }
      recalculateDuration();
      fetchAgentPolicyGuardrail(formLeaveType.value);
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
      let ctype = file.type || '';
      if (!ctype || ctype === 'image/jpg') {
        if (file.name.toLowerCase().endsWith('.pdf')) ctype = 'application/pdf';
        else if (file.name.toLowerCase().endsWith('.png')) ctype = 'image/png';
        else ctype = 'image/jpeg';
      }
      const reader = new FileReader();
      reader.onload = (e) => {
        const b64 = e.target.result.split(',')[1];
        formAttachment.value = {
          filename: file.name,
          content_type: ctype,
          content_base64: b64
        };
      };
      reader.readAsDataURL(file);
    }

    function submitLeaveForm() {
      if (formWorkingDays.value === 0) return;
      const sickThreshold = Number(policyRules.value.sick_doc_threshold ?? 2);
      if (
        formLeaveType.value === 'sick' &&
        formWorkingDays.value > sickThreshold &&
        !formAttachment.value
      ) {
        notify(`Cuti sakit > ${sickThreshold} hari kerja wajib melampirkan dokumen surat dokter.`, 'error');
        return;
      }

      const typeLabels = { annual: 'Cuti Tahunan', sick: 'Cuti Sakit', parental: 'Cuti Orang Tua' };
      const label = typeLabels[formLeaveType.value] || formLeaveType.value;
      const reasonPart = formReason.value.trim() ? ` dengan alasan: ${formReason.value.trim()}` : '';
      const prompt = `Siapkan ${label.toLowerCase()} (${formLeaveType.value}) dari ${formStartDate.value} sampai ${formEndDate.value}${reasonPart}`;
      const attToForward = formLeaveType.value === 'sick' ? formAttachment.value : null;

      formAttachment.value = null;
      isLeaveModalOpen.value = false;
      activeTab.value = 'chat';
      userInputText.value = prompt;
      sendChatMessage({ modalAttachment: attToForward });
    }

    // --- VOICE RECORDING ---
    const isRecording = ref(false);
    let mediaRecorder = null;
    let audioChunks = [];

    async function toggleVoiceRecording() {
      if (isRecording.value) {
        if (mediaRecorder && mediaRecorder.state !== 'inactive') {
          mediaRecorder.stop();
        }
        isRecording.value = false;
        return;
      }

      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioChunks = [];
        const mimeType = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/wav';
        mediaRecorder = new MediaRecorder(stream);

        mediaRecorder.ondataavailable = (e) => {
          if (e.data.size > 0) audioChunks.push(e.data);
        };

        mediaRecorder.onstop = async () => {
          stream.getTracks().forEach(t => t.stop());
          isRecording.value = false;
          const audioBlob = new Blob(audioChunks, { type: mimeType });
          if (audioBlob.size < 4) {
            notify('Rekaman suara terlalu singkat atau kosong. Silakan rekam ulang.', 'info');
            return;
          }
          const reader = new FileReader();
          reader.onerror = () => {
            notify('Gagal membaca data rekaman audio dari perangkat.', 'error');
          };
          reader.onload = async () => {
            const rawResult = typeof reader.result === 'string' ? reader.result : '';
            const b64 = rawResult.includes(',') ? rawResult.split(',')[1] : '';
            if (!b64) {
              notify('Format rekaman audio tidak valid. Silakan coba lagi.', 'error');
              return;
            }
            try {
              const res = await apiCall('/api/v1/audio/transcribe', {
                method: 'POST',
                body: JSON.stringify({
                  audio_base64: b64,
                  filename: `voice_query.${mimeType.includes('webm') ? 'webm' : 'wav'}`,
                  language: 'id'
                })
              });
              if (res && res.text) {
                userInputText.value = res.text;
                sendChatMessage();
              } else {
                notify('Tidak ada ucapan yang terdeteksi.', 'info');
              }
            } catch (err) {
              const rawMsg = String(err?.message || '');
              const lower = rawMsg.toLowerCase();
              if (lower.includes('no speech detected')) {
                notify('Tidak ada ucapan yang terdeteksi pada rekaman. Silakan ulangi dan bicara lebih jelas.', 'info');
              } else if (lower.includes('audio size') || lower.includes('invalid base64')) {
                notify('Ukuran atau format rekaman audio tidak valid. Silakan rekam ulang minimal 1 detik.', 'error');
              } else if (lower.includes('unavailable') || lower.includes('502') || lower.includes('bad gateway')) {
                notify('Layanan suara-ke-teks (STT) sedang tidak tersedia. Silakan ketik pesan Anda secara manual.', 'error');
              } else {
                notify(`Gagal menerjemahkan suara: ${rawMsg || 'Terjadi kesalahan pada layanan STT.'}`, 'error');
              }
            }
          };
          reader.readAsDataURL(audioBlob);
        };

        mediaRecorder.start();
        isRecording.value = true;
        refreshIcons();
      } catch (err) {
        notify('Akses mikrofon tidak tersedia: ' + err.message, 'error');
      }
    }

    // --- MY REQUESTS & ATTACHMENT VIEWER ---
    const myRequests = ref([]);
    const attachmentViewerModal = ref({
      open: false,
      loading: false,
      requestId: '',
      filename: '',
      contentType: '',
      dataUrl: ''
    });

    async function fetchMyRequests() {
      if (!activePersona.value) return;
      try {
        const res = await apiCall('/api/v1/leave-requests/me');
        myRequests.value = res || [];
      } catch (err) {
        console.error('Fetch my requests error:', err);
      }
    }

    async function uploadExistingRequestAttachment(event, requestId) {
      const file = event.target.files[0];
      if (!file) return;
      let ctype = file.type || '';
      if (!ctype || ctype === 'image/jpg') {
        if (file.name.toLowerCase().endsWith('.pdf')) ctype = 'application/pdf';
        else if (file.name.toLowerCase().endsWith('.png')) ctype = 'image/png';
        else ctype = 'image/jpeg';
      }
      const reader = new FileReader();
      reader.onload = async (e) => {
        const b64 = e.target.result.split(',')[1];
        try {
          await apiCall(`/api/v1/leave-requests/${requestId}/attachment`, {
            method: 'POST',
            body: JSON.stringify({
              filename: file.name,
              content_type: ctype,
              content_base64: b64
            })
          });
          notify(`Lampiran ${file.name} berhasil disimpan`, 'success');
          fetchMyRequests();
        } catch (err) {
          notify(`Gagal mengunggah lampiran: ${err.message}`, 'error');
        }
      };
      reader.readAsDataURL(file);
    }

    async function viewAttachment(requestId) {
      attachmentViewerModal.value = {
        open: true,
        loading: true,
        requestId,
        filename: '',
        contentType: '',
        dataUrl: ''
      };
      refreshIcons();
      try {
        const res = await apiCall(`/api/v1/leave-requests/${requestId}/attachment`);
        attachmentViewerModal.value = {
          open: true,
          loading: false,
          requestId,
          filename: res.filename,
          contentType: res.content_type,
          dataUrl: `data:${res.content_type};base64,${res.content_base64}`
        };
      } catch (err) {
        attachmentViewerModal.value.open = false;
        notify(`Gagal memuat lampiran: ${err.message}`, 'error');
      } finally {
        refreshIcons();
      }
    }

    // --- ANONYMIZED HR ANALYTICS (ADMIN ONLY) ---
    const teamAnalytics = ref(null);

    async function fetchAnalyticsOverview() {
      if (!isAdmin.value) return;
      try {
        const res = await apiCall('/api/v1/analytics/overview');
        teamAnalytics.value = res || null;
      } catch (err) {
        console.error('Fetch analytics error:', err);
      }
    }

    // --- DYNAMIC CALENDAR ---
    const calYear = ref(new Date().getFullYear());
    const calMonth = ref(new Date().getMonth() + 1); // 1 - 12
    const calFilterType = ref('all');
    const calFilterStatus = ref('all');

    const monthNamesId = [
      '', 'Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni',
      'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'
    ];

    function prevCalMonth() {
      if (calMonth.value === 1) {
        calMonth.value = 12;
        calYear.value -= 1;
      } else {
        calMonth.value -= 1;
      }
    }

    function nextCalMonth() {
      if (calMonth.value === 12) {
        calMonth.value = 1;
        calYear.value += 1;
      } else {
        calMonth.value += 1;
      }
    }

    function resetCalToday() {
      const d = new Date(`${policyRules.value.server_date}T00:00:00`);
      calYear.value = d.getFullYear();
      calMonth.value = d.getMonth() + 1;
    }

    const calendarActiveRequests = computed(() => {
      return myRequests.value.filter(r => {
        if (!['approved', 'pending_manager_review'].includes(r.status)) return false;
        if (calFilterType.value !== 'all' && r.leave_type !== calFilterType.value) return false;
        if (calFilterStatus.value !== 'all' && r.status !== calFilterStatus.value) return false;
        return true;
      });
    });

    const earliestAnnualStartDate = computed(() => calculateMinStartDate('annual'));

    const calendarDays = computed(() => {
      const y = calYear.value;
      const m = calMonth.value;
      const firstDay = new Date(y, m - 1, 1);
      const totalDays = new Date(y, m, 0).getDate();
      const startWeekday = firstDay.getDay(); // 0=Sun, 1=Mon...
      const offset = startWeekday === 0 ? 6 : startWeekday - 1;
      const serverDate = policyRules.value.server_date || formatLocalDate(new Date());
      const earliestAnnual = earliestAnnualStartDate.value;

      const days = [];
      for (let i = 0; i < offset; i++) {
        days.push({
          dayNum: '',
          dateStr: `pad-${i}`,
          isToday: false,
          isWeekend: false,
          isLeadLocked: false,
          isBookable: false,
          events: []
        });
      }

      for (let d = 1; d <= totalDays; d++) {
        const dStr = `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
        const dateObj = new Date(`${dStr}T00:00:00`);
        const dow = dateObj.getDay();
        const isWeekend = dow === 0 || dow === 6;
        const isToday = dStr === serverDate;
        const isLeadLocked = !isWeekend && dStr >= serverDate && dStr < earliestAnnual;
        const isBookable = !isWeekend && dStr >= earliestAnnual;

        const events = [];
        for (const req of calendarActiveRequests.value) {
          if (req.start_date <= dStr && req.end_date >= dStr) {
            const empName = req.employee_name || req.employee_id || userDisplayName.value;
            const shortName = empName.split(' ')[0];
            const typeMap = { annual: 'Tahunan', sick: 'Sakit', parental: 'Orang Tua' };
            const tLabel = typeMap[req.leave_type] || req.leave_type;
            const isPend = req.status === 'pending_manager_review';

            let badgeCls = 'bg-blue-500/15 text-blue-400 border border-blue-500/30';
            if (req.leave_type === 'sick') badgeCls = 'bg-rose-500/15 text-rose-400 border border-rose-500/30';
            if (req.leave_type === 'parental') badgeCls = 'bg-indigo-500/15 text-indigo-400 border border-indigo-500/30';
            if (isPend) badgeCls += ' border-dashed opacity-85';

            events.push({
              id: req.request_id,
              text: `Cuti ${tLabel}`,
              tooltip: `${empName} | Cuti ${tLabel} (${req.start_date} s/d ${req.end_date}) — ${formatStatus(req.status)}`,
              class: badgeCls
            });
          }
        }

        days.push({ dayNum: d, dateStr: dStr, isToday, isWeekend, isLeadLocked, isBookable, events });
      }
      return days;
    });

    // --- MONITORING DATA FETCH ---
    const monitoringSummary = ref({});
    const monitoringAlerts = ref([]);

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

    // --- TICKETS STATE & ACTIONS (EMAIL INBOX CONCEPT) ---
    const ticketsList = ref([]);
    const isLoadingTickets = ref(false);
    const selectedTicketId = ref('');
    const ticketFilterStatus = ref('all');
    const ticketSearchQuery = ref('');
    const isUpdatingTicket = ref(false);
    const editTicketStatus = ref('pending');

    const selectedTicket = computed(() => {
      return ticketsList.value.find(t => t.ticket_id === selectedTicketId.value) || null;
    });

    const pendingTicketsCount = computed(() => {
      return ticketsList.value.filter(t => t.status === 'pending').length;
    });

    const filteredTickets = computed(() => {
      let list = ticketsList.value;
      if (ticketFilterStatus.value !== 'all') {
        list = list.filter(t => t.status === ticketFilterStatus.value);
      }
      if (ticketSearchQuery.value.trim()) {
        const q = ticketSearchQuery.value.toLowerCase();
        list = list.filter(t =>
          (t.summary && t.summary.toLowerCase().includes(q)) ||
          (t.ticket_id && t.ticket_id.toLowerCase().includes(q)) ||
          (t.employee_name && t.employee_name.toLowerCase().includes(q)) ||
          (t.employee_id && t.employee_id.toLowerCase().includes(q)) ||
          (t.category && t.category.toLowerCase().includes(q))
        );
      }
      return list;
    });

    async function fetchTickets() {
      if (!activePersona.value?.demo_token) return;
      isLoadingTickets.value = true;
      try {
        const data = await apiCall('/api/v1/tickets');
        ticketsList.value = Array.isArray(data) ? data : [];
        if (ticketsList.value.length > 0) {
          if (!selectedTicketId.value || !ticketsList.value.some(t => t.ticket_id === selectedTicketId.value)) {
            selectedTicketId.value = ticketsList.value[0].ticket_id;
            editTicketStatus.value = ticketsList.value[0].status || 'pending';
          } else {
            const cur = ticketsList.value.find(t => t.ticket_id === selectedTicketId.value);
            if (cur) editTicketStatus.value = cur.status || 'pending';
          }
        } else {
          selectedTicketId.value = '';
        }
      } catch (err) {
        console.error('Fetch tickets error:', err);
      } finally {
        isLoadingTickets.value = false;
        refreshIcons();
      }
    }

    function selectTicket(ticket) {
      if (!ticket) return;
      selectedTicketId.value = ticket.ticket_id;
      editTicketStatus.value = ticket.status || 'pending';
      refreshIcons();
    }

    async function submitTicketStatusChange(ticketId, newStatus) {
      if (!activePersona.value?.demo_token) return;
      if (!isAdmin.value) {
        notify('Hanya Monitoring Admin yang dapat memperbarui status tiket', 'error');
        return;
      }
      isUpdatingTicket.value = true;
      try {
        const updated = await apiCall(`/api/v1/tickets/${ticketId}/status`, {
          method: 'PATCH',
          body: JSON.stringify({ status: newStatus })
        });
        const idx = ticketsList.value.findIndex(t => t.ticket_id === ticketId);
        if (idx !== -1) {
          ticketsList.value[idx] = updated;
        }
        editTicketStatus.value = updated.status;
        notify(`Status tiket ${ticketId} berhasil diperbarui menjadi "${updated.status}"`, 'success');
      } catch (err) {
        notify(err.message || 'Gagal memperbarui status tiket', 'error');
      } finally {
        isUpdatingTicket.value = false;
        refreshIcons();
      }
    }

    watch(activeTab, async (newTab) => {
      if (newTab === 'tickets') {
        fetchTickets();
      } else if (newTab === 'calendar') {
        await refreshPolicyRules();
      }
      refreshIcons();
    });

    // --- FORMATTERS ---
    function formatStatus(st) {
      const map = {
        pending_manager_review: 'Menunggu Review',
        approved: 'Disetujui',
        rejected: 'Ditolak',
        cancelled: 'Dibatalkan'
      };
      return map[st] || st;
    }

    function formatLeaveType(lt) {
      const map = {
        annual: 'Cuti Tahunan',
        sick: 'Cuti Sakit',
        parental: 'Cuti Orang Tua'
      };
      return map[lt] || lt;
    }

    function statusBadgeClass(st) {
      if (st === 'approved') return 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30';
      if (st === 'rejected') return 'bg-rose-500/15 text-rose-400 border border-rose-500/30';
      if (st === 'cancelled') return 'bg-zinc-500/15 text-zinc-400 border border-zinc-500/30';
      return 'bg-amber-500/15 text-amber-400 border border-amber-500/30';
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
      fetchSystemInit();
      refreshIcons();
    });

    return {
      isAuthenticated,
      isSidebarCollapsed,
      isMobileSidebarOpen,
      showSidebarExpanded,
      openMobileSidebar,
      closeMobileSidebar,
      selectTab,
      activeTab,
      isBackendReady,
      isDarkMode,
      toggleTheme,
      showDevAudit,
      toggleDevAudit,
      toast,
      notify,
      formatLocalDate,
      policyRules,
      refreshPolicyRules,
      currentDateFormatted,
      personasCatalog,
      isLoadingPersonas,
      activePersona,
      selectedPersonaId,
      selectSsoPersona,
      onSidebarPersonaSwitch,
      logoutSession,
      isLoginModalOpen,
      pendingStepUpPersona,
      openManualLoginModal,
      loginUsername,
      loginPassword,
      loginError,
      isLoggingIn,
      submitPasswordLogin,
      userDisplayName,
      userInitials,
      getInitials,
      userRoleLabel,
      isAdmin,
      roleBadgeClass,
      visibleTabs,
      currentTabTitle,
      myBalances,
      annualBalanceDays,
      sickBalanceDays,
      parentalBalanceDays,
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
      getUnconfirmedProposals,
      sendChatMessage,
      sendQuickPrompt,
      clearChat,
      confirmProposal,
      confirmAllProposals,
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
      isConsultingAgent,
      agentPolicySummary,
      agentPolicyCitation,
      policyCache,
      fetchAgentPolicyGuardrail,
      openLeaveModal,
      onLeaveTypeChange,
      recalculateDuration,
      handleFormAttachment,
      submitLeaveForm,
      myRequests,
      fetchMyRequests,
      uploadExistingRequestAttachment,
      attachmentViewerModal,
      viewAttachment,
      teamAnalytics,
      fetchAnalyticsOverview,
      calYear,
      calMonth,
      calFilterType,
      calFilterStatus,
      monthNamesId,
      prevCalMonth,
      nextCalMonth,
      resetCalToday,
      earliestAnnualStartDate,
      calendarActiveRequests,
      calendarDays,
      monitoringSummary,
      monitoringAlerts,
      fetchMonitoringData,
      ticketsList,
      isLoadingTickets,
      selectedTicketId,
      selectedTicket,
      ticketFilterStatus,
      ticketSearchQuery,
      isUpdatingTicket,
      editTicketStatus,
      pendingTicketsCount,
      filteredTickets,
      fetchTickets,
      selectTicket,
      submitTicketStatusChange,
      formatStatus,
      formatLeaveType,
      statusBadgeClass,
      refreshIcons,
      apiBaseUrl,
      showSettingsModal,
      showApiSettingsModal,
      tempApiUrl,
      isTestingConnection,
      connectionTestResult,
      openSettingsModal,
      openApiSettingsModal,
      closeSettingsModal,
      testBackendConnection,
      saveApiSettings,
      resetApiSettings,
      isSettingsMenuOpen,
      toggleSettingsMenu,
      closeSettingsMenu
    };
  }
}).mount('#app');