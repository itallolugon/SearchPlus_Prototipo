"""
Search+ Backend — Flask API
Serve o frontend em http://127.0.0.1:5000 e expõe todos os endpoints da API.
"""

import os
import json
import hashlib
import mimetypes
import queue
import sqlite3
import subprocess
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from flask import Flask, jsonify, request, send_file, send_from_directory, session
from flask_cors import CORS

# ──────────────────────────────────────────────────────────────────────────────
# Configuração de caminhos e chaves
# ──────────────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent          # .../SearchPlus-front-end/backend/
FRONTEND_DIR = BASE_DIR.parent            # .../SearchPlus-front-end/
DB_PATH = BASE_DIR / "searchplus.db"

# ──────────────────────────────────────────────────────────────────────────────
# Libs opcionais (sem crash se não instaladas)
# ──────────────────────────────────────────────────────────────────────────────

try:
    import ollama as _ollama
    OLLAMA_OK = True
except ImportError:
    OLLAMA_OK = False

try:
    import fitz  # PyMuPDF
    PYMUPDF_OK = True
except ImportError:
    PYMUPDF_OK = False

try:
    from docx import Document as DocxDoc
    DOCX_OK = True
except ImportError:
    DOCX_OK = False

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np
    SKLEARN_OK = True
except ImportError:
    SKLEARN_OK = False

# Força uso do cache local por padrão — evita timeouts de rede ao checar arquivos no HuggingFace.
# Para baixar modelos pela primeira vez, rode com: SEARCHPLUS_OFFLINE=0 py backend/app.py
if os.environ.get("SEARCHPLUS_OFFLINE", "1") == "1":
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

try:
    from sentence_transformers import SentenceTransformer as _ST
    _SBERT = _ST("paraphrase-multilingual-MiniLM-L12-v2")
    SBERT_OK = True
    print("[AI] Sentence Transformers carregado — busca semântica ativa.")
except Exception as _e:
    SBERT_OK = False
    print(f"[AI] Sentence Transformers indisponível: {_e}")

# ── CLIP: busca visual direta (texto↔imagem no mesmo espaço vetorial) ───────
# Dois modelos: encoder de texto multilingual + encoder de imagem original.
# Total ~1.1GB no primeiro download. Rode uma vez com SEARCHPLUS_OFFLINE=0.
try:
    from PIL import Image as _PILImage
    PIL_OK = True
except ImportError:
    PIL_OK = False

try:
    if not PIL_OK:
        raise ImportError("Pillow não instalado (pip install Pillow).")
    from sentence_transformers import SentenceTransformer as _ST2
    _CLIP_TXT = _ST2("sentence-transformers/clip-ViT-B-32-multilingual-v1")
    _CLIP_IMG = _ST2("sentence-transformers/clip-ViT-B-32")
    CLIP_OK = True
    print("[AI] CLIP multilingual carregado — busca visual ativa.")
except Exception as _e:
    CLIP_OK = False
    print(f"[AI] CLIP indisponível (busca visual desligada): {_e}")

# ── BM25: busca por palavra-chave (complemento ao SBERT) ────────────────────
try:
    from rank_bm25 import BM25Okapi
    BM25_OK = True
except ImportError:
    BM25_OK = False
    print("[AI] rank_bm25 indisponível — busca híbrida cairá para SBERT puro.")

# ──────────────────────────────────────────────────────────────────────────────
# Flask App
# ──────────────────────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")
app.secret_key = "searchplus_secret_2024_XkQ!9@#mZ"
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True

CORS(
    app,
    supports_credentials=True,
    origins=[
        "http://127.0.0.1:5000",
        "http://localhost:5000",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "null",
    ],
)

# ──────────────────────────────────────────────────────────────────────────────
# Estado global do motor de IA (thread-safe)
# ──────────────────────────────────────────────────────────────────────────────

_queue: queue.Queue = queue.Queue()
_processed: int = 0
_status: str = "Ocioso"
_lock = threading.Lock()

