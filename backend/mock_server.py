"""
Search+ — servidor MOCK da API.

Serve exatamente os mesmos endpoints do backend real (`app.py`), com o mesmo
formato de resposta, mas em cima de dados fixos em memória. Não precisa de
Postgres, nem dos ~1.1GB de modelos locais, nem de chave da Anthropic — sobe em
dois segundos.

Para que serve: permitir que o frontend seja desenvolvido de forma autônoma. O
contrato da API está descrito em `docs/API.md`; este arquivo é a versão
executável desse contrato.

Como rodar:
    py backend/mock_server.py            # http://127.0.0.1:5001
    MOCK_PORT=5002 py backend/mock_server.py

Login: qualquer usuário/senha é aceito (é um mock — não há autenticação real).

Diferenças propositais em relação ao backend real:
  - as imagens são SVGs gerados na hora, então a galeria aparece preenchida sem
    precisar de arquivo nenhum no disco;
  - a busca é por substring simples com um score decrescente, só para exercitar
    a ordenação e os cortes de faixa do frontend;
  - `/api/choose_folder` e `/api/choose_image` devolvem caminhos fixos em vez de
    abrir diálogos nativos do Windows.
"""

import base64
import os
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from flask import (
    Flask, jsonify, request, send_from_directory, session, Response,
)
from flask_cors import CORS

BASE_DIR = Path(__file__).resolve().parent      # .../backend/
FRONTEND_DIR = BASE_DIR.parent                  # raiz do projeto

# static_folder=None: servimos os arquivos em serve_static(), com fallback de
# rota para SPA — a rota estática automática do Flask atrapalharia os dois.
app = Flask(__name__, static_folder=None)
app.secret_key = "searchplus_mock_key"
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True

CORS(
    app,
    supports_credentials=True,
    origins=[
        "http://127.0.0.1:5000", "http://localhost:5000",
        "http://127.0.0.1:5500", "http://localhost:5500",
        "http://127.0.0.1:5173", "http://localhost:5173",
        "http://127.0.0.1:3000", "http://localhost:3000",
        "http://127.0.0.1:4200", "http://localhost:4200",
        "http://127.0.0.1:8080", "http://localhost:8080",
        "null",
    ],
)

_EXT_IMG = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}
_EXT_VID = {"mp4", "avi", "mkv", "mov", "webm"}
_EXT_AUD = {"mp3", "wav", "ogg", "m4a", "flac"}


# ──────────────────────────────────────────────────────────────────────────────
# Dados de exemplo
# ──────────────────────────────────────────────────────────────────────────────

def _desc(estilo, oque, pessoas, animais, objetos, ambiente, acoes, texto, tags):
    """Monta a descrição no mesmo formato de campos que o Claude produz."""
    return (
        f"- Estilo: {estilo}\n"
        f"- O que é: {oque}\n"
        f"- Pessoas: {pessoas}\n"
        f"- Animais: {animais}\n"
        f"- Objetos: {objetos}\n"
        f"- Ambiente: {ambiente}\n"
        f"- Ações: {acoes}\n"
        f"- Texto: {texto}\n"
        f"- Tags: {tags}"
    )


_BASE = "C:\\Users\\Demo\\Imagens"
_DOCS = "C:\\Users\\Demo\\Documentos"

