# Sistema de Monitoramento de Radiação UV com Flask (unificado)

from flask import Flask, render_template, request, jsonify, render_template_string
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from apscheduler.schedulers.background import BackgroundScheduler
from flask_cors import CORS
from datetime import datetime
import requests
import re
import os
import math
import pandas as pd
from sqlalchemy import create_engine, text
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

# ===================== Build / Diagnóstico =====================
APP_BUILD = "build-2025-10-05-uvmax+uvnow+regiao+fallback"

# ===================== App/Base =====================
app = Flask(__name__, static_folder="static", static_url_path="/static")
app.url_map.strict_slashes = False
CORS(app)
app.secret_key = "cadastro"
serializer = URLSafeTimedSerializer(app.secret_key)

def make_unsub_token(email: str) -> str:
    return serializer.dumps({"email": email}, salt="unsub")

def load_unsub_token(token: str, max_age=60*60*24*7):     # expira em 7 dias
    return serializer.loads(token, salt="unsub", max_age=max_age)
app.config["TEMPLATES_AUTO_RELOAD"] = True

# ===================== Banco (SQLAlchemy - e-mails) =====================
app.config["SQLALCHEMY_DATABASE_URI"] = "mysql+mysqlconnector://root:Kauan1807%40@localhost:3306/tcc_emails"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# ===================== Engine (SQLAlchemy - gráficos TCC) =====================
ENGINE_TCC = create_engine(
    "mysql+mysqlconnector://root:Kauan1807%40@localhost:3306/tcc",
    pool_pre_ping=True,)

# ===================== E-mail =====================
app.config["MAIL_SERVER"] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 587
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USERNAME"] = "radiacaouv123@gmail.com"
app.config["MAIL_PASSWORD"] = "hxauakmvbaaxlvfx"
mail = Mail(app)

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:5051")

# ===================== Modelo =====================
class Email(db.Model):
    __tablename__ = "emails_clientes"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)

with app.app_context():
    db.create_all()