def _normalizar(text: str) -> str:
    """Converte para minúsculo e remove acentos. 'Cão' → 'cao'."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(c) != "Mn"
    )


def _gerar_embedding(text: str) -> list[float] | None:
    """Gera embedding semântico do texto usando Sentence Transformers."""
    if not SBERT_OK or not text.strip():
        return None
    try:
        return _SBERT.encode(text, convert_to_numpy=True).tolist()
    except Exception as exc:
        print(f"[SBERT] Erro ao gerar embedding: {exc}")
        return None


def _gerar_embedding_clip_imagem(filepath: str) -> list[float] | None:
    """Gera embedding CLIP visual da imagem. Fica no mesmo espaço vetorial do encoder de texto multilingual."""
    if not CLIP_OK:
        return None
    try:
        with _PILImage.open(filepath) as img:
            img = img.convert("RGB")
            vec = _CLIP_IMG.encode(img, convert_to_numpy=True)
        return vec.tolist()
    except Exception as exc:
        print(f"[CLIP] Erro ao gerar embedding de imagem: {exc}")
        return None


def _gerar_embedding_clip_texto(text: str) -> list[float] | None:
    """Gera embedding CLIP do texto (multilingual) — compatível com imagens."""
    if not CLIP_OK or not text.strip():
        return None
    try:
        return _CLIP_TXT.encode(text, convert_to_numpy=True).tolist()
    except Exception as exc:
        print(f"[CLIP] Erro ao gerar embedding de texto: {exc}")
        return None


def _extrair_campos_llava(desc: str) -> str:
    """
    Extrai campos semanticamente ricos da saída LLaVA para gerar embedding.
    Inclui 'O que é', 'Pessoas', 'Objetos', 'Ações' e 'Tags'.
    Descarta 'Ambiente' (cores/local) para reduzir ruído.
    Retorna o texto original se o formato estruturado não for encontrado.
    """
    campos_alvo = {"o que e", "pessoas", "animais", "objetos", "acoes", "tags"}
    linhas_extraidas = []

    for linha in desc.splitlines():
        limpa = linha.strip().lstrip("-• ").strip()
        norm  = _normalizar(limpa)
        campo = norm.split(":")[0].strip() if ":" in norm else ""
        if campo in campos_alvo:
            linhas_extraidas.append(limpa)

    return " | ".join(linhas_extraidas) if linhas_extraidas else desc


def _rerank_com_llm(query: str, candidatos: list[dict], topk: int = 20) -> list[dict]:
    """
    Reordena os top-K candidatos usando llama3.2 como juiz de relevância.
    Blend 50/50 entre score base (SBERT+BM25+CLIP) e nota do LLM.
    Salvaguarda: se o base é alto (>= 0.60) e o LLM discorda fortemente (<= 0.2),
    ignora o LLM — provável erro de julgamento, não descartamos um hit óbvio.
    Se Ollama falhar ou só houver 1 candidato, devolve inalterado (degrada gracioso).
    """
    if not OLLAMA_OK or not candidatos:
        return candidatos

    topo = candidatos[:topk]
    resto = candidatos[topk:]

    # Monta bloco numerado compacto: descrição truncada para não estourar contexto
    itens = []
    for i, c in enumerate(topo, 1):
        desc = (c.get("descricao_ia") or c.get("nome") or "")[:300].replace("\n", " ")
        itens.append(f"{i}. {desc}")

    prompt = (
        f'Consulta do usuário: "{query}"\n\n'
        "Abaixo há arquivos numerados. Para CADA arquivo, dê uma nota de 0 a 10 "
        "indicando o quanto ele é relevante à consulta. Seja generoso com SINÔNIMOS "
        "e termos relacionados (ex: 'cachorro' = 'cão' = 'pet'; 'mulher' inclui 'menina'; "
        "'comida' inclui 'prato', 'refeição').\n"
        "Critério: 10 = diretamente sobre o tema; 7-9 = contém claramente o tema; "
        "4-6 = relação indireta; 0-3 = não tem relação.\n\n"
        "Responda APENAS em JSON, sem markdown, sem explicação. "
        "Formato: {\"1\": 8, \"2\": 3, \"3\": 10, ...}\n\n"
        + "\n".join(itens)
    )

    try:
        resp = _ollama.chat(
            model="llama3.2",
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.0},
        )
        raw = resp["message"]["content"].strip()
        if raw.startswith("```"):
            raw = raw.strip("`").lstrip("json").strip()
        notas = json.loads(raw)
    except Exception as exc:
        print(f"[Rerank] Falhou, mantendo ordem original: {exc}")
        return candidatos

    # Palavras originais da query + variantes morfológicas (cobre 'homem'→'homens'
    # sem trazer ruído de sinônimos genéricos como 'adulto')
    q_palavras_literais = set()
    for w in _tokenizar(query):
        if len(w) >= 3:
            q_palavras_literais.update(_variantes_morfologicas(w))

    for i, c in enumerate(topo, 1):
        nota = notas.get(str(i), notas.get(i))
        if not isinstance(nota, (int, float)):
            continue
        llm_score = max(0.0, min(1.0, float(nota) / 10.0))
        base = c["score"]

        # Salvaguarda 1: hit forte do motor + LLM "rejeita" → LLM provavelmente errou
        if base >= 0.60 and llm_score <= 0.20:
            print(f"[Rerank] LLM rejeitou '{c['nome']}' (base={base:.2f}) — ignorando nota LLM")
            continue

        # Salvaguarda 2: palavra da query aparece LITERALMENTE na descrição → piso 0.5
        # Evita que o LLM mate um match direto (ex: 'carne' em 'kebab de carne')
        desc_norm = _normalizar(c.get("descricao_ia") or "")
        if any(w in desc_norm for w in q_palavras_literais):
            llm_score = max(llm_score, 0.5)

        c["score_original"] = base
        c["score_llm"]      = round(llm_score, 3)
        c["score"]          = round(0.5 * base + 0.5 * llm_score, 4)

    topo.sort(key=lambda x: x["score"], reverse=True)
    return topo + resto


def _variantes_morfologicas(palavra: str) -> set[str]:
    """
    Gera variantes singular↔plural em português, cobrindo o caso problemático
    do plural nasal (homem→homens, jovem→jovens) que substring puro não pega.
    Mantém-se pequeno e focado — não substitui um stemmer real, mas cobre
    os 90% dos casos sem dependência extra.
    """
    out = {palavra}
    if len(palavra) < 4:
        return out
    # Plural nasal: homem ↔ homens, jovem ↔ jovens
    if palavra.endswith("m"):
        out.add(palavra[:-1] + "ns")
    elif palavra.endswith("ns"):
        out.add(palavra[:-2] + "m")
    # Plural regular: gato ↔ gatos
    elif palavra.endswith("s"):
        out.add(palavra[:-1])
    else:
        out.add(palavra + "s")
    return out


def _texto_para_embedding(desc: str) -> str:
    """
    Prepara texto da descrição LLaVA para virar embedding de alto recall.
    Expande sinônimos no próprio texto do documento (não só na query), então
    uma imagem com 'Cão' também casa com buscas por 'cachorro', 'caozinho' etc.
    """
    campos = _extrair_campos_llava(desc)
    tokens = _tokenizar(campos)
    expandido = _expandir_sinonimos(tokens)
    return expandido or _normalizar(campos)

# ──────────────────────────────────────────────────────────────────────────────
# Banco de dados SQLite
# ──────────────────────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            config_json   TEXT    DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS folders (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id  INTEGER NOT NULL,
            path     TEXT    NOT NULL,
            name     TEXT    NOT NULL,
            added_at TEXT    NOT NULL,
            UNIQUE (user_id, path),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS files (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            folder_id       INTEGER,
            user_id         INTEGER NOT NULL,
            nome            TEXT    NOT NULL,
            caminho         TEXT    NOT NULL,
            tipo            TEXT    NOT NULL,
            descricao_ia    TEXT    DEFAULT '',
            embedding       TEXT    DEFAULT NULL,
            embedding_clip  TEXT    DEFAULT NULL,
            data_adicionado TEXT    NOT NULL,
            favorito        INTEGER DEFAULT 0,
            processado      INTEGER DEFAULT 0,
            UNIQUE (user_id, caminho),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    """)
    # Migrações idempotentes para bancos antigos
    for coluna, ddl in (
        ("embedding",      "ALTER TABLE files ADD COLUMN embedding TEXT DEFAULT NULL"),
        ("embedding_clip", "ALTER TABLE files ADD COLUMN embedding_clip TEXT DEFAULT NULL"),
    ):
        try:
            conn.execute(ddl)
            conn.commit()
            print(f"[DB] Coluna '{coluna}' adicionada.")
        except sqlite3.OperationalError:
            pass  # Coluna já existe
    conn.commit()
    conn.close()


# Garante que as tabelas existam ao carregar o módulo (idempotente)
try:
    init_db()
    print("[DB] Banco de dados pronto.")
except Exception as _db_exc:
    print(f"[DB] ERRO na inicialização: {_db_exc}")


def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


def _uid():
    """Retorna user_id da sessão ou None."""
    return session.get("user_id")


# ──────────────────────────────────────────────────────────────────────────────
# Servir frontend (sem CORS, same-origin)
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/")
def serve_index():
    return send_from_directory(str(FRONTEND_DIR), "index.html")


@app.route("/<path:filename>")
def serve_static(filename):
    if filename.startswith("api/"):
        return jsonify({"error": "not found"}), 404
    return send_from_directory(str(FRONTEND_DIR), filename)


# ──────────────────────────────────────────────────────────────────────────────
# Autenticação
# ──────────────────────────────────────────────────────────────────────────────

_DEFAULT_CFG = {
    "perfil_nome": "",
    "perfil_handle": "",
    "perfil_bio": "",
    "perfil_cargo": "",
    "perfil_local": "",
    "perfil_avatar": "",
    "perfil_banner": "",
    "cor_primaria": "#A855F7",
    "cor_secundaria": "#E879F9",
    "cor_texto_botao": "#FFFFFF",
    "tema": "dark",
    "bg_url": "",
    "bg_blur": 15,
    "idioma": "pt-BR",
}


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()

    if not username or not password:
        return jsonify({"mensagem": "Preencha todos os campos."}), 400

    conn = get_db()
    row = conn.execute(
        "SELECT id, password_hash FROM users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()

    if row and row["password_hash"] == _hash(password):
        session["user_id"] = row["id"]
        session["username"] = username
        return jsonify({"status": "ok", "username": username})

    return jsonify({"mensagem": "Usuário ou senha incorretos."}), 401


@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()

    if not username or not password:
        return jsonify({"mensagem": "Preencha todos os campos."}), 400

    cfg = {**_DEFAULT_CFG, "perfil_nome": username, "perfil_handle": username.lower()}

    try:
        conn = get_db()
    except Exception as exc:
        print(f"[DB] Falha ao conectar: {exc}")
        return jsonify({"mensagem": f"Erro ao conectar ao banco: {exc}"}), 500

    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, config_json) VALUES (?, ?, ?)",
            (username, _hash(password), json.dumps(cfg)),
        )
        conn.commit()
        return jsonify({"status": "ok"})
    except sqlite3.IntegrityError:
        return jsonify({"mensagem": "Este usuário já existe."}), 409
    except Exception as exc:
        print(f"[DB] Erro no registro: {exc}")
        return jsonify({"mensagem": f"Erro interno: {exc}"}), 500
    finally:
        conn.close()


# Alias para /api/cadastro (caso o front use os dois)
@app.route("/api/cadastro", methods=["POST"])
def api_cadastro():
    return api_register()


@app.route("/api/check_session")
def api_check_session():
    uid = _uid()
    if not uid:
        return jsonify({"error": "Sem sessão ativa."}), 401

    # Verifica se o usuário ainda existe no banco (ex: após deletar o DB)
    conn = get_db()
    user = conn.execute("SELECT username FROM users WHERE id = ?", (uid,)).fetchone()
    conn.close()

    if user:
        return jsonify({"username": user["username"]})

    # Usuário não existe mais — limpa sessão e força novo login
    session.clear()
    return jsonify({"error": "Usuário não encontrado."}), 401


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"status": "ok"})


