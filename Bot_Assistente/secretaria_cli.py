# ─────────────────────────────────────────
#  AUTO-INSTALAÇÃO DE DEPENDÊNCIAS
# ─────────────────────────────────────────
import subprocess, sys

_DEPS = [
    "rich",
    "google-auth",
    "google-auth-oauthlib",
    "google-api-python-client",
    "google-genai",
    "python-dotenv",
]

def _instalar_deps():
    import importlib
    mapa = {
        "rich":                     "rich",
        "google-auth":              "google.auth",
        "google-auth-oauthlib":     "google_auth_oauthlib",
        "google-api-python-client": "googleapiclient",
        "google-genai":            "google.genai",
        "python-dotenv":           "dotenv",
    }
    precisam = []
    for pkg, modulo in mapa.items():
        try:
            importlib.import_module(modulo)
        except ImportError:
            precisam.append(pkg)
    if precisam:
        print("[SecretarIA] Instalando dependencias: " + ", ".join(precisam))
        for pkg in precisam:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])
        print("[SecretarIA] Instalacao concluida. Reiniciando...\n")
        subprocess.check_call([sys.executable] + sys.argv)
        sys.exit(0)

_instalar_deps()

import os
import sys
import sqlite3
import hashlib
import secrets
import msvcrt
import re
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    GOOGLE_DISPONIVEL = True
except ImportError:
    GOOGLE_DISPONIVEL = False

try:
    from google import genai as genai_client
    GEMINI_DISPONIVEL = True
except ImportError:
    GEMINI_DISPONIVEL = False

try:
    from dotenv import load_dotenv, set_key
    DOTENV_DISPONIVEL = True
except ImportError:
    DOTENV_DISPONIVEL = False

def _carregar_dotenv():
    if not DOTENV_DISPONIVEL:
        return
    for nome in [".env", ".env.txt", "file.env.txt", "file.env"]:
        p = _BASE_DIR / nome
        if p.exists():
            load_dotenv(dotenv_path=p, override=True)
            return

GOOGLE_SCOPES       = ["https://www.googleapis.com/auth/calendar"]
# Usa sempre o diretório de onde o script está sendo executado
_BASE_DIR           = Path(os.path.abspath(__file__)).parent
_carregar_dotenv()
CREDENTIALS_FILE    = _BASE_DIR / "credentials.json"
TOKENS_DIR          = _BASE_DIR / "tokens"
TOKENS_DIR.mkdir(exist_ok=True)

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Prompt
from rich.align import Align
from rich import box as rbox
from rich.table import Table as RichTable

console = Console()

ADMIN_EMAIL = "admin@secretaria.com"
ADMIN_SENHA = "Admin@1234"
DB_PATH     = "secretaria.db"

# ─────────────────────────────────────────
#  BANCO DE DADOS
# ─────────────────────────────────────────
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

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
            CREATE TABLE IF NOT EXISTS recuperacao_senha (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER NOT NULL,
                token      TEXT    NOT NULL,
                expira_em  DATETIME NOT NULL,
                usado      INTEGER DEFAULT 0,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
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
            CREATE TABLE IF NOT EXISTS estatisticas_usuarios (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                criado_em   DATETIME DEFAULT CURRENT_TIMESTAMP,
                excluido_em DATETIME
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
        # Migração: adiciona cartao_id em gastos se não existir
        try:
            conn.execute("ALTER TABLE gastos ADD COLUMN cartao_id INTEGER REFERENCES cartoes(id)")
        except Exception:
            pass
        conn.commit()

# ─────────────────────────────────────────
#  CRIPTOGRAFIA
# ─────────────────────────────────────────
def gerar_hash(senha, salt=None):
    if salt is None:
        salt = secrets.token_hex(32)
    chave = hashlib.pbkdf2_hmac(
        "sha256", senha.encode("utf-8"), salt.encode("utf-8"), iterations=390_000
    ).hex()
    return chave, salt

# ─────────────────────────────────────────
#  UTILITÁRIOS DE TERMINAL
# ─────────────────────────────────────────
def clear():
    os.system("cls" if os.name == "nt" else "clear")

def header(subtitulo=""):
    robo = Text(justify="center")
    robo.append(" [o_o]\n", style="bold cyan")
    robo.append(" /|_|\\\n", style="bold cyan")
    robo.append("\n")
    robo.append("S E C R E T A R I A\n", style="bold cyan")
    robo.append("  Bot  Assistente  ", style="white")
    if subtitulo:
        robo.append("\n\n" + subtitulo, style="dim white")
    console.print(Panel(Align.center(robo), box=rbox.DOUBLE, border_style="cyan", padding=(1, 6)))

def aviso_voltar():
    console.print(Panel(
        "[yellow][!] Para voltar a tela anterior:[/yellow]\n"
        "    Digite  [bold]V[/bold]  e pressione  [bold]Enter[/bold]",
        box=rbox.ROUNDED, border_style="yellow", padding=(0, 2)
    ))
    console.print()

def ok(msg):    console.print("\n  [bold green][OK] " + msg + "[/bold green]")
def erro(msg):  console.print("\n  [bold red][X] " + msg + "[/bold red]")
def aviso(msg): console.print("  [bold yellow][!] " + msg + "[/bold yellow]\n")
def info(msg):  console.print("  [cyan]" + msg + "[/cyan]")

def aguardar(msg="  Pressione Enter para continuar."):
    input(msg)

def ler_senha(prompt="  Senha: "):
    print(prompt, end="", flush=True)
    senha = []
    while True:
        c = msvcrt.getwch()
        if c in ("\r", "\n"):
            print()
            break
        elif c == "\x08":
            if senha:
                senha.pop()
                print("\b \b", end="", flush=True)
        elif c == "\x03":
            raise KeyboardInterrupt
        else:
            senha.append(c)
            print("*", end="", flush=True)
    return "".join(senha)

class Cancelado(Exception):
    pass

# ─────────────────────────────────────────
#  VALIDAÇÕES
# ─────────────────────────────────────────
def validar_nome(v):
    if len(v) < 5: return "Nome deve ter no minimo 5 caracteres."
    if not re.search(r"[a-zA-ZÀ-ÿ]", v): return "Nome deve conter letras."
    return None

def validar_data(v):
    try:
        datetime.strptime(v, "%d/%m/%Y"); return None
    except ValueError:
        return "Data invalida. Use DD/MM/AAAA."

def validar_telefone(v):
    limpo = re.sub(r"\D", "", v)
    if len(limpo) < 10 or len(limpo) > 11: return "Telefone invalido. Ex: (62) 99999-9999"
    return None

def validar_email(v):
    if "@" not in v or "." not in v.split("@")[-1]: return "E-mail invalido."
    return None

def validar_senha(v):
    if len(v) < 8: return "Minimo 8 caracteres."
    if not any(c.isdigit() for c in v): return "Deve conter ao menos um numero."
    if not any(c.isupper() for c in v): return "Deve conter ao menos uma letra maiuscula."
    return None

def validar_confirmacao(original):
    return lambda v: None if v == original else "As senhas nao coincidem."

def validar_valor(v):
    return None if re.match(r"^\d+([.,]\d{1,2})?$", v) else "Valor invalido. Ex: 45.90"

def campo(label, obrigatorio=True, mascara=False, validar=None, dica="", pode_cancelar=False):
    dica_str = dica
    if pode_cancelar and not mascara:
        dica_str = (dica + " | " if dica else "") + "V para voltar"
    while True:
        prompt_txt = "  [bold]" + label + "[/bold]"
        if dica_str:
            prompt_txt += " [dim](" + dica_str + ")[/dim]"
        if mascara:
            valor = ler_senha("  " + label + (" (" + dica + ")" if dica else "") + ": ")
        else:
            valor = Prompt.ask(prompt_txt, console=console).strip()
        if pode_cancelar and valor.upper() == "V":
            raise Cancelado
        if obrigatorio and not valor:
            aviso(label + " nao pode ser vazio.")
            continue
        if validar:
            err = validar(valor)
            if err:
                aviso(err)
                continue
        return valor

# ─────────────────────────────────────────
#  HELPERS — USUÁRIOS
# ─────────────────────────────────────────
def buscar_usuario_por_email(email):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM usuarios WHERE email = ?", (email.lower(),)).fetchone()

def email_existe(email):
    return buscar_usuario_por_email(email) is not None

def verificar_senha(usuario, senha):
    h, _ = gerar_hash(senha, usuario["salt"])
    return h == usuario["senha_hash"]

def atualizar_senha(usuario_id, nova_senha):
    h, salt = gerar_hash(nova_senha)
    with get_conn() as conn:
        conn.execute("UPDATE usuarios SET senha_hash=?, salt=? WHERE id=?", (h, salt, usuario_id))
        conn.commit()

# ─────────────────────────────────────────
#  HELPERS — FINANCEIRO
# ─────────────────────────────────────────
CATEGORIAS_PADRAO = ["Alimentacao", "Transporte", "Saude", "Lazer", "Outros"]

def garantir_categorias_padrao(usuario_id):
    with get_conn() as conn:
        for nome in CATEGORIAS_PADRAO:
            conn.execute(
                "INSERT OR IGNORE INTO categorias (usuario_id, nome, padrao) VALUES (?, ?, 1)",
                (usuario_id, nome)
            )
        conn.commit()

def listar_categorias(usuario_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM categorias WHERE usuario_id = ? ORDER BY padrao DESC, nome",
            (usuario_id,)
        ).fetchall()

def adicionar_categoria(usuario_id, nome):
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO categorias (usuario_id, nome, padrao) VALUES (?, ?, 0)",
                (usuario_id, nome.strip().capitalize())
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

def salvar_gasto(usuario_id, categoria_id, descricao, valor):
    data = datetime.now().strftime("%Y-%m-%d")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO gastos (usuario_id, categoria_id, descricao, valor, data) VALUES (?,?,?,?,?)",
            (usuario_id, categoria_id, descricao, valor, data)
        )
        conn.commit()

def salvar_gasto_com_data(usuario_id, categoria_id, descricao, valor, data, cartao_id=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO gastos (usuario_id, categoria_id, descricao, valor, data, cartao_id) VALUES (?,?,?,?,?,?)",
            (usuario_id, categoria_id, descricao, valor, data, cartao_id)
        )
        conn.commit()

def salvar_teto(usuario_id, valor, categoria_id=None, mes="*"):
    """mes='*' = teto global (todos os meses). mes='YYYY-MM' = sobrescreve so aquele mes."""
    with get_conn() as conn:
        if categoria_id:
            conn.execute(
                "DELETE FROM tetos WHERE usuario_id=? AND categoria_id=? AND mes=?",
                (usuario_id, categoria_id, mes)
            )
        else:
            conn.execute(
                "DELETE FROM tetos WHERE usuario_id=? AND categoria_id IS NULL AND mes=?",
                (usuario_id, mes)
            )
        conn.execute(
            "INSERT INTO tetos (usuario_id, categoria_id, valor, mes) VALUES (?,?,?,?)",
            (usuario_id, categoria_id, valor, mes)
        )
        conn.commit()

def buscar_teto_geral(usuario_id):
    mes = datetime.now().strftime("%Y-%m")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT valor FROM tetos WHERE usuario_id=? AND categoria_id IS NULL AND mes=?",
            (usuario_id, mes)
        ).fetchone()
        return row["valor"] if row else None

