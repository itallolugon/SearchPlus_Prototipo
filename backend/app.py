"""
Search+ Backend — Flask API
Serve o frontend em http://127.0.0.1:5000 e expõe todos os endpoints da API.
"""

import os
import json
import hashlib
import mimetypes
import queue
import subprocess
import threading
import time
import unicodedata
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

import psycopg2
import psycopg2.errors
from psycopg2 import pool as pg_pool
from psycopg2.extras import RealDictCursor
from pgvector.psycopg2 import register_vector
from dotenv import load_dotenv

from flask import Flask, jsonify, request, send_file, send_from_directory, session
from flask_cors import CORS

# ──────────────────────────────────────────────────────────────────────────────
# Configuração de caminhos e ambiente
# ──────────────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent          # .../backend/
FRONTEND_DIR = BASE_DIR.parent            # .../

# Carrega .env do diretório do backend
load_dotenv(BASE_DIR / ".env")

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL não definida. Crie backend/.env baseado em .env.example."
    )

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
    Inclui 'O que é', 'Pessoas', 'Animais', 'Objetos', 'Ações' e 'Tags'.
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
    if palavra.endswith("m"):
        out.add(palavra[:-1] + "ns")
    elif palavra.endswith("ns"):
        out.add(palavra[:-2] + "m")
    elif palavra.endswith("s"):
        out.add(palavra[:-1])
    else:
        out.add(palavra + "s")
    return out


def _texto_para_embedding(desc: str) -> str:
    """
    Prepara texto da descrição LLaVA para virar embedding de alto recall.
    Expande sinônimos no próprio texto do documento (não só na query), então
    uma imagem com 'cão' também casa com buscas por 'cachorro', 'caozinho' etc.
    """
    campos = _extrair_campos_llava(desc)
    tokens = _tokenizar(campos)
    expandido = _expandir_sinonimos(tokens)
    return expandido or _normalizar(campos)


def _rerank_com_llm(query: str, candidatos: list[dict], topk: int = 20) -> list[dict]:
    """
    Reordena os top-K candidatos usando llama3.2 como juiz de relevância.
    Blend 50/50 entre score base (SBERT+BM25+CLIP) e nota do LLM.
    Salvaguardas: hit forte (base ≥ 0.60) + LLM rejeita (≤ 0.20) → ignora LLM.
    Palavra da query literalmente na descrição → piso 0.5 no score do LLM.
    Se Ollama falhar, devolve os candidatos inalterados (degrada gracioso).
    """
    if not OLLAMA_OK or not candidatos:
        return candidatos

    topo = candidatos[:topk]
    resto = candidatos[topk:]

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

        if base >= 0.60 and llm_score <= 0.20:
            print(f"[Rerank] LLM rejeitou '{c['nome']}' (base={base:.2f}) — ignorando nota LLM")
            continue

        desc_norm = _normalizar(c.get("descricao_ia") or "")
        if any(w in desc_norm for w in q_palavras_literais):
            llm_score = max(llm_score, 0.5)

        c["score_original"] = base
        c["score_llm"]      = round(llm_score, 3)
        c["score"]          = round(0.5 * base + 0.5 * llm_score, 4)

    topo.sort(key=lambda x: x["score"], reverse=True)
    return topo + resto


# ──────────────────────────────────────────────────────────────────────────────
# Banco de dados Postgres (Supabase) — pool de conexões
# ──────────────────────────────────────────────────────────────────────────────

# Pool com 1-10 conexões. Cada request pega uma do pool; devolve no close.
_pg_pool = pg_pool.ThreadedConnectionPool(1, 10, dsn=DATABASE_URL)
print(f"[DB] Pool Postgres pronto ({DATABASE_URL.split('@')[-1]})")


class _PooledConnection:
    """
    Wrapper de conexão Postgres que devolve ao pool no .close() em vez de fechar.
    Mantém a mesma interface do sqlite3.Connection (conn.execute, conn.commit, conn.close)
    pra minimizar refactor das chamadas existentes.
    """
    def __init__(self, raw):
        self._raw = raw
        # Registra o adapter pgvector pra aceitar/devolver listas como vector(N)
        try:
            register_vector(raw)
        except Exception as e:
            # Se a extensão vector não está habilitada ainda, ignora silencioso
            print(f"[DB] pgvector adapter nao registrado: {e}")
        self._cursor = raw.cursor(cursor_factory=RealDictCursor)

    def execute(self, sql, params=None):
        self._cursor.execute(sql, params or ())
        return self._cursor

    def executescript(self, sql):
        # No Postgres rodamos como um único bloco
        self._cursor.execute(sql)

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        try:
            self._cursor.close()
        except Exception:
            pass
        # Garante que a conexão volta limpa ao pool — se ficou em transaction
        # com erro, a próxima query daria InFailedSqlTransaction.
        try:
            self._raw.rollback()
        except Exception:
            pass
        try:
            _pg_pool.putconn(self._raw)
        except Exception:
            pass


def get_db():
    """Pega uma conexão do pool. Sempre chame .close() no final pra devolver."""
    raw = _pg_pool.getconn()
    return _PooledConnection(raw)


def _safe_json_loads(raw, default=None):
    """
    Wrapper tolerante de json.loads. No Postgres com JSONB, vem como dict
    direto — só usamos esta função quando o campo é TEXT ou pode ser str.
    """
    if raw is None:
        return default
    # JSONB do Postgres já vem como dict/list direto
    if isinstance(raw, (dict, list)):
        return raw
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return default


def init_db() -> None:
    """Roda schema.sql — idempotente (todas as DDL têm IF NOT EXISTS)."""
    schema_path = BASE_DIR / "schema.sql"
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()
    conn = get_db()
    try:
        conn._cursor.execute(schema_sql)
        conn.commit()
    finally:
        conn.close()