# ──────────────────────────────────────────────────────────────────────────────
# Configuração do usuário
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    uid = _uid()

    if request.method == "GET":
        if not uid:
            # Retorna padrões para o front carregar cores antes do login
            return jsonify({**_DEFAULT_CFG, "pastas": [], "historico_pastas": False})

        conn = get_db()
        row = conn.execute("SELECT config_json FROM users WHERE id = ?", (uid,)).fetchone()
        folders = conn.execute(
            "SELECT path FROM folders WHERE user_id = ? ORDER BY added_at", (uid,)
        ).fetchall()
        conn.close()

        cfg = {**_DEFAULT_CFG, **json.loads(row["config_json"] or "{}")} if row else dict(_DEFAULT_CFG)
        cfg["pastas"] = [f["path"] for f in folders]
        cfg["historico_pastas"] = len(cfg["pastas"]) > 0
        return jsonify(cfg)

    # POST – salvar configurações
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    data = request.get_json(force=True) or {}
    # Remove campos derivados para não poluir o JSON salvo
    data.pop("pastas", None)
    data.pop("historico_pastas", None)

    conn = get_db()
    conn.execute("UPDATE users SET config_json = ? WHERE id = ?", (json.dumps(data), uid))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


# ──────────────────────────────────────────────────────────────────────────────
# Pastas monitoradas
# ──────────────────────────────────────────────────────────────────────────────

def _list_folders(uid: int):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, path FROM folders WHERE user_id = ? ORDER BY added_at", (uid,)
    ).fetchall()
    conn.close()
    return rows


@app.route("/api/folders", methods=["GET", "POST", "DELETE"])
def api_folders():
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    if request.method == "GET":
        rows = _list_folders(uid)
        return jsonify({"pastas": [r["path"] for r in rows]})

    if request.method == "POST":
        data = request.get_json(force=True) or {}
        pasta = (data.get("pasta") or "").strip()

        if not pasta or not os.path.isdir(pasta):
            return jsonify({"error": "Caminho inválido ou inexistente."}), 400

        name = os.path.basename(pasta) or pasta
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO folders (user_id, path, name, added_at) VALUES (?, ?, ?, ?)",
                (uid, pasta, name, datetime.now().isoformat()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            pass  # Pasta já cadastrada
        finally:
            conn.close()

        # Análise em background
        threading.Thread(target=_scan_folder, args=(pasta, uid), daemon=True).start()

        rows = _list_folders(uid)
        return jsonify({"status": "ok", "pastas": [r["path"] for r in rows]})

    # DELETE
    data = request.get_json(force=True) or {}
    pasta = (data.get("pasta") or "").strip()

    conn = get_db()
    conn.execute("DELETE FROM folders WHERE user_id = ? AND path = ?", (uid, pasta))
    conn.commit()
    conn.close()

    rows = _list_folders(uid)
    return jsonify({"status": "ok", "pastas": [r["path"] for r in rows]})


@app.route("/api/folders/<int:folder_id>", methods=["DELETE"])
def api_delete_folder_by_id(folder_id):
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    conn = get_db()
    conn.execute("DELETE FROM folders WHERE id = ? AND user_id = ?", (folder_id, uid))
    conn.commit()
    conn.close()

    rows = _list_folders(uid)
    return jsonify({"status": "ok", "pastas": [r["path"] for r in rows]})


# ──────────────────────────────────────────────────────────────────────────────
# Servir arquivos locais pelo caminho absoluto
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/file/<path:filepath>")
def api_serve_file(filepath):
    # Flask decodifica %XX automaticamente; backslash (%5C) também
    filepath = unquote(filepath)
    filepath = os.path.normpath(filepath)

    if not os.path.isfile(filepath):
        return jsonify({"error": "Arquivo não encontrado."}), 404

    mime, _ = mimetypes.guess_type(filepath)
    return send_file(filepath, mimetype=mime or "application/octet-stream")


# ──────────────────────────────────────────────────────────────────────────────
# Diálogos nativos do Windows (tkinter)
# ──────────────────────────────────────────────────────────────────────────────

def _tk_pick(mode: str):
    """Abre seletor nativo. mode='image' | 'folder'. Retorna path ou None."""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        root.wm_attributes("-topmost", 1)
    except Exception:
        pass

    if mode == "image":
        path = filedialog.askopenfilename(
            title="Selecionar Imagem",
            filetypes=[
                ("Imagens", "*.png *.jpg *.jpeg *.gif *.webp *.bmp"),
                ("Todos os arquivos", "*.*"),
            ],
        )
    else:
        path = filedialog.askdirectory(title="Selecionar Pasta")

    root.destroy()
    return os.path.normpath(path) if path else None


@app.route("/api/choose_image")
def api_choose_image():
    try:
        path = _tk_pick("image")
        if path:
            return jsonify({"status": "sucesso", "caminho": path})
        return jsonify({"status": "cancelado"})
    except Exception as exc:
        return jsonify({"status": "erro", "mensagem": str(exc)})


@app.route("/api/choose_folder")
def api_choose_folder():
    try:
        path = _tk_pick("folder")
        if path:
            return jsonify({"status": "sucesso", "pasta": path})
        return jsonify({"status": "cancelado"})
    except Exception as exc:
        return jsonify({"status": "erro", "mensagem": str(exc)})


# ──────────────────────────────────────────────────────────────────────────────
# Busca semântica (TF-IDF)
# ──────────────────────────────────────────────────────────────────────────────

_EXT_IMG   = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}
_EXT_VID   = {"mp4", "avi", "mkv", "mov", "webm"}
_EXT_AUD   = {"mp3", "wav", "ogg", "m4a", "flac"}

# Stopwords em português — palavras sem valor semântico que poluem o embedding
_STOPWORDS_PT = {
    "a", "o", "as", "os", "um", "uma", "uns", "umas",
    "de", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas",
    "e", "ou", "que", "com", "por", "para", "pra", "pro", "pelo", "pela",
    "ao", "aos", "aquele", "aquela", "este", "esta", "esse", "essa", "isto", "isso",
    "meu", "minha", "seu", "sua", "nosso", "nossa",
    "mostrar", "mostre", "ver", "encontrar", "achar", "buscar", "procurar",
    "foto", "fotos", "imagem", "imagens", "arquivo", "arquivos", "tem", "ter",
    "algum", "alguma", "qualquer", "todo", "toda", "tudo", "nada",
    "eu", "tu", "nos", "vos",
}

# Termos de busca por PESSOA humana (sem acentos)
_TERMOS_PESSOA = {
    "pessoa", "pessoas", "gente", "humano", "humanos",
    "homem", "homens", "mulher", "mulheres",
    "garoto", "garota", "menino", "menina",
    "crianca", "criancas", "bebe", "bebes", "neném", "nenem",
    "adulto", "adultos", "jovem", "jovens", "idoso", "idosa",
    "cara", "moca", "rapaz", "individuo", "senhor", "senhora",
    "pai", "mae", "mamae", "papai", "irmao", "irma",
    "namorado", "namorada", "esposa", "marido",
}

# Termos de busca por ANIMAL
_TERMOS_ANIMAL = {
    "cachorro", "cachorra", "cao", "caozinho", "cachorrinho", "dog", "vira-lata", "viralata",
    "gato", "gata", "gatinho", "gatinha", "felino", "bichano", "cat",
    "pet", "pets", "animal", "animais", "bicho", "bichinho",
    "passaro", "passarinho", "ave", "aves",
    "cavalo", "coelho", "hamster", "peixe", "tartaruga", "papagaio",
}

# Frases na descrição LLaVA que confirmam AUSÊNCIA de pessoas (normalizadas)
_FRASES_SEM_PESSOA = (
    "nenhuma pessoa", "sem pessoas", "nenhum humano", "sem humanos",
    "nenhuma figura humana", "nao ha pessoas", "pessoas: nenhuma",
    "pessoas: nao", "pessoas: 0", "pessoa: nenhuma",
)

# Frases que confirmam AUSÊNCIA de animais
_FRASES_SEM_ANIMAL = (
    "nenhum animal", "sem animais", "nao ha animais", "animais: nenhum",
)

