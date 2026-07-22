/* ============================================================
   WeSafe — Página de perfil (métricas principais do usuário)
   ============================================================ */
(function () {
  "use strict";

  const CFG = window.WESAFE_CONFIG || {};
  const API_BASE = CFG.API_BASE || "";
  const TOKEN = localStorage.getItem("wesafe_token");

  if (!TOKEN) {
    window.location.href = CFG.LOGIN_URL || "/login";
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

  async function authFetch(path, options = {}) {
    const headers = Object.assign({}, options.headers, {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${localStorage.getItem("wesafe_token")}`,
    });
    const resp = await fetch(`${API_BASE}${path}`, { ...options, headers });
    if (resp.status === 401) {
      localStorage.removeItem("wesafe_token");
      localStorage.removeItem("wesafe_user_id");
      window.location.href = CFG.LOGIN_URL || "/login";
      throw new Error("Sessão expirada");
    }
    return resp;
  }

  el("backBtn").addEventListener("click", () => {
    window.location.href = CFG.HOME_URL || "/app";
  });

  el("logoutBtn").addEventListener("click", () => {
    if (!confirm("Deseja sair da sua conta WeSafe?")) return;
    localStorage.removeItem("wesafe_token");
    localStorage.removeItem("wesafe_user_id");
    window.location.href = CFG.ENTRADA_URL || "/";
  });

  function formatMemberSince(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    const meses = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
    return `Guardião da comunidade desde ${meses[d.getMonth()]} de ${d.getFullYear()}`;
  }

  function renderProfile(p) {
    el("profileNome").textContent = p.nome || "Usuário WeSafe";
    el("profileEmail").textContent = p.email || "";
    el("levelBadge").textContent = p.level;

    if (p.badge) {
      el("badgeTag").style.display = "inline-flex";
      el("badgeLabel").textContent = p.badge.label;
    }

    el("xpProgressLabel").textContent = `${p.xp_into_level} / ${p.xp_for_next_level} XP`;
    el("profileXpBar").style.width = `${p.progress_pct || 0}%`;

    el("metricLevel").textContent = p.level;
    el("metricStreak").textContent = p.streak_count;
    el("metricReports").textContent = p.reports_count;
    el("metricXp").textContent = p.xp_total;

    el("memberSince").textContent = formatMemberSince(p.created_at);

    el("loadingState").style.display = "none";
    el("profileContent").style.display = "block";
  }

  async function loadProfile() {
    try {
      const resp = await authFetch("/api/profile");
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "Não foi possível carregar seu perfil.");
      renderProfile(data);
    } catch (err) {
      showToast(err.message || "Erro ao carregar perfil.", "error");
    }
  }

  loadProfile();
})();