_ARQUIVOS = [
    {
        "id": 1, "nome": "praia-por-do-sol.jpg", "caminho": f"{_BASE}\\praia-por-do-sol.jpg",
        "tipo": "jpg", "cor": "#F59E0B",
        "descricao_ia": _desc(
            "fotografia", "pôr do sol na praia com o mar calmo", "nenhuma", "nenhum",
            "guarda-sol, cadeira de praia", "praia ao entardecer, céu alaranjado",
            "sol se pondo no horizonte", "nenhum", "praia, por do sol, mar, natureza, verao"),
    },
    {
        "id": 2, "nome": "cachorro-parque.jpg", "caminho": f"{_BASE}\\cachorro-parque.jpg",
        "tipo": "jpg", "cor": "#10B981",
        "descricao_ia": _desc(
            "fotografia", "cachorro correndo na grama de um parque", "nenhuma",
            "cachorro golden retriever", "bola, coleira", "parque com árvores e gramado",
            "cachorro correndo e brincando", "nenhum", "cachorro, pet, parque, animais, natureza"),
    },
    {
        "id": 3, "nome": "gato-janela.png", "caminho": f"{_BASE}\\gato-janela.png",
        "tipo": "png", "cor": "#8B5CF6",
        "descricao_ia": _desc(
            "fotografia", "gato deitado no parapeito de uma janela", "nenhuma",
            "gato malhado cinza", "almofada, cortina", "interior de casa, luz natural",
            "gato dormindo", "nenhum", "gato, pet, casa, animais"),
    },
    {
        "id": 4, "nome": "equipe-reuniao.jpg", "caminho": f"{_BASE}\\equipe-reuniao.jpg",
        "tipo": "jpg", "cor": "#3B82F6",
        "descricao_ia": _desc(
            "fotografia", "equipe de trabalho reunida em volta de uma mesa",
            "quatro pessoas adultas, homens e mulheres", "nenhum",
            "notebooks, cadernos, café", "escritório moderno e iluminado",
            "pessoas conversando e apontando para uma tela", "nenhum",
            "equipe, trabalho, escritorio, reuniao, pessoas"),
    },
    {
        "id": 5, "nome": "desenho-dragao.png", "caminho": f"{_BASE}\\desenho-dragao.png",
        "tipo": "png", "cor": "#EF4444",
        "descricao_ia": _desc(
            "desenho, ilustração digital", "ilustração de um dragão vermelho voando",
            "nenhuma", "dragão", "montanhas ao fundo", "céu nublado ao entardecer",
            "dragão voando e soltando fogo", "nenhum",
            "desenho, ilustracao, dragao, fantasia, arte digital"),
    },
    {
        "id": 6, "nome": "sushi-combinado.jpg", "caminho": f"{_BASE}\\sushi-combinado.jpg",
        "tipo": "jpg", "cor": "#EC4899",
        "descricao_ia": _desc(
            "fotografia", "combinado de sushi servido em uma tábua de madeira",
            "nenhuma", "nenhum", "sushi, sashimi, hashi, molho shoyu, wasabi",
            "mesa de restaurante japonês", "nenhuma", "nenhum",
            "sushi, comida, japonesa, restaurante, refeicao"),
    },
    {
        "id": 7, "nome": "cidade-noite.jpg", "caminho": f"{_BASE}\\cidade-noite.jpg",
        "tipo": "jpg", "cor": "#6366F1",
        "descricao_ia": _desc(
            "fotografia", "vista aérea de uma cidade grande à noite", "nenhuma", "nenhum",
            "prédios, carros, postes de luz", "cidade iluminada à noite",
            "trânsito nas avenidas", "nenhum", "cidade, urbano, noite, predios, luzes"),
    },
    {
        "id": 8, "nome": "anime-personagem.png", "caminho": f"{_BASE}\\anime-personagem.png",
        "tipo": "png", "cor": "#14B8A6",
        "descricao_ia": _desc(
            "desenho, anime", "personagem de anime com cabelo azul",
            "uma personagem feminina jovem", "nenhum", "uniforme escolar, mochila",
            "rua de uma cidade japonesa", "personagem caminhando e sorrindo", "nenhum",
            "anime, desenho, personagem, ilustracao"),
    },
    {
        "id": 9, "nome": "montanha-neve.jpg", "caminho": f"{_BASE}\\montanha-neve.jpg",
        "tipo": "jpg", "cor": "#0EA5E9",
        "descricao_ia": _desc(
            "fotografia", "montanha coberta de neve sob céu azul", "nenhuma", "nenhum",
            "pinheiros, trilha", "paisagem de montanha no inverno", "nenhuma", "nenhum",
            "montanha, neve, paisagem, natureza, inverno"),
    },
    {
        "id": 10, "nome": "relatorio-anual.pdf", "caminho": f"{_DOCS}\\relatorio-anual.pdf",
        "tipo": "pdf", "cor": "#64748B",
        "descricao_ia": (
            "Relatório anual de resultados. Apresenta o crescimento de receita ao longo "
            "dos quatro trimestres, a expansão da base de clientes e as metas definidas "
            "para o próximo ano. Inclui gráficos de faturamento e uma análise comparativa "
            "com o período anterior."
        ),
    },
    {
        "id": 11, "nome": "contrato-servico.docx", "caminho": f"{_DOCS}\\contrato-servico.docx",
        "tipo": "docx", "cor": "#475569",
        "descricao_ia": (
            "Contrato de prestação de serviços entre as partes, com cláusulas de prazo, "
            "escopo do trabalho, forma de pagamento, confidencialidade e rescisão. "
            "Assinado digitalmente por ambas as partes."
        ),
    },
    {
        "id": 12, "nome": "apresentacao-produto.mp4", "caminho": f"{_DOCS}\\apresentacao-produto.mp4",
        "tipo": "mp4", "cor": "#A855F7",
        "descricao_ia": "Vídeo de apresentação do produto, com demonstração das principais funcionalidades.",
    },
]