# Dicionário de sinônimos — MUITO expandido (chaves sem acentos)
_SINONIMOS_QUERY: dict[str, list[str]] = {
    # ── Animais ──────────────────────────────────────────────────────────
    "cao":         ["cachorro", "caozinho", "cachorrinho", "cachorra", "dog", "pet"],
    "caes":        ["cachorro", "cao", "caozinhos", "cachorrinhos", "dogs", "pets"],
    "ca":          ["cao", "cachorro"],  # truncamento comum do LLaVA
    "cae":         ["cao", "cachorro"],  # truncamento comum do LLaVA
    "cachorro":    ["cao", "caozinho", "cachorrinho", "cachorra", "filhote", "pet", "dog"],
    "cachorros":   ["cachorro", "cao", "caes", "pets"],
    "caozinho":    ["cachorro", "cao", "cachorrinho", "filhote"],
    "caozinhos":   ["cachorro", "caes", "cachorrinhos", "filhotes"],
    "cachorrinho": ["cachorro", "caozinho", "cao", "filhote"],
    "cachorrinhos":["cachorros", "caozinhos", "caes", "filhotes"],
    "cachorra":    ["cachorro", "cao", "cadela"],
    "cadela":      ["cachorra", "cachorro", "cao"],
    "filhote":     ["cachorro", "cao", "caozinho", "bebe animal"],
    "filhotes":    ["cachorros", "caes", "caozinhos"],
    "dog":         ["cachorro", "cao"],
    "dogs":        ["cachorros", "caes"],
    "vira-lata":   ["cachorro", "cao"],
    "viralata":    ["cachorro", "cao"],

    "gato":      ["gatinho", "gata", "felino", "bichano", "cat"],
    "gatos":     ["gatinhos", "gatas", "felinos", "bichanos"],
    "gatinha":   ["gata", "gato", "gatinho", "felina"],
    "gatinho":   ["gato", "gata", "felino", "filhote"],
    "gatinhos":  ["gatos", "gatas", "felinos", "filhotes"],
    "gata":      ["gato", "gatinha", "felina"],
    "gatas":     ["gatos", "gatinhas", "felinas"],
    "felino":    ["gato", "gatinho"],
    "felinos":   ["gatos", "gatinhos"],
    "bichano":   ["gato", "gatinho"],
    "bichanos":  ["gatos", "gatinhos"],

    "pet":      ["cachorro", "gato", "animal domestico", "bicho de estimacao"],
    "pets":     ["cachorros", "gatos", "animais"],
    "animal":   ["bicho", "pet", "fauna"],
    "animais":  ["bichos", "pets", "fauna"],
    "bicho":    ["animal", "pet"],
    "passaro":  ["ave", "passarinho"],
    "ave":      ["passaro", "passarinho"],

    # ── Pessoas feminino ─────────────────────────────────────────────────
    "menina":   ["garota", "moca", "garotinha", "mocinha", "adolescente feminina"],
    "garota":   ["menina", "moca", "garotinha", "jovem feminina"],
    "moca":     ["menina", "garota", "mulher jovem", "mocinha"],
    "mulher":   ["senhora", "dona", "feminino", "adulta"],
    "mulheres": ["mulher", "senhoras", "donas"],
    "senhora":  ["mulher", "dona", "adulta"],
    "mae":      ["mulher", "mamae", "genitora"],
    "mamae":    ["mae", "mulher"],
    "irma":     ["mulher jovem", "garota"],
    "namorada": ["mulher", "garota", "moça"],
    "esposa":   ["mulher", "senhora"],

    # ── Pessoas masculino ────────────────────────────────────────────────
    "menino":   ["garoto", "rapaz", "garotinho", "adolescente masculino"],
    "garoto":   ["menino", "rapaz", "garotinho", "jovem masculino"],
    "rapaz":    ["menino", "garoto", "homem jovem"],
    "homem":    ["senhor", "rapaz", "masculino", "adulto"],
    "homens":   ["homem", "senhores"],
    "senhor":   ["homem", "adulto"],
    "pai":      ["homem", "papai", "genitor"],
    "papai":    ["pai", "homem"],
    "irmao":    ["homem jovem", "garoto"],
    "namorado": ["homem", "garoto", "rapaz"],
    "marido":   ["homem", "senhor"],

    # ── Criança / bebê ───────────────────────────────────────────────────
    "bebe":     ["crianca", "infante", "recem nascido", "nenem", "bebezinho"],
    "bebes":    ["criancas", "bebes"],
    "nenem":    ["bebe", "crianca"],
    "crianca":  ["menino", "menina", "infante", "bebe"],
    "criancas": ["meninos", "meninas", "bebes"],
    "jovem":    ["adolescente"],
    "jovens":   ["adolescentes"],

    # ── Natureza / lugares ───────────────────────────────────────────────
    "praia":    ["litoral", "mar", "areia", "costa"],
    "mar":      ["oceano", "praia", "agua"],
    "oceano":   ["mar", "praia"],
    "montanha": ["serra", "morro", "pico"],
    "floresta": ["mata", "bosque", "selva", "arvores"],
    "mata":     ["floresta", "bosque", "verde"],
    "cidade":   ["urbano", "metropole", "centro"],
    "rua":      ["avenida", "estrada", "calcada"],
    "parque":   ["jardim", "area verde"],
    "jardim":   ["parque", "horta"],
    "ceu":      ["firmamento", "nuvens"],

    # ── Veículos ─────────────────────────────────────────────────────────
    "carro":     ["automovel", "veiculo", "auto"],
    "automovel": ["carro", "veiculo"],
    "veiculo":   ["carro", "automovel"],
    "moto":      ["motocicleta"],
    "motocicleta": ["moto"],
    "bicicleta": ["bike"],
    "bike":      ["bicicleta"],

    # ── Objetos comuns ───────────────────────────────────────────────────
    "celular":   ["telefone", "smartphone"],
    "telefone":  ["celular", "smartphone"],
    "smartphone": ["celular", "telefone"],
    "computador": ["pc", "notebook", "laptop"],
    "notebook":  ["laptop", "computador"],
    "laptop":    ["notebook", "computador"],

    # ── Comida ───────────────────────────────────────────────────────────
    "carne":     ["kebab", "frango", "porco", "boi", "churrasco", "bife", "almoco"],
    "kebab":     ["carne", "espeto", "churrasco"],
    "frango":    ["carne", "ave"],
    "comida":    ["alimento", "refeicao", "prato", "almoco", "janta"],
    "refeicao":  ["comida", "alimento", "prato"],

    # ── Cores ────────────────────────────────────────────────────────────
    "vermelho":  ["vermelha", "rubro", "encarnado"],
    "preto":     ["preta", "escuro", "negro"],
    "branco":    ["branca", "claro"],
    "azul":      ["azulado", "azulada"],
    "verde":     ["verdejante"],
    "amarelo":   ["amarela", "dourado"],

    # ── Roupas ───────────────────────────────────────────────────────────
    "roupa":    ["roupas", "vestimenta", "traje"],
    "camiseta": ["blusa", "camisa"],
    "camisa":   ["camiseta", "blusa"],
    "vestido":  ["traje"],
    "sapato":   ["tenis", "calcado"],
    "tenis":    ["sapato", "calcado"],
}

# Termos de GÊNERO na QUERY
_TERMOS_FEMININO = {
    "menina", "meninas", "garota", "garotas", "moca", "mocas",
    "mulher", "mulheres", "feminina", "feminino", "femininas",
    "mae", "mamae", "irma", "namorada", "esposa", "senhora",
    "dona", "tia", "vovó", "vovo", "filha",
}
_TERMOS_MASCULINO = {
    "menino", "meninos", "garoto", "garotos", "rapaz", "rapazes",
    "homem", "homens", "masculino", "masculina",
    "pai", "papai", "irmao", "namorado", "marido", "senhor",
    "tio", "vovô", "vovo", "filho",
}

# Palavras na DESCRIÇÃO que identificam GÊNERO (normalizadas)
_PALAVRAS_DESC_MASC = {
    "homem", "homens", "menino", "meninos", "garoto", "garotos",
    "rapaz", "rapazes", "senhor", "masculino", "namorado", "marido",
    "barba", "bigode",
}
_PALAVRAS_DESC_FEM = {
    "mulher", "mulheres", "menina", "meninas", "garota", "garotas",
    "moca", "mocas", "senhora", "feminino", "namorada", "esposa",
    "vestido", "saia",
}


