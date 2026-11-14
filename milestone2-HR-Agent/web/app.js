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
    const activeTab = ref('chat'); // 'chat' | 'my_requests' | 'approvals' | 'calendar' | 'monitoring'
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

    // --- POLICY & SERVER DATE STATE (DYNAMIC FROM BACKEND) ---
    const policyRules = ref({
      server_date: new Date().toISOString().split('T')[0],
      annual_lead_days: 3,
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

    async function fetchSystemInit() {
      isLoadingPersonas.value = true;
      try {
        const [personasRes, rulesRes] = await Promise.all([
          fetch(`${getApiBase()}/api/v1/auth/personas`).then(r => (r.ok ? r.json() : [])),
          fetch(`${getApiBase()}/api/v1/policies/rules`).then(r => (r.ok ? r.json() : null))
        ]);

        if (rulesRes) {
          policyRules.value = rulesRes;
          warmPolicyCacheFromRules(rulesRes);
          const d = new Date(`${rulesRes.server_date}T00:00:00`);
          calYear.value = d.getFullYear();
          calMonth.value = d.getMonth() + 1;
        }

        personasCatalog.value = (personasRes || []).map(p => ({
          ...p,
          label: `${p.display_name} — ${p.department || p.role}`
        }));

        // Restore previous session if valid
        const savedSession = sessionStorage.getItem('miyo_active_session');
        if (savedSession) {
          try {
            const parsed = JSON.parse(savedSession);
            if (parsed && parsed.demo_token) {
              activePersona.value = parsed;
              selectedPersonaId.value = parsed.employee_id;
              isAuthenticated.value = true;
              await loadAuthenticatedWorkspace();
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

    function selectSsoPersona(persona) {
      if (persona.requires_password && !persona.demo_token) {
        pendingStepUpPersona.value = persona;
        loginUsername.value = persona.username || persona.employee_id;
        loginPassword.value = '';
        loginError.value = '';
        isLoginModalOpen.value = true;
        refreshIcons();
        return;
      }
      activateSession(persona);
    }

    function onSidebarPersonaSwitch() {
      const target = personasCatalog.value.find(p => p.employee_id === selectedPersonaId.value);
      if (!target) return;
      if (target.requires_password && !target.demo_token) {
        // Revert dropdown until password is verified
        selectedPersonaId.value = activePersona.value ? activePersona.value.employee_id : '';
        selectSsoPersona(target);
        return;
      }
      activateSession(target);
    }

    async function activateSession(persona) {
      activePersona.value = persona;
      selectedPersonaId.value = persona.employee_id;
      isAuthenticated.value = true;
      sessionStorage.setItem('miyo_active_session', JSON.stringify(persona));

      chatMessages.value = [];
      confirmedProposals.value = new Set();
      proposalAttachments.value = {};
      activeTab.value = 'chat';

      await loadAuthenticatedWorkspace();
      refreshIcons();
    }

    function logoutSession() {
      isAuthenticated.value = false;
      activePersona.value = null;
      selectedPersonaId.value = '';
      chatMessages.value = [];
      confirmedProposals.value = new Set();
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
        const res = await fetch(`${getApiBase()}/api/v1/auth/login`, {
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

        let existing = personasCatalog.value.find(p => p.employee_id === profile.employee_id);
        if (!existing) {
          existing = {
            employee_id: profile.employee_id,
            username: loginUsername.value.trim(),
            display_name: profile.display_name,
            role: profile.role,
            department: profile.department || 'Engineering',
            label: `${profile.display_name} — ${profile.department || profile.role}`,
            requires_password: true,
            demo_token: token,
            balances: {}
          };
          personasCatalog.value.push(existing);
        } else {
          existing.demo_token = token;
        }

        isLoginModalOpen.value = false;
        pendingStepUpPersona.value = null;
        loginUsername.value = '';
        loginPassword.value = '';
        await activateSession(existing);
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
      if (r === 'manager') return 'Engineering Manager';
      return activePersona.value.department || 'Software Engineer';
    });

    const isAdmin = computed(() => activePersona.value?.role === 'monitoring_admin');
    const isManager = computed(() => activePersona.value?.role === 'manager' || isAdmin.value);

    const roleBadgeClass = computed(() => {
      const r = activePersona.value?.role;
      if (r === 'monitoring_admin') return 'bg-sky-500/15 text-sky-400 border border-sky-500/30';
      if (r === 'manager') return 'bg-blue-500/15 text-blue-400 border border-blue-500/30';
      return 'bg-zinc-500/15 text-zinc-300 border border-zinc-500/30';
    });

    const visibleTabs = computed(() => {
      const list = [
        { id: 'chat', label: 'Asisten Kebijakan', icon: 'message-square' },
        { id: 'my_requests', label: 'Permohonan Cuti', icon: 'file-text' },
        { id: 'calendar', label: 'Kalender Cuti', icon: 'calendar' }
      ];
      if (isManager.value) {
        const pendingCount = teamRequests.value.filter(r => r.status === 'pending_manager_review').length;
        list.push({
          id: 'approvals',
          label: 'Persetujuan Tim',
          icon: 'users',
          badge: pendingCount > 0 ? pendingCount : null
        });
      }
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
        fetchMyBalances(),
        fetchMyRequests(),
        fetchTickets(),
        isManager.value ? fetchTeamRequests() : Promise.resolve(),
        isManager.value ? fetchAnalyticsOverview() : Promise.resolve(),
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
      if (isManager.value) {
        return [
          'Bagaimana tren analitik dan pengajuan cuti tim saya saat ini?',
          'Siapa anggota tim yang sisa saldo cutinya paling rendah?',
          'Berapa sisa saldo cuti saya saat ini?',
          'Berapa hari boleh Work From Home (WFH) per minggu?'
        ];
      }
      return base;
    });

    function renderMarkdown(content) {
      if (!content) return '';
      return marked.parse(content);
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

    async function sendChatMessage() {
      const text = userInputText.value.trim();
      if (!text || isGenerating.value) return;

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

      const att = proposalAttachments.value[proposalId] || formAttachment.value;
      const reqAtt = propObj
        ? (propObj.requires_attachment || (propObj.leave_type === 'sick' && propObj.business_days > policyRules.value.sick_doc_threshold))
        : false;

      if (reqAtt && !att) {
        notify(`Sesuai kebijakan HR-LEAVE-002, cuti sakit > ${policyRules.value.sick_doc_threshold} hari wajib melampirkan surat dokter.`, 'error');
        return;
      }

      isConfirming.value = true;
      const idempotencyKey = `idem_${proposalId}`;
      try {
        const res = await apiCall(`/api/v1/action-proposals/${proposalId}/confirm`, {
          method: 'POST',
          body: JSON.stringify({ idempotency_key: idempotencyKey })
        });

        confirmedProposals.value.add(proposalId);

        if (att && res.request_id) {
          await apiCall(`/api/v1/leave-requests/${res.request_id}/attachment`, {
            method: 'POST',
            body: JSON.stringify(att)
          });
          delete proposalAttachments.value[proposalId];
          formAttachment.value = null;
        }

        chatMessages.value.push({
          role: 'assistant',
          content: `Permohonan cuti **#${res.request_id}** telah berhasil diajukan dengan status \`${res.status}\` (Audit Ref: \`${res.audit_reference}\`). Manajer Anda akan meninjau permohonan ini.`
        });

        notify(`Permohonan cuti #${res.request_id} berhasil dikonfirmasi`, 'success');
        await Promise.all([fetchMyBalances(), fetchMyRequests(), isManager.value ? fetchTeamRequests() : Promise.resolve()]);
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
      const today = new Date(`${policyRules.value.server_date}T00:00:00`);
      if (leaveType !== 'annual') {
        return policyRules.value.server_date;
      }
      const requiredLead = policyRules.value.annual_lead_days || 3;
      const candidate = new Date(today);
      candidate.setDate(candidate.getDate() + 1);
      while (true) {
        let leadWorkdays = 0;
        const c = new Date(today);
        c.setDate(c.getDate() + 1);
        while (c < candidate) {
          if (c.getDay() !== 0 && c.getDay() !== 6) leadWorkdays++;
          c.setDate(c.getDate() + 1);
        }
        if (leadWorkdays >= requiredLead && candidate.getDay() !== 0 && candidate.getDay() !== 6) {
          return candidate.toISOString().split('T')[0];
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
        const lead = rules.annual_lead_days || 3;
        const thresh = rules.sick_doc_threshold || 2;
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
      isConsultingAgent.value = true;
      agentPolicySummary.value = '';
      agentPolicyCitation.value = '';

      const typeLabels = { annual: 'cuti tahunan', sick: 'cuti sakit', parental: 'cuti orang tua' };
      const label = typeLabels[leaveType] || leaveType;

      try {
        const token = sessionStorage.getItem('miyo_active_token') || 'token-alya';
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
          let citation = '[HR-LEAVE-001]';
          if (data.citations && data.citations.length > 0) {
            citation = data.citations.join(', ');
          } else {
            const match = data.reply.match(/\[(HR-LEAVE-[0-9]+)\]/i);
            citation = match ? match[0] : (leaveType === 'annual' ? '[HR-LEAVE-001]' : '[HR-LEAVE-002]');
          }
          agentPolicySummary.value = data.reply;
          agentPolicyCitation.value = citation;

          // Save to Cache for subsequent opens/switches
          policyCache.value[leaveType] = {
            citation,
            summary: data.reply
          };
        }
      } catch (err) {
        console.warn('Gagal memanggil Agent untuk guardrail kebijakan, menggunakan fallback cache:', err);
        if (policyCache.value && policyCache.value[leaveType]) {
          agentPolicySummary.value = policyCache.value[leaveType].summary;
          agentPolicyCitation.value = policyCache.value[leaveType].citation;
        }
      } finally {
        isConsultingAgent.value = false;
        refreshIcons();
      }
    }

    function openLeaveModal() {
      formLeaveType.value = 'annual';
      const minDate = calculateMinStartDate('annual');
      formMinStartDate.value = minDate;
      formStartDate.value = minDate;
      formEndDate.value = minDate;
      formWorkingDays.value = calculateWorkingDays(minDate, minDate);
      formReason.value = '';
      formAttachment.value = null;
      isLeaveModalOpen.value = true;
      fetchAgentPolicyGuardrail('annual');
      refreshIcons();
    }

    function onLeaveTypeChange() {
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
      if (
        formLeaveType.value === 'sick' &&
        formWorkingDays.value > policyRules.value.sick_doc_threshold &&
        !formAttachment.value
      ) {
        notify(`Cuti sakit > ${policyRules.value.sick_doc_threshold} hari kerja wajib melampirkan dokumen surat dokter.`, 'error');
        return;
      }

      const typeLabels = { annual: 'Cuti Tahunan', sick: 'Cuti Sakit', parental: 'Cuti Orang Tua' };
      const label = typeLabels[formLeaveType.value] || formLeaveType.value;
      const reasonPart = formReason.value.trim() ? ` dengan alasan: ${formReason.value.trim()}` : '';
      const prompt = `Siapkan ${label.toLowerCase()} (${formLeaveType.value}) dari ${formStartDate.value} sampai ${formEndDate.value}${reasonPart}`;

      isLeaveModalOpen.value = false;
      activeTab.value = 'chat';
      userInputText.value = prompt;
      sendChatMessage();
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
                notify('Tidak ada ucapan yang terdeteksi.', 'info');
              }
            } catch (err) {
              notify(`Gagal menerjemahkan suara: ${err.message}`, 'error');
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

    // --- MANAGER APPROVALS & ANALYTICS ---
    const teamRequests = ref([]);
    const teamAnalytics = ref(null);
    const reviewNotes = ref({});

    async function fetchTeamRequests() {
      if (!isManager.value) return;
      try {
        const res = await apiCall('/api/v1/manager/leave-requests');
        teamRequests.value = res || [];
        teamRequests.value.forEach(r => {
          if (!reviewNotes.value[r.request_id]) {
            reviewNotes.value[r.request_id] = 'Reviewed by manager';
          }
        });
      } catch (err) {
        console.error('Fetch team requests error:', err);
      }
    }

    async function fetchAnalyticsOverview() {
      if (!isManager.value) return;
      try {
        const res = await apiCall('/api/v1/analytics/overview');
        teamAnalytics.value = res || null;
      } catch (err) {
        console.error('Fetch analytics error:', err);
      }
    }

    async function reviewRequest(requestId, decision) {
      const note = (reviewNotes.value[requestId] || '').trim() || (decision === 'approved' ? 'Approved by manager' : 'Rejected by manager');
      try {
        const res = await apiCall(`/api/v1/manager/leave-requests/${requestId}/review`, {
          method: 'POST',
          body: JSON.stringify({
            decision,
            review_note: note
          })
        });
        notify(`Permohonan #${requestId} telah ${decision === 'approved' ? 'disetujui' : 'ditolak'} (${res.audit_reference})`, 'success');
        await Promise.all([fetchTeamRequests(), fetchAnalyticsOverview(), fetchMyRequests(), fetchMyBalances()]);
      } catch (err) {
        notify(`Gagal memproses review: ${err.message}`, 'error');
      }
    }

    // --- DYNAMIC CALENDAR ---
    const calYear = ref(new Date().getFullYear());
    const calMonth = ref(new Date().getMonth() + 1); // 1 - 12
    const calScope = ref('team'); // 'team' | 'personal'
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
      const source = (isManager.value && calScope.value === 'team') ? teamRequests.value : myRequests.value;
      return source.filter(r => {
        if (!['approved', 'pending_manager_review'].includes(r.status)) return false;
        if (calFilterType.value !== 'all' && r.leave_type !== calFilterType.value) return false;
        if (calFilterStatus.value !== 'all' && r.status !== calFilterStatus.value) return false;
        return true;
      });
    });

    const calendarDays = computed(() => {
      const y = calYear.value;
      const m = calMonth.value;
      const firstDay = new Date(y, m - 1, 1);
      const totalDays = new Date(y, m, 0).getDate();
      const startWeekday = firstDay.getDay(); // 0=Sun, 1=Mon...
      const offset = startWeekday === 0 ? 6 : startWeekday - 1;

      const days = [];
      for (let i = 0; i < offset; i++) {
        days.push({ dayNum: '', dateStr: `pad-${i}`, isToday: false, isWeekend: false, events: [] });
      }

      for (let d = 1; d <= totalDays; d++) {
        const dStr = `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
        const dateObj = new Date(`${dStr}T00:00:00`);
        const dow = dateObj.getDay();
        const isWeekend = dow === 0 || dow === 6;
        const isToday = dStr === policyRules.value.server_date;

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
              text: (isManager.value && calScope.value === 'team') ? `${shortName} · ${tLabel}` : `Cuti ${tLabel}`,
              tooltip: `${empName} | Cuti ${tLabel} (${req.start_date} s/d ${req.end_date}) — ${formatStatus(req.status)}`,
              class: badgeCls
            });
          }
        }

        days.push({ dayNum: d, dateStr: dStr, isToday, isWeekend, events });
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
      if (!isManager.value && !isAdmin.value) {
        notify('Hanya Manager atau Admin yang dapat memperbarui status tiket', 'error');
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

    watch(activeTab, (newTab) => {
      if (newTab === 'tickets') {
        fetchTickets();
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
      activeTab,
      isBackendReady,
      isDarkMode,
      toggleTheme,
      showDevAudit,
      toggleDevAudit,
      toast,
      notify,
      policyRules,
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
      isManager,
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
      teamRequests,
      teamAnalytics,
      reviewNotes,
      fetchTeamRequests,
      fetchAnalyticsOverview,
      reviewRequest,
      calYear,
      calMonth,
      calScope,
      calFilterType,
      calFilterStatus,
      monthNamesId,
      prevCalMonth,
      nextCalMonth,
      resetCalToday,
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