# Data decrescente: o item 1 é o mais recente
_HOJE = datetime.now()
for _i, _a in enumerate(_ARQUIVOS):
    _a["data"] = (_HOJE - timedelta(days=_i * 3)).isoformat()
    _a["favorito"] = _a["id"] in (1, 5)

_PASTAS = [
    {"id": 1, "path": _BASE, "prioridades": ["tudo"],
     "perfil_analise": "fast", "janela_processamento": "always"},
    {"id": 2, "path": _DOCS, "prioridades": ["documentos"],
     "perfil_analise": "deep", "janela_processamento": "always"},
]

_COLECOES = [
    {"id": 1, "nome": "Favoritos do mês", "criado_em": _HOJE.isoformat(), "files": [1, 5, 9]},
    {"id": 2, "nome": "Trabalho", "criado_em": (_HOJE - timedelta(days=10)).isoformat(),
     "files": [4, 10, 11]},
]

_HISTORICO = ["cachorro no parque", "pôr do sol", "sushi", "relatório"]

_CONFIG = {
    "perfil_nome": "Usuário Demo", "perfil_handle": "demo", "perfil_bio": "Conta de demonstração",
    "perfil_cargo": "Designer", "perfil_local": "São Paulo, BR",
    "perfil_avatar": "", "perfil_banner": "",
    "cor_primaria": "#A855F7", "cor_secundaria": "#E879F9", "cor_texto_botao": "#FFFFFF",
    "tema": "dark", "bg_url": "", "bg_blur": 15, "idioma": "pt-BR",
    "notificacoes": True, "atalho_busca": "Ctrl+Shift+F", "iniciar_sistema": False,
    "modo_privado": False, "pastas_ignoradas": "", "modo_desempenho": "economico",
}

_CATEGORIAS = {
    "pessoas":  [4, 8],
    "animais":  [2, 3],
    "comida":   [6],
    "natureza": [1, 9],
    "urbano":   [7],
    "desenhos": [5, 8],
}


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _logado() -> bool:
    return bool(session.get("user_id"))


def _nao_autenticado():
    return jsonify({"error": "Não autenticado."}), 401


def _item(arq: dict, score: float = 1.0) -> dict:
    """Formato padrão de resultado, idêntico ao do backend real."""
    desc = arq["descricao_ia"]
    return {
        "id": arq["id"], "nome": arq["nome"], "caminho": arq["caminho"],
        "tipo": arq["tipo"], "descricao_ia": desc, "conteudo": desc,
        "trecho": desc[:200], "data": arq["data"],
        "favorito": bool(arq["favorito"]), "score": round(score, 4),
    }


def _por_id(file_id):
    try:
        file_id = int(file_id)
    except (TypeError, ValueError):
        return None
    return next((a for a in _ARQUIVOS if a["id"] == file_id), None)


def _por_caminho(caminho: str):
    alvo = (caminho or "").replace("/", "\\").lower()
    return next((a for a in _ARQUIVOS if a["caminho"].lower() == alvo), None)


def _svg_placeholder(arq: dict) -> str:
    """Gera um SVG colorido com o nome do arquivo — evita depender de imagens em disco."""
    cor = arq["cor"]
    nome = arq["nome"]
    rotulo = arq["descricao_ia"].splitlines()[1][11:60] if arq["tipo"] in _EXT_IMG else arq["tipo"].upper()
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600" viewBox="0 0 800 600">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{cor}"/>
      <stop offset="100%" stop-color="{cor}99"/>
    </linearGradient>
  </defs>
  <rect width="800" height="600" fill="url(#g)"/>
  <text x="400" y="290" font-family="system-ui, sans-serif" font-size="34"
        fill="#ffffff" text-anchor="middle" font-weight="600">{nome}</text>
  <text x="400" y="335" font-family="system-ui, sans-serif" font-size="20"
        fill="#ffffffcc" text-anchor="middle">{rotulo}</text>