def _tokenizar(texto: str) -> list[str]:
    """Normaliza, quebra em palavras e remove stopwords."""
    norm = _normalizar(texto)
    return [w for w in norm.split() if w and w not in _STOPWORDS_PT]


def _expandir_sinonimos(palavras: list[str]) -> str:
    """Expande uma lista de tokens com sinônimos, mantendo ordem e unicidade."""
    expandido: list[str] = []
    vistos: set[str] = set()
    for p in palavras:
        if p not in vistos:
            expandido.append(p)
            vistos.add(p)
        for s in _SINONIMOS_QUERY.get(p, []):
            if s not in vistos:
                expandido.append(s)
                vistos.add(s)
    return " ".join(expandido)


def _analisar_query(query: str) -> dict:
    """
    Analisa a query do usuário e extrai metadados úteis para a busca:
    normalização, tokens relevantes, expansão com sinônimos, e intenção
    (pessoa/animal/gênero).
    """
    norm = _normalizar(query)
    palavras = _tokenizar(query)
    palavras_set = set(palavras)
    return {
        "original":        query,
        "normalizada":     norm,
        "palavras":        palavras,
        "palavras_set":    palavras_set,
        "expandida":       _expandir_sinonimos(palavras) or norm,
        "busca_pessoa":    bool(palavras_set & _TERMOS_PESSOA),
        "busca_animal":    bool(palavras_set & _TERMOS_ANIMAL),
        "busca_feminino":  bool(palavras_set & _TERMOS_FEMININO),
        "busca_masculino": bool(palavras_set & _TERMOS_MASCULINO),
    }


def _ajustar_score(score_raw: float, q: dict, desc_norm: str, nome_norm: str) -> float | None:
    """
    Aplica regras de negócio sobre o score (blended ou SBERT puro):
    - Rejeita matches impossíveis (pessoa vs imagem sem pessoa, gênero oposto)
    - Aplica boosts: nome do arquivo, keyword match, gênero compatível
    Threshold mínimo de relevância fica no pré-filtro SBERT (no api_search).
    Retorna None se o resultado deve ser descartado.
    """
    if score_raw < 0.20:
        return None

    desc_words = set(desc_norm.split())

    # === Regras de rejeição ===============================================

    # Busca de pessoa não pode retornar imagem sem pessoa
    if q["busca_pessoa"] and score_raw < 0.90:
        if any(frase in desc_norm for frase in _FRASES_SEM_PESSOA):
            return None

    # Busca de animal não pode retornar imagem sem animal
    if q["busca_animal"] and score_raw < 0.90:
        if any(frase in desc_norm for frase in _FRASES_SEM_ANIMAL):
            return None

    # Gênero: descrição só com termos masculinos é rejeitada para query feminina
    if q["busca_feminino"] and score_raw < 0.85:
        tem_masc = bool(desc_words & _PALAVRAS_DESC_MASC)
        tem_fem  = bool(desc_words & _PALAVRAS_DESC_FEM)
        if tem_masc and not tem_fem:
            return None
    if q["busca_masculino"] and score_raw < 0.85:
        tem_fem  = bool(desc_words & _PALAVRAS_DESC_FEM)
        tem_masc = bool(desc_words & _PALAVRAS_DESC_MASC)
        if tem_fem and not tem_masc:
            return None

    # === Boosts (aumentam o score) ========================================

    score = score_raw

    # Query exata dentro do nome do arquivo → +15%
    if q["normalizada"] and q["normalizada"] in nome_norm:
        score += 0.15

    # Cada palavra-chave da query que aparece na descrição → +5%
    matches_desc = q["palavras_set"] & desc_words
    if matches_desc:
        score += 0.05 * len(matches_desc)

    # Gênero da query combina com descrição → +8%
    if q["busca_feminino"] and (desc_words & _PALAVRAS_DESC_FEM):
        score += 0.08
    if q["busca_masculino"] and (desc_words & _PALAVRAS_DESC_MASC):
        score += 0.08

    return min(1.0, score)


def _bm25_scores(corpus_tokens: list[list[str]], query_tokens: list[str]) -> list[float]:
    """
    Calcula scores BM25 sobre um corpus de tokens para uma query já tokenizada.
    Retorna lista vazia se BM25 indisponível ou corpus vazio. Scores são
    normalizados para [0, 1] dividindo pelo máximo.
    """
    if not BM25_OK or not corpus_tokens or not query_tokens:
        return [0.0] * len(corpus_tokens)
    try:
        bm25 = BM25Okapi(corpus_tokens)
        raw  = bm25.get_scores(query_tokens).tolist()
        mx   = max(raw) if raw else 0.0
        if mx <= 0:
            return [0.0] * len(raw)
        return [s / mx for s in raw]
    except Exception as exc:
        print(f"[BM25] Erro: {exc}")
        return [0.0] * len(corpus_tokens)


def _match_filter(ext: str, filtro: str) -> bool:
    ext = ext.lower()
    if filtro == "all":
        return True
    if filtro == "imagem":
        return ext in _EXT_IMG
    if filtro == "midia":
        return ext in _EXT_VID or ext in _EXT_AUD
    # 'documento' ou desconhecido
    return ext not in _EXT_IMG and ext not in _EXT_VID and ext not in _EXT_AUD


def _trecho(desc: str, query: str) -> str:
    if not desc:
        return "Nenhum conteúdo..."
    q = query.lower()
    d = desc.lower()
    if q in d:
        idx = d.index(q)
        start = max(0, idx - 60)
        return desc[start : start + 240].strip()
    return desc[:240].strip()


