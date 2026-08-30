"""
Search+ Backend — Flask API
Serve o frontend em http://127.0.0.1:5000 e expõe todos os endpoints da API.
"""

import os
import re
import json
import hashlib
import bcrypt
import mimetypes
import queue
import shutil
import subprocess
import threading
import time
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import psycopg2
import psycopg2.errors
from psycopg2 import pool as pg_pool
from psycopg2.extras import RealDictCursor
from pgvector.psycopg2 import register_vector
from dotenv import load_dotenv

from flask import (
    Flask, g, has_app_context, jsonify, request, send_file,
    send_from_directory, session,
)
from flask_cors import CORS

# ──────────────────────────────────────────────────────────────────────────────
# Configuração de caminhos e ambiente
# ──────────────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent   # .../backend/

# Carrega .env do diretório do backend
load_dotenv(BASE_DIR / ".env")

# Pasta servida como frontend. Por padrão é a raiz do projeto (o protótipo em
# HTML/CSS/JS puro). Quando o front definitivo chegar, basta apontar o .env para
# a pasta de build dele — nenhuma linha de Python muda:
#   FRONTEND_DIR=../front/dist
_frontend_cfg = os.environ.get("FRONTEND_DIR", "").strip()
FRONTEND_DIR = (
    (BASE_DIR / _frontend_cfg).resolve() if _frontend_cfg else BASE_DIR.parent
)
if _frontend_cfg and not FRONTEND_DIR.is_dir():
    print(f"[Front] FRONTEND_DIR '{FRONTEND_DIR}' não existe — caindo para a raiz do projeto.")
    FRONTEND_DIR = BASE_DIR.parent

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL não definida. Crie backend/.env baseado em .env.example."
    )

# ──────────────────────────────────────────────────────────────────────────────
# Libs opcionais (sem crash se não instaladas)
# ──────────────────────────────────────────────────────────────────────────────

# ── Claude (Anthropic): toda a IA de visão e re-rank do Search+ ─────────────
# O Search+ usa o Claude para (1) descrever imagens e (2) julgar a relevância
# dos resultados da busca. A chave fica no .env (ANTHROPIC_API_KEY), nunca no
# código. Os embeddings (SBERT/CLIP) continuam locais — só a descrição e o
# julgamento usam a API.
_CLAUDE = None
CLAUDE_OK = False
# Modelo usado tanto para descrever imagens quanto para julgar a busca.
# Pode ser trocado no .env (CLAUDE_MODEL) sem mexer no código.
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "").strip() or "claude-opus-5"
try:
    import anthropic as _anthropic
    _chave = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not _chave:
        print("[AI] ANTHROPIC_API_KEY não encontrada no .env — análise de imagens e re-rank ficarão indisponíveis.")
    else:
        _CLAUDE = _anthropic.Anthropic(api_key=_chave)
        CLAUDE_OK = True
        print("[AI] Claude ativo — descrição de imagens e re-rank da busca via API.")
except ImportError:
    print("[AI] Lib 'anthropic' não instalada (pip install anthropic).")
except Exception as _e:
    print(f"[AI] Falha ao iniciar Claude: {_e}")

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

# static_folder=None desliga a rota estática automática do Flask. Com
# static_url_path="" ela registrava o próprio '/<path:filename>' e, por ser
# criada junto com o app, vencia a nossa — devolvendo 404 em rotas de SPA antes
# que o fallback para o index.html tivesse chance de rodar. Servimos os arquivos
# em serve_static(), logo abaixo.
app = Flask(__name__, static_folder=None)

# Chave de sessão: vem do .env em produção. O fallback só existe para o
# desenvolvimento local não exigir configuração — trocar a chave invalida todas
# as sessões abertas, então em produção ela PRECISA ser fixa e secreta.
app.secret_key = os.environ.get("SECRET_KEY", "").strip() or "searchplus_dev_only_key"
if app.secret_key == "searchplus_dev_only_key":
    print("[Auth] SECRET_KEY não definida no .env — usando chave de desenvolvimento.")

# ── Origens liberadas no CORS ───────────────────────────────────────────────
# O front pode ser servido pelo próprio Flask (same-origin, porta 5000) ou por
# um dev server separado (Vite 5173, Next/CRA 3000...). Configurável no .env:
#   ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000
_ORIGENS_PADRAO = [
    "http://127.0.0.1:5000",  "http://localhost:5000",   # Flask (same-origin)
    "http://127.0.0.1:5500",  "http://localhost:5500",   # Live Server
    "http://127.0.0.1:5173",  "http://localhost:5173",   # Vite
    "http://127.0.0.1:3000",  "http://localhost:3000",   # Next.js / CRA
    "http://127.0.0.1:4200",  "http://localhost:4200",   # Angular
    "http://127.0.0.1:8080",  "http://localhost:8080",   # Vue CLI
]
_extra_origins = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()
]
ALLOWED_ORIGINS = _extra_origins or _ORIGENS_PADRAO

# ── Cookie de sessão ────────────────────────────────────────────────────────
# SameSite=Lax faz o browser NÃO enviar o cookie em requisições cross-site, o
# que quebra o login inteiro quando o front roda em outra porta (localhost:5173
# → localhost:5000 são sites diferentes para essa regra). Nesse cenário é
# preciso SameSite=None, que por especificação só vale acompanhado de Secure
# (ou seja, HTTPS). Configurável no .env para não travar quem serve tudo pelo
# Flask, onde Lax é a opção mais segura.
#   CROSS_SITE_COOKIES=1  → SameSite=None + Secure (front em outro domínio/porta, sob HTTPS)
_cross_site = os.environ.get("CROSS_SITE_COOKIES", "0") == "1"
app.config["SESSION_COOKIE_SAMESITE"] = "None" if _cross_site else "Lax"
app.config["SESSION_COOKIE_SECURE"] = _cross_site
app.config["SESSION_COOKIE_HTTPONLY"] = True
if _cross_site:
    print("[Auth] Cookies cross-site ativos (SameSite=None; Secure) — exige HTTPS.")