def buscar_teto_categoria(usuario_id, categoria_id):
    mes = datetime.now().strftime("%Y-%m")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT valor FROM tetos WHERE usuario_id=? AND categoria_id=? AND mes=?",
            (usuario_id, categoria_id, mes)
        ).fetchone()
        return row["valor"] if row else None

def resumo_gastos_mes(usuario_id):
    mes = datetime.now().strftime("%Y-%m")
    with get_conn() as conn:
        return conn.execute("""
            SELECT c.id, c.nome, SUM(g.valor) as total
            FROM gastos g
            JOIN categorias c ON c.id = g.categoria_id
            WHERE g.usuario_id = ? AND strftime('%Y-%m', g.data) = ?
            GROUP BY c.id, c.nome
            ORDER BY total DESC
        """, (usuario_id, mes)).fetchall()

def listar_gastos_categoria(usuario_id, categoria_id):
    mes = datetime.now().strftime("%Y-%m")
    with get_conn() as conn:
        return conn.execute("""
            SELECT descricao, valor, data
            FROM gastos
            WHERE usuario_id = ? AND categoria_id = ?
              AND strftime('%Y-%m', data) = ?
            ORDER BY data DESC
        """, (usuario_id, categoria_id, mes)).fetchall()

# ─────────────────────────────────────────
#  HELPERS — ESTATÍSTICAS
# ─────────────────────────────────────────
def registrar_novo_usuario():
    with get_conn() as conn:
        conn.execute("INSERT INTO estatisticas_usuarios DEFAULT VALUES")
        conn.commit()

def registrar_exclusao_usuario():
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM estatisticas_usuarios WHERE excluido_em IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE estatisticas_usuarios SET excluido_em=datetime('now','localtime') WHERE id=?",
                (row["id"],)
            )
        conn.commit()

def buscar_estatisticas():
    with get_conn() as conn:
        total     = conn.execute("SELECT COUNT(*) as c FROM estatisticas_usuarios").fetchone()["c"]
        excluidos = conn.execute("SELECT COUNT(*) as c FROM estatisticas_usuarios WHERE excluido_em IS NOT NULL").fetchone()["c"]
        hist      = conn.execute(
            "SELECT id, criado_em, excluido_em FROM estatisticas_usuarios ORDER BY id DESC LIMIT 10"
        ).fetchall()
        return total, total - excluidos, excluidos, hist


# ─────────────────────────────────────────
#  GEMINI — SERVIÇO DE IA NATURAL
# ─────────────────────────────────────────
GEMINI_MODEL       = "gemini-2.5-flash-lite"
_GEMINI_KEY_PADRAO = "AIzaSyD2k3OSfMn2ao-etaIeHARZMSPjgpQn8rg"
GEMINI_API_KEY     = os.environ.get("GEMINI_API_KEY", "") or _GEMINI_KEY_PADRAO

def _gemini_configurado():
    return GEMINI_DISPONIVEL and bool(GEMINI_API_KEY)

def _gemini_gerar(prompt):
    """Cria cliente novo a cada chamada — evita 'client has been closed'."""
    with genai_client.Client(api_key=GEMINI_API_KEY) as client:
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        return resp.text.strip()

def _salvar_key_env(key):
    global GEMINI_API_KEY
    GEMINI_API_KEY = key
    os.environ["GEMINI_API_KEY"] = key
    if DOTENV_DISPONIVEL:
        env_path = _BASE_DIR / ".env"
        if not env_path.exists():
            env_path.write_text("")
        set_key(str(env_path), "GEMINI_API_KEY", key)

def gemini_classificar_intencao(texto):
    if not _gemini_configurado():
        return None
    prompt = f"""Você é o assistente SecretarIA. O usuário enviou uma mensagem em português.
Classifique a intenção e extraia os dados. Responda APENAS com JSON válido, sem markdown.

Intenções: AGENDAR_EVENTO, VER_AGENDA_HOJE, VER_AGENDA_SEMANA, VER_HORARIOS_LIVRES,
           CANCELAR_EVENTO, REGISTRAR_GASTO, VER_FINANCAS, DEFINIR_TETO, AJUDA, CONVERSA

Formato:
{{
  "intent": "NOME",
  "dados": {{
    "titulo": "", "data": "", "hora": "", "duracao": 60,
    "descricao": "", "valor": 0.0, "categoria": "", "parcelas": 1
  }},
  "resposta_direta": null
}}

Mensagem: "{texto}"
"""
    try:
        raw = _gemini_gerar(prompt)
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception:
        return {"intent": "AJUDA", "dados": {}, "resposta_direta": None}

def gemini_extrair_data(texto_data, referencia=None):
    if not _gemini_configurado():
        return None
    hoje = (referencia or datetime.now()).strftime("%d/%m/%Y")
    try:
        resultado = _gemini_gerar(
            f"Hoje é {hoje}. Converta para DD/MM/AAAA. Responda APENAS a data ou 'INVALIDO'.\nExpressão: \"{texto_data}\""
        )
        if resultado == "INVALIDO":
            return None
        datetime.strptime(resultado, "%d/%m/%Y")
        return resultado
    except Exception:
        return None

def gemini_resposta_livre(mensagem, usuario, contexto=""):
    if not _gemini_configurado():
        return "IA não configurada."
    nome = usuario.get("nome", "usuário").split()[0]
    try:
        return _gemini_gerar(
            f"Você é a SecretarIA, assistente pessoal de {nome}. Responda em português, direto e amigável. Máximo 3 parágrafos.\n"
            f"{f'Contexto: {contexto}' if contexto else ''}\n{nome} disse: \"{mensagem}\""
        )
    except Exception as e:
        return f"Erro: {str(e)}"

def gemini_resumo_financeiro(usuario, resumo, teto_geral):
    if not _gemini_configurado():
        return None
    total = sum(r["total"] for r in resumo)
    cats  = "\n".join(f"  - {r['nome']}: R$ {r['total']:.2f}" for r in resumo)
    teto  = f"R$ {teto_geral:.2f}" if teto_geral else "não definido"
    try:
        return _gemini_gerar(
            f"Analise os gastos de {datetime.now().strftime('%B de %Y')} em português. Máximo 4 linhas. Sem markdown.\n"
            f"Total: R$ {total:.2f} | Teto: {teto}\n{cats}\nDê 1 ponto de atenção + 1 sugestão prática."
        )
    except Exception:
        return None

def tela_configurar_gemini():
    global GEMINI_API_KEY
    clear()
    header("Configurar IA — Gemini")
    aviso_voltar()

    if not GEMINI_DISPONIVEL:
        erro("Biblioteca google-genai não instalada.")
        info("Execute: pip install google-genai")
        aguardar()
        return

    console.print(Panel(
        f"  Pacote:  [bold cyan]google-genai[/bold cyan]  (novo SDK oficial)\n"
        f"  Modelo:  [bold cyan]{GEMINI_MODEL}[/bold cyan]  |  Cota: [bold green]~1.500 req/dia[/bold green]\n\n"
        + (f"  [green]✓ Key ativa:[/green] [dim]{GEMINI_API_KEY[:8]}...{GEMINI_API_KEY[-4:]}[/dim]\n\n"
           if GEMINI_API_KEY else "  [yellow]Nenhuma key configurada.[/yellow]\n\n")
        + "  Obtenha sua key:\n  [cyan]https://aistudio.google.com/app/apikey[/cyan]",
        box=rbox.ROUNDED, border_style="cyan", padding=(0, 2)
    ))
    console.print()

    try:
        nova_key = campo("Cole sua Gemini API Key", pode_cancelar=True, dica="começa com AIza...")
    except Cancelado:
        return

    info(f"Testando conexão com {GEMINI_MODEL}...")
    try:
        with genai_client.Client(api_key=nova_key.strip()) as client:
            resp = client.models.generate_content(model=GEMINI_MODEL, contents="Diga apenas: OK")
        if resp.text:
            _salvar_key_env(nova_key.strip())
            ok("Gemini conectado! Key salva em [bold].env[/bold] permanentemente.")
        else:
            aviso("Resposta inesperada. Key não salva.")
    except Exception as e:
        erro("Falha ao conectar: " + str(e))

    aguardar("\n  Pressione Enter para voltar.")