@app.route("/api/search", methods=["GET", "POST"])
def api_search():
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    if request.method == "POST":
        data = request.get_json(force=True) or {}
        query  = (data.get("query") or "").strip()
        filtro = data.get("filtro", "all")
    else:
        query  = (request.args.get("q") or "").strip()
        filtro = request.args.get("filtro", "all")

    if not query:
        return jsonify({"resultados": [], "tempo": 0})

    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM files WHERE user_id = ? AND processado = 1", (uid,)
    ).fetchall()
    conn.close()

    files = [r for r in rows if _match_filter(r["tipo"], filtro)]
    if not files:
        return jsonify({"resultados": [], "tempo": 0})

    t0 = time.time()

    # ── Busca híbrida: SBERT (semântica) + BM25 (keyword) + CLIP (visual) ────
    if SBERT_OK:
        files_emb = [f for f in files if f["embedding"]]
        files_sem_emb = [f for f in files if not f["embedding"]]

        results = []
        q = _analisar_query(query)

        if files_emb:
            import numpy as np

            # 1) SBERT — score semântico sobre o texto da descrição
            query_emb = _SBERT.encode(q["expandida"], convert_to_numpy=True)
            doc_embs  = np.array([json.loads(f["embedding"]) for f in files_emb])
            sbert_sims = cosine_similarity([query_emb], doc_embs)[0].tolist()

            # 2) BM25 — score de palavra-chave sobre descrição + nome
            corpus_tokens = [
                _tokenizar((f["descricao_ia"] or "") + " " + (f["nome"] or ""))
                for f in files_emb
            ]
            bm25_sims = _bm25_scores(corpus_tokens, q["palavras"])

            # 3) CLIP — score visual (texto↔imagem) só para imagens com embedding CLIP
            clip_sims: list[float] = [0.0] * len(files_emb)
            if CLIP_OK:
                clip_query_vec = _gerar_embedding_clip_texto(q["original"])
                if clip_query_vec is not None:
                    clip_q_np = np.array([clip_query_vec])
                    for i, f in enumerate(files_emb):
                        if f["tipo"] in _EXT_IMG and f["embedding_clip"]:
                            try:
                                img_vec = np.array([json.loads(f["embedding_clip"])])
                                clip_sims[i] = float(cosine_similarity(clip_q_np, img_vec)[0][0])
                            except Exception:
                                pass

            # 4) Blend dos três scores — pesos diferentes para imagens vs outros
            # Imagens: CLIP entra com peso; outros: só SBERT + BM25
            W_SBERT_IMG, W_BM25_IMG, W_CLIP_IMG = 0.45, 0.25, 0.30
            W_SBERT_DOC, W_BM25_DOC             = 0.65, 0.35

            # Match literal: palavras originais da query + variantes morfológicas
            # (singular↔plural). Não usa a expansão inteira para evitar matches
            # espúrios em sinônimos genéricos como "adulto", "feminino".
            palavras_literais = set()
            for w in q["palavras"]:
                if len(w) >= 3:
                    palavras_literais.update(_variantes_morfologicas(w))

            def _filtrar_e_pontuar(threshold_sbert: float) -> list:
                """Aplica filtro+score com um threshold específico. Usado para fallback adaptativo."""
                out = []
                for f, s_sbert, s_bm25, s_clip in zip(files_emb, sbert_sims, bm25_sims, clip_sims):
                    desc_norm_local = _normalizar(f["descricao_ia"] or "")
                    tem_texto     = s_sbert >= threshold_sbert
                    tem_visual    = (f["tipo"] in _EXT_IMG and CLIP_OK and s_clip >= 0.25)
                    tem_keyword   = s_bm25 >= 0.5 and bool(q["palavras_set"])
                    # Match literal: palavra da query aparece na descrição (cobre 'carne' em 'kebab de carne')
                    match_literal = any(w in desc_norm_local for w in palavras_literais)
                    if not (tem_texto or tem_visual or tem_keyword or match_literal):
                        continue

                    if f["tipo"] in _EXT_IMG and CLIP_OK and s_clip > 0:
                        blended = W_SBERT_IMG * s_sbert + W_BM25_IMG * s_bm25 + W_CLIP_IMG * s_clip
                    else:
                        blended = W_SBERT_DOC * s_sbert + W_BM25_DOC * s_bm25

                    desc      = f["descricao_ia"] or ""
                    desc_norm = _normalizar(desc)
                    nome_norm = _normalizar(f["nome"])
                    score = _ajustar_score(float(blended), q, desc_norm, nome_norm)
                    if score is None:
                        continue
                    out.append((f, desc, score))
                return out

            # Busca adaptativa: tenta threshold normal; se vazio, afrouxa só um pouco
            # (0.30 ainda bloqueia falso-positivo tipo 'gato' → cachorro em 0.28).
            candidatos = _filtrar_e_pontuar(0.35)
            if not candidatos:
                candidatos = _filtrar_e_pontuar(0.30)

            for f, desc, score in candidatos:
                results.append({
                    "id": f["id"], "nome": f["nome"], "caminho": f["caminho"],
                    "tipo": f["tipo"], "descricao_ia": desc, "conteudo": desc,
                    "trecho": _trecho(desc, query), "data": f["data_adicionado"],
                    "favorito": bool(f["favorito"]), "score": round(score, 4),
                })

        # Arquivos ainda sem embedding: fallback por nome de arquivo
        for f in files_sem_emb:
            nome_norm = _normalizar(f["nome"])
            if q["normalizada"] and q["normalizada"] in nome_norm:
                desc = f["descricao_ia"] or ""
                results.append({
                    "id": f["id"], "nome": f["nome"], "caminho": f["caminho"],
                    "tipo": f["tipo"], "descricao_ia": desc, "conteudo": desc,
                    "trecho": _trecho(desc, query), "data": f["data_adicionado"],
                    "favorito": bool(f["favorito"]), "score": 0.5,
                })

    # ── Fallback TF-IDF (quando SBERT não está disponível) ──────────────────
    else:
        corpus = [_normalizar(r["descricao_ia"] or r["nome"]) for r in files]
        q_norm = _normalizar(query)
        if SKLEARN_OK:
            try:
                vec  = TfidfVectorizer(min_df=1, sublinear_tf=True, analyzer="word")
                mat  = vec.fit_transform(corpus + [q_norm])
                sims = cosine_similarity(mat[-1:], mat[:-1])[0].tolist()
            except Exception:
                sims = _fallback_sims(files, q_norm)
        else:
            sims = _fallback_sims(files, q_norm)

        max_sim = max(sims) if sims else 0.0
        sims_n  = [s / max_sim for s in sims] if max_sim >= 0.02 else [0.0] * len(sims)

        results = []
        for f, score, score_raw in zip(files, sims_n, sims):
            if score_raw < 0.02 or score < 0.20:
                continue
            if query.lower() in f["nome"].lower():
                score = min(1.0, score + 0.20)
            desc = f["descricao_ia"] or ""
            results.append({
                "id": f["id"], "nome": f["nome"], "caminho": f["caminho"],
                "tipo": f["tipo"], "descricao_ia": desc, "conteudo": desc,
                "trecho": _trecho(desc, query), "data": f["data_adicionado"],
                "favorito": bool(f["favorito"]), "score": round(float(score), 4),
            })

    results.sort(key=lambda x: x["score"], reverse=True)

    # Re-rank com LLM-juiz sobre os top-20. Se o Ollama não responder a tempo,
    # devolve a ordem SBERT+BM25 pura (degrada gracioso).
    if results:
        results = _rerank_com_llm(query, results, topk=20)
        # Corte final: depois do LLM, tudo < 0.20 vira ruído. Remove.
        results = [r for r in results if r["score"] >= 0.20]

    tempo = round(time.time() - t0, 3)
    return jsonify({"resultados": results[:60], "tempo": tempo})


def _fallback_sims(files, query: str):
    q = query.lower()
    sims = []
    for f in files:
        desc = (f["descricao_ia"] or "").lower()
        nome = f["nome"].lower()
        if q in desc:
            sims.append(0.8)
        elif q in nome:
            sims.append(0.5)
        elif any(w in desc for w in q.split() if len(w) > 2):
            sims.append(0.3)
        else:
            sims.append(0.0)
    return sims


# ──────────────────────────────────────────────────────────────────────────────
# Favoritos
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/favorites")
def api_favorites():
    uid = _uid()
    if not uid:
        return jsonify({"resultados": []})

    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM files WHERE user_id = ? AND favorito = 1 ORDER BY data_adicionado DESC",
        (uid,),
    ).fetchall()
    conn.close()

    results = [
        {
            "id":          r["id"],
            "nome":        r["nome"],
            "caminho":     r["caminho"],
            "tipo":        r["tipo"],
            "descricao_ia": r["descricao_ia"] or "",
            "conteudo":    r["descricao_ia"] or "",
            "trecho":      (r["descricao_ia"] or "")[:200],
            "data":        r["data_adicionado"],
            "favorito":    True,
            "score":       1.0,
        }
        for r in rows
    ]
    return jsonify({"resultados": results})


@app.route("/api/favorites/toggle", methods=["POST"])
def api_favorites_toggle():
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    data    = request.get_json(force=True) or {}
    file_id = data.get("id")

    conn = get_db()
    row  = conn.execute(
        "SELECT favorito FROM files WHERE id = ? AND user_id = ?", (file_id, uid)
    ).fetchone()

    if not row:
        conn.close()
        return jsonify({"error": "Arquivo não encontrado."}), 404

    new_fav = 1 - int(row["favorito"])
    conn.execute(
        "UPDATE files SET favorito = ? WHERE id = ? AND user_id = ?", (new_fav, file_id, uid)
    )
    conn.commit()
    conn.close()

    return jsonify({"status": "sucesso", "favorito": bool(new_fav)})


# ──────────────────────────────────────────────────────────────────────────────
# Status do motor
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    with _lock:
        return jsonify({
            "status":                    _status,
            "arquivos_pendentes":        _queue.qsize(),
            "arquivos_processados_sessao": _processed,
        })


@app.route("/api/debug/files")
def api_debug_files():
    """Mostra todos os arquivos indexados com preview da descrição."""
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401
    conn = get_db()
    rows = conn.execute(
        "SELECT id, nome, tipo, processado, embedding IS NOT NULL as tem_embedding, "
        "substr(descricao_ia,1,120) as desc_preview FROM files WHERE user_id = ?",
        (uid,)
    ).fetchall()
    conn.close()
    return jsonify({
        "total": len(rows),
        "sbert_disponivel": SBERT_OK,
        "ollama_disponivel": OLLAMA_OK,
        "arquivos": [dict(r) for r in rows]
    })