CORS(
    app,
    supports_credentials=True,
    origins=ALLOWED_ORIGINS + ["null"],
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


def _limpar_texto_para_banco(texto: str) -> str:
    """
    Tira o byte NUL do texto extraído de arquivos.

    O Postgres recusa \\x00 em coluna `text` ("A string literal cannot contain
    NUL characters"), e basta UM .txt/.csv corrompido com esse byte para o
    UPDATE estourar. Como a exceção subia no meio do worker, a thread de
    indexação morria e o acervo inteiro parava de ser processado — com o status
    exibindo "Ocioso", sem nenhum sinal de erro para o usuário.
    """
    return texto.replace("\x00", "") if texto else texto


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


def _extrair_campos_descricao(desc: str) -> str:
    """
    Extrai campos semanticamente ricos da descrição para gerar embedding.
    Inclui 'Estilo', 'O que é', 'Pessoas', 'Animais', 'Objetos', 'Ações',
    'Texto' e 'Tags'. Descarta 'Ambiente' (cores/local) para reduzir ruído.
    Retorna o texto original se o formato estruturado não for encontrado.
    """
    campos_alvo = {"estilo", "o que e", "pessoas", "animais", "objetos",
                   "acoes", "texto", "tags"}
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
    Prepara o texto da descrição para virar embedding de alto recall.
    Expande sinônimos no próprio texto do documento (não só na query), então
    uma imagem com 'cão' também casa com buscas por 'cachorro', 'caozinho' etc.
    """
    campos = _extrair_campos_descricao(desc)
    tokens = _tokenizar(campos)
    expandido = _expandir_sinonimos(tokens)
    return expandido or _normalizar(campos)


def _rerank_com_claude(query: str, candidatos: list[dict], topk: int = 15) -> list[dict]:
    """
    Re-rank usando o Claude como juiz semântico: em vez de dar notas, ele diz
    QUAIS resultados realmente correspondem à busca e quais não.
    Resolve casos como 'gato aparecendo em busca de cachorro' — o Claude entende
    que são animais diferentes, mesmo que os embeddings os achem parecidos.

    Penaliza forte (corta) os que o Claude marca como NÃO correspondentes; mantém
    a ordem do motor para os correspondentes. Degrada gracioso se a API falhar.
    """
    if not CLAUDE_OK or _CLAUDE is None or not candidatos:
        return candidatos

    topo = candidatos[:topk]
    resto = candidatos[topk:]

    # Monta a lista numerada com a descrição curta de cada candidato.
    # Itens SEM descrição (imagens lazy ainda não descritas) ficam de fora do
    # julgamento — o Claude só teria o nome do arquivo pra opinar, o que é
    # chute. O score visual do motor decide por eles.
    itens = []
    julgaveis = []  # índices de `topo` na mesma ordem dos números do prompt
    for c in topo:
        desc = (c.get("descricao_ia") or "").strip()
        if not desc:
            continue
        julgaveis.append(c)
        # O tipo vai junto porque a régua é outra para imagem e para documento
        # (ver o prompt abaixo). Sem essa marcação, o juiz cobrava de um manual
        # de bicicleta o mesmo que cobraria de uma foto e o descartava.
        eh_img = c.get("tipo") in _EXT_IMG
        rotulo = "IMAGEM" if eh_img else "DOCUMENTO"
        # 500 caracteres: a descrição é multi-campo (Estilo/Pessoas/Animais/...),
        # e cortar cedo demais escondia justamente o campo que decide o veredito.
        itens.append(
            f"{len(julgaveis)}. [{rotulo}] {desc[:500]}".replace("\n", " | ")
        )

    if not itens:
        return candidatos

    prompt = (
        f"O usuário buscou por: \"{query}\"\n\n"
        f"Abaixo estão arquivos encontrados (com a descrição de cada um). "
        f"Para CADA número, responda se o arquivo REALMENTE corresponde ao que o "
        f"usuário buscou.\n\n"
        f"A régua muda conforme o tipo do arquivo:\n\n"
        f"[IMAGEM] — vale o que a imagem MOSTRA. Seja rigoroso com coisas "
        f"parecidas mas distintas: numa busca por 'cachorro', um GATO NÃO "
        f"corresponde, mesmo que ambos sejam animais.\n"
        f"O MEIO da imagem nunca desqualifica: desenho, ilustração, pintura, "
        f"anime, cartoon, quadrinho, pixel art e render 3D contam pelo que "
        f"representam. Um desenho de cachorro CORRESPONDE a uma busca por "
        f"'cachorro'. Só marque false quando o assunto for outro, não quando o "
        f"estilo for diferente do esperado — a menos que o usuário tenha pedido um "
        f"estilo específico (ex.: 'foto de cachorro' exclui desenhos; "
        f"'desenho de cachorro' exclui fotos).\n\n"
        f"[DOCUMENTO] — vale o ASSUNTO de que o texto trata. A pergunta é se "
        f"alguém que buscou aquilo ficaria satisfeito ao abrir este documento, "
        f"e NÃO se o documento é o objeto buscado. Um manual de manutenção de "
        f"bicicleta CORRESPONDE a 'freio da bicicleta', porque é sobre isso que "
        f"ele fala. Não exija que o texto responda a pergunta por completo nem "
        f"que contenha um dado específico: tratar do assunto basta. Marque false "
        f"só quando o tema for realmente outro.\n\n"
        + "\n".join(itens)
    )

    try:
        resp = _CLAUDE.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2000,
            output_config={
                "effort": "low",
                "format": {
                    "type": "json_schema",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "veredictos": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "n": {"type": "integer"},
                                        "corresponde": {"type": "boolean"},
                                    },
                                    "required": ["n", "corresponde"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["veredictos"],
                        "additionalProperties": False,
                    },
                },
            },
            messages=[{"role": "user", "content": prompt}],
        )
        if resp.stop_reason == "refusal":
            print("[Rerank Claude] Recusado — mantendo ordem original")
            return candidatos
        raw = "".join(b.text for b in resp.content if b.type == "text").strip()
        dados = json.loads(raw)
        veredictos = {
            int(v["n"]): bool(v["corresponde"])
            for v in dados.get("veredictos", [])
            if isinstance(v, dict) and "n" in v and "corresponde" in v
        }
    except Exception as exc:
        print(f"[Rerank Claude] Falhou, mantendo ordem original: {exc}")
        return candidatos

    for i, c in enumerate(julgaveis, 1):
        if veredictos.get(i) is not False:
            continue  # corresponde, ou o Claude não opinou → mantém o score do motor
        # Hit semântico muito forte: o juiz pode estar errado (descrição pobre,
        # sinônimo que ele não reconheceu). Penaliza sem eliminar.
        if c.get("_sbert", 0.0) >= 0.75:
            c["score"] = min(c["score"], 0.45)
            print(f"[Rerank Claude] '{c['nome']}' duvidoso para '{query}' — rebaixado")
            continue
        # Caso normal: joga o score pra baixo do corte final. Não remove direto
        # (deixa o corte > 0.25 do api_search descartar), assim a lógica de corte
        # fica num lugar só.
        print(f"[Rerank Claude] '{c['nome']}' nao corresponde a '{query}' — descartado")
        c["score"] = 0.10

    topo.sort(key=lambda x: x["score"], reverse=True)
    return topo + resto


# ──────────────────────────────────────────────────────────────────────────────
# Banco de dados Postgres (Supabase) — pool de conexões
# ──────────────────────────────────────────────────────────────────────────────

# Tamanho do pool. O frontend dispara várias chamadas em paralelo ao abrir a
# home (config + stats + gallery + favorites + collections + status), e cada aba
# aberta multiplica isso — 10 conexões estouravam com facilidade. Configurável
# no .env porque o teto depende do plano do Postgres/Supabase.
_POOL_MAX = max(4, int(os.environ.get("DB_POOL_MAX", "20")))
_POOL_TIMEOUT = float(os.environ.get("DB_POOL_TIMEOUT", "10"))

_pg_pool = pg_pool.ThreadedConnectionPool(1, _POOL_MAX, dsn=DATABASE_URL)
print(f"[DB] Pool Postgres pronto ({DATABASE_URL.split('@')[-1]}, máx {_POOL_MAX} conexões)")


def _pegar_conexao_do_pool():
    """
    Pega uma conexão, esperando se todas estiverem ocupadas.

    `ThreadedConnectionPool.getconn()` não espera: com o pool cheio ele levanta
    PoolError na hora, e um pico de requisições paralelas virava uma rajada de
    HTTP 500. Como as conexões são devolvidas em milissegundos, uma espera curta
    resolve o pico sem precisar de um pool gigante.
    """
    limite = time.monotonic() + _POOL_TIMEOUT
    while True:
        try:
            return _pg_pool.getconn()
        except pg_pool.PoolError:
            if time.monotonic() >= limite:
                raise
            time.sleep(0.05)


class _PooledConnection:
    """
    Wrapper de conexão Postgres que devolve ao pool no .close() em vez de fechar.
    Mantém a mesma interface do sqlite3.Connection (conn.execute, conn.commit, conn.close)
    pra minimizar refactor das chamadas existentes.
    """
    def __init__(self, raw):
        self._raw = raw
        self._fechada = False
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
        """
        Devolve a conexão ao pool. Idempotente: chamar duas vezes não faz nada
        na segunda — é o que permite ao teardown do request fechar sobras sem
        arriscar devolver ao pool uma conexão que já voltou.
        """
        if self._fechada:
            return
        self._fechada = True
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
    """
    Pega uma conexão do pool. Continue chamando `.close()` ao terminar — quanto
    antes ela voltar ao pool, melhor (uma busca segura a conexão por segundos se
    esperar o fim do request).

    Dentro de um request as conexões entregues ficam anotadas em `flask.g`, e o
    teardown fecha o que sobrar. É só uma rede de segurança: sem ela, qualquer
    exceção entre o `get_db()` e o `conn.close()` vazava uma conexão para
    sempre, e bastavam algumas dezenas de erros para esgotar o pool e derrubar
    o servidor inteiro.
    """
    conn = _PooledConnection(_pegar_conexao_do_pool())
    if has_app_context():
        abertas = getattr(g, "_db_abertas", None)
        if abertas is None:
            abertas = []
            g._db_abertas = abertas
        abertas.append(conn)
    return conn


@app.teardown_appcontext
def _fechar_db_do_request(_exc):
    """Fecha conexões que o handler não devolveu — por exceção ou esquecimento."""
    for conn in (getattr(g, "_db_abertas", None) or []):
        if not conn._fechada:
            print("[DB] Conexão não devolvida pelo handler — fechando no teardown.")
        conn.close()   # idempotente: no-op se o handler já fechou


def _vec_to_list(v):
    """
    Normaliza um vetor lido do banco para lista de float puro.

    O pgvector >= 0.4 devolve um objeto `Vector`, que NÃO é iterável e não
    converte pra float direto — np.array([Vector]) vira array de dtype=object
    e quebra o cosine_similarity. Aceita também list/tuple/numpy (caso o
    adapter não esteja registrado) pra ficar à prova de versão.
    """
    if v is None:
        return None
    to_list = getattr(v, "to_list", None)     # pgvector.Vector
    if callable(to_list):
        return [float(x) for x in to_list()]
    tolist = getattr(v, "tolist", None)       # numpy.ndarray
    if callable(tolist):
        return [float(x) for x in tolist()]
    if isinstance(v, str):                    # fallback: '[0.1,0.2,...]'
        return [float(x) for x in v.strip("[]").split(",") if x.strip()]
    return [float(x) for x in v]              # list/tuple


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
    """Gera hash bcrypt da senha (seguro contra brute-force)."""
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def _verificar_senha(pw: str, hash_armazenado: str) -> bool:
    """
    Verifica a senha contra o hash do banco. Aceita:
    - bcrypt (novo padrão): hashes que começam com $2
    - SHA-256 (legado): migração transparente de contas antigas
    """
    if not hash_armazenado:
        return False
    if hash_armazenado.startswith("$2"):
        try:
            return bcrypt.checkpw(pw.encode("utf-8"), hash_armazenado.encode("utf-8"))
        except ValueError:
            return False
    # Legado SHA-256: compara e (no login) será re-hasheado para bcrypt
    return hashlib.sha256(pw.encode()).hexdigest() == hash_armazenado


def _eh_hash_legado(hash_armazenado: str) -> bool:
    """True se o hash ainda é SHA-256 (precisa migrar para bcrypt)."""
    return bool(hash_armazenado) and not hash_armazenado.startswith("$2")


def _uid():
    """Retorna user_id da sessão ou None."""
    return session.get("user_id")


# ──────────────────────────────────────────────────────────────────────────────
# Servir frontend (sem CORS, same-origin)
# ──────────────────────────────────────────────────────────────────────────────

# Extensões que um frontend legitimamente serve. É uma allowlist, e não uma
# lista de bloqueio, porque a pasta servida é a raiz do projeto — que contém
# backend/.env (senha do banco e chave da API), .git/ e o código do servidor.
# Com denylist, qualquer arquivo novo nasceria público até alguém lembrar de
# bloqueá-lo; assim, nasce privado.
_EXT_PUBLICAS = {
    ".html", ".htm", ".css", ".js", ".mjs", ".cjs", ".map", ".json", ".wasm",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico", ".avif",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp4", ".webm", ".mp3", ".ogg", ".wav",
    ".txt", ".webmanifest", ".xml",
}

# Pastas nunca servidas, mesmo que contenham arquivos de extensão liberada.
_PASTAS_PRIVADAS = {"backend", "docs", "node_modules", "venv", "__pycache__"}


def _pode_servir(rel: Path) -> bool:
    """Decide se um caminho relativo ao FRONTEND_DIR pode ir para o navegador."""
    partes = rel.parts
    # Dotfiles e dotdirs em qualquer nível: .env, .git/, .vscode/, .gitignore
    if any(p.startswith(".") for p in partes):
        return False
    if any(p.lower() in _PASTAS_PRIVADAS for p in partes[:-1]):
        return False
    return rel.suffix.lower() in _EXT_PUBLICAS


@app.route("/")
def serve_index():
    return send_from_directory(str(FRONTEND_DIR), "index.html")


@app.route("/<path:filename>")
def serve_static(filename):
    """
    Serve um arquivo do frontend; se a rota não for um arquivo, devolve o
    index.html.

    O fallback é o que faz uma SPA com roteamento próprio (React Router, Vue
    Router) funcionar: abrir /configuracoes direto na barra de endereços não
    corresponde a nenhum arquivo em disco, e sem isso viraria 404 em vez de
    deixar o roteador do front resolver a rota.
    """
    if filename.startswith("api/"):
        return jsonify({"error": "not found"}), 404

    destino = (FRONTEND_DIR / filename).resolve()
    # Confere que o caminho pedido não escapou da pasta do frontend via '../'
    if FRONTEND_DIR not in destino.parents and destino != FRONTEND_DIR:
        return jsonify({"error": "not found"}), 404

    rel = destino.relative_to(FRONTEND_DIR)
    if destino.is_file():
        if not _pode_servir(rel):
            return jsonify({"error": "not found"}), 404
        # as_posix(): send_from_directory espera '/' como separador. No Windows,
        # str(rel) devolveria 'fonts\arquivo.ttf' e a barra invertida seria
        # recusada, transformando um arquivo existente em 404.
        resposta = send_from_directory(str(FRONTEND_DIR), rel.as_posix())

        # Código do frontend nunca é cacheado. O index.html referencia
        # `script.js?v=<string fixa>`: se o navegador guardar a versão antiga,
        # ela fica servida para sempre, e o app passa a rodar HTML novo com JS
        # velho — sintoma que aparece como erro de backend, não de cache.
        # Fonte e imagem continuam cacheáveis: mudam raramente e pesam.
        if rel.suffix.lower() in {".js", ".css", ".html"}:
            resposta.headers["Cache-Control"] = "no-store, must-revalidate"
        return resposta

    # Não é arquivo: se o caminho tem cara de recurso estático (tem extensão),
    # é um 404 de verdade. Sem extensão, é rota de SPA — entrega o index.html
    # e deixa o roteador do frontend decidir.
    if rel.suffix:
        return jsonify({"error": "not found"}), 404
    return send_from_directory(str(FRONTEND_DIR), "index.html")


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
    # Último diretório usado para exportar. Pré-preenche o seletor nativo na
    # próxima vez — quem sempre exporta para o mesmo lugar reescolhia o caminho
    # a cada exportação. Vazio = seletor abre onde o sistema decidir.
    "ultima_pasta_exportacao": "",
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

    if row and _verificar_senha(password, row["password_hash"]):
        # Migração transparente: se a conta ainda usa SHA-256, re-hash com bcrypt
        if _eh_hash_legado(row["password_hash"]):
            try:
                conn.execute(
                    "UPDATE users SET password_hash = %s WHERE id = %s",
                    (_hash(password), row["id"])
                )
                conn.commit()
                print(f"[Auth] Senha de '{username}' migrada para bcrypt.")
            except Exception as exc:
                print(f"[Auth] Falha ao migrar senha: {exc}")
        conn.close()
        session["user_id"] = row["id"]
        session["username"] = username
        return jsonify({"status": "ok", "username": username})

    conn.close()
    return jsonify({"mensagem": "Usuário ou senha incorretos."}), 401


@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    handle   = (data.get("handle") or "").strip()
    password = (data.get("password") or "").strip()

    if not username or not password:
        return jsonify({"mensagem": "Preencha todos os campos."}), 400

    # O bcrypt recusa senhas acima de 72 BYTES — e em UTF-8 cada acento ocupa
    # 2, então uma senha em português estoura o limite antes dos 72 caracteres.
    # Sem esta checagem o erro subia como 500, vazando a mensagem da biblioteca.
    if len(password.encode("utf-8")) > 72:
        return jsonify({
            "mensagem": "Senha muito longa (máximo 72 bytes; letras acentuadas contam 2)."
        }), 400

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
        # Banco existe mas sem schema (ex: tabelas dropadas durante o uso) —
        # recria e tenta de novo. O próprio tipo da exceção já diz que a tabela
        # não existe; não há mensagem a inspecionar.
        print(f"[DB] Schema ausente, recriando: {exc}")
        conn.close()  # limpa a transação abortada antes de rodar o DDL
        try:
            init_db()
            conn = get_db()
            conn.execute(
                "INSERT INTO users (username, password_hash, config_json) VALUES (%s, %s, %s)",
                (username, _hash(password), json.dumps(cfg)),
            )
            conn.commit()
            return jsonify({"status": "ok"})
        except psycopg2.errors.UniqueViolation:
            return jsonify({"mensagem": "Este usuário já existe."}), 409
        except Exception as exc2:
            print(f"[DB] Falha após recriar schema: {exc2}")
            return jsonify({"mensagem": f"Erro interno: {exc2}"}), 500
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
        conn.close()

        cfg = {**_DEFAULT_CFG, **_safe_json_loads(row["config_json"], {})} if row else dict(_DEFAULT_CFG)
        cfg["pastas"] = _folders_to_json(_list_folders(uid))
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
    # MERGE, não replace: o config_json guarda também o histórico de buscas
    # (chave 'search_history'). Sobrescrever o blob inteiro apagava o histórico
    # a cada salvamento de preferência, e obrigaria o frontend a reenviar o
    # objeto completo só para mudar um campo.
    row = conn.execute("SELECT config_json FROM users WHERE id = %s", (uid,)).fetchone()
    cfg_atual = _safe_json_loads(row["config_json"] if row else None, {}) or {}
    cfg_atual.update(data)

    conn.execute("UPDATE users SET config_json = %s WHERE id = %s",
                 (json.dumps(cfg_atual), uid))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


# ──────────────────────────────────────────────────────────────────────────────
# Pastas monitoradas
# ──────────────────────────────────────────────────────────────────────────────

def _prefixo_pasta(pasta: str) -> str:
    """
    Prefixo canônico de uma pasta, para decidir se um caminho está DENTRO dela.

    Três cuidados, e cada um corrige um jeito diferente de errar:
      - `normpath` resolve '..' e unifica os separadores;
      - o separador no fim impede 'C:\\fotos' de casar com 'C:\\fotos_backup';
      - minúsculas porque o Windows não diferencia caixa, e o mesmo arquivo
        pode estar no índice como 'C:\\Fotos\\a.jpg' ou 'c:\\fotos\\a.jpg'.

    Quem compara com este prefixo tem que aplicar `lower()` no outro lado
    também — daí o `left(lower(caminho), ...)` nas queries.
    """
    return os.path.normpath(pasta).rstrip("\\/").lower() + os.sep


def _apagar_arquivos_da_pasta(conn, uid: int, pasta: str) -> None:
    """
    Remove do índice os arquivos que estão DENTRO de `pasta`.

    Não usa LIKE de propósito: 'C:\\fotos%' casaria também com
    'C:\\fotos_backup', apagando o índice de uma pasta irmã, e o '_' do LIKE é
    curinga (qualquer pasta com underscore casaria demais). Comparar o prefixo
    com left() e o separador no fim resolve os dois casos.

    Subpastas que continuam monitoradas são preservadas: quem monitora
    'C:\\A' e 'C:\\A\\B' e remove só 'C:\\A' não pode perder o índice de
    'C:\\A\\B', que segue na lista de pastas e não seria reindexado sozinho.
    """
    prefixo = _prefixo_pasta(pasta)

    monitoradas = conn.execute(
        "SELECT path FROM folders WHERE user_id = %s", (uid,)
    ).fetchall()
    subpastas = [
        p for p in (_prefixo_pasta(r["path"]) for r in monitoradas)
        if p.startswith(prefixo) and p != prefixo
    ]

    sql = "DELETE FROM files WHERE user_id = %s AND left(lower(caminho), %s) = %s"
    params: list = [uid, len(prefixo), prefixo]
    for sub in subpastas:
        sql += " AND left(lower(caminho), %s) <> %s"
        params.extend([len(sub), sub])

    conn.execute(sql, params)


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

        # Unifica separadores e resolve '..' antes de gravar — sem isso a mesma
        # pasta escrita de dois jeitos vira dois registros distintos.
        pasta = os.path.normpath(pasta)

        # Novos campos de Indexação Inteligente
        prioridades = data.get("prioridades", ["tudo"])
        perfil      = data.get("perfil_analise", "fast")
        janela      = data.get("janela_processamento", "always")

        name = os.path.basename(pasta) or pasta
        conn = get_db()
        try:
            # O UNIQUE (user_id, path) diferencia maiúsculas, mas o Windows não:
            # cadastrar 'C:\Fotos' e depois 'c:\fotos' indexava a MESMA pasta
            # duas vezes — resultado repetido na busca e o dobro de chamadas ao
            # Claude. A checagem case-insensitive resolve antes do INSERT e
            # preserva o caminho já gravado, com a caixa original.
            ja_existe = conn.execute(
                "SELECT path FROM folders WHERE user_id = %s AND lower(path) = %s",
                (uid, pasta.lower()),
            ).fetchone()

            if ja_existe:
                conn.execute(
                    "UPDATE folders SET prioridades=%s, perfil_analise=%s, janela_processamento=%s "
                    "WHERE user_id=%s AND path=%s",
                    (json.dumps(prioridades), perfil, janela, uid, ja_existe["path"]),
                )
            else:
                conn.execute(
                    "INSERT INTO folders (user_id, path, name, added_at, prioridades, perfil_analise, janela_processamento) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (uid, pasta, name, datetime.now(timezone.utc).isoformat(),
                     json.dumps(prioridades), perfil, janela),
                )
            conn.commit()
        except psycopg2.errors.UniqueViolation:
            # Corrida entre dois requests simultâneos — o outro inseriu primeiro.
            # O rollback é obrigatório: sem ele a transação fica abortada e o
            # UPDATE abaixo estoura InFailedSqlTransaction, virando um 500.
            conn.rollback()
            conn.execute(
                "UPDATE folders SET prioridades=%s, perfil_analise=%s, janela_processamento=%s "
                "WHERE user_id=%s AND lower(path)=%s",
                (json.dumps(prioridades), perfil, janela, uid, pasta.lower()),
            )
            conn.commit()
        finally:
            conn.close()

        # NÃO dispara a análise aqui — só salva a pasta. A análise começa quando
        # o usuário confirma (botão "Analisar"/"Concluir"), que chama
        # /api/analyze_folders. Assim o usuário escolhe deep/relâmpago antes.

        rows = _list_folders(uid)
        return jsonify({"status": "ok", "pastas": _folders_to_json(rows)})

    # DELETE
    data = request.get_json(force=True) or {}
    pasta = (data.get("pasta") or "").strip()

    conn = get_db()
    _apagar_arquivos_da_pasta(conn, uid, pasta)
    # Compara sem caixa e sem barra final, pelo mesmo motivo do cadastro: no
    # Windows 'C:\Fotos' e 'c:\fotos\' são a mesma pasta.
    alvo = os.path.normpath(pasta).rstrip("\\/").lower() if pasta else ""
    conn.execute(
        "DELETE FROM folders WHERE user_id = %s AND lower(rtrim(path, '\\/')) = %s",
        (uid, alvo),
    )
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
        _apagar_arquivos_da_pasta(conn, uid, row["path"])

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

    # Indexação lazy: no upload só geramos o embedding CLIP local (~0.5s por
    # arquivo). A descrição pela IA acontece depois, sob demanda, na busca —
    # então ela não entra nesta estimativa. O perfil (fast/deep) afeta o nível
    # de detalhe da descrição na busca, não o tempo de indexação.
    rate = 0.5  # segundos por arquivo (embedding CLIP local)

    est_min = round((count * rate) / 60, 1)
    # Se o tempo for menor que 0.1 mas maior que 0, mostre 0.1 min
    if est_min == 0 and count > 0:
        est_min = 0.1

    return jsonify({
        "estimativa_minutos": est_min,
        "total_imagens": count,
        "truncado": truncado,
    })


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

def _tk_pick(mode: str, inicial: str = ""):
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
        # `initialdir` inexistente faz o tkinter cair no padrão sozinho, sem
        # erro — daí só checar isdir e deixar o resto com ele.
        kwargs = {"title": "Selecionar Pasta"}
        if inicial and os.path.isdir(inicial):
            kwargs["initialdir"] = inicial
        path = filedialog.askdirectory(**kwargs)

    root.destroy()
    return os.path.normpath(path) if path else None


@app.route("/api/choose_image")
def api_choose_image():
    if not _uid():
        return jsonify({"status": "erro", "mensagem": "Não autenticado."}), 401
    try:
        path = _tk_pick("image")
        if not path:
            return jsonify({"status": "cancelado"})

        # Devolve a imagem já em base64 (data URL). Isso é usado por avatar/
        # banner, que tipicamente são imagens FORA das pastas monitoradas —
        # então não dá pra servir via /api/file (que só libera pastas do user).
        # Limite de 20 MB no arquivo de origem (o cropper reduz a resolução
        # final, então o que é salvo no config fica pequeno).
        try:
            tamanho = os.path.getsize(path)
        except OSError:
            return jsonify({"status": "erro", "mensagem": "Não foi possível ler o arquivo."})
        if tamanho > 20 * 1024 * 1024:
            return jsonify({"status": "erro",
                            "mensagem": "Imagem muito grande (máx. 20 MB). Escolha uma menor."})

        import base64
        mime, _ = mimetypes.guess_type(path)
        if not mime or not mime.startswith("image/"):
            mime = "image/jpeg"
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        data_url = f"data:{mime};base64,{b64}"

        return jsonify({"status": "sucesso", "caminho": path, "data_url": data_url})
    except Exception as exc:
        return jsonify({"status": "erro", "mensagem": str(exc)})


@app.route("/api/choose_folder")
def api_choose_folder():
    if not _uid():
        return jsonify({"status": "erro", "mensagem": "Não autenticado."}), 401
    try:
        path = _tk_pick("folder", inicial=_ultima_pasta_exportacao(_uid()))
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

# Termos que indicam busca por imagem NÃO fotográfica (desenho, arte, etc.).
# Casados contra a query normalizada inteira, não contra os tokens, porque
# 'imagem'/'foto' são stopwords e sumiriam da tokenização.
_TERMOS_DESENHO = (
    "desenho", "desenhos", "desenhado", "desenhada", "desenhar",
    "ilustracao", "ilustracoes", "ilustrado", "arte", "artistico",
    "anime", "animes", "manga", "mangas", "animacao", "animado", "animada",
    "cartoon", "cartoons", "caricatura", "quadrinho", "quadrinhos", "hq",
    "pintura", "pintado", "aquarela", "oleo sobre tela",
    "pixel art", "pixelart", "arte digital", "digital art",
    "esboco", "rascunho", "sketch", "rabisco", "traco",
    "render", "3d", "cgi", "vetor", "vetorial",
    "logotipo", "logotipos", "icone", "icones", "emoji", "meme", "memes",
    "wallpaper", "papel de parede", "personagem", "personagens", "chibi",
    "captura de tela", "screenshot", "print", "grafico", "diagrama", "mapa",
)
# 'logo' fica de fora de propósito: é advérbio comum em pt-BR ("me mostre logo
# as fotos") e apareceria em buscas que nada têm a ver com logotipo.

# Termos que indicam busca por FOTOGRAFIA real (o oposto do conjunto acima)
_TERMOS_FOTO = (
    "foto", "fotos", "fotografia", "fotografias", "fotografico",
    "foto real", "imagem real", "vida real", "retrato fotografico",
)

# Frases na descrição que confirmam AUSÊNCIA de pessoas (normalizadas)
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

    # ── Estilo da imagem (desenho, arte, etc.) ───────────────────────────
    "desenho":    ["ilustracao", "arte", "desenhado", "cartoon", "esboco", "arte digital"],
    "desenhos":   ["ilustracoes", "desenho", "arte", "cartoon"],
    "ilustracao": ["desenho", "arte", "arte digital", "ilustrado"],
    "arte":       ["desenho", "ilustracao", "pintura", "arte digital"],
    "anime":      ["manga", "desenho", "animacao japonesa", "ilustracao", "personagem"],
    "manga":      ["anime", "quadrinho", "desenho", "ilustracao"],
    "cartoon":    ["desenho", "animacao", "caricatura", "ilustracao"],
    "animacao":   ["desenho", "cartoon", "animado"],
    "quadrinho":  ["hq", "manga", "cartoon", "desenho"],
    "quadrinhos": ["hq", "manga", "cartoon", "desenhos"],
    "hq":         ["quadrinho", "manga", "cartoon"],
    "pintura":    ["quadro", "arte", "pintado", "aquarela", "tela"],
    "esboco":     ["rascunho", "sketch", "desenho", "traco"],
    "sketch":     ["esboco", "rascunho", "desenho"],
    "personagem": ["desenho", "ilustracao", "anime", "cartoon", "figura"],
    "personagens": ["desenhos", "ilustracoes", "anime", "cartoon", "figuras"],
    # 'logo' sozinho não entra: é advérbio comum e poluiria o embedding da query.
    "logotipo":   ["marca", "icone", "simbolo", "identidade visual"],
    "icone":      ["logotipo", "simbolo"],
    "meme":       ["imagem engracada", "piada", "captura de tela"],
    "wallpaper":  ["papel de parede", "fundo de tela", "arte"],
    "screenshot": ["captura de tela", "print", "tela"],
    "print":      ["captura de tela", "screenshot", "tela"],
    "3d":         ["render", "cgi", "modelagem", "arte digital"],
    "render":     ["3d", "cgi", "modelagem"],
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


def _contem_termo(texto: str, termos) -> bool:
    """
    Procura qualquer um dos termos em `texto` casando PALAVRA INTEIRA.
    Substring pura daria falso-positivo caro aqui: 'arte' casaria dentro de
    'partes', 'meme' dentro de 'memento', 'mapa' dentro de qualquer coisa.
    Funciona também com termos compostos ('pixel art', 'captura de tela').
    """
    if not texto:
        return False
    return any(
        re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", texto)
        for t in termos
    )


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

    # Gênero: termos ambíguos depois de tirar acento ('vovô' e 'vovó' viram
    # 'vovo') marcavam os dois gêneros ao mesmo tempo, e aí as duas regras de
    # rejeição disparavam juntas e a busca voltava vazia. Empate = sem filtro.
    fem  = bool(palavras_set & _TERMOS_FEMININO)
    masc = bool(palavras_set & _TERMOS_MASCULINO)
    if fem and masc:
        fem = masc = False

    # Estilo: casado contra a query inteira porque 'foto'/'imagem' são
    # stopwords e não sobrevivem à tokenização.
    busca_desenho = _contem_termo(norm, _TERMOS_DESENHO)
    busca_foto    = _contem_termo(norm, _TERMOS_FOTO)
    if busca_desenho and busca_foto:
        # "foto de um desenho" — não dá pra decidir, não filtra por estilo.
        busca_desenho = busca_foto = False

    return {
        "original":        query,
        "normalizada":     norm,
        "palavras":        palavras,
        "palavras_set":    palavras_set,
        "expandida":       _expandir_sinonimos(palavras) or norm,
        "busca_pessoa":    bool(palavras_set & _TERMOS_PESSOA),
        "busca_animal":    bool(palavras_set & _TERMOS_ANIMAL),
        "busca_feminino":  fem,
        "busca_masculino": masc,
        "busca_desenho":   busca_desenho,
        "busca_foto":      busca_foto,
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

    # Palavra da query que aparece literalmente na descrição. Serve de escape
    # para as regras de rejeição abaixo: se a descrição diz "Animais: nenhum"
    # mas cita 'cachorro' em outro campo, quem decide é o juiz semântico, não
    # uma regra de texto. Evita descartar desenhos e casos de borda.
    matches_desc = q["palavras_set"] & desc_words
    tem_literal = bool(matches_desc)

    # === Regras de rejeição ===============================================

    # Busca de pessoa não pode retornar imagem sem pessoa
    if q["busca_pessoa"] and score_raw < 0.90 and not tem_literal:
        if any(frase in desc_norm for frase in _FRASES_SEM_PESSOA):
            return None

    # Busca de animal não pode retornar imagem sem animal
    if q["busca_animal"] and score_raw < 0.90 and not tem_literal:
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

    # Estilo pedido na query (desenho vs foto) casando com o campo "Estilo"
    # da descrição. É preferência, não filtro: no máximo empurra pra cima ou
    # pra baixo, nunca elimina — o corte final decide.
    if (q["busca_desenho"] or q["busca_foto"]) and desc_norm:
        estilo = _campo_descricao(desc_norm, "estilo")
        if estilo:
            e_desenho = _contem_termo(estilo, _TERMOS_DESENHO)
            e_foto    = _contem_termo(estilo, _TERMOS_FOTO)
            if q["busca_desenho"]:
                score += 0.12 if e_desenho else (-0.12 if e_foto else 0.0)
            elif q["busca_foto"]:
                score += 0.12 if e_foto else (-0.12 if e_desenho else 0.0)

    # Query exata dentro do nome do arquivo → +15%
    if q["normalizada"] and q["normalizada"] in nome_norm:
        score += 0.15

    # Cada palavra-chave da query que aparece na descrição → +5%
    if matches_desc:
        score += 0.05 * len(matches_desc)

    # Gênero da query combina com descrição → +8%
    if q["busca_feminino"] and (desc_words & _PALAVRAS_DESC_FEM):
        score += 0.08
    if q["busca_masculino"] and (desc_words & _PALAVRAS_DESC_MASC):
        score += 0.08

    return max(0.0, min(1.0, score))


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
        avancado = data.get("avancado") or {}
    else:
        query  = (request.args.get("q") or "").strip()
        filtro = request.args.get("filtro", "all")
        avancado = {}

    if not query:
        return jsonify({"resultados": [], "tempo": 0})

    t0 = time.time()

    if not SBERT_OK:
        return jsonify({"resultados": [], "tempo": 0,
                        "erro": "SBERT indisponível — busca semântica desligada."})

    q = _analisar_query(query)
    query_emb = _SBERT.encode(q["expandida"], convert_to_numpy=True).tolist()

    # Filtros SQL (tipo + filtros avançados de data e pasta)
    sql_filtros = []
    params_filtro = []

    if filtro == "imagem":
        sql_filtros.append("tipo = ANY(%s)")
        params_filtro.append(list(_EXT_IMG))
    elif filtro == "midia":
        sql_filtros.append("tipo = ANY(%s)")
        params_filtro.append(list(_EXT_VID | _EXT_AUD))
    elif filtro == "documento":
        sql_filtros.append("tipo != ALL(%s)")
        params_filtro.append(list(_EXT_IMG | _EXT_VID | _EXT_AUD))

    # Filtro avançado: data (data_de / data_ate em formato YYYY-MM-DD)
    if avancado.get("data_de"):
        sql_filtros.append("data_adicionado >= %s")
        params_filtro.append(avancado["data_de"])
    if avancado.get("data_ate"):
        # +1 dia pra incluir o dia inteiro
        sql_filtros.append("data_adicionado < (%s::date + interval '1 day')")
        params_filtro.append(avancado["data_ate"])

    # Filtro avançado: pasta específica (caminho começa com o path da pasta).
    # Usa left()=prefixo em vez de LIKE porque o '\' do Windows é caractere
    # de escape no LIKE do Postgres e quebraria o match. O prefixo sai de
    # _prefixo_pasta(): sem o separador no fim, filtrar por 'C:\Fotos' trazia
    # junto os arquivos de 'C:\Fotos_backup' e 'C:\Fotos2'.
    if avancado.get("pasta"):
        prefixo_pasta = _prefixo_pasta(avancado["pasta"])
        sql_filtros.append("left(lower(caminho), %s) = %s")
        params_filtro.append(len(prefixo_pasta))
        params_filtro.append(prefixo_pasta)

    sql_where_extra = (" AND " + " AND ".join(sql_filtros)) if sql_filtros else ""

    # Vetor CLIP da frase buscada — usado na query complementar de imagens lazy
    # e no cálculo de similaridade visual mais abaixo (calculado uma vez só).
    clip_query_vec = _gerar_embedding_clip_texto(q["original"]) if CLIP_OK else None

    # Candidatos: trazemos DOIS tipos de arquivo —
    #  (a) documentos/arquivos com embedding SBERT (texto), e
    #  (b) imagens com embedding_clip (busca lazy: indexadas só com CLIP, sem
    #      descrição ainda). O sbert_score é NULL pra imagens sem SBERT; o CLIP
    #      cuida da relevância delas mais abaixo.
    conn = get_db()
    rows = conn.execute(
        f"""
        SELECT id, folder_id, nome, caminho, tipo, descricao_ia,
               embedding_clip, data_adicionado, favorito,
               CASE WHEN embedding IS NOT NULL
                    THEN 1 - (embedding <=> %s::vector)
                    ELSE NULL END AS sbert_score
        FROM files
        WHERE user_id = %s AND processado = 1
              AND (embedding IS NOT NULL OR embedding_clip IS NOT NULL)
        {sql_where_extra}
        ORDER BY
            CASE WHEN embedding IS NOT NULL
                 THEN (embedding <=> %s::vector) ELSE 2 END ASC
        LIMIT 100
        """,
        (query_emb, uid, *params_filtro, query_emb)
    ).fetchall()
    rows = list(rows)

    # Complemento lazy: com muitos arquivos, as imagens sem SBERT ficam no fim
    # da ordenação acima e podem cair fora do LIMIT 100 — sumindo da busca.
    # Busca-as separadamente por similaridade VISUAL (CLIP no banco) e junta.
    if clip_query_vec is not None:
        rows_lazy = conn.execute(
            f"""
            SELECT id, folder_id, nome, caminho, tipo, descricao_ia,
                   embedding_clip, data_adicionado, favorito,
                   NULL AS sbert_score
            FROM files
            WHERE user_id = %s AND processado = 1
                  AND embedding IS NULL AND embedding_clip IS NOT NULL
            {sql_where_extra}
            ORDER BY embedding_clip <=> %s::vector
            LIMIT 40
            """,
            (uid, *params_filtro, clip_query_vec)
        ).fetchall()
        ja_vistos = {r["id"] for r in rows}
        rows.extend(r for r in rows_lazy if r["id"] not in ja_vistos)
    conn.close()

    if not rows:
        return jsonify({"resultados": [], "tempo": round(time.time() - t0, 3)})

    sbert_sims = [max(0.0, float(r["sbert_score"])) if r["sbert_score"] is not None else 0.0 for r in rows]

    # BM25 (palavra-chave) sobre os candidatos
    corpus_tokens = [
        _tokenizar((f["descricao_ia"] or "") + " " + (f["nome"] or ""))
        for f in rows
    ]
    bm25_sims = _bm25_scores(corpus_tokens, q["palavras"])

    # CLIP (visual): só pra imagens com embedding_clip (vetor da query já
    # foi calculado antes da SQL — reusa)
    clip_sims = [0.0] * len(rows)
    if CLIP_OK and SKLEARN_OK and clip_query_vec is not None:
        import numpy as np
        clip_q_np = np.array([clip_query_vec])
        for i, f in enumerate(rows):
            if f["tipo"] in _EXT_IMG and f["embedding_clip"] is not None:
                try:
                    img_vec = np.array([_vec_to_list(f["embedding_clip"])], dtype=float)
                    clip_sims[i] = float(cosine_similarity(clip_q_np, img_vec)[0][0])
                except Exception as e:
                    # Não engole em silêncio: sem CLIP, imagem sem descrição
                    # nunca pontua e some da busca.
                    print(f"[CLIP] falha ao comparar '{f['nome']}': {type(e).__name__}: {e}")

    # A similaridade CLIP texto↔imagem vive numa faixa estreita (~0.15 a 0.30),
    # bem diferente do SBERT, que usa [0, 1]. Misturar as duas escalas cruas
    # fazia o sinal visual valer quase nada: uma imagem sem descrição batia no
    # máximo 0.09 de score e era cortada antes de chegar na tela. Aqui a faixa
    # útil do CLIP é esticada para [0, 1] antes de entrar no blend. Os limiares
    # continuam usando o valor cru (clip_sims), que é onde foram calibrados.
    clip_norm = [max(0.0, min(1.0, (s - 0.15) / 0.15)) for s in clip_sims]

    # ── DESCRIÇÃO SOB DEMANDA (lazy) ────────────────────────────────────────
    # As imagens são indexadas só com embedding CLIP (sem descrição). Aqui,
    # na busca, pegamos as TOP-5 imagens visualmente mais parecidas com a query
    # que ainda não foram descritas, e o Claude descreve só essas. A descrição
    # é salva (cache), então buscas futuras dessas imagens já são instantâneas.
    if CLAUDE_OK:
        candidatas_sem_desc = [
            i for i, f in enumerate(rows)
            if f["tipo"] in _EXT_IMG and not (f["descricao_ia"] or "").strip()
            and clip_sims[i] > 0.15  # só as minimamente parecidas visualmente
        ]
        # Ordena por similaridade visual e pega as 5 melhores
        candidatas_sem_desc.sort(key=lambda idx: clip_sims[idx], reverse=True)
        for i in candidatas_sem_desc[:5]:
            f = rows[i]
            desc_nova = _descrever_imagem_on_demand(f["caminho"], f["nome"])
            if desc_nova:
                # Atualiza em memória (pra esta busca) e salva no banco (cache).
                rows[i]["descricao_ia"] = desc_nova
                _salvar_descricao_e_embedding(uid, f["caminho"], desc_nova)
                # Recalcula SBERT e BM25 desta imagem agora que ela tem descrição.
                if SBERT_OK and SKLEARN_OK:
                    emb_nova = _gerar_embedding(_texto_para_embedding(desc_nova))
                    if emb_nova is not None and query_emb is not None:
                        import numpy as np
                        a = np.array([emb_nova]); b = np.array([query_emb])
                        sbert_sims[i] = max(0.0, float(cosine_similarity(a, b)[0][0]))
                corpus_tokens[i] = _tokenizar((desc_nova or "") + " " + (f["nome"] or ""))
        # BM25 depende do corpus inteiro — recalcula se alguma imagem foi descrita
        if candidatas_sem_desc:
            bm25_sims = _bm25_scores(corpus_tokens, q["palavras"])

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
        for f, s_sbert, s_bm25, s_clip, s_visual in zip(
                rows, sbert_sims, bm25_sims, clip_sims, clip_norm):
            desc_local      = (f["descricao_ia"] or "").strip()
            desc_norm_local = _normalizar(desc_local)
            tem_texto     = s_sbert >= threshold_sbert
            tem_visual    = (f["tipo"] in _EXT_IMG and CLIP_OK and s_clip >= 0.25)
            tem_keyword   = s_bm25 >= 0.5 and bool(q["palavras_set"])
            match_literal = any(w in desc_norm_local for w in palavras_literais)
            if not (tem_texto or tem_visual or tem_keyword or match_literal):
                continue

            eh_imagem_clip = f["tipo"] in _EXT_IMG and CLIP_OK and s_clip > 0
            if eh_imagem_clip and desc_local:
                blended = W_SBERT_IMG * s_sbert + W_BM25_IMG * s_bm25 + W_CLIP_IMG * s_visual
            elif eh_imagem_clip:
                # Imagem ainda sem descrição (indexada só com CLIP): não faz
                # sentido cobrar dela os pesos de texto que ela não tem como
                # ganhar. O sinal visual responde sozinho, mas com teto, pra
                # não passar na frente de um acerto textual bem descrito.
                blended = min(0.70, 0.85 * s_visual)
            else:
                blended = W_SBERT_DOC * s_sbert + W_BM25_DOC * s_bm25

            desc      = f["descricao_ia"] or ""
            desc_norm = _normalizar(desc)
            nome_norm = _normalizar(f["nome"])
            score = _ajustar_score(float(blended), q, desc_norm, nome_norm)
            if score is None:
                continue
            out.append((f, desc, score, float(s_sbert)))
        return out

    candidatos = _filtrar_e_pontuar(0.35)
    if not candidatos:
        candidatos = _filtrar_e_pontuar(0.30)

    results = []
    for f, desc, score, s_sbert in candidatos:
        results.append({
            "id": f["id"], "nome": f["nome"], "caminho": f["caminho"],
            "tipo": f["tipo"], "descricao_ia": desc, "conteudo": desc,
            "trecho": _trecho(desc, query),
            "data": f["data_adicionado"].isoformat() if f["data_adicionado"] else "",
            "favorito": bool(f["favorito"]),
            "score": round(score, 4),
            "_sbert": round(s_sbert, 4),   # usado pelo rerank pra proteger hits semânticos fortes
        })

    results.sort(key=lambda x: x["score"], reverse=True)

    if results:
        # Re-rank com Claude: juiz semântico que entende diferenças finas
        # (gato ≠ cachorro) e descarta resultados parecidos-mas-errados.
        # Se a API falhar, mantém a ordem do motor (degrada gracioso).
        results = _rerank_com_claude(query, results, topk=15)
        # Corte final: > 0.25 descarta o "ruído de fundo" (itens fracos, ou os que
        # o Claude marcou como não-correspondentes). Busca sem match real volta vazia.
        results = [r for r in results if r["score"] > 0.25]
        # Remove o campo interno _sbert (não precisa ir pro frontend)
        for r in results:
            r.pop("_sbert", None)

    # Filtro avançado de tamanho (lido do disco — não está no banco).
    # tam_min / tam_max em MB. Aplicado no fim pra não pesar a query.
    tam_min = avancado.get("tam_min")
    tam_max = avancado.get("tam_max")
    if tam_min is not None or tam_max is not None:
        def _dentro_do_tamanho(r):
            try:
                mb = os.path.getsize(r["caminho"]) / (1024 * 1024)
            except OSError:
                return False  # arquivo sumiu do disco
            if tam_min is not None and mb < float(tam_min):
                return False
            if tam_max is not None and mb > float(tam_max):
                return False
            return True
        results = [r for r in results if _dentro_do_tamanho(r)]

    tempo = round(time.time() - t0, 3)
    return jsonify({"resultados": results[:60], "tempo": tempo})


# ──────────────────────────────────────────────────────────────────────────────
# Busca por imagem (similaridade visual via CLIP)
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/search_by_image", methods=["POST"])
def api_search_by_image():
    """
    Busca imagens visualmente parecidas usando o embedding CLIP.
    Aceita no corpo JSON (um ou outro):
      - data_url: imagem em base64 (upload do navegador)
      - file_id:  id de um arquivo já indexado (usa o embedding_clip salvo)
    """
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    if not CLIP_OK:
        return jsonify({"erro": "Busca por imagem indisponível (modelo visual desligado). "
                                "Reinicie o servidor com conexão à internet na primeira vez."})

    data = request.get_json(force=True) or {}
    file_id = data.get("file_id")
    data_url = data.get("data_url")

    import numpy as np
    query_vec = None

    if file_id:
        # Reusa o embedding_clip já calculado do arquivo indexado
        conn = get_db()
        row = conn.execute(
            "SELECT embedding_clip FROM files WHERE id = %s AND user_id = %s",
            (file_id, uid)
        ).fetchone()
        conn.close()
        if not row or row["embedding_clip"] is None:
            return jsonify({"erro": "Essa imagem ainda não tem dados visuais. "
                                    "Rode 'Re-analisar' para gerá-los."})
        # pgvector devolve um objeto Vector (não iterável); converte pra float
        # puro (psycopg2 não adapta numpy.float32/Vector na query de volta)
        query_vec = _vec_to_list(row["embedding_clip"])

    elif data_url:
        # Decodifica base64 → arquivo temporário → embedding CLIP → apaga
        import base64, tempfile
        try:
            cabecalho, _, b64 = data_url.partition(",")
            raw = base64.b64decode(b64 or cabecalho)
        except Exception:
            return jsonify({"erro": "Imagem inválida."})
        if len(raw) > 20 * 1024 * 1024:
            return jsonify({"erro": "Imagem muito grande (máx. 20 MB)."})

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as tmp:
                tmp.write(raw)
                tmp_path = tmp.name
            query_vec = _gerar_embedding_clip_imagem(tmp_path)
        finally:
            if tmp_path and os.path.isfile(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        if query_vec is None:
            return jsonify({"erro": "Não foi possível processar essa imagem."})
    else:
        return jsonify({"error": "Envie data_url ou file_id."}), 400

    t0 = time.time()

    conn = get_db()
    rows = conn.execute(
        """
        SELECT id, nome, caminho, tipo, descricao_ia, data_adicionado, favorito,
               1 - (embedding_clip <=> %s::vector) AS score
        FROM files
        WHERE user_id = %s AND processado = 1 AND embedding_clip IS NOT NULL
          AND tipo = ANY(%s)
          AND (%s::int IS NULL OR id != %s)
        ORDER BY embedding_clip <=> %s::vector
        LIMIT 40
        """,
        (query_vec, uid, list(_EXT_IMG), file_id, file_id, query_vec)
    ).fetchall()
    conn.close()

    # Corte de score: CLIP cosine de imagens parecidas costuma ficar alto.
    # 0.55 filtra ruído sem cortar resultados legítimos (calibrável).
    CORTE_VISUAL = 0.55
    resultados = []
    for r in rows:
        score = float(r["score"])
        if score < CORTE_VISUAL:
            continue
        desc = r["descricao_ia"] or ""
        resultados.append({
            "id": r["id"], "nome": r["nome"], "caminho": r["caminho"],
            "tipo": r["tipo"], "descricao_ia": desc, "conteudo": desc,
            "trecho": desc[:240], "data": r["data_adicionado"].isoformat() if r["data_adicionado"] else "",
            "favorito": bool(r["favorito"]), "score": round(score, 4),
        })

    return jsonify({"resultados": resultados, "tempo": round(time.time() - t0, 3),
                    "modo": "imagem"})


# ──────────────────────────────────────────────────────────────────────────────
# Estatísticas do acervo (para o perfil)
# ──────────────────────────────────────────────────────────────────────────────

# Categorias temáticas: palavra-chave (normalizada) -> categoria.
# Usadas para classificar cada arquivo a partir da descrição da IA.
_CATEGORIAS_STATS = {
    "pessoas": ["pessoa", "pessoas", "homem", "homens", "mulher", "mulheres",
                "menino", "menina", "crianca", "bebe", "rosto", "gente", "humano"],
    "animais": ["cachorro", "cao", "gato", "animal", "animais", "passaro",
                "cavalo", "pet", "bicho", "ave", "peixe"],
    "comida":  ["comida", "prato", "refeicao", "alimento", "bebida", "fruta",
                "lanche", "almoco", "janta", "restaurante", "kebab", "pizza"],
    "natureza":["paisagem", "natureza", "praia", "montanha", "floresta", "mar",
                "ceu", "arvore", "jardim", "parque", "campo", "flor", "po do sol", "por do sol"],
    "urbano":  ["cidade", "rua", "predio", "carro", "veiculo", "moto", "edificio",
                "loja", "trafego", "urbano"],
    "desenhos":["desenho", "ilustracao", "cartoon", "anime", "manga", "quadrinho",
                "pintura", "pixel art", "arte digital", "esboco", "caricatura",
                "logotipo", "meme", "render 3d", "animacao"],
}


@app.route("/api/stats")
def api_stats():
    """Estatísticas do acervo do usuário para exibir no perfil."""
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    conn = get_db()
    rows = conn.execute(
        "SELECT tipo, descricao_ia FROM files WHERE user_id = %s AND processado = 1",
        (uid,)
    ).fetchall()
    total_pastas = conn.execute(
        "SELECT COUNT(*) AS n FROM folders WHERE user_id = %s", (uid,)
    ).fetchone()["n"]
    conn.close()

    total = len(rows)
    # Contagem por tipo de arquivo (imagem / documento / mídia)
    por_formato = {"imagem": 0, "documento": 0, "midia": 0}
    # Contagem por categoria temática (uma imagem pode contar em várias)
    por_categoria = {k: 0 for k in _CATEGORIAS_STATS}

    for r in rows:
        ext = (r["tipo"] or "").lower()
        if ext in _EXT_IMG:
            por_formato["imagem"] += 1
        elif ext in _EXT_VID or ext in _EXT_AUD:
            por_formato["midia"] += 1
        else:
            por_formato["documento"] += 1

        desc_norm = _normalizar(r["descricao_ia"] or "")
        # Remove linhas de negação ("pessoas: nenhuma", "animais: nenhum")
        # pra não contar a palavra-chave do rótulo quando o campo está vazio.
        linhas_validas = []
        for linha in desc_norm.splitlines():
            if any(neg in linha for neg in ("nenhum", "nenhuma", "nao ha", "ausente")):
                continue
            linhas_validas.append(linha)
        desc_filtrada = " ".join(linhas_validas)

        for cat, palavras in _CATEGORIAS_STATS.items():
            # Palavra inteira, não substring: 'cao' casava dentro de 'locacao' e
            # 'manutencao', e 'mar' dentro de 'camara' — o painel do perfil
            # exibia animais e natureza em acervos que só tinham documentos.
            if _contem_termo(desc_filtrada, palavras):
                por_categoria[cat] += 1

    # Só categorias com pelo menos 1, ordenadas da maior pra menor
    categorias = sorted(
        [{"categoria": k, "total": v} for k, v in por_categoria.items() if v > 0],
        key=lambda x: x["total"], reverse=True
    )

    return jsonify({
        "total_arquivos": total,
        "total_pastas": total_pastas,
        "por_formato": por_formato,
        "por_categoria": categorias,
    })


_NEGACOES = ("nenhum", "nenhuma", "nao ha", "ausente", "n/a", "sem ")

# Palavras-chave por categoria temática para campos descritivos
# (usadas SÓ nos campos certos, não na descrição inteira — evita falso-positivo
# tipo 'cachorro-quente' caindo em animais, ou 'bebida' numa festa caindo em comida)
_KW_COMIDA = ["comida", "refeicao", "alimento", "almoco", "janta", "lanche",
              "prato de comida", "arroz", "kebab", "pizza", "hamburguer", "sushi",
              "fruta", "salada", "sobremesa", "restaurante"]
_KW_NATUREZA = ["paisagem", "praia", "montanha", "floresta", "mata", "oceano",
                "cachoeira", "arvore", "arvores", "jardim", "campo", "flor",
                "por do sol", "natureza", "lago", "rio"]
_KW_DESENHO = ["desenho", "desenhado", "desenhada", "ilustracao", "ilustrado",
               "cartoon", "anime", "manga", "quadrinho", "hq", "caricatura",
               "pintura", "aquarela", "pixel art", "arte digital", "esboco",
               "render 3d", "cgi", "vetorial", "logotipo", "icone", "meme",
               "captura de tela", "personagem", "animacao"]
_KW_URBANO = ["cidade", "rua", "predio", "edificio", "avenida", "metropole",
              "arranha-ceu", "carro", "veiculo", "moto", "transito", "urbano"]


def _campo_descricao(desc_norm: str, nome_campo: str) -> str:
    """Extrai o conteúdo de um campo da descrição (ex: 'pessoas', 'animais').
    Retorna '' se o campo não existe ou está negado (Nenhum/Nenhuma)."""
    for linha in desc_norm.splitlines():
        linha = linha.strip().lstrip("-• ").strip()
        if ":" not in linha:
            continue
        campo, _, valor = linha.partition(":")
        if campo.strip() == nome_campo:
            valor = valor.strip()
            # Campo negado conta como vazio
            if not valor or any(neg in valor for neg in _NEGACOES):
                return ""
            return valor
    return ""


def _categorias_do_arquivo(descricao_ia: str) -> list[str]:
    """
    Categoriza um arquivo usando os CAMPOS ESTRUTURADOS da descrição,
    não busca solta. Isso evita os falsos-positivos:
      - prato com 'cachorro-quente' caindo em Animais
      - festa com 'bebida' caindo em Comida
    """
    desc_norm = _normalizar(descricao_ia or "")
    cats = []

    # Pessoas: SÓ se o campo "Pessoas" tiver conteúdo real (não negado)
    if _campo_descricao(desc_norm, "pessoas"):
        cats.append("pessoas")

    # Animais: SÓ se o campo "Animais" tiver conteúdo real.
    # Ignora "cachorro-quente"/"cachorro quente" (é comida, não animal).
    animais_val = _campo_descricao(desc_norm, "animais")
    if animais_val:
        sem_hotdog = animais_val.replace("cachorro-quente", "").replace("cachorro quente", "")
        if sem_hotdog.strip():
            cats.append("animais")

    # Comida / Natureza / Urbano: por palavra-chave nos campos descritivos
    # (o que e / objetos / ambiente / acoes / tags), não em pessoas/animais.
    contexto = " ".join(
        _campo_descricao(desc_norm, c) or ""
        for c in ("estilo", "o que e", "objetos", "ambiente", "acoes", "tags")
    )
    # Tokeniza por palavra inteira pra evitar substring (ex: 'cidade' em
    # 'feli-cidade', 'mar' em 'marca'). Mantém termos compostos via checagem
    # separada de frase.
    tokens = set(re.findall(r"[a-z]+", contexto))

    def _bate(kw_list):
        for kw in kw_list:
            if " " in kw or "-" in kw:
                # termo composto: procura a frase literal
                if kw in contexto:
                    return True
            elif kw in tokens:
                return True
        return False

    if _bate(_KW_COMIDA):
        cats.append("comida")
    if _bate(_KW_NATUREZA):
        cats.append("natureza")
    if _bate(_KW_URBANO):
        cats.append("urbano")

    # Desenhos: decidido pelo campo "Estilo", que é onde o Claude declara o
    # meio da imagem. Só cai aqui se o estilo NÃO for fotografia.
    estilo = _campo_descricao(desc_norm, "estilo")
    if _contem_termo(estilo, _KW_DESENHO):
        cats.append("desenhos")

    return cats


@app.route("/api/gallery")
def api_gallery():
    """
    Galeria de imagens agrupadas por categoria temática, para a home.
    Cada imagem pode aparecer em mais de um grupo. Retorna também um grupo
    'outras' para imagens que não casaram com nenhuma categoria.
    """
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    conn = get_db()
    rows = conn.execute(
        "SELECT id, nome, caminho, tipo, descricao_ia, data_adicionado, favorito "
        "FROM files WHERE user_id = %s AND processado = 1 AND tipo = ANY(%s) "
        "ORDER BY data_adicionado DESC",
        (uid, list(_EXT_IMG))
    ).fetchall()
    conn.close()

    grupos = {k: [] for k in _CATEGORIAS_STATS}
    grupos["outras"] = []

    for r in rows:
        item = {
            "id": r["id"], "nome": r["nome"], "caminho": r["caminho"],
            "tipo": r["tipo"], "descricao_ia": r["descricao_ia"] or "",
            "conteudo": r["descricao_ia"] or "",
            "trecho": (r["descricao_ia"] or "")[:200],
            "data": r["data_adicionado"].isoformat() if r["data_adicionado"] else "",
            "favorito": bool(r["favorito"]), "score": 1.0,
        }
        cats = _categorias_do_arquivo(r["descricao_ia"])
        if cats:
            for c in cats:
                grupos[c].append(item)
        else:
            grupos["outras"].append(item)

    # Só devolve grupos não-vazios, na ordem definida
    ordem = list(_CATEGORIAS_STATS.keys()) + ["outras"]
    resultado = [{"categoria": c, "total": len(grupos[c]), "itens": grupos[c]}
                 for c in ordem if grupos[c]]

    return jsonify({"grupos": resultado, "total_imagens": len(rows)})


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
    # Inverte dentro do próprio UPDATE, em vez de ler e escrever em dois passos:
    #   - dois cliques rápidos no coração liam o mesmo valor e gravavam o mesmo
    #     resultado, deixando o favorito "preso";
    #   - a coluna aceita NULL, e o `1 - int(None)` do jeito antigo virava 500.
    row = conn.execute(
        "UPDATE files SET favorito = CASE WHEN COALESCE(favorito, 0) = 1 THEN 0 ELSE 1 END "
        "WHERE id = %s AND user_id = %s RETURNING favorito",
        (file_id, uid)
    ).fetchone()

    if not row:
        conn.close()
        return jsonify({"error": "Arquivo não encontrado."}), 404

    conn.commit()
    conn.close()

    return jsonify({"status": "sucesso", "favorito": bool(row["favorito"])})


# ──────────────────────────────────────────────────────────────────────────────
# Coleções (playlists de arquivos)
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/collections", methods=["GET", "POST"])
def api_collections():
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    if request.method == "GET":
        # Lista coleções com contagem e até 4 imagens de capa (mosaico)
        conn = get_db()
        rows = conn.execute(
            """
            SELECT c.id, c.nome, c.criado_em, c.pasta_vinculada, c.modo_sync,
                   COUNT(cf.file_id) AS total
            FROM collections c
            LEFT JOIN collection_files cf ON cf.collection_id = c.id
            WHERE c.user_id = %s
            GROUP BY c.id, c.nome, c.criado_em, c.pasta_vinculada, c.modo_sync
            ORDER BY c.criado_em DESC
            """,
            (uid,)
        ).fetchall()

        colecoes = []
        for r in rows:
            # Pega até 4 imagens da coleção pra montar a capa em mosaico
            capas = conn.execute(
                """
                SELECT f.caminho
                FROM collection_files cf
                JOIN files f ON f.id = cf.file_id
                WHERE cf.collection_id = %s AND f.tipo = ANY(%s)
                ORDER BY cf.adicionado_em DESC
                LIMIT 4
                """,
                (r["id"], list(_EXT_IMG))
            ).fetchall()
            colecoes.append({
                "id": r["id"], "nome": r["nome"], "total": r["total"],
                "criado_em": r["criado_em"].isoformat() if r["criado_em"] else "",
                "capas": [c["caminho"] for c in capas],
                "pasta_vinculada": r["pasta_vinculada"],
                "modo_sync": r["modo_sync"] or "manual",
            })
        conn.close()
        return jsonify({"colecoes": colecoes})

    # POST — criar coleção
    data = request.get_json(force=True) or {}
    nome = (data.get("nome") or "").strip()
    if not nome:
        return jsonify({"error": "Nome da coleção é obrigatório."}), 400

    conn = get_db()
    try:
        row = conn.execute(
            "INSERT INTO collections (user_id, nome) VALUES (%s, %s) RETURNING id",
            (uid, nome)
        ).fetchone()
        conn.commit()
        return jsonify({"status": "ok", "id": row["id"], "nome": nome,
                        "pasta_vinculada": None, "modo_sync": "manual"})
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return jsonify({"error": "Você já tem uma coleção com esse nome."}), 409
    finally:
        conn.close()


_MODOS_SYNC = {"auto", "perguntar", "manual"}


def _ultima_pasta_exportacao(uid) -> str:
    """
    Último diretório de exportação do usuário, se ainda existir.

    Devolve "" quando a pasta sumiu (HD desconectado, pasta apagada) — o
    seletor então abre no padrão do sistema, sem erro. Preferência que aponta
    para o vazio não pode virar obstáculo.
    """
    if not uid:
        return ""
    try:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT config_json FROM users WHERE id = %s", (uid,)
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        return ""     # sem banco, o seletor ainda tem de abrir

    cfg = _safe_json_loads(row["config_json"] if row else None, {}) or {}
    caminho = (cfg.get("ultima_pasta_exportacao") or "").strip()
    return caminho if caminho and os.path.isdir(caminho) else ""


def _lembrar_pasta_exportacao(uid, destino: str) -> None:
    """Guarda a pasta-mãe escolhida. Falha aqui não pode quebrar a exportação."""
    if not uid or not destino:
        return
    try:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT config_json FROM users WHERE id = %s", (uid,)
            ).fetchone()
            cfg = _safe_json_loads(row["config_json"] if row else None, {}) or {}
            if cfg.get("ultima_pasta_exportacao") == destino:
                return                      # nada mudou, evita escrita à toa
            cfg["ultima_pasta_exportacao"] = destino
            conn.execute("UPDATE users SET config_json = %s WHERE id = %s",
                         (json.dumps(cfg), uid))
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        print(f"[EXPORT] não foi possível lembrar a pasta: {type(exc).__name__}: {exc}")


def _registrar_pasta(conn, col_id: int, uid: int, caminho: str) -> None:
    """
    Guarda uma pasta gerada para a coleção, sem duplicar.

    Toda pasta que o app cria passa por aqui. É esse registro que sustenta três
    coisas: abrir a pasta depois, sincronizar novas imagens nela, e — ao
    excluir a coleção — listar o que existe no disco para o usuário decidir.
    Sem ele, uma exportação vira um retrato órfão (era o caso antes).
    """
    conn.execute(
        "INSERT INTO collection_folders (collection_id, user_id, caminho) "
        "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
        (col_id, uid, os.path.normpath(caminho)),
    )


def _pastas_da_colecao(conn, col_id: int, uid: int):
    """Caminhos já gerados para a coleção, do mais recente para o mais antigo."""
    return [r["caminho"] for r in conn.execute(
        "SELECT caminho FROM collection_folders "
        "WHERE collection_id = %s AND user_id = %s ORDER BY criado_em DESC",
        (col_id, uid),
    ).fetchall()]


def _pastas_que_recebem(conn, col_id: int, uid: int):
    """
    Pastas que devem receber as novas imagens da coleção.

    É um conjunto, não um valor: o usuário pode espelhar a coleção em duas
    pastas ao mesmo tempo, ou em nenhuma. Lista vazia significa "não enviar",
    sem perder o registro das pastas já criadas.
    """
    return [r["caminho"] for r in conn.execute(
        "SELECT caminho FROM collection_folders "
        "WHERE collection_id = %s AND user_id = %s AND recebe = TRUE "
        "ORDER BY criado_em",
        (col_id, uid),
    ).fetchall()]


def _definir_pastas_que_recebem(conn, col_id: int, uid: int, caminhos) -> list:
    """
    Troca o conjunto de destinos. Só aceita pasta já registrada para a coleção.

    Mantém `collections.pasta_vinculada` apontando para a primeira do conjunto
    (ou NULL): as telas antigas e as mensagens de erro ainda leem esse campo, e
    deixá-lo divergir do conjunto criaria duas verdades sobre o mesmo assunto.
    """
    registradas = {os.path.normpath(c) for c in _pastas_da_colecao(conn, col_id, uid)}
    alvos = [c for c in (os.path.normpath(str(x).strip()) for x in caminhos)
             if c in registradas]

    conn.execute(
        "UPDATE collection_folders SET recebe = FALSE "
        "WHERE collection_id = %s AND user_id = %s", (col_id, uid))
    if alvos:
        conn.execute(
            "UPDATE collection_folders SET recebe = TRUE "
            "WHERE collection_id = %s AND user_id = %s AND caminho = ANY(%s)",
            (col_id, uid, alvos))

    conn.execute(
        "UPDATE collections SET pasta_vinculada = %s WHERE id = %s AND user_id = %s",
        (alvos[0] if alvos else None, col_id, uid))
    return alvos


def _atualizar_colecao(col_id: int, uid: int):
    """
    PATCH da coleção: nome, pasta vinculada e modo de sincronia.

    Só toca os campos presentes no corpo — mandar `{"modo_sync": "auto"}` não
    apaga a pasta já vinculada. Enviar `pasta_vinculada: null` desvincula de
    propósito e devolve a coleção ao modo manual.
    """
    data = request.get_json(force=True) or {}
    campos, valores = [], []

    if "nome" in data:
        nome = (data.get("nome") or "").strip()
        if not nome:
            return jsonify({"error": "Nome da coleção é obrigatório."}), 400
        campos.append("nome = %s")
        valores.append(nome)

    # `criar_pasta_em` é o caminho normal: o usuário escolhe a pasta-mãe e o
    # backend cria a subpasta da coleção dentro dela — mesma sanitização e
    # mesma resolução de colisão da exportação, para não haver duas lógicas.
    pasta_criada = None
    if data.get("criar_pasta_em"):
        destino = os.path.normpath(str(data["criar_pasta_em"]).strip())
        if not os.path.isdir(destino):
            return jsonify({"error": "A pasta escolhida não existe mais."}), 400

        conn_nome = get_db()
        try:
            row = conn_nome.execute(
                "SELECT nome FROM collections WHERE id = %s AND user_id = %s",
                (col_id, uid),
            ).fetchone()
        finally:
            conn_nome.close()
        if not row:
            return jsonify({"error": "Coleção não encontrada."}), 404

        alvo = _pasta_disponivel(destino, _sanitizar_nome(row["nome"],
                                                          padrao=f"colecao_{col_id}"))
        try:
            os.makedirs(alvo)
        except PermissionError:
            return jsonify({"error": f"Não foi possível gravar em {destino}. "
                                     "Escolha outra pasta ou verifique as permissões."}), 403
        except OSError as exc:
            print(f"[VINCULO] erro ao criar '{alvo}': {type(exc).__name__}: {exc}")
            return jsonify({"error": f"Não foi possível criar a pasta em {destino}. "
                                     "Escolha outra pasta."}), 400

        pasta_criada = alvo
        _lembrar_pasta_exportacao(uid, destino)
        campos.append("pasta_vinculada = %s")
        valores.append(alvo)

        conn_reg = get_db()
        try:
            _registrar_pasta(conn_reg, col_id, uid, alvo)
            conn_reg.commit()
        finally:
            conn_reg.close()

    elif "pasta_vinculada" in data:
        pasta = data.get("pasta_vinculada")
        if pasta is None or not str(pasta).strip():
            # Desvincular: sem pasta, sincronizar automaticamente não faz sentido
            campos.append("pasta_vinculada = NULL")
            campos.append("modo_sync = 'manual'")
        else:
            pasta = os.path.normpath(str(pasta).strip())
            if not os.path.isdir(pasta):
                return jsonify({"error": "A pasta escolhida não existe mais."}), 400
            campos.append("pasta_vinculada = %s")
            valores.append(pasta)

    if "modo_sync" in data:
        modo = (data.get("modo_sync") or "").strip()
        if modo not in _MODOS_SYNC:
            return jsonify({"error": "Modo de sincronia inválido."}), 400
        campos.append("modo_sync = %s")
        valores.append(modo)

    # Conjunto de pastas que recebem as novas imagens. Lista vazia é escolha
    # válida: para de enviar sem perder o registro das pastas já criadas.
    novos_destinos = None
    if "pastas_que_recebem" in data:
        bruto = data.get("pastas_que_recebem")
        if not isinstance(bruto, list):
            return jsonify({"error": "pastas_que_recebem deve ser uma lista."}), 400
        novos_destinos = bruto

    if not campos and novos_destinos is None:
        return jsonify({"error": "Nada para atualizar."}), 400

    conn = get_db()
    try:
        dono = conn.execute(
            "SELECT id FROM collections WHERE id = %s AND user_id = %s", (col_id, uid)
        ).fetchone()
        if not dono:
            return jsonify({"error": "Coleção não encontrada."}), 404

        try:
            if campos:
                valores.extend([col_id, uid])
                conn.execute(
                    f"UPDATE collections SET {', '.join(campos)} "
                    "WHERE id = %s AND user_id = %s",
                    tuple(valores),
                )
            # Pasta recém-criada por `criar_pasta_em` já entra como destino —
            # foi para isso que o usuário a criou.
            if pasta_criada and novos_destinos is None:
                atuais = _pastas_que_recebem(conn, col_id, uid)
                _definir_pastas_que_recebem(conn, col_id, uid, atuais + [pasta_criada])
            elif novos_destinos is not None:
                _definir_pastas_que_recebem(conn, col_id, uid, novos_destinos)
            conn.commit()
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            return jsonify({"error": "Você já tem uma coleção com esse nome."}), 409

        atual = conn.execute(
            "SELECT id, nome, pasta_vinculada, modo_sync FROM collections "
            "WHERE id = %s AND user_id = %s",
            (col_id, uid),
        ).fetchone()
        destinos = _pastas_que_recebem(conn, col_id, uid)
    finally:
        conn.close()

    return jsonify({
        "status": "ok",
        "id": atual["id"],
        "nome": atual["nome"],
        "pasta_vinculada": atual["pasta_vinculada"],
        "pastas_que_recebem": destinos,
        "modo_sync": atual["modo_sync"],
    })


@app.route("/api/collections/<int:col_id>", methods=["GET", "DELETE", "PATCH"])
def api_collection_detail(col_id):
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    if request.method == "PATCH":
        return _atualizar_colecao(col_id, uid)

    conn = get_db()
    # Confirma que a coleção é do usuário
    dono = conn.execute(
        "SELECT id FROM collections WHERE id = %s AND user_id = %s", (col_id, uid)
    ).fetchone()
    if not dono:
        conn.close()
        return jsonify({"error": "Coleção não encontrada."}), 404

    if request.method == "DELETE":
        conn.execute("DELETE FROM collections WHERE id = %s AND user_id = %s", (col_id, uid))
        conn.commit()
        conn.close()
        return jsonify({"status": "ok"})

    # GET — arquivos da coleção (formato igual ao de busca/favoritos)
    rows = conn.execute(
        """
        SELECT f.id, f.nome, f.caminho, f.tipo, f.descricao_ia,
               f.data_adicionado, f.favorito
        FROM collection_files cf
        JOIN files f ON f.id = cf.file_id
        WHERE cf.collection_id = %s
        ORDER BY cf.adicionado_em DESC
        """,
        (col_id,)
    ).fetchall()
    conn.close()

    resultados = [
        {"id": r["id"], "nome": r["nome"], "caminho": r["caminho"],
         "tipo": r["tipo"], "descricao_ia": r["descricao_ia"] or "",
         "conteudo": r["descricao_ia"] or "",
         "trecho": (r["descricao_ia"] or "")[:200],
         "data": r["data_adicionado"].isoformat() if r["data_adicionado"] else "",
         "favorito": bool(r["favorito"]), "score": 1.0}
        for r in rows
    ]
    return jsonify({"resultados": resultados})


@app.route("/api/collections/<int:col_id>/files", methods=["POST", "DELETE"])
def api_collection_files(col_id):
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    data = request.get_json(force=True) or {}
    # Aceita "file_id" (um arquivo, formato original) ou "file_ids" (lote).
    # O singular continua valendo para não quebrar quem já chama assim.
    if data.get("file_ids") is not None:
        brutos = data.get("file_ids")
        if not isinstance(brutos, list):
            return jsonify({"error": "file_ids deve ser uma lista."}), 400
    else:
        brutos = [data.get("file_id")] if data.get("file_id") else []

    # Normaliza para inteiros únicos, preservando a ordem de chegada
    file_ids, vistos = [], set()
    for b in brutos:
        try:
            n = int(b)
        except (TypeError, ValueError):
            return jsonify({"error": "Identificador de arquivo inválido."}), 400
        if n not in vistos:
            vistos.add(n)
            file_ids.append(n)

    if not file_ids:
        return jsonify({"error": "file_id é obrigatório."}), 400

    conn = get_db()
    try:
        # Confirma posse da coleção E de todos os arquivos
        dono = conn.execute(
            "SELECT id FROM collections WHERE id = %s AND user_id = %s", (col_id, uid)
        ).fetchone()
        if not dono:
            return jsonify({"error": "Coleção ou arquivo não encontrado."}), 404

        proprios = conn.execute(
            "SELECT id FROM files WHERE id = ANY(%s) AND user_id = %s", (file_ids, uid)
        ).fetchall()
        ids_validos = [r["id"] for r in proprios]
        if not ids_validos:
            return jsonify({"error": "Coleção ou arquivo não encontrado."}), 404

        if request.method == "DELETE":
            # Os NOMES vão na resposta porque, depois do DELETE, não há mais
            # como o frontend saber que arquivo era — e é pelo nome que a
            # cópia é localizada na pasta espelho.
            nomes = [r["nome"] for r in conn.execute(
                "SELECT nome FROM files WHERE id = ANY(%s) AND user_id = %s",
                (ids_validos, uid)
            ).fetchall()]

            conn.execute(
                "DELETE FROM collection_files WHERE collection_id = %s AND file_id = ANY(%s)",
                (col_id, ids_validos)
            )
            conn.commit()

            vinc = conn.execute(
                "SELECT modo_sync FROM collections WHERE id = %s", (col_id,)
            ).fetchone()
            return jsonify({"status": "ok", "acao": "removido",
                            "removidos": len(ids_validos),
                            "nomes_removidos": nomes,
                            "modo_sync": (dict(vinc).get("modo_sync") if vinc else None) or "manual",
                            "pastas_que_recebem": _pastas_que_recebem(conn, col_id, uid)})

        # POST — adicionar. O ON CONFLICT deixa o banco garantir a ausência de
        # duplicata; o RETURNING diz quantas linhas realmente entraram, para a
        # interface poder dizer "3 adicionadas, 2 já estavam".
        inseridos = conn.execute(
            "INSERT INTO collection_files (collection_id, file_id) "
            "SELECT %s, unnest(%s::int[]) "
            "ON CONFLICT DO NOTHING RETURNING file_id",
            (col_id, ids_validos)
        ).fetchall()
        conn.commit()
        n_add = len(inseridos)

        # Devolve o estado de sincronia junto: sem isto o frontend precisaria
        # de um GET extra a cada adição só para saber se deve copiar.
        vinculo = conn.execute(
            "SELECT pasta_vinculada, modo_sync FROM collections WHERE id = %s",
            (col_id,)
        ).fetchone()

        # Acesso tolerante de propósito: init_db() apenas registra falhas de DDL
        # em vez de abortar, então o app pode estar rodando sem as colunas de
        # vínculo. Sem isto, uma migração falha derrubaria TODA adição a
        # coleção com HTTP 500 — em vez de só desativar a sincronia.
        vinc = dict(vinculo) if vinculo else {}
        return jsonify({
            "status": "ok",
            "acao": "adicionado",
            "adicionados": n_add,
            "ja_existiam": len(ids_validos) - n_add,
            "ids_adicionados": [r["file_id"] for r in inseridos],
            "pasta_vinculada": vinc.get("pasta_vinculada"),
            "modo_sync": vinc.get("modo_sync") or "manual",
        })
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# Exportação de coleção para uma pasta local
# ──────────────────────────────────────────────────────────────────────────────
# Exportar aqui é COPIAR arquivo local → pasta local: as imagens indexadas já
# estão no disco do usuário (files.caminho), e o backend roda na máquina dele.
# Não há download, não há URL, não há rede envolvida na cópia.
# Especificação: docs/features/12-colecoes-exportacao.md

_export_jobs = {}                  # job_id → estado do job
_export_lock = threading.Lock()

# Windows: caracteres proibidos em nome de arquivo/pasta e nomes reservados.
_CHARS_INVALIDOS = r'<>:"/\|?*'
_NOMES_RESERVADOS = (
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def _sanitizar_nome(nome: str, padrao: str = "sem_nome", limite: int = 120) -> str:
    """
    Converte um texto qualquer num nome válido de arquivo/pasta no Windows.

    Função pura: não toca o disco. As regras do Windows são as mais restritivas
    entre os sistemas suportados, então o resultado também é válido em Linux e
    macOS. Ver RF-038 a RF-040.
    """
    limpo = "".join(
        "_" if (c in _CHARS_INVALIDOS or ord(c) < 32) else c
        for c in (nome or "")
    )
    # Windows não aceita nome terminando em ponto ou espaço
    limpo = limpo.strip().rstrip(". ")

    # Nome reservado é inválido inclusive com extensão (CON.jpg)
    if limpo.split(".")[0].upper() in _NOMES_RESERVADOS:
        limpo = f"_{limpo}"

    if len(limpo) > limite:
        limpo = limpo[:limite].rstrip(". ")

    # Um nome que virou só separadores ("///:::" → "______") é tecnicamente
    # válido, mas não diz nada a quem for abrir a pasta. Sem nenhum caractere
    # alfanumérico sobrando, o padrão é mais útil (RF-039).
    if not any(c.isalnum() for c in limpo):
        return padrao

    return limpo


def _nome_disponivel(pasta: str, nome_arquivo: str) -> str:
    """
    Devolve um nome livre dentro de `pasta`, sufixando _1, _2… se preciso.

    Colisão é o caso comum, não a exceção: files tem UNIQUE(user_id, caminho),
    não UNIQUE(user_id, nome) — duas pastas monitoradas podem ter IMG_0001.jpg.
    Nunca sobrescreve (RF-042, RF-043).
    """
    base, ext = os.path.splitext(nome_arquivo)
    base = _sanitizar_nome(base, padrao="arquivo")
    ext = _sanitizar_nome(ext, padrao="")

    candidato = f"{base}{ext}"
    i = 1
    while os.path.exists(os.path.join(pasta, candidato)):
        candidato = f"{base}_{i}{ext}"
        i += 1
    return candidato


def _pasta_disponivel(destino: str, nome_pasta: str, sufixo: str = "") -> str:
    """
    Caminho de pasta ainda inexistente, preservando o nome da coleção.

    O nome da coleção é sempre o prefixo — é o que permite ao usuário
    reconhecer no Explorer de qual coleção veio a pasta, e ao sistema
    relacionar as duas. O que varia é o sufixo:

        "Natureza"            1ª exportação
        "Natureza_2"          2ª (sufixo automático)
        "Natureza_praia"      sufixo escolhido pelo usuário

    Colisão continua sendo tratada: se "Natureza_praia" já existir, tenta
    "Natureza_praia_2". Nunca sobrescreve nada (RF-041, RF-043).
    """
    if sufixo:
        base = f"{nome_pasta}_{_sanitizar_nome(sufixo, padrao='2')}"
        candidato = os.path.join(destino, base)
        if not os.path.exists(candidato):
            return candidato
        # Sufixo escolhido já em uso: numera a partir dele
        i = 2
        while os.path.exists(os.path.join(destino, f"{base}_{i}")):
            i += 1
        return os.path.join(destino, f"{base}_{i}")

    candidato = os.path.join(destino, nome_pasta)
    i = 2                       # a primeira é sem número; a próxima é _2
    while os.path.exists(candidato):
        candidato = os.path.join(destino, f"{nome_pasta}_{i}")
        i += 1
    return candidato


def _dentro_das_pastas(caminho: str, pastas_monitoradas) -> bool:
    """
    Mesma regra anti-path-traversal de /api/file (RF-045, RNF-015).

    Exige o separador no fim para 'C:\\foo' não casar com 'C:\\foobar'.
    """
    alvo = os.path.abspath(caminho).lower()
    for p in pastas_monitoradas:
        base = os.path.abspath(p).lower()
        if alvo == base or alvo.startswith(base + os.sep):
            return True
    return False


def _worker_exportacao(job_id: str, itens, destino_pasta: str):
    """Copia os arquivos da coleção, um a um, atualizando o progresso."""

    for item in itens:
        with _export_lock:
            job = _export_jobs.get(job_id)
            if not job or job["cancelar"]:
                break

        origem = item["caminho"]
        motivo = None
        try:
            if not item["autorizado"]:
                motivo = "fora_das_pastas"
            elif not os.path.isfile(origem):
                motivo = "nao_encontrado"
            else:
                alvo = os.path.join(destino_pasta, _nome_disponivel(destino_pasta, item["nome"]))
                shutil.copy2(origem, alvo)      # copy2 preserva timestamps (RF-046)
        except PermissionError:
            motivo = "sem_permissao"
        except OSError as exc:
            # ENOSPC (disco cheio) é fatal: continuar só produz mais falhas.
            if getattr(exc, "errno", None) == 28:
                with _export_lock:
                    j = _export_jobs.get(job_id)
                    if j:
                        j["estado"] = "erro"
                        j["erro"] = "disco_cheio"
                print(f"[EXPORT] disco cheio ao copiar '{origem}'")
                return
            motivo = "erro_leitura"
            print(f"[EXPORT] falha em '{origem}': {type(exc).__name__}: {exc}")

        with _export_lock:
            job = _export_jobs.get(job_id)
            if not job:
                return
            if motivo:
                job["falhas"].append({"nome": item["nome"], "motivo": motivo})
            else:
                job["copiados"] += 1

    with _export_lock:
        job = _export_jobs.get(job_id)
        if job and job["estado"] == "executando":
            job["estado"] = "cancelado" if job["cancelar"] else "concluido"


@app.route("/api/collections/<int:col_id>/export", methods=["POST"])
def api_collection_export(col_id):
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    data = request.get_json(force=True) or {}
    destino = (data.get("destino") or "").strip()
    if not destino:
        return jsonify({"error": "Escolha uma pasta de destino."}), 400

    destino = os.path.normpath(destino)
    if not os.path.isdir(destino):
        return jsonify({"error": "A pasta escolhida não existe mais."}), 400

    conn = get_db()
    try:
        col = conn.execute(
            "SELECT id, nome FROM collections WHERE id = %s AND user_id = %s",
            (col_id, uid)
        ).fetchone()
        if not col:
            return jsonify({"error": "Coleção não encontrada."}), 404

        arquivos = conn.execute(
            """
            SELECT f.nome, f.caminho
            FROM collection_files cf
            JOIN files f ON f.id = cf.file_id
            WHERE cf.collection_id = %s AND f.user_id = %s
            ORDER BY cf.adicionado_em DESC
            """,
            (col_id, uid)
        ).fetchall()

        pastas = [r["path"] for r in conn.execute(
            "SELECT path FROM folders WHERE user_id = %s", (uid,)
        ).fetchall()]
    finally:
        conn.close()

    if not arquivos:
        return jsonify({"error": "Esta coleção está vazia. "
                                 "Adicione imagens antes de exportar."}), 400

    # Uma exportação por coleção de cada vez (RF-057)
    with _export_lock:
        for j in _export_jobs.values():
            if (j["user_id"] == uid and j["collection_id"] == col_id
                    and j["estado"] == "executando"):
                return jsonify({"error": "Esta coleção já está sendo exportada."}), 409

    # Cria a pasta ANTES de começar: se não der, nada é copiado (RF-054)
    nome_pasta = _sanitizar_nome(col["nome"], padrao=f"colecao_{col_id}")
    pasta_final = _pasta_disponivel(destino, nome_pasta,
                                    sufixo=str(data.get("sufixo") or "").strip())
    try:
        os.makedirs(pasta_final)
    except PermissionError:
        return jsonify({"error": f"Não foi possível gravar em {destino}. "
                                 "Escolha outra pasta ou verifique as permissões."}), 403
    except OSError as exc:
        print(f"[EXPORT] erro ao criar '{pasta_final}': {type(exc).__name__}: {exc}")
        return jsonify({"error": f"Não foi possível criar a pasta da coleção em "
                                 f"{destino}. Escolha outra pasta."}), 400

    # Registra a pasta. Sem isto, exportar era um retrato sem memória: as
    # imagens adicionadas DEPOIS não tinham para onde ir, e o usuário só
    # descobria ao abrir a pasta e não achar as novas.
    #
    # O VÍNCULO é decisão à parte. Numa segunda exportação, quem escolhe qual
    # pasta recebe as próximas imagens é o usuário — assumir a mais recente
    # mudaria o destino sem ele pedir. `vincular` vem do frontend:
    #   ausente → só vincula se ainda não houver pasta vinculada
    #   true    → passa a apontar para esta
    #   false   → mantém o vínculo atual
    _lembrar_pasta_exportacao(uid, destino)

    conn = get_db()
    try:
        _registrar_pasta(conn, col_id, uid, pasta_final)
        vincular = data.get("vincular")
        if vincular is True:
            conn.execute(
                "UPDATE collections SET pasta_vinculada = %s, "
                "modo_sync = CASE WHEN modo_sync = 'manual' THEN 'perguntar' "
                "                 ELSE modo_sync END "
                "WHERE id = %s AND user_id = %s",
                (pasta_final, col_id, uid),
            )
        elif vincular is None:
            conn.execute(
                "UPDATE collections SET pasta_vinculada = %s, modo_sync = 'perguntar' "
                "WHERE id = %s AND user_id = %s AND pasta_vinculada IS NULL",
                (pasta_final, col_id, uid),
            )
        conn.commit()
    finally:
        conn.close()

    itens = [
        {"nome": a["nome"], "caminho": a["caminho"],
         "autorizado": _dentro_das_pastas(a["caminho"], pastas)}
        for a in arquivos
    ]

    import uuid
    job_id = uuid.uuid4().hex
    with _export_lock:
        _export_jobs[job_id] = {
            "user_id": uid, "collection_id": col_id, "colecao": col["nome"],
            "pasta": pasta_final, "total": len(itens), "copiados": 0,
            "falhas": [], "estado": "executando", "cancelar": False, "erro": None,
            "criado_em": time.time(),
        }

    threading.Thread(
        target=_worker_exportacao, args=(job_id, itens, pasta_final), daemon=True
    ).start()

    return jsonify({"status": "ok", "job_id": job_id,
                    "total": len(itens), "pasta": pasta_final})


@app.route("/api/collections/<int:col_id>/folders", methods=["GET"])
def api_collection_folders(col_id):
    """
    Pastas que o app gerou para esta coleção, com o estado de cada uma.

    Alimenta o diálogo de exclusão: o usuário precisa VER o que existe no disco
    antes de decidir o que apagar. `existe` distingue a pasta que ainda está lá
    daquela que o usuário já removeu por fora — apagar já não se aplica.
    """
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    conn = get_db()
    try:
        col = conn.execute(
            "SELECT id FROM collections WHERE id = %s AND user_id = %s",
            (col_id, uid),
        ).fetchone()
        if not col:
            return jsonify({"error": "Coleção não encontrada."}), 404
        caminhos = _pastas_da_colecao(conn, col_id, uid)
        recebem = {os.path.normpath(c) for c in _pastas_que_recebem(conn, col_id, uid)}
    finally:
        conn.close()

    pastas = []
    for c in caminhos:
        existe = os.path.isdir(c)
        recebe = os.path.normpath(c) in recebem
        pastas.append({
            "caminho": c,
            "nome": os.path.basename(c),
            "existe": existe,
            "recebe": recebe,
            # `vinculada` mantido para não quebrar quem já lê esse campo
            "vinculada": recebe,
            "arquivos": len(os.listdir(c)) if existe else 0,
        })
    return jsonify({"pastas": pastas})


@app.route("/api/collections/<int:col_id>/folders", methods=["DELETE"])
def api_collection_folders_delete(col_id):
    """
    Apaga do disco pastas geradas para esta coleção — as que o usuário escolher.

    Operação destrutiva e irreversível: não há lixeira. Por isso três travas:

    1. **Lista fechada.** Só apaga caminho registrado em `collection_folders`
       para ESTE usuário e ESTA coleção. Um caminho arbitrário no corpo é
       recusado, mesmo que exista no disco.
    2. **Escolha explícita.** Exige `caminhos` no corpo. Não existe "apagar
       todas" implícito — quem quer todas manda todas.
    3. **Confirmação obrigatória.** Exige `confirmar: true`. O frontend só
       manda isso depois da segunda etapa do diálogo.

    A coleção NÃO é excluída aqui. São operações separadas de propósito: dá
    para apagar a pasta e manter a coleção, e vice-versa.
    """
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    data = request.get_json(force=True) or {}
    if data.get("confirmar") is not True:
        return jsonify({"error": "Confirmação obrigatória para apagar pastas."}), 400

    pedidos = data.get("caminhos")
    if not isinstance(pedidos, list) or not pedidos:
        return jsonify({"error": "Escolha ao menos uma pasta."}), 400

    conn = get_db()
    try:
        col = conn.execute(
            "SELECT id FROM collections WHERE id = %s AND user_id = %s", (col_id, uid)
        ).fetchone()
        if not col:
            return jsonify({"error": "Coleção não encontrada."}), 404
        registradas = {os.path.normpath(c) for c in _pastas_da_colecao(conn, col_id, uid)}
    finally:
        conn.close()

    apagadas, falhas = [], []
    for bruto in pedidos:
        alvo = os.path.normpath(str(bruto).strip())

        # Trava 1: o caminho tem de ter sido gerado pelo app, para esta coleção.
        if alvo not in registradas:
            falhas.append({"caminho": alvo, "motivo": "nao_autorizada"})
            continue

        if not os.path.isdir(alvo):
            # Já não está lá: some do registro, sem alarde.
            conn = get_db()
            try:
                conn.execute(
                    "DELETE FROM collection_folders WHERE collection_id = %s "
                    "AND user_id = %s AND caminho = %s", (col_id, uid, alvo))
                conn.commit()
            finally:
                conn.close()
            continue

        try:
            shutil.rmtree(alvo)
        except PermissionError:
            falhas.append({"caminho": alvo, "motivo": "sem_permissao"})
            continue
        except OSError as exc:
            print(f"[PASTAS] erro ao apagar '{alvo}': {type(exc).__name__}: {exc}")
            falhas.append({"caminho": alvo, "motivo": "erro_ao_apagar"})
            continue

        apagadas.append(alvo)
        conn = get_db()
        try:
            conn.execute(
                "DELETE FROM collection_folders WHERE collection_id = %s "
                "AND user_id = %s AND caminho = %s", (col_id, uid, alvo))
            # A linha some junto com a pasta, então ela sai do conjunto de
            # destinos automaticamente. Só o espelho em `collections` precisa
            # de ajuste — e apenas se apontava para a pasta apagada.
            restantes = _pastas_que_recebem(conn, col_id, uid)
            conn.execute(
                "UPDATE collections SET pasta_vinculada = %s "
                "WHERE id = %s AND user_id = %s AND pasta_vinculada = %s",
                (restantes[0] if restantes else None, col_id, uid, alvo))
            conn.commit()
        finally:
            conn.close()

    return jsonify({"status": "ok", "apagadas": apagadas, "falhas": falhas})


def _remover_das_pastas(col_id: int, uid: int):
    """
    Apaga das pastas espelho as cópias dos arquivos informados.

    Apaga arquivo do disco, então vale o mesmo rigor do resto:

    1. **Só dentro das pastas registradas** para esta coleção. O nome recebido
       é sanitizado e reduzido a `basename` — `..\\..\\algo` não escapa.
    2. **Só a cópia.** O original nas pastas monitoradas nunca é tocado: as
       duas árvores são distintas e só a pasta espelho entra no laço.
    3. **Nunca apaga diretório.** Se o nome casar com uma subpasta, é ignorado.

    Diferente da exclusão de pastas, não exige confirmação no corpo: quem
    chama já confirmou ao remover da coleção, e o que se apaga é uma cópia
    gerada pelo próprio app — não um arquivo do usuário.
    """
    data = request.get_json(force=True) or {}
    nomes = data.get("nomes")
    if not isinstance(nomes, list) or not nomes:
        return jsonify({"error": "Informe os nomes a remover."}), 400

    conn = get_db()
    try:
        col = conn.execute(
            "SELECT id FROM collections WHERE id = %s AND user_id = %s", (col_id, uid)
        ).fetchone()
        if not col:
            return jsonify({"error": "Coleção não encontrada."}), 404
        destinos = [c for c in _pastas_que_recebem(conn, col_id, uid) if os.path.isdir(c)]
    finally:
        conn.close()

    if not destinos:
        return jsonify({"status": "ok", "apagados": 0, "falhas": [], "pastas": []})

    # basename + sanitização: o nome vem do banco, mas tratá-lo como caminho
    # confiável seria assumir que ninguém adulterou a requisição.
    alvos = []
    for n in nomes:
        limpo = os.path.basename(_sanitizar_nome(str(n), padrao=""))
        if limpo:
            alvos.append(limpo)

    apagados, falhas = 0, []
    for pasta in destinos:
        for nome in alvos:
            caminho = os.path.join(pasta, nome)
            # Confere que o resultado continua DENTRO da pasta espelho
            if os.path.dirname(os.path.abspath(caminho)) != os.path.abspath(pasta):
                continue
            if not os.path.isfile(caminho):     # inexistente ou é diretório
                continue
            try:
                os.remove(caminho)
                apagados += 1
            except PermissionError:
                falhas.append({"nome": nome, "motivo": "sem_permissao",
                               "pasta": os.path.basename(pasta)})
            except OSError as exc:
                print(f"[SYNC-DEL] '{caminho}': {type(exc).__name__}: {exc}")
                falhas.append({"nome": nome, "motivo": "erro_ao_apagar",
                               "pasta": os.path.basename(pasta)})

    return jsonify({"status": "ok", "apagados": apagados,
                    "falhas": falhas, "pastas": destinos})


@app.route("/api/collections/<int:col_id>/sync_status")
def api_collection_sync_status(col_id):
    """
    Compara a coleção com o conteúdo de cada pasta espelho.

    Responde a pergunta que o modo manual deixa em aberto: *quais* imagens já
    foram copiadas e quais ainda não. Sem isto, quem copia manualmente não tem
    como saber onde parou — só o número total de arquivos na pasta.

    Três listas por pasta:
      na_pasta  — está na coleção E na pasta
      faltando  — está na coleção, não está na pasta
      extras    — está na pasta, não está mais na coleção (removida depois)

    `extras` é o que revela cópia órfã: o arquivo saiu da coleção mas ficou no
    disco. Em modo manual isso é esperado; em auto, indica falha de remoção.
    """
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    conn = get_db()
    try:
        col = conn.execute(
            "SELECT id, modo_sync FROM collections WHERE id = %s AND user_id = %s",
            (col_id, uid),
        ).fetchone()
        if not col:
            return jsonify({"error": "Coleção não encontrada."}), 404

        arquivos = conn.execute(
            """
            SELECT f.id, f.nome
            FROM collection_files cf
            JOIN files f ON f.id = cf.file_id
            WHERE cf.collection_id = %s AND f.user_id = %s
            ORDER BY f.nome
            """,
            (col_id, uid),
        ).fetchall()
        caminhos = _pastas_da_colecao(conn, col_id, uid)
        recebem = {os.path.normpath(c) for c in _pastas_que_recebem(conn, col_id, uid)}
    finally:
        conn.close()

    # O nome no destino é o sanitizado — comparar com o nome cru daria
    # "faltando" para todo arquivo cujo nome tenha caractere inválido.
    da_colecao = [{"id": a["id"], "nome": a["nome"],
                   "no_disco": _sanitizar_nome(a["nome"], padrao="arquivo")}
                  for a in arquivos]

    pastas = []
    for c in caminhos:
        if not os.path.isdir(c):
            pastas.append({"caminho": c, "nome": os.path.basename(c), "existe": False,
                           "recebe": os.path.normpath(c) in recebem,
                           "na_pasta": [], "faltando": [], "extras": []})
            continue

        try:
            no_disco = {n for n in os.listdir(c) if os.path.isfile(os.path.join(c, n))}
        except OSError:
            no_disco = set()

        na_pasta = [a for a in da_colecao if a["no_disco"] in no_disco]
        faltando = [a for a in da_colecao if a["no_disco"] not in no_disco]
        esperados = {a["no_disco"] for a in da_colecao}
        extras = sorted(n for n in no_disco if n not in esperados)

        pastas.append({
            "caminho": c, "nome": os.path.basename(c), "existe": True,
            "recebe": os.path.normpath(c) in recebem,
            "na_pasta": [{"id": a["id"], "nome": a["nome"]} for a in na_pasta],
            "faltando": [{"id": a["id"], "nome": a["nome"]} for a in faltando],
            "extras": extras,
        })

    return jsonify({"total_colecao": len(da_colecao),
                    "modo_sync": col["modo_sync"] or "manual",
                    "pastas": pastas})


@app.route("/api/collections/<int:col_id>/sync", methods=["POST", "DELETE"])
def api_collection_sync(col_id):
    """
    Copia arquivos da coleção para TODAS as pastas marcadas como destino.

    O destino é um conjunto: o usuário pode espelhar a coleção em duas pastas
    ao mesmo tempo. Cada arquivo é copiado uma vez por pasta.

    Diferente de /export em dois pontos que importam:

    1. Escreve dentro das pastas existentes — não cria `Nome_2`. A pasta
       vinculada é um espelho estável da coleção; criar outra a cada adição
       derrotaria o propósito.
    2. Aceita `file_ids` para copiar só o que acabou de entrar. Sem isso,
       adicionar uma foto a uma coleção de 300 recopiaria as 300.

    Arquivo que já existe no destino é pulado (`ja_existiam`), não duplicado
    com sufixo: aqui a intenção é espelhar, não acumular versões.

    DELETE faz o caminho inverso: apaga da pasta as cópias dos arquivos
    informados por `nomes`. Espelhar é nos dois sentidos — sem isso, remover
    da coleção deixaria a pasta divergindo para sempre.
    """
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    if request.method == "DELETE":
        return _remover_das_pastas(col_id, uid)

    data = request.get_json(force=True) or {}
    brutos = data.get("file_ids")

    conn = get_db()
    try:
        col = conn.execute(
            "SELECT id, nome, modo_sync FROM collections "
            "WHERE id = %s AND user_id = %s",
            (col_id, uid),
        ).fetchone()
        if not col:
            return jsonify({"error": "Coleção não encontrada."}), 404

        destinos = _pastas_que_recebem(conn, col_id, uid)
        if not destinos:
            return jsonify({"error": "Esta coleção não tem pasta recebendo imagens."}), 400

        # Uma pasta pode ter sumido do disco sem as outras terem sumido: só
        # aborta se NENHUMA sobrou. Perder um destino não pode impedir a cópia
        # nos demais.
        sumidas = [d for d in destinos if not os.path.isdir(d)]
        destinos = [d for d in destinos if os.path.isdir(d)]
        if not destinos:
            nomes = ", ".join(f'"{os.path.basename(d)}"' for d in sumidas)
            return jsonify({
                "error": f'A pasta {nomes} não está mais no lugar. '
                         "Escolha outra pasta para receber as imagens."
            }), 409

        if brutos is None:
            sql = """
                SELECT f.nome, f.caminho
                FROM collection_files cf
                JOIN files f ON f.id = cf.file_id
                WHERE cf.collection_id = %s AND f.user_id = %s
                ORDER BY cf.adicionado_em DESC
            """
            params = (col_id, uid)
        else:
            if not isinstance(brutos, list):
                return jsonify({"error": "file_ids deve ser uma lista."}), 400
            try:
                ids = [int(b) for b in brutos]
            except (TypeError, ValueError):
                return jsonify({"error": "Identificador de arquivo inválido."}), 400
            if not ids:
                return jsonify({"status": "ok", "copiados": 0, "ja_existiam": 0,
                                "falhas": [], "pastas": destinos,
                                "pasta": destinos[0]})
            sql = """
                SELECT f.nome, f.caminho
                FROM collection_files cf
                JOIN files f ON f.id = cf.file_id
                WHERE cf.collection_id = %s AND f.user_id = %s AND f.id = ANY(%s)
            """
            params = (col_id, uid, ids)

        arquivos = conn.execute(sql, params).fetchall()
        pastas = [r["path"] for r in conn.execute(
            "SELECT path FROM folders WHERE user_id = %s", (uid,)
        ).fetchall()]
    finally:
        conn.close()

    copiados, ja_existiam, falhas = 0, 0, []
    for a in arquivos:
        origem = a["caminho"]

        # Validações do arquivo valem para todos os destinos: falham uma vez,
        # não uma por pasta — senão o resumo contaria a mesma falha N vezes.
        if not _dentro_das_pastas(origem, pastas):
            falhas.append({"nome": a["nome"], "motivo": "fora_das_pastas"})
            continue
        if not os.path.isfile(origem):
            falhas.append({"nome": a["nome"], "motivo": "nao_encontrado"})
            continue

        nome_destino = _sanitizar_nome(a["nome"], padrao="arquivo")
        for pasta in destinos:
            alvo = os.path.join(pasta, nome_destino)
            if os.path.exists(alvo):
                ja_existiam += 1
                continue
            try:
                shutil.copy2(origem, alvo)
                copiados += 1
            except PermissionError:
                falhas.append({"nome": a["nome"], "motivo": "sem_permissao",
                               "pasta": os.path.basename(pasta)})
            except OSError as exc:
                print(f"[SYNC] '{origem}' → '{alvo}': {type(exc).__name__}: {exc}")
                falhas.append({"nome": a["nome"], "motivo": "erro_escrita",
                               "pasta": os.path.basename(pasta)})

    return jsonify({"status": "ok", "copiados": copiados,
                    "ja_existiam": ja_existiam, "falhas": falhas,
                    "pastas": destinos, "pasta": destinos[0]})


def _job_do_usuario(job_id, uid):
    """Devolve o job se ele existir E pertencer ao usuário; senão None."""
    job = _export_jobs.get(job_id)
    return job if job and job["user_id"] == uid else None


@app.route("/api/collections/export/<job_id>")
def api_collection_export_status(job_id):
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    with _export_lock:
        job = _job_do_usuario(job_id, uid)
        if not job:
            return jsonify({"error": "Exportação não encontrada."}), 404
        # Descarta jobs terminados há mais de 5 min, para o dict não crescer
        # indefinidamente (RNF do risco R-05).
        agora = time.time()
        for jid, j in list(_export_jobs.items()):
            if j["estado"] != "executando" and agora - j["criado_em"] > 300:
                _export_jobs.pop(jid, None)
        return jsonify({
            "estado": job["estado"], "copiados": job["copiados"],
            "total": job["total"], "falhas": job["falhas"],
            "pasta": job["pasta"], "colecao": job["colecao"], "erro": job["erro"],
        })


@app.route("/api/collections/export/<job_id>/cancel", methods=["POST"])
def api_collection_export_cancel(job_id):
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    with _export_lock:
        job = _job_do_usuario(job_id, uid)
        if not job:
            return jsonify({"error": "Exportação não encontrada."}), 404
        # Cooperativo: o worker checa a flag entre arquivos. A cópia em
        # andamento termina — interromper no meio deixaria arquivo truncado.
        job["cancelar"] = True
        return jsonify({"status": "ok", "copiados": job["copiados"]})


@app.route("/api/open_folder")
def api_open_folder():
    """
    Abre no Explorer uma pasta criada por exportação desta sessão.

    Diferente de /api/open_location, valida o caminho. São autorizadas duas
    origens, ambas criadas pelo próprio app a pedido do usuário:

    1. pasta de uma exportação desta sessão (`_export_jobs`, em memória);
    2. qualquer pasta já gerada para o usuário (`collection_folders`, no banco).

    A segunda é o caso do botão "Abrir pasta exportada" — e precisa vir do
    banco porque o registro sobrevive a reinícios, ao contrário dos jobs.
    Sem essa lista fechada, a rota viraria um "abra qualquer caminho do
    disco" (RF-059).
    """
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    caminho = os.path.normpath(unquote(request.args.get("path", "")).strip())

    with _export_lock:
        autorizado = any(
            j["user_id"] == uid and os.path.normpath(j["pasta"]) == caminho
            for j in _export_jobs.values()
        )

    if not autorizado:
        conn = get_db()
        try:
            registradas = conn.execute(
                "SELECT caminho FROM collection_folders WHERE user_id = %s", (uid,)
            ).fetchall()
        finally:
            conn.close()
        autorizado = any(
            os.path.normpath(r["caminho"]) == caminho for r in registradas
        )

    if not autorizado:
        return jsonify({"error": "Pasta não autorizada."}), 403

    if not os.path.isdir(caminho):
        return jsonify({"error": "Pasta não encontrada."}), 404

    if os.name != "nt":
        return jsonify({"error": "Disponível apenas no Windows."}), 501

    subprocess.Popen(["explorer", caminho])
    return jsonify({"status": "ok"})


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
    
    # Alias nomeado ('n') porque o cursor é RealDictCursor: a linha volta como
    # dict, e o antigo fetchone()[0] levantava KeyError — capturado pelo except
    # abaixo, o contador ficava zerado em toda chamada.
    conn = None
    try:
        conn = get_db()
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM files WHERE user_id = %s", (uid,)
        ).fetchone()["n"]
    except Exception as exc:
        print(f"[Status] Falha ao contar arquivos: {exc}")
        count = 0
    finally:
        if conn is not None:
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
    # termina normalmente (não dá pra abortar uma chamada de visão em curso).
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
        "claude_disponivel": CLAUDE_OK,
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
    # Marca como não processado: arquivos travados (processado=0), sem NENHUM
    # embedding, ou com descrição de fallback. Imagens lazy-indexadas (só com
    # embedding_clip, descrição vazia de propósito) são SAUDÁVEIS — não entram,
    # senão o botão "Re-analisar" as tiraria da busca à toa.
    conditions = " OR ".join(
        "descricao_ia LIKE %s" for _ in _DESCRICOES_RUINS
    )
    rows = conn.execute(
        f"SELECT id, caminho, nome, tipo FROM files WHERE user_id = %s AND "
        f"(processado = 0 OR (embedding IS NULL AND embedding_clip IS NULL) OR {conditions})",
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

    # Imagens descritas ANTES do prompt ganhar o campo "Estilo:" não sabem dizer
    # se são foto ou desenho — e as antigas ainda podiam marcar "Animais: nenhum"
    # num desenho de cachorro. Limpar a descrição basta: a imagem continua
    # indexada pelo CLIP (processado=1) e a própria busca a redescreve sob
    # demanda com o prompt novo. Não precisa passar pela fila.
    desatualizadas = conn.execute(
        "UPDATE files SET descricao_ia = '', embedding = NULL "
        "WHERE user_id = %s AND tipo = ANY(%s) AND embedding_clip IS NOT NULL "
        "AND descricao_ia <> '' AND descricao_ia NOT LIKE %s "
        "RETURNING id",
        (uid, list(_EXT_IMG), "%Estilo:%")
    ).fetchall()
    conn.commit()
    conn.close()

    # Re-enfileira os arquivos para análise
    for r in rows:
        _queue.put({"path": r["caminho"], "nome": r["nome"], "ext": r["tipo"], "uid": uid})

    return jsonify({
        "status": "ok",
        "reenfileirados": len(rows),
        "descricoes_limpas": len(desatualizadas),
    })


# ──────────────────────────────────────────────────────────────────────────────
# Re-geração rápida de embeddings (sem re-descrever as imagens)
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/reembed", methods=["POST"])
def api_reembed():
    """
    Re-gera os embeddings de todos os arquivos já processados:
    - SBERT a partir da descrição textual (rápido)
    - CLIP a partir da imagem no disco (lento, só imagens)
    Não chama o Claude novamente.
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
    """
    Abre o Explorer com o arquivo selecionado.

    Só abre arquivo dentro de uma pasta monitorada do usuário. Antes bastava
    o caminho existir: `?path=C:\\Users\\x\\.ssh\\id_rsa` abria o Explorer ali,
    e o próprio `/api/file` — que serve o mesmo tipo de recurso — já recusava
    isso. A rota era a única porta sem tranca.

    A validação usa `realpath`, não `normpath`: um symlink dentro da pasta
    monitorada apontando para fora passaria pela comparação textual, porque o
    caminho *escrito* fica dentro. Resolver primeiro elimina essa classe.
    """
    uid = _uid()
    if not uid:
        return jsonify({"error": "Não autenticado."}), 401

    bruto = unquote(request.args.get("path", "")).strip()
    if not bruto:
        return jsonify({"error": "Caminho não informado."}), 400

    filepath = os.path.realpath(bruto)

    conn = get_db()
    try:
        pastas = [r["path"] for r in conn.execute(
            "SELECT path FROM folders WHERE user_id = %s", (uid,)
        ).fetchall()]
    finally:
        conn.close()

    if not _dentro_das_pastas(filepath, pastas):
        return jsonify({"error": "Arquivo fora das pastas monitoradas."}), 403

    if not os.path.exists(filepath):
        return jsonify({"error": "Arquivo não encontrado."}), 404

    if os.name != "nt":
        return jsonify({"error": "Disponível apenas no Windows."}), 501

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
    # Blacklist de pastas (config do usuário): caminhos a ignorar no scan
    cfg_row = conn.execute(
        "SELECT config_json FROM users WHERE id = %s", (uid,)
    ).fetchone()
    conn.close()

    cfg = _safe_json_loads(cfg_row["config_json"] if cfg_row else None, {}) or {}
    blacklist = [
        os.path.normpath(p.strip()).lower()
        for p in (cfg.get("pastas_ignoradas") or "").split(",")
        if p.strip()
    ]

    def _esta_na_blacklist(caminho: str) -> bool:
        cam = os.path.normpath(caminho).lower()
        return any(cam.startswith(b) for b in blacklist)

    for root, _, filenames in os.walk(folder_path):
        # Pula diretórios inteiros que estão na blacklist
        if _esta_na_blacklist(root):
            continue
        for fname in filenames:
            ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
            if ext not in _EXT_ALL:
                continue

            fpath = os.path.join(root, fname)
            if _esta_na_blacklist(fpath):
                continue

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
                        (folder_id, uid, fname, fpath, ext,
                         datetime.now(timezone.utc).isoformat()),
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
        # Hora LOCAL de propósito (os timestamps do banco são UTC, este não):
        # a janela é configurada pelo usuário no fuso dele — "22:00-06:00"
        # significa a madrugada de quem usa a máquina, não a madrugada em UTC.
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

        # Todo o processamento de UM item fica dentro deste try: sem ele, uma
        # exceção aqui matava a thread e a indexação parava para sempre — com o
        # status exibindo "Ocioso", sem nenhum sinal de que algo quebrou.
        try:
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
                _status = f"Indexando ({_queue.qsize()} na fila): {fname}"

            # ── INDEXAÇÃO LAZY ──────────────────────────────────────────────
            # No upload NÃO chamamos o Claude. Geramos só o embedding CLIP
            # (local, rápido, grátis) para imagens, e extraímos texto de
            # documentos. A descrição rica (Claude) é gerada SOB DEMANDA na
            # busca, só para as imagens que aparecem como candidatas —
            # economiza tempo e créditos.
            desc = ""
            emb_clip_vec = None

            if ext in _EXT_IMG:
                # Imagem: só o embedding visual CLIP. Descrição vem na busca.
                if CLIP_OK:
                    emb_clip = _gerar_embedding_clip_imagem(fpath)
                    if emb_clip:
                        emb_clip_vec = emb_clip
                desc = ""  # vazia de propósito — a busca preenche depois
            else:
                # Documentos (pdf/docx/txt/csv): extrai o texto na hora (é local
                # e barato, e a busca textual precisa dele de cara).
                try:
                    desc = _analyze_file(fpath, ext, prioridades=prioridades, perfil=perfil)
                except Exception as exc:
                    print(f"[ERRO] {fpath}: {exc}")
                    desc = f"{ext.upper()}: {fname}"
                # Binário/corrompido pode trazer \x00, que o Postgres recusa.
                desc = _limpar_texto_para_banco(desc)

            # Embedding SBERT só para documentos (imagens ainda não têm texto)
            emb_vec = None
            if SBERT_OK and desc:
                texto_emb = _texto_para_embedding(desc)
                emb = _gerar_embedding(texto_emb)
                if emb:
                    emb_vec = emb

            # Imagem indexada (tem embedding CLIP) ou documento com texto =
            # processado. Imagem sem CLIP = não indexada (tenta de novo depois).
            if ext in _EXT_IMG:
                processado_flag = 1 if emb_clip_vec is not None else 0
            else:
                caiu_no_fallback = any(desc.startswith(prefix) for prefix in _DESCRICOES_RUINS)
                processado_flag = 0 if caiu_no_fallback else 1

            conn = get_db()
            try:
                conn.execute(
                    "UPDATE files SET descricao_ia = %s, embedding = %s, embedding_clip = %s, processado = %s "
                    "WHERE user_id = %s AND caminho = %s",
                    (desc, emb_vec, emb_clip_vec, processado_flag, uid, fpath),
                )
                conn.commit()
            finally:
                # Esta thread roda fora do app context, então o teardown do
                # Flask não recolhe a conexão: sem o finally, cada falha no
                # UPDATE vazava uma conexão até esgotar o pool.
                conn.close()

            with _lock:
                _processed += 1

            _queue.task_done()

        except Exception as exc:
            print(f"[WORKER] Falha ao processar '{fname}': {type(exc).__name__}: {exc}")
            try:
                _queue.task_done()
            except ValueError:
                pass  # já contabilizado antes da exceção


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


def _build_prompt_visao(prioridades: list) -> str:
    """Constrói o prompt de visão do Claude baseado nas prioridades do usuário."""
    base = (
        "Analise esta imagem e descreva APENAS o que VOCÊ VÊ. "
        "NÃO INVENTE pessoas, animais ou objetos que não estão visíveis.\n\n"
        "REGRA MAIS IMPORTANTE — DESENHOS CONTAM COMO O QUE REPRESENTAM:\n"
        "A imagem pode ser uma foto, mas também pode ser desenho, ilustração, "
        "pintura, anime, cartoon, quadrinho, pixel art, render 3D, captura de tela "
        "ou logotipo. Personagens desenhados, animados ou pintados devem ser "
        "descritos como as PESSOAS e os ANIMAIS que representam. Um cachorro de "
        "desenho animado é listado em 'Animais: cachorro'. Uma personagem de anime "
        "é listada em 'Pessoas: mulher jovem'. NUNCA escreva 'nenhum' só porque a "
        "imagem não é uma fotografia real — quem procura por 'cachorro' quer achar "
        "o desenho de cachorro também. Escreva 'nenhuma'/'nenhum' apenas quando o "
        "ser realmente não aparece na imagem, em nenhuma forma.\n\n"
        "REGRAS DE VOCABULÁRIO (obrigatório):\n"
        "• 'cachorro' (NUNCA 'cão' ou 'cãe')\n"
        "• 'gato' (NUNCA 'felino' ou 'bichano')\n"
        "• 'mulher' / 'menina' (NUNCA 'senhora', 'moça', 'dama')\n"
        "• 'homem' / 'menino' (NUNCA 'senhor', 'rapaz', 'cavalheiro')\n\n"
        "FORMATO (sempre em português, um campo por linha):\n"
        "- Estilo: escolha os termos que se aplicam entre foto, desenho, ilustração, "
        "pintura, anime, mangá, cartoon, quadrinho, pixel art, arte digital, "
        "esboço, render 3D, captura de tela, logotipo, ícone, meme, gráfico, mapa\n"
        "- O que é: cena principal em uma frase curta\n"
        "- Pessoas: pessoas e personagens humanos visíveis (inclusive desenhados) "
        "com gênero + idade + ação; ou 'nenhuma' se não há nenhum\n"
        "- Animais: animais e personagens-animais visíveis (inclusive desenhados) "
        "com espécie + ação; ou 'nenhum' se não há nenhum\n"
        "- Objetos: itens visíveis (vírgula-separado)\n"
        "- Ambiente: local + cores dominantes\n"
        "- Ações: o que está acontecendo (verbos no gerúndio)\n"
        "- Texto: texto legível na imagem entre aspas; ou 'nenhum'\n"
        "- Tags: 6 a 10 palavras-chave usando o vocabulário acima, incluindo o estilo"
    )

    extras = []
    prio_set = set(prioridades)

    if "tudo" in prio_set:
        extras.append("Seja conciso: uma linha curta por campo, sem repetir.")
    else:
        if "animais" in prio_set:
            extras.append(
                "Foque a descrição em identificar espécies, raças e comportamentos "
                "dos animais visíveis, sejam eles reais ou desenhados."
            )
        if "pessoas" in prio_set:
            extras.append(
                "Foque em descrever detalhadamente as pessoas e personagens humanos: "
                "gênero, idade aproximada, roupas, expressões faciais e ações."
            )
        if "paisagens" in prio_set:
            extras.append(
                "Foque em descrever o ambiente, paisagem, elementos naturais, "
                "arquitetônicos e as cores dominantes da cena."
            )
        if extras:
            extras.append("Mesmo assim, preencha TODOS os campos do formato.")
        if not extras:
            extras.append("Seja conciso: uma linha curta por campo, sem repetir.")

    return base + "\n" + " ".join(extras)


def _preparar_imagem(filepath: str, max_size=768) -> bytes:
    """Redimensiona a imagem em memória antes de mandar pro Claude (menor = mais barato)."""
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


def _analyze_image_claude(filepath: str, prompt: str, perfil: str = "fast") -> str | None:
    """Descreve a imagem usando a API do Claude (vision). Retorna None se falhar.
    perfil 'deep' = análise mais detalhada e cuidadosa; 'fast' = mais econômica."""
    if not CLAUDE_OK or _CLAUDE is None:
        return None
    try:
        import base64
        img_bytes = _preparar_imagem(filepath)
        media_type = "image/jpeg"  # _preparar_imagem sempre devolve JPEG
        img_b64 = base64.standard_b64encode(img_bytes).decode("utf-8")

        # Perfil controla o quão detalhada é a descrição (deep gasta mais tokens).
        # max_tokens é o teto do raciocínio + do texto juntos, por isso a folga.
        if perfil == "deep":
            prompt_final = prompt + (
                "\n\nMODO PROFUNDO: seja minucioso. Identifique raças/espécies "
                "específicas, marcas, estilo artístico, texto visível na imagem e "
                "detalhes do ambiente. Não deixe passar nada relevante para a busca."
            )
            max_tok, esforco = 3000, "medium"
        else:
            prompt_final = prompt
            max_tok, esforco = 2000, "low"

        resp = _CLAUDE.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=max_tok,
            output_config={"effort": esforco},
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": media_type, "data": img_b64,
                    }},
                    {"type": "text", "text": prompt_final},
                ],
            }],
        )
        if resp.stop_reason == "refusal":
            print(f"[VLM:claude] Recusou descrever {os.path.basename(filepath)}")
            return None
        # Concatena os blocos de texto da resposta (geralmente é um só)
        desc = "".join(b.text for b in resp.content if b.type == "text").strip()
        if desc:
            print(f"[VLM:claude] OK: {os.path.basename(filepath)}")
            return desc
    except Exception as exc:
        print(f"[VLM:claude] Falhou para {filepath}: {exc}")
    return None