# Garante que as tabelas existam ao carregar o módulo (idempotente)
try:
    init_db()
    print("[DB] Schema verificado.")
except Exception as _db_exc:
    print(f"[DB] ERRO na inicialização: {_db_exc}")


@app.errorhandler(psycopg2.errors.UndefinedTable)
@app.errorhandler(psycopg2.errors.UndefinedColumn)
def _handle_missing_schema(exc):
    """Se as tabelas sumirem em runtime, recria o schema e pede retry."""
    print(f"[DB] Schema ausente/incompleto detectado: {exc}. Recriando...")
    try:
        init_db()
    except Exception as init_exc:
        print(f"[DB] Falha ao recriar schema: {init_exc}")
        return jsonify({"error": "Falha ao restaurar banco de dados."}), 500
    return jsonify({
        "error": "Banco de dados foi restaurado. Tente a operação novamente.",
        "retry": True,
    }), 503


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
    "notificacoes": True,
    "atalho_busca": "Ctrl+Shift+F",
    "iniciar_sistema": False,
    "modo_privado": False,
    "pastas_ignoradas": "",
    "modo_desempenho": "economico",
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
        "SELECT id, password_hash FROM users WHERE username = %s", (username,)
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
    handle   = (data.get("handle") or "").strip()
    password = (data.get("password") or "").strip()

    if not username or not password:
        return jsonify({"mensagem": "Preencha todos os campos."}), 400

    cfg = {
        **_DEFAULT_CFG, 
        "perfil_nome": username, 
        "perfil_handle": handle if handle else username.lower()
    }

    try:
        conn = get_db()
    except Exception as exc:
        print(f"[DB] Falha ao conectar: {exc}")
        return jsonify({"mensagem": f"Erro ao conectar ao banco: {exc}"}), 500

    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, config_json) VALUES (%s, %s, %s)",
            (username, _hash(password), json.dumps(cfg)),
        )
        conn.commit()
        return jsonify({"status": "ok"})
    except psycopg2.errors.UniqueViolation:
        return jsonify({"mensagem": "Este usuário já existe."}), 409
    except psycopg2.errors.UndefinedTable as exc:
        # Banco existe mas sem schema (ex: arquivo zerado durante uso) — recria e tenta de novo
        if "no such table" in str(exc).lower():
            print(f"[DB] Schema ausente, recriando: {exc}")
            conn.close()
            init_db()
            conn = get_db()
            try:
                conn.execute(
                    "INSERT INTO users (username, password_hash, config_json) VALUES (%s, %s, %s)",
                    (username, _hash(password), json.dumps(cfg)),
                )
                conn.commit()
                return jsonify({"status": "ok"})
            except Exception as exc2:
                print(f"[DB] Falha após recriar schema: {exc2}")
                return jsonify({"mensagem": f"Erro interno: {exc2}"}), 500
        print(f"[DB] Erro no registro: {exc}")
        return jsonify({"mensagem": f"Erro interno: {exc}"}), 500
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
    user = conn.execute("SELECT username FROM users WHERE id = %s", (uid,)).fetchone()
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
        row = conn.execute("SELECT config_json FROM users WHERE id = %s", (uid,)).fetchone()
        folders = conn.execute(
            "SELECT path FROM folders WHERE user_id = %s ORDER BY added_at", (uid,)
        ).fetchall()
        conn.close()

        cfg = {**_DEFAULT_CFG, **_safe_json_loads(row["config_json"], {})} if row else dict(_DEFAULT_CFG)
        rows = _list_folders(uid)
        cfg["pastas"] = _folders_to_json(rows)
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
    conn.execute("UPDATE users SET config_json = %s WHERE id = %s", (json.dumps(data), uid))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


# ──────────────────────────────────────────────────────────────────────────────
# Pastas monitoradas
# ──────────────────────────────────────────────────────────────────────────────

def _list_folders(uid: int):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, path, prioridades, perfil_analise, janela_processamento "
        "FROM folders WHERE user_id = %s ORDER BY added_at", (uid,)
    ).fetchall()
    conn.close()
    return rows


def _folders_to_json(rows):
    """Converte rows do banco em lista de dicts para o frontend."""
    result = []
    for r in rows:
        prio = _safe_json_loads(r["prioridades"], ["tudo"])
        result.append({
            "id": r["id"],
            "path": r["path"],
            "prioridades": prio,
            "perfil_analise": r["perfil_analise"] or "fast",
            "janela_processamento": r["janela_processamento"] or "always",
        })
    return result