@app.route("/api/debug/scores")
def api_debug_scores():
    """Mostra scores brutos SBERT para uma query, sem aplicar threshold."""
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"error": "Passe ?q=sua_busca na URL."}), 400
    if not SBERT_OK:
        return jsonify({"error": "SBERT nao carregou. Verifique o log do servidor."}), 400

    try:
        conn = get_db()
        todos = conn.execute(
            "SELECT COUNT(*) as n FROM files WHERE user_id = ?", (uid,)
        ).fetchone()["n"]
        rows_emb = conn.execute(
            "SELECT nome, tipo, embedding, substr(descricao_ia,1,200) as desc_preview "
            "FROM files WHERE user_id = ? AND embedding IS NOT NULL",
            (uid,),
        ).fetchall()
        conn.close()

        if not rows_emb:
            return jsonify({
                "query": query,
                "erro": "Nenhum arquivo tem embedding ainda.",
                "total_arquivos": todos,
                "dica": "Clique em 'Analisar Pastas' para gerar os embeddings.",
            })

        import numpy as np
        from sklearn.metrics.pairwise import cosine_similarity as _cos_sim
        q = _analisar_query(query)
        query_emb = _SBERT.encode(q["expandida"], convert_to_numpy=True)
        doc_embs  = np.array([json.loads(r["embedding"]) for r in rows_emb])
        sims      = _cos_sim([query_emb], doc_embs)[0].tolist()

        resultados = sorted([
            {"nome": r["nome"], "tipo": r["tipo"],
             "score": round(s, 4), "passa_threshold": s >= 0.35,
             "desc_preview": r["desc_preview"]}
            for r, s in zip(rows_emb, sims)
        ], key=lambda x: x["score"], reverse=True)

        return jsonify({
            "query": query,
            "query_expandida": q["expandida"],
            "threshold_atual": 0.35,
            "total_arquivos": todos,
            "com_embedding": len(rows_emb),
            "resultados": resultados,
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ──────────────────────────────────────────────────────────────────────────────
# Análise forçada
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/analyze_folders", methods=["POST"])
def api_analyze_folders():
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    conn    = get_db()
    folders = conn.execute(
        "SELECT path FROM folders WHERE user_id = ?", (uid,)
    ).fetchall()
    conn.close()

    for f in folders:
        threading.Thread(target=_scan_folder, args=(f["path"], uid), daemon=True).start()

    return jsonify({"status": "ok", "mensagem": f"{len(folders)} pasta(s) sendo analisadas."})


# ──────────────────────────────────────────────────────────────────────────────
# Re-análise seletiva (apenas arquivos novos ou com descrição ruim)
# ──────────────────────────────────────────────────────────────────────────────

_DESCRICOES_RUINS = ("Imagem:", "PDF:", "Documento:", "Texto:", "Vídeo:", "Áudio:")

@app.route("/api/reanalyze", methods=["POST"])
def api_reanalyze():
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    conn = get_db()
    # Marca como não processado: arquivos com descrição ruim (fallback) ou vazios
    conditions = " OR ".join(
        f"descricao_ia LIKE ?" for _ in _DESCRICOES_RUINS
    )
    rows = conn.execute(
        f"SELECT id, caminho, nome, tipo FROM files WHERE user_id = ? AND (processado = 0 OR embedding IS NULL OR {conditions})",
        (uid, *[f"{p}%" for p in _DESCRICOES_RUINS])
    ).fetchall()

    ids = [r["id"] for r in rows]
    if ids:
        conn.execute(
            f"UPDATE files SET processado = 0, descricao_ia = '', embedding = NULL WHERE id IN ({','.join('?'*len(ids))})",
            ids
        )
        conn.commit()
    conn.close()

    # Re-enfileira os arquivos para análise
    for r in rows:
        _queue.put({"path": r["caminho"], "nome": r["nome"], "ext": r["tipo"], "uid": uid})

    return jsonify({"status": "ok", "reenfileirados": len(rows)})


# ──────────────────────────────────────────────────────────────────────────────
# Re-geração rápida de embeddings (sem re-executar LLaVA)
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/reembed", methods=["POST"])
def api_reembed():
    """
    Re-gera os embeddings de todos os arquivos já processados:
    - SBERT a partir da descrição textual (rápido)
    - CLIP a partir da imagem no disco (lento, só imagens)
    Não chama LLaVA novamente.
    """
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401
    if not SBERT_OK and not CLIP_OK:
        return jsonify({"error": "Nenhum modelo de embedding disponível.", "atualizados": 0}), 400

    conn = get_db()
    rows = conn.execute(
        "SELECT id, caminho, tipo, descricao_ia FROM files "
        "WHERE user_id = ? AND processado = 1 AND descricao_ia != ''",
        (uid,),
    ).fetchall()
    conn.close()

    total = len(rows)

    def _worker():
        ok_sbert = 0
        ok_clip  = 0
        for r in rows:
            sets: list[str] = []
            vals: list = []

            if SBERT_OK:
                texto_emb = _texto_para_embedding(r["descricao_ia"])
                emb = _gerar_embedding(texto_emb)
                if emb:
                    sets.append("embedding = ?")
                    vals.append(json.dumps(emb))
                    ok_sbert += 1

            if CLIP_OK and r["tipo"] in _EXT_IMG and os.path.isfile(r["caminho"]):
                emb_clip = _gerar_embedding_clip_imagem(r["caminho"])
                if emb_clip:
                    sets.append("embedding_clip = ?")
                    vals.append(json.dumps(emb_clip))
                    ok_clip += 1

            if sets:
                vals.append(r["id"])
                c = get_db()
                c.execute(f"UPDATE files SET {', '.join(sets)} WHERE id = ?", vals)
                c.commit()
                c.close()
        print(f"[Reembed] SBERT: {ok_sbert} | CLIP: {ok_clip} | Total varrido: {total}")

    threading.Thread(target=_worker, daemon=True).start()
    return jsonify({"status": "ok", "atualizados": total})


# ──────────────────────────────────────────────────────────────────────────────
# Histórico de buscas
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/search_history", methods=["GET"])
def api_search_history():
    uid = _uid()
    if not uid:
        return jsonify({"historico": []})
    conn = get_db()
    row  = conn.execute("SELECT config_json FROM users WHERE id = ?", (uid,)).fetchone()
    conn.close()
    cfg  = json.loads(row["config_json"] or "{}") if row else {}
    return jsonify({"historico": cfg.get("search_history", [])})


@app.route("/api/search_history", methods=["POST"])
def api_add_search_history():
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401
    query = (request.get_json(force=True) or {}).get("query", "").strip()
    if not query:
        return jsonify({"error": "Query vazia."}), 400

    conn = get_db()
    row  = conn.execute("SELECT config_json FROM users WHERE id = ?", (uid,)).fetchone()
    cfg  = json.loads(row["config_json"] or "{}") if row else {}

    historico = cfg.get("search_history", [])
    if query in historico:
        historico.remove(query)
    historico.insert(0, query)
    cfg["search_history"] = historico[:10]  # Mantém só as 10 últimas

    conn.execute("UPDATE users SET config_json = ? WHERE id = ?", (json.dumps(cfg), uid))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "historico": cfg["search_history"]})


@app.route("/api/search_history/<int:index>", methods=["DELETE"])
def api_delete_search_history(index):
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401
    conn = get_db()
    row  = conn.execute("SELECT config_json FROM users WHERE id = ?", (uid,)).fetchone()
    cfg  = json.loads(row["config_json"] or "{}") if row else {}
    historico = cfg.get("search_history", [])
    if 0 <= index < len(historico):
        historico.pop(index)
    cfg["search_history"] = historico
    conn.execute("UPDATE users SET config_json = ? WHERE id = ?", (json.dumps(cfg), uid))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "historico": historico})


# ──────────────────────────────────────────────────────────────────────────────
# Abrir local do arquivo no Explorer
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/open_location")
def api_open_location():
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    filepath = unquote(request.args.get("path", "")).strip()
    filepath = os.path.normpath(filepath)

    if not os.path.exists(filepath):
        return jsonify({"error": "Arquivo não encontrado."}), 404

    # Abre o Explorer com o arquivo selecionado
    subprocess.Popen(["explorer", "/select,", filepath])
    return jsonify({"status": "ok"})