# ─────────────────────────────────────────
#  TELA: CHAT COM IA
# ─────────────────────────────────────────
def tela_chat_ia(usuario):
    if not _gemini_configurado():
        clear()
        header("Falar com a SecretarIA (IA)")
        aviso("Gemini não configurado. Use a opção [bold]IA[/bold] no menu.")
        aguardar()
        return

    historico = []
    while True:
        clear()
        header("Falar com a SecretarIA (IA)")
        console.print(Panel(
            "  Digite sua mensagem em linguagem natural.\n"
            "  [dim]• 'Reunião com João amanhã às 14h por 1 hora'[/dim]\n"
            "  [dim]• 'Gastei 45 reais no supermercado'[/dim]\n"
            "  [dim]• 'Como estão meus gastos?'[/dim]\n\n"
            "  [yellow]V[/yellow] para voltar.",
            box=rbox.ROUNDED, border_style="cyan", padding=(0, 2)
        ))
        console.print()

        if historico:
            console.print("  [dim]── Histórico ──[/dim]")
            for e in historico[-3:]:
                console.print("  [bold cyan]Você:[/bold cyan] " + e["user"])
                console.print("  [bold green]IA:[/bold green]   " + e["ia"][:120] + ("..." if len(e["ia"]) > 120 else ""))
                console.print()

        try:
            texto = campo("Você", pode_cancelar=True)
        except Cancelado:
            return

        with console.status("[cyan]SecretarIA pensando...[/cyan]"):
            resultado = gemini_classificar_intencao(texto)

        if not resultado:
            erro("Não consegui interpretar.")
            aguardar()
            continue

        intent = resultado.get("intent", "AJUDA")
        dados  = resultado.get("dados", {})
        resp_d = resultado.get("resposta_direta")
        console.print()

        rotas = {
            "VER_AGENDA_HOJE":     tela_agenda_hoje,
            "VER_AGENDA_SEMANA":   tela_agenda_semana,
            "VER_HORARIOS_LIVRES": tela_horarios_livres,
            "CANCELAR_EVENTO":     tela_cancelar_compromisso,
            "VER_FINANCAS":        tela_checar_financas,
            "DEFINIR_TETO":        tela_definir_teto,
        }

        if intent == "AGENDAR_EVENTO":
            _chat_agendar(usuario, dados, texto)
            historico.append({"user": texto, "ia": "Evento processado."})
        elif intent == "REGISTRAR_GASTO":
            r = _chat_registrar_gasto(usuario, dados, texto)
            historico.append({"user": texto, "ia": r})
        elif intent in rotas:
            historico.append({"user": texto, "ia": f"Abrindo {intent}..."})
            rotas[intent](usuario)
            continue
        else:
            resposta = resp_d or gemini_resposta_livre(texto, usuario)
            console.print(Panel("[bold green]SecretarIA:[/bold green]\n\n" + resposta,
                                box=rbox.ROUNDED, border_style="green", padding=(0, 2)))
            historico.append({"user": texto, "ia": resposta})

        aguardar("\n  Pressione Enter para continuar...")

def _chat_agendar(usuario, dados, texto_original):
    service = get_google_service(usuario["id"])
    if not service:
        aviso("Google Agenda não conectado.")
        return
    titulo   = dados.get("titulo") or texto_original[:40]
    data_raw = dados.get("data", "hoje")
    hora_raw = dados.get("hora") or "09:00"
    duracao  = int(dados.get("duracao") or 60)
    if str(data_raw).lower() in ("hoje", "today", ""):
        data_str = datetime.now().strftime("%d/%m/%Y")
    elif str(data_raw).lower() in ("amanha", "amanhã", "tomorrow"):
        data_str = (datetime.now() + timedelta(days=1)).strftime("%d/%m/%Y")
    elif re.match(r"\d{2}/\d{2}/\d{4}", str(data_raw)):
        data_str = data_raw
    else:
        with console.status("[cyan]Interpretando data...[/cyan]"):
            data_str = gemini_extrair_data(data_raw) or datetime.now().strftime("%d/%m/%Y")
    hora_limpa = str(hora_raw).replace("h", ":").replace("H", ":")
    if not re.match(r"\d{1,2}:\d{2}", hora_limpa):
        hora_limpa = "09:00"
    p = hora_limpa.split(":")
    hora_limpa = p[0].zfill(2) + ":" + (p[1][:2] if len(p) > 1 else "00")
    console.print(Panel(
        f"  [bold]Evento:[/bold]   {titulo}\n"
        f"  [bold]Data:[/bold]     {data_str}\n"
        f"  [bold]Hora:[/bold]     {hora_limpa}\n"
        f"  [bold]Duração:[/bold]  {duracao} min",
        title="[cyan]Confirmar agendamento[/cyan]", box=rbox.ROUNDED, border_style="cyan", padding=(0, 2)
    ))
    if Prompt.ask("  [bold]Confirmar? (S/N)[/bold]", console=console).strip().upper() != "S":
        aviso("Cancelado.")
        return
    try:
        dt_i = datetime.strptime(data_str + " " + hora_limpa, "%d/%m/%Y %H:%M")
        dt_f = dt_i + timedelta(minutes=duracao)
        criado = service.events().insert(
            calendarId="primary",
            body={"summary": titulo, "description": dados.get("descricao", ""),
                  "start": {"dateTime": dt_i.isoformat(), "timeZone": "America/Sao_Paulo"},
                  "end":   {"dateTime": dt_f.isoformat(), "timeZone": "America/Sao_Paulo"}}
        ).execute()
        ok("Agendado: " + criado.get("summary", titulo) + " em " + dt_i.strftime("%d/%m/%Y %H:%M"))
    except Exception as e:
        erro("Erro: " + str(e))

def _chat_registrar_gasto(usuario, dados, texto_original):
    garantir_categorias_padrao(usuario["id"])
    cats      = listar_categorias(usuario["id"])
    valor     = float(dados.get("valor") or 0.0)
    cat_nome  = (dados.get("categoria") or "Outros").strip().capitalize()
    descricao = dados.get("descricao") or texto_original[:60]
    categoria = next((c for c in cats if c["nome"].lower() == cat_nome.lower()),
                     next((c for c in cats if c["nome"] == "Outros"), cats[0]))
    if valor <= 0:
        try:
            valor = float(campo("Valor (R$)", validar=validar_valor).replace(",", "."))
        except Cancelado:
            return "Cancelado."
    console.print(Panel(
        f"  [bold]Descrição:[/bold]  {descricao}\n"
        f"  [bold]Valor:[/bold]      R$ {valor:.2f}\n"
        f"  [bold]Categoria:[/bold]  {categoria['nome']}",
        title="[cyan]Confirmar gasto[/cyan]", box=rbox.ROUNDED, border_style="cyan", padding=(0, 2)
    ))
    if Prompt.ask("  [bold]Confirmar? (S/N)[/bold]", console=console).strip().upper() != "S":
        return "Cancelado."
    salvar_gasto(usuario["id"], categoria["id"], descricao, valor)
    msg = f"Gasto de R$ {valor:.2f} em '{categoria['nome']}' registrado!"
    ok(msg)
    return msg


# ─────────────────────────────────────────
#  RECUPERAÇÃO DE SENHA
# ─────────────────────────────────────────
def gerar_token_recuperacao(usuario_id):
    token_raw = secrets.token_hex(8).upper()
    token_fmt = "-".join(token_raw[i:i+4] for i in range(0, 16, 4))
    expira = datetime.now() + timedelta(minutes=15)
    with get_conn() as conn:
        conn.execute("UPDATE recuperacao_senha SET usado=1 WHERE usuario_id=?", (usuario_id,))
        conn.execute(
            "INSERT INTO recuperacao_senha (usuario_id, token, expira_em) VALUES (?,?,?)",
            (usuario_id, token_raw, expira.strftime("%Y-%m-%d %H:%M:%S"))
        )
        conn.commit()
    return token_fmt

def validar_token_recuperacao(email, token_digitado):
    usuario = buscar_usuario_por_email(email)
    if not usuario:
        return None
    token_limpo = token_digitado.replace("-", "").replace(" ", "").upper()
    with get_conn() as conn:
        row = conn.execute("""
            SELECT * FROM recuperacao_senha
            WHERE usuario_id=? AND token=? AND usado=0
              AND expira_em > datetime('now','localtime')
            ORDER BY id DESC LIMIT 1
        """, (usuario["id"], token_limpo)).fetchone()
        if row:
            conn.execute("UPDATE recuperacao_senha SET usado=1 WHERE id=?", (row["id"],))
            conn.commit()
            return usuario["id"]
    return None

# ─────────────────────────────────────────
#  TELA: RECUPERAR SENHA
# ─────────────────────────────────────────
def tela_recuperar_senha():
    while True:
        clear()
        header("Recuperacao de senha")
        aviso_voltar()
        info("Informe seu e-mail cadastrado para receber o codigo.\n")
        try:
            email = campo("E-mail", validar=validar_email, pode_cancelar=True)
        except Cancelado:
            return
        usuario = buscar_usuario_por_email(email)
        token   = gerar_token_recuperacao(usuario["id"]) if usuario else None
        if token:
            console.print(Panel(
                "[bold][#] Codigo gerado (valido por 15 minutos):[/bold]\n\n"
                "[bold cyan]        " + token + "[/bold cyan]\n\n"
                "[dim](Em producao seria enviado ao seu e-mail.)[/dim]",
                box=rbox.ROUNDED, border_style="cyan", padding=(1, 4)
            ))
        else:
            info("Se o e-mail estiver cadastrado, um codigo seria enviado.")
        console.print()
        try:
            token_digitado = campo("Codigo (XXXX-XXXX-XXXX-XXXX)", pode_cancelar=True)
        except Cancelado:
            return
        usuario_id = validar_token_recuperacao(email, token_digitado)
        if not usuario_id:
            erro("Codigo invalido ou expirado.")
            aguardar()
            continue
        ok("Codigo valido! Defina sua nova senha.\n")
        nova_senha = campo("Nova senha", mascara=True, validar=validar_senha,
                           dica="min. 8 chars, 1 maiuscula, 1 numero")
        campo("Confirmar nova senha", mascara=True, validar=validar_confirmacao(nova_senha))
        atualizar_senha(usuario_id, nova_senha)
        ok("Senha redefinida com sucesso!")
        aguardar("\n  Pressione Enter para voltar ao login.")
        return

# ─────────────────────────────────────────
#  TELA: LOGIN
# ─────────────────────────────────────────
def tela_login():
    while True:
        clear()
        header("Login")
        aviso_voltar()
        console.print(Panel(
            "  [bold]R[/bold]  + Enter  ->  Recuperar senha\n"
            "  [bold]V[/bold]  + Enter  ->  Voltar ao menu principal",
            title="[dim]Atalhos no campo E-mail[/dim]",
            box=rbox.ROUNDED, border_style="dim", padding=(0, 2)
        ))
        console.print()
        email = Prompt.ask("  [bold]E-mail[/bold] [dim](ou R / V)[/dim]", console=console).strip()
        cmd = email.upper()
        if cmd == "V":
            return None
        if cmd == "R":
            tela_recuperar_senha()
            continue
        if not email:
            aviso("E-mail nao pode ser vazio.")
            aguardar()
            continue
        if validar_email(email):
            aviso(validar_email(email))
            aguardar()
            continue
        senha   = ler_senha("  Senha: ")
        usuario = buscar_usuario_por_email(email)
        if not usuario or not verificar_senha(usuario, senha):
            erro("E-mail ou senha incorretos.")
            aguardar()
            continue
        u = dict(usuario)
        garantir_categorias_padrao(u["id"])
        return u

