import os
import re
import ssl
import time
import datetime
import math
import secrets
import smtplib
import threading
from pathlib import Path
from email.mime.text import MIMEText
from email.utils import formataddr
import requests
from typing import List, Dict, Optional, Any, Tuple

# Carrega o .env que fica ao lado deste arquivo (app.py), independente de qual seja o
# diretório de trabalho de onde você rodou "python app.py" / "flask run". Isso evita o
# problema clássico de "editei o .env certo mas nada muda" quando se roda o comando de
# outra pasta.
_APP_DIR = Path(__file__).resolve().parent
_ENV_PATH = _APP_DIR / ".env"

try:
    from dotenv import load_dotenv
    if _ENV_PATH.exists():
        load_dotenv(dotenv_path=_ENV_PATH, override=True)
    else:
        print(f"[AVISO] Nenhum arquivo .env encontrado em {_ENV_PATH} — usando só variáveis de ambiente do sistema.")
except ImportError:
    print(
        "[AVISO] python-dotenv não está instalado neste ambiente Python — o arquivo .env "
        "NÃO será lido, mesmo que exista e esteja correto. Rode: pip install python-dotenv "
        "(ou confira se está no requirements.txt e se você instalou no venv/ambiente certo)."
    )

from functools import wraps

from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_jwt_extended import (
    JWTManager, create_access_token,
    jwt_required, get_jwt_identity, get_jwt, unset_jwt_cookies
)
from flask_cors import CORS
from sqlalchemy import desc, func
from sqlalchemy.exc import IntegrityError

# ============================================================
# ⚙️ CONFIGURAÇÃO
# ============================================================

def _bool_env(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")

def _require_env(name: str, min_length: int = 16) -> str:
    """
    Exige que uma variável de ambiente sensível esteja definida e seja "forte" o suficiente.
    Em vez de cair para um valor padrão fraco (ex.: 'mude-esta-chave'), a aplicação recusa
    subir — isso evita que alguém esqueça de configurar o segredo em produção sem perceber.
    """
    value = os.getenv(name, "")
    if not value or len(value) < min_length:
        raise RuntimeError(
            f"A variável de ambiente {name} não está definida (ou é curta/fraca demais, "
            f"mínimo {min_length} caracteres). Gere um valor aleatório forte, por exemplo com: "
            f"python -c \"import secrets; print(secrets.token_urlsafe(48))\" "
            f"e defina {name} no seu .env antes de rodar a aplicação."
        )
    return value

# Fora do modo de desenvolvimento explícito, tratamos como produção por padrão (fail-safe):
# só relaxamos as exigências de segredo forte se STRICT_SECRETS=false for setado manualmente.
STRICT_SECRETS = _bool_env("STRICT_SECRETS", "true")

class Config:
    """Configurações centrais da aplicação."""
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///wesafe.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False

    # Sem valor padrão fraco: se STRICT_SECRETS=true (padrão), a app não sobe sem uma
    # JWT_SECRET_KEY forte de verdade definida no ambiente.
    JWT_SECRET_KEY = (
        _require_env("JWT_SECRET_KEY", 32) if STRICT_SECRETS
        else (os.getenv("JWT_SECRET_KEY") or secrets.token_urlsafe(48))
    )
    JWT_ACCESS_TOKEN_EXPIRES = datetime.timedelta(hours=6)

    # Mapbox é usado apenas no FRONTEND (tiles + geocoding de endereços).
    # As ROTAS em si (o cálculo real de caminho) usam o roteador OSRM público,
    # que não exige chave e devolve geometria real de ruas + alternativas.
    MAPBOX_TOKEN = os.getenv("MAPBOX_TOKEN", "")

    # Roteador OSRM (OpenStreetMap). Serviço público, sem necessidade de API key.
    # routed-car / routed-foot / routed-bike cobrem os 3 perfis de deslocamento.
    OSRM_BASE_URL = os.getenv("OSRM_BASE_URL", "https://routing.openstreetmap.de")
    OSRM_TIMEOUT = float(os.getenv("OSRM_TIMEOUT", "8"))

    # Envio de email (código OTP de verificação no cadastro).
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASS = os.getenv("SMTP_PASS", "")
    # "starttls" (porta 587, padrão), "ssl" (porta 465, conexão já criptografada) ou "none" (só testes locais).
    SMTP_SECURITY = os.getenv("SMTP_SECURITY", "starttls").strip().lower()
    SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "WeSafe")
    SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", os.getenv("SMTP_USER", "no-reply@wesafe.app"))
    SMTP_TIMEOUT = float(os.getenv("SMTP_TIMEOUT", "10"))

    # Se "true", devolve o código OTP na resposta da API (apenas para testar sem SMTP configurado).
    # Trava adicional: mesmo que fique "true" por engano, é ignorado quando STRICT_SECRETS está ativo.
    OTP_DEBUG_ECHO = _bool_env("OTP_DEBUG_ECHO", "false") and not STRICT_SECRETS
    OTP_EXPIRATION_MINUTES = 10
    OTP_RESEND_COOLDOWN_SECONDS = 30

    # Origens autorizadas a chamar a API (CORS). Lista separada por vírgula.
    # Nunca usar "*" — restrinja ao(s) domínio(s) reais do front-end.
    CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]

app = Flask(__name__)
app.config.from_object(Config)

if app.config["CORS_ORIGINS"]:
    CORS(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}}, supports_credentials=False)
else:
    # Sem CORS_ORIGINS configurado: nenhuma origem cross-site é liberada para /api/* (seguro por padrão).
    app.logger.warning(
        "CORS_ORIGINS não definido — nenhuma origem cross-site foi liberada para /api/*. "
        "Defina CORS_ORIGINS=https://seu-dominio.com no .env se o front-end rodar em outro domínio/porta."
    )

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
jwt = JWTManager(app)

MAPBOX_TOKEN = app.config["MAPBOX_TOKEN"]
OSRM_BASE_URL = app.config["OSRM_BASE_URL"]
OSRM_TIMEOUT = app.config["OSRM_TIMEOUT"]

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

def is_valid_email(value: str) -> bool:
    """Valida formato do email e barra caracteres de controle (CR/LF), que poderiam
    ser usados para injeção de cabeçalhos em emails (header injection)."""
    if not value or len(value) > 254:
        return False
    if any(ch in value for ch in ("\r", "\n", "\x00")):
        return False
    return bool(EMAIL_RE.match(value))

def _utcnow() -> datetime.datetime:
    """UTC 'naive' (sem tzinfo) — mesmo formato usado no banco (SQLite não guarda tzinfo),
    só sem o warning de depreciação do _utcnow()."""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

# ============================================================
# 🚨 CLASSES DE ERRO
# ============================================================

class APIError(Exception):
    status_code = 400
    def __init__(self, message, status_code=None):
        super().__init__()
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        app.logger.error(f"API Error ({self.status_code}): {self.message}")

@app.errorhandler(APIError)
def handle_api_error(error):
    response = jsonify({"error": error.message})
    response.status_code = error.status_code
    return response

@app.errorhandler(404)
def handle_404(error):
    return jsonify({"error": "Recurso não encontrado."}), 404