# ===================== Headers de Cache =====================
@app.after_request
def add_header(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# ===================== Rotas básicas =====================
@app.get("/")
def home():
    return render_template("index.html")

@app.get("/ping")
def ping():
    return "pong", 200

if os.getenv("ENABLE_DIAG_ROUTES") == "1":
    @app.get("/__routes")
    def __routes():
        return {"routes": [str(r) for r in app.url_map.iter_rules()]}, 200

    @app.get("/__whoami")
    def __whoami():
        return f"OK | file={os.path.abspath(__file__)} | build={APP_BUILD}", 200

    @app.get("/__versions")
    def __versions():
        import sqlalchemy, pandas
        return jsonify({
            "build": APP_BUILD,
            "pandas": pandas.__version__,
            "sqlalchemy": sqlalchemy.__version__
        }), 200

# ===================== Helpers =====================
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def render_email(uv_max, uv_now, nivel_max, descadastro_link, regiao=None):
    """
    Renderiza o HTML do e-mail com:
      - uv_max: pico do dia
      - uv_now: valor instantâneo (/uvi)
      - nivel_max: texto de orientação baseado no uv_max (ou uv_now se uv_max indisponível)
      - regiao: "Cidade – Estado"
    """
    with open("email/email.html", "r", encoding="utf-8") as f:
        template_str = f.read()
    return render_template_string(
        template_str,
        uv_max=uv_max,
        uv_now=uv_now,
        nivel_max=nivel_max.replace("\n", "<br>"),
        descadastro_link=descadastro_link,
        regiao=regiao,
    )

def consulta_uv_agora(latitude, longitude):
    """Valor instantâneo (pode ser diferente do pico do dia)."""
    api_key = "3f59fb330add1cfad36119abb1e4d8cb"
    url = f"https://api.openweathermap.org/data/2.5/uvi?lat={latitude}&lon={longitude}&appid={api_key}"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        v = data.get("value")
        return float(v) if v is not None else None
    except Exception as e:
        print(f"[consulta_uv_agora] erro: {e}")
        return None

def _uv_daily_max_from_uvi_forecast(lat: float, lon: float, api_key: str) -> float | None:
    """
    Fallback usando /data/2.5/uvi/forecast (grátis).
    Retorna o máximo do dia UTC; se não houver itens do dia, usa o máximo geral.
    """
    try:
        r = requests.get(
            "https://api.openweathermap.org/data/2.5/uvi/forecast",
            params={"lat": lat, "lon": lon, "appid": api_key, "cnt": 8},
            timeout=10,
        )
        r.raise_for_status()
        arr = r.json()  # lista de {lat, lon, date_iso, value}
        if not isinstance(arr, list) or not arr:
            return None

        today_utc = datetime.utcnow().date().isoformat()  # 'YYYY-MM-DD'
        todays = []
        for item in arr:
            v = item.get("value")
            d = item.get("date_iso") or ""
            if v is None:
                continue
            if d[:10] == today_utc:
                todays.append(float(v))

        values = todays if todays else [float(x.get("value")) for x in arr if x.get("value") is not None]
        return max(values) if values else None
    except Exception as e:
        print(f"[_uv_daily_max_from_uvi_forecast] erro: {e}")
        return None

def consulta_uv_daily_max(latitude, longitude):
    """
    UV máximo de hoje. Tenta One Call (/data/2.5/onecall).
    Se 401/403/qualquer erro, faz fallback para /data/2.5/uvi/forecast.
    """
    api_key = "3f59fb330add1cfad36119abb1e4d8cb"

    # Tenta One Call (muitos planos exigem assinatura para este endpoint)
    try:
        r = requests.get(
            "https://api.openweathermap.org/data/2.5/onecall",
            params={
                "lat": latitude,
                "lon": longitude,
                "exclude": "minutely,hourly,alerts",
                "appid": api_key,
            },
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        uvi = (data.get("daily") or [{}])[0].get("uvi")
        if uvi is not None:
            return float(uvi)
        else:
            print("[consulta_uv_daily_max] onecall sem daily[0].uvi; usando fallback /uvi/forecast")
            return _uv_daily_max_from_uvi_forecast(latitude, longitude, api_key)

    except requests.HTTPError as he:
        code = getattr(he.response, "status_code", None)
        print(f"[consulta_uv_daily_max] One Call falhou ({code}); usando fallback /uvi/forecast")
        return _uv_daily_max_from_uvi_forecast(latitude, longitude, api_key)
    except Exception as e:
        print(f"[consulta_uv_daily_max] erro inesperado One Call: {e}; usando fallback /uvi/forecast")
        return _uv_daily_max_from_uvi_forecast(latitude, longitude, api_key)

def texto_nivel(uv):
    """Retorna o texto de orientação conforme o valor do UV."""
    if uv is None:
        return "⚠️ Não foi possível consultar o índice UV no momento. Continue se protegendo!"
    if uv >= 11:
        return (
            "🌡️ Extremamente alto! O índice UV está perigosamente elevado.\n\n"
            "⚠️ Riscos: Queimaduras em menos de 10 minutos, risco alto de câncer de pele e danos aos olhos.\n\n"
            "📌 Cuidados essenciais:\n"
            "- Evite sair ao sol entre 10h e 16h.\n"
            "- Use protetor solar FPS 50+ e reaplique a cada 2 horas.\n"
            "- Use chapéu de aba larga, óculos escuros com proteção UV e roupas com proteção solar.\n"
            "- Busque sombra sempre que possível.\n"
            "- Crianças e idosos devem evitar exposição direta.\n\n"
            "🛑 Se puder, permaneça em locais cobertos durante esse período."
        )
    if uv >= 8:
        return (
            "⚠️ Muito alto! O índice UV está elevado e pode causar danos sérios à pele e aos olhos.\n\n"
            "📌 Cuidados recomendados:\n"
            "- Evite exposição direta ao sol entre 10h e 16h.\n"
            "- Use protetor solar com FPS 30+ e reaplique a cada 2 horas.\n"
            "- Use chapéu, boné ou guarda-sol ao sair.\n"
            "- Use óculos escuros com proteção UV.\n"
            "- Prefira roupas de manga longa e tecidos leves.\n\n"
            "🚸 Crianças, idosos e pessoas com pele clara devem redobrar os cuidados."
        )
    if uv >= 6:
        return (
            "🌞 Alto! O índice UV pode causar danos à pele e aos olhos em exposições prolongadas.\n\n"
            "📌 Dicas de proteção:\n"
            "- Evite exposição direta ao sol entre 10h e 16h.\n"
            "- Use protetor solar com FPS 30+ mesmo em dias nublados.\n"
            "- Use boné, óculos escuros e roupas leves que cubram a pele.\n"
            "- Prefira ambientes com sombra e mantenha-se hidratado.\n\n"
            "📣 Fique atento(a): mesmo níveis altos podem causar danos cumulativos à pele com o tempo."
        )
    if uv >= 3:
        return (
            "🧴 Moderado. O índice UV está dentro de níveis aceitáveis, mas ainda requer atenção.\n\n"
            "📌 Dicas de proteção:\n"
            "- Use protetor solar com FPS 15+ se for se expor ao sol por longos períodos.\n"
            "- Prefira ficar na sombra entre 10h e 16h.\n"
            "- Use óculos escuros e boné ou chapéu se for sair.\n\n"
            "💡 Dica extra: mesmo em dias nublados, os raios UV continuam presentes!"
        )
    return "✅ Baixo. Ainda assim, proteção nunca é demais!"

# --- Reverse Geocoding (Nominatim / OpenStreetMap) ---
def reverse_geocode_osm(lat: float, lon: float):
    """Consulta o Nominatim e retorna dados do lugar (cidade, bairro, etc.)."""
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "format": "jsonv2",
                "lat": lat,
                "lon": lon,
                "zoom": 14,  # ~ bairro
                "addressdetails": 1,
            },
            headers={
                "User-Agent": f"nosso-tcc/1.0 ({app.config.get('MAIL_USERNAME', 'contact@example.com')})"
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        addr = (data.get("address") or {})

        city = (
            addr.get("city")
            or addr.get("town")
            or addr.get("municipality")
            or addr.get("village")
            or addr.get("hamlet")
        )
        neighbourhood = (
            addr.get("neighbourhood")
            or addr.get("suburb")
            or addr.get("quarter")
        )
        state = addr.get("state") or addr.get("region") or addr.get("state_district")

        return {
            "display_name": data.get("display_name"),
            "city": city,
            "neighbourhood": neighbourhood,
            "state": state,
            "country": addr.get("country"),
            "postcode": addr.get("postcode"),
        }
    except Exception as e:
        print(f"[reverse_geocode_osm] erro: {e}")
        return None

def format_regiao_from_place(place: dict | None, lat: float, lon: float) -> str:
    """Gera string 'Cidade – Estado' com fallback para lat/lon."""
    if place:
        city = place.get("city")
        state = place.get("state")
        if city and state:
            return f"{city} – {state}"
        if city:
            return city
        if state:
            return state
    return f"{lat:.4f}, {lon:.4f}"

# ---------- SQL helper (SEM pandas.read_sql_query) ----------
def run_query(sql: str, params: dict | None = None) -> pd.DataFrame:
    """Executa SQL (SQLAlchemy text) e retorna DataFrame."""
    with ENGINE_TCC.connect() as conn:
        result = conn.execute(text(sql), params or {})
        rows = result.fetchall()
        cols = result.keys()
    return pd.DataFrame(rows, columns=cols)

# ---------- Diagnóstico UV / Localização ----------
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))