@app.route("/api/folders", methods=["GET", "POST", "DELETE"])
def api_folders():
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    if request.method == "GET":
        rows = _list_folders(uid)
        return jsonify({"pastas": _folders_to_json(rows)})

    if request.method == "POST":
        data = request.get_json(force=True) or {}
        pasta = (data.get("pasta") or "").strip()

        if not pasta or not os.path.isdir(pasta):
            return jsonify({"error": "Caminho inválido ou inexistente."}), 400

        # Novos campos de Indexação Inteligente
        prioridades = data.get("prioridades", ["tudo"])
        perfil      = data.get("perfil_analise", "fast")
        janela      = data.get("janela_processamento", "always")

        name = os.path.basename(pasta) or pasta
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO folders (user_id, path, name, added_at, prioridades, perfil_analise, janela_processamento) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (uid, pasta, name, datetime.now().isoformat(),
                 json.dumps(prioridades), perfil, janela),
            )
            conn.commit()
        except psycopg2.errors.UniqueViolation:
            # Pasta já existe — atualiza config
            conn.execute(
                "UPDATE folders SET prioridades=%s, perfil_analise=%s, janela_processamento=%s "
                "WHERE user_id=%s AND path=%s",
                (json.dumps(prioridades), perfil, janela, uid, pasta),
            )
            conn.commit()
        finally:
            conn.close()

        # Análise em background
        threading.Thread(target=_scan_folder, args=(pasta, uid), daemon=True).start()

        rows = _list_folders(uid)
        return jsonify({"status": "ok", "pastas": _folders_to_json(rows)})

    # DELETE
    data = request.get_json(force=True) or {}
    pasta = (data.get("pasta") or "").strip()

    conn = get_db()
    conn.execute("DELETE FROM files WHERE user_id = %s AND caminho LIKE %s", (uid, pasta + "%"))
    conn.execute("DELETE FROM folders WHERE user_id = %s AND path = %s", (uid, pasta))
    conn.commit()
    conn.close()

    rows = _list_folders(uid)
    return jsonify({"status": "ok", "pastas": _folders_to_json(rows)})


@app.route("/api/folders/<int:folder_id>", methods=["DELETE"])
def api_delete_folder_by_id(folder_id):
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    conn = get_db()
    
    # Pegar o path da pasta para deletar os arquivos
    row = conn.execute("SELECT path FROM folders WHERE id = %s AND user_id = %s", (folder_id, uid)).fetchone()
    if row:
        pasta = row["path"]
        conn.execute("DELETE FROM files WHERE user_id = %s AND caminho LIKE %s", (uid, pasta + "%"))

    conn.execute("DELETE FROM folders WHERE id = %s AND user_id = %s", (folder_id, uid))
    conn.commit()
    conn.close()

    rows = _list_folders(uid)
    return jsonify({"status": "ok", "pastas": _folders_to_json(rows)})


@app.route("/api/folders/update_config", methods=["GET", "POST"])
def api_update_folder_config():
    """Atualiza config de indexação (por ID ou Path)."""
    print(f"[DEBUG] Recebido {request.method} em /api/folders/update_config")
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    if request.method == "GET":
        return jsonify({"status": "error", "message": "Use POST"}), 400
        
    data = request.get_json(force=True) or {}
    print(f"[DEBUG] Payload: {data}")
    folder_id = data.get("id")
    folder_path = data.get("path")
    
    sets, vals = [], []
    if "prioridades" in data:
        sets.append("prioridades = %s")
        vals.append(json.dumps(data["prioridades"]))
    if "perfil_analise" in data:
        sets.append("perfil_analise = %s")
        vals.append(data["perfil_analise"])
    if "janela_processamento" in data:
        sets.append("janela_processamento = %s")
        vals.append(data["janela_processamento"])

    if not sets:
        return jsonify({"error": "Nenhum campo enviado."}), 400

    conn = get_db()
    if folder_id is not None:
        vals.extend([folder_id, uid])
        conn.execute(f"UPDATE folders SET {', '.join(sets)} WHERE id = %s AND user_id = %s", vals)
    elif folder_path:
        vals.extend([folder_path, uid])
        conn.execute(f"UPDATE folders SET {', '.join(sets)} WHERE path = %s AND user_id = %s", vals)
    else:
        conn.close()
        return jsonify({"error": "ID ou Path não fornecido."}), 400
        
    conn.commit()
    conn.close()

    rows = _list_folders(uid)
    return jsonify({"status": "ok", "pastas": _folders_to_json(rows)})


@app.route("/api/estimate_time")
def api_estimate_time():
    """Estima tempo de processamento baseado em nº de imagens e perfil."""
    uid = _uid()
    if not uid:
        return jsonify({"estimativa_minutos": 0, "total_imagens": 0})

    pasta  = request.args.get("pasta", "").strip()
    perfil = request.args.get("perfil", "fast")
    foco   = request.args.get("foco", "tudo")

    if not pasta or not os.path.isdir(pasta):
        return jsonify({"estimativa_minutos": 0, "total_imagens": 0})

    # Limite de tempo + arquivos para não travar com pastas gigantes (ex: C:\)
    LIMITE_ARQUIVOS = 50_000
    LIMITE_TEMPO_S = 5
    t_inicio = time.time()
    count = 0
    truncado = False
    for root, _, filenames in os.walk(pasta):
        if (time.time() - t_inicio) > LIMITE_TEMPO_S or count >= LIMITE_ARQUIVOS:
            truncado = True
            break
        for fname in filenames:
            ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
            if ext in _EXT_ALL:
                count += 1
                if count >= LIMITE_ARQUIVOS:
                    truncado = True
                    break

    rate = 2 if perfil == "fast" else 10  # segundos por arquivo
    
    # Se o foco for específico, a grande maioria dos arquivos será pulada rapidamente pelo CLIP (~0.1s).
    # Assumimos conservadoramente que 10% vão para a IA densa, e 90% são pulados.
    if foco != "tudo" and foco != "":
        rate = (rate * 0.1) + (0.1 * 0.9)

    est_min = round((count * rate) / 60, 1)
    # Se o tempo for menor que 0.1 mas maior que 0, mostre 0.1 min
    if est_min == 0 and count > 0:
        est_min = 0.1

    return jsonify({
        "estimativa_minutos": est_min,
        "total_imagens": count,
        "truncado": truncado,
    })


@app.route("/api/ollama_models")
def api_ollama_models():
    """Retorna lista de modelos Ollama disponíveis."""
    if not OLLAMA_OK:
        return jsonify({"disponivel": False, "modelos": []})
    try:
        models = _ollama.list()
        nomes = [m.get("name", m.get("model", "")) for m in models.get("models", [])]
        return jsonify({"disponivel": True, "modelos": nomes})
    except Exception as exc:
        return jsonify({"disponivel": False, "erro": str(exc), "modelos": []})


