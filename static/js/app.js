/* ============================================================
   WeSafe — App principal (mapa, rotas, denúncias, gamificação)
   ============================================================ */
(function () {
  "use strict";

  const CFG = window.WESAFE_CONFIG || {};
  const API_BASE = CFG.API_BASE || "";
  const TOKEN = localStorage.getItem("wesafe_token");

  // ---------- Guarda de autenticação ----------
  if (!TOKEN) {
    window.location.href = CFG.LOGIN_URL || "/login";
    return;
  }

  if (!CFG.MAPBOX_TOKEN) {
    console.error("MAPBOX_TOKEN não configurado. Defina MAPBOX_TOKEN no .env do servidor.");
  }
  mapboxgl.accessToken = CFG.MAPBOX_TOKEN;

  // ---------- Elementos ----------
  const el = (id) => document.getElementById(id);

  const topBar = el("topBar");
  const searchBar = el("searchBar");
  const mainBottomPanel = el("mainBottomPanel");
  const autocompleteContainer = el("autocompleteContainer");

  const levelValue = el("levelValue");
  const streakValue = el("streakValue");
  const xpBarFill = el("xpBarFill");
  const profileBtn = el("profileBtn");

  const originInput = el("originInput");
  const destinationInput = el("destinationInput");
  const switchBtn = el("switchBtn");

  const locationSelectionPanel = el("locationSelectionPanel");
  const routePanel = el("routePanel");
  const reportPanel = el("reportPanel");
  const goBtnDummy = el("goBtnDummy");

  const routeDistance = el("routeDistance");
  const routeTime = el("routeTime");
  const routeRiskChip = el("routeRiskChip");
  const riskAlert = el("riskAlert");
  const routeToggleRow = el("routeToggleRow");
  const startBtn = el("startBtn");
  const backToSearchBtn = el("backToSearchBtn");

  const reportCloseBtn = el("reportCloseBtn");
  const modeButtons = document.querySelectorAll(".mode-btn");
  const modeRow = el("modeRow");

  const centerBtn = el("centerBtn");
  const alertBtn = el("navAlertBtn") || el("alertBtn");
  const sosBtn = el("navSosBtn") || el("sosBtn");
  const endNavigationBtn = el("endNavigationBtn");
  const appNavbar = el("appNavbar");

  const speedometer = el("speedometer");
  const currentSpeedEl = el("currentSpeed");
  const speedLimitEl = el("speedLimit");
  const navProgress = el("navProgress");

  const xpToast = el("xpToast");
  const xpToastMsg = el("xpToastMsg");
  const levelupOverlay = el("levelupOverlay");
  const levelupText = el("levelupText");
  const levelupCloseBtn = el("levelupCloseBtn");

  // ---------- Estado ----------
  let userCoords = null;      // [lng, lat]
  let destCoords = null;      // [lng, lat]
  let currentProfile = "driving";
  let lastRouteResult = null; // resposta completa de /api/safe_route
  let selectedChoice = "safest"; // "safest" | "balanced" | "fastest"
  let isNavigating = false;
  let navTimer = null;
  let navRouteCoords = null;
  let navSteps = [];
  let navStepIndex = 0;
  let navIndex = 0;
  let watchId = null;
  let heatmapOn = false;
  let satelliteOn = false;

  function routeByChoice(choice) {
    if (!lastRouteResult) return null;
    if (choice === "fastest") return lastRouteResult.fastest_route;
    if (choice === "balanced") return lastRouteResult.balanced_route;
    return lastRouteResult.safest_route || lastRouteResult.recommended_route;
  }

  // ---------- Helpers de UI ----------
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

  function showXpToast(msg) {
    xpToastMsg.textContent = msg;
    xpToast.classList.add("show");
    clearTimeout(window._xpTimeout);
    window._xpTimeout = setTimeout(() => xpToast.classList.remove("show"), 2600);
  }

  function showPanel(name) {
    locationSelectionPanel.classList.remove("active");
    routePanel.classList.remove("active");
    reportPanel.classList.remove("active");
    if (name === "locationSelection") locationSelectionPanel.classList.add("active");
    if (name === "route") routePanel.classList.add("active");
    if (name === "report") reportPanel.classList.add("active");
    // O seletor de carro/bike/a pé fica visível em qualquer estado, exceto
    // enquanto o usuário está registrando uma denúncia.
    if (modeRow) modeRow.classList.toggle("hidden-row", name === "report");
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

  // ---------- Perfil / gamificação ----------
  function renderProfile(profile) {
    if (!profile) return;
    levelValue.textContent = profile.level;
    streakValue.textContent = profile.streak_count;
    xpBarFill.style.width = `${profile.progress_pct || 0}%`;
  }

  async function loadProfile() {
    try {
      const resp = await authFetch("/api/profile");
      if (!resp.ok) return;
      const profile = await resp.json();
      renderProfile(profile);
    } catch (e) { /* já tratado em authFetch */ }
  }

  const CONFETTI_COLORS = ["#ff8c1f", "#ffc800", "#8b5cf6", "#58cc02", "#ff4b4b"];
  function fireConfetti() {
    const burst = el("confettiBurst");
    if (!burst) return;
    burst.innerHTML = "";
    for (let i = 0; i < 26; i++) {
      const piece = document.createElement("span");
      piece.className = "confetti-piece";
      const angle = Math.random() * Math.PI * 2;
      const distance = 70 + Math.random() * 90;
      piece.style.setProperty("--cx", `${Math.cos(angle) * distance}px`);
      piece.style.setProperty("--cy", `${Math.sin(angle) * distance - 40}px`);
      piece.style.setProperty("--cr", `${Math.round(Math.random() * 480)}deg`);
      piece.style.background = CONFETTI_COLORS[i % CONFETTI_COLORS.length];
      piece.style.animationDelay = `${Math.random() * 120}ms`;
      burst.appendChild(piece);
    }
  }

  function applyGamification(gam) {
    if (!gam) return;
    renderProfile(gam.profile);
    let msg = `+${gam.xp_gained} XP pelo relato!`;
    if (gam.streak_bonus > 0) msg += ` (+${gam.streak_bonus} bônus de sequência)`;
    showXpToast(msg);

    if (gam.leveled_up) {
      setTimeout(() => {
        levelupText.textContent = `Agora você é nível ${gam.profile.level}. Continue protegendo a comunidade.`;
        levelupOverlay.classList.add("show");
        fireConfetti();
      }, 700);
    }
  }

  levelupCloseBtn.addEventListener("click", () => levelupOverlay.classList.remove("show"));

  profileBtn.addEventListener("click", () => {
    window.location.href = CFG.PERFIL_URL || "/perfil";
  });
  const navProfileBtn = el("navProfileBtn");
  if (navProfileBtn) {
    navProfileBtn.addEventListener("click", () => {
      window.location.href = CFG.PERFIL_URL || "/perfil";
    });
  }

  // ---------- Mapa ----------
  const map = new mapboxgl.Map({
    container: "map",
    style: CFG.MAPBOX_STYLE || "mapbox://styles/miguwl0287/cmixney1h001501s111340npb",
    center: [-46.6333, -23.5505],
    zoom: 13,
  });

  map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "bottom-right");

  // ---------- Modo "seguir usuário" ----------
  // O mapa fica travado na localização do usuário até que ele interaja manualmente
  // (arrastar, girar ou dar zoom com o dedo/mouse). O botão de centralizar reativa o modo.
  let followUser = true;
  ["dragstart", "rotatestart", "pitchstart"].forEach((evt) => {
    map.on(evt, (e) => {
      if (e.originalEvent) followUser = false; // só desativa em interação humana, não em flyTo/easeTo programático
    });
  });
  map.on("wheel", () => { followUser = false; });
  map.on("touchstart", (e) => {
    if (e.points && e.points.length > 1) followUser = false; // pinch-zoom manual
  });

  let userMarker = null;
  let userMarkerArrow = null;
  const hotspotMarkers = [];

  function buildDestMarkerEl() {
    const wrap = document.createElement("div");
    wrap.className = "dest-marker-wrap";
    wrap.innerHTML = `
      <div class="dest-marker-pin"><i class="fa-solid fa-flag-checkered"></i></div>
      <div class="dest-marker-shadow"></div>`;
    return wrap;
  }
  const destMarker = new mapboxgl.Marker({ element: buildDestMarkerEl(), anchor: "bottom" });

  function setDestinationMarker(lngLat) {
    if (!lngLat) {
      destMarker.remove();
      return;
    }
    destMarker.setLngLat(lngLat).addTo(map);
  }

  // Trilha real percorrida durante a navegação (cresce a cada atualização de GPS)
  let traveledCoords = [];
  let lastFixCoords = null;
  let lastFixTimestamp = null;
  let lastHeading = 0;
  let lastFollowEase = 0;

  function clearHotspotMarkers() {
    hotspotMarkers.forEach((m) => m.remove());
    hotspotMarkers.length = 0;
  }

  function buildHotspotEl(riskScore) {
    const isHigh = riskScore >= 8;
    const isMod = !isHigh && riskScore >= 6.5;
    const level = isHigh ? "high" : isMod ? "moderate" : "low";
    const icon = isHigh ? "fa-triangle-exclamation" : isMod ? "fa-circle-exclamation" : "fa-eye";
    const wrap = document.createElement("div");
    wrap.className = `hotspot-marker-wrap ${level}`;
    wrap.innerHTML = `<div class="hotspot-marker-dot"><i class="fa-solid ${icon}"></i></div>`;
    return wrap;
  }

  function paintHotspots(hotspots) {
    clearHotspotMarkers();
    (hotspots || []).forEach((h) => {
      const m = new mapboxgl.Marker({ element: buildHotspotEl(h.risk_score) })
        .setLngLat([h.lng, h.lat])
        .setPopup(new mapboxgl.Popup({ offset: 16 }).setText(`⚠ Trecho de risco: ${h.risk_score.toFixed(1)}/10`))
        .addTo(map);
      hotspotMarkers.push(m);
    });
  }

  // Distância em metros entre dois pontos [lng, lat] (Haversine)
  function haversineM(a, b) {
    const R = 6371000;
    const toRad = (d) => (d * Math.PI) / 180;
    const dLat = toRad(b[1] - a[1]);
    const dLng = toRad(b[0] - a[0]);
    const s = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a[1])) * Math.cos(toRad(b[1])) * Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.atan2(Math.sqrt(s), Math.sqrt(1 - s));
  }

  // Direção (graus, 0 = norte) entre dois pontos [lng, lat]
  function bearingBetween(a, b) {
    const toRad = (d) => (d * Math.PI) / 180;
    const toDeg = (r) => (r * 180) / Math.PI;
    const y = Math.sin(toRad(b[0] - a[0])) * Math.cos(toRad(b[1]));
    const x = Math.cos(toRad(a[1])) * Math.sin(toRad(b[1])) -
      Math.sin(toRad(a[1])) * Math.cos(toRad(b[1])) * Math.cos(toRad(b[0] - a[0]));
    return (toDeg(Math.atan2(y, x)) + 360) % 360;
  }

  function buildUserMarkerEl() {
    const wrap = document.createElement("div");
    wrap.className = "user-marker-wrap";
    wrap.innerHTML = `
      <div class="user-marker-pulse"></div>
      <div class="user-marker-dot">
        <i class="fa-solid fa-location-arrow user-marker-arrow" id="userMarkerArrowIcon"></i>
      </div>`;
    return wrap;
  }

  function setUserLocation(lngLat, { fly = false, heading = null } = {}) {
    userCoords = lngLat;
    if (!userMarker) {
      const wrap = buildUserMarkerEl();
      userMarkerArrow = wrap.querySelector("#userMarkerArrowIcon");
      userMarker = new mapboxgl.Marker({ element: wrap, rotationAlignment: "map" }).setLngLat(lngLat).addTo(map);
    } else {
      userMarker.setLngLat(lngLat);
    }
    if (heading !== null && !Number.isNaN(heading) && userMarkerArrow) {
      lastHeading = heading;
      userMarkerArrow.style.transform = `rotate(${heading}deg)`;
    }
    if (fly) map.flyTo({ center: lngLat, zoom: 15, essential: true });
  }

  function initGeolocation() {
    if (!("geolocation" in navigator)) {
      showToast("Geolocalização não disponível neste dispositivo.", "error");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => setUserLocation([pos.coords.longitude, pos.coords.latitude], { fly: true }),
      () => showToast("Não foi possível obter sua localização.", "error"),
      { enableHighAccuracy: true, timeout: 8000 }
    );

    watchId = navigator.geolocation.watchPosition(handlePositionUpdate, () => {}, {
      enableHighAccuracy: true,
      maximumAge: 2000,
      timeout: 10000,
    });
  }

  // ---------- Processa cada nova posição real do GPS ----------
  function handlePositionUpdate(pos) {
    const lngLat = [pos.coords.longitude, pos.coords.latitude];
    const now = pos.timestamp || Date.now();

    // Direção: usa a bússola do dispositivo se disponível, senão calcula pelo deslocamento.
    let heading = typeof pos.coords.heading === "number" && !Number.isNaN(pos.coords.heading)
      ? pos.coords.heading
      : (lastFixCoords ? bearingBetween(lastFixCoords, lngLat) : lastHeading);

    setUserLocation(lngLat, { heading });

    // Fora da navegação: mantém a câmera centralizada no usuário enquanto o modo "seguir" estiver ativo.
    if (!isNavigating && followUser) {
      const nowTs = Date.now();
      if (!lastFollowEase || nowTs - lastFollowEase > 1200) {
        lastFollowEase = nowTs;
        map.easeTo({ center: lngLat, duration: 900 });
      }
    }

    if (isNavigating) {
      // Só registra o ponto na trilha se houve deslocamento real perceptível (evita ruído de GPS parado)
      const movedEnough = !traveledCoords.length || haversineM(traveledCoords[traveledCoords.length - 1], lngLat) > 3;
      if (movedEnough) {
        traveledCoords.push(lngLat);
        setRouteData("user-trail", traveledCoords);
      }

      // Velocidade real: usa coords.speed (m/s) quando disponível, senão estima pelo deslocamento/tempo.
      let speedKmh = 0;
      if (typeof pos.coords.speed === "number" && pos.coords.speed >= 0) {
        speedKmh = Math.round(pos.coords.speed * 3.6);
      } else if (lastFixCoords && lastFixTimestamp) {
        const dtSec = (now - lastFixTimestamp) / 1000;
        if (dtSec > 0) {
          const distM = haversineM(lastFixCoords, lngLat);
          speedKmh = Math.round((distM / dtSec) * 3.6);
        }
      }
      currentSpeedEl.textContent = speedKmh;
      const limit = currentProfile === "driving" ? 60 : currentProfile === "cycling" ? 25 : 6;
      speedLimitEl.textContent = `Limite: ${limit} km/h`;
      speedometer.classList.toggle("overspeed", speedKmh > limit);

      map.easeTo({ center: lngLat, bearing: heading, pitch: 55, zoom: 17, duration: 700 });
      updateNavProgress(lngLat);
      updateNextStepDistance(lngLat);

      // Chegada: dentro de 25m do destino encerra a navegação com sucesso.
      const destPoint = navRouteCoords && navRouteCoords[navRouteCoords.length - 1];
      if (destPoint && haversineM(lngLat, destPoint) < 25) {
        endNavigation(true);
      }
    }

    lastFixCoords = lngLat;
    lastFixTimestamp = now;
  }

  // ---------- Botão "Buscar rota" (antes ficava sempre travado/inerte) ----------
  function updateGoButtonState() {
    if (!goBtnDummy) return;
    if (destCoords) {
      goBtnDummy.disabled = false;
      goBtnDummy.innerHTML = '<i class="fa-solid fa-route"></i> Buscar rota segura';
    } else {
      goBtnDummy.disabled = true;
      goBtnDummy.innerHTML = '<i class="fa-solid fa-route"></i> Digite um destino';
    }
  }

  goBtnDummy.addEventListener("click", () => {
    if (destCoords) {
      requestRoute();
    } else {
      destinationInput.focus();
    }
  });

  // ---------- Autocomplete de destino (Mapbox Geocoding API) ----------
  let autocompleteTimer = null;
  let lastAutocompleteFeatures = [];

  async function handleAutocomplete() {
    const query = destinationInput.value.trim();
    if (query.length < 3) {
      autocompleteContainer.classList.add("hidden-panel");
      return;
    }
    clearTimeout(autocompleteTimer);
    autocompleteTimer = setTimeout(async () => {
      try {
        const params = new URLSearchParams({
          access_token: CFG.MAPBOX_TOKEN,
          language: "pt",
          country: "br",
          limit: "5",
          types: "address,poi,place,neighborhood",
        });
        if (userCoords) params.set("proximity", `${userCoords[0]},${userCoords[1]}`);

        const resp = await fetch(
          `https://api.mapbox.com/geocoding/v5/mapbox.places/${encodeURIComponent(query)}.json?${params.toString()}`
        );
        const data = await resp.json();

        autocompleteContainer.innerHTML = "";
        const features = data.features || [];
        lastAutocompleteFeatures = features;
        if (!features.length) {
          autocompleteContainer.classList.add("hidden-panel");
          return;
        }

        features.forEach((feature) => {
          const item = document.createElement("div");
          item.className = "autocomplete-item";
          const isPOI = (feature.place_type || []).includes("poi");
          const main = feature.text || feature.place_name;
          const secondary = (feature.place_name || "").replace(`${main}, `, "");
          item.innerHTML = `
            <div class="autocomplete-item-top">
              <i class="fa-solid ${isPOI ? "fa-store" : "fa-location-dot"} autocomplete-item-icon"></i>
              <span>${main}</span>
            </div>
            <div class="autocomplete-item-secondary">${secondary}</div>
          `;
          item.addEventListener("click", () => selectDestination(feature));
          autocompleteContainer.appendChild(item);
        });
        autocompleteContainer.classList.remove("hidden-panel");
      } catch (e) {
        console.error("Erro no autocompletar:", e);
      }
    }, 280);
  }

  function selectDestination(feature) {
    destinationInput.value = feature.place_name || feature.text;
    destCoords = feature.center; // [lng, lat]
    setDestinationMarker(destCoords);
    autocompleteContainer.classList.add("hidden-panel");
    updateGoButtonState();
    requestRoute();
  }

  destinationInput.addEventListener("input", () => {
    // Se o usuário editar o texto manualmente, o destino anterior deixa de valer
    // até que ele escolha uma nova sugestão (evita buscar rota para um endereço "fantasma").
    destCoords = null;
    setDestinationMarker(null);
    updateGoButtonState();
    handleAutocomplete();
  });
  destinationInput.addEventListener("focus", handleAutocomplete);
  destinationInput.addEventListener("blur", () =>
    setTimeout(() => autocompleteContainer.classList.add("hidden-panel"), 200)
  );
  destinationInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      if (lastAutocompleteFeatures.length) selectDestination(lastAutocompleteFeatures[0]);
    }
  });

  switchBtn.addEventListener("click", () => {
    const originVal = originInput.value;
    const destVal = destinationInput.value;
    originInput.value = destVal || "Minha Localização";
    destinationInput.value = originVal === "Minha Localização" ? "" : originVal;
    const tmp = userCoords;
    if (destCoords) userCoords = destCoords;
    destCoords = tmp;
    setDestinationMarker(destCoords);
    updateGoButtonState();
    if (destCoords) requestRoute();
  });

  modeButtons.forEach((btn) =>
    btn.addEventListener("click", () => {
      if (btn.classList.contains("active") || isNavigating) return;
      modeButtons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentProfile = btn.getAttribute("data-profile");
      if (destCoords) requestRoute();
    })
  );

  // ---------- Rotas (via backend: OSRM real + risco calculado das denuncias) ----------

  // Converte um risco 0-10 em cor (verde seguro -> amarelo -> vermelho perigoso)
  function riskToColor(score) {
    if (score >= 7) return "#ff4b4b";
    if (score >= 4) return "#ffc800";
    if (score >= 1.2) return "#a7d94a";
    return "#58cc02";
  }

  // Constroi a expressao de gradiente do Mapbox a partir do "risk_profile" devolvido pelo backend
  function buildRiskGradient(riskProfile) {
    const stops = [];
    const profile = (riskProfile && riskProfile.length) ? riskProfile : [{ t: 0, risk: 0 }, { t: 1, risk: 0 }];
    let lastT = -1;
    profile.forEach((p) => {
      let t = Math.max(0, Math.min(1, p.t));
      if (t <= lastT) t = Math.min(1, lastT + 0.0001);
      stops.push(t, riskToColor(p.risk));
      lastT = t;
    });
    if (stops[0] !== 0) { stops.unshift(riskToColor(profile[0].risk)); stops.unshift(0); }
    return ["interpolate", ["linear"], ["line-progress"], ...stops];
  }

  function ensureRouteLayers() {
    // Rota ATIVA (a escolhida no momento) - colorida com gradiente de risco real ao longo do trajeto,
    // como uma "faixa de seguranca" (analoga a faixa de transito do Google Maps, so que para perigo).
    if (!map.getSource("route-active")) {
      map.addSource("route-active", {
        type: "geojson",
        lineMetrics: true,
        data: { type: "Feature", geometry: { type: "LineString", coordinates: [] } },
      });
      map.addLayer({
        id: "route-active-casing", type: "line", source: "route-active",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": "#05070a", "line-width": 11, "line-opacity": 0.38 },
      });
      map.addLayer({
        id: "route-active-layer", type: "line", source: "route-active",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-width": 6.5, "line-gradient": ["interpolate", ["linear"], ["line-progress"], 0, "#58cc02", 1, "#58cc02"] },
      });
    }

    // Rotas alternativas (as 2 opcoes nao escolhidas) - linhas finas e tracejadas, clicaveis p/ trocar.
    ["route-alt-a", "route-alt-b"].forEach((id) => {
      if (!map.getSource(id)) {
        map.addSource(id, { type: "geojson", data: { type: "Feature", geometry: { type: "LineString", coordinates: [] }, properties: {} } });
        map.addLayer({
          id: `${id}-layer`, type: "line", source: id,
          layout: { "line-join": "round", "line-cap": "round" },
          paint: { "line-color": "#a7abb8", "line-width": 4.2, "line-opacity": 0.6, "line-dasharray": [0.2, 1.6] },
        });
        map.on("click", `${id}-layer`, () => {
          const choice = map.getSource(id)._choice;
          if (choice) selectRouteChoice(choice);
        });
        map.on("mouseenter", `${id}-layer`, () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", `${id}-layer`, () => { map.getCanvas().style.cursor = ""; });
      }
    });

    // Camada de "fluxo" animado sobre a rota recomendada — dá sensação de rota viva/em movimento
    if (!map.getSource("route-flow")) {
      map.addSource("route-flow", { type: "geojson", data: { type: "Feature", geometry: { type: "LineString", coordinates: [] } } });
      map.addLayer({
        id: "route-flow-layer",
        type: "line",
        source: "route-flow",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: { "line-color": "#ffe066", "line-width": 3.4, "line-opacity": 0.9 },
      });
      startRouteFlowAnimation();
    }

    // Trilha do trajeto já percorrido (GPS real) — fica por cima das rotas planejadas
    if (!map.getSource("user-trail")) {
      map.addSource("user-trail", { type: "geojson", data: { type: "Feature", geometry: { type: "LineString", coordinates: [] } } });
      map.addLayer({
        id: "user-trail-layer",
        type: "line",
        source: "user-trail",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: {
          "line-color": "#8b5cf6",
          "line-width": 6,
          "line-opacity": 0.95,
        },
      });
    }
  }

  // Animação "formiguinhas" leve (dash-array cíclico) para dar sensação de rota viva/em movimento
  let routeFlowFrame = null;
  const FLOW_DASH_STEPS = [
    [0, 4, 3], [0.5, 4, 2.5], [1, 4, 2], [1.5, 4, 1.5],
    [2, 4, 1], [2.5, 4, 0.5], [3, 4, 0], [0, 0.5, 3, 3.5],
    [0, 1, 3, 3], [0, 1.5, 3, 2.5],
  ];
  function startRouteFlowAnimation() {
    if (routeFlowFrame) return;
    let step = 0;
    let lastTick = 0;
    function tick(ts) {
      routeFlowFrame = requestAnimationFrame(tick);
      if (ts - lastTick < 80) return; // ~12fps é suficiente para o efeito, economiza CPU
      lastTick = ts;
      if (!map.getLayer("route-flow-layer")) return;
      step = (step + 1) % FLOW_DASH_STEPS.length;
      map.setPaintProperty("route-flow-layer", "line-dasharray", FLOW_DASH_STEPS[step]);
    }
    routeFlowFrame = requestAnimationFrame(tick);
  }

  function setRouteData(id, coords) {
    const source = map.getSource(id);
    if (source) {
      source.setData({ type: "Feature", geometry: { type: "LineString", coordinates: coords || [] } });
    }
  }

  function fitToCoords(coords) {
    if (!coords || !coords.length) return;
    const bounds = coords.reduce(
      (b, c) => b.extend(c),
      new mapboxgl.LngLatBounds(coords[0], coords[0])
    );
    map.fitBounds(bounds, { padding: { top: 220, bottom: 260, left: 50, right: 50 }, duration: 900 });
  }

  // Converte um número de minutos restantes em horário estimado de chegada ("Chegada às 14:32")
  function formatArrivalClock(minutesFromNow) {
    const arrival = new Date(Date.now() + minutesFromNow * 60000);
    const hh = String(arrival.getHours()).padStart(2, "0");
    const mm = String(arrival.getMinutes()).padStart(2, "0");
    return `${hh}:${mm}`;
  }

  function riskChipClass(score) {
    if (score >= 7) return "chip-high";
    if (score >= 4) return "chip-mod";
    if (score >= 0) return "chip-low";
    return "chip-na";
  }

  function formatMinutes(sec) { return Math.max(1, Math.round(sec / 60)); }

  function updateRoutePanel() {
    if (!lastRouteResult) return;
    const chosen = routeByChoice(selectedChoice);
    if (!chosen) return;

    const durationSec = chosen.duration_in_traffic || chosen.duration;
    const durationMin = formatMinutes(durationSec);
    routeDistance.textContent = `${(chosen.distance / 1000).toFixed(1)} km`;
    routeTime.textContent = `${durationMin} min`;
    const routeEtaEl = el("routeEta");
    if (routeEtaEl) routeEtaEl.innerHTML = `<i class="fa-solid fa-flag-checkered"></i> Chegada as ${formatArrivalClock(durationMin)}`;

    routeRiskChip.className = `route-risk-chip ${riskChipClass(chosen.risk_score)}`;
    routeRiskChip.textContent = `SEGURANCA ${Math.round(chosen.safety_score != null ? chosen.safety_score : (100 - chosen.risk_score * 10))}%`;

    riskAlert.className = "risk-alert";
    if (chosen.risk_score >= 7) {
      riskAlert.classList.add("high");
      riskAlert.innerHTML = '<i class="fa-solid fa-triangle-exclamation"></i> Rota com trechos de alto risco. Prefira a opcao "Mais segura".';
      riskAlert.style.display = "flex";
    } else if (chosen.risk_score >= 4) {
      riskAlert.classList.add("moderate");
      riskAlert.innerHTML = '<i class="fa-solid fa-circle-exclamation"></i> Atencao redobrada em alguns trechos desta rota.';
      riskAlert.style.display = "flex";
    } else {
      riskAlert.style.display = "none";
    }

    // ---------- Cards comparativos das 3 opcoes (segura / equilibrada / rapida) ----------
    const modes = [
      { key: "safest", route: lastRouteResult.safest_route, icon: "fa-shield-halved", label: "Mais segura" },
      { key: "balanced", route: lastRouteResult.balanced_route, icon: "fa-scale-balanced", label: "Equilibrada" },
      { key: "fastest", route: lastRouteResult.fastest_route, icon: "fa-bolt", label: "Mais rapida" },
    ];
    routeToggleRow.innerHTML = modes.map((m) => {
      if (!m.route) return "";
      const mins = formatMinutes(m.route.duration_in_traffic || m.route.duration);
      const km = (m.route.distance / 1000).toFixed(1);
      const active = selectedChoice === m.key ? "active" : "";
      return `<button class="route-toggle-btn ${active}" data-choice="${m.key}">
                <i class="fa-solid ${m.icon}"></i>
                <span class="route-toggle-label">${m.label}</span>
                <span class="route-toggle-meta">${mins} min &middot; ${km} km</span>
              </button>`;
    }).join("");
    routeToggleRow.style.display = "flex";
    routeToggleRow.querySelectorAll(".route-toggle-btn").forEach((btn) => {
      btn.addEventListener("click", () => selectRouteChoice(btn.getAttribute("data-choice")));
    });

    // Rota ativa: gradiente de risco real ao longo do trajeto
    const activeSource = map.getSource("route-active");
    if (activeSource) activeSource.setData({ type: "Feature", geometry: { type: "LineString", coordinates: chosen.coords } });
    if (map.getLayer("route-active-layer")) {
      map.setPaintProperty("route-active-layer", "line-gradient", buildRiskGradient(chosen.risk_profile));
    }

    // As outras 2 rotas viram linhas de comparacao tracejadas (clicaveis)
    const others = modes.filter((m) => m.key !== selectedChoice && m.route && m.route.id !== chosen.id);
    ["route-alt-a", "route-alt-b"].forEach((id, i) => {
      const src = map.getSource(id);
      if (!src) return;
      const other = others[i];
      if (other) {
        src.setData({ type: "Feature", geometry: { type: "LineString", coordinates: other.route.coords }, properties: {} });
        src._choice = other.key;
      } else {
        src.setData({ type: "Feature", geometry: { type: "LineString", coordinates: [] }, properties: {} });
        src._choice = null;
      }
    });

    setRouteData("route-flow", chosen.coords);
    paintHotspots(chosen.hotspots);
    fitToCoords(chosen.coords);
  }

  function selectRouteChoice(choice) {
    if (!choice) return;
    selectedChoice = choice;
    updateRoutePanel();
  }

  async function requestRoute() {
    if (!userCoords || !destCoords) return;

    goBtnDummy.disabled = true;
    goBtnDummy.innerHTML = '<span class="spinner" style="border-top-color:#1a0e00;"></span> Calculando rota segura...';

    try {
      const params = new URLSearchParams({
        o_lat: userCoords[1],
        o_lng: userCoords[0],
        d_lat: destCoords[1],
        d_lng: destCoords[0],
        profile: currentProfile,
      });
      const resp = await fetch(`${API_BASE}/api/safe_route?${params.toString()}`);
      const data = await resp.json();

      if (!resp.ok) throw new Error(data.error || "Não foi possível calcular a rota.");

      lastRouteResult = data;
      selectedChoice = "safest";

      ensureRouteLayers();
      updateRoutePanel();
      showPanel("route");
    } catch (err) {
      showToast(err.message || "Erro ao calcular rota.", "error");
    } finally {
      updateGoButtonState();
    }
  }

  backToSearchBtn.addEventListener("click", () => {
    showPanel("locationSelection");
  });

  // ---------- Navegação (real, guiada por GPS) ----------
  const navRemainingDistance = el("navRemainingDistance");
  const navEta = el("navEta");

  function updateNavProgress(currentLngLat) {
    if (!navRouteCoords || !navRouteCoords.length) return;
    const destPoint = navRouteCoords[navRouteCoords.length - 1];
    const remainingM = haversineM(currentLngLat, destPoint);
    if (navRemainingDistance) {
      navRemainingDistance.textContent = remainingM >= 1000
        ? `${(remainingM / 1000).toFixed(1)} km restantes`
        : `${Math.round(remainingM)} m restantes`;
    }
    if (navEta) {
      const speedRef = currentProfile === "driving" ? 30 : currentProfile === "cycling" ? 15 : 4.5; // km/h típico
      const etaMin = Math.max(1, Math.round((remainingM / 1000) / speedRef * 60));
      navEta.textContent = `~${etaMin} min · chegada às ${formatArrivalClock(etaMin)}`;
    }
  }

  function startNavigation() {
    const chosen = routeByChoice(selectedChoice);
    if (!chosen || !chosen.coords || chosen.coords.length < 2) {
      showToast("Rota indisponivel para navegacao.", "error");
      return;
    }

    isNavigating = true;
    navRouteCoords = chosen.coords;
    navSteps = chosen.steps || [];
    navStepIndex = 0;
    navIndex = 0;

    // Reinicia a trilha do trajeto: comeca no ponto atual do usuario (GPS real)
    traveledCoords = userCoords ? [userCoords] : [];
    ensureRouteLayers();
    setRouteData("user-trail", traveledCoords);

    topBar.classList.add("slide-up");
    searchBar.classList.add("slide-up");
    mainBottomPanel.classList.add("slide-down");
    if (appNavbar) appNavbar.classList.add("slide-down");
    speedometer.classList.add("show");
    if (navProgress) navProgress.classList.add("show");
    endNavigationBtn.style.display = "flex";
    if (el("mapControls")) el("mapControls").classList.add("nav-mode");
    updateNextStepPanel();

    const startCenter = userCoords || navRouteCoords[0];
    map.flyTo({ center: startCenter, zoom: 17, pitch: 55, essential: true });
    if (userCoords) updateNavProgress(userCoords);
  }

  // ---------- Instrucoes passo-a-passo (turn-by-turn, estilo Google Maps) ----------
  const nextStepPanelEl = el("nextStepPanel");
  const nextStepIconEl = el("nextStepIcon");
  const nextStepTextEl = el("nextStepText");
  const nextStepDistEl = el("nextStepDistance");

  const STEP_ICON_MAP = {
    "turn-left": "fa-arrow-left", "turn-right": "fa-arrow-right",
    "turn-sharp-left": "fa-share", "turn-sharp-right": "fa-share",
    "turn-slight-left": "fa-arrow-turn-up", "turn-slight-right": "fa-arrow-turn-up",
    "straight": "fa-arrow-up", "rotate": "fa-rotate-left", "flag": "fa-flag-checkered",
  };

  function updateNextStepPanel() {
    if (!nextStepPanelEl) return;
    if (!navSteps.length || navStepIndex >= navSteps.length) {
      nextStepPanelEl.classList.remove("show");
      return;
    }
    const step = navSteps[navStepIndex];
    const iconClass = STEP_ICON_MAP[step.icon] || "fa-arrow-up";
    if (nextStepIconEl) nextStepIconEl.className = `fa-solid ${iconClass}`;
    if (nextStepTextEl) nextStepTextEl.textContent = step.instruction;
    nextStepPanelEl.classList.add("show");
  }

  function updateNextStepDistance(currentLngLat) {
    if (!navSteps.length || navStepIndex >= navSteps.length) return;
    const step = navSteps[navStepIndex];
    if (!step.location || step.location.length < 2) return;
    const distM = haversineM(currentLngLat, step.location);
    if (nextStepDistEl) {
      nextStepDistEl.textContent = distM >= 1000 ? `${(distM / 1000).toFixed(1)} km` : `${Math.round(distM)} m`;
    }
    if (distM < 25 && navStepIndex < navSteps.length - 1) {
      navStepIndex += 1;
      updateNextStepPanel();
    }
  }

  function endNavigation(completed = false) {
    isNavigating = false;

    topBar.classList.remove("slide-up");
    searchBar.classList.remove("slide-up");
    mainBottomPanel.classList.remove("slide-down");
    if (appNavbar) appNavbar.classList.remove("slide-down");
    speedometer.classList.remove("show", "overspeed");
    if (navProgress) navProgress.classList.remove("show");
    endNavigationBtn.style.display = "none";
    if (el("mapControls")) el("mapControls").classList.remove("nav-mode");
    map.setPitch(0);

    if (completed) {
      showToast("Você chegou ao destino com segurança! 🎉", "success");
    }
    showPanel("locationSelection");
    destinationInput.value = "";
    destCoords = null;
    setDestinationMarker(null);
    navRouteCoords = null;
    traveledCoords = [];
    setRouteData("user-trail", []);
    setRouteData("route-flow", []);
    setRouteData("route-active", []);
    setRouteData("route-alt-a", []);
    setRouteData("route-alt-b", []);
    if (nextStepPanelEl) nextStepPanelEl.classList.remove("show");
    navSteps = [];
    navStepIndex = 0;
    updateGoButtonState();
  }

  startBtn.addEventListener("click", () => {
    if (isNavigating) return;
    startBtn.classList.add("loading");
    startBtn.innerHTML = '<span class="spinner" style="border-top-color:#063d00;"></span> Iniciando...';
    setTimeout(() => {
      startBtn.classList.remove("loading");
      startBtn.innerHTML = '<i class="fa-solid fa-location-arrow"></i> Iniciar navegação';
      startNavigation();
    }, 700);
  });

  endNavigationBtn.addEventListener("click", () => endNavigation(false));

  // ---------- Denúncias ----------
  function setActiveNavBtn(activeEl) {
    document.querySelectorAll(".nav-btn").forEach((b) => b.classList.remove("active"));
    if (activeEl) activeEl.classList.add("active");
  }

  alertBtn.addEventListener("click", () => {
    if (!userCoords) {
      showToast("Aguardando sua localização GPS.", "error");
      return;
    }
    showPanel("report");
    setActiveNavBtn(alertBtn);
  });

  reportCloseBtn.addEventListener("click", () => {
    showPanel(destCoords ? "route" : "locationSelection");
    setActiveNavBtn(centerBtn);
  });

  document.querySelectorAll(".report-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const category = btn.getAttribute("data-category");
      const severity = parseInt(btn.getAttribute("data-severity"), 10);
      if (!userCoords) return;

      btn.disabled = true;
      try {
        const resp = await authFetch("/api/report", {
          method: "POST",
          body: JSON.stringify({
            latitude: userCoords[1],
            longitude: userCoords[0],
            risk_level: severity,
            category,
            comment: `Relato de ${category.replace(/-/g, " ")} via app`,
          }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || "Não foi possível enviar o relato.");

        showToast("Relato enviado! Obrigado por proteger a comunidade.", "success");
        applyGamification(data.gamification);
        showPanel(destCoords ? "route" : "locationSelection");
        if (destCoords) requestRoute();
      } catch (err) {
        showToast(err.message || "Erro ao enviar relato.", "error");
      } finally {
        btn.disabled = false;
      }
    });
  });

  sosBtn.addEventListener("click", async () => {
    if (!userCoords) {
      showToast("Aguardando sua localização GPS.", "error");
      return;
    }
    if (!confirm("Enviar um alerta SOS de emergência para a comunidade nesta localização?")) return;

    try {
      const resp = await authFetch("/api/report", {
        method: "POST",
        body: JSON.stringify({
          latitude: userCoords[1],
          longitude: userCoords[0],
          risk_level: 3,
          category: "sos",
          comment: "Alerta SOS enviado pelo usuário",
        }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "Não foi possível enviar o SOS.");
      showToast("Alerta SOS enviado. Fique em segurança!", "success");
      applyGamification(data.gamification);
    } catch (err) {
      showToast(err.message || "Erro ao enviar SOS.", "error");
    }
  });

  centerBtn.addEventListener("click", () => {
    followUser = true;
    setActiveNavBtn(centerBtn);
    if (userCoords) map.flyTo({ center: userCoords, zoom: isNavigating ? 17 : 15, essential: true });
    else showToast("Localização não disponível.", "error");
  });

  // ---------- Controles estilo Google Maps: minha localizacao, satelite, mapa de calor ----------
  const myLocationBtn = el("myLocationBtn");
  const satelliteToggleBtn = el("satelliteToggleBtn");
  const heatmapToggleBtn = el("heatmapToggleBtn");
  const STREETS_STYLE = CFG.MAPBOX_STYLE || "mapbox://styles/miguwl0287/cmixney1h001501s111340npb";
  const SATELLITE_STYLE = "mapbox://styles/mapbox/satellite-streets-v12";

  if (myLocationBtn) {
    myLocationBtn.addEventListener("click", () => {
      followUser = true;
      if (userCoords) {
        map.flyTo({ center: userCoords, zoom: isNavigating ? 17 : 16, essential: true });
        myLocationBtn.classList.add("pulse-once");
        setTimeout(() => myLocationBtn.classList.remove("pulse-once"), 500);
      } else {
        showToast("Aguardando sinal de GPS...", "error");
      }
    });
  }

  function ensureHeatmapLayer() {
    if (map.getSource("risk-heatmap")) return;
    map.addSource("risk-heatmap", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    map.addLayer({
      id: "risk-heatmap-layer",
      type: "heatmap",
      source: "risk-heatmap",
      layout: { visibility: "none" },
      paint: {
        "heatmap-weight": ["interpolate", ["linear"], ["get", "risk_level"], 1, 0.35, 2, 0.7, 3, 1],
        "heatmap-intensity": 0.9,
        "heatmap-radius": 32,
        "heatmap-opacity": 0.55,
        "heatmap-color": [
          "interpolate", ["linear"], ["heatmap-density"],
          0, "rgba(88,204,2,0)",
          0.3, "rgba(88,204,2,0.55)",
          0.55, "rgba(255,200,0,0.65)",
          0.8, "rgba(255,140,31,0.75)",
          1, "rgba(255,75,75,0.85)",
        ],
      },
    }, "route-active-casing");
  }

  async function loadHeatmapData() {
    try {
      const resp = await fetch(`${API_BASE}/api/hotspots`);
      const data = await resp.json();
      const features = (data.hotspots || []).map((h) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [h.lng, h.lat] },
        properties: { risk_level: h.risk_level },
      }));
      const src = map.getSource("risk-heatmap");
      if (src) src.setData({ type: "FeatureCollection", features });
    } catch (e) { /* silencioso — mapa de calor e um extra, nao deve travar o app */ }
  }

  if (heatmapToggleBtn) {
    heatmapToggleBtn.addEventListener("click", () => {
      ensureHeatmapLayer();
      heatmapOn = !heatmapOn;
      heatmapToggleBtn.classList.toggle("active", heatmapOn);
      map.setLayoutProperty("risk-heatmap-layer", "visibility", heatmapOn ? "visible" : "none");
      if (heatmapOn) {
        loadHeatmapData();
        showToast("Mapa de calor de risco ativado.", "success");
      }
    });
  }

  if (satelliteToggleBtn) {
    satelliteToggleBtn.addEventListener("click", () => {
      satelliteOn = !satelliteOn;
      satelliteToggleBtn.classList.toggle("active", satelliteOn);
      const wasHeatmapOn = heatmapOn;
      const wasNavigating = isNavigating;
      map.setStyle(satelliteOn ? SATELLITE_STYLE : STREETS_STYLE);
      map.once("style.load", () => {
        ensureRouteLayers();
        if (wasHeatmapOn) { ensureHeatmapLayer(); map.setLayoutProperty("risk-heatmap-layer", "visibility", "visible"); loadHeatmapData(); }
        if (lastRouteResult) updateRoutePanel();
        if (userCoords) setUserLocation(userCoords);
        if (destCoords) setDestinationMarker(destCoords);
        if (wasNavigating) map.setPitch(55);
      });
    });
  }

  // ---------- Boot ----------
  map.on("load", () => {
    initGeolocation();
    ensureHeatmapLayer();
    showPanel("locationSelection");
  });

  loadProfile();
})();
