# ─────────────────────────────────────────────────────────────────────
#  SecretarIA — webhook.py
#  API Python: processa áudio e imagem com Gemini
#  Acessa o mesmo SQLite e Google Agenda do secretaria_cli.py
# ─────────────────────────────────────────────────────────────────────

import subprocess, sys, importlib

_DEPS = {
    "flask":              "flask",
    "google-genai":       "google.genai",
    "python-dotenv":      "dotenv",
    "google-auth":        "google.auth",
    "google-auth-oauthlib":"google_auth_oauthlib",
    "google-api-python-client": "googleapiclient",
}

def _auto_instalar():
    faltando = []
    for pkg, mod in _DEPS.items():
        try:
            importlib.import_module(mod)
        except ImportError:
            faltando.append(pkg)
    if faltando:
        print(f"[SecretarIA] Instalando: {', '.join(faltando)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", *faltando])
        print("[SecretarIA] Instalacao concluida. Reiniciando...\n")
        subprocess.check_call([sys.executable] + sys.argv)
        sys.exit(0)

_auto_instalar()

import os, json, base64, sqlite3, tempfile, re, logging, hashlib, secrets
from pathlib        import Path
from datetime       import datetime, timedelta
from flask          import Flask, request, jsonify
from dotenv         import load_dotenv
from google         import genai as genai_sdk
from google.oauth2.credentials          import Credentials
from google.auth.transport.requests     import Request
from googleapiclient.discovery          import build
from google_auth_oauthlib.flow          import Flow

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("SecretarIA")

BASE_DIR = Path(__file__).parent
for nome in [".env", ".env.txt", "file.env.txt", "file.env"]:
    p = BASE_DIR / nome
    if p.exists():
        load_dotenv(dotenv_path=p, override=True)
        break

GEMINI_KEY   = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash-lite"
DB_PATH      = BASE_DIR / "secretaria.db"
TOKENS_DIR   = BASE_DIR / "tokens"
SCOPES       = ["https://www.googleapis.com/auth/calendar"]

if not GEMINI_KEY:
    log.error("GEMINI_API_KEY nao encontrada! Verifique seu arquivo .env")
    sys.exit(1)

log.info(f"Gemini configurado | Modelo: {GEMINI_MODEL} | Key: {GEMINI_KEY[:8]}...")
app = Flask(__name__)

# ── DB ────────────────────────────────────────────────────────────────
def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def gerar_hash(senha, salt=None):
    if salt is None:
        salt = secrets.token_hex(32)
    chave = hashlib.pbkdf2_hmac(
        "sha256", senha.encode("utf-8"), salt.encode("utf-8"), iterations=390_000
    ).hex()
    return chave, salt