def consulta_uv_inspect(latitude, longitude):
    """Chama a API /uvi e retorna também lat/lon que a API usou e a distância."""
    api_key = "3f59fb330add1cfad36119abb1e4d8cb"
    url = f"https://api.openweathermap.org/data/2.5/uvi?lat={latitude}&lon={longitude}&appid={api_key}"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()  # esperado: {lat, lon, date_iso, value}
        api_lat = data.get("lat")
        api_lon = data.get("lon")
        uv = data.get("value")
        dist_km = None
        ok = False
        if api_lat is not None and api_lon is not None:
            dist_km = haversine_km(float(latitude), float(longitude), float(api_lat), float(api_lon))
            ok = (uv is not None) and (dist_km is not None and dist_km <= 5.0)  # tolerância 5 km

        return {
            "input_lat": float(latitude),
            "input_lon": float(longitude),
            "api_lat": api_lat,
            "api_lon": api_lon,
            "distance_km": round(dist_km, 3) if dist_km is not None else None,
            "uv": uv,
            "at": data.get("date_iso") or datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "ok": ok,
            "provider": "openweathermap/uvi",
            "request_url": url,
        }
    except Exception as e:
        return {"error": str(e), "input_lat": latitude, "input_lon": longitude}

# ===================== Cadastro / Descadastro =====================
@app.post("/cadastro_email")
def cadastro_email():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    latitude = data.get("latitude")
    longitude = data.get("longitude")

    if not email or latitude is None or longitude is None:
        return jsonify({"success": False, "message": "Dados incompletos!"}), 400
    if not EMAIL_RE.match(email):
        return jsonify({"success": False, "message": "E-mail inválido."}), 400
    if Email.query.filter_by(email=email).first():
        return jsonify({"success": False, "message": "E-mail já cadastrado."}), 409

    novo_email = Email(email=email, latitude=latitude, longitude=longitude)
    db.session.add(novo_email)
    db.session.commit()

    # Região (cidade – estado) no e-mail de confirmação
    place = reverse_geocode_osm(latitude, longitude)
    regiao = format_regiao_from_place(place, latitude, longitude)

    token = make_unsub_token(email)
    descadastro_link = f"{BASE_URL}/descadastrar?token={token}"


    msg = Message(
        subject=f"Cadastro confirmado - Monitoramento UV ({regiao})",
        sender=app.config["MAIL_USERNAME"],
        recipients=[email],
        body=(
            "Olá! Seu e-mail foi cadastrado com sucesso para receber notificações UV.\n\n"
            f"Sua localização aproximada: {latitude}, {longitude}.\n"
            f"Sua região: {regiao}\n\n"
            "Se quiser parar de receber notificações, clique no link abaixo:\n"
            f"{descadastro_link}"
        ),
    )
    try:
        mail.send(msg)
    except Exception:
        # registra o erro completo no log do servidor (com stacktrace)
        app.logger.exception("Falha ao enviar e-mail de confirmação para %s", email)
        db.session.delete(novo_email)
        db.session.commit()
        return jsonify({
            "success": False,
            "message": "Erro ao processar o envio do e-mail. Tente novamente mais tarde."
    }), 500


    return jsonify({"success": True, "message": "Cadastro feito com sucesso! Verifique seu e-mail."}), 200

