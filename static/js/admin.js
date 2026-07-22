/* ============================================================
   WeSafe Admin — lógica do painel
   ============================================================ */
(function () {
  "use strict";

  const CFG = window.WESAFE_ADMIN_CONFIG || {};
  const API_BASE = CFG.API_BASE || "";
  const TOKEN = localStorage.getItem("wesafe_admin_token");

  if (!TOKEN) {
    window.location.href = CFG.LOGIN_URL || "/admin";
    return;
  }

  const el = (id) => document.getElementById(id);

  function showToast(msg, type = "success") {
    const toast = el("toast");
    const icon = toast.querySelector("i");
    const msgEl = el("toastMsg");
    toast.className = "toast show " + type;
    icon.className = type === "error" ? "fa-solid fa-circle-exclamation" : "fa-solid fa-circle-check";
    msgEl.textContent = msg;
    clearTimeout(window._toastTimeout);
    window._toastTimeout = setTimeout(() => toast.classList.remove("show"), 3200);
  }

  async function api(path, options = {}) {
    const headers = Object.assign({}, options.headers, {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${localStorage.getItem("wesafe_admin_token")}`,
    });
    const resp = await fetch(`${API_BASE}${path}`, { ...options, headers });
    if (resp.status === 401 || resp.status === 403) {
      localStorage.removeItem("wesafe_admin_token");
      localStorage.removeItem("wesafe_admin_name");
      window.location.href = CFG.LOGIN_URL || "/admin";
      throw new Error("Sessão de administrador expirada ou sem permissão.");
    }
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || "Erro ao comunicar com a API.");
    return data;
  }

  // ---------- Cabeçalho ----------
  el("adminName").textContent = localStorage.getItem("wesafe_admin_name") || "Administrador";
  el("logoutBtn").addEventListener("click", () => {
    localStorage.removeItem("wesafe_admin_token");
    localStorage.removeItem("wesafe_admin_name");
    window.location.href = CFG.LOGIN_URL || "/admin";
  });

  // ---------- Abas ----------
  document.querySelectorAll(".admin-tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".admin-tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".admin-tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      el(`tab-${btn.dataset.tab}`).classList.add("active");
      if (btn.dataset.tab === "users") loadUsers();
      if (btn.dataset.tab === "reports") loadReports();
    });
  });

  function timeAgo(iso) {
    if (!iso) return "—";
    const diffMs = Date.now() - new Date(iso + "Z").getTime();
    const mins = Math.floor(diffMs / 60000);
    if (mins < 1) return "agora mesmo";
    if (mins < 60) return `${mins} min atrás`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours} h atrás`;
    const days = Math.floor(hours / 24);
    return `${days} d atrás`;
  }

  const CATEGORY_LABELS = {
    "assalto": "Assalto / Roubo",
    "suspeito": "Atividade suspeita",
    "ma-iluminacao": "Iluminação ruim",
    "acidente": "Acidente",
    "via-bloqueada": "Via bloqueada",
    "radar": "Radar / Blitz",
    "sos": "SOS",
  };

  // ---------- Visão geral ----------
  function countUp(elId, target) {
    const node = el(elId);
    if (!node) return;
    const start = 0;
    const duration = 700;
    const startTime = performance.now();
    function tick(now) {
      const progress = Math.min(1, (now - startTime) / duration);
      const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
      node.textContent = Math.round(start + (target - start) * eased);
      if (progress < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }

  async function loadOverview() {
    try {
      const stats = await api("/api/admin/stats");

      countUp("statTotalUsers", stats.total_users);
      countUp("statTotalReports", stats.total_reports);
      countUp("statNewUsers", stats.new_users_today);
      countUp("statReports7d", stats.reports_last_7d);

      const maxCat = Math.max(1, ...stats.by_category.map((c) => c.count));
      el("categoryBars").innerHTML = stats.by_category.length
        ? stats.by_category.map((c) => `
            <div class="bar-row">
              <div class="bar-label">${CATEGORY_LABELS[c.category] || c.category}</div>
              <div class="bar-track"><div class="bar-fill" data-target="${(c.count / maxCat) * 100}" style="width:0%"></div></div>
              <div class="bar-count">${c.count}</div>
            </div>`).join("")
        : '<div class="empty-state">Nenhum relato ainda.</div>';

      const riskLabels = { "1": "Baixo", "2": "Médio", "3": "Alto" };
      const riskColors = { "1": "var(--green)", "2": "var(--gold)", "3": "var(--red)" };
      const maxRisk = Math.max(1, ...Object.values(stats.by_risk_level));
      el("riskBars").innerHTML = Object.entries(stats.by_risk_level).map(([level, count]) => `
        <div class="bar-row">
          <div class="bar-label">${riskLabels[level]}</div>
          <div class="bar-track"><div class="bar-fill" data-target="${(count / maxRisk) * 100}" style="width:0%; background:${riskColors[level]}"></div></div>
          <div class="bar-count">${count}</div>
        </div>`).join("");

      // Dispara o crescimento das barras num frame seguinte (senão o navegador não anima a transição)
      requestAnimationFrame(() => {
        document.querySelectorAll(".bar-fill[data-target]").forEach((bar) => {
          bar.style.width = `${bar.dataset.target}%`;
        });
      });

      el("topUsersBody").innerHTML = stats.top_users.length
        ? stats.top_users.map((u) => `
            <tr>
              <td>${u.nome}</td>
              <td><b>${u.xp}</b></td>
              <td>${u.reports_count}</td>
              <td><i class="fa-solid fa-fire" style="color:var(--gold)"></i> ${u.streak_count}</td>
            </tr>`).join("")
        : '<tr><td colspan="4" class="empty-state">Sem usuários ainda.</td></tr>';

      el("recentReportsBody").innerHTML = stats.recent_reports.length
        ? stats.recent_reports.map((r) => `
            <tr>
              <td>${CATEGORY_LABELS[r.category] || r.category || "—"}</td>
              <td><span class="badge-pill risk-${r.risk_level}">${["", "Baixo", "Médio", "Alto"][r.risk_level]}</span></td>
              <td>${r.neighborhood || r.city || "—"}</td>
              <td>${timeAgo(r.created_at)}</td>
            </tr>`).join("")
        : '<tr><td colspan="4" class="empty-state">Sem relatos ainda.</td></tr>';
    } catch (err) {
      showToast(err.message || "Erro ao carregar estatísticas.", "error");
    } finally {
      el("pageLoader").style.display = "none";
    }
  }

  // ---------- Usuários ----------
  let usersPage = 1;
  let usersSearchTimer = null;

  async function loadUsers() {
    const q = el("userSearchInput").value.trim();
    try {
      const data = await api(`/api/admin/users?page=${usersPage}&per_page=15&q=${encodeURIComponent(q)}`);
      const totalPages = Math.max(1, Math.ceil(data.total / data.per_page));
      el("usersPageLabel").textContent = `Página ${data.page} de ${totalPages} (${data.total} usuários)`;
      el("usersPrevBtn").disabled = data.page <= 1;
      el("usersNextBtn").disabled = data.page >= totalPages;

      el("usersBody").innerHTML = data.users.length
        ? data.users.map((u) => `
            <tr data-id="${u.id}">
              <td>${u.nome}</td>
              <td>${u.email}</td>
              <td>${u.xp}</td>
              <td>${u.reports_count}</td>
              <td>${u.streak_count}</td>
              <td><span class="badge-pill ${u.is_active ? "active" : "inactive"}">${u.is_active ? "Ativo" : "Inativo"}</span></td>
              <td>${u.is_admin ? '<span class="badge-pill admin">Admin</span>' : "—"}</td>
              <td>${new Date(u.created_at).toLocaleDateString("pt-BR")}</td>
              <td style="white-space:nowrap;">
                <button class="icon-btn toggle-active" title="Ativar/Desativar"><i class="fa-solid fa-power-off"></i></button>
                <button class="icon-btn toggle-admin" title="Tornar admin/comum"><i class="fa-solid fa-user-shield"></i></button>
                <button class="icon-btn danger delete-user" title="Excluir"><i class="fa-solid fa-trash"></i></button>
              </td>
            </tr>`).join("")
        : '<tr><td colspan="9" class="empty-state">Nenhum usuário encontrado.</td></tr>';

      el("usersBody").querySelectorAll(".toggle-active").forEach((btn) =>
        btn.addEventListener("click", (e) => toggleUserField(e, "is_active"))
      );
      el("usersBody").querySelectorAll(".toggle-admin").forEach((btn) =>
        btn.addEventListener("click", (e) => toggleUserField(e, "is_admin"))
      );
      el("usersBody").querySelectorAll(".delete-user").forEach((btn) =>
        btn.addEventListener("click", (e) => deleteUser(e))
      );
    } catch (err) {
      showToast(err.message || "Erro ao carregar usuários.", "error");
    }
  }

  async function toggleUserField(e, field) {
    const row = e.target.closest("tr");
    const id = row.dataset.id;
    const badge = field === "is_active" ? row.querySelector(".badge-pill.active, .badge-pill.inactive")
                                         : row.querySelector(".badge-pill.admin");
    const currentlyOn = field === "is_active" ? badge.classList.contains("active") : !!badge;
    try {
      await api(`/api/admin/users/${id}`, { method: "PATCH", body: JSON.stringify({ [field]: !currentlyOn }) });
      showToast("Usuário atualizado.", "success");
      loadUsers();
    } catch (err) {
      showToast(err.message || "Erro ao atualizar usuário.", "error");
    }
  }

  async function deleteUser(e) {
    const row = e.target.closest("tr");
    const id = row.dataset.id;
    if (!confirm("Tem certeza que deseja excluir este usuário e todos os seus relatos?")) return;
    try {
      await api(`/api/admin/users/${id}`, { method: "DELETE" });
      showToast("Usuário removido.", "success");
      loadUsers();
    } catch (err) {
      showToast(err.message || "Erro ao remover usuário.", "error");
    }
  }

  el("userSearchInput").addEventListener("input", () => {
    clearTimeout(usersSearchTimer);
    usersSearchTimer = setTimeout(() => { usersPage = 1; loadUsers(); }, 350);
  });
  el("usersPrevBtn").addEventListener("click", () => { if (usersPage > 1) { usersPage--; loadUsers(); } });
  el("usersNextBtn").addEventListener("click", () => { usersPage++; loadUsers(); });

  // ---------- Relatos ----------
  let reportsPage = 1;

  async function loadReports() {
    const category = el("categoryFilter").value;
    const risk = el("riskFilter").value;
    try {
      const params = new URLSearchParams({ page: reportsPage, per_page: 15 });
      if (category) params.set("category", category);
      if (risk) params.set("risk_level", risk);

      const data = await api(`/api/admin/reports?${params.toString()}`);
      const totalPages = Math.max(1, Math.ceil(data.total / data.per_page));
      el("reportsPageLabel").textContent = `Página ${data.page} de ${totalPages} (${data.total} relatos)`;
      el("reportsPrevBtn").disabled = data.page <= 1;
      el("reportsNextBtn").disabled = data.page >= totalPages;

      el("reportsBody").innerHTML = data.reports.length
        ? data.reports.map((r) => `
            <tr data-id="${r.id}">
              <td>#${r.id}</td>
              <td>${r.user_email || "Anônimo"}</td>
              <td>${CATEGORY_LABELS[r.category] || r.category || "—"}</td>
              <td><span class="badge-pill risk-${r.risk_level}">${["", "Baixo", "Médio", "Alto"][r.risk_level]}</span></td>
              <td>${r.neighborhood || r.city || `${r.latitude.toFixed(3)}, ${r.longitude.toFixed(3)}`}</td>
              <td style="max-width:220px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${r.comment || "—"}</td>
              <td>${timeAgo(r.created_at)}</td>
              <td><button class="icon-btn danger delete-report" title="Excluir"><i class="fa-solid fa-trash"></i></button></td>
            </tr>`).join("")
        : '<tr><td colspan="8" class="empty-state">Nenhum relato encontrado.</td></tr>';

      el("reportsBody").querySelectorAll(".delete-report").forEach((btn) =>
        btn.addEventListener("click", async (e) => {
          const row = e.target.closest("tr");
          if (!confirm("Excluir este relato permanentemente?")) return;
          try {
            await api(`/api/admin/reports/${row.dataset.id}`, { method: "DELETE" });
            showToast("Relato removido.", "success");
            loadReports();
          } catch (err) {
            showToast(err.message || "Erro ao remover relato.", "error");
          }
        })
      );
    } catch (err) {
      showToast(err.message || "Erro ao carregar relatos.", "error");
    }
  }

  el("categoryFilter").addEventListener("change", () => { reportsPage = 1; loadReports(); });
  el("riskFilter").addEventListener("change", () => { reportsPage = 1; loadReports(); });
  el("reportsPrevBtn").addEventListener("click", () => { if (reportsPage > 1) { reportsPage--; loadReports(); } });
  el("reportsNextBtn").addEventListener("click", () => { reportsPage++; loadReports(); });

  // ---------- Boot ----------
  loadOverview();
})();