def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                nome             TEXT    NOT NULL,
                data_nasc        TEXT    NOT NULL,
                telefone         TEXT    NOT NULL,
                email            TEXT    UNIQUE NOT NULL,
                senha_hash       TEXT    NOT NULL,
                salt             TEXT    NOT NULL,
                google_conectado INTEGER DEFAULT 0,
                criado_em        DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS categorias (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER NOT NULL,
                nome       TEXT    NOT NULL,
                padrao     INTEGER DEFAULT 0,
                UNIQUE(usuario_id, nome),
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tetos (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id   INTEGER NOT NULL,
                categoria_id INTEGER,
                valor        REAL    NOT NULL,
                mes          TEXT    NOT NULL,
                FOREIGN KEY (usuario_id)   REFERENCES usuarios(id),
                FOREIGN KEY (categoria_id) REFERENCES categorias(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gastos (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id   INTEGER NOT NULL,
                categoria_id INTEGER NOT NULL,
                descricao    TEXT    NOT NULL,
                valor        REAL    NOT NULL,
                data         TEXT    NOT NULL,
                criado_em    DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (usuario_id)   REFERENCES usuarios(id),
                FOREIGN KEY (categoria_id) REFERENCES categorias(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cartoes (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id    INTEGER NOT NULL,
                banco         TEXT    NOT NULL,
                ultimos4      TEXT    NOT NULL,
                limite        REAL    NOT NULL,
                dia_venc      INTEGER NOT NULL,
                dia_fecha     INTEGER NOT NULL,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
            )
        """)
        try:
            conn.execute("ALTER TABLE gastos ADD COLUMN cartao_id INTEGER REFERENCES cartoes(id)")
        except sqlite3.OperationalError:
            pass
        
        # Migrações adicionais para lembrete e fuso
        for col, col_type in [("timezone", "TEXT DEFAULT 'America/Sao_Paulo'"), 
                             ("reminder_time", "TEXT DEFAULT '08:00'"),
                             ("ultimo_lembrete", "TEXT")]:
            try:
                conn.execute(f"ALTER TABLE usuarios ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass
        conn.commit()

init_db()

def usuario_por_phone(phone):
    phone_limpo = re.sub(r"\D", "", phone)
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM usuarios WHERE telefone = ?", (phone_limpo,)).fetchone()
    return dict(row) if row else None

def listar_categorias(usuario_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM categorias WHERE usuario_id=? ORDER BY padrao DESC, nome", (usuario_id,)
        ).fetchall()
    return [dict(r) for r in rows]

def garantir_categorias_padrao(usuario_id):
    PADRAO = ["Alimentacao", "Transporte", "Saude", "Lazer", "Outros"]
    with get_conn() as conn:
        for nome in PADRAO:
            conn.execute("INSERT OR IGNORE INTO categorias (usuario_id, nome, padrao) VALUES (?,?,1)", (usuario_id, nome))
        conn.commit()

def salvar_gasto(usuario_id, categoria_id, descricao, valor, data=None, cartao_id=None):
    data = data or datetime.now().strftime("%Y-%m-%d")
    with get_conn() as conn:
        conn.execute("INSERT INTO gastos (usuario_id, categoria_id, descricao, valor, data, cartao_id) VALUES (?,?,?,?,?,?)",
                     (usuario_id, categoria_id, descricao, valor, data, cartao_id))
        conn.commit()

def buscar_cartao_por_nome(usuario_id, nome_banco):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM cartoes WHERE usuario_id=?", (usuario_id,)).fetchall()
        for r in rows:
            if nome_banco.lower() in r["banco"].lower():
                return dict(r)
    return None

def calcular_mes_fatura(dia_compra, mes_compra, ano_compra, dia_fecha):
    if dia_compra <= dia_fecha:
        return mes_compra, ano_compra
    else:
        m = mes_compra + 1
        a = ano_compra
        if m > 12:
            m = 1
            a += 1
        return m, a

def buscar_teto_geral(usuario_id):
    mes = datetime.now().strftime("%Y-%m")
    with get_conn() as conn:
        row = conn.execute("SELECT valor FROM tetos WHERE usuario_id=? AND categoria_id IS NULL AND mes=?", (usuario_id, mes)).fetchone()
        if row: return row["valor"]
        row = conn.execute("SELECT valor FROM tetos WHERE usuario_id=? AND categoria_id IS NULL AND mes='*'", (usuario_id,)).fetchone()
    return row["valor"] if row else None

def salvar_teto(usuario_id, valor, categoria_id=None, mes="*"):
    with get_conn() as conn:
        if categoria_id:
            conn.execute("DELETE FROM tetos WHERE usuario_id=? AND categoria_id=? AND mes=?", (usuario_id, categoria_id, mes))
        else:
            conn.execute("DELETE FROM tetos WHERE usuario_id=? AND categoria_id IS NULL AND mes=?", (usuario_id, mes))
        conn.execute("INSERT INTO tetos (usuario_id, categoria_id, valor, mes) VALUES (?,?,?,?)", (usuario_id, categoria_id, valor, mes))
        conn.commit()

def resumo_gastos_mes(usuario_id):
    mes = datetime.now().strftime("%Y-%m")
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT c.nome, SUM(g.valor) as total
            FROM gastos g JOIN categorias c ON c.id = g.categoria_id
            WHERE g.usuario_id=? AND strftime('%Y-%m', g.data)=?
            GROUP BY c.nome ORDER BY total DESC
        """, (usuario_id, mes)).fetchall()
    return [dict(r) for r in rows]

def resumo_gastos_mes_com_id(usuario_id):
    mes = datetime.now().strftime("%Y-%m")
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT c.id, c.nome, SUM(g.valor) as total
            FROM gastos g JOIN categorias c ON c.id = g.categoria_id
            WHERE g.usuario_id=? AND strftime('%Y-%m', g.data)=?
            GROUP BY c.id, c.nome ORDER BY total DESC
        """, (usuario_id, mes)).fetchall()
    return [dict(r) for r in rows]

def listar_gastos_cat(usuario_id, categoria_id, mes):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT descricao, valor, data FROM gastos
            WHERE usuario_id=? AND categoria_id=? AND strftime('%Y-%m', data)=?
            ORDER BY data DESC LIMIT 3
        """, (usuario_id, categoria_id, mes)).fetchall()
    return [dict(r) for r in rows]

def buscar_teto_cat(usuario_id, categoria_id, mes):
    with get_conn() as conn:
        row = conn.execute("SELECT valor FROM tetos WHERE usuario_id=? AND categoria_id=? AND mes=?", (usuario_id, categoria_id, mes)).fetchone()
        if row: return row["valor"]
        row = conn.execute("SELECT valor FROM tetos WHERE usuario_id=? AND categoria_id=? AND mes='*'", (usuario_id, categoria_id)).fetchone()
    return row["valor"] if row else None

def listar_cartoes(usuario_id):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM cartoes WHERE usuario_id=? ORDER BY banco", (usuario_id,)).fetchall()
    return [dict(r) for r in rows]

def gastos_cartao(usuario_id, cartao_id, mes):
    with get_conn() as conn:
        row = conn.execute("""
            SELECT SUM(valor) as total FROM gastos
            WHERE usuario_id=? AND cartao_id=? AND strftime('%Y-%m', data)=?
        """, (usuario_id, cartao_id, mes)).fetchone()
    return row["total"] or 0.0

# ── Google Agenda ─────────────────────────────────────────────────────
def get_google_service(usuario_id):
    token_path = TOKENS_DIR / f"token_{usuario_id}.json"
    if not token_path.exists(): return None
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json())
    return build("calendar", "v3", credentials=creds)

def listar_eventos(service, inicio, fim):
    result = service.events().list(
        calendarId="primary",
        timeMin=inicio.isoformat()+"Z", timeMax=fim.isoformat()+"Z",
        singleEvents=True, orderBy="startTime"
    ).execute()
    return result.get("items", [])

def parse_google_datetime(dt_str):
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is not None:
            dt = dt.astimezone(None).replace(tzinfo=None)
        return dt
    except Exception:
        try:
            return datetime.strptime(dt_str[:10], "%Y-%m-%d")
        except Exception:
            return None

def formatar_evento(e):
    inicio = e["start"].get("dateTime") or e["start"].get("date","")
    dt = parse_google_datetime(inicio)
    if dt:
        # Mapeamento de dias em português
        dias_pt = {'Mon': 'Seg', 'Tue': 'Ter', 'Wed': 'Qua', 'Thu': 'Qui', 'Fri': 'Sex', 'Sat': 'Sáb', 'Sun': 'Dom'}
        dia_fmt = dt.strftime("%a %d/%m %H:%M")
        for en, pt in dias_pt.items():
            dia_fmt = dia_fmt.replace(en, pt)
        return f"{dia_fmt} — {e.get('summary','(sem titulo)')}"
    return f"{inicio} — {e.get('summary','(sem titulo)')}"

# ── Gemini ────────────────────────────────────────────────────────────
def gemini_gerar(prompt, partes_extra=None, tentativas=3):
    """Chama o Gemini com retry automático em caso de falha transitória."""
    import time
    ultimo_erro = None
    for tentativa in range(1, tentativas + 1):
        try:
            with genai_sdk.Client(api_key=GEMINI_KEY) as client:
                conteudo = [prompt] + (partes_extra or [])
                resp = client.models.generate_content(model=GEMINI_MODEL, contents=conteudo)
            return resp.text.strip()
        except Exception as e:
            ultimo_erro = e
            log.warning(f"[Gemini] Tentativa {tentativa}/{tentativas} falhou: {type(e).__name__}: {e}")
            if tentativa < tentativas:
                time.sleep(2 ** (tentativa - 1))  # backoff: 1s, 2s
    raise ultimo_erro

def limpar_json(raw):
    raw = raw.strip()
    # Tenta extrair JSON entre ```json ... ``` ou ``` ... ```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Fallback: extrai o primeiro objeto JSON encontrado no texto
    m2 = re.search(r"\{.*\}", raw, re.DOTALL)
    return m2.group(0).strip() if m2 else raw

def obter_agora():
    from datetime import datetime, timezone, timedelta
    fuso = timezone(timedelta(hours=-3))
    return datetime.now(fuso).replace(tzinfo=None)

def normalizar_data(data_str):
    """Converte data de qualquer formato para DD/MM/AAAA.
    Aceita: DD/MM/AAAA, AAAA-MM-DD (ISO), AAAA/MM/DD, DD/MM, hoje, amanhã, etc.
    """
    if not data_str:
        return None
    s = str(data_str).strip().lower()
    
    # Fallbacks para palavras comuns
    if s in ["hoje", "today"]:
        return obter_agora().strftime("%d/%m/%Y")
    if s in ["amanhã", "amanha", "tomorrow"]:
        from datetime import timedelta
        return (obter_agora() + timedelta(days=1)).strftime("%d/%m/%Y")
        
    # Já está no formato correto DD/MM/AAAA
    if re.match(r'^\d{2}/\d{2}/\d{4}$', s):
        return s
        
    # DD-MM-YYYY, DD/MM/YYYY, DD.MM.YYYY
    m = re.match(r'^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})', s)
    if m:
        d = m.group(1).zfill(2)
        m_val = m.group(2).zfill(2)
        y = m.group(3)
        if len(y) == 2:
            y = "20" + y
        return f"{d}/{m_val}/{y}"
        
    # YYYY-MM-DD, YYYY/MM/DD
    m = re.match(r'^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})', s)
    if m:
        y = m.group(1)
        m_val = m.group(2).zfill(2)
        d = m.group(3).zfill(2)
        return f"{d}/{m_val}/{y}"
        
    # DD/MM (sem ano)
    m = re.match(r'^(\d{1,2})[-/.](\d{1,2})$', s)
    if m:
        d = m.group(1).zfill(2)
        m_val = m.group(2).zfill(2)
        y = str(obter_agora().year)
        return f"{d}/{m_val}/{y}"
        
    return None

def normalizar_hora(hora_str):
    """Converte hora de qualquer formato para HH:MM.
    Aceita: HH:MM, HH:MM:SS, HHhMM, HHh, HH.
    """
    if not hora_str:
        return "09:00"
    s = str(hora_str).strip().lower()
    m = re.match(r'^(\d{1,2}):(\d{2})', s)
    if m:
        return f"{m.group(1).zfill(2)}:{m.group(2)}"
    m = re.match(r'^(\d{1,2})h(\d{2})?', s)
    if m:
        h = m.group(1).zfill(2)
        min_val = m.group(2) or "00"
        return f"{h}:{min_val}"
    m = re.match(r'^(\d{1,2})$', s)
    if m:
        return f"{m.group(1).zfill(2)}:00"
    return "09:00"

def gemini_resposta_livre(texto, user):
    """Responde a mensagens de conversa geral, cumprimentos e perguntas genéricas."""
    prompt = (
        f"Você é a SecretarIA, assistente pessoal de {user['nome']}. "
        f"Responda de forma amigável, direta e em português brasileiro.\n\n"
        f"Mensagem do usuário: {texto}"
    )
    return gemini_gerar(prompt)

# ── Agenda endpoints ──────────────────────────────────────────────────
@app.route("/agenda/hoje", methods=["POST"])
def agenda_hoje():
    req_json = request.json or {}
    phone = req_json.get("phone","")
    dados = req_json.get("dados") or {}
    user  = usuario_por_phone(phone)
    if not user: return jsonify({"texto":"Numero nao cadastrado."})
    service = get_google_service(user["id"])
    if not service: return jsonify({"texto":"Google Agenda nao conectado."})
    
    hoje_dt = datetime.now()
    alvo_dt = hoje_dt
    
    data_str = dados.get("data")
    if data_str:
        data_normalizada = normalizar_data(data_str)
        if data_normalizada:
            try:
                alvo_dt = datetime.strptime(data_normalizada, "%d/%m/%Y")
            except Exception:
                pass

    inicio = alvo_dt.replace(hour=0,minute=0,second=0,microsecond=0)
    fim = inicio + timedelta(days=1)
    eventos = listar_eventos(service, inicio, fim)
    
    # Determina o nome do dia na resposta
    dias_pt = {'Monday': 'segunda-feira', 'Tuesday': 'terça-feira', 'Wednesday': 'quarta-feira', 
               'Thursday': 'quinta-feira', 'Friday': 'sexta-feira', 'Saturday': 'sábado', 'Sunday': 'domingo'}
    
    if alvo_dt.date() == hoje_dt.date():
        dia_str = "hoje"
    elif alvo_dt.date() == (hoje_dt + timedelta(days=1)).date():
        dia_str = "amanhã"
    else:
        dia_str = f"dia {alvo_dt.strftime('%d/%m/%Y')}"
        
    dia_semana_en = alvo_dt.strftime('%A')
    dia_semana_pt = dias_pt.get(dia_semana_en, dia_semana_en)
    
    if not eventos: 
        return jsonify({"texto": f"Sua agenda de {dia_str} ({dia_semana_pt}) está livre!"})
        
    linhas = [f"Agenda de {dia_str} ({alvo_dt.strftime('%d/%m')} - {dia_semana_pt}):\n"]
    for i,e in enumerate(eventos,1): 
        linhas.append(f"{i}. {formatar_evento(e)}")
    return jsonify({"texto":"\n".join(linhas)})

@app.route("/agenda/semana", methods=["POST"])
def agenda_semana():
    req_json = request.json or {}
    phone = req_json.get("phone","")
    dados = req_json.get("dados") or {}
    user  = usuario_por_phone(phone)
    if not user: return jsonify({"texto":"Numero nao cadastrado."})
    service = get_google_service(user["id"])
    if not service: return jsonify({"texto":"Google Agenda nao conectado."})
    
    hoje_dt = datetime.now()
    alvo_dt = hoje_dt
    
    data_str = dados.get("data")
    if data_str:
        data_normalizada = normalizar_data(data_str)
        if data_normalizada:
            try:
                alvo_dt = datetime.strptime(data_normalizada, "%d/%m/%Y")
            except Exception:
                pass
                
    inicio = alvo_dt.replace(hour=0,minute=0,second=0,microsecond=0)
    eventos = listar_eventos(service, inicio, inicio+timedelta(days=7))
    if not eventos: 
        if alvo_dt.date() == hoje_dt.date():
            return jsonify({"texto":"Nenhum compromisso nos próximos 7 dias!"})
        else:
            return jsonify({"texto":f"Nenhum compromisso a partir de {inicio.strftime('%d/%m/%Y')} nos próximos 7 dias!"})
            
    if alvo_dt.date() == hoje_dt.date():
        titulo_semana = "Agenda da semana:\n"
    else:
        titulo_semana = f"Agenda a partir de {inicio.strftime('%d/%m/%Y')} (7 dias):\n"
        
    linhas = [titulo_semana]
    for i,e in enumerate(eventos,1): 
        linhas.append(f"{i}. {formatar_evento(e)}")
    return jsonify({"texto":"\n".join(linhas)})

@app.route("/agenda/livres", methods=["POST"])
def agenda_livres():
    req_json = request.json or {}
    phone = req_json.get("phone","")
    dados = req_json.get("dados") or {}
    user  = usuario_por_phone(phone)
    if not user: return jsonify({"texto":"Numero nao cadastrado."})
    service = get_google_service(user["id"])
    if not service: return jsonify({"texto":"Google Agenda nao conectado."})
    
    hoje_dt = datetime.now()
    alvo_dt = hoje_dt
    
    data_str = dados.get("data")
    if data_str:
        data_normalizada = normalizar_data(data_str)
        if data_normalizada:
            try:
                alvo_dt = datetime.strptime(data_normalizada, "%d/%m/%Y")
            except Exception:
                pass
                
    inicio_dia = alvo_dt.replace(hour=0,minute=0,second=0,microsecond=0)
    eventos = listar_eventos(service, inicio_dia, inicio_dia + timedelta(days=1))
    ocupados = []
    for e in eventos:
        s = e["start"].get("dateTime")
        f = e["end"].get("dateTime")
        s_dt = parse_google_datetime(s)
        f_dt = parse_google_datetime(f)
        if s_dt and f_dt:
            ocupados.append((s_dt, f_dt))
            
    livre = inicio_dia.replace(hour=8,minute=0)
    if alvo_dt.date() == hoje_dt.date():
        agora_naive = hoje_dt.replace(second=0, microsecond=0)
        livre = max(livre, agora_naive)
        
    fim_dia = inicio_dia.replace(hour=18,minute=0)
    slots = []
    for s,f in sorted(ocupados):
        if livre < s: 
            slots.append(f"• {livre.strftime('%H:%M')} – {s.strftime('%H:%M')}")
        livre = max(livre, f)
    if livre < fim_dia: 
        slots.append(f"• {livre.strftime('%H:%M')} – {fim_dia.strftime('%H:%M')}")
        
    if alvo_dt.date() == hoje_dt.date():
        dia_str = "hoje"
    elif alvo_dt.date() == (hoje_dt + timedelta(days=1)).date():
        dia_str = "amanhã"
    else:
        dia_str = f"no dia {alvo_dt.strftime('%d/%m/%Y')}"
        
    if not slots: 
        return jsonify({"texto": f"Nenhum horário livre {dia_str} (08h-18h)."})
    return jsonify({"texto": f"Horários livres {dia_str}:\n\n" + "\n".join(slots)})

@app.route("/agenda/agendar", methods=["POST"])
def agenda_agendar():
    data  = request.json
    phone = data.get("phone",""); texto = data.get("texto","")
    user  = usuario_por_phone(phone)
    if not user: return jsonify({"texto":"Numero nao cadastrado."})
    
    info = data.get("dados")
    if info:
        if info.get("data"):
            info["data"] = normalizar_data(info["data"]) or info["data"]
            
    if not info or not info.get("titulo") or not info.get("data") or not info.get("hora"):
        hoje_dt = obter_agora()
        hoje = hoje_dt.strftime("%d/%m/%Y")
        hora_atual = hoje_dt.strftime("%H:%M")
        amanha = (hoje_dt + timedelta(days=1)).strftime("%d/%m/%Y")
        # Calcula próxima ocorrência de cada dia da semana (ou hoje se for o próprio dia)
        dias_semana = {}
        nomes_dias = ['segunda', 'terca', 'quarta', 'quinta', 'sexta', 'sabado', 'domingo']
        for i, nome in enumerate(nomes_dias):
            dias_ate = (i - hoje_dt.weekday()) % 7
            dias_semana[nome] = (hoje_dt + timedelta(days=dias_ate)).strftime("%d/%m/%Y")
        
        prompt = f"""Você é um assistente de agendamento profissional do Brasil.
Hoje é {hoje} ({hora_atual}) — Fuso: America/Sao_Paulo.

Referências de datas para hoje:
- "hoje" = {hoje}
- "amanhã" = {amanha}
- "segunda" ou "segunda-feira" = {dias_semana['segunda']}
- "terça" ou "terça-feira" = {dias_semana['terca']}
- "quarta" ou "quarta-feira" = {dias_semana['quarta']}
- "quinta" ou "quinta-feira" = {dias_semana['quinta']}
- "sexta" ou "sexta-feira" = {dias_semana['sexta']}
- "sábado" = {dias_semana['sabado']}
- "domingo" = {dias_semana['domingo']}
- "semana que vem" = some 7 dias a partir da data mencionada
- "próxima [dia]" = o mesmo que o dia da semana acima

Regras de extração:
1. O campo "titulo" DEVE ser específico, capturando nomes de pessoas e contexto completo:
   - "reunião com Warley amanhã às 14h" → titulo: "Reunião com Warley"
   - "dentista na quinta às 10h" → titulo: "Consulta no Dentista"
   - "almoço com equipe de vendas sexta" → titulo: "Almoço com Equipe de Vendas"
   - "call com cliente às 15h" → titulo: "Call com Cliente"
   NUNCA coloque apenas "Reunião", "Compromisso", "Consulta" ou "Evento" sozinhos.
2. A "data" DEVE estar no formato DD/MM/AAAA. Use as referências acima.
3. A "hora" DEVE estar no formato HH:MM (24h). Se não for mencionada, use "09:00".
   - "às 14h" = "14:00"
   - "às 8 da manhã" = "08:00"
   - "de tarde" = "14:00"
   - "de manhã" = "09:00"
4. "duracao" em minutos: padrão 60 se não mencionado.
5. Responda APENAS com JSON válido, sem markdown (sem ```json), sem texto extra.

Formato de resposta:
{{"titulo": "Título específico", "data": "DD/MM/AAAA", "hora": "HH:MM", "duracao": 60, "descricao": ""}}

Texto do usuario: "{texto}"""
        try:
            raw = gemini_gerar(prompt)
            info = json.loads(limpar_json(raw))
            log.info(f"[agendar] Gemini retornou: {info}")
            # Normaliza data que pode vir em formato ISO do Gemini
            if info.get("data"):
                info["data"] = normalizar_data(info["data"]) or info["data"]
        except Exception as e:
            err_msg = str(e).upper()
            if "RESOURCE_EXHAUSTED" in err_msg or "429" in err_msg or "QUOTA" in err_msg:
                return jsonify({"texto": "⚠️ O serviço de Inteligência Artificial (Gemini) está temporariamente congestionado ou o limite de requisições foi atingido. Por favor, aguarde cerca de 1 minuto e tente novamente."})
            log.error(f"[agendar] Erro no Gemini: {e}")
            return jsonify({"texto":'Nao consegui interpretar o agendamento. Tente: "reuniao com Joao sexta as 15h"'})
    
    # Garante hora padrão e normalizada
    info["hora"] = normalizar_hora(info.get("hora"))
    
    try:
        data_normalizada = normalizar_data(info.get('data', ''))
        if not data_normalizada:
            log.error(f"[agendar/parse] Data inválida: {info.get('data')}")
            return jsonify({"texto": f"Nao consegui entender a data '{info.get('data', '')}'. Tente no formato: 'reuniao sexta as 15h'"})
        
        inicio = datetime.strptime(f"{data_normalizada} {info['hora']}", "%d/%m/%Y %H:%M")
        dur = int(info.get("duracao") or 60)
        titulo = info.get("titulo", "Compromisso")
        
        # Mapeamento de dias em inglês para português (retorno do strftime)
        dias_pt = {'Mon': 'Seg', 'Tue': 'Ter', 'Wed': 'Qua', 'Thu': 'Qui', 'Fri': 'Sex', 'Sat': 'Sáb', 'Sun': 'Dom'}
        dia_fmt = inicio.strftime('%a %d/%m às %H:%M')
        for en, pt in dias_pt.items():
            dia_fmt = dia_fmt.replace(en, pt)
        
        return jsonify({
            "texto": (f"📅 Confirmar agendamento?\n\n"
                      f"📌 *{titulo}*\n"
                      f"🕐 {dia_fmt} ({dur} min)\n\n"
                      f"Responda *sim* para confirmar ou *não* para cancelar."),
            "pendente": True, "estado": "AGUARDANDO_CONFIRMAR_AGENDA",
            "dados": {"evento": {"titulo": titulo, "inicio": inicio.isoformat(),
                                 "duracao": dur, "descricao": info.get("descricao","")}}
        })
    except Exception as e:
        log.error(f"[agendar/parse] Erro: {e} | info={info}")
        return jsonify({"texto":'Erro ao processar data/hora. Tente: "reuniao com Joao sexta as 15h"'})

@app.route("/agenda/confirmar", methods=["POST"])
def agenda_confirmar():
    data   = request.json
    phone  = data.get("phone",""); evento = data.get("evento",{})
    user   = usuario_por_phone(phone)
    if not user: return jsonify({"texto":"Numero nao cadastrado."})
    service = get_google_service(user["id"])
    if not service: return jsonify({"texto":"Google Agenda nao conectado."})
    try:
        inicio = datetime.fromisoformat(evento["inicio"])
        fim    = inicio + timedelta(minutes=int(evento.get("duracao",60)))
        body   = {"summary": evento["titulo"], "description": evento.get("descricao",""),
                  "start": {"dateTime": inicio.isoformat(), "timeZone": "America/Sao_Paulo"},
                  "end":   {"dateTime": fim.isoformat(),    "timeZone": "America/Sao_Paulo"}}
        criado = service.events().insert(calendarId="primary", body=body).execute()
        return jsonify({"texto": f"Agendado!\n{criado.get('summary')}\n{inicio.strftime('%a %d/%m as %H:%M')}"})
    except Exception as e:
        log.error(f"[confirmar] {e}")
        return jsonify({"texto":"Erro ao criar evento. Tente novamente."})

@app.route("/agenda/cancelar", methods=["POST"])
def agenda_cancelar():
    data  = request.json
    phone = data.get("phone",""); texto = data.get("texto","")
    user  = usuario_por_phone(phone)
    if not user: return jsonify({"texto":"Numero nao cadastrado."})
    service = get_google_service(user["id"])
    if not service: return jsonify({"texto":"Google Agenda nao conectado."})
    try:
        hoje = datetime.now().replace(hour=0,minute=0,second=0,microsecond=0)
        eventos = listar_eventos(service, hoje, hoje+timedelta(days=7))
        if not eventos: return jsonify({"texto":"Nenhum evento encontrado."})
        lista = "\n".join(f"{i+1}. {formatar_evento(e)}" for i,e in enumerate(eventos))
        raw = gemini_gerar(f'Qual numero corresponde a "{texto}"? Responda APENAS o numero.\n{lista}')
        idx = int(re.search(r"\d+", raw).group()) - 1
        if 0 <= idx < len(eventos):
            service.events().delete(calendarId="primary", eventId=eventos[idx]["id"]).execute()
            return jsonify({"texto": f"Evento '{eventos[idx].get('summary')}' cancelado!"})
        return jsonify({"texto":"Nao identifiquei o evento. Seja mais especifico."})
    except Exception as e:
        log.error(f"[cancelar] {e}")
        return jsonify({"texto":"Erro ao cancelar. Tente novamente."})

# ── Financeiro endpoints ──────────────────────────────────────────────
@app.route("/financeiro/registrar", methods=["POST"])
def financeiro_registrar():
    data      = request.json
    phone     = data.get("phone","")
    valor_total = float(data.get("valor",0))
    descricao = data.get("descricao","Gasto via WhatsApp")
    cat_nome  = data.get("categoria","Outros")
    parcelas  = int(data.get("parcelas", 1))
    cartao_nome = data.get("cartao", "")
    data_compra_str = data.get("data", "")
    
    user = usuario_por_phone(phone)
    if not user: return jsonify({"texto":"Numero nao cadastrado."})
    
    garantir_categorias_padrao(user["id"])
    cats = listar_categorias(user["id"])
    cat  = next((c for c in cats if c["nome"].lower()==cat_nome.lower()),
                next((c for c in cats if c["nome"]=="Outros"), cats[0]))
    
    # Processa data da compra
    if data_compra_str:
        try:
            data_compra = datetime.strptime(data_compra_str, "%d/%m/%Y")
        except Exception:
            data_compra = datetime.now()
    else:
        data_compra = datetime.now()
        
    # Processa cartão de crédito
    cartao_id = None
    mes_inicio = data_compra.month
    ano_inicio = data_compra.year
    
    info_cartao = ""
    if cartao_nome:
        cartao = buscar_cartao_por_nome(user["id"], cartao_nome)
        if cartao:
            cartao_id = cartao["id"]
            mes_inicio, ano_inicio = calcular_mes_fatura(data_compra.day, data_compra.month, data_compra.year, cartao["dia_fecha"])
            info_cartao = f" no cartao {cartao['banco']} (...{cartao['ultimos4']})"
        else:
            info_cartao = f" (cartao '{cartao_nome}' nao cadastrado no sistema, salvo como debito/dinheiro)"

    # Registra gasto (parcelado ou à vista)
    valor_parcela = round(valor_total / parcelas, 2)
    for i in range(parcelas):
        m = mes_inicio + i
        a = ano_inicio
        while m > 12:
            m -= 12
            a += 1
        data_parcela = f"{a}-{str(m).zfill(2)}-{str(data_compra.day).zfill(2)}"
        desc_parcela = descricao if parcelas == 1 else f"{descricao} {i+1}/{parcelas}"
        salvar_gasto(user["id"], cat["id"], desc_parcela, valor_parcela, data_parcela, cartao_id)
        
    teto  = buscar_teto_geral(user["id"])
    total = sum(r["total"] for r in resumo_gastos_mes(user["id"]))
    aviso = ""
    if teto and total > teto:
        aviso = f"\n\nAtencao! Voce ultrapassou o teto de R$ {teto:.2f}!\nTotal: R$ {total:.2f}"
    elif teto and total > teto*0.8:
        aviso = f"\n\nAtencao: {(total/teto*100):.0f}% do teto mensal usado."
        
    if parcelas == 1:
        texto_resp = f"Gasto registrado!\n{descricao}\nR$ {valor_total:.2f} em {cat['nome']}{info_cartao}{aviso}"
    else:
        texto_resp = f"Gasto parcelado registrado!\n{descricao}\n{parcelas}x de R$ {valor_parcela:.2f} (Total: R$ {valor_total:.2f}) em {cat['nome']}{info_cartao}{aviso}"
        
    return jsonify({"texto": texto_resp})

@app.route("/financeiro/resumo", methods=["POST"])
def financeiro_resumo():
    phone = request.json.get("phone","")
    user  = usuario_por_phone(phone)
    if not user: return jsonify({"texto":"Numero nao cadastrado."})
    
    mes_ref = datetime.now().strftime("%Y-%m")
    resumo = resumo_gastos_mes_com_id(user["id"])
    teto   = buscar_teto_geral(user["id"])
    total  = sum(r["total"] for r in resumo)
    
    mes_lbl = datetime.now().strftime("%B de %Y")
    if not resumo: return jsonify({"texto": f"Nenhum gasto registrado em {mes_lbl}."})
    
    linhas = [f"💰 *Resumo Financeiro — {mes_lbl}*\n"]
    if teto:
        saldo = teto - total
        sinal = "✅" if saldo >= 0 else "🚨"
        linhas.append(f"• Teto Mensal: R$ {teto:.2f}")
        linhas.append(f"• Total Gasto: R$ {total:.2f}")
        linhas.append(f"• {sinal} Saldo: R$ {saldo:.2f}" + (" *(ESTOURADO)*" if saldo < 0 else ""))
    else:
        linhas.append(f"• Total Gasto: R$ {total:.2f}")
        linhas.append("_(sem teto geral definido)_")
        
    linhas.append("\n*Detalhamento por Categoria:*")
    for r in resumo:
        tc = buscar_teto_cat(user["id"], r["id"], mes_ref)
        if tc:
            pct = int(r["total"] / tc * 100)
            sinal = "🚨" if pct > 100 else ("⚠️" if pct > 80 else "✅")
            linhas.append(f"{sinal} *{r['nome']}*: R$ {r['total']:.2f} / R$ {tc:.2f} ({pct}%)")
        else:
            linhas.append(f"• *{r['nome']}*: R$ {r['total']:.2f}")
            
        # Lista os 3 últimos gastos dessa categoria
        gastos = listar_gastos_cat(user["id"], r["id"], mes_ref)
        for g in gastos:
            try:
                dt_fmt = datetime.strptime(g["data"], "%Y-%m-%d").strftime("%d/%m")
            except:
                dt_fmt = g["data"]
            linhas.append(f"  _{dt_fmt} - {g['descricao'][:20]} — R$ {g['valor']:.2f}_")
            
    # Cartões de crédito
    cartoes = listar_cartoes(user["id"])
    if cartoes:
        linhas.append("\n*Cartões de Crédito:*")
        for c in cartoes:
            usado = gastos_cartao(user["id"], c["id"], mes_ref)
            pct = int(usado / c["limite"] * 100) if c["limite"] else 0
            sinal = "🚨" if pct > 100 else ("⚠️" if pct > 80 else "✅")
            linhas.append(f"{sinal} {c['banco']} (...{c['ultimos4']}): R$ {usado:.2f} / R$ {c['limite']:.2f} ({pct}%)")
            
    # Insights via Gemini
    if GEMINI_KEY:
        try:
            prompt_insight = (
                f"Analise de forma amigável e direta os gastos do mês de {mes_lbl} para o usuário {user['nome']}.\n"
                f"Forneça no máximo 4 linhas de conselhos, incluindo 1 ponto de atenção e 1 sugestão prática. Não use markdown (apenas negrito padrão com *).\n"
                f"Resumo de Gastos:\n" +
                "\n".join(f"- {r['nome']}: R$ {r['total']:.2f}" for r in resumo) +
                f"\nTotal Gasto: R$ {total:.2f} | Teto: R$ {teto:.2f if teto else 'Não definido'}"
            )
            insight = gemini_gerar(prompt_insight)
            if insight:
                linhas.append(f"\n🤖 *Análise da SecretarIA:*\n{insight}")
        except Exception as e:
            log.error(f"[resumo/gemini] {e}")
            
    return jsonify({"texto": "\n".join(linhas)})

@app.route("/financeiro/teto", methods=["POST"])
def financeiro_teto():
    data  = request.json
    phone = data.get("phone",""); valor = float(data.get("valor",0))
    user  = usuario_por_phone(phone)
    if not user: return jsonify({"texto":"Numero nao cadastrado."})
    salvar_teto(user["id"], valor, mes=datetime.now().strftime("%Y-%m"))
    return jsonify({"texto": f"Teto mensal definido: R$ {valor:.2f}"})

# ── Midia endpoints ───────────────────────────────────────────────────
@app.route("/media/audio", methods=["POST"])
def media_audio():
    phone = request.form.get("phone","")
    file  = request.files.get("file")
    if not file: return jsonify({"texto":"Arquivo de audio nao recebido."})
    user = usuario_por_phone(phone)
    if not user: return jsonify({"texto":"Numero nao cadastrado."})
    
    # mkstemp resolve o problema de permissão no Windows fechando o descritor imediatamente
    fd, temp_path = tempfile.mkstemp(suffix=".ogg")
    os.close(fd)
    try:
        file.save(temp_path)
        tamanho = os.path.getsize(temp_path)
        log.info(f"[audio] Arquivo recebido: {tamanho} bytes | phone: {phone}")
        
        if tamanho < 100:
            log.error(f"[audio] Arquivo muito pequeno ({tamanho} bytes), provavelmente corrompido")
            return jsonify({"texto": "O arquivo de áudio parece estar vazio ou corrompido. Tente gravar novamente."})
        
        from google.genai import types
        data_bytes = Path(temp_path).read_bytes()
        
        # Tenta múltiplos MIME types — WhatsApp/Android usa Opus dentro de OGG
        # O Gemini aceita: audio/ogg, audio/opus, audio/webm, audio/mp4, etc.
        mime_types_tentativas = ["audio/ogg; codecs=opus", "audio/ogg", "audio/opus", "audio/webm"]
        
        hoje_dt = datetime.now()
        hoje = hoje_dt.strftime("%d/%m/%Y")
        hora_atual = hoje_dt.strftime("%H:%M")
        amanha = (hoje_dt + timedelta(days=1)).strftime("%d/%m/%Y")
        dias_semana_refs = {}
        nomes_dias = ['segunda', 'terca', 'quarta', 'quinta', 'sexta', 'sabado', 'domingo']
        for i, nome in enumerate(nomes_dias):
            dias_ate = (i - hoje_dt.weekday()) % 7
            if dias_ate == 0:
                dias_ate = 7
            dias_semana_refs[nome] = (hoje_dt + timedelta(days=dias_ate)).strftime("%d/%m/%Y")
        
        prompt = f"""Você é a SecretarIA, assistente pessoal inteligente do Brasil.
Hoje é {hoje} ({hora_atual}) — Fuso: America/Sao_Paulo.

Referências de datas:
- "hoje" = {hoje}
- "amanhã" = {amanha}
- "segunda" = {dias_semana_refs['segunda']}
- "terça" = {dias_semana_refs['terca']}
- "quarta" = {dias_semana_refs['quarta']}
- "quinta" = {dias_semana_refs['quinta']}
- "sexta" = {dias_semana_refs['sexta']}
- "sábado" = {dias_semana_refs['sabado']}
- "domingo" = {dias_semana_refs['domingo']}

Transcreva o áudio e interprete a intenção do usuário.
Intenções: AGENDAR, VER_HOJE, VER_SEMANA, VER_LIVRE, CANCELAR_EVENTO, REGISTRAR_GASTO, VER_FINANCAS, DEFINIR_TETO, AJUDA

Regras para AGENDAR:
- "titulo" DEVE ser específico com nomes e contexto: "Reunião com Warley", "Consulta no Dentista", "Almoço com Ana".
  NUNCA use apenas "Reunião", "Evento" ou "Compromisso" sozinhos.
- "data" DEVE estar no formato DD/MM/AAAA usando as referências acima.
- "hora" em HH:MM (24h). Se não mencionada, use "09:00".

Responda APENAS com JSON válido, sem markdown, sem texto extra.

Formato:
{{"transcricao": "texto transcrito", "intent": "INTENÇÃO", "dados": {{"titulo": "", "data": "DD/MM/AAAA", "hora": "HH:MM", "duracao": 60, "valor": 0.0, "descricao": "", "categoria": ""}}}}"""
        
        raw = None
        ultimo_erro = None
        for mime in mime_types_tentativas:
            try:
                log.info(f"[audio] Tentando MIME type: {mime}")
                part = types.Part.from_bytes(data=data_bytes, mime_type=mime)
                raw = gemini_gerar(prompt, partes_extra=[part])
                log.info(f"[audio] Sucesso com MIME: {mime}")
                break
            except Exception as e:
                log.warning(f"[audio] Falhou com MIME {mime}: {type(e).__name__}: {e}")
                ultimo_erro = e
        
        if raw is None:
            log.error(f"[audio] Todos os MIME types falharam. Último erro: {ultimo_erro}")
            return jsonify({"texto": "Não consegui processar o áudio. Tente novamente ou envie uma mensagem de texto."})
        
        info = json.loads(limpar_json(raw))
        intent      = info.get("intent","AJUDA")
        dados       = info.get("dados",{})
        transcricao = info.get("transcricao","")
        
        # Normaliza data retornada pelo Gemini
        if dados.get("data"):
            dados["data"] = normalizar_data(dados["data"]) or dados["data"]
        
        log.info(f"[audio] {phone} intent:{intent} | transcricao: '{transcricao[:80]}'")
        return _executar_intent(phone, intent, dados, transcricao, user)
    except Exception as e:
        log.error(f"[audio] Erro inesperado: {type(e).__name__}: {e}")
        import traceback
        log.error(traceback.format_exc())
        return jsonify({"texto":"Nao consegui processar o audio. Tente novamente."})
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

@app.route("/media/imagem", methods=["POST"])
def media_imagem():
    phone = request.form.get("phone","")
    file  = request.files.get("file")
    if not file: return jsonify({"texto":"Imagem nao recebida."})
    user = usuario_por_phone(phone)
    if not user: return jsonify({"texto":"Numero nao cadastrado."})
    
    # mkstemp resolve o problema de permissão no Windows fechando o descritor imediatamente
    fd, temp_path = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    try:
        file.save(temp_path)
        from google.genai import types
        data_bytes = Path(temp_path).read_bytes()
        part = types.Part.from_bytes(data=data_bytes, mime_type="image/jpeg")
        
        prompt = """Analise este recibo/nota fiscal/cupom.
Extraia os dados e responda APENAS JSON valido, sem markdown.
Formato: {"valor_total":0.0,"estabelecimento":"","categoria":"Alimentacao|Transporte|Saude|Lazer|Outros","data":"DD/MM/AAAA","descricao":""}
Se nao for documento financeiro: {"erro":"nao_e_recibo"}"""
        
        raw  = gemini_gerar(prompt, partes_extra=[part])
        info = json.loads(limpar_json(raw))
        if "erro" in info:
            return jsonify({"texto":"Esta imagem nao parece ser um recibo. Mande foto de cupom ou nota fiscal."})
        valor     = float(info.get("valor_total") or 0)
        descricao = info.get("descricao") or info.get("estabelecimento") or "Gasto via foto"
        categoria = info.get("categoria","Outros")
        if valor <= 0:
            return jsonify({"texto":"Nao consegui identificar o valor. Registre: gastei X reais em Y"})
        log.info(f"[imagem] {phone} R${valor:.2f} | {descricao} | {categoria}")
        return jsonify({
            "texto": (f"Recibo identificado!\n\n{descricao}\nR$ {valor:.2f}\nCategoria: {categoria}\n\nConfirmar e registrar? (sim / nao)"),
            "pendente": True, "estado": "AGUARDANDO_CONFIRMAR_GASTO",
            "dados": {"valor": valor, "descricao": descricao, "categoria": categoria}
        })
    except Exception as e:
        log.error(f"[imagem] {e}")
        return jsonify({"texto":"Nao consegui ler o recibo. Tente foto mais nitida."})
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

def _executar_intent(phone, intent, dados, transcricao, user, com_prefixo=True):
    prefixo = f'"{transcricao[:80]}{"..." if len(transcricao)>80 else ""}"\n\n' if com_prefixo else ""
    try:
        with app.test_client() as c:
            if intent == "VER_HOJE":
                txt = c.post("/agenda/hoje", json={"phone":phone, "dados":dados}).get_json()["texto"]
                return jsonify({"texto": prefixo+txt})
            elif intent == "VER_SEMANA":
                txt = c.post("/agenda/semana", json={"phone":phone, "dados":dados}).get_json()["texto"]
                return jsonify({"texto": prefixo+txt})
            elif intent == "VER_LIVRE":
                txt = c.post("/agenda/livres", json={"phone":phone, "dados":dados}).get_json()["texto"]
                return jsonify({"texto": prefixo+txt})
            elif intent == "AGENDAR":
                res = c.post("/agenda/agendar", json={"phone":phone,"texto":transcricao,"dados":dados}).get_json()
                res["texto"] = prefixo + res.get("texto","")
                return jsonify(res)
            elif intent == "CANCELAR_EVENTO":
                txt = c.post("/agenda/cancelar", json={"phone":phone,"texto":transcricao}).get_json()["texto"]
                return jsonify({"texto": prefixo+txt})
            elif intent == "REGISTRAR_GASTO":
                valor = float(dados.get("valor") or 0)
                desc  = dados.get("descricao") or transcricao[:60]
                cat   = dados.get("categoria","Outros")
                if valor > 0:
                    return jsonify({"texto": prefixo+f"Confirmar gasto?\n{desc}\nR$ {valor:.2f} ({cat})\n(sim / nao)",
                                    "pendente":True,"estado":"AGUARDANDO_CONFIRMAR_GASTO",
                                    "dados":{"valor":valor,"descricao":desc,"categoria":cat}})
                return jsonify({"texto": prefixo+"Qual foi o valor do gasto? (ex: 45.90)",
                                "pendente":True,"estado":"AGUARDANDO_VALOR_GASTO","dados":{"descricao":desc}})
            elif intent == "VER_FINANCAS":
                txt = c.post("/financeiro/resumo", json={"phone":phone}).get_json()["texto"]
                return jsonify({"texto": prefixo+txt})
            elif intent == "DEFINIR_TETO":
                valor = float(dados.get("valor") or 0)
                if valor > 0:
                    txt = c.post("/financeiro/teto", json={"phone":phone,"valor":valor}).get_json()["texto"]
                    return jsonify({"texto": prefixo+txt})
                return jsonify({"texto": prefixo+"Qual o valor do teto mensal? (ex: 3000)",
                                "pendente":True,"estado":"AGUARDANDO_VALOR_TETO","dados":{}})
            else:
                return jsonify({"texto": prefixo+"Nao entendi. Diga ajuda para ver opcoes."})
    except Exception as e:
        log.error(f"[intent] {e}")
        return jsonify({"texto": prefixo+"Erro ao executar. Tente novamente."})

# ── Onboarding Endpoints ──────────────────────────────────────────────
CREDENTIALS_FILE = BASE_DIR / "credentials.json"

def obter_redirect_uri():
    # 1. Se configurado no .env, usa ele
    env_uri = os.getenv("OAUTH_REDIRECT_URI", "").strip() or os.getenv("OAUTH_REDIRECT_URL", "").strip()
    if env_uri:
        return env_uri
        
    # 2. Caso contrário, lê de credentials.json
    if CREDENTIALS_FILE.exists():
        try:
            with open(str(CREDENTIALS_FILE)) as f:
                secret_json = json.load(f)
                client_type = "installed" if "installed" in secret_json else "web"
                client_info = secret_json[client_type]
                uris = client_info.get("redirect_uris", [])
                if uris:
                    return uris[0]
        except Exception as e:
            log.error(f"[obter_redirect_uri] Erro ao ler credentials.json: {e}")
            
    # 3. Fallback final
    return "http://localhost:8080"

@app.route("/", methods=["GET"])
def oauth_callback():
    code = request.args.get("code")
    phone = request.args.get("state")  # state contém o telefone do usuário
    
    if not code or not phone:
        return "SecretarIA API Online", 200

    try:
        import urllib.request, urllib.parse
        
        # 1. Busca o usuário no banco pelo telefone
        user = usuario_por_phone(phone)
        if not user:
            return "Erro: Usuario nao cadastrado para este telefone.", 400
            
        # 2. Carrega dados do credentials.json
        if not CREDENTIALS_FILE.exists():
            return "Erro: Arquivo credentials.json nao encontrado no servidor.", 500
            
        with open(str(CREDENTIALS_FILE)) as f:
            secret_json = json.load(f)
            client_type = "installed" if "installed" in secret_json else "web"
            client_info = secret_json[client_type]
            
        redirect_uri = obter_redirect_uri()
            
        # 3. Faz a requisição de troca de token
        params = {
            "code": code,
            "client_id": client_info["client_id"],
            "client_secret": client_info["client_secret"],
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code"
        }
        post_data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=post_data, method="POST")
        
        with urllib.request.urlopen(req) as response:
            tokens_resp = json.loads(response.read().decode("utf-8"))
            
        # 4. Cria as Credenciais do Google no formato esperado
        creds = Credentials(
            token=tokens_resp.get("access_token"),
            refresh_token=tokens_resp.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_info["client_id"],
            client_secret=client_info["client_secret"],
            scopes=SCOPES
        )
            
        # 5. Salva o token na pasta tokens/
        if not TOKENS_DIR.exists():
            TOKENS_DIR.mkdir(parents=True, exist_ok=True)
            
        token_path = TOKENS_DIR / f"token_{user['id']}.json"
        token_path.write_text(creds.to_json())
            
        # 6. Atualiza o banco de dados
        with get_conn() as conn:
            conn.execute("UPDATE usuarios SET google_conectado=1 WHERE id=?", (user["id"],))
            conn.commit()
            
        # 7. Notifica o bot Node.js para limpar o estado e mandar as boas-vindas
        bot_api = os.getenv("BOT_API", "http://localhost:5001")
        welcome_text = (
            "🚀 *Tudo pronto! Bem-vindo(a) à SecretarIA!* 🎉\n\n"
            "Agora posso gerenciar seus *compromissos* e *finanças*!\n\n"
            "📚 *Exemplos do que posso fazer:*\n"
            "• _\"Reunião com Ana sexta às 15h\"_\n"
            "• _\"Coloca dentista amanhã às 10h\"_\n"
            "• _\"Ver agenda de hoje\"_\n"
            "• _\"Gastei 45 reais no almoço\"_\n"
            "• _\"Ver meus gastos do mês\"_\n\n"
            "💡 Digite *ajuda* para ver todos os comandos! 😊"
        )
        try:
            req_bot = urllib.request.Request(
                f"{bot_api}/oauth/success",
                data=json.dumps({"phone": phone, "text": welcome_text}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req_bot) as resp_bot:
                pass
        except Exception as bot_err:
            log.error(f"[Callback] Erro ao notificar bot Node: {bot_err}")

        # 8. Retorna uma página de sucesso premium (Glassmorphism)
        success_html = """
        <!DOCTYPE html>
        <html lang="pt-BR">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Conexão Concluída — SecretarIA</title>
            <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&display=swap" rel="stylesheet">
            <style>
                * {
                    margin: 0;
                    padding: 0;
                    box-sizing: border-box;
                    font-family: 'Outfit', sans-serif;
                }
                body {
                    background: radial-gradient(circle at top right, #1e1b4b, #0f0b1b, #000000);
                    color: #ffffff;
                    min-height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    overflow: hidden;
                    position: relative;
                }
                body::before {
                    content: '';
                    position: absolute;
                    width: 300px;
                    height: 300px;
                    background: #6366f1;
                    filter: blur(150px);
                    border-radius: 50%;
                    top: 15%;
                    left: 20%;
                    opacity: 0.4;
                    z-index: 0;
                }
                body::after {
                    content: '';
                    position: absolute;
                    width: 300px;
                    height: 300px;
                    background: #d946ef;
                    filter: blur(150px);
                    border-radius: 50%;
                    bottom: 15%;
                    right: 20%;
                    opacity: 0.3;
                    z-index: 0;
                }
                .card {
                    background: rgba(255, 255, 255, 0.03);
                    backdrop-filter: blur(20px);
                    -webkit-backdrop-filter: blur(20px);
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 24px;
                    padding: 40px 30px;
                    width: 90%;
                    max-width: 450px;
                    text-align: center;
                    box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5);
                    z-index: 10;
                    animation: fadeInUp 0.8s ease-out;
                }
                .icon-container {
                    width: 80px;
                    height: 80px;
                    background: linear-gradient(135deg, #6366f1, #d946ef);
                    border-radius: 50%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    margin: 0 auto 24px auto;
                    box-shadow: 0 8px 24px rgba(99, 102, 241, 0.4);
                }
                .icon {
                    font-size: 40px;
                    animation: scaleUp 0.5s 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275) both;
                }
                h1 {
                    font-size: 26px;
                    font-weight: 800;
                    background: linear-gradient(to right, #ffffff, #c7d2fe);
                    -webkit-background-clip: text;
                    -webkit-text-fill-color: transparent;
                    margin-bottom: 12px;
                }
                p {
                    font-size: 15px;
                    color: #94a3b8;
                    line-height: 1.6;
                    margin-bottom: 30px;
                }
                .btn {
                    display: inline-block;
                    width: 100%;
                    padding: 14px;
                    background: linear-gradient(135deg, #4f46e5, #c084fc);
                    color: #ffffff;
                    border: none;
                    border-radius: 12px;
                    font-size: 16px;
                    font-weight: 600;
                    cursor: pointer;
                    text-decoration: none;
                    box-shadow: 0 4px 15px rgba(79, 70, 229, 0.3);
                    transition: transform 0.2s, box-shadow 0.2s;
                }
                .btn:hover {
                    transform: translateY(-2px);
                    box-shadow: 0 6px 20px rgba(79, 70, 229, 0.5);
                }
                .btn:active {
                    transform: translateY(0);
                }
                @keyframes fadeInUp {
                    from { opacity: 0; transform: translateY(20px); }
                    to { opacity: 1; transform: translateY(0); }
                }
                @keyframes scaleUp {
                    from { transform: scale(0); }
                    to { transform: scale(1); }
                }
            </style>
        </head>
        <body>
            <div class="card">
                <div class="icon-container">
                    <span class="icon">🚀</span>
                </div>
                <h1>Conta Conectada!</h1>
                <p>Sua conta do Google Agenda foi integrada com sucesso à SecretarIA.<br>Você já pode fechar esta página e voltar para o WhatsApp para começar a agendar!</p>
                <button class="btn" onclick="window.close()">Fechar Aba</button>
            </div>
            <script>
                // Tenta fechar a aba automaticamente após 3 segundos
                setTimeout(function() {
                    window.close();
                }, 3000);
            </script>
        </body>
        </html>
        """
        return success_html, 200

    except Exception as e:
        log.error(f"[Callback] Erro na autorizacao: {e}")
        return f"Erro durante a conexão com o Google Agenda: {e}", 500

@app.route("/onboarding/verificar", methods=["POST"])
def onboarding_verificar():
    phone = request.json.get("phone", "")
    user = usuario_por_phone(phone)
    if not user:
        return jsonify({"cadastrado": False})
    
    # Verifica se o arquivo de token do Google Agenda existe
    token_path = TOKENS_DIR / f"token_{user['id']}.json"
    google_conectado = 1 if (token_path.exists() and user.get("google_conectado") == 1) else 0
    
    # Atualiza no banco se houver inconsistência
    if google_conectado != user.get("google_conectado"):
        with get_conn() as conn:
            conn.execute("UPDATE usuarios SET google_conectado=? WHERE id=?", (google_conectado, user["id"]))
            conn.commit()
    
    return jsonify({
        "cadastrado": True,
        "google_conectado": bool(google_conectado),
        "id": user["id"],
        "nome": user["nome"]
    })

@app.route("/onboarding/cadastrar", methods=["POST"])
def onboarding_cadastrar():
    data = request.json
    phone = re.sub(r"\D", "", data.get("phone", ""))
    nome = data.get("nome", "").strip()
    data_nasc = data.get("data_nasc", "").strip()
    email = data.get("email", "").strip().lower()
    
    if not phone or not nome or not data_nasc or not email:
        return jsonify({"erro": "Todos os campos sao obrigatorios."}), 400
    
    # Verifica se e-mail já existe
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM usuarios WHERE email=?", (email,)).fetchone()
        if row:
            return jsonify({"erro": "Este e-mail ja esta cadastrado no sistema."}), 400
            
    # Cria senha aleatória e gera hash
    senha_temp = secrets.token_hex(8)
    senha_hash, salt = gerar_hash(senha_temp)
    
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO usuarios (nome, data_nasc, telefone, email, senha_hash, salt, google_conectado)
                VALUES (?, ?, ?, ?, ?, ?, 0)
            """, (nome, data_nasc, phone, email, senha_hash, salt))
            conn.commit()
            user_id = cursor.lastrowid
            
        log.info(f"[Onboarding] Cadastrado: {nome} | ID: {user_id} | Telefone: {phone}")
        return jsonify({"success": True, "id": user_id})
    except Exception as e:
        log.error(f"[Onboarding] Erro ao cadastrar usuario: {e}")
        return jsonify({"erro": "Erro interno ao salvar no banco."}), 500

@app.route("/onboarding/auth_url", methods=["POST"])
def onboarding_auth_url():
    if not CREDENTIALS_FILE.exists():
        return jsonify({"erro": "Arquivo credentials.json nao encontrado no servidor."}), 500
        
    try:
        import urllib.parse
        phone = request.json.get("phone", "")
        bot_phone = request.json.get("botPhone", "")
        
        with open(str(CREDENTIALS_FILE)) as f:
            secret_json = json.load(f)
            client_type = "installed" if "installed" in secret_json else "web"
            client_info = secret_json[client_type]
            
        redirect_uri = obter_redirect_uri()
        auth_base = client_info.get("auth_uri", "https://accounts.google.com/o/oauth2/auth")
        
        params = {
            "client_id": client_info["client_id"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": f"{phone}:{bot_phone}"  # Concatena telefone do usuário e do bot
        }
        auth_url = f"{auth_base}?{urllib.parse.urlencode(params)}"
        return jsonify({"url": auth_url})
    except Exception as e:
        log.error(f"[Onboarding] Erro ao gerar URL Google OAuth: {e}")
        return jsonify({"erro": "Erro ao gerar URL de autorizacao."}), 500

@app.route("/onboarding/confirmar_code", methods=["POST"])
def onboarding_confirmar_code():
    data = request.json
    phone = data.get("phone", "")
    raw_code = data.get("code", "").strip()
    user_id = data.get("userId")
    
    # Remove prefixo se vier via WhatsApp Click-to-Chat
    if "Confirmar_Conexao:" in raw_code:
        raw_code = raw_code.replace("Confirmar_Conexao:", "").strip()
        
    # Extrai o código caso o usuário cole a URL inteira
    code = raw_code
    if "code=" in raw_code:
        m = re.search(r"code=([^&]+)", raw_code)
        if m:
            from urllib.parse import unquote
            code = unquote(m.group(1))
            
    # Se userId for nulo ou vazio, pesquisa por telefone no banco
    if not user_id and phone:
        user = usuario_por_phone(phone)
        if user:
            user_id = user["id"]
            
    if not code or not user_id:
        return jsonify({"erro": "Dados incompletos."}), 400
        
    try:
        import urllib.request, urllib.parse
        
        # 1. Carrega dados do credentials.json
        if not CREDENTIALS_FILE.exists():
            return jsonify({"erro": "Arquivo credentials.json nao encontrado."}), 500
            
        with open(str(CREDENTIALS_FILE)) as f:
            secret_json = json.load(f)
            client_type = "installed" if "installed" in secret_json else "web"
            client_info = secret_json[client_type]
            
        redirect_uri = obter_redirect_uri()
            
        # 2. Faz a requisição de troca direta
        params = {
            "code": code,
            "client_id": client_info["client_id"],
            "client_secret": client_info["client_secret"],
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code"
        }
        post_data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request("https://oauth2.googleapis.com/token", data=post_data, method="POST")
        
        with urllib.request.urlopen(req) as response:
            tokens_resp = json.loads(response.read().decode("utf-8"))
            
        # 3. Cria as Credenciais do Google no formato esperado
        creds = Credentials(
            token=tokens_resp.get("access_token"),
            refresh_token=tokens_resp.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_info["client_id"],
            client_secret=client_info["client_secret"],
            scopes=SCOPES
        )
        
        # Garante que a pasta de tokens existe
        TOKENS_DIR.mkdir(exist_ok=True)
        token_path = TOKENS_DIR / f"token_{user_id}.json"
        token_path.write_text(creds.to_json())
        
        with get_conn() as conn:
            conn.execute("UPDATE usuarios SET google_conectado=1 WHERE id=?", (user_id,))
            conn.commit()
            
        log.info(f"[Onboarding] Google conectado para o ID: {user_id}")
        return jsonify({"success": True})
    except Exception as e:
        import urllib.error
        if isinstance(e, urllib.error.HTTPError):
            try:
                err_body = e.read().decode("utf-8")
                log.error(f"[Onboarding] Erro ao validar codigo OAuth (HTTPError): {e.code} {e.reason} - {err_body}")
            except Exception:
                log.error(f"[Onboarding] Erro ao validar codigo OAuth (HTTPError fallback): {e}")
        else:
            log.error(f"[Onboarding] Erro ao validar codigo OAuth: {e}")
        return jsonify({"erro": "Codigo ou URL invalida ou expirada. Certifique-se de copiar a URL inteira de redirecionamento ou o codigo."}), 400

@app.route("/onboarding/excluir", methods=["POST"])
def onboarding_excluir():
    phone = request.json.get("phone", "")
    user  = usuario_por_phone(phone)
    if not user:
        return jsonify({"sucesso": False, "erro": "Numero nao cadastrado."}), 404
    
    usuario_id = user["id"]
    try:
        with get_conn() as conn:
            # Remove gastos do usuário
            conn.execute("DELETE FROM gastos WHERE usuario_id=?", (usuario_id,))
            # Remove tetos
            conn.execute("DELETE FROM tetos WHERE usuario_id=?", (usuario_id,))
            # Remove cartões
            conn.execute("DELETE FROM cartoes WHERE usuario_id=?", (usuario_id,))
            # Remove categorias
            conn.execute("DELETE FROM categorias WHERE usuario_id=?", (usuario_id,))
            # Remove o usuário
            conn.execute("DELETE FROM usuarios WHERE id=?", (usuario_id,))
            conn.commit()
        
        # Remove token Google Agenda se existir
        token_path = TOKENS_DIR / f"token_{usuario_id}.json"
        if token_path.exists():
            token_path.unlink()
            log.info(f"[Excluir] Token Google removido para ID {usuario_id}")
        
        log.info(f"[Excluir] Conta excluida com sucesso: {user['nome']} | ID: {usuario_id} | phone: {phone}")
        return jsonify({"sucesso": True})
    except Exception as e:
        log.error(f"[Excluir] Erro ao excluir conta ID {usuario_id}: {e}")
        return jsonify({"sucesso": False, "erro": "Erro interno ao excluir conta."}), 500

@app.route("/texto", methods=["POST"])
def texto_webhook():
    phone = request.json.get("phone", "")
    texto = request.json.get("texto", "")
    user = usuario_por_phone(phone)
    if not user:
        return jsonify({"texto": "Numero nao cadastrado."})
    
    try:
        hoje_dt = obter_agora()
        hoje = hoje_dt.strftime("%d/%m/%Y")
        hora_atual = hoje_dt.strftime("%H:%M")
        amanha = (hoje_dt + timedelta(days=1)).strftime("%d/%m/%Y")
        dias_semana_refs = {}
        nomes_dias = ['segunda', 'terca', 'quarta', 'quinta', 'sexta', 'sabado', 'domingo']
        for i, nome in enumerate(nomes_dias):
            dias_ate = (i - hoje_dt.weekday()) % 7
            dias_semana_refs[nome] = (hoje_dt + timedelta(days=dias_ate)).strftime("%d/%m/%Y")
        
        prompt = f"""Você é a SecretarIA, assistente pessoal do Brasil. Hoje é {hoje} ({hora_atual}) — Fuso: America/Sao_Paulo.

Referências de datas:
- hoje={hoje}, amanhã={amanha}
- segunda={dias_semana_refs['segunda']}, terça={dias_semana_refs['terca']}, quarta={dias_semana_refs['quarta']}
- quinta={dias_semana_refs['quinta']}, sexta={dias_semana_refs['sexta']}, sábado={dias_semana_refs['sabado']}, domingo={dias_semana_refs['domingo']}

Classifique a intenção e extraia dados. Responda APENAS JSON válido, sem markdown.
Intenções: AGENDAR, VER_HOJE, VER_SEMANA, VER_LIVRE, CANCELAR_EVENTO, REGISTRAR_GASTO, VER_FINANCAS, DEFINIR_TETO, CONVERSA, AJUDA

Regras importantes:
1. Para AGENDAR:
   - "titulo" DEVE ser específico: "Reunião com Warley", "Consulta no Dentista", "Almoço com João".
     NUNCA use apenas "Reunião", "Compromisso" ou "Evento".
   - "data" DEVE estar em DD/MM/AAAA usando as referências acima.
   - "hora" em HH:MM (24h). Se não mencionada, use "09:00".
2. Para REGISTRAR_GASTO:
   - "valor" deve ser número (ex: 45.90).
   - "categoria" deve ser um de: Alimentacao, Transporte, Saude, Lazer, Outros.
   - "parcelas" (inteiro) e "cartao" (nome do banco) se mencionados.
3. CONVERSA: use para perguntas gerais, cumprimentos, dúvidas não relacionadas a agenda/finanças.

Formato:
{{"intent":"","dados":{{"titulo":"","data":"DD/MM/AAAA","hora":"HH:MM","duracao":60,"valor":0.0,"descricao":"","categoria":"","parcelas":1,"cartao":""}},"resposta_direta":null}}

Mensagem do usuario: "{texto}"""
        
        try:
            raw  = gemini_gerar(prompt)
            info = json.loads(limpar_json(raw))
        except Exception as gemini_err:
            err_msg = str(gemini_err).upper()
            if "RESOURCE_EXHAUSTED" in err_msg or "429" in err_msg or "QUOTA" in err_msg:
                return jsonify({"texto": "⚠️ O serviço de Inteligência Artificial (Gemini) está temporariamente congestionado ou o limite de requisições foi atingido. Por favor, aguarde cerca de 1 minuto e tente novamente."})
            raise gemini_err

        intent = info.get("intent", "AJUDA")
        dados = info.get("dados", {})
        resp_direta = info.get("resposta_direta")
        
        # Normaliza data para agendamentos
        if intent == "AGENDAR" and dados.get("data"):
            dados["data"] = normalizar_data(dados["data"]) or dados["data"]
        
        log.info(f"[texto] {phone} intent:{intent} | dados: {dados}")
        
        if intent == "CONVERSA":
            resposta = resp_direta or gemini_resposta_livre(texto, user)
            return jsonify({"texto": resposta})
            
        return _executar_intent(phone, intent, dados, texto, user, com_prefixo=False)
    except Exception as e:
        log.error(f"[texto/gemini] {type(e).__name__}: {e}")
        return jsonify({"texto": "Nao consegui processar a mensagem. Tente novamente."})

# ── Thread de Monitoramento de Lembretes ──────────────────────────────
def check_reminders_loop():
    import time, urllib.request, json, threading
    
    # Aguarda o servidor Flask e o bot Node.js iniciarem
    time.sleep(10)
    log.info("[Lembretes] Thread de monitoramento iniciada.")
    
    while True:
        try:
            # Obtém a hora atual em Brasília (UTC-3)
            from datetime import datetime, timezone, timedelta
            sp_tz = timezone(timedelta(hours=-3))
            now = datetime.now(sp_tz)
            hoje_str = now.strftime("%Y-%m-%d")
            hora_min_str = now.strftime("%H:%M")
            
            with get_conn() as conn:
                # Busca usuários cadastrados que tenham o Google Agenda conectado
                users = conn.execute("SELECT * FROM usuarios WHERE google_conectado=1").fetchall()
                
            for u in users:
                u_dict = dict(u)
                rem_time = u_dict.get("reminder_time", "08:00")
                last_rem = u_dict.get("ultimo_lembrete")
                
                # Se a hora bate com o agendado e ainda não enviou hoje
                if rem_time == hora_min_str and last_rem != hoje_str:
                    log.info(f"[Lembretes] Enviando briefing diario para {u_dict['nome']} ({u_dict['telefone']})")
                    
                    # Busca a agenda do dia no Google
                    service = get_google_service(u_dict["id"])
                    if service:
                        inicio_dia = now.replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
                        fim_dia = inicio_dia + timedelta(days=1)
                        eventos = listar_eventos(service, inicio_dia, fim_dia)
                        
                        briefing = f"🤖 *Bom dia, {u_dict['nome'].split(' ')[0]}! Aqui esta sua agenda de hoje:*\n\n"
                        if eventos:
                            for i, e in enumerate(eventos, 1):
                                start = e["start"].get("dateTime", e["start"].get("date", ""))
                                try:
                                    # Corrige a formatação para exibição
                                    if "T" in start:
                                        dt = datetime.fromisoformat(start.split("-03:00")[0].split("+")[0].replace("Z", ""))
                                        hora_fmt = dt.strftime("%H:%M")
                                    else:
                                        hora_fmt = "Dia todo"
                                except Exception:
                                    hora_fmt = start
                                briefing += f"{i}. *{e.get('summary', 'Sem titulo')}* as {hora_fmt}\n"
                        else:
                            briefing += "Sua agenda esta livre hoje! 🎉"
                            
                        # Envia via POST para o listener HTTP do bot Node.js (porta 5001)
                        payload = json.dumps({
                            "to": u_dict["telefone"],
                            "text": briefing
                        }).encode("utf-8")
                        
                        req = urllib.request.Request(
                            "http://localhost:5001/send",
                            data=payload,
                            headers={"Content-Type": "application/json"},
                            method="POST"
                        )
                        try:
                            with urllib.request.urlopen(req, timeout=5) as response:
                                if response.status == 200:
                                    # Atualiza no banco que o lembrete foi enviado hoje
                                    with get_conn() as conn:
                                        conn.execute("UPDATE usuarios SET ultimo_lembrete=? WHERE id=?", (hoje_str, u_dict["id"]))
                                        conn.commit()
                                    log.info(f"[Lembretes] Briefing enviado com sucesso para {u_dict['telefone']}")
                        except Exception as send_err:
                            log.error(f"[Lembretes] Erro ao enviar lembrete para {u_dict['telefone']}: {send_err}")
                            
        except Exception as loop_err:
            log.error(f"[Lembretes] Erro no loop de monitoramento: {loop_err}")
            
        time.sleep(30)

if __name__ == "__main__":
    import threading
    t = threading.Thread(target=check_reminders_loop, daemon=True)
    t.start()
    
    log.info("SecretarIA Webhook iniciado na porta 8080")
    app.run(host="0.0.0.0", port=8080, debug=False)