@app.route("/descadastrar", methods=["GET", "POST"])
def descadastrar():
    # aceita token via GET (?token=...) ou via JSON/form
    token = (
        request.args.get("token")
        or (request.json or {}).get("token")
        or request.form.get("token")
    )
    if not token:
        return "Token ausente.", 400

    try:
        data = load_unsub_token(token)
        email = (data.get("email") or "").strip()
    except SignatureExpired:
        return "Link expirado. Solicite novo descadastro.", 400
    except BadSignature:
        return "Link inválido.", 400

    registro = Email.query.filter_by(email=email).first()
    if not registro:
        return "E-mail não encontrado ou já descadastrado.", 404

    db.session.delete(registro)
    db.session.commit()
    return "Você foi descadastrado com sucesso. ✅", 200

# ===================== Envio diário =====================
def envia_emails_diarios():
    with app.app_context():
        emails = Email.query.all()
        total_enviados = 0
        total_falhas = 0
        print(f"[envio] Iniciando envio para {len(emails)} emails...")

        for e in emails:
            # Região do destinatário
            place = reverse_geocode_osm(e.latitude, e.longitude)
            regiao = format_regiao_from_place(place, e.latitude, e.longitude)

            # UV pico do dia e UV do momento
            uv_max = consulta_uv_daily_max(e.latitude, e.longitude)
            uv_now = consulta_uv_agora(e.latitude, e.longitude)

            # Recomendações baseadas no MÁXIMO do dia (ou no 'agora' se o máximo não vier)
            base_para_nivel = uv_max if uv_max is not None else uv_now
            nivel_max = texto_nivel(base_para_nivel)

            token = make_unsub_token(e.email)
            descadastro_link = f"{BASE_URL}/descadastrar?token={token}"

            email_html = render_email(
                uv_max=uv_max if uv_max is not None else "Indisponível",
                uv_now=uv_now,  # pode ser None; template imprime vazio/None
                nivel_max=nivel_max,
                descadastro_link=descadastro_link,
                regiao=regiao,
            )

            assunto = f"☀️ Alerta Diário - Índice UV ({regiao})"

            msg = Message(
                subject=assunto,
                sender=app.config["MAIL_USERNAME"],
                recipients=[e.email],
                html=email_html,
            )
            try:
                mail.send(msg)
                total_enviados += 1
                print(f"[envio] [OK]   {e.email} | UVmax={uv_max} | UVagora={uv_now} | {regiao}")
            except Exception as erro:
                total_falhas += 1
                print(f"[envio] [FAIL] {e.email}: {erro}")

        print(f"[envio] Finalizado: {total_enviados} enviados, {total_falhas} falhas.")