# ──────────────────────────────────────────────────────────────────────────────
# Servir arquivos locais pelo caminho absoluto
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/file/<path:filepath>")
def api_serve_file(filepath):
    # Auth: precisa estar logado
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    # Flask decodifica %XX automaticamente; backslash (%5C) também
    filepath = unquote(filepath)
    filepath = os.path.normpath(filepath)

    if not os.path.isfile(filepath):
        return jsonify({"error": "Arquivo não encontrado."}), 404

    # Anti-path-traversal: o arquivo precisa estar dentro de UMA das pastas
    # monitoradas do usuário. Sem isso, qualquer caminho do disco poderia
    # ser servido (ex: C:\Users\X\.ssh\id_rsa).
    abs_path = os.path.abspath(filepath)
    conn = get_db()
    pastas = conn.execute(
        "SELECT path FROM folders WHERE user_id = %s", (uid,)
    ).fetchall()
    conn.close()

    autorizado = False
    for p in pastas:
        pasta_abs = os.path.abspath(p["path"])
        # Garante separador no fim para 'C:\foo' não casar com 'C:\foobar'
        if abs_path.lower().startswith(pasta_abs.lower() + os.sep) or abs_path.lower() == pasta_abs.lower():
            autorizado = True
            break

    if not autorizado:
        return jsonify({"error": "Arquivo fora das pastas monitoradas."}), 403

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
    if not _uid():
        return jsonify({"status": "erro", "mensagem": "Não autenticado."}), 401
    try:
        path = _tk_pick("image")
        if path:
            return jsonify({"status": "sucesso", "caminho": path})
        return jsonify({"status": "cancelado"})
    except Exception as exc:
        return jsonify({"status": "erro", "mensagem": str(exc)})


@app.route("/api/choose_folder")
def api_choose_folder():
    if not _uid():
        return jsonify({"status": "erro", "mensagem": "Não autenticado."}), 401
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
    "cachorro":    ["cao", "caozinho", "cachorrinho", "cachorra", "filhote", "pet", "dog"],
    "caozinho":    ["cachorro", "cao", "cachorrinho", "filhote"],
    "cachorrinho": ["cachorro", "caozinho", "cao", "filhote"],
    "cachorra":    ["cachorro", "cao", "cadela"],
    "dog":         ["cachorro", "cao"],
    "vira-lata":   ["cachorro", "cao"],
    "viralata":    ["cachorro", "cao"],

    "gato":      ["gatinho", "gata", "felino", "bichano", "cat"],
    "gatinha":   ["gata", "gato", "gatinho", "felina"],
    "gatinho":   ["gato", "gata", "felino", "filhote"],
    "gata":      ["gato", "gatinha", "felina"],
    "felino":    ["gato", "gatinho"],
    "bichano":   ["gato", "gatinho"],

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
    """
    Busca híbrida com pgvector:
    1. SBERT (no banco): top 100 candidatos por cosine distance (HNSW index)
    2. BM25 (em Python): re-pontuação por palavra-chave nos 100 candidatos
    3. CLIP (em Python, opcional): similaridade visual quando disponível
    4. Match literal + ajustes de score + re-rank com LLM-juiz
    """
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

    t0 = time.time()

    if not SBERT_OK:
        return jsonify({"resultados": [], "tempo": 0,
                        "erro": "SBERT indisponível — busca semântica desligada."})

    q = _analisar_query(query)
    query_emb = _SBERT.encode(q["expandida"], convert_to_numpy=True).tolist()

    # Filtro por tipo no SQL (mais rápido que filtrar em Python depois)
    sql_filtro_tipo = ""
    params_filtro = ()
    if filtro == "imagem":
        sql_filtro_tipo = " AND tipo = ANY(%s)"
        params_filtro = (list(_EXT_IMG),)
    elif filtro == "midia":
        sql_filtro_tipo = " AND tipo = ANY(%s)"
        params_filtro = (list(_EXT_VID | _EXT_AUD),)
    elif filtro == "documento":
        sql_filtro_tipo = " AND tipo != ALL(%s)"
        params_filtro = (list(_EXT_IMG | _EXT_VID | _EXT_AUD),)

    # Top 100 por SBERT via pgvector (HNSW index — O(log n))
    conn = get_db()
    rows = conn.execute(
        f"""
        SELECT id, folder_id, nome, caminho, tipo, descricao_ia,
               embedding_clip, data_adicionado, favorito,
               1 - (embedding <=> %s::vector) AS sbert_score
        FROM files
        WHERE user_id = %s AND processado = 1 AND embedding IS NOT NULL
        {sql_filtro_tipo}
        ORDER BY embedding <=> %s::vector
        LIMIT 100
        """,
        (query_emb, uid, *params_filtro, query_emb)
    ).fetchall()
    conn.close()

    if not rows:
        return jsonify({"resultados": [], "tempo": round(time.time() - t0, 3)})

    sbert_sims = [max(0.0, float(r["sbert_score"])) for r in rows]

    # BM25 (palavra-chave) sobre os candidatos
    corpus_tokens = [
        _tokenizar((f["descricao_ia"] or "") + " " + (f["nome"] or ""))
        for f in rows
    ]
    bm25_sims = _bm25_scores(corpus_tokens, q["palavras"])

    # CLIP (visual): só pra imagens com embedding_clip
    clip_sims = [0.0] * len(rows)
    if CLIP_OK:
        clip_query_vec = _gerar_embedding_clip_texto(q["original"])
        if clip_query_vec is not None:
            import numpy as np
            clip_q_np = np.array([clip_query_vec])
            for i, f in enumerate(rows):
                if f["tipo"] in _EXT_IMG and f["embedding_clip"] is not None:
                    try:
                        img_vec = np.array([f["embedding_clip"]])
                        clip_sims[i] = float(cosine_similarity(clip_q_np, img_vec)[0][0])
                    except Exception:
                        pass

    # Pesos do blend
    W_SBERT_IMG, W_BM25_IMG, W_CLIP_IMG = 0.45, 0.25, 0.30
    W_SBERT_DOC, W_BM25_DOC             = 0.65, 0.35

    # Match literal (cobre plural nasal pt-BR: homem ↔ homens)
    palavras_literais = set()
    for w in q["palavras"]:
        if len(w) >= 3:
            palavras_literais.update(_variantes_morfologicas(w))

    def _filtrar_e_pontuar(threshold_sbert: float) -> list:
        out = []
        for f, s_sbert, s_bm25, s_clip in zip(rows, sbert_sims, bm25_sims, clip_sims):
            desc_norm_local = _normalizar(f["descricao_ia"] or "")
            tem_texto     = s_sbert >= threshold_sbert
            tem_visual    = (f["tipo"] in _EXT_IMG and CLIP_OK and s_clip >= 0.25)
            tem_keyword   = s_bm25 >= 0.5 and bool(q["palavras_set"])
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

    candidatos = _filtrar_e_pontuar(0.35)
    if not candidatos:
        candidatos = _filtrar_e_pontuar(0.30)

    results = []
    for f, desc, score in candidatos:
        results.append({
            "id": f["id"], "nome": f["nome"], "caminho": f["caminho"],
            "tipo": f["tipo"], "descricao_ia": desc, "conteudo": desc,
            "trecho": _trecho(desc, query),
            "data": f["data_adicionado"].isoformat() if f["data_adicionado"] else "",
            "favorito": bool(f["favorito"]),
            "score": round(score, 4),
        })

    results.sort(key=lambda x: x["score"], reverse=True)

    if results:
        results = _rerank_com_llm(query, results, topk=20)
        results = [r for r in results if r["score"] >= 0.20]

    tempo = round(time.time() - t0, 3)
    return jsonify({"resultados": results[:60], "tempo": tempo})


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
        "SELECT * FROM files WHERE user_id = %s AND favorito = 1 ORDER BY data_adicionado DESC",
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
            "data":        r["data_adicionado"].isoformat() if r["data_adicionado"] else "",
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
        "SELECT favorito FROM files WHERE id = %s AND user_id = %s", (file_id, uid)
    ).fetchone()

    if not row:
        conn.close()
        return jsonify({"error": "Arquivo não encontrado."}), 404

    new_fav = 1 - int(row["favorito"])
    conn.execute(
        "UPDATE files SET favorito = %s WHERE id = %s AND user_id = %s", (new_fav, file_id, uid)
    )
    conn.commit()
    conn.close()

    return jsonify({"status": "sucesso", "favorito": bool(new_fav)})