</svg>"""


# ──────────────────────────────────────────────────────────────────────────────
# Auth
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    if not username or not password:
        return jsonify({"mensagem": "Preencha todos os campos."}), 400
    session["user_id"] = 1
    session["username"] = username
    return jsonify({"status": "ok", "username": username})


@app.route("/api/register", methods=["POST"])
@app.route("/api/cadastro", methods=["POST"])
def register():
    data = request.get_json(force=True, silent=True) or {}
    senha = (data.get("password") or "").strip()
    if not (data.get("username") or "").strip() or not senha:
        return jsonify({"mensagem": "Preencha todos os campos."}), 400
    # Mesmo limite do backend real: o bcrypt recusa acima de 72 bytes, e em
    # UTF-8 cada acento ocupa 2.
    if len(senha.encode("utf-8")) > 72:
        return jsonify({
            "mensagem": "Senha muito longa (máximo 72 bytes; letras acentuadas contam 2)."
        }), 400
    return jsonify({"status": "ok"})


@app.route("/api/check_session")
def check_session():
    if not _logado():
        return jsonify({"error": "Sem sessão ativa."}), 401
    return jsonify({"username": session.get("username", "demo")})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"status": "ok"})


# ──────────────────────────────────────────────────────────────────────────────
# Config e pastas
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/config", methods=["GET", "POST"])
def config():
    if request.method == "GET":
        cfg = dict(_CONFIG)
        if not _logado():
            return jsonify({**cfg, "pastas": [], "historico_pastas": False})
        cfg["pastas"] = _PASTAS
        cfg["historico_pastas"] = len(_PASTAS) > 0
        return jsonify(cfg)

    if not _logado():
        return _nao_autenticado()
    data = request.get_json(force=True, silent=True) or {}
    data.pop("pastas", None)
    data.pop("historico_pastas", None)
    _CONFIG.update(data)
    return jsonify({"status": "ok"})


@app.route("/api/folders", methods=["GET", "POST", "DELETE"])
def folders():
    if not _logado():
        return _nao_autenticado()

    if request.method == "GET":
        return jsonify({"pastas": _PASTAS})

    data = request.get_json(force=True, silent=True) or {}
    pasta = (data.get("pasta") or "").strip()

    if request.method == "POST":
        if not pasta:
            return jsonify({"error": "Caminho inválido ou inexistente."}), 400
        existente = next((p for p in _PASTAS if p["path"].lower() == pasta.lower()), None)
        novo = {
            "id": existente["id"] if existente else (max((p["id"] for p in _PASTAS), default=0) + 1),
            "path": pasta,
            "prioridades": data.get("prioridades", ["tudo"]),
            "perfil_analise": data.get("perfil_analise", "fast"),
            "janela_processamento": data.get("janela_processamento", "always"),
        }
        if existente:
            _PASTAS[_PASTAS.index(existente)] = novo
        else:
            _PASTAS.append(novo)
        return jsonify({"status": "ok", "pastas": _PASTAS})

    # DELETE
    for p in list(_PASTAS):
        if p["path"].lower() == pasta.lower():
            _PASTAS.remove(p)
    return jsonify({"status": "ok", "pastas": _PASTAS})


@app.route("/api/folders/<int:folder_id>", methods=["DELETE"])
def delete_folder(folder_id):
    if not _logado():
        return _nao_autenticado()
    for p in list(_PASTAS):
        if p["id"] == folder_id:
            _PASTAS.remove(p)
    return jsonify({"status": "ok", "pastas": _PASTAS})


@app.route("/api/folders/update_config", methods=["GET", "POST"])
def update_folder_config():
    if not _logado():
        return _nao_autenticado()
    if request.method == "GET":
        return jsonify({"status": "error", "message": "Use POST"}), 400

    data = request.get_json(force=True, silent=True) or {}
    campos = {k: data[k] for k in ("prioridades", "perfil_analise", "janela_processamento")
              if k in data}
    if not campos:
        return jsonify({"error": "Nenhum campo enviado."}), 400

    for p in _PASTAS:
        if p["id"] == data.get("id") or p["path"] == data.get("path"):
            p.update(campos)
    return jsonify({"status": "ok", "pastas": _PASTAS})


@app.route("/api/estimate_time")
def estimate_time():
    imagens = len([a for a in _ARQUIVOS if a["tipo"] in _EXT_IMG])
    perfil = request.args.get("perfil", "fast")
    return jsonify({
        "estimativa_minutos": 1 if perfil == "fast" else 3,
        "total_imagens": imagens,
    })


# ──────────────────────────────────────────────────────────────────────────────
# Busca
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/search", methods=["GET", "POST"])
def search():
    if not _logado():
        return _nao_autenticado()

    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
        query = (data.get("query") or "").strip()
        filtro = data.get("filtro", "all")
    else:
        query = (request.args.get("q") or "").strip()
        filtro = request.args.get("filtro", "all")

    if not query:
        return jsonify({"resultados": [], "tempo": 0})

    t0 = time.time()
    termos = [t for t in query.lower().split() if len(t) >= 3]

    candidatos = _ARQUIVOS
    if filtro == "imagem":
        candidatos = [a for a in candidatos if a["tipo"] in _EXT_IMG]
    elif filtro == "midia":
        candidatos = [a for a in candidatos if a["tipo"] in _EXT_VID | _EXT_AUD]
    elif filtro == "documento":
        candidatos = [a for a in candidatos
                      if a["tipo"] not in _EXT_IMG | _EXT_VID | _EXT_AUD]

    # Score por quantidade de termos encontrados na descrição/nome.
    achados = []
    for a in candidatos:
        alvo = (a["descricao_ia"] + " " + a["nome"]).lower()
        acertos = sum(1 for t in termos if t in alvo)
        if acertos:
            achados.append((a, 0.55 + 0.4 * (acertos / max(1, len(termos)))))

    achados.sort(key=lambda x: x[1], reverse=True)
    resultados = [_item(a, s) for a, s in achados]

    # Simula a latência de uma busca real (SBERT + CLIP + re-rank do Claude).
    time.sleep(0.25)
    return jsonify({"resultados": resultados, "tempo": round(time.time() - t0, 3)})


@app.route("/api/search_by_image", methods=["POST"])
def search_by_image():
    if not _logado():
        return _nao_autenticado()

    data = request.get_json(force=True, silent=True) or {}
    if not data.get("data_url") and not data.get("file_id"):
        return jsonify({"erro": "Envie data_url ou file_id."}), 400

    origem = _por_id(data.get("file_id"))
    imagens = [a for a in _ARQUIVOS if a["tipo"] in _EXT_IMG
               and (origem is None or a["id"] != origem["id"])]
    resultados = [_item(a, 0.92 - i * 0.07) for i, a in enumerate(imagens[:8])]
    time.sleep(0.25)
    return jsonify({"resultados": resultados, "tempo": 0.31, "modo": "imagem"})


# ──────────────────────────────────────────────────────────────────────────────
# Home: estatísticas e galeria
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/stats")
def stats():
    if not _logado():
        return _nao_autenticado()

    por_formato = {"imagem": 0, "documento": 0, "midia": 0}
    for a in _ARQUIVOS:
        if a["tipo"] in _EXT_IMG:
            por_formato["imagem"] += 1
        elif a["tipo"] in _EXT_VID | _EXT_AUD:
            por_formato["midia"] += 1
        else:
            por_formato["documento"] += 1

    categorias = sorted(
        [{"categoria": k, "total": len(v)} for k, v in _CATEGORIAS.items() if v],
        key=lambda x: x["total"], reverse=True,
    )
    return jsonify({
        "total_arquivos": len(_ARQUIVOS),
        "total_pastas": len(_PASTAS),
        "por_formato": por_formato,
        "por_categoria": categorias,
    })


@app.route("/api/gallery")
def gallery():
    if not _logado():
        return _nao_autenticado()

    grupos = []
    usados = set()
    for cat, ids in _CATEGORIAS.items():
        itens = [_item(_por_id(i)) for i in ids if _por_id(i)]
        if itens:
            grupos.append({"categoria": cat, "total": len(itens), "itens": itens})
            usados.update(ids)

    outras = [_item(a) for a in _ARQUIVOS
              if a["tipo"] in _EXT_IMG and a["id"] not in usados]
    if outras:
        grupos.append({"categoria": "outras", "total": len(outras), "itens": outras})

    total_img = len([a for a in _ARQUIVOS if a["tipo"] in _EXT_IMG])
    return jsonify({"grupos": grupos, "total_imagens": total_img})


# ──────────────────────────────────────────────────────────────────────────────
# Favoritos e coleções
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/favorites")
def favorites():
    if not _logado():
        return jsonify({"resultados": []})
    return jsonify({"resultados": [_item(a) for a in _ARQUIVOS if a["favorito"]]})


@app.route("/api/favorites/toggle", methods=["POST"])
def favorites_toggle():
    if not _logado():
        return _nao_autenticado()
    data = request.get_json(force=True, silent=True) or {}
    arq = _por_id(data.get("id"))
    if not arq:
        return jsonify({"error": "Arquivo não encontrado."}), 404
    arq["favorito"] = not arq["favorito"]
    return jsonify({"status": "sucesso", "favorito": arq["favorito"]})


@app.route("/api/collections", methods=["GET", "POST"])
def collections():
    if not _logado():
        return _nao_autenticado()

    if request.method == "GET":
        saida = []
        for c in _COLECOES:
            capas = [a["caminho"] for a in (_por_id(i) for i in c["files"])
                     if a and a["tipo"] in _EXT_IMG][:4]
            saida.append({"id": c["id"], "nome": c["nome"], "total": len(c["files"]),
                          "criado_em": c["criado_em"], "capas": capas})
        return jsonify({"colecoes": saida})

    data = request.get_json(force=True, silent=True) or {}
    nome = (data.get("nome") or "").strip()
    if not nome:
        return jsonify({"error": "Nome da coleção é obrigatório."}), 400
    if any(c["nome"].lower() == nome.lower() for c in _COLECOES):
        return jsonify({"error": "Você já tem uma coleção com esse nome."}), 409

    novo_id = max((c["id"] for c in _COLECOES), default=0) + 1
    _COLECOES.append({"id": novo_id, "nome": nome,
                      "criado_em": datetime.now().isoformat(), "files": []})
    return jsonify({"status": "ok", "id": novo_id, "nome": nome})


@app.route("/api/collections/<int:col_id>", methods=["GET", "DELETE"])
def collection_detail(col_id):
    if not _logado():
        return _nao_autenticado()
    col = next((c for c in _COLECOES if c["id"] == col_id), None)
    if not col:
        return jsonify({"error": "Coleção não encontrada."}), 404

    if request.method == "DELETE":
        _COLECOES.remove(col)
        return jsonify({"status": "ok"})

    itens = [_item(a) for a in (_por_id(i) for i in col["files"]) if a]
    return jsonify({"resultados": itens})


@app.route("/api/collections/<int:col_id>/files", methods=["POST", "DELETE"])
def collection_files(col_id):
    if not _logado():
        return _nao_autenticado()

    data = request.get_json(force=True, silent=True) or {}
    # Aceita "file_id" (um) ou "file_ids" (lote) — mesma regra do app.py
    if data.get("file_ids") is not None:
        brutos = data.get("file_ids")
        if not isinstance(brutos, list):
            return jsonify({"error": "file_ids deve ser uma lista."}), 400
    else:
        brutos = [data.get("file_id")] if data.get("file_id") else []

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

    col = next((c for c in _COLECOES if c["id"] == col_id), None)
    validos = [n for n in file_ids if _por_id(n)]
    if not col or not validos:
        return jsonify({"error": "Coleção ou arquivo não encontrado."}), 404

    if request.method == "DELETE":
        for n in validos:
            if n in col["files"]:
                col["files"].remove(n)
        return jsonify({"status": "ok", "acao": "removido",
                        "removidos": len(validos)})

    n_add = 0
    for n in validos:
        if n not in col["files"]:
            col["files"].append(n)
            n_add += 1
    return jsonify({"status": "ok", "acao": "adicionado",
                    "adicionados": n_add, "ja_existiam": len(validos) - n_add})


# ──────────────────────────────────────────────────────────────────────────────
# Exportação de coleção (simulada)
# ──────────────────────────────────────────────────────────────────────────────
# NÃO cria pasta nem copia arquivo: o mock existe para desenvolver a interface,
# e um mock que escreve no disco de quem programa é uma armadilha. O progresso
# avança com o tempo e a última imagem "falha", para o caminho de exportação
# parcial ser exercitável sem precisar preparar um cenário.

_EXPORTS = {}


@app.route("/api/collections/<int:col_id>/export", methods=["POST"])
def collection_export(col_id):
    if not _logado():
        return _nao_autenticado()

    data = request.get_json(force=True, silent=True) or {}
    destino = (data.get("destino") or "").strip()
    if not destino:
        return jsonify({"error": "Escolha uma pasta de destino."}), 400

    col = next((c for c in _COLECOES if c["id"] == col_id), None)
    if not col:
        return jsonify({"error": "Coleção não encontrada."}), 404
    if not col["files"]:
        return jsonify({"error": "Esta coleção está vazia. "
                                 "Adicione imagens antes de exportar."}), 400

    for j in _EXPORTS.values():
        if j["collection_id"] == col_id and _estado_simulado(j) == "executando":
            return jsonify({"error": "Esta coleção já está sendo exportada."}), 409

    job_id = uuid.uuid4().hex
    pasta = os.path.join(destino, col["nome"])
    _EXPORTS[job_id] = {
        "collection_id": col_id, "colecao": col["nome"], "pasta": pasta,
        "total": len(col["files"]), "inicio": time.time(),
        "cancelado": False, "cancelado_em": 0,
    }
    return jsonify({"status": "ok", "job_id": job_id,
                    "total": len(col["files"]), "pasta": pasta})


def _progresso_simulado(job):
    """Copiados em função do tempo: ~4 arquivos por segundo."""
    if job["cancelado"]:
        return job["cancelado_em"]
    return min(job["total"], int((time.time() - job["inicio"]) * 4))


def _estado_simulado(job):
    """Estado derivado do tempo. Não fica guardado no dict — só é calculado."""
    if job["cancelado"]:
        return "cancelado"
    return "concluido" if _progresso_simulado(job) >= job["total"] else "executando"


@app.route("/api/collections/export/<job_id>")
def collection_export_status(job_id):
    if not _logado():
        return _nao_autenticado()

    job = _EXPORTS.get(job_id)
    if not job:
        return jsonify({"error": "Exportação não encontrada."}), 404

    feitos = _progresso_simulado(job)
    estado = _estado_simulado(job)

    # A última imagem falha, para exercitar a exportação parcial na interface
    falhas = []
    copiados = feitos
    if estado == "concluido" and job["total"] > 1:
        copiados = job["total"] - 1
        falhas = [{"nome": "imagem_exemplo.jpg", "motivo": "nao_encontrado"}]

    return jsonify({
        "estado": estado, "copiados": copiados, "total": job["total"],
        "falhas": falhas, "pasta": job["pasta"], "colecao": job["colecao"],
        "erro": None,
    })


@app.route("/api/collections/export/<job_id>/cancel", methods=["POST"])
def collection_export_cancel(job_id):
    if not _logado():
        return _nao_autenticado()

    job = _EXPORTS.get(job_id)
    if not job:
        return jsonify({"error": "Exportação não encontrada."}), 404

    if not job["cancelado"]:
        job["cancelado_em"] = _progresso_simulado(job)
        job["cancelado"] = True
    return jsonify({"status": "ok", "copiados": job["cancelado_em"]})


@app.route("/api/open_folder")
def open_folder():
    """No mock não abre nada — só confirma, para o botão ser testável."""
    if not _logado():
        return _nao_autenticado()
    return jsonify({"status": "ok"})


# ──────────────────────────────────────────────────────────────────────────────
# Histórico de busca
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/search_history", methods=["GET", "POST"])
def search_history():
    if not _logado():
        return jsonify({"historico": []})

    if request.method == "GET":
        return jsonify({"historico": _HISTORICO})

    data = request.get_json(force=True, silent=True) or {}
    termo = (data.get("query") or data.get("termo") or "").strip()
    if termo:
        if termo in _HISTORICO:
            _HISTORICO.remove(termo)
        _HISTORICO.insert(0, termo)
        del _HISTORICO[20:]
    return jsonify({"status": "ok", "historico": _HISTORICO})


@app.route("/api/search_history/<int:index>", methods=["DELETE"])
def delete_search_history(index):
    if not _logado():
        return _nao_autenticado()
    if 0 <= index < len(_HISTORICO):
        _HISTORICO.pop(index)
    return jsonify({"status": "ok", "historico": _HISTORICO})


@app.route("/api/clear_history", methods=["POST"])
def clear_history():
    if not _logado():
        return _nao_autenticado()
    _HISTORICO.clear()
    return jsonify({"status": "ok"})


# ──────────────────────────────────────────────────────────────────────────────
# Arquivos
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/file/<path:filepath>")
def serve_file(filepath):
    """Devolve um SVG gerado na hora — o mock não depende de arquivos em disco."""
    if not _logado():
        return _nao_autenticado()

    arq = _por_caminho(filepath)
    if not arq:
        return jsonify({"error": "Arquivo não encontrado."}), 404
    return Response(_svg_placeholder(arq), mimetype="image/svg+xml")


@app.route("/api/choose_folder")
def choose_folder():
    """No backend real isto abre um diálogo nativo do Windows no SERVIDOR."""
    if not _logado():
        return jsonify({"status": "erro", "mensagem": "Não autenticado."}), 401
    return jsonify({"status": "sucesso", "pasta": "C:\\Users\\Demo\\Downloads"})


@app.route("/api/choose_image")
def choose_image():
    if not _logado():
        return jsonify({"status": "erro", "mensagem": "Não autenticado."}), 401
    svg = _svg_placeholder(_ARQUIVOS[0])
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return jsonify({
        "status": "sucesso",
        "caminho": "C:\\Users\\Demo\\Imagens\\avatar.png",
        "data_url": f"data:image/svg+xml;base64,{b64}",
    })


@app.route("/api/open_location")
def open_location():
    if not _logado():
        return _nao_autenticado()
    return jsonify({"status": "ok"})


# ──────────────────────────────────────────────────────────────────────────────
# Motor de indexação
# ──────────────────────────────────────────────────────────────────────────────

@app.route("/api/status")
def status():
    if not _logado():
        return jsonify({"status": "Ocioso", "arquivos_pendentes": 0,
                        "arquivos_processados_sessao": 0})
    return jsonify({"status": "Ocioso", "arquivos_pendentes": 0,
                    "arquivos_processados_sessao": len(_ARQUIVOS)})


@app.route("/api/analyze_folders", methods=["POST"])
def analyze_folders():
    if not _logado():
        return _nao_autenticado()
    return jsonify({"status": "ok", "enfileirados": 0,
                    "mensagem": "Análise iniciada (mock — nada é processado)."})


@app.route("/api/reanalyze", methods=["POST"])
def reanalyze():
    if not _logado():
        return _nao_autenticado()
    return jsonify({"status": "ok", "reenfileirados": 0, "descricoes_limpas": 0})


@app.route("/api/reembed", methods=["POST"])
def reembed():
    if not _logado():
        return _nao_autenticado()
    return jsonify({"status": "ok", "atualizados": 0})


@app.route("/api/cancel_analysis", methods=["POST"])
def cancel_analysis():
    if not _logado():
        return _nao_autenticado()
    return jsonify({"status": "ok", "descartados": 0})


@app.route("/api/clear_cache", methods=["POST"])
def clear_cache():
    if not _logado():
        return _nao_autenticado()
    return jsonify({"status": "ok"})


@app.route("/api/debug/files")
def debug_files():
    if not _logado():
        return _nao_autenticado()
    return jsonify({"total": len(_ARQUIVOS), "arquivos": [_item(a) for a in _ARQUIVOS]})


@app.route("/api/debug/scores")
def debug_scores():
    if not _logado():
        return _nao_autenticado()
    return jsonify({"query": request.args.get("q", ""), "detalhes": []})


# ──────────────────────────────────────────────────────────────────────────────
# Frontend
# ──────────────────────────────────────────────────────────────────────────────
#
# O mock serve o frontend além da API, e é isso que permite abrir
# http://127.0.0.1:5001 e ver o aplicativo inteiro funcionando com dados
# fictícios — sem Postgres, sem os modelos de IA e sem chave de API.
#
# Mesmas regras de segurança do backend real: allowlist de extensões, porque a
# pasta servida é a raiz do projeto e ela contém backend/.env e .git/.

_EXT_PUBLICAS = {
    ".html", ".htm", ".css", ".js", ".mjs", ".cjs", ".map", ".json", ".wasm",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico", ".avif",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp4", ".webm", ".mp3", ".ogg", ".wav",
    ".txt", ".webmanifest", ".xml",
}
_PASTAS_PRIVADAS = {"backend", "docs", "node_modules", "venv", "__pycache__"}


def _pode_servir(rel: Path) -> bool:
    partes = rel.parts
    if any(p.startswith(".") for p in partes):
        return False
    if any(p.lower() in _PASTAS_PRIVADAS for p in partes[:-1]):
        return False
    return rel.suffix.lower() in _EXT_PUBLICAS


@app.route("/")
def raiz():
    return send_from_directory(str(FRONTEND_DIR), "index.html")


@app.route("/__mock__")
def info_mock():
    """Lista os endpoints simulados — útil para conferir o contrato."""
    rotas = sorted({r.rule for r in app.url_map.iter_rules() if r.rule.startswith("/api")})
    return jsonify({
        "servidor": "Search+ MOCK",
        "aviso": "Dados fictícios em memória. O backend real é backend/app.py.",
        "endpoints": rotas,
    })


@app.route("/<path:filename>")
def serve_static(filename):
    if filename.startswith("api/"):
        return jsonify({"error": "not found"}), 404

    destino = (FRONTEND_DIR / filename).resolve()
    if FRONTEND_DIR not in destino.parents and destino != FRONTEND_DIR:
        return jsonify({"error": "not found"}), 404

    rel = destino.relative_to(FRONTEND_DIR)
    if destino.is_file():
        if not _pode_servir(rel):
            return jsonify({"error": "not found"}), 404
        return send_from_directory(str(FRONTEND_DIR), rel.as_posix())

    # Sem extensão = rota de SPA: entrega o index.html e deixa o roteador do
    # frontend resolver. Com extensão, é um arquivo que realmente não existe.
    if rel.suffix:
        return jsonify({"error": "not found"}), 404
    return send_from_directory(str(FRONTEND_DIR), "index.html")


if __name__ == "__main__":
    porta = int(os.environ.get("MOCK_PORT", "5001"))
    print("=" * 62)
    print("  Search+ — SERVIDOR MOCK (dados fictícios, sem banco e sem IA)")
    print(f"  Aplicativo: http://127.0.0.1:{porta}")
    print(f"  Endpoints:  http://127.0.0.1:{porta}/__mock__")
    print("  Login: qualquer usuário e senha são aceitos.")
    print("=" * 62)
    app.run(host="127.0.0.1", port=porta, debug=False)