# ──────────────────────────────────────────────────────────────────────────────
# Pipeline de IA em background
# ──────────────────────────────────────────────────────────────────────────────

_EXT_ALL = (
    _EXT_IMG | _EXT_VID | _EXT_AUD |
    {"pdf", "docx", "doc", "txt", "odt", "csv", "xlsx"}
)


def _scan_folder(folder_path: str, uid: int) -> None:
    global _status
    with _lock:
        _status = f"Escaneando: {os.path.basename(folder_path)}"

    conn = get_db()
    row  = conn.execute(
        "SELECT id FROM folders WHERE user_id = ? AND path = ?", (uid, folder_path)
    ).fetchone()
    folder_id = row["id"] if row else None
    conn.close()

    for root, _, filenames in os.walk(folder_path):
        for fname in filenames:
            ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
            if ext not in _EXT_ALL:
                continue

            fpath = os.path.join(root, fname)

            conn = get_db()
            existing = conn.execute(
                "SELECT processado FROM files WHERE user_id = ? AND caminho = ?",
                (uid, fpath),
            ).fetchone()

            if existing and existing["processado"]:
                conn.close()
                continue

            if not existing:
                try:
                    conn.execute(
                        """INSERT INTO files
                           (folder_id, user_id, nome, caminho, tipo,
                            data_adicionado, favorito, processado)
                           VALUES (?, ?, ?, ?, ?, ?, 0, 0)""",
                        (folder_id, uid, fname, fpath, ext, datetime.now().isoformat()),
                    )
                    conn.commit()
                except sqlite3.IntegrityError:
                    pass
            conn.close()

            _queue.put({"path": fpath, "nome": fname, "ext": ext, "uid": uid})

    with _lock:
        if _queue.empty():
            _status = "Ocioso"


def _process_worker() -> None:
    global _processed, _status

    while True:
        try:
            item = _queue.get(timeout=5)
        except queue.Empty:
            with _lock:
                _status = "Ocioso"
            continue

        fpath = item["path"]
        fname = item["nome"]
        ext   = item["ext"]
        uid   = item["uid"]

        with _lock:
            _status = f"Analisando ({_queue.qsize()} na fila): {fname}"

        try:
            desc = _analyze_file(fpath, ext)
        except Exception as exc:
            print(f"[ERRO] {fpath}: {exc}")
            desc = f"{ext.upper()}: {fname}"

        emb_json = None
        if SBERT_OK and desc:
            # Texto expandido com sinônimos → embedding casa com variações do termo
            texto_emb = _texto_para_embedding(desc)
            emb = _gerar_embedding(texto_emb)
            if emb:
                emb_json = json.dumps(emb)

        # CLIP visual — apenas para imagens, lê o próprio arquivo
        emb_clip_json = None
        if CLIP_OK and ext in _EXT_IMG:
            emb_clip = _gerar_embedding_clip_imagem(fpath)
            if emb_clip:
                emb_clip_json = json.dumps(emb_clip)

        # Se caiu no fallback conhecido (LLaVA/extrator falhou), deixa processado=0
        # para que uma próxima varredura tente de novo. Não depende de emb_json
        # porque o SBERT gera embedding até de texto curto ("imagem a.jpg").
        caiu_no_fallback = any(desc.startswith(prefix) for prefix in _DESCRICOES_RUINS)
        processado_flag = 0 if caiu_no_fallback else 1

        conn = get_db()
        conn.execute(
            "UPDATE files SET descricao_ia = ?, embedding = ?, embedding_clip = ?, processado = ? "
            "WHERE user_id = ? AND caminho = ?",
            (desc, emb_json, emb_clip_json, processado_flag, uid, fpath),
        )
        conn.commit()
        conn.close()

        with _lock:
            _processed += 1

        _queue.task_done()


# ──────────────────────────────────────────────────────────────────────────────
# Análise de arquivos
# ──────────────────────────────────────────────────────────────────────────────

def _analyze_file(filepath: str, ext: str) -> str:
    if ext in _EXT_IMG:
        return _analyze_image(filepath)
    if ext == "pdf":
        return _extract_pdf(filepath)
    if ext in ("docx", "doc"):
        return _extract_docx(filepath)
    if ext in ("txt", "csv"):
        return _extract_txt(filepath)
    return f"{ext.upper()}: {os.path.basename(filepath)}"


def _analyze_image(filepath: str) -> str:
    llava_desc = None

    # ── Etapa 1: LLaVA via Ollama ──────────────────────────────────────────
    if OLLAMA_OK:
        try:
            resp = _ollama.chat(
                model="llava:13b",
                options={"temperature": 0.0, "top_p": 0.5},
                messages=[{
                    "role": "user",
                    "content": (
                        "Analise esta imagem e descreva APENAS o que VOCÊ VÊ. "
                        "NÃO INVENTE pessoas, animais ou objetos que não estão visíveis. "
                        "Se não tem pessoa, escreva 'nenhuma'. Se não tem animal, escreva 'nenhum'.\n\n"
                        "REGRAS DE VOCABULÁRIO (obrigatório):\n"
                        "• 'cachorro' (NUNCA 'cão' ou 'cãe')\n"
                        "• 'gato' (NUNCA 'felino' ou 'bichano')\n"
                        "• 'mulher' / 'menina' (NUNCA 'senhora', 'moça', 'dama')\n"
                        "• 'homem' / 'menino' (NUNCA 'senhor', 'rapaz', 'cavalheiro')\n\n"
                        "FORMATO (máx. 6 linhas, sempre em português):\n"
                        "- O que é: cena principal em uma frase curta\n"
                        "- Pessoas: liste somente as REALMENTE visíveis com gênero + idade + ação; "
                        "ou 'nenhuma' se não há pessoa\n"
                        "- Animais: liste somente os REALMENTE visíveis com espécie + ação; "
                        "ou 'nenhum' se não há animal\n"
                        "- Objetos: itens visíveis (vírgula-separado)\n"
                        "- Ambiente: local + cores dominantes\n"
                        "- Tags: 6 a 10 palavras-chave usando o vocabulário acima"
                    ),
                    "images": [filepath],
                }],
            )
            llava_desc = resp["message"]["content"]
            print(f"[LLaVA] OK: {os.path.basename(filepath)}")
        except Exception as exc:
            print(f"[LLaVA] Indisponível: {exc}")

    # ── Fallback: usa nome do arquivo se LLaVA falhou ─────────────────────
    # Sinaliza com prefixo "Imagem:" para que o worker não marque como processado
    # e uma próxima varredura tente novamente (evita travar em fallback permanente).
    return llava_desc or f"Imagem: {os.path.basename(filepath)}"


def _extract_pdf(filepath: str) -> str:
    if PYMUPDF_OK:
        try:
            doc  = fitz.open(filepath)
            text = "\n".join(page.get_text() for page in doc).strip()
            doc.close()
            return text[:6000] if text else f"PDF: {os.path.basename(filepath)}"
        except Exception as exc:
            print(f"[PDF] {exc}")
    return f"PDF: {os.path.basename(filepath)}"


def _extract_docx(filepath: str) -> str:
    if DOCX_OK:
        try:
            doc  = DocxDoc(filepath)
            text = "\n".join(p.text for p in doc.paragraphs).strip()
            return text[:6000] if text else f"Documento: {os.path.basename(filepath)}"
        except Exception as exc:
            print(f"[DOCX] {exc}")
    return f"Documento: {os.path.basename(filepath)}"


def _extract_txt(filepath: str) -> str:
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(6000)
    except Exception:
        return f"Texto: {os.path.basename(filepath)}"


# ──────────────────────────────────────────────────────────────────────────────
# Ponto de entrada
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()

    # Worker de processamento em background (daemon = mata junto com o processo)
    threading.Thread(target=_process_worker, daemon=True).start()

    print("=" * 60)
    print("  Search+ Backend iniciado!")
    print("  Acesse: http://127.0.0.1:5000")
    print("=" * 60)
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