@app.get("/testar_envio")
def testar_envio():        
    envia_emails_diarios()
    return "Notificações enviadas com sucesso (teste manual)!"

# ===================== Rotas de diagnóstico (UV + Geocode) =====================
@app.get("/api/debug/geocode")
def debug_geocode():
    """Use: /api/debug/geocode?lat=-23.55&lon=-46.63"""
    try:
        lat = float(request.args.get("lat"))
        lon = float(request.args.get("lon"))
    except Exception:
        return jsonify({"ok": False, "error": "Passe ?lat=...&lon=... válidos"}), 400
    place = reverse_geocode_osm(lat, lon)
    regiao = format_regiao_from_place(place, lat, lon)
    return jsonify({"ok": place is not None, "lat": lat, "lon": lon, "place": place, "regiao": regiao}), 200

@app.get("/api/debug/uv")
def debug_uv():
    """Use: /api/debug/uv?lat=-23.55&lon=-46.63"""
    try:
        lat = float(request.args["lat"])
        lon = float(request.args["lon"])
    except Exception:
        return jsonify({"error": "Informe ?lat=...&lon=... (números)"}), 400
    info = consulta_uv_inspect(lat, lon)
    place = reverse_geocode_osm(lat, lon)
    info["place"] = place
    info["regiao"] = format_regiao_from_place(place, lat, lon)
    return jsonify(info), 200

@app.get("/api/debug/uv/emails")
def debug_uv_emails():
    """Valida até 50 e-mails cadastrados: compara input vs API e mostra distância/UV + cidade/bairro."""
    out = []
    geocache = {}

    for e in Email.query.limit(50).all():
        lat = float(e.latitude)
        lon = float(e.longitude)

        info = consulta_uv_inspect(lat, lon)

        key = (round(lat, 4), round(lon, 4))
        if key not in geocache:
            geocache[key] = reverse_geocode_osm(lat, lon)

        place = geocache[key]
        regiao = format_regiao_from_place(place, lat, lon)

        info.update({
            "email": e.email,
            "place": place,
            "regiao": regiao,
        })
        out.append(info)

    return jsonify(out), 200

# ===================== APIs de Gráficos (TCC) =====================

@app.get("/api/incidencia/anual") # 1) Histórico de incidências por ano (2000–2023)
def incidencia_anual():
    print("[ROUTE] /api/incidencia/anual", APP_BUILD)
    start = int(request.args.get("start", 2000))
    end = int(request.args.get("end", 2023))
    sql = """
        SELECT t.ano, COUNT(*) AS casos
        FROM (
            SELECT CAST(ano_cmpt AS UNSIGNED) AS ano
            FROM incidencia_clima_unificado_stage
            WHERE CAST(ano_cmpt AS UNSIGNED) BETWEEN :start AND :end
        ) t
        GROUP BY t.ano
        ORDER BY t.ano
    """
    df = run_query(sql, {"start": start, "end": end})
    return jsonify(df.to_dict(orient="records")), 200

@app.get("/api/preditivo/anual")  # 2) Preditivo até 2033 (ARIMA | ETS)
def preditivo_anual():
    print("[ROUTE] /api/preditivo/anual", APP_BUILD)
    modelo = (request.args.get("modelo", "ARIMA") or "ARIMA").upper()
    if modelo not in {"ARIMA", "ETS"}:
        modelo = "ARIMA"
    sql = """
        SELECT CAST(year AS UNSIGNED) AS ano, UPPER(model) AS modelo, point, lo95, hi95
        FROM resultadosprevisoes_cancer_pele
        WHERE UPPER(model) = :modelo
        ORDER BY ano
    """
    df = run_query(sql, {"modelo": modelo})
    return jsonify(df.to_dict(orient="records")), 200