# ─────────────────────────────────────────
#  TELA: CRIAR USUÁRIO
# ─────────────────────────────────────────
def tela_criar_usuario():
    while True:
        clear()
        header("Criar novo usuario")
        aviso_voltar()
        info("Preencha os campos abaixo. Todos sao obrigatorios.\n")
        try:
            nome      = campo("Nome completo", validar=validar_nome, pode_cancelar=True)
            data_nasc = campo("Data de nascimento", dica="DD/MM/AAAA", validar=validar_data, pode_cancelar=True)
            telefone  = campo("Telefone", dica="(XX) 9XXXX-XXXX", validar=validar_telefone, pode_cancelar=True)
            while True:
                email = campo("E-mail", validar=validar_email, pode_cancelar=True)
                if email_existe(email):
                    aviso("Este e-mail ja esta cadastrado.")
                else:
                    break
            # Loop de senha: redigitar ou voltar ao inicio
            while True:
                senha = campo("Senha", mascara=True, validar=validar_senha,
                              dica="min. 8 chars, 1 maiuscula, 1 numero", pode_cancelar=True)
                # Confirmação manual sem campo() para ter controle total
                conf = ler_senha("  Confirmar senha: ")
                if conf.upper() == "V":
                    raise Cancelado
                if conf == senha:
                    break  # senhas conferem — sai do loop
                # senhas não batem
                aviso("As senhas nao coincidem.")
                nav = Prompt.ask(
                    "  [bold](T)[/bold] Redigitar senha  |  [bold](V)[/bold] Voltar ao inicio",
                    console=console
                ).strip().upper()
                if nav == "V":
                    raise Cancelado
                # T ou qualquer coisa: volta ao topo e redigita senha + confirmação
        except Cancelado:
            console.print("\n  [dim]< Cadastro cancelado. Voltando ao menu...[/dim]")
            aguardar()
            return
        # Tenta salvar
        senha_hash, salt = gerar_hash(senha)
        try:
            with get_conn() as conn:
                conn.execute("""
                    INSERT INTO usuarios (nome, data_nasc, telefone, email, senha_hash, salt)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (nome, data_nasc, re.sub(r"\D", "", telefone), email.lower(), senha_hash, salt))
                conn.commit()
            registrar_novo_usuario()
            ok("Usuario criado com sucesso! Bem-vindo(a), " + nome.split()[0] + "!")
            aguardar("\n  Pressione Enter para voltar ao menu.")
            return
        except sqlite3.IntegrityError:
            erro("E-mail ja cadastrado.")
            nav = Prompt.ask(
                "  [bold](T)[/bold] Tentar novamente  |  [bold](V)[/bold] Voltar",
                console=console
            ).strip().upper()
            if nav != "T":
                return
            # T: reinicia o formulário mantendo tela

# ─────────────────────────────────────────
#  TELA: CADASTRAR CARTÃO
# ─────────────────────────────────────────
def tela_cadastrar_cartao(usuario):
    clear()
    header("Cadastrar Cartao de Credito")
    aviso_voltar()
    cartoes = listar_cartoes(usuario["id"])
    if cartoes:
        console.print("  [bold]Cartoes cadastrados:[/bold]\n")
        for c in cartoes:
            console.print("  [cyan]•[/cyan] " + nome_cartao(c) +
                          "  Limite: R$ " + f"{c['limite']:.2f}" +
                          "  Venc: dia " + str(c["dia_venc"]) +
                          "  Fecha: dia " + str(c["dia_fecha"]))
        console.print()
    try:
        banco    = campo("Banco/Operadora", dica="ex: Nubank, Itau, Bradesco", pode_cancelar=True)
        ult4     = campo("Ultimos 4 digitos",
                         validar=lambda v: None if (v.isdigit() and len(v)==4) else "Digite exatamente 4 digitos.",
                         pode_cancelar=True)
        lim_str  = campo("Limite (R$)", dica="ex: 5000.00", validar=validar_valor, pode_cancelar=True)
        venc_str = campo("Dia de vencimento", dica="ex: 10",
                         validar=lambda v: None if (v.isdigit() and 1<=int(v)<=31) else "Dia invalido.",
                         pode_cancelar=True)
        fech_str = campo("Dia de fechamento da fatura", dica="ex: 28",
                         validar=lambda v: None if (v.isdigit() and 1<=int(v)<=31) else "Dia invalido.",
                         pode_cancelar=True)
    except Cancelado:
        return
    salvar_cartao(usuario["id"], banco.strip(), ult4.strip(),
                  float(lim_str.replace(",",".")), int(venc_str), int(fech_str))
    ok("Cartao " + banco.strip() + " ..." + ult4.strip() + " cadastrado!")
    aguardar("\n  Pressione Enter para voltar.")

# ─────────────────────────────────────────
#  TELA: ADICIONAR GASTO
# ─────────────────────────────────────────
def tela_adicionar_gasto(usuario):
    clear()
    header("Adicionar Gasto")
    aviso_voltar()
    garantir_categorias_padrao(usuario["id"])
    cats = listar_categorias(usuario["id"])
    console.print("[bold]  Categorias disponíveis:[/bold]\n")
    for i, c in enumerate(cats, 1):
        console.print("  [cyan]" + str(i) + "[/cyan] - " + c["nome"])
    console.print("  [cyan]" + str(len(cats)+1) + "[/cyan] - Nova categoria")
    console.print()
    try:
        escolha = campo("Categoria",
                        validar=lambda v: None if (v.isdigit() and 1 <= int(v) <= len(cats)+1) else "Opcao invalida.",
                        pode_cancelar=True)
    except Cancelado:
        return
    escolha = int(escolha)
    if escolha == len(cats) + 1:
        try:
            nova = campo("Nome da nova categoria", pode_cancelar=True)
        except Cancelado:
            return
        if not adicionar_categoria(usuario["id"], nova):
            aviso("Categoria ja existe.")
            aguardar()
            return
        cats      = listar_categorias(usuario["id"])
        categoria = next(c for c in cats if c["nome"].lower() == nova.strip().lower())
        ok("Categoria '" + categoria["nome"] + "' criada!")
    else:
        categoria = cats[escolha - 1]
    try:
        descricao = campo("Descricao", pode_cancelar=True)
        valor_str = campo("Valor total (R$)", dica="ex: 300.00", validar=validar_valor, pode_cancelar=True)
        parc_str  = campo("Parcelas", dica="ex: 3  (1 = a vista)",
                          obrigatorio=False, pode_cancelar=True)
        data_str  = campo("Data da compra", dica="DD/MM/AAAA ou Enter para hoje",
                          obrigatorio=False, pode_cancelar=True)
    except Cancelado:
        return

    valor_total = float(valor_str.replace(",", "."))
    parcelas = 1
    if parc_str and parc_str.strip().isdigit() and int(parc_str.strip()) > 1:
        parcelas = int(parc_str.strip())
    if data_str:
        err = validar_data(data_str)
        if err:
            aviso(err)
            aguardar()
            return
        data_inicio = datetime.strptime(data_str, "%d/%m/%Y")
    else:
        data_inicio = datetime.now()

    # Meio de pagamento
    console.print()
    console.print("  [bold]Meio de pagamento:[/bold]\n")
    console.print("  [cyan]1[/cyan] - Dinheiro / Debito / Pix  [dim](registra no mes atual)[/dim]")
    cartoes_usr = listar_cartoes(usuario["id"])
    for i, c in enumerate(cartoes_usr, 2):
        console.print("  [cyan]" + str(i) + "[/cyan] - " + nome_cartao(c))
    if not cartoes_usr:
        console.print("  [dim]  (Nenhum cartao cadastrado — opcao 8 do menu)[/dim]")
    console.print()
    max_pag = 1 + len(cartoes_usr)
    try:
        pag_str = campo("Meio de pagamento",
                        validar=lambda v: None if (v.isdigit() and 1<=int(v)<=max_pag) else "Opcao invalida.",
                        pode_cancelar=True)
    except Cancelado:
        return
    pag_idx   = int(pag_str)
    cartao_id = None

    if pag_idx == 1:
        # Dinheiro/Debito/Pix: mes atual, sem perguntar
        mes_inicio = data_inicio.month
        ano_inicio = data_inicio.year
    else:
        cartao_sel = cartoes_usr[pag_idx - 2]
        cartao_id  = cartao_sel["id"]
        # Calcula mes sugerido pelo fechamento
        mes_sug, ano_sug = calcular_mes_fatura(
            data_inicio.day, data_inicio.month, data_inicio.year, cartao_sel["dia_fecha"]
        )
        console.print()
        console.print("  [bold]Mes da fatura:[/bold]  [dim](fechamento dia " + str(cartao_sel["dia_fecha"]) + ")[/dim]\n")
        opcoes_meses = []
        for delta in range(4):
            m = mes_sug + delta
            a = ano_sug
            while m > 12:
                m -= 12
                a += 1
            opcoes_meses.append((m, a))
        for i, (m, a) in enumerate(opcoes_meses, 1):
            label = MESES_PT[m-1] + "/" + str(a)
            suf = "  [bold yellow](sugerido)[/bold yellow]" if i == 1 else ""
            console.print("  [cyan]" + str(i) + "[/cyan] - " + label + suf)
        console.print()
        try:
            mes_esc = campo("Mes da fatura", dica="Enter para o sugerido",
                            obrigatorio=False, pode_cancelar=True)
        except Cancelado:
            return
        if mes_esc and mes_esc.strip().isdigit() and 1 <= int(mes_esc.strip()) <= len(opcoes_meses):
            mes_inicio, ano_inicio = opcoes_meses[int(mes_esc.strip()) - 1]
        else:
            mes_inicio, ano_inicio = opcoes_meses[0]

    # Parcelas: para dinheiro/debito perguntar mes inicio se > 1
    if parcelas > 1 and pag_idx == 1:
        console.print()
        console.print("  [bold]Mes de inicio das parcelas:[/bold]\n")
        opcoes_meses = []
        for delta in range(4):
            m = data_inicio.month + delta
            a = data_inicio.year
            while m > 12:
                m -= 12
                a += 1
            opcoes_meses.append((m, a))
        for i, (m, a) in enumerate(opcoes_meses, 1):
            label = MESES_PT[m-1] + "/" + str(a)
            suf = "  [bold yellow](atual)[/bold yellow]" if i == 1 else ""
            console.print("  [cyan]" + str(i) + "[/cyan] - " + label + suf)
        console.print()
        try:
            mes_esc = campo("Mes de inicio", dica="Enter para o mes atual",
                            obrigatorio=False, pode_cancelar=True)
        except Cancelado:
            return
        if mes_esc and mes_esc.strip().isdigit() and 1 <= int(mes_esc.strip()) <= len(opcoes_meses):
            mes_inicio, ano_inicio = opcoes_meses[int(mes_esc.strip()) - 1]
        else:
            mes_inicio, ano_inicio = opcoes_meses[0]

    # Salva parcelas
    valor_parcela = round(valor_total / parcelas, 2)
    for i in range(parcelas):
        m = mes_inicio + i
        a = ano_inicio
        while m > 12:
            m -= 12
            a += 1
        data_parcela = str(a) + "-" + str(m).zfill(2) + "-" + str(data_inicio.day).zfill(2)
        desc_parcela = descricao if parcelas == 1 else descricao + " " + str(i+1) + "/" + str(parcelas)
        salvar_gasto_com_data(usuario["id"], categoria["id"], desc_parcela,
                              valor_parcela, data_parcela, cartao_id)

    if parcelas == 1:
        ok("Gasto de R$ " + f"{valor_total:.2f}" + " em '" + categoria["nome"] + "' registrado!")
    else:
        mes_fim = mes_inicio + parcelas - 1
        ano_fim = ano_inicio
        while mes_fim > 12:
            mes_fim -= 12
            ano_fim += 1
        ok(str(parcelas) + "x de R$ " + f"{valor_parcela:.2f}" + " de " +
           MESES_PT[mes_inicio-1] + " a " + MESES_PT[mes_fim-1] + "/" + str(ano_fim) + "!")
    aguardar("\n  Pressione Enter para voltar.")

# ─────────────────────────────────────────
#  TELA: DEFINIR TETO
# ─────────────────────────────────────────
def tela_definir_teto(usuario):
    clear()
    header("Definir Teto de Gastos")
    aviso_voltar()
    garantir_categorias_padrao(usuario["id"])
    console.print("  [bold]Definir teto para:[/bold]\n")
    console.print("  [cyan]1[/cyan] - Teto mensal geral")
    console.print("  [cyan]2[/cyan] - Teto por categoria")
    console.print()
    try:
        escolha = campo("Opcao", validar=lambda v: None if v in ("1","2") else "Digite 1 ou 2.",
                        pode_cancelar=True)
    except Cancelado:
        return
    if escolha == "1":
        teto_atual = buscar_teto_geral(usuario["id"])
        if teto_atual:
            info("Teto atual: R$ " + f"{teto_atual:.2f}")
        try:
            valor_str = campo("Novo teto mensal (R$)", dica="ex: 3000.00",
                              validar=validar_valor, pode_cancelar=True)
        except Cancelado:
            return
        valor = float(valor_str.replace(",", "."))
        salvar_teto(usuario["id"], valor)
        ok("Teto mensal geral definido: R$ " + f"{valor:.2f}")
    else:
        cats = listar_categorias(usuario["id"])
        console.print("\n  [bold]Categorias:[/bold]\n")
        for i, c in enumerate(cats, 1):
            teto     = buscar_teto_categoria(usuario["id"], c["id"])
            teto_str = "R$ " + f"{teto:.2f}" if teto else "sem teto"
            console.print("  [cyan]" + str(i) + "[/cyan] - " + c["nome"].ljust(15) + " [" + teto_str + "]")
        console.print()
        try:
            idx = campo("Categoria",
                        validar=lambda v: None if (v.isdigit() and 1 <= int(v) <= len(cats)) else "Opcao invalida.",
                        pode_cancelar=True)
            categoria = cats[int(idx) - 1]
            valor_str = campo("Teto para '" + categoria["nome"] + "' (R$)", dica="ex: 800.00",
                              validar=validar_valor, pode_cancelar=True)
        except Cancelado:
            return
        valor = float(valor_str.replace(",", "."))
        salvar_teto(usuario["id"], valor, categoria["id"])
        ok("Teto de R$ " + f"{valor:.2f}" + " definido para '" + categoria["nome"] + "'!")
    aguardar("\n  Pressione Enter para voltar.")

# ─────────────────────────────────────────
#  HELPERS — FINANCEIRO POR MÊS
# ─────────────────────────────────────────
MESES_PT = ["Janeiro","Fevereiro","Marco","Abril","Maio","Junho",
            "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]

def buscar_teto_geral_mes(usuario_id, mes):
    """Retorna teto do mes especifico, ou fallback para o teto global ('*')."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT valor FROM tetos WHERE usuario_id=? AND categoria_id IS NULL AND mes=?",
            (usuario_id, mes)
        ).fetchone()
        if row:
            return row["valor"]
        row = conn.execute(
            "SELECT valor FROM tetos WHERE usuario_id=? AND categoria_id IS NULL AND mes='*'",
            (usuario_id,)
        ).fetchone()
        return row["valor"] if row else None