# ──────────────────────────────────────────────────────────────────────────────
# Status do motor
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    uid = _uid()
    if not uid:
        return jsonify({
            "status": "Ocioso",
            "arquivos_pendentes": 0,
            "arquivos_processados_sessao": 0,
        })
    
    try:
        conn = get_db()
        count = conn.execute("SELECT COUNT(*) FROM files WHERE user_id = %s", (uid,)).fetchone()[0]
    except Exception:
        count = 0
    finally:
        if 'conn' in locals():
            conn.close()

    with _lock:
        return jsonify({
            "status":                    _status,
            "arquivos_pendentes":        _queue.qsize(),
            "arquivos_processados_sessao": count,
        })


@app.route("/api/cancel_analysis", methods=["POST"])
def api_cancel_analysis():
    """Esvazia a fila de análise — interrompe a indexação em andamento."""
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    global _status
    descartados = 0
    # Esvazia a fila. O item que já está sendo processado no worker
    # termina normalmente (não dá pra abortar uma chamada LLaVA em curso).
    while True:
        try:
            _queue.get_nowait()
            _queue.task_done()
            descartados += 1
        except queue.Empty:
            break

    with _lock:
        _status = "Ocioso"

    return jsonify({"status": "ok", "descartados": descartados})


@app.route("/api/debug/files")
def api_debug_files():
    """Mostra todos os arquivos indexados com preview da descrição."""
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401
    conn = get_db()
    rows = conn.execute(
        "SELECT id, nome, tipo, processado, embedding IS NOT NULL as tem_embedding, "
        "substr(descricao_ia,1,120) as desc_preview FROM files WHERE user_id = %s",
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
        q = _analisar_query(query)
        query_emb = _SBERT.encode(q["expandida"], convert_to_numpy=True).tolist()

        conn = get_db()
        todos = conn.execute(
            "SELECT COUNT(*) as n FROM files WHERE user_id = %s", (uid,)
        ).fetchone()["n"]
        # Busca scores SBERT via pgvector (no banco)
        rows = conn.execute(
            """
            SELECT nome, tipo, substr(descricao_ia, 1, 200) AS desc_preview,
                   1 - (embedding <=> %s::vector) AS score
            FROM files
            WHERE user_id = %s AND embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT 200
            """,
            (query_emb, uid, query_emb)
        ).fetchall()
        conn.close()

        if not rows:
            return jsonify({
                "query": query,
                "erro": "Nenhum arquivo tem embedding ainda.",
                "total_arquivos": todos,
                "dica": "Clique em 'Analisar Pastas' para gerar os embeddings.",
            })

        resultados = [
            {"nome": r["nome"], "tipo": r["tipo"],
             "score": round(float(r["score"]), 4),
             "passa_threshold": float(r["score"]) >= 0.35,
             "desc_preview": r["desc_preview"]}
            for r in rows
        ]

        return jsonify({
            "query": query,
            "query_expandida": q["expandida"],
            "threshold_atual": 0.35,
            "total_arquivos": todos,
            "com_embedding": len(rows),
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
        "SELECT path FROM folders WHERE user_id = %s", (uid,)
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
        "descricao_ia LIKE %s" for _ in _DESCRICOES_RUINS
    )
    rows = conn.execute(
        f"SELECT id, caminho, nome, tipo FROM files WHERE user_id = %s AND (processado = 0 OR embedding IS NULL OR {conditions})",
        (uid, *[f"{p}%" for p in _DESCRICOES_RUINS])
    ).fetchall()

    ids = [r["id"] for r in rows]
    if ids:
        placeholders = ','.join(['%s'] * len(ids))
        conn.execute(
            f"UPDATE files SET processado = 0, descricao_ia = '', embedding = NULL WHERE id IN ({placeholders})",
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
        "WHERE user_id = %s AND processado = 1 AND descricao_ia != ''",
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
                    sets.append("embedding = %s")
                    vals.append(emb)  # pgvector adapter converte lista → vector
                    ok_sbert += 1

            if CLIP_OK and r["tipo"] in _EXT_IMG and os.path.isfile(r["caminho"]):
                emb_clip = _gerar_embedding_clip_imagem(r["caminho"])
                if emb_clip:
                    sets.append("embedding_clip = %s")
                    vals.append(emb_clip)
                    ok_clip += 1

            if sets:
                vals.append(r["id"])
                c = get_db()
                c.execute(f"UPDATE files SET {', '.join(sets)} WHERE id = %s", vals)
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
    row  = conn.execute("SELECT config_json FROM users WHERE id = %s", (uid,)).fetchone()
    conn.close()
    cfg  = _safe_json_loads(row["config_json"] if row else None, {}) or {}
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
    row  = conn.execute("SELECT config_json FROM users WHERE id = %s", (uid,)).fetchone()
    cfg  = _safe_json_loads(row["config_json"] if row else None, {}) or {}

    historico = cfg.get("search_history", [])
    if query in historico:
        historico.remove(query)
    historico.insert(0, query)
    cfg["search_history"] = historico[:10]  # Mantém só as 10 últimas

    conn.execute("UPDATE users SET config_json = %s WHERE id = %s", (json.dumps(cfg), uid))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "historico": cfg["search_history"]})


@app.route("/api/search_history/<int:index>", methods=["DELETE"])
def api_delete_search_history(index):
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401
    conn = get_db()
    row  = conn.execute("SELECT config_json FROM users WHERE id = %s", (uid,)).fetchone()
    cfg  = _safe_json_loads(row["config_json"] if row else None, {}) or {}
    historico = cfg.get("search_history", [])
    if 0 <= index < len(historico):
        historico.pop(index)
    cfg["search_history"] = historico
    conn.execute("UPDATE users SET config_json = %s WHERE id = %s", (json.dumps(cfg), uid))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "historico": historico})