@app.errorhandler(500)
def handle_500(error):
    app.logger.exception("Erro interno não tratado")
    return jsonify({"error": "Erro interno do servidor."}), 500

class RateLimiter:
    """
    Rate limiter simples em memória (janela deslizante por IP+rota).
    Suficiente para um único processo; se a app rodar com múltiplos workers/instâncias,
    troque por um backend compartilhado (Redis) — mas isso aqui já barra brute force
    e abuso trivial de bots sem exigir infraestrutura extra.
    """
    def __init__(self):
        self._hits: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, max_hits: int, window_seconds: int) -> bool:
        now = time.time()
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < window_seconds]
            if len(hits) >= max_hits:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            return True

_rate_limiter = RateLimiter()

def rate_limit(max_hits: int, window_seconds: int, scope: str):
    """Decorator: limita quantas requisições um mesmo IP pode fazer numa rota sensível."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
            key = f"{scope}:{ip}"
            if not _rate_limiter.check(key, max_hits, window_seconds):
                raise APIError("Muitas tentativas. Aguarde um pouco antes de tentar novamente.", 429)
            return fn(*args, **kwargs)
        return wrapper
    return decorator

def admin_required(fn):
    """Exige um JWT válido cujo claim 'is_admin' seja verdadeiro."""
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        claims = get_jwt()
        if not claims.get("is_admin"):
            raise APIError("Acesso restrito a administradores.", 403)
        return fn(*args, **kwargs)
    return wrapper

# ============================================================
# 🎮 REGRAS DE GAMIFICAÇÃO
# ============================================================

XP_PER_REPORT = 15
XP_STREAK_BONUS = 5          # bônus por manter a sequência viva
XP_PER_LEVEL_BASE = 100      # xp necessário para o nível 2
XP_LEVEL_GROWTH = 1.18       # cada nível fica ~18% mais "caro"

BADGES = [
    {"id": "novato", "label": "Novato Vigilante", "min_reports": 1},
    {"id": "bronze", "label": "Guardião Bronze", "min_reports": 5},
    {"id": "prata", "label": "Guardião Prata", "min_reports": 20},
    {"id": "ouro", "label": "Guardião Ouro", "min_reports": 50},
    {"id": "lenda", "label": "Lenda da Comunidade", "min_reports": 150},
]

def xp_required_for_level(level: int) -> int:
    """XP acumulado necessário para alcançar um determinado nível."""
    if level <= 1:
        return 0
    total = 0
    req = XP_PER_LEVEL_BASE
    for lvl in range(2, level + 1):
        total += req
        req = math.ceil(req * XP_LEVEL_GROWTH)
    return total

def compute_level_progress(xp: int) -> Dict[str, Any]:
    """Deriva nível atual e progresso percentual até o próximo nível a partir do XP total."""
    level = 1
    req = XP_PER_LEVEL_BASE
    floor_xp = 0
    while xp >= floor_xp + req:
        floor_xp += req
        level += 1
        req = math.ceil(req * XP_LEVEL_GROWTH)

    xp_into_level = xp - floor_xp
    progress_pct = round(min(100, (xp_into_level / req) * 100), 1) if req else 100

    return {
        "level": level,
        "xp_total": xp,
        "xp_into_level": xp_into_level,
        "xp_for_next_level": req,
        "progress_pct": progress_pct,
    }

def current_badge(reports_count: int) -> Optional[Dict[str, str]]:
    unlocked = [b for b in BADGES if reports_count >= b["min_reports"]]
    return unlocked[-1] if unlocked else None

def update_streak(user: "User") -> int:
    """Atualiza a sequência diária de atividade do usuário. Retorna o bônus de XP ganho."""
    today = datetime.date.today()
    last = user.last_activity_date

    if last == today:
        bonus = 0  # já contabilizado hoje
    elif last == today - datetime.timedelta(days=1):
        user.streak_count += 1
        bonus = XP_STREAK_BONUS
    else:
        user.streak_count = 1
        bonus = 0

    user.last_activity_date = today
    return bonus

# ============================================================
# 💾 MODELS
# ============================================================

class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False, default="Usuário WeSafe")
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    xp = db.Column(db.Integer, nullable=False, default=0)
    streak_count = db.Column(db.Integer, nullable=False, default=0)
    last_activity_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow)

    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    reports = db.relationship("Report", backref="user", lazy=True, cascade="all, delete-orphan")

    def set_password(self, password: str):
        self.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

    def check_password(self, password: str) -> bool:
        return bcrypt.check_password_hash(self.password_hash, password)

    def to_profile_dict(self) -> Dict[str, Any]:
        reports_count = len(self.reports)
        progress = compute_level_progress(self.xp)
        badge = current_badge(reports_count)
        return {
            "id": self.id,
            "nome": self.nome,
            "email": self.email,
            "reports_count": reports_count,
            "streak_count": self.streak_count,
            "badge": badge,
            "is_admin": self.is_admin,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            **progress,
        }

    def to_admin_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "nome": self.nome,
            "email": self.email,
            "xp": self.xp,
            "streak_count": self.streak_count,
            "reports_count": len(self.reports),
            "is_admin": self.is_admin,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

class PendingSignup(db.Model):
    """Cadastro em andamento aguardando confirmação do código OTP enviado por email."""
    __tablename__ = "pending_signups"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    nome = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    otp_hash = db.Column(db.String(255), nullable=False)
    otp_expires_at = db.Column(db.DateTime, nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    last_sent_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    created_at = db.Column(db.DateTime, default=_utcnow)


class Report(db.Model):
    __tablename__ = "reports"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    risk_level = db.Column(db.Integer, nullable=False)  # 1 (Baixo), 2 (Médio), 3 (Alto)
    category = db.Column(db.String(40), nullable=True)  # assalto, iluminacao, radar, etc.
    comment = db.Column(db.String(500), nullable=True)
    neighborhood = db.Column(db.String(100), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow, index=True)
    specific_location = db.Column(db.String(255), nullable=True)

    def to_admin_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "user_email": self.user.email if self.user else None,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "risk_level": self.risk_level,
            "category": self.category,
            "comment": self.comment,
            "neighborhood": self.neighborhood,
            "city": self.city,
            "specific_location": self.specific_location,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

# ============================================================
# 🛠️ CÁLCULO DE RISCO (baseado em denúncias reais dos usuários)
# ============================================================

R_EARTH_METERS = 6371000
BASE_SCORES = {1: 1.5, 2: 5.0, 3: 9.0}

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância em metros entre dois pontos (Fórmula Haversine)."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R_EARTH_METERS * c

def _time_of_day_weight(dt: datetime.datetime) -> float:
    hour = dt.hour
    if 0 <= hour < 5: return 1.8
    if 22 <= hour <= 23: return 1.6
    if 18 <= hour < 22: return 1.4
    if 17 <= hour < 18: return 1.25
    if 5 <= hour < 7: return 1.2
    if 7 <= hour < 9: return 1.1
    if 7 <= hour < 17: return 1.0
    return 1.0

def _decay_time_weight(created_at: datetime.datetime) -> float:
    """Decaimento exponencial: denúncias recentes pesam mais que antigas."""
    now = _utcnow()
    hours_diff = (now - created_at).total_seconds() / 3600.0
    decay_factor = 0.05
    weight = math.exp(-decay_factor * hours_diff)
    return max(0.1, weight)

def _density_weight(reports_count: int) -> float:
    """Áreas com múltiplas denúncias concordantes pesam mais (efeito de confirmação)."""
    if reports_count < 2: return 1.0
    max_reports_for_full_weight = 15
    max_weight = 1.5
    weight = 1.0 + (max_weight - 1.0) * math.sqrt(min(reports_count, max_reports_for_full_weight) / max_reports_for_full_weight)
    return weight

def _get_risk_category(score: float) -> Dict[str, Any]:
    if score >= 7.0: return {"level": "Alto", "color_code": "red"}
    if score >= 4.0: return {"level": "Médio", "color_code": "orange"}
    if score >= 1.0: return {"level": "Baixo", "color_code": "yellowgreen"}
    return {"level": "Muito Baixo", "color_code": "green"}

def _get_active_reports(hours: int = 72, limit: int = 3000) -> List[Report]:
    """Todas as denúncias ainda 'ativas' (dentro da janela de relevância)."""
    time_limit = _utcnow() - datetime.timedelta(hours=hours)
    return (
        db.session.execute(
            db.select(Report)
            .where(Report.created_at >= time_limit)
            .order_by(desc(Report.created_at))
            .limit(limit)
        ).scalars().all()
    )

def _get_nearby_reports(lat: float, lng: float, radius_m: int = 200, pool: Optional[List[Report]] = None) -> List[Report]:
    """Filtra, dentro de um pool de denúncias já carregado, as que ficam a `radius_m` de um ponto."""
    reports = pool if pool is not None else _get_active_reports()
    nearby: List[Report] = []
    degree_radius = radius_m / R_EARTH_METERS * (180 / math.pi)

    for r in reports:
        if (abs(r.latitude - lat) > degree_radius * 2 or
                abs(r.longitude - lng) > degree_radius * 2):
            continue
        dist = haversine_distance(lat, lng, r.latitude, r.longitude)
        if dist <= radius_m:
            nearby.append(r)

    return nearby

def _score_reports(nearby: List[Report]) -> float:
    """Converte uma lista de denúncias próximas em um score 0-10."""
    if not nearby:
        return 0.0

    density_w = _density_weight(len(nearby))
    scores = []
    for r in nearby:
        base = BASE_SCORES.get(r.risk_level, 5.0)
        time_weight = _decay_time_weight(r.created_at)
        tod_weight = _time_of_day_weight(r.created_at)
        scores.append(base * time_weight * tod_weight * density_w)

    return max(0.0, min(10.0, sum(scores) / len(scores)))

def calculate_risk_score(lat: float, lng: float, radius_m: int = 200) -> Dict[str, Any]:
    """Calcula o risco (0-10) num raio em torno de um ponto (lat, lng)."""
    pool = _get_active_reports()
    nearby = _get_nearby_reports(lat, lng, radius_m=radius_m, pool=pool)[:80]
    risk_score = round(_score_reports(nearby), 2)

    return {
        "risk_score": risk_score,
        "reports_count": len(nearby),
        "risk_category": _get_risk_category(risk_score)
    }

# ============================================================
# 🗺️ GEOCODIFICAÇÃO (Mapbox, opcional — apenas enriquece denúncias com endereço)
# ============================================================

def reverse_geocode(lat: float, lng: float) -> Dict[str, Optional[str]]:
    """Busca bairro/cidade de um ponto via Mapbox, se um token válido estiver configurado."""
    if not MAPBOX_TOKEN:
        return {"neighborhood": None, "city": None, "specific_location": None}

    # Endpoint REST correto da Mapbox Geocoding API (o "mapbox://styles/..." é só o
    # identificador do estilo visual do mapa e nunca deve ser usado para geocoding).
    url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{lng},{lat}.json"
    params = {
        "access_token": MAPBOX_TOKEN,
        "types": "address,locality,place,neighborhood",
        "language": "pt",
        "limit": 1
    }

    try:
        resp = requests.get(url, params=params, timeout=5)
        resp.raise_for_status()
        data = resp.json()

        neighborhood = None
        city = None
        specific_location = None

        if data.get("features"):
            feature = data["features"][0]
            context = feature.get("context", [])

            if feature.get("place_type") and ("address" in feature["place_type"] or "poi" in feature["place_type"]):
                specific_location = feature.get("text")
            elif feature.get("text") and not any(t in feature.get("place_type", []) for t in ["neighborhood", "locality", "place"]):
                specific_location = feature["text"]

            for item in context:
                if 'neighborhood' in item['id']:
                    neighborhood = item['text']
                elif 'place' in item['id'] or 'locality' in item['id']:
                    if not city:
                        city = item['text']

            if not specific_location and feature.get("place_type") and ("neighborhood" in feature["place_type"] or "locality" in feature["place_type"]):
                specific_location = feature["text"]

        return {"neighborhood": neighborhood, "city": city, "specific_location": specific_location}

    except requests.exceptions.RequestException as e:
        app.logger.error(f"Erro no Geocoding Reverso: {e}")
        return {"neighborhood": None, "city": None, "specific_location": None}

# ============================================================
# 🧭 ROTEAMENTO REAL (OSRM) + ALGORITMO DE RISCO POR TRAJETO
# ============================================================

OSRM_PROFILE_PATH = {
    "driving": "routed-car/route/v1/driving",
    "cycling": "routed-bike/route/v1/bike",
    "walking": "routed-foot/route/v1/foot",
}

# Distância (m) entre pontos de amostragem ao longo da rota para avaliação de risco.
ROUTE_SAMPLE_STEP_M = 120
# Peso do risco vs. tempo/distância na escolha da rota recomendada (0-1).
RISK_WEIGHT_DEFAULT = 0.65
# Pontos de amostragem do "perfil de risco" ao longo da rota, usado para colorir o traçado
# no mapa (efeito de "faixa de risco", análogo às faixas de trânsito do Google Maps).
RISK_PROFILE_SAMPLES = 24

# ---------- Tradução de manobras OSRM -> instruções em PT-BR (turn-by-turn) ----------
_MANEUVER_VERBS = {
    "turn": "Vire",
    "new name": "Continue",
    "depart": "Siga",
    "arrive": "Chegue ao destino",
    "merge": "Entre",
    "on ramp": "Pegue a rampa de acesso",
    "off ramp": "Saia pela rampa",
    "fork": "Mantenha-se",
    "end of road": "No fim da via, vire",
    "continue": "Continue",
    "roundabout": "Na rotatória, saia",
    "rotary": "Na rotatória, saia",
    "roundabout turn": "Na rotatória, vire",
    "notification": "Continue",
    "exit roundabout": "Saia da rotatória",
    "exit rotary": "Saia da rotatória",
}
_MANEUVER_MODIFIERS = {
    "uturn": "e retorne",
    "sharp right": "acentuadamente à direita",
    "right": "à direita",
    "slight right": "levemente à direita",
    "straight": "e siga em frente",
    "slight left": "levemente à esquerda",
    "left": "à esquerda",
    "sharp left": "acentuadamente à esquerda",
}
_MANEUVER_ICONS = {
    "uturn": "rotate", "sharp right": "turn-sharp-right", "right": "turn-right",
    "slight right": "turn-slight-right", "straight": "straight", "slight left": "turn-slight-left",
    "left": "turn-left", "sharp left": "turn-sharp-left",
}

def _translate_step(step: Dict[str, Any]) -> Dict[str, Any]:
    """Converte um 'step' cru do OSRM em uma instrução legível, com ícone de manobra."""
    maneuver = step.get("maneuver", {})
    m_type = maneuver.get("type", "turn")
    modifier = maneuver.get("modifier", "")
    name = step.get("name") or ""
    verb = _MANEUVER_VERBS.get(m_type, "Continue")

    if m_type == "arrive":
        text = "Você chegou ao seu destino"
    elif m_type == "depart":
        text = f"Siga por {name}" if name else "Siga em frente"
    elif m_type in ("roundabout", "rotary", "roundabout turn"):
        exit_n = maneuver.get("exit", 1)
        text = f"Na rotatória, pegue a {exit_n}ª saída" + (f" em direção a {name}" if name else "")
    else:
        mod_text = _MANEUVER_MODIFIERS.get(modifier, "")
        text = f"{verb} {mod_text}".strip()
        if name:
            text += f" em {name}"

    return {
        "instruction": text,
        "street": name,
        "type": m_type,
        "modifier": modifier,
        "icon": _MANEUVER_ICONS.get(modifier, "straight" if m_type != "arrive" else "flag"),
        "distance": round(step.get("distance", 0), 1),
        "duration": round(step.get("duration", 0), 1),
        "location": step.get("maneuver", {}).get("location", []),  # [lng, lat]
    }

def _traffic_multiplier(dt: Optional[datetime.datetime] = None) -> float:
    """
    Estimativa simples de trânsito por horário (análoga ao 'duration_in_traffic' do Google Maps),
    já que não temos um provedor de trânsito ao vivo: horários de pico recebem um multiplicador maior.
    """
    dt = dt or datetime.datetime.now()
    weekday = dt.weekday()  # 0 = segunda ... 6 = domingo
    hour = dt.hour
    is_weekend = weekday >= 5

    if is_weekend:
        if 11 <= hour < 15 or 18 <= hour < 22:
            return 1.12
        return 1.0

    if 7 <= hour < 10 or 17 <= hour < 20:
        return 1.35
    if 10 <= hour < 17:
        return 1.08
    if 6 <= hour < 7 or 20 <= hour < 22:
        return 1.15
    return 0.95  # madrugada: vias livres

def fetch_osrm_routes(origin: List[float], destination: List[float], profile: str = "driving") -> List[Dict[str, Any]]:
    """Consulta o roteador OSRM real e devolve a rota principal + alternativas com geometria de ruas
    e instruções passo-a-passo (turn-by-turn)."""
    path = OSRM_PROFILE_PATH.get(profile, OSRM_PROFILE_PATH["driving"])
    o_lat, o_lng = origin
    d_lat, d_lng = destination

    url = f"{OSRM_BASE_URL}/{path}/{o_lng},{o_lat};{d_lng},{d_lat}"
    params = {
        "alternatives": "true",
        "geometries": "geojson",
        "overview": "full",
        "steps": "true",
    }

    try:
        resp = requests.get(url, params=params, timeout=OSRM_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Erro ao consultar OSRM: {e}")
        raise APIError("Não foi possível calcular a rota no momento. Tente novamente em instantes.", 503)

    if data.get("code") != "Ok" or not data.get("routes"):
        raise APIError("Nenhuma rota encontrada entre os pontos informados.", 404)

    traffic_mult = _traffic_multiplier()

    routes = []
    for r in data["routes"]:
        steps = []
        for leg in r.get("legs", []):
            for step in leg.get("steps", []):
                translated = _translate_step(step)
                if translated["distance"] < 8 and translated["type"] not in ("depart", "arrive"):
                    continue  # ignora micro-manobras irrelevantes (ruído do roteador)
                steps.append(translated)

        routes.append({
            "distance": r["distance"],                                   # metros
            "duration": r["duration"],                                    # segundos (sem trânsito)
            "duration_in_traffic": round(r["duration"] * traffic_mult, 1),  # estimativa com trânsito
            "coords": r["geometry"]["coordinates"],                       # [[lng, lat], ...]
            "steps": steps,
        })
    return routes

def _interpolate_point(lat1, lng1, lat2, lng2, fraction: float) -> Tuple[float, float]:
    """Interpolação linear simples entre dois pontos (precisão suficiente em segmentos curtos)."""
    return (lat1 + (lat2 - lat1) * fraction, lng1 + (lng2 - lng1) * fraction)

def sample_route_points(coords: List[List[float]], step_m: int = ROUTE_SAMPLE_STEP_M) -> List[Tuple[float, float, float]]:
    """
    Converte a geometria [lng, lat] da rota em pontos de amostragem espaçados por `step_m` metros.
    Retorna lista de (lat, lng, dist_segmento_m) onde dist_segmento_m é a distância representada
    por aquele ponto (usada para ponderar a exposição ao risco).
    """
    if len(coords) < 2:
        return [(coords[0][1], coords[0][0], 0.0)] if coords else []

    samples: List[Tuple[float, float, float]] = []
    carry = 0.0

    for i in range(len(coords) - 1):
        lng1, lat1 = coords[i]
        lng2, lat2 = coords[i + 1]
        seg_len = haversine_distance(lat1, lng1, lat2, lng2)
        if seg_len == 0:
            continue

        dist_along = -carry
        while True:
            dist_along += step_m
            if dist_along > seg_len:
                carry = seg_len - (dist_along - step_m)
                break
            fraction = dist_along / seg_len
            plat, plng = _interpolate_point(lat1, lng1, lat2, lng2, fraction)
            samples.append((plat, plng, step_m))

    if not samples:
        mid = coords[len(coords) // 2]
        samples.append((mid[1], mid[0], 0.0))

    return samples

def _build_risk_profile(samples: List[Tuple[float, float, float]], reports_pool: List[Report]) -> List[Dict[str, float]]:
    """
    Reamostra o risco em ~RISK_PROFILE_SAMPLES pontos uniformemente espaçados ao longo da rota,
    devolvendo {t: fração 0-1 do trajeto, risk: 0-10}. O frontend usa isso para pintar um
    gradiente de cor na linha da rota (verde → amarelo → vermelho), como uma "faixa de risco".
    """
    if not samples:
        return [{"t": 0.0, "risk": 0.0}, {"t": 1.0, "risk": 0.0}]

    n = len(samples)
    step = max(1, round(n / RISK_PROFILE_SAMPLES))
    profile = []
    for i in range(0, n, step):
        lat, lng, _ = samples[i]
        nearby = _get_nearby_reports(lat, lng, radius_m=120, pool=reports_pool)
        score = _score_reports(nearby)
        profile.append({"t": round(i / max(1, n - 1), 4), "risk": round(score, 2)})

    if profile[-1]["t"] != 1.0:
        lat, lng, _ = samples[-1]
        nearby = _get_nearby_reports(lat, lng, radius_m=120, pool=reports_pool)
        profile.append({"t": 1.0, "risk": round(_score_reports(nearby), 2)})

    return profile

def score_route_risk(coords: List[List[float]], reports_pool: List[Report]) -> Dict[str, Any]:
    """
    Algoritmo de risco por trajeto:
    1) amostra pontos ao longo da geometria real da rota,
    2) para cada ponto calcula o risco local a partir das denúncias próximas (raio 120m),
    3) agrega em um score único ponderando exposição média + pico de risco + nº de pontos quentes,
    4) gera um "perfil de risco" espacial para colorir a linha da rota no mapa.
    """
    samples = sample_route_points(coords)
    if not samples:
        return {
            "risk_score": 0.0, "safety_score": 100.0, "risk_category": _get_risk_category(0.0),
            "hotspots": [], "reports_considered": 0, "risk_profile": _build_risk_profile([], reports_pool),
        }

    total_exposure = sum(s[2] for s in samples) or 1.0
    weighted_sum = 0.0
    peak_risk = 0.0
    hotspots = []
    reports_touched = set()

    for lat, lng, seg_weight in samples:
        nearby = _get_nearby_reports(lat, lng, radius_m=120, pool=reports_pool)
        local_score = _score_reports(nearby)

        weighted_sum += local_score * seg_weight
        peak_risk = max(peak_risk, local_score)

        for r in nearby:
            reports_touched.add(r.id)

        if local_score >= 6.5:
            hotspots.append({"lat": round(lat, 6), "lng": round(lng, 6), "risk_score": round(local_score, 2)})

    avg_exposure_risk = weighted_sum / total_exposure
    hotspot_density = min(1.0, len(hotspots) / 6.0) * 10.0  # normaliza p/ escala 0-10

    # Composição final: média de exposição pesa mais, pico e densidade de pontos quentes completam.
    final_score = (0.55 * avg_exposure_risk) + (0.30 * peak_risk) + (0.15 * hotspot_density)
    final_score = round(max(0.0, min(10.0, final_score)), 2)

    # Limita a no máx. 6 hotspots mais graves para não poluir o mapa
    hotspots.sort(key=lambda h: h["risk_score"], reverse=True)

    return {
        "risk_score": final_score,
        "safety_score": round(max(0.0, 100.0 - final_score * 10), 1),  # 0-100, mais alto = mais seguro
        "risk_category": _get_risk_category(final_score),
        "hotspots": hotspots[:6],
        "reports_considered": len(reports_touched),
        "risk_profile": _build_risk_profile(samples, reports_pool),
    }

def _composite_score(route: Dict[str, Any], risk_weight: float, fastest_duration: float) -> float:
    """Combina risco normalizado (0-1) e tempo normalizado (0 = mais rápida) num único score — quanto menor, melhor."""
    risk_norm = route["risk_score"] / 10.0
    time_norm = (route["duration"] - fastest_duration) / fastest_duration
    return round((risk_weight * risk_norm) + ((1 - risk_weight) * time_norm), 4)

def find_safest_route(origin: List[float], destination: List[float], profile: str = "driving",
                       risk_weight: float = RISK_WEIGHT_DEFAULT) -> Dict[str, Any]:
    """
    Busca a rota real (OSRM) + alternativas, calcula o risco real de cada uma a partir dos relatos
    da comunidade e monta 3 recomendações claramente diferentes — como o seletor de rotas do
    Google Maps, mas otimizando também para segurança:

      • safest_route     -> menor risco possível, mesmo que mais longa/demorada
      • balanced_route    -> melhor equilíbrio entre risco e tempo (peso 0.5/0.5)
      • fastest_route     -> menor tempo de viagem, ignorando risco

    Quando o OSRM devolve poucas alternativas, os 3 modos ainda são calculados de forma consistente
    (podem apontar para a mesma rota se não houver alternativa realmente mais segura ou mais rápida).
    """
    raw_routes = fetch_osrm_routes(origin, destination, profile=profile)
    reports_pool = _get_active_reports()

    enriched_routes = []
    for idx, r in enumerate(raw_routes):
        risk_info = score_route_risk(r["coords"], reports_pool)
        enriched_routes.append({
            "id": idx,
            "type": "main" if idx == 0 else "alternative",
            "distance": round(r["distance"], 1),
            "duration": round(r["duration"], 1),
            "duration_in_traffic": r["duration_in_traffic"],
            "coords": r["coords"],
            "steps": r["steps"],
            **risk_info,
        })

    fastest_duration = min(r["duration"] for r in enriched_routes) or 1.0

    # Score "oficial" (respeitando o risk_weight pedido pelo cliente) — usado para ordenação geral.
    for r in enriched_routes:
        r["composite_score"] = _composite_score(r, risk_weight, fastest_duration)

    fastest_route = min(enriched_routes, key=lambda r: r["duration"])
    safest_route = min(enriched_routes, key=lambda r: (r["risk_score"], r["duration"]))

    # Rota equilibrada: melhor score com peso 0.5 — se coincidir com uma das duas acima e existirem
    # outras alternativas, usa a próxima melhor opção para garantir 3 escolhas distintas quando possível.
    balanced_candidates = sorted(enriched_routes, key=lambda r: _composite_score(r, 0.5, fastest_duration))
    balanced_route = balanced_candidates[0]
    if len(enriched_routes) > 1 and balanced_route["id"] in (fastest_route["id"], safest_route["id"]):
        for cand in balanced_candidates[1:]:
            if cand["id"] not in (fastest_route["id"], safest_route["id"]):
                balanced_route = cand
                break

    enriched_routes.sort(key=lambda r: r["composite_score"])
    recommended = safest_route if risk_weight >= 0.5 else enriched_routes[0]

    return {
        "recommended_route": recommended,   # compatibilidade retroativa (rota "ideal" segundo risk_weight)
        "safest_route": safest_route,
        "balanced_route": balanced_route,
        "fastest_route": fastest_route,
        "all_routes": enriched_routes,
        "profile": profile,
        "traffic_note": "Estimativa de trânsito baseada em padrões horários históricos." if profile == "driving" else None,
    }

# ============================================================
# ✉️ OTP — verificação de email no cadastro
# ============================================================

def generate_otp_code() -> str:
    """Gera um código numérico de 4 dígitos criptograficamente seguro."""
    return f"{secrets.randbelow(10000):04d}"

def hash_otp_code(code: str) -> str:
    return bcrypt.generate_password_hash(code).decode("utf-8")

def check_otp_code(otp_hash: str, code: str) -> bool:
    try:
        return bcrypt.check_password_hash(otp_hash, code)
    except ValueError:
        return False

def send_otp_email(to_email: str, nome: str, code: str) -> bool:
    """Envia o código OTP por email via SMTP. Retorna True se o envio foi concluído com sucesso."""
    host = app.config["SMTP_HOST"]
    if not host:
        # Em produção (STRICT_SECRETS) nunca logamos o código em texto puro, mesmo sem SMTP —
        # isso evitaria o próprio propósito do OTP se alguém tiver acesso aos logs.
        if STRICT_SECRETS:
            app.logger.error("SMTP não configurado — não é possível enviar código de verificação.")
        else:
            app.logger.warning(f"[DEV] SMTP não configurado — código OTP para {to_email}: {code}")
        return False

    # Defesa em profundidade: mesmo já validado antes de chegar aqui, nunca construímos
    # uma mensagem de email com um destinatário que não passe numa validação estrita.
    if not is_valid_email(to_email):
        app.logger.error("Tentativa de enviar OTP para endereço de email inválido, bloqueado.")
        return False

    # Remove quebras de linha/caracteres de controle do nome antes de colocá-lo no corpo
    # do email (defesa extra contra injeção de conteúdo, mesmo não indo em cabeçalho).
    safe_nome = re.sub(r"[\r\n\x00]", " ", (nome or "guardião(ã)")).strip()[:100]

    subject = "Seu código de verificação WeSafe"
    body = (
        f"Olá, {safe_nome}!\n\n"
        f"Seu código de verificação WeSafe é: {code}\n\n"
        f"Ele expira em {app.config['OTP_EXPIRATION_MINUTES']} minutos. "
        f"Se você não solicitou este código, apenas ignore este email — sua conta continua segura.\n\n"
        f"— Equipe WeSafe"
    )
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr((app.config["SMTP_FROM_NAME"], app.config["SMTP_FROM_EMAIL"]))
    msg["To"] = to_email

    port = app.config["SMTP_PORT"]
    timeout = app.config["SMTP_TIMEOUT"]
    security = app.config["SMTP_SECURITY"]
    # Contexto TLS com verificação de certificado habilitada (padrão seguro do módulo ssl) —
    # evita ataques man-in-the-middle na conexão com o servidor SMTP.
    tls_context = ssl.create_default_context()

    try:
        if security == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=timeout, context=tls_context)
        else:
            server = smtplib.SMTP(host, port, timeout=timeout)

        with server:
            if security == "starttls":
                server.starttls(context=tls_context)
            if app.config["SMTP_USER"]:
                server.login(app.config["SMTP_USER"], app.config["SMTP_PASS"])
            server.sendmail(app.config["SMTP_FROM_EMAIL"], [to_email], msg.as_string())
        return True

    except smtplib.SMTPAuthenticationError:
        app.logger.error("Falha de autenticação SMTP — verifique SMTP_USER/SMTP_PASS.")
        return False
    except (smtplib.SMTPException, OSError, TimeoutError) as e:
        # Loga o tipo do erro sem incluir o código OTP nem stack trace completo com dados sensíveis.
        app.logger.error(f"Falha ao enviar OTP por email ({type(e).__name__}).")
        return False

# ============================================================
# ⚙️ ROTAS / PÁGINAS (FRONTEND)
# ============================================================

@app.route("/", endpoint="entrada")
def entrada_view():
    return render_template("entrada.html")

@app.route("/login", endpoint="login")
def login_page_view():
    return render_template("login.html")

@app.route("/registro", endpoint="registro")
def registro_page_view():
    return render_template("registro.html")

@app.route("/app", endpoint="home")
def app_page_view():
    return render_template("inicio.html")

@app.route("/perfil", endpoint="perfil")
def perfil_view():
    return render_template("profile.html")

@app.route("/baixar", endpoint="baixar")
def baixar_view():
    return render_template("baixar.html")

@app.route("/admin", endpoint="admin_login")
def admin_login_view():
    return render_template("admin_login.html")

@app.route("/admin/dashboard", endpoint="admin_dashboard")
def admin_dashboard_view():
    return render_template("admin_dashboard.html")

# ---------- STATUS ----------

@app.get("/api/status")
def status():
    try:
        db.session.execute(db.select(User).limit(1)).scalar_one_or_none()
        db_status = "ok"
    except Exception:
        db_status = "error"

    return jsonify({
        "status": "online",
        "database": db_status,
        "api_version": "2.0.0",
        "routing_engine": "osrm",
        "mapbox_configured": bool(MAPBOX_TOKEN),
    })

# ---------- AUTH ----------

@app.post("/api/register/request-otp", endpoint="api_register_request_otp")
@rate_limit(max_hits=5, window_seconds=600, scope="register_otp")
def register_request_otp():
    """Etapa 1 do cadastro: valida os dados e envia um código OTP de 4 dígitos para o email."""
    data = request.get_json() or {}
    nome = re.sub(r"[\r\n\x00]", " ", (data.get("nome") or "")).strip()[:100]
    email = (data.get("email") or "").strip().lower()
    password = data.get("password")

    if not email or not password:
        raise APIError("Email e password são obrigatórios.", 400)

    if not is_valid_email(email):
        raise APIError("Email inválido.", 400)

    if len(password) < 8 or len(password) > 128:
        raise APIError("A senha deve ter entre 8 e 128 caracteres.", 400)

    if db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none():
        raise APIError("Email já registrado.", 409)

    pending = db.session.execute(db.select(PendingSignup).filter_by(email=email)).scalar_one_or_none()

    now = _utcnow()
    if pending and (now - pending.last_sent_at).total_seconds() < app.config["OTP_RESEND_COOLDOWN_SECONDS"]:
        wait_s = int(app.config["OTP_RESEND_COOLDOWN_SECONDS"] - (now - pending.last_sent_at).total_seconds())
        raise APIError(f"Aguarde {wait_s}s antes de reenviar o código.", 429)

    code = generate_otp_code()
    expires_at = now + datetime.timedelta(minutes=app.config["OTP_EXPIRATION_MINUTES"])

    if not pending:
        pending = PendingSignup(email=email)
        db.session.add(pending)

    pending.nome = nome or "Usuário WeSafe"
    pending.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")
    pending.otp_hash = hash_otp_code(code)
    pending.otp_expires_at = expires_at
    pending.attempts = 0
    pending.last_sent_at = now

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise APIError("Erro interno ao preparar o cadastro.", 500)

    email_sent = send_otp_email(email, pending.nome, code)

    response_payload = {"message": "Código enviado para o seu email.", "email_sent": email_sent}
    if app.config["OTP_DEBUG_ECHO"]:
        response_payload["debug_otp_code"] = code
    return jsonify(response_payload), 200


@app.post("/api/register/verify-otp", endpoint="api_register_verify_otp")
@rate_limit(max_hits=10, window_seconds=600, scope="verify_otp")
def register_verify_otp():
    """Etapa 2 do cadastro: confirma o código OTP e cria a conta definitivamente."""
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()

    if not email or not code:
        raise APIError("Email e código são obrigatórios.", 400)

    pending = db.session.execute(db.select(PendingSignup).filter_by(email=email)).scalar_one_or_none()
    if not pending:
        raise APIError("Nenhum cadastro pendente para este email. Solicite um novo código.", 404)

    if _utcnow() > pending.otp_expires_at:
        raise APIError("Código expirado. Solicite um novo código.", 410)

    if pending.attempts >= 5:
        raise APIError("Muitas tentativas inválidas. Solicite um novo código.", 429)

    if not check_otp_code(pending.otp_hash, code):
        pending.attempts += 1
        db.session.commit()
        raise APIError("Código inválido.", 400)

    if db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none():
        db.session.delete(pending)
        db.session.commit()
        raise APIError("Email já registrado.", 409)

    user = User(email=email, nome=pending.nome)
    user.password_hash = pending.password_hash  # já é um hash bcrypt válido

    try:
        db.session.add(user)
        db.session.delete(pending)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise APIError("Erro interno ao salvar usuário.", 500)

    token = create_access_token(identity=str(user.id), additional_claims={"is_admin": user.is_admin})

    return jsonify({
        "message": "Usuário registrado com sucesso",
        "access_token": token,
        "user_id": user.id,
        "profile": user.to_profile_dict(),
    }), 201


@app.post("/api/login", endpoint="api_login")
@rate_limit(max_hits=10, window_seconds=300, scope="login")
def login():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password")

    if not email or not password:
        raise APIError("Email e password são obrigatórios.", 400)

    if not is_valid_email(email):
        raise APIError("Credenciais inválidas.", 401)

    user = db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none()
    if not user or not user.check_password(password):
        raise APIError("Credenciais inválidas.", 401)

    if not user.is_active:
        raise APIError("Esta conta foi desativada. Fale com o suporte.", 403)

    token = create_access_token(identity=str(user.id), additional_claims={"is_admin": user.is_admin})

    return jsonify({
        "access_token": token,
        "user_id": user.id,
        "profile": user.to_profile_dict(),
    })

@app.post("/api/logout", endpoint="api_logout")
@jwt_required()
def logout():
    response = jsonify({"message": "Logout bem-sucedido"})
    unset_jwt_cookies(response)
    return response

@app.get("/api/profile", endpoint="api_profile")
@jwt_required()
def get_profile():
    user_id = get_jwt_identity()
    user = db.session.get(User, int(user_id))
    if not user:
        raise APIError("Usuário não encontrado.", 404)
    return jsonify(user.to_profile_dict())

# ---------- ADMIN ----------

@app.post("/api/admin/login", endpoint="api_admin_login")
@rate_limit(max_hits=5, window_seconds=300, scope="admin_login")
def admin_login():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password")

    if not email or not password:
        raise APIError("Email e password são obrigatórios.", 400)

    if not is_valid_email(email):
        raise APIError("Credenciais inválidas.", 401)

    user = db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none()
    if not user or not user.check_password(password):
        raise APIError("Credenciais inválidas.", 401)

    if not user.is_admin:
        raise APIError("Esta conta não tem acesso de administrador.", 403)

    token = create_access_token(identity=str(user.id), additional_claims={"is_admin": True})

    return jsonify({
        "access_token": token,
        "user_id": user.id,
        "profile": user.to_profile_dict(),
    })

@app.get("/api/admin/stats", endpoint="api_admin_stats")
@admin_required
def admin_stats():
    total_users = db.session.execute(db.select(func.count(User.id))).scalar_one()
    total_reports = db.session.execute(db.select(func.count(Report.id))).scalar_one()

    today = _utcnow().date()
    week_ago = _utcnow() - datetime.timedelta(days=7)

    new_users_today = db.session.execute(
        db.select(func.count(User.id)).where(func.date(User.created_at) == today)
    ).scalar_one()

    reports_last_7d = db.session.execute(
        db.select(func.count(Report.id)).where(Report.created_at >= week_ago)
    ).scalar_one()

    by_category_rows = db.session.execute(
        db.select(Report.category, func.count(Report.id))
        .group_by(Report.category)
        .order_by(desc(func.count(Report.id)))
    ).all()
    by_category = [{"category": c or "outro", "count": n} for c, n in by_category_rows]

    by_risk_rows = db.session.execute(
        db.select(Report.risk_level, func.count(Report.id)).group_by(Report.risk_level)
    ).all()
    by_risk = {str(level): n for level, n in by_risk_rows}

    top_users_rows = db.session.execute(
        db.select(User).order_by(desc(User.xp)).limit(5)
    ).scalars().all()

    recent_reports_rows = db.session.execute(
        db.select(Report).order_by(desc(Report.created_at)).limit(8)
    ).scalars().all()

    return jsonify({
        "total_users": total_users,
        "total_reports": total_reports,
        "new_users_today": new_users_today,
        "reports_last_7d": reports_last_7d,
        "by_category": by_category,
        "by_risk_level": {"1": by_risk.get("1", 0), "2": by_risk.get("2", 0), "3": by_risk.get("3", 0)},
        "top_users": [u.to_admin_dict() for u in top_users_rows],
        "recent_reports": [r.to_admin_dict() for r in recent_reports_rows],
    })

@app.get("/api/admin/users", endpoint="api_admin_list_users")
@admin_required
def admin_list_users():
    search = (request.args.get("q") or "").strip().lower()
    page = max(1, int(request.args.get("page", 1)))
    per_page = min(100, max(1, int(request.args.get("per_page", 20))))

    query = db.select(User).order_by(desc(User.created_at))
    if search:
        like = f"%{search}%"
        query = query.where(db.or_(User.email.ilike(like), User.nome.ilike(like)))

    all_users = db.session.execute(query).scalars().all()
    total = len(all_users)
    start = (page - 1) * per_page
    page_users = all_users[start:start + per_page]

    return jsonify({
        "total": total,
        "page": page,
        "per_page": per_page,
        "users": [u.to_admin_dict() for u in page_users],
    })

@app.patch("/api/admin/users/<int:user_id>", endpoint="api_admin_update_user")
@admin_required
def admin_update_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        raise APIError("Usuário não encontrado.", 404)

    data = request.get_json() or {}
    if "is_active" in data:
        user.is_active = bool(data["is_active"])
    if "is_admin" in data:
        user.is_admin = bool(data["is_admin"])
    if "xp" in data:
        try:
            user.xp = max(0, int(data["xp"]))
        except (TypeError, ValueError):
            raise APIError("xp deve ser numérico.", 400)

    db.session.commit()
    return jsonify(user.to_admin_dict())

@app.delete("/api/admin/users/<int:user_id>", endpoint="api_admin_delete_user")
@admin_required
def admin_delete_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        raise APIError("Usuário não encontrado.", 404)
    db.session.delete(user)
    db.session.commit()
    return jsonify({"message": "Usuário removido."})

@app.get("/api/admin/reports", endpoint="api_admin_list_reports")
@admin_required
def admin_list_reports():
    page = max(1, int(request.args.get("page", 1)))
    per_page = min(100, max(1, int(request.args.get("per_page", 20))))
    category = request.args.get("category")
    risk_level = request.args.get("risk_level")

    query = db.select(Report).order_by(desc(Report.created_at))
    if category:
        query = query.where(Report.category == category)
    if risk_level:
        query = query.where(Report.risk_level == int(risk_level))

    all_reports = db.session.execute(query).scalars().all()
    total = len(all_reports)
    start = (page - 1) * per_page
    page_reports = all_reports[start:start + per_page]

    return jsonify({
        "total": total,
        "page": page,
        "per_page": per_page,
        "reports": [r.to_admin_dict() for r in page_reports],
    })

@app.delete("/api/admin/reports/<int:report_id>", endpoint="api_admin_delete_report")
@admin_required
def admin_delete_report(report_id):
    report = db.session.get(Report, report_id)
    if not report:
        raise APIError("Relato não encontrado.", 404)
    db.session.delete(report)
    db.session.commit()
    return jsonify({"message": "Relato removido."})

# ---------- REPORTS / RISCO / GAMIFICAÇÃO ----------

@app.post("/api/report", endpoint="api_create_report")
@jwt_required(optional=True)
def create_report():
    user_id = get_jwt_identity()
    data = request.get_json() or {}

    try:
        lat = float(data.get("latitude"))
        lng = float(data.get("longitude"))
        risk_level = int(data.get("risk_level"))
        comment = data.get("comment", "") or ""
        category = data.get("category")
    except (TypeError, ValueError):
        raise APIError("latitude, longitude e risk_level devem ser numéricos.", 400)

    if risk_level not in (1, 2, 3):
        raise APIError("risk_level deve ser 1 (baixo), 2 (médio) ou 3 (alto).", 400)

    location_data = reverse_geocode(lat, lng)

    report = Report(
        user_id=int(user_id) if user_id else None,
        latitude=lat,
        longitude=lng,
        risk_level=risk_level,
        category=category,
        comment=comment[:500],
        neighborhood=location_data.get("neighborhood"),
        city=location_data.get("city"),
        specific_location=location_data.get("specific_location")
    )

    gamification = None
    try:
        db.session.add(report)

        user = None
        if user_id:
            user = db.session.get(User, int(user_id))

        if user:
            streak_bonus = update_streak(user)
            xp_gained = XP_PER_REPORT + streak_bonus
            before = compute_level_progress(user.xp)
            user.xp += xp_gained
            after = compute_level_progress(user.xp)

            gamification = {
                "xp_gained": xp_gained,
                "streak_bonus": streak_bonus,
                "streak_count": user.streak_count,
                "leveled_up": after["level"] > before["level"],
                "profile": user.to_profile_dict(),
            }

        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise APIError("Erro ao salvar relato no banco de dados.", 500)

    return jsonify({
        "message": "Relato registrado com sucesso",
        "id": report.id,
        "context": location_data,
        "gamification": gamification,
    }), 201


@app.get("/api/risk")
def get_risk_score():
    try:
        lat = float(request.args.get("lat"))
        lng = float(request.args.get("lng"))
        radius_m = int(request.args.get("radius", 200))
    except (TypeError, ValueError):
        raise APIError("lat, lng e radius devem ser numéricos.", 400)

    if radius_m > 1000:
        raise APIError("O raio máximo permitido é 1000 metros.", 400)

    result = calculate_risk_score(lat, lng, radius_m)
    return jsonify(result)

@app.get("/api/hotspots")
def get_hotspots():
    time_limit = _utcnow() - datetime.timedelta(days=7)

    reports = db.session.execute(
        db.select(Report)
        .where(Report.created_at >= time_limit)
        .order_by(desc(Report.created_at))
        .limit(500)
    ).scalars().all()

    hotspots = []
    for r in reports:
        category = _get_risk_category(BASE_SCORES.get(r.risk_level, 5.0))
        hotspots.append({
            "id": r.id,
            "lat": r.latitude,
            "lng": r.longitude,
            "risk_level": r.risk_level,
            "category": r.category,
            "comment": r.comment,
            "color": category["color_code"],
            "created_at": r.created_at.isoformat()
        })

    return jsonify({"count": len(hotspots), "hotspots": hotspots})

# ---------- ROTA SEGURA (REAL — OSRM + risco calculado a partir das denúncias) ----------

@app.get("/api/safe_route", endpoint="api_get_safe_route")
def get_safe_route():
    try:
        o_lat = float(request.args.get("o_lat"))
        o_lng = float(request.args.get("o_lng"))
        d_lat = float(request.args.get("d_lat"))
        d_lng = float(request.args.get("d_lng"))
    except (TypeError, ValueError):
        raise APIError("Coordenadas de origem e destino são obrigatórias e devem ser numéricas.", 400)

    profile = request.args.get("profile", "driving")
    if profile not in OSRM_PROFILE_PATH:
        profile = "driving"

    try:
        risk_weight = float(request.args.get("risk_weight", RISK_WEIGHT_DEFAULT))
        risk_weight = max(0.0, min(1.0, risk_weight))
    except (TypeError, ValueError):
        risk_weight = RISK_WEIGHT_DEFAULT

    origin = [o_lat, o_lng]
    destination = [d_lat, d_lng]

    result = find_safest_route(origin, destination, profile=profile, risk_weight=risk_weight)
    return jsonify(result)

# ============================================================
# ⚙️ COMANDOS E EXECUÇÃO
# ============================================================

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
ADMIN_NAME = os.getenv("ADMIN_NAME", "Administrador WeSafe")

def seed_admin_user():
    """
    Garante que exista uma conta de administrador — mas nunca com credenciais previsíveis.
    Se ADMIN_EMAIL/ADMIN_PASSWORD não estiverem definidos (ou a senha for fraca), nenhuma
    conta admin.com/admin123 é criada silenciosamente: geramos uma senha aleatória forte
    e a mostramos UMA única vez no log, para você trocar/guardar em local seguro.
    """
    if not ADMIN_EMAIL or not is_valid_email(ADMIN_EMAIL):
        app.logger.warning(
            "ADMIN_EMAIL não definido (ou inválido) — nenhuma conta de administrador padrão "
            "foi criada. Defina ADMIN_EMAIL e ADMIN_PASSWORD no .env se quiser um admin automático."
        )
        return None

    existing = db.session.execute(
        db.select(User).filter_by(email=ADMIN_EMAIL)
    ).scalar_one_or_none()

    if existing:
        if not existing.is_admin:
            existing.is_admin = True
            db.session.commit()
        return existing

    password = ADMIN_PASSWORD
    generated = False
    if not password or len(password) < 10:
        password = secrets.token_urlsafe(16)
        generated = True

    admin = User(nome=ADMIN_NAME, email=ADMIN_EMAIL, is_admin=True)
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()

    if generated:
        app.logger.warning(
            f"ADMIN_PASSWORD ausente/fraca — conta de administrador criada com senha ALEATÓRIA "
            f"gerada agora (mostrada só desta vez): {password}  "
            f"Guarde-a e troque-a depois. Defina ADMIN_PASSWORD forte no .env para evitar isso."
        )
    else:
        app.logger.info(f"Conta de administrador criada: {ADMIN_EMAIL}")
    return admin

@app.cli.command("init-db")
def init_db_command():
    """flask --app app.py init-db"""
    with app.app_context():
        db.create_all()
        seed_admin_user()
        print("Banco criado / atualizado (sqlite:///wesafe.db).")
        print(f"Admin: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")

with app.app_context():
    db.create_all()
    seed_admin_user()

    # Diagnóstico de startup: mostra SE o SMTP foi carregado do .env, nunca a senha em si.
    if app.config["SMTP_HOST"]:
        app.logger.info(
            f"SMTP configurado: host={app.config['SMTP_HOST']} porta={app.config['SMTP_PORT']} "
            f"user={app.config['SMTP_USER'] or '(vazio)'} seguranca={app.config['SMTP_SECURITY']}"
        )
    else:
        app.logger.warning(
            f"SMTP_HOST está vazio — o backend NÃO vai enviar OTP por email. "
            f"Arquivo .env procurado em: {_ENV_PATH} (existe: {_ENV_PATH.exists()}). "
            f"Confirme que SMTP_HOST está definido exatamente nesse arquivo."
        )

if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "false").strip().lower() in ("1", "true", "yes")
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    app.run(debug=debug_mode, host=host, port=port)