@app.get("/api/correlacao/uv-incidencia")  # 3) Correlação UV x Casos
def correlacao_uv():
    print("[ROUTE] /api/correlacao/uv-incidencia", APP_BUILD)
    start = int(request.args.get("start", 2000))
    end = int(request.args.get("end", 2023))
    sql = """
        SELECT 
            t.ano,
            COUNT(*) AS casos,
            NULL AS uv_medio
        FROM (
            SELECT CAST(ano_cmpt AS UNSIGNED) AS ano
            FROM incidencia_clima_unificado_stage
            WHERE CAST(ano_cmpt AS UNSIGNED) BETWEEN :start AND :end
        ) t
        GROUP BY t.ano
        ORDER BY t.ano
    """
    df = run_query(sql, {"start": start, "end": end})
    return jsonify(df.to_dict(orient="records")), 200

# 4) Rota agregadora
@app.get("/api/graficos")
def api_graficos():
    print("[ROUTE] /api/graficos", APP_BUILD)
    start = int(request.args.get("start", 2000))
    end = int(request.args.get("end", 2023))

    incidencia_df = run_query(
        """
        SELECT t.ano, COUNT(*) AS casos
        FROM (
            SELECT CAST(ano_cmpt AS UNSIGNED) AS ano
            FROM incidencia_clima_unificado_stage
            WHERE CAST(ano_cmpt AS UNSIGNED) BETWEEN :start AND :end
        ) t
        GROUP BY t.ano
        ORDER BY t.ano
        """,
        {"start": start, "end": end},
    )

    arima_df = run_query(
        """
        SELECT CAST(year AS UNSIGNED) AS ano, UPPER(model) AS modelo, point, lo95, hi95
        FROM resultadosprevisoes_cancer_pele
        WHERE UPPER(model) = 'ARIMA'
        ORDER BY ano
        """,
        {},
    )

    ets_df = run_query(
        """
        SELECT CAST(year AS UNSIGNED) AS ano, UPPER(model) AS modelo, point, lo95, hi95
        FROM resultadosprevisoes_cancer_pele
        WHERE UPPER(model) = 'ETS'
        ORDER BY ano
        """,
        {},
    )

    corr_df = run_query(
        """
        SELECT 
            t.ano,
            COUNT(*) AS casos,
            NULL AS uv_medio
        FROM (
            SELECT CAST(ano_cmpt AS UNSIGNED) AS ano
            FROM incidencia_clima_unificado_stage
            WHERE CAST(ano_cmpt AS UNSIGNED) BETWEEN :start AND :end
        ) t
        GROUP BY t.ano
        ORDER BY t.ano
        """,
        {"start": start, "end": end},
    )

    return jsonify(
        {
            "incidencia": incidencia_df.to_dict(orient="records"),
            "preditivo": {
                "ARIMA": arima_df.to_dict(orient="records"),
                "ETS": ets_df.to_dict(orient="records"),
            },
            "correlacao": corr_df.to_dict(orient="records"),
        }
    ), 200

# (Opcional) Compat
@app.get("/api/graficos/historico")
def api_graficos_historico():
    with app.test_request_context(f"/api/incidencia/anual?start=2000&end=2023"):
        return incidencia_anual()

# ===================== Scheduler/Boot =====================
scheduler = BackgroundScheduler(daemon=True, timezone="America/Sao_Paulo")

# horário fixo de disparo do e-mail seguindo o fuso horário de Brasília
scheduler.add_job(envia_emails_diarios, "cron", hour=11, minute=30, id="envio_diario_uv")

def log_next_runs():
    for job in scheduler.get_jobs():
        print(f"[scheduler] Job {job.id} -> próximo disparo: {job.next_run_time}")

if __name__ == "__main__":
    print(f"[BOOT] app.py em: {os.path.abspath(__file__)} | build={APP_BUILD}")
    scheduler.start()
    log_next_runs()
    app.run(host="127.0.0.1", port=5051, debug=True, use_reloader=False)