def buscar_teto_categoria_mes(usuario_id, categoria_id, mes):
    """Retorna teto da categoria no mes especifico, ou fallback para o global ('*')."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT valor FROM tetos WHERE usuario_id=? AND categoria_id=? AND mes=?",
            (usuario_id, categoria_id, mes)
        ).fetchone()
        if row:
            return row["valor"]
        row = conn.execute(
            "SELECT valor FROM tetos WHERE usuario_id=? AND categoria_id=? AND mes='*'",
            (usuario_id, categoria_id)
        ).fetchone()
        return row["valor"] if row else None

def resumo_gastos_mes_ref(usuario_id, mes):
    with get_conn() as conn:
        return conn.execute("""
            SELECT c.id, c.nome, SUM(g.valor) as total
            FROM gastos g
            JOIN categorias c ON c.id = g.categoria_id
            WHERE g.usuario_id = ? AND strftime('%Y-%m', g.data) = ?
            GROUP BY c.id, c.nome
            ORDER BY total DESC
        """, (usuario_id, mes)).fetchall()

def listar_gastos_categoria_mes(usuario_id, categoria_id, mes):
    with get_conn() as conn:
        return conn.execute("""
            SELECT descricao, valor, data
            FROM gastos
            WHERE usuario_id = ? AND categoria_id = ?
              AND strftime('%Y-%m', data) = ?
            ORDER BY data DESC
        """, (usuario_id, categoria_id, mes)).fetchall()

# ─────────────────────────────────────────
#  HELPERS — CARTÕES
# ─────────────────────────────────────────
def listar_cartoes(usuario_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM cartoes WHERE usuario_id=? ORDER BY banco",
            (usuario_id,)
        ).fetchall()

def salvar_cartao(usuario_id, banco, ultimos4, limite, dia_venc, dia_fecha):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO cartoes (usuario_id,banco,ultimos4,limite,dia_venc,dia_fecha) VALUES (?,?,?,?,?,?)",
            (usuario_id, banco, ultimos4, limite, dia_venc, dia_fecha)
        )
        conn.commit()

def gastos_cartao_mes(usuario_id, cartao_id, mes):
    with get_conn() as conn:
        row = conn.execute("""
            SELECT SUM(valor) as total FROM gastos
            WHERE usuario_id=? AND cartao_id=? AND strftime('%Y-%m', data)=?
        """, (usuario_id, cartao_id, mes)).fetchone()
        return row["total"] or 0.0

def calcular_mes_fatura(dia_compra, mes_compra, ano_compra, dia_fecha):
    """Retorna (mes, ano) da fatura baseado no dia de fechamento."""
    if dia_compra <= dia_fecha:
        return mes_compra, ano_compra
    else:
        m = mes_compra + 1
        a = ano_compra
        if m > 12:
            m = 1
            a += 1
        return m, a

def nome_cartao(c):
    return c["banco"] + " ..." + c["ultimos4"]

def _ajustar_teto_mes(usuario, mes_ref, mes_label):
    """Permite sobrescrever teto geral ou por categoria apenas para mes_ref."""
    clear()
    header("Ajustar Teto — " + mes_label)
    console.print("  [bold]O que deseja ajustar?[/bold]\n")
    console.print("  [cyan]1[/cyan] - Teto geral deste mes")
    console.print("  [cyan]2[/cyan] - Teto de uma categoria neste mes")
    console.print()
    try:
        op = campo("Opcao", validar=lambda v: None if v in ("1","2") else "Digite 1 ou 2.",
                   pode_cancelar=True)
    except Cancelado:
        return
    if op == "1":
        teto_atual = buscar_teto_geral_mes(usuario["id"], mes_ref)
        if teto_atual:
            info("Teto atual para " + mes_label + ": R$ " + f"{teto_atual:.2f}")
        try:
            valor_str = campo("Novo teto para " + mes_label + " (R$)",
                              dica="ex: 3500.00", validar=validar_valor, pode_cancelar=True)
        except Cancelado:
            return
        salvar_teto(usuario["id"], float(valor_str.replace(",",".")), mes=mes_ref)
        ok("Teto de " + mes_label + " definido: R$ " + f"{float(valor_str.replace(',','.')):.2f}")
    else:
        cats = listar_categorias(usuario["id"])
        console.print("\n  [bold]Categorias:[/bold]\n")
        for i, c in enumerate(cats, 1):
            teto = buscar_teto_categoria_mes(usuario["id"], c["id"], mes_ref)
            teto_str = "R$ " + f"{teto:.2f}" if teto else "sem teto"
            console.print("  [cyan]" + str(i) + "[/cyan] - " + c["nome"].ljust(15) + " [" + teto_str + "]")
        console.print()
        try:
            idx = campo("Categoria",
                        validar=lambda v: None if (v.isdigit() and 1<=int(v)<=len(cats)) else "Opcao invalida.",
                        pode_cancelar=True)
            cat = cats[int(idx)-1]
            valor_str = campo("Teto para '" + cat["nome"] + "' em " + mes_label + " (R$)",
                              dica="ex: 800.00", validar=validar_valor, pode_cancelar=True)
        except Cancelado:
            return
        salvar_teto(usuario["id"], float(valor_str.replace(",",".")), categoria_id=cat["id"], mes=mes_ref)
        ok("Teto de '" + cat["nome"] + "' em " + mes_label + ": R$ " + f"{float(valor_str.replace(',','.')):.2f}")
    aguardar()

# ─────────────────────────────────────────
#  TELA: CHECAR FINANCAS
# ─────────────────────────────────────────
def tela_checar_financas(usuario):
    garantir_categorias_padrao(usuario["id"])
    ano_atual = datetime.now().year
    mes_atual = datetime.now().month
    mes_sel   = mes_atual

    while True:
        clear()
        mes_ref   = str(ano_atual) + "-" + str(mes_sel).zfill(2)
        mes_label = MESES_PT[mes_sel - 1] + "/" + str(ano_atual)
        header("Resumo Financeiro - " + mes_label)

        nav_txt = ("  [dim]Navegacao:[/dim]  "
                   "[bold](A)[/bold] Mes anterior  |  "
                   "[bold](P)[/bold] Proximo mes  |  "
                   "[bold](T)[/bold] Ajustar teto deste mes  |  "
                   "[bold](V)[/bold] Voltar")
        console.print(nav_txt)
        console.print()

        # Grade de meses 4x3
        for i, nome in enumerate(MESES_PT, 1):
            if i == mes_sel:
                celula = "[bold yellow][" + nome[:3] + "/" + str(ano_atual) + "][/bold yellow]"
            else:
                celula = "[dim]" + nome[:3] + "/" + str(ano_atual) + "[/dim]"
            fim = "\n" if i % 4 == 0 else "   "
            console.print("  " + celula, end=fim)
        console.print()
        console.print()

        teto_geral  = buscar_teto_geral_mes(usuario["id"], mes_ref)
        resumo      = resumo_gastos_mes_ref(usuario["id"], mes_ref)
        total_gasto = sum(r["total"] for r in resumo)

        if teto_geral:
            saldo     = teto_geral - total_gasto
            cor_saldo = "green" if saldo >= 0 else "red"
            linha1 = "  Teto mensal geral:  [bold]R$ " + f"{teto_geral:>9.2f}" + "[/bold]"
            linha2 = "  Total gasto:        [bold]R$ " + f"{total_gasto:>9.2f}" + "[/bold]"
            sufixo_saldo = "" if saldo >= 0 else "  [bold red]ESTOURADO[/bold red]"
            linha3 = "  Saldo restante:     [bold " + cor_saldo + "]R$ " + f"{saldo:>9.2f}" + "[/bold " + cor_saldo + "]" + sufixo_saldo
            console.print(Panel(linha1 + "\n" + linha2 + "\n" + linha3,
                                box=rbox.ROUNDED, border_style="cyan", padding=(0, 2)))
        else:
            linha1 = "  Total gasto em " + mes_label + ":  [bold]R$ " + f"{total_gasto:.2f}" + "[/bold]"
            linha2 = "  [dim](Sem teto geral definido para este mes)[/dim]"
            console.print(Panel(linha1 + "\n" + linha2,
                                box=rbox.ROUNDED, border_style="dim", padding=(0, 2)))

        if not resumo:
            console.print("\n  [dim]Nenhum gasto registrado em " + mes_label + ".[/dim]\n")
        else:
            console.print("\n  [bold]Por categoria:[/bold]\n")
            BAR = 20
            for r in resumo:
                teto_cat    = buscar_teto_categoria_mes(usuario["id"], r["id"], mes_ref)
                nome        = r["nome"][:14].ljust(14)
                gasto       = r["total"]
                lancamentos = listar_gastos_categoria_mes(usuario["id"], r["id"], mes_ref)
                if teto_cat:
                    pct    = gasto / teto_cat
                    filled = min(int(pct * BAR), BAR)
                    empty  = BAR - filled
                    cor    = "green" if pct <= 1.0 else "red"
                    if pct <= 1.0:
                        status = "[green][OK][/green]"
                    else:
                        status = "[bold red][ESTOURADO][/bold red]"
                    barra  = "[" + cor + "]" + chr(9608)*filled + "[/" + cor + "][dim]" + chr(9617)*empty + "[/dim]"
                    pct_str = str(int(pct*100)).rjust(3)
                    console.print("  " + nome + "  " + barra + "  R$ " + f"{gasto:>7.2f}" + " / R$ " + f"{teto_cat:.2f}" + "  " + pct_str + "%  " + status)
                else:
                    filled = min(int((gasto / max(total_gasto, 1)) * BAR), BAR)
                    empty  = BAR - filled
                    barra  = "[cyan]" + chr(9608)*filled + "[/cyan][dim]" + chr(9617)*empty + "[/dim]"
                    console.print("  " + nome + "  " + barra + "  R$ " + f"{gasto:>7.2f}" + "  [dim]sem teto[/dim]")
                for l in lancamentos:
                    data_fmt = datetime.strptime(l["data"], "%Y-%m-%d").strftime("%d/%m")
                    desc     = l["descricao"][:28].ljust(28)
                    console.print("  [dim]  " + data_fmt + "  " + desc + "  R$ " + f"{l['valor']:>8.2f}" + "[/dim]")
                console.print()
            console.print("  " + chr(8212)*60)
            if teto_geral:
                pct_t  = total_gasto / teto_geral
                filled = min(int(pct_t * BAR), BAR)
                empty  = BAR - filled
                cor    = "green" if pct_t <= 1.0 else "red"
                barra  = "[" + cor + "]" + chr(9608)*filled + "[/" + cor + "][dim]" + chr(9617)*empty + "[/dim]"
                console.print("  " + "TOTAL".ljust(14) + "  " + barra + "  R$ " + f"{total_gasto:>7.2f}" + " / R$ " + f"{teto_geral:.2f}" + "  " + str(int(pct_t*100)).rjust(3) + "%")
            else:
                console.print("  " + "TOTAL".ljust(14) + "  R$ " + f"{total_gasto:.2f}")
            console.print()

        # ── Seção cartões ──
        cartoes_usr = listar_cartoes(usuario["id"])
        if cartoes_usr:
            console.print("  [bold]Cartoes de credito:[/bold]\n")
            BAR_C = 20
            for c in cartoes_usr:
                usado = gastos_cartao_mes(usuario["id"], c["id"], mes_ref)
                limite = c["limite"]
                pct_c  = usado / limite if limite else 0
                filled = min(int(pct_c * BAR_C), BAR_C)
                empty  = BAR_C - filled
                cor_c  = "green" if pct_c <= 0.8 else ("yellow" if pct_c <= 1.0 else "red")
                barra_c = "[" + cor_c + "]" + chr(9608)*filled + "[/" + cor_c + "][dim]" + chr(9617)*empty + "[/dim]"
                label_c = nome_cartao(c)[:18].ljust(18)
                if pct_c > 1.0:
                    status_c = "  [bold red][ESTOURADO][/bold red]"
                else:
                    status_c = ""
                console.print("  " + label_c + "  " + barra_c +
                              "  R$ " + f"{usado:>8.2f}" + " / R$ " + f"{limite:.2f}" +
                              "  " + str(int(pct_c*100)).rjust(3) + "%" + status_c)
                console.print("  [dim]" + " "*18 + "  Venc: dia " + str(c["dia_venc"]) +
                              "  Fecha: dia " + str(c["dia_fecha"]) + "[/dim]")
            console.print()

        if resumo and _gemini_configurado():
            console.print()
            with console.status("[cyan]Analisando com IA...[/cyan]"):
                insight = gemini_resumo_financeiro(usuario, resumo, teto_geral)
            if insight:
                console.print(Panel(
                    "[bold cyan]🤖 Análise SecretarIA:[/bold cyan]\n\n" + insight,
                    box=rbox.ROUNDED, border_style="cyan", padding=(0, 2)
                ))
                console.print()

        nav = Prompt.ask("  [bold]Opcao[/bold] [dim](A/P/T/V)[/dim]", console=console).strip().upper()
        if nav == "V":
            return
        elif nav == "T":
            _ajustar_teto_mes(usuario, mes_ref, mes_label)
        elif nav == "A":
            if mes_sel > 1:
                mes_sel -= 1
            else:
                aviso("Ja esta em Janeiro/" + str(ano_atual) + ".")
                aguardar()
        elif nav == "P":
            if mes_sel < 12:
                mes_sel += 1
            else:
                aviso("Ja esta em Dezembro/" + str(ano_atual) + ".")
                aguardar()
        else:
            aviso("Use A (anterior), P (proximo) ou V (voltar).")
            aguardar()

# ─────────────────────────────────────────
#  GOOGLE AGENDA — HELPERS
# ─────────────────────────────────────────
def token_path(usuario_id):
    return TOKENS_DIR / ("token_" + str(usuario_id) + ".json")

def get_google_service(usuario_id):
    """Retorna o service autenticado ou None se não conectado/sem lib."""
    if not GOOGLE_DISPONIVEL:
        return None
    tp = token_path(usuario_id)
    if not tp.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(tp), GOOGLE_SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            tp.write_text(creds.to_json())
        except Exception:
            return None
    if not creds or not creds.valid:
        return None
    return build("calendar", "v3", credentials=creds)

def conectar_google(usuario_id):
    """Inicia fluxo OAuth local. Retorna True se conectou."""
    if not GOOGLE_DISPONIVEL:
        aviso("Bibliotecas do Google nao instaladas.")
        aviso("Execute:  pip install google-auth google-auth-oauthlib google-api-python-client")
        aguardar()
        return False
    if not CREDENTIALS_FILE.exists():
        aviso("Arquivo credentials.json nao encontrado na pasta do script.")
        aviso("Baixe em: console.cloud.google.com > Credenciais > OAuth 2.0 > Desktop App")
        aguardar()
        return False
    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), GOOGLE_SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True)
        token_path(usuario_id).write_text(creds.to_json())
        return True
    except Exception as e:
        aviso("Erro ao conectar: " + str(e))
        aguardar()
        return False

def _fmt_evento(ev):
    """Formata um evento do Google para exibição."""
    inicio = ev.get("start", {})
    dt_str = inicio.get("dateTime") or inicio.get("date", "")
    try:
        if "T" in dt_str:
            dt = datetime.fromisoformat(dt_str)
            hora = dt.strftime("%d/%m %H:%M")
        else:
            dt = datetime.strptime(dt_str, "%Y-%m-%d")
            hora = dt.strftime("%d/%m") + " (dia todo)"
    except Exception:
        hora = dt_str
    return hora + "  " + ev.get("summary", "(sem titulo)")

def _listar_eventos(service, time_min, time_max, max_results=20):
    result = service.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime"
    ).execute()
    return result.get("items", [])

# ─────────────────────────────────────────
#  TELA: CONECTAR GOOGLE
# ─────────────────────────────────────────
def tela_conectar_google(usuario):
    clear()
    header("Conectar Google Agenda")
    console.print(Panel(
        "  O navegador sera aberto para voce autorizar o acesso.\n"
        "  Apos autorizar, volte aqui — a conexao sera salva automaticamente.",
        box=rbox.ROUNDED, border_style="cyan", padding=(0, 2)
    ))
    console.print()
    resp = Prompt.ask("  Deseja continuar? [bold](S/N)[/bold]", console=console).strip().upper()
    if resp != "S":
        return
    console.print()
    info("Abrindo navegador...")
    if conectar_google(usuario["id"]):
        # Marca no banco
        with get_conn() as conn:
            conn.execute("UPDATE usuarios SET google_conectado=1 WHERE id=?", (usuario["id"],))
            conn.commit()
        usuario["google_conectado"] = 1
        ok("Google Agenda conectado com sucesso!")
    aguardar()

# ─────────────────────────────────────────
#  TELA: AGENDAR COMPROMISSO
# ─────────────────────────────────────────
def tela_agendar(usuario):
    clear()
    header("Agendar Compromisso")
    aviso_voltar()
    service = get_google_service(usuario["id"])
    if not service:
        aviso("Google Agenda nao conectado. Use a opcao 0 no menu.")
        aguardar()
        return
    try:
        titulo   = campo("Titulo do evento", pode_cancelar=True)
        data_str = campo("Data", dica="DD/MM/AAAA", validar=validar_data, pode_cancelar=True)
        hora_str = campo("Hora de inicio", dica="HH:MM",
                         validar=lambda v: None if re.match(r"^\d{2}:\d{2}$", v) else "Use HH:MM.",
                         pode_cancelar=True)
        dur_str  = campo("Duracao em minutos", dica="ex: 60",
                         validar=lambda v: None if (v.isdigit() and int(v) > 0) else "Numero positivo.",
                         obrigatorio=False, pode_cancelar=True)
        desc     = campo("Descricao", obrigatorio=False, pode_cancelar=True)
    except Cancelado:
        return

    dt_inicio = datetime.strptime(data_str + " " + hora_str, "%d/%m/%Y %H:%M")
    duracao   = int(dur_str) if dur_str else 60
    dt_fim    = dt_inicio + timedelta(minutes=duracao)
    tz        = "America/Sao_Paulo"

    evento = {
        "summary": titulo,
        "description": desc or "",
        "start": {"dateTime": dt_inicio.isoformat(), "timeZone": tz},
        "end":   {"dateTime": dt_fim.isoformat(),    "timeZone": tz},
    }
    try:
        criado = service.events().insert(calendarId="primary", body=evento).execute()
        ok("Evento criado: " + criado.get("summary","") + "  em  " + dt_inicio.strftime("%d/%m/%Y %H:%M"))
    except Exception as e:
        aviso("Erro ao criar evento: " + str(e))
    aguardar()

# ─────────────────────────────────────────
#  TELA: VER AGENDA DE HOJE
# ─────────────────────────────────────────
def tela_agenda_hoje(usuario):
    clear()
    header("Agenda de Hoje")
    service = get_google_service(usuario["id"])
    if not service:
        aviso("Google Agenda nao conectado.")
        aguardar()
        return
    hoje    = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    amanha  = hoje + timedelta(days=1)
    tz_off  = "+00:00"
    eventos = _listar_eventos(service,
                              hoje.isoformat() + tz_off,
                              amanha.isoformat() + tz_off)
    if not eventos:
        console.print("  [dim]Nenhum evento hoje.[/dim]")
    else:
        for ev in eventos:
            console.print("  [cyan]•[/cyan] " + _fmt_evento(ev))
    console.print()
    aguardar()

# ─────────────────────────────────────────
#  TELA: VER AGENDA DA SEMANA
# ─────────────────────────────────────────
def tela_agenda_semana(usuario):
    clear()
    header("Agenda da Semana")
    service = get_google_service(usuario["id"])
    if not service:
        aviso("Google Agenda nao conectado.")
        aguardar()
        return
    hoje   = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    fim    = hoje + timedelta(days=7)
    tz_off = "+00:00"
    eventos = _listar_eventos(service,
                              hoje.isoformat() + tz_off,
                              fim.isoformat() + tz_off, max_results=50)
    if not eventos:
        console.print("  [dim]Nenhum evento nos proximos 7 dias.[/dim]")
    else:
        dia_atual = ""
        for ev in eventos:
            inicio = ev.get("start", {})
            dt_str = inicio.get("dateTime") or inicio.get("date", "")
            try:
                dt = datetime.fromisoformat(dt_str[:10])
                dia = dt.strftime("%A, %d/%m").capitalize()
            except Exception:
                dia = dt_str[:10]
            if dia != dia_atual:
                console.print()
                console.print("  [bold cyan]" + dia + "[/bold cyan]")
                dia_atual = dia
            hora = ""
            if "T" in dt_str:
                try:
                    hora = datetime.fromisoformat(dt_str).strftime("%H:%M") + "  "
                except Exception:
                    pass
            console.print("  [dim]" + hora + "[/dim]" + ev.get("summary","(sem titulo)"))
    console.print()
    aguardar()

# ─────────────────────────────────────────
#  TELA: HORÁRIOS LIVRES
# ─────────────────────────────────────────
def tela_horarios_livres(usuario):
    clear()
    header("Horarios Livres")
    aviso_voltar()
    service = get_google_service(usuario["id"])
    if not service:
        aviso("Google Agenda nao conectado.")
        aguardar()
        return
    try:
        data_str  = campo("Data", dica="DD/MM/AAAA ou Enter para hoje",
                          obrigatorio=False, pode_cancelar=True)
        inicio_str = campo("Inicio do periodo", dica="HH:MM  ex: 08:00",
                           validar=lambda v: None if re.match(r"^\d{2}:\d{2}$", v) else "Use HH:MM.",
                           pode_cancelar=True)
        fim_str    = campo("Fim do periodo", dica="HH:MM  ex: 18:00",
                           validar=lambda v: None if re.match(r"^\d{2}:\d{2}$", v) else "Use HH:MM.",
                           pode_cancelar=True)
        dur_str    = campo("Duracao minima livre (min)", dica="ex: 30",
                           validar=lambda v: None if (v.isdigit() and int(v)>0) else "Numero positivo.",
                           obrigatorio=False, pode_cancelar=True)
    except Cancelado:
        return

    data_ref = datetime.strptime(data_str, "%d/%m/%Y") if data_str else datetime.now()
    data_base = data_ref.strftime("%Y-%m-%d")
    t_ini  = datetime.fromisoformat(data_base + "T" + inicio_str + ":00")
    t_fim  = datetime.fromisoformat(data_base + "T" + fim_str + ":00")
    dur_min = int(dur_str) if dur_str else 30

    eventos = _listar_eventos(service, t_ini.isoformat()+"+00:00", t_fim.isoformat()+"+00:00", max_results=50)

    ocupados = []
    for ev in eventos:
        ini = ev.get("start",{}).get("dateTime")
        fim = ev.get("end",{}).get("dateTime")
        if ini and fim:
            try:
                ocupados.append((datetime.fromisoformat(ini).replace(tzinfo=None),
                                 datetime.fromisoformat(fim).replace(tzinfo=None)))
            except Exception:
                pass
    ocupados.sort()

    livres = []
    cursor = t_ini
    for (oi, of) in ocupados:
        if cursor < oi and (oi - cursor).seconds // 60 >= dur_min:
            livres.append((cursor, oi))
        cursor = max(cursor, of)
    if cursor < t_fim and (t_fim - cursor).seconds // 60 >= dur_min:
        livres.append((cursor, t_fim))

    console.print()
    console.print("  [bold]Horarios livres em " + data_ref.strftime("%d/%m/%Y") + ":[/bold]\n")
    if not livres:
        console.print("  [dim]Nenhum horario livre com " + str(dur_min) + "+ minutos.[/dim]")
    else:
        for (li, lf) in livres:
            mins = int((lf - li).seconds / 60)
            console.print("  [green]•[/green] " + li.strftime("%H:%M") + " – " + lf.strftime("%H:%M") +
                          "  [dim](" + str(mins) + " min)[/dim]")
    console.print()
    aguardar()

# ─────────────────────────────────────────
#  TELA: CANCELAR COMPROMISSO
# ─────────────────────────────────────────
def tela_cancelar_compromisso(usuario):
    clear()
    header("Cancelar Compromisso")
    aviso_voltar()
    service = get_google_service(usuario["id"])
    if not service:
        aviso("Google Agenda nao conectado.")
        aguardar()
        return
    hoje   = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    fim    = hoje + timedelta(days=30)
    tz_off = "+00:00"
    eventos = _listar_eventos(service, hoje.isoformat()+tz_off, fim.isoformat()+tz_off, max_results=30)
    if not eventos:
        console.print("  [dim]Nenhum evento nos proximos 30 dias.[/dim]")
        aguardar()
        return
    console.print("  [bold]Eventos dos proximos 30 dias:[/bold]\n")
    for i, ev in enumerate(eventos, 1):
        console.print("  [cyan]" + str(i) + "[/cyan] - " + _fmt_evento(ev))
    console.print()
    try:
        idx_str = campo("Numero do evento para cancelar",
                        validar=lambda v: None if (v.isdigit() and 1<=int(v)<=len(eventos)) else "Opcao invalida.",
                        pode_cancelar=True)
    except Cancelado:
        return
    ev_sel = eventos[int(idx_str)-1]
    console.print()
    console.print("  Evento: [bold]" + ev_sel.get("summary","") + "[/bold]")
    confirm = Prompt.ask("  Confirma cancelamento? [bold](S/N)[/bold]", console=console).strip().upper()
    if confirm != "S":
        aviso("Cancelamento abortado.")
        aguardar()
        return
    try:
        service.events().delete(calendarId="primary", eventId=ev_sel["id"]).execute()
        ok("Evento cancelado: " + ev_sel.get("summary",""))
    except Exception as e:
        aviso("Erro ao cancelar: " + str(e))
    aguardar()

# ─────────────────────────────────────────
#  TELA: BOT PRINCIPAL
# ─────────────────────────────────────────
def tela_bot(usuario):
    clear()
    nome_curto       = usuario["nome"].split()[0]
    google_conectado = bool(usuario.get("google_conectado", 0))
    header("Ola, " + nome_curto + "! Bem-vindo(a) de volta.")
    if not google_conectado:
        console.print(Panel(
            "[bold yellow][*] Voce nao conectou seu Google Agenda![/bold yellow]\n"
            "    Para receber lembretes, digite  [bold]0[/bold]  e pressione Enter.",
            box=rbox.ROUNDED, border_style="yellow", padding=(0, 2)
        ))
        console.print()
    console.print("[bold]  O que deseja fazer?[/bold]\n")
    console.print("  [dim]-- Agenda --[/dim]")
    for num, desc in [("1","Agendar compromisso"),("2","Ver agenda de hoje"),
                      ("3","Ver agenda da semana"),("4","Horarios livres"),
                      ("5","Cancelar compromisso")]:
        console.print("  [cyan]" + num + "[/cyan] - " + desc)
    if not google_conectado:
        console.print("  [cyan]0[/cyan] - Conectar Google Agenda")
    console.print()
    console.print("  [dim]-- Financas --[/dim]")
    console.print("  [cyan]6[/cyan] - Adicionar gasto")
    console.print("  [cyan]7[/cyan] - Definir teto de gastos")
    console.print("  [cyan]8[/cyan] - Cadastrar cartao de credito")
    console.print("  [cyan]9[/cyan] - Checar financas")
    console.print()
    console.print()
    console.print("  [dim]-- Inteligência Artificial --[/dim]")
    _ia_st = "[green]ativa ✓[/green]" if _gemini_configurado() else "[yellow]use IA p/ configurar[/yellow]"
    console.print("  [cyan]G[/cyan]  - Falar com a SecretarIA  [dim](" + _ia_st + ")[/dim]")
    console.print("  [cyan]IA[/cyan] - Configurar Gemini API Key")
    console.print()
    console.print("  [red]S[/red] - Sair (logout)  ->  Digite S e pressione Enter")
    console.print()
    escolha = Prompt.ask("  [bold]Opcao[/bold]", console=console).strip().upper()
    if escolha == "S":
        clear()
        console.print(Panel("[bold cyan]Ate logo![/bold cyan]",
                            box=rbox.ROUNDED, border_style="cyan", padding=(1, 4)))
        aguardar()
        return False
    if escolha == "6":
        tela_adicionar_gasto(usuario)
        return True
    if escolha == "7":
        tela_definir_teto(usuario)
        return True
    if escolha == "8":
        tela_cadastrar_cartao(usuario)
        return True
    if escolha == "9":
        tela_checar_financas(usuario)
        return True
    if escolha == "0" and not google_conectado:
        tela_conectar_google(usuario)
        return True
    if escolha == "1":
        tela_agendar(usuario)
        return True
    if escolha == "2":
        tela_agenda_hoje(usuario)
        return True
    if escolha == "3":
        tela_agenda_semana(usuario)
        return True
    if escolha == "4":
        tela_horarios_livres(usuario)
        return True
    if escolha == "5":
        tela_cancelar_compromisso(usuario)
        return True
    if escolha == "G":
        tela_chat_ia(usuario)
        return True
    if escolha == "IA":
        tela_configurar_gemini()
        return True
    aviso("Opcao invalida.")
    aguardar()
    return True

# ─────────────────────────────────────────
#  TELA: ADMIN
# ─────────────────────────────────────────
def tela_admin():
    while True:
        clear()
        header("Painel Administrativo")

        total, ativos, excluidos, hist = buscar_estatisticas()
        console.print(Panel(
            "  Total de contas criadas:  [bold]" + str(total) + "[/bold]\n"
            "  Contas ativas:            [bold green]" + str(ativos) + "[/bold green]\n"
            "  Contas excluidas:         [bold red]" + str(excluidos) + "[/bold red]",
            title="[cyan]Estatísticas de Uso[/cyan]",
            box=rbox.ROUNDED, border_style="cyan", padding=(0, 2)
        ))
        console.print()
        if hist:
            etab = RichTable(box=rbox.SIMPLE, header_style="bold dim", show_lines=False)
            etab.add_column("Reg.", style="dim",   width=5,  justify="center")
            etab.add_column("Criado em",  style="white", width=20)
            etab.add_column("Excluído em", style="red",  width=20)
            for h in hist:
                excl = h["excluido_em"][:16] if h["excluido_em"] else "[green]-[/green]"
                etab.add_row(str(h["id"]), h["criado_em"][:16], excl)
            console.print(etab)
            console.print()

        with get_conn() as conn:
            usuarios = conn.execute(
                "SELECT id, nome, email, telefone, criado_em FROM usuarios ORDER BY id"
            ).fetchall()

        if not usuarios:
            console.print(Panel("[dim]Nenhum usuario ativo cadastrado.[/dim]",
                                box=rbox.ROUNDED, border_style="dim", padding=(1, 4)))
        else:
            tabela = RichTable(box=rbox.ROUNDED, border_style="cyan",
                               header_style="bold cyan", show_lines=True)
            tabela.add_column("ID",       style="dim",        width=5,  justify="center")
            tabela.add_column("Nome",     style="bold white", width=25)
            tabela.add_column("E-mail",   style="cyan",       width=30)
            tabela.add_column("Telefone", style="white",      width=15)
            tabela.add_column("Cadastro", style="dim",        width=20)
            for u in usuarios:
                tabela.add_row(str(u["id"]), u["nome"], u["email"],
                               u["telefone"], u["criado_em"][:16] if u["criado_em"] else "-")
            console.print(tabela)

        console.print()
        console.print("  [cyan]E[/cyan] - Desativar/excluir usuario pelo ID")
        console.print("  [red]V[/red] - Voltar ao menu principal")
        console.print()
        escolha = Prompt.ask("  [bold]Opcao[/bold]", console=console).strip().upper()
        if escolha == "V":
            return
        if escolha == "E":
            if not usuarios:
                aviso("Nao ha usuarios para excluir.")
                aguardar()
                continue
            id_str = Prompt.ask("  [bold]ID do usuario a excluir[/bold]", console=console).strip()
            if not id_str.isdigit():
                aviso("ID invalido.")
                aguardar()
                continue
            usuario_id = int(id_str)
            with get_conn() as conn:
                usuario = conn.execute("SELECT * FROM usuarios WHERE id=?", (usuario_id,)).fetchone()
            if not usuario:
                erro("Nenhum usuario encontrado com ID " + str(usuario_id) + ".")
                aguardar()
                continue
            console.print(Panel(
                "[bold]Nome:[/bold]  " + usuario["nome"] + "\n"
                "[bold]Email:[/bold] " + usuario["email"],
                title="[yellow]Confirmar exclusao[/yellow]",
                box=rbox.ROUNDED, border_style="yellow", padding=(0, 2)
            ))
            confirmacao = Prompt.ask(
                "  [bold yellow]Tem certeza? Digite SIM para confirmar[/bold yellow]",
                console=console
            ).strip().upper()
            if confirmacao == "SIM":
                with get_conn() as conn:
                    conn.execute("DELETE FROM recuperacao_senha WHERE usuario_id=?", (usuario_id,))
                    conn.execute("DELETE FROM gastos WHERE usuario_id=?", (usuario_id,))
                    conn.execute("DELETE FROM tetos WHERE usuario_id=?", (usuario_id,))
                    conn.execute("DELETE FROM categorias WHERE usuario_id=?", (usuario_id,))
                    conn.execute("DELETE FROM usuarios WHERE id=?", (usuario_id,))
                    conn.commit()
                registrar_exclusao_usuario()
                ok("Usuario '" + usuario["nome"] + "' excluido com sucesso.")
            else:
                info("Exclusao cancelada.")
            aguardar()
        else:
            aviso("Opcao invalida.")
            aguardar()

def tela_login_admin():
    clear()
    header("Acesso Administrativo")
    aviso_voltar()
    email = Prompt.ask("  [bold]E-mail admin[/bold] [dim](ou V para voltar)[/dim]",
                       console=console).strip()
    if email.upper() == "V":
        return
    senha = ler_senha("  Senha admin: ")
    if email.lower() == ADMIN_EMAIL.lower() and senha == ADMIN_SENHA:
        ok("Acesso autorizado!")
        aguardar()
        tela_admin()
    else:
        erro("Credenciais invalidas.")
        aguardar()

# ─────────────────────────────────────────
#  TELA INICIAL
# ─────────────────────────────────────────
def tela_inicial():
    clear()
    header()
    opcoes_txt = Text(justify="center")
    opcoes_txt.append("1", style="bold cyan");   opcoes_txt.append(" - Fazer login\n")
    opcoes_txt.append("2", style="bold cyan");   opcoes_txt.append(" - Criar usuario\n")
    opcoes_txt.append("3", style="bold yellow"); opcoes_txt.append(" - Acesso administrativo\n")
    opcoes_txt.append("0", style="bold red");    opcoes_txt.append(" - Encerrar programa")
    console.print(Panel(Align.center(opcoes_txt), box=rbox.ROUNDED,
                        border_style="cyan", padding=(1, 6)))
    console.print()
    return Prompt.ask("  [bold]Escolha uma opcao[/bold]", console=console).strip()

# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────
def main():
    init_db()
    while True:
        escolha = tela_inicial()
        if escolha == "1":
            usuario = tela_login()
            if usuario:
                while tela_bot(usuario):
                    pass
        elif escolha == "2":
            tela_criar_usuario()
        elif escolha == "3":
            tela_login_admin()
        elif escolha == "0":
            clear()
            console.print(Panel("[bold cyan]Programa encerrado. Ate logo![/bold cyan]",
                                box=rbox.ROUNDED, border_style="cyan", padding=(1, 4)))
            sys.exit(0)
        else:
            aviso("Opcao invalida.")
            aguardar()

if __name__ == "__main__":
    main()