def _analyze_image(filepath: str, *, prioridades=None, perfil="fast") -> str:
    """Descreve a imagem usando o Claude (vision). O perfil deep/fast controla
    o nível de detalhe. Se a API falhar, devolve um fallback com o nome do
    arquivo (o worker mantém processado=0 e tenta de novo na próxima varredura)."""
    if prioridades is None:
        prioridades = ["tudo"]

    prompt = _build_prompt_visao(prioridades)
    desc = _analyze_image_claude(filepath, prompt, perfil=perfil)
    return desc or f"Imagem: {os.path.basename(filepath)}"


def _descrever_imagem_on_demand(caminho: str, nome: str) -> str | None:
    """Descreve UMA imagem com o Claude na hora da busca (modo lazy).
    Usada quando a imagem foi indexada só com embedding CLIP, sem descrição.
    Se o arquivo sumiu do disco ou a API falhar, retorna None."""
    if not CLAUDE_OK:
        return None
    if not os.path.isfile(caminho):
        return None
    prompt = _build_prompt_visao(["tudo"])
    desc = _analyze_image_claude(caminho, prompt, perfil="fast")
    if desc:
        print(f"[Lazy] Descrita sob demanda: {nome}")
    return desc


def _salvar_descricao_e_embedding(uid: int, caminho: str, desc: str) -> None:
    """Salva a descrição gerada sob demanda + o embedding SBERT no banco,
    pra que buscas futuras dessa imagem já tenham tudo pronto (cache)."""
    emb_vec = None
    if SBERT_OK and desc:
        emb = _gerar_embedding(_texto_para_embedding(desc))
        if emb:
            emb_vec = emb
    try:
        conn = get_db()
        conn.execute(
            "UPDATE files SET descricao_ia = %s, embedding = %s WHERE user_id = %s AND caminho = %s",
            (desc, emb_vec, uid, caminho),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[Lazy] Falha ao salvar descrição de {caminho}: {exc}")


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