@app.route("/api/clear_history", methods=["POST"])
def api_clear_history():
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401
    conn = get_db()
    row  = conn.execute("SELECT config_json FROM users WHERE id = %s", (uid,)).fetchone()
    cfg  = _safe_json_loads(row["config_json"] if row else None, {}) or {}
    cfg["search_history"] = []
    conn.execute("UPDATE users SET config_json = %s WHERE id = %s", (json.dumps(cfg), uid))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "historico": []})


@app.route("/api/clear_cache", methods=["POST"])
def api_clear_cache():
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401
    conn = get_db()
    # Limpa apenas os arquivos do usuário, mantendo as pastas cadastradas
    conn.execute("DELETE FROM files WHERE user_id = %s", (uid,))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


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
        "SELECT id FROM folders WHERE user_id = %s AND path = %s", (uid, folder_path)
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
                "SELECT processado FROM files WHERE user_id = %s AND caminho = %s",
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
                           VALUES (%s, %s, %s, %s, %s, %s, 0, 0)""",
                        (folder_id, uid, fname, fpath, ext, datetime.now().isoformat()),
                    )
                    conn.commit()
                except psycopg2.errors.UniqueViolation:
                    conn.rollback()
            conn.close()

            _queue.put({"path": fpath, "nome": fname, "ext": ext, "uid": uid, "folder_id": folder_id})

    with _lock:
        if _queue.empty():
            _status = "Ocioso"


def _is_within_window(janela: str) -> bool:
    """Verifica se a hora atual está dentro da janela de processamento."""
    if not janela or janela == "always":
        return True
    try:
        parts = janela.split("-")
        if len(parts) != 2:
            return True
        h_start, h_end = int(parts[0].split(":")[0]), int(parts[1].split(":")[0])
        now_h = datetime.now().hour
        if h_start <= h_end:
            return h_start <= now_h < h_end
        else:  # ex: 22:00-06:00 (passa da meia-noite)
            return now_h >= h_start or now_h < h_end
    except (ValueError, IndexError):
        return True


def _get_folder_config(folder_id, uid):
    """Busca config de indexação da pasta no banco."""
    if not folder_id:
        return ["tudo"], "fast", "always"
    conn = get_db()
    row = conn.execute(
        "SELECT prioridades, perfil_analise, janela_processamento "
        "FROM folders WHERE id = %s AND user_id = %s", (folder_id, uid)
    ).fetchone()
    conn.close()
    if not row:
        return ["tudo"], "fast", "always"
    prio = _safe_json_loads(row["prioridades"], ["tudo"])
    return prio, row["perfil_analise"] or "fast", row["janela_processamento"] or "always"


# ── Caches de Vetores CLIP (Lazy Loading) ──
_CLIP_TERMS = {
    "pessoas": ["a photo of a person", "a photo of a human", "a face", "people"],
    "animais": ["a photo of an animal", "a dog", "a cat", "wildlife", "pet"],
    "paisagens": ["a landscape", "nature", "a photo of a city", "scenery", "outdoors"]
}
_CLIP_EMBS_CACHE = {}
_CLIP_THRESHOLDS = {
    "pessoas": 0.20,
    "animais": 0.21,
    "paisagens": 0.21
}

def _get_precomputed_clip_embs(category: str) -> list:
    """Retorna os vetores de texto pré-computados para uma categoria."""
    if category in _CLIP_EMBS_CACHE:
        return _CLIP_EMBS_CACHE[category]
    embs = []
    if CLIP_OK:
        for term in _CLIP_TERMS.get(category, []):
            emb = _gerar_embedding_clip_texto(term)
            if emb:
                embs.append(emb)
    _CLIP_EMBS_CACHE[category] = embs
    return embs


def _process_worker() -> None:
    global _processed, _status

    # Contador de itens consecutivos descartados por janela. Quando bate o
    # tamanho da fila, dormimos uma vez e zeramos — evita o ciclo
    # "pega → re-enfileira → sleep 30s → pega o próximo → ...".
    fora_da_janela_consecutivos = 0

    while True:
        try:
            item = _queue.get(timeout=5)
        except queue.Empty:
            with _lock:
                _status = "Ocioso"
            fora_da_janela_consecutivos = 0
            continue

        fpath     = item["path"]
        fname     = item["nome"]
        ext       = item["ext"]
        uid       = item["uid"]
        folder_id = item.get("folder_id")

        # ── Buscar config da pasta ──
        prioridades, perfil, janela = _get_folder_config(folder_id, uid)

        # ── Scheduling: verificar janela de processamento ──
        if not _is_within_window(janela):
            _queue.put(item)
            _queue.task_done()
            fora_da_janela_consecutivos += 1
            # Se já passamos por uma volta inteira da fila sem nada entrar,
            # dorme uma vez ao invés de 30s × N itens.
            if fora_da_janela_consecutivos >= max(_queue.qsize(), 1):
                with _lock:
                    _status = f"Aguardando janela de processamento ({janela})"
                import time as _t
                _t.sleep(60)  # 1 min antes de tentar de novo (granularidade da janela é hora)
                fora_da_janela_consecutivos = 0
            continue
        fora_da_janela_consecutivos = 0

        with _lock:
            _status = f"Analisando ({_queue.qsize()} na fila): {fname}"

        # ── CLIP pre-filter: Otimização Extrema ──
        # Tenta pular o LLaVA se a imagem não contiver o que o usuário quer.
        skip_llava = False
        if ext in _EXT_IMG and CLIP_OK and prioridades and "tudo" not in prioridades:
            clip_emb_img = _gerar_embedding_clip_imagem(fpath)
            if clip_emb_img:
                import numpy as np
                clip_q = np.array([clip_emb_img])
                
                # Para CADA categoria desejada, verificamos se a imagem atinge o threshold.
                # Se falhar em TODAS as categorias selecionadas, pulamos o LLaVA.
                passou_no_filtro = False
                
                for cat in prioridades:
                    if cat not in _CLIP_TERMS:
                        passou_no_filtro = True # Categoria desconhecida, melhor analisar
                        break
                        
                    cat_embs = _get_precomputed_clip_embs(cat)
                    if not cat_embs:
                        passou_no_filtro = True
                        break
                        
                    max_sim = 0.0
                    for t_emb in cat_embs:
                        sim = float(cosine_similarity(clip_q, np.array([t_emb]))[0][0])
                        max_sim = max(max_sim, sim)
                        
                    if max_sim >= _CLIP_THRESHOLDS.get(cat, 0.20):
                        passou_no_filtro = True
                        break
                
                if not passou_no_filtro:
                    skip_llava = True
                    print(f"[CLIP Pre-filter] Rejeitado visualmente pelas categorias {prioridades}: {fname}")

        try:
            if skip_llava:
                desc = f"Imagem: {fname}"
            else:
                desc = _analyze_file(fpath, ext, prioridades=prioridades, perfil=perfil)
        except Exception as exc:
            print(f"[ERRO] {fpath}: {exc}")
            desc = f"{ext.upper()}: {fname}"

        emb_vec = None  # pgvector adapter converte lista direto pra vector
        if SBERT_OK and desc:
            texto_emb = _texto_para_embedding(desc)
            emb = _gerar_embedding(texto_emb)
            if emb:
                emb_vec = emb

        emb_clip_vec = None
        if CLIP_OK and ext in _EXT_IMG:
            emb_clip = _gerar_embedding_clip_imagem(fpath)
            if emb_clip:
                emb_clip_vec = emb_clip

        # Se caiu no fallback conhecido (LLaVA/extrator falhou), deixa processado=0
        caiu_no_fallback = any(desc.startswith(prefix) for prefix in _DESCRICOES_RUINS)
        processado_flag = 0 if caiu_no_fallback else 1

        conn = get_db()
        conn.execute(
            "UPDATE files SET descricao_ia = %s, embedding = %s, embedding_clip = %s, processado = %s "
            "WHERE user_id = %s AND caminho = %s",
            (desc, emb_vec, emb_clip_vec, processado_flag, uid, fpath),
        )
        conn.commit()
        conn.close()

        with _lock:
            _processed += 1

        _queue.task_done()


# ──────────────────────────────────────────────────────────────────────────────
# Análise de arquivos
# ──────────────────────────────────────────────────────────────────────────────

def _analyze_file(filepath: str, ext: str, *, prioridades=None, perfil="fast") -> str:
    if ext in _EXT_IMG:
        return _analyze_image(filepath, prioridades=prioridades or ["tudo"], perfil=perfil)
    if ext == "pdf":
        return _extract_pdf(filepath)
    if ext in ("docx", "doc"):
        return _extract_docx(filepath)
    if ext in ("txt", "csv"):
        return _extract_txt(filepath)
    return f"{ext.upper()}: {os.path.basename(filepath)}"


def _build_llava_prompt(prioridades: list) -> str:
    """Constrói o prompt do LLaVA baseado nas prioridades do usuário."""
    base = (
        "Analise esta imagem e descreva APENAS o que VOCÊ VÊ. "
        "NÃO INVENTE pessoas, animais ou objetos que não estão visíveis. "
        "Se não tem pessoa, escreva 'nenhuma'. Se não tem animal, escreva 'nenhum'.\n\n"
        "REGRAS DE VOCABULÁRIO (obrigatório):\n"
        "• 'cachorro' (NUNCA 'cão' ou 'cãe')\n"
        "• 'gato' (NUNCA 'felino' ou 'bichano')\n"
        "• 'mulher' / 'menina' (NUNCA 'senhora', 'moça', 'dama')\n"
        "• 'homem' / 'menino' (NUNCA 'senhor', 'rapaz', 'cavalheiro')\n\n"
        "FORMATO (sempre em português):\n"
        "- O que é: cena principal em uma frase curta\n"
        "- Pessoas: liste somente as REALMENTE visíveis com gênero + idade + ação; "
        "ou 'nenhuma' se não há pessoa\n"
        "- Animais: liste somente os REALMENTE visíveis com espécie + ação; "
        "ou 'nenhum' se não há animal\n"
        "- Objetos: itens visíveis (vírgula-separado)\n"
        "- Ambiente: local + cores dominantes\n"
        "- Ações: o que está acontecendo (verbos no gerúndio)\n"
        "- Tags: 6 a 10 palavras-chave usando o vocabulário acima"
    )

    extras = []
    prio_set = set(prioridades)

    if "tudo" in prio_set:
        extras.append("Máximo 5 linhas.")
    else:
        if "animais" in prio_set:
            extras.append(
                "Foque a descrição estritamente em identificar espécies, raças e "
                "comportamentos de animais visíveis na imagem."
            )
        if "pessoas" in prio_set:
            extras.append(
                "Foque em descrever detalhadamente as pessoas: gênero, idade aproximada, "
                "roupas, expressões faciais e ações."
            )
        if "paisagens" in prio_set:
            extras.append(
                "Foque em descrever o ambiente, paisagem, elementos naturais, "
                "arquitetônicos e as cores dominantes da cena."
            )
        if not extras:
            extras.append("Máximo 5 linhas.")

    return base + "\n" + " ".join(extras)


def _resize_image_for_llava(filepath: str, max_size=768) -> bytes:
    """Redimensiona imagem em memória para otimizar processamento no LLaVA."""
    if not PIL_OK:
        with open(filepath, "rb") as f:
            return f.read()
            
    try:
        import io
        with _PILImage.open(filepath) as img:
            img = img.convert("RGB")
            w, h = img.size
            if max(w, h) > max_size:
                ratio = max_size / float(max(w, h))
                new_size = (int(w * ratio), int(h * ratio))
                img = img.resize(new_size, _PILImage.Resampling.LANCZOS)
            
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=85)
            return buffer.getvalue()
    except Exception as exc:
        print(f"[Otimização] Falha ao redimensionar {filepath}: {exc}")
        with open(filepath, "rb") as f:
            return f.read()


def _analyze_image(filepath: str, *, prioridades=None, perfil="fast") -> str:
    vlm_desc = None
    if prioridades is None:
        prioridades = ["tudo"]

    # ── Modelos de visão a tentar ───────────────────────────────────────────
    # LLaVA é o modelo usado: nos testes, o qwen2.5vl ficou inviável neste
    # hardware (7-12 min/imagem — vision encoder mal otimizado no llama.cpp).
    # LLaVA roda em ~1 min/imagem. Ordem de fallback caso um não esteja instalado.
    if perfil == "deep":
        models_to_try = ["llava:13b", "llava"]
    else:
        models_to_try = ["llava", "llava:13b"]

    prompt = _build_llava_prompt(prioridades)

    # ── Modelo de visão via Ollama com fallback automático ──────────────────
    if OLLAMA_OK:
        optimized_image_bytes = _resize_image_for_llava(filepath)
        for model in models_to_try:
            try:
                resp = _ollama.chat(
                    model=model,
                    options={"temperature": 0.0, "top_p": 0.5},
                    messages=[{
                        "role": "user",
                        "content": prompt,
                        "images": [optimized_image_bytes],
                    }],
                )
                vlm_desc = resp["message"]["content"]
                print(f"[VLM:{model}] OK: {os.path.basename(filepath)}")
                break  # Sucesso — não tenta o próximo modelo
            except Exception as exc:
                error_msg = f"[VLM:{model}] Indisponível para {filepath}: {exc}"
                print(error_msg)
                with open("searchplus.log", "a") as f:
                    f.write(error_msg + "\n")
                continue  # Tenta próximo modelo

    return vlm_desc or f"Imagem: {os.path.basename(filepath)}"


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
