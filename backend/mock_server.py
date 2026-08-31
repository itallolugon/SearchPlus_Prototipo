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


def _origem_falsa(arq: dict) -> str:
    """
    Por que o resultado apareceu.

    O mock nao tem motor de busca, entao deriva do tipo do arquivo: imagem vem
    "pela aparencia", o resto "pelo texto do documento". O que importa aqui e
    o front receber origens DIFERENTES e conseguir desenhar as duas badges sem
    depender do motor real.
    """
    return "aparencia" if arq["tipo"] in _EXT_IMG else "texto"


def _item(arq: dict, score: float = 1.0) -> dict:
    """Formato padrão de resultado, idêntico ao do backend real."""
    desc = arq["descricao_ia"]
    return {
        "id": arq["id"], "nome": arq["nome"], "caminho": arq["caminho"],
        "tipo": arq["tipo"], "descricao_ia": desc, "conteudo": desc,
        "trecho": desc[:200], "data": arq["data"],
        "favorito": bool(arq["favorito"]), "score": round(score, 4),
        "origem": _origem_falsa(arq),
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


# Pastas ja verificadas nesta execucao do mock. A verificacao concilia o que
# achou, entao rodar de novo na mesma pasta tem que vir limpo -- e e justamente
# o estado "nada mudou" que o front precisa saber desenhar.
_PASTAS_VERIFICADAS: set[int] = set()


@app.route("/api/folders/<int:folder_id>/verificar", methods=["POST"])
def verificar_pasta(folder_id):
    if not _logado():
        return _nao_autenticado()

    pasta = next((p for p in _PASTAS if p["id"] == folder_id), None)
    if not pasta:
        return jsonify({"error": "Pasta não encontrada."}), 404

    if folder_id in _PASTAS_VERIFICADAS:
        achados = {"novos": [], "modificados": [], "ausentes": [], "voltaram": []}
    else:
        # O mock não tem disco: entrega um resultado plausível uma vez, para o
        # front conseguir desenhar a tela de "achei isto aqui" sem depender de
        # alguém ir mexer em arquivo de verdade.
        _PASTAS_VERIFICADAS.add(folder_id)
        achados = {
            "novos": ["foto-nova.jpg", "orcamento-revisado.pdf"],
            "modificados": ["praia-por-do-sol.jpg"],
            "ausentes": ["arquivo-apagado.png"],
            "voltaram": [],
        }

    return jsonify({
        "status": "ok",
        "pasta": pasta["path"],
        **achados,
        "resumo": {chave: len(lista) for chave, lista in achados.items()},
    })


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

def _separar_exclusoes(query):
    """
    Separa "praia -pessoas" em ("praia", ["pessoas"]).

    Mesma regra do backend real: o hifen so conta colado a uma palavra e
    precedido de espaco. Se divergir, o front acerta contra um servidor e erra
    contra o outro -- e a trilha de refino mostra uma coisa que nao aconteceu.
    """
    if not query:
        return "", []
    excluidos, restantes = [], []
    for pedaco in query.split():
        if pedaco.startswith("-"):
            termo = pedaco[1:].strip()
            if termo:
                excluidos.append(termo)
        else:
            restantes.append(pedaco)
    return " ".join(restantes), excluidos


@app.route("/api/search", methods=["GET", "POST"])
def search():
    if not _logado():
        return _nao_autenticado()

    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
        query = (data.get("query") or "").strip()
        filtro = data.get("filtro", "all")
        escopo = data.get("escopo") or []
        avancado = data.get("avancado") or {}
    else:
        query = (request.args.get("q") or "").strip()
        filtro = request.args.get("filtro", "all")
        escopo = []
        avancado = {}

    # "praia -pessoas": mesma separacao do backend real.
    query, excluidos = _separar_exclusoes(query)

    escopo_ids = set()
    for i in escopo[:5000]:
        try:
            escopo_ids.add(int(i))
        except (TypeError, ValueError):
            continue

    if not query:
        if excluidos:
            return jsonify({
                "resultados": [], "tempo": 0, "consulta": "",
                "excluidos": excluidos, "escopo": len(escopo_ids),
                "erro": "Diga também o que você procura. Sozinho, o traço só "
                        "serve para tirar algo de uma busca — por exemplo, "
                        "“praia -pessoas”.",
            })
        return jsonify({"resultados": [], "tempo": 0})

    t0 = time.time()
    termos = [t for t in query.lower().split() if len(t) >= 3]

    candidatos = _ARQUIVOS
    if escopo_ids:
        candidatos = [a for a in candidatos if a["id"] in escopo_ids]
    if avancado.get("so_favoritos"):
        candidatos = [a for a in candidatos if a["favorito"]]
    if filtro == "imagem":
        candidatos = [a for a in candidatos if a["tipo"] in _EXT_IMG]
    elif filtro == "midia":
        candidatos = [a for a in candidatos if a["tipo"] in _EXT_VID | _EXT_AUD]
    elif filtro == "documento":
        candidatos = [a for a in candidatos
                      if a["tipo"] not in _EXT_IMG | _EXT_VID | _EXT_AUD]

    # Score por quantidade de termos encontrados na descrição/nome.
    excluidos_lower = [e.lower() for e in excluidos if e]

    achados = []
    for a in candidatos:
        alvo = (a["descricao_ia"] + " " + a["nome"]).lower()
        # O que o usuario mandou tirar sai antes de disputar posicao.
        if any(e in alvo for e in excluidos_lower):
            continue
        acertos = sum(1 for t in termos if t in alvo)
        if acertos:
            achados.append((a, 0.55 + 0.4 * (acertos / max(1, len(termos)))))

    achados.sort(key=lambda x: x[1], reverse=True)
    resultados = [_item(a, s) for a, s in achados]

    # Simula a latência de uma busca real (SBERT + CLIP + re-rank do Claude).
    time.sleep(0.25)
    return jsonify({
        "resultados": resultados, "tempo": round(time.time() - t0, 3),
        "consulta": query, "excluidos": excluidos, "escopo": len(escopo_ids),
    })


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


def _pasta_do_arquivo(arq):
    """
    A qual pasta indexada o arquivo pertence.

    O mock nao guarda folder_id nos arquivos; deriva do caminho, que e o que
    o backend real tem gravado de qualquer jeito.
    """
    caminho = (arq.get("caminho") or "").lower()
    for p in _PASTAS:
        if caminho.startswith(p["path"].lower()):
            return p["id"]
    return None


@app.route("/api/files/validos", methods=["POST"])
def files_validos():
    if not _logado():
        return _nao_autenticado()
    data = request.get_json(force=True, silent=True) or {}
    brutos = data.get("ids")
    if not isinstance(brutos, list):
        return jsonify({"error": "ids deve ser uma lista."}), 400
    validos = []
    for i in brutos[:5000]:
        try:
            n = int(i)
        except (TypeError, ValueError):
            continue
        if _por_id(n):
            validos.append(n)
    return jsonify({"ids": validos})


@app.route("/api/gallery")
def gallery():
    if not _logado():
        return _nao_autenticado()

    pedidas = []
    for pedaco in (request.args.get("pastas") or "").split(","):
        pedaco = pedaco.strip()
        if pedaco:
            try:
                pedidas.append(int(pedaco))
            except ValueError:
                continue

    def visivel(arq):
        return not pedidas or _pasta_do_arquivo(arq) in pedidas

    grupos = []
    usados = set()
    for cat, ids in _CATEGORIAS.items():
        itens = [_item(_por_id(i)) for i in ids
                 if _por_id(i) and visivel(_por_id(i))]
        if itens:
            grupos.append({"categoria": cat, "total": len(itens), "itens": itens})
        usados.update(ids)

    outras = [_item(a) for a in _ARQUIVOS
              if a["tipo"] in _EXT_IMG and a["id"] not in usados and visivel(a)]
    if outras:
        grupos.append({"categoria": "outras", "total": len(outras), "itens": outras})

    imagens = [a for a in _ARQUIVOS if a["tipo"] in _EXT_IMG]
    pastas = []
    for p in _PASTAS:
        pastas.append({
            "id": p["id"],
            "nome": p["path"].rstrip("\\/").split("\\")[-1] or p["path"],
            "caminho": p["path"],
            "imagens": len([a for a in imagens if _pasta_do_arquivo(a) == p["id"]]),
        })

    return jsonify({
        "grupos": grupos,
        "total_imagens": len([a for a in imagens if visivel(a)]),
        "pastas": pastas,
        "pastas_ativas": pedidas,
    })


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
            # Capa escolhida a dedo. Se a imagem sumiu, volta ao mosaico --
            # mesmo comportamento do LEFT JOIN no backend real.
            escolhida = _por_id(c.get("capa_file_id")) if c.get("capa_file_id") else None
            saida.append({"id": c["id"], "nome": c["nome"], "total": len(c["files"]),
                          "criado_em": c["criado_em"], "capas": capas,
                          "capa": escolhida["caminho"] if escolhida else "",
                          "capa_file_id": c.get("capa_file_id"),
                          "pasta_vinculada": c.get("pasta_vinculada"),
                          "modo_sync": c.get("modo_sync", "manual")})

        # Mesmas ordens do backend real. Nome desconhecido cai no padrao.
        ordem = (request.args.get("ordem") or "").strip()
        if ordem == "antigas":
            saida.sort(key=lambda x: x["criado_em"])
        elif ordem == "nome":
            saida.sort(key=lambda x: x["nome"].lower())
        elif ordem == "tamanho":
            saida.sort(key=lambda x: (-x["total"], x["nome"].lower()))
        else:
            saida.sort(key=lambda x: x["criado_em"], reverse=True)

        return jsonify({"colecoes": saida})

    data = request.get_json(force=True, silent=True) or {}
    nome = (data.get("nome") or "").strip()
    if not nome:
        return jsonify({"error": "Nome da coleção é obrigatório."}), 400
    if any(c["nome"].lower() == nome.lower() for c in _COLECOES):
        return jsonify({"error": "Você já tem uma coleção com esse nome."}), 409

    novo_id = max((c["id"] for c in _COLECOES), default=0) + 1
    _COLECOES.append({"id": novo_id, "nome": nome,
                      "criado_em": datetime.now().isoformat(), "files": [],
                      "pasta_vinculada": None, "modo_sync": "manual"})
    return jsonify({"status": "ok", "id": novo_id, "nome": nome,
                    "pasta_vinculada": None, "modo_sync": "manual"})


@app.route("/api/collections/<int:col_id>", methods=["GET", "DELETE", "PATCH"])
def collection_detail(col_id):
    if not _logado():
        return _nao_autenticado()
    col = next((c for c in _COLECOES if c["id"] == col_id), None)
    if not col:
        return jsonify({"error": "Coleção não encontrada."}), 404

    if request.method == "DELETE":
        lixeira_id = _para_lixeira("colecao", col["nome"], {
            "id": col["id"], "nome": col["nome"],
            "criado_em": col.get("criado_em"),
            "pasta_vinculada": col.get("pasta_vinculada"),
            "modo_sync": col.get("modo_sync", "manual"),
            "arquivos": [{"file_id": f, "adicionado_em": None} for f in col["files"]],
        })
        _COLECOES.remove(col)
        return jsonify({"status": "ok", "lixeira_id": lixeira_id, "nome": col["nome"]})

    if request.method == "PATCH":
        data = request.get_json(force=True, silent=True) or {}
        campos = 0
        if "capa_file_id" in data:
            capa = data.get("capa_file_id")
            if capa is None:
                col["capa_file_id"] = None
            else:
                try:
                    capa = int(capa)
                except (TypeError, ValueError):
                    return jsonify({"error": "Imagem de capa inválida."}), 400
                if capa not in col["files"]:
                    return jsonify({
                        "error": "Escolha uma imagem que esteja nesta coleção."
                    }), 400
                col["capa_file_id"] = capa
            campos += 1
        renomeadas, ignoradas = [], []
        if "nome" in data:
            nome = (data.get("nome") or "").strip()
            if not nome:
                return jsonify({"error": "Nome da coleção é obrigatório."}), 400
            if any(c["nome"].lower() == nome.lower() and c["id"] != col_id
                   for c in _COLECOES):
                return jsonify({"error": "Você já tem uma coleção com esse nome."}), 409

            # Cascata nas pastas — SIMULADA, nada renomeado em disco. O mock
            # precisa reproduzir isto: sem ele o frontend seria desenvolvido
            # contra um comportamento que o backend real não tem.
            antigo = col["nome"]
            if data.get("renomear_pastas") and antigo != nome:
                geradas = col.get("pastas_geradas") or []
                for i, caminho in enumerate(list(geradas)):
                    base = caminho.rsplit("\\", 1)[-1]
                    mae = caminho.rsplit("\\", 1)[0]
                    # Mesma regra do backend real: pasta que nao deriva do
                    # nome antigo NAO e renomeada — senao duas disputariam o
                    # mesmo nome novo.
                    if base == antigo:
                        sufixo = ""
                    elif base.startswith(antigo + "_"):
                        sufixo = base[len(antigo) + 1:]
                    else:
                        ignoradas.append(base)
                        continue
                    novo_base = f"{nome}_{sufixo}" if sufixo else nome
                    novo = mae + "\\" + novo_base
                    geradas[i] = novo
                    if col.get("pasta_vinculada") == caminho:
                        col["pasta_vinculada"] = novo
                    recebem = col.get("pastas_que_recebem") or []
                    if caminho in recebem:
                        recebem[recebem.index(caminho)] = novo
                    renomeadas.append({"de": base, "para": novo_base})

            col["nome"] = nome
            campos += 1
        if data.get("criar_pasta_em"):
            # Simulado: NÃO cria pasta no disco de quem desenvolve.
            # Devolve o caminho que o backend real criaria.
            base = str(data["criar_pasta_em"]).rstrip("\\/")
            col["pasta_vinculada"] = base + "\\" + col["nome"]
            col.setdefault("pastas_geradas", [])
            if col["pasta_vinculada"] not in col["pastas_geradas"]:
                col["pastas_geradas"].append(col["pasta_vinculada"])
            campos += 1
        elif "pasta_vinculada" in data:
            pasta = data.get("pasta_vinculada")
            # O mock aceita qualquer caminho: não toca o disco, então não
            # há o que validar. O backend real exige que a pasta exista.
            if pasta is None or not str(pasta).strip():
                col["pasta_vinculada"] = None
                col["modo_sync"] = "manual"
            else:
                col["pasta_vinculada"] = str(pasta).strip()
            campos += 1
        if "modo_sync" in data:
            modo = (data.get("modo_sync") or "").strip()
            if modo not in {"auto", "perguntar", "manual"}:
                return jsonify({"error": "Modo de sincronia inválido."}), 400
            col["modo_sync"] = modo
            campos += 1
        if "pastas_que_recebem" in data:
            bruto = data.get("pastas_que_recebem")
            if not isinstance(bruto, list):
                return jsonify({"error": "pastas_que_recebem deve ser uma lista."}), 400
            geradas = col.get("pastas_geradas") or []
            alvos = [c for c in bruto if c in geradas]
            col["pastas_que_recebem"] = alvos
            col["pasta_vinculada"] = alvos[0] if alvos else None
            campos += 1
        if not campos:
            return jsonify({"error": "Nada para atualizar."}), 400
        return jsonify({"status": "ok", "id": col["id"], "nome": col["nome"],
                        "pasta_vinculada": col.get("pasta_vinculada"),
                        "pastas_que_recebem": col.get("pastas_que_recebem") or [],
                        "modo_sync": col.get("modo_sync", "manual"),
                        "pastas_renomeadas": renomeadas,
                        "pastas_com_falha": [],
                        "pastas_ignoradas": ignoradas})

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
        estavam = [n for n in validos if n in col["files"]]
        lixeira_id = None
        if estavam:
            rotulo = (f"{len(estavam)} imagem de “{col['nome']}”"
                      if len(estavam) == 1
                      else f"{len(estavam)} imagens de “{col['nome']}”")
            lixeira_id = _para_lixeira("itens", rotulo, {
                "collection_id": col["id"], "colecao": col["nome"],
                "arquivos": [{"file_id": n, "adicionado_em": None} for n in estavam],
            })
        for n in validos:
            if n in col["files"]:
                col["files"].remove(n)
        nomes = [a["nome"] for a in (_por_id(n) for n in validos) if a]
        return jsonify({"status": "ok", "acao": "removido",
                        "removidos": len(validos),
                        "nomes_removidos": nomes,
                        "lixeira_id": lixeira_id,
                        "modo_sync": col.get("modo_sync", "manual"),
                        "pastas_que_recebem": col.get("pastas_que_recebem") or []})

    n_add, adicionados_ids = 0, []
    for n in validos:
        if n not in col["files"]:
            col["files"].append(n)
            adicionados_ids.append(n)
            n_add += 1
    return jsonify({"status": "ok", "acao": "adicionado",
                    "adicionados": n_add, "ja_existiam": len(validos) - n_add,
                    "ids_adicionados": adicionados_ids,
                    "pasta_vinculada": col.get("pasta_vinculada"),
                    "modo_sync": col.get("modo_sync", "manual")})


@app.route("/api/collections/<int:col_id>/folders", methods=["GET"])
def collection_folders(col_id):
    """Pastas geradas — SIMULADAS. Nada é lido do disco de quem desenvolve."""
    if not _logado():
        return _nao_autenticado()
    col = next((c for c in _COLECOES if c["id"] == col_id), None)
    if not col:
        return jsonify({"error": "Coleção não encontrada."}), 404

    geradas = col.get("pastas_geradas") or []
    # Conjunto de destinos; cai no campo antigo para coleções criadas antes.
    vinc = col.get("pasta_vinculada")
    recebem = col.get("pastas_que_recebem")
    if recebem is None:
        recebem = [vinc] if vinc else []
    return jsonify({"pastas": [
        {"caminho": c, "nome": c.rstrip("\\/").split("\\")[-1],
         "existe": True,
         "recebe": c in recebem, "vinculada": c in recebem,
         "arquivos": len(col["files"])}
        for c in geradas
    ]})


@app.route("/api/collections/<int:col_id>/folders", methods=["PATCH"])
def collection_folder_rename(col_id):
    """
    Trocar o complemento do nome — SIMULADO. Nada é renomeado no disco.

    Reproduz o contrato: prefixo continua sendo o nome da coleção, e nome já em
    uso devolve 409 para o frontend exercitar esse caminho.
    """
    if not _logado():
        return _nao_autenticado()

    data = request.get_json(force=True, silent=True) or {}
    caminho = str(data.get("caminho") or "").strip()
    if not caminho:
        return jsonify({"error": "Informe a pasta."}), 400
    if "sufixo" not in data:
        return jsonify({"error": "Informe o novo complemento."}), 400

    col = next((c for c in _COLECOES if c["id"] == col_id), None)
    if not col:
        return jsonify({"error": "Coleção não encontrada."}), 404

    geradas = col.get("pastas_geradas") or []
    if caminho not in geradas:
        return jsonify({"error": "Pasta não autorizada."}), 403

    sufixo = str(data.get("sufixo") or "").strip()
    novo_nome = f'{col["nome"]}_{sufixo}' if sufixo else col["nome"]
    mae = caminho.rsplit("\\", 1)[0]
    novo = mae + "\\" + novo_nome

    if novo != caminho and novo in geradas:
        return jsonify({"error": f'Já existe uma pasta chamada "{novo_nome}" nesse local.'}), 409

    geradas[geradas.index(caminho)] = novo
    if col.get("pasta_vinculada") == caminho:
        col["pasta_vinculada"] = novo
    recebem = col.get("pastas_que_recebem") or []
    if caminho in recebem:
        recebem[recebem.index(caminho)] = novo

    return jsonify({"status": "ok", "caminho": novo,
                    "nome": novo_nome, "sufixo": sufixo})


@app.route("/api/collections/<int:col_id>/folders", methods=["DELETE"])
def collection_folders_delete(col_id):
    """
    Exclusão de pastas — SIMULADA. NENHUM diretório é removido do disco.

    O mock existe para desenvolver a interface; um mock que apaga pasta de
    verdade na máquina de quem programa seria a pior armadilha possível.
    As travas de contrato (confirmação e lista fechada) são reproduzidas,
    para o frontend exercitar os caminhos de recusa.
    """
    if not _logado():
        return _nao_autenticado()

    data = request.get_json(force=True, silent=True) or {}
    if data.get("confirmar") is not True:
        return jsonify({"error": "Confirmação obrigatória para apagar pastas."}), 400

    pedidos = data.get("caminhos")
    if not isinstance(pedidos, list) or not pedidos:
        return jsonify({"error": "Escolha ao menos uma pasta."}), 400

    col = next((c for c in _COLECOES if c["id"] == col_id), None)
    if not col:
        return jsonify({"error": "Coleção não encontrada."}), 404

    geradas = col.get("pastas_geradas") or []
    apagadas, falhas = [], []
    for c in pedidos:
        if c in geradas:
            geradas.remove(c)
            apagadas.append(c)
            if col.get("pasta_vinculada") == c:
                col["pasta_vinculada"] = None
                col["modo_sync"] = "manual"
        else:
            falhas.append({"caminho": c, "motivo": "nao_autorizada"})
    col["pastas_geradas"] = geradas
    return jsonify({"status": "ok", "apagadas": apagadas, "falhas": falhas})


@app.route("/api/collections/<int:col_id>/sync_status")
def collection_sync_status(col_id):
    """
    Diff coleção x pasta — SIMULADO, sem ler o disco.

    Divide os arquivos da coleção em "já na pasta" e "faltando" de forma
    determinística (índices pares/ímpares), para o frontend exercitar as duas
    listas, a barra de progresso e o botão de copiar o que falta.
    """
    if not _logado():
        return _nao_autenticado()
    col = next((c for c in _COLECOES if c["id"] == col_id), None)
    if not col:
        return jsonify({"error": "Coleção não encontrada."}), 404

    itens = [a for a in (_por_id(i) for i in col["files"]) if a]
    recebem = col.get("pastas_que_recebem") or []
    pastas = []
    for idx, c in enumerate(col.get("pastas_geradas") or []):
        # A primeira pasta fica completa; as demais, com metade — assim as duas
        # situacoes aparecem na tela sem precisar montar cenario.
        if idx == 0:
            dentro, fora = itens, []
        else:
            dentro = [a for i, a in enumerate(itens) if i % 2 == 0]
            fora = [a for i, a in enumerate(itens) if i % 2 == 1]
        pastas.append({
            "caminho": c, "nome": c.rstrip("\\/").split("\\")[-1],
            "existe": True, "recebe": c in recebem,
            "na_pasta": [{"id": a["id"], "nome": a["nome"]} for a in dentro],
            "faltando": [{"id": a["id"], "nome": a["nome"]} for a in fora],
            "extras": ["antiga.jpg"] if idx == 0 and itens else [],
        })

    return jsonify({"total_colecao": len(itens),
                    "modo_sync": col.get("modo_sync", "manual"),
                    "pastas": pastas})


@app.route("/api/collections/<int:col_id>/sync", methods=["POST", "DELETE"])
def collection_sync(col_id):
    """
    Sincronia com a pasta vinculada — SIMULADA.

    Nenhuma pasta é criada e nenhum arquivo é copiado nem apagado: o mock
    existe para desenvolver a interface. Devolve contagens plausíveis para o
    frontend exercitar os três modos e as mensagens de resultado.

    DELETE simula a remoção das cópias — sem tocar em disco nenhum.
    """
    if not _logado():
        return _nao_autenticado()

    if request.method == "DELETE":
        data = request.get_json(force=True, silent=True) or {}
        nomes = data.get("nomes")
        if not isinstance(nomes, list) or not nomes:
            return jsonify({"error": "Informe os nomes a remover."}), 400
        col_ = next((c for c in _COLECOES if c["id"] == col_id), None)
        if not col_:
            return jsonify({"error": "Coleção não encontrada."}), 404
        destinos_ = col_.get("pastas_que_recebem") or []
        return jsonify({"status": "ok",
                        "apagados": len(nomes) * len(destinos_),
                        "falhas": [], "pastas": destinos_})

    if False:
        return _nao_autenticado()

    col = next((c for c in _COLECOES if c["id"] == col_id), None)
    if not col:
        return jsonify({"error": "Coleção não encontrada."}), 404

    destinos = col.get("pastas_que_recebem")
    if destinos is None:
        destinos = [col["pasta_vinculada"]] if col.get("pasta_vinculada") else []
    if not destinos:
        return jsonify({"error": "Esta coleção não tem pasta recebendo imagens."}), 400
    pasta = destinos[0]

    data = request.get_json(force=True, silent=True) or {}
    brutos = data.get("file_ids")
    if brutos is None:
        alvos = list(col["files"])
    else:
        if not isinstance(brutos, list):
            return jsonify({"error": "file_ids deve ser uma lista."}), 400
        try:
            alvos = [int(b) for b in brutos]
        except (TypeError, ValueError):
            return jsonify({"error": "Identificador de arquivo inválido."}), 400

    copiados = [n for n in alvos if _por_id(n)]
    # Um item "some do disco" quando há mais de 2, para o caminho de falha
    # parcial ser exercitável sem precisar montar cenário.
    falhas = []
    if len(copiados) > 2:
        sumido = _por_id(copiados[-1])
        copiados = copiados[:-1]
        if sumido:
            falhas.append({"nome": sumido["nome"], "motivo": "nao_encontrado"})

    return jsonify({"status": "ok", "copiados": len(copiados) * len(destinos),
                    "ja_existiam": 0, "falhas": falhas,
                    "pastas": destinos, "pasta": pasta})


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

    # Mesmas validacoes e o mesmo filtro do backend real -- o front precisa
    # receber os MESMOS erros aqui, senao acerta contra um servidor e erra
    # contra o outro.
    tipos = (data.get("tipos") or "tudo").strip().lower()
    if tipos not in {"tudo", "imagens", "documentos"}:
        return jsonify({"error": "Tipo de arquivo desconhecido."}), 400

    largura = data.get("largura_max")
    if largura not in (None, ""):
        try:
            largura = int(largura)
        except (TypeError, ValueError):
            return jsonify({"error": "A largura precisa ser um número."}), 400
        if not (100 <= largura <= 10000):
            return jsonify({
                "error": "A largura precisa ficar entre 100 e 10000 pixels."
            }), 400

    arquivos = [a for a in (_por_id(i) for i in col["files"]) if a]
    if tipos == "imagens":
        arquivos = [a for a in arquivos if a["tipo"] in _EXT_IMG]
    elif tipos == "documentos":
        arquivos = [a for a in arquivos
                    if a["tipo"] not in _EXT_IMG | _EXT_VID | _EXT_AUD]
    if not arquivos:
        rotulo = "Nenhuma imagem" if tipos == "imagens" else "Nenhum documento"
        return jsonify({
            "error": f"{rotulo} nesta coleção. Escolha outro tipo de arquivo."
        }), 400

    for j in _EXPORTS.values():
        if j["collection_id"] == col_id and _estado_simulado(j) == "executando":
            return jsonify({"error": "Esta coleção já está sendo exportada."}), 409

    job_id = uuid.uuid4().hex
    # Mesma nomeacao do backend real: o nome da colecao e sempre o prefixo.
    geradas_ate_agora = col.get("pastas_geradas") or []
    sufixo = str(data.get("sufixo") or "").strip()
    if sufixo:
        base = f'{col["nome"]}_{sufixo}'
    elif geradas_ate_agora:
        base = f'{col["nome"]}_{len(geradas_ate_agora) + 1}'
    else:
        base = col["nome"]
    pasta = os.path.join(destino, base)
    _EXPORTS[job_id] = {
        "collection_id": col_id, "colecao": col["nome"], "pasta": pasta,
        # O total reflete o FILTRO por tipo, como no backend real: dizer
        # "12 arquivos" e copiar 5 faria a barra de progresso mentir.
        "total": len(arquivos), "inicio": time.time(),
        "cancelado": False, "cancelado_em": 0,
    }

    # Registra e vincula, como o backend real. Sem isto o mock reproduziria o
    # bug que a feature corrige: exportar sem memória, e as imagens
    # adicionadas depois não teriam para onde ir.
    col.setdefault("pastas_geradas", [])
    if pasta not in col["pastas_geradas"]:
        col["pastas_geradas"].append(pasta)
    # `vincular` decide o destino das proximas fotos — ver docs/API.md
    vincular = data.get("vincular")
    col.setdefault("pastas_que_recebem",
                   [col["pasta_vinculada"]] if col.get("pasta_vinculada") else [])
    if vincular is True:
        if pasta not in col["pastas_que_recebem"]:
            col["pastas_que_recebem"].append(pasta)
        col["pasta_vinculada"] = col["pastas_que_recebem"][0]
        if col.get("modo_sync", "manual") == "manual":
            col["modo_sync"] = "perguntar"
    elif vincular is None and not col["pastas_que_recebem"]:
        col["pastas_que_recebem"] = [pasta]
        col["pasta_vinculada"] = pasta
        col["modo_sync"] = "perguntar"

    return jsonify({"status": "ok", "job_id": job_id,
                    "total": len(arquivos), "pasta": pasta})


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
    """
    Abrir no Explorer — SIMULADO, nada é aberto.

    Reproduz o CONTRATO de validação do backend real: caminho vazio dá 400.
    A checagem contra as pastas monitoradas não é reproduzida porque o mock não
    tem pastas de verdade — mas o frontend precisa exercitar o 400 e o 403.
    """
    if not _logado():
        return _nao_autenticado()
    caminho = (request.args.get("path") or "").strip()
    if not caminho:
        return jsonify({"error": "Caminho não informado."}), 400
    # Caminho fora do acervo de exemplo: mesma recusa do backend real.
    if not any(caminho.startswith(b) for b in (_BASE, _DOCS)):
        return jsonify({"error": "Arquivo fora das pastas monitoradas."}), 403
    return jsonify({"status": "ok"})


# ──────────────────────────────────────────────────────────────────────────────
# Motor de indexação
# ──────────────────────────────────────────────────────────────────────────────

# Fila simulada. O mock nao indexa nada, mas o front precisa conseguir desenhar
# a barra de progresso COM a estimativa -- e ver o numero cair -- sem depender
# de alguem ter uma pasta de dez mil fotos a mao.
#
# Comeca zerada: quem so quer mexer nas colecoes nao precisa ver uma barra de
# indexacao inventada. POST /api/analyze_folders enche a fila, e cada consulta
# de status drena um pouco, como o worker de verdade faria.
_FILA_SIMULADA = [0]
_RITMO_SIMULADO = 0.9      # segundos por arquivo


def _texto_do_restante(pendentes, segundos_por_arquivo):
    """Mesmas faixas do backend real -- se divergirem, o front mente numa delas."""
    if pendentes <= 0:
        return ""
    restante = pendentes * segundos_por_arquivo
    if restante < 60:
        return "quase terminando"
    minutos = restante / 60
    if minutos < 10:
        return f"\u2248 {round(minutos)} min restantes"
    if minutos < 60:
        return f"\u2248 {int(round(minutos / 5) * 5)} min restantes"
    horas = minutos / 60
    if horas < 2:
        return "\u2248 1 hora restante"
    return f"\u2248 {round(horas)} horas restantes"


def _drenar_fila_simulada():
    if _FILA_SIMULADA[0] > 0:
        _FILA_SIMULADA[0] = max(0, _FILA_SIMULADA[0] - 37)
        if _FILA_SIMULADA[0] == 0:
            # Fila zerou: o resumo fica disponivel, como no backend real.
            _fechar_resumo_simulado()
    return _FILA_SIMULADA[0]


@app.route("/api/status")
def status():
    if not _logado():
        return jsonify({"status": "Ocioso", "arquivos_pendentes": 0,
                        "restante_texto": "", "segundos_por_arquivo": 0.5,
                        "arquivos_processados_sessao": 0})

    pendentes = _drenar_fila_simulada()
    return jsonify({
        "status": "Indexando" if pendentes else "Ocioso",
        "arquivos_pendentes": pendentes,
        "restante_texto": _texto_do_restante(pendentes, _RITMO_SIMULADO),
        "segundos_por_arquivo": _RITMO_SIMULADO,
        "arquivos_processados_sessao": len(_ARQUIVOS),
    })


# Lixeira do mock. Reproduz o que importa para o front: excluir devolve um
# lixeira_id, restaurar traz a colecao de volta com o mesmo id, e restaurar
# duas vezes o mesmo item da 404.
_LIXEIRA = []
_PROX_LIXEIRA = [1]


def _para_lixeira(tipo, rotulo, conteudo):
    item = {"id": _PROX_LIXEIRA[0], "tipo": tipo, "rotulo": rotulo,
            "conteudo": conteudo, "excluido_em": _HOJE.isoformat()}
    _PROX_LIXEIRA[0] += 1
    _LIXEIRA.append(item)
    return item["id"]


@app.route("/api/lixeira", methods=["GET"])
def lixeira():
    if not _logado():
        return _nao_autenticado()
    return jsonify({
        "dias": 30,
        "itens": [{"id": i["id"], "tipo": i["tipo"], "rotulo": i["rotulo"],
                   "imagens": len(i["conteudo"].get("arquivos") or []),
                   "excluido_em": i["excluido_em"]}
                  for i in reversed(_LIXEIRA)],
    })


@app.route("/api/lixeira/<int:item_id>/restaurar", methods=["POST"])
def lixeira_restaurar(item_id):
    if not _logado():
        return _nao_autenticado()

    item = next((i for i in _LIXEIRA if i["id"] == item_id), None)
    if not item:
        return jsonify({"error": "Este item não está mais na lixeira."}), 404

    conteudo = item["conteudo"]
    if item["tipo"] == "colecao":
        if any(c["nome"].lower() == (conteudo.get("nome") or "").lower()
               for c in _COLECOES):
            return jsonify({
                "error": "Você criou outra coleção com esse nome depois de "
                         "excluir esta. Renomeie a atual e tente restaurar de novo."
            }), 409
        _COLECOES.append({
            "id": conteudo["id"], "nome": conteudo["nome"],
            "criado_em": conteudo.get("criado_em") or _HOJE.isoformat(),
            "files": [a["file_id"] for a in conteudo.get("arquivos") or []],
            "pasta_vinculada": conteudo.get("pasta_vinculada"),
            "modo_sync": conteudo.get("modo_sync", "manual"),
        })
    else:
        alvo = next((c for c in _COLECOES if c["id"] == conteudo["collection_id"]), None)
        if not alvo:
            return jsonify({
                "error": "A coleção foi excluída depois. Restaure a coleção primeiro."
            }), 409
        for a in conteudo.get("arquivos") or []:
            if a["file_id"] not in alvo["files"]:
                alvo["files"].append(a["file_id"])

    _LIXEIRA.remove(item)
    return jsonify({"status": "ok", "rotulo": item["rotulo"], "tipo": item["tipo"]})


@app.route("/api/lixeira/<int:item_id>", methods=["DELETE"])
def lixeira_descartar(item_id):
    if not _logado():
        return _nao_autenticado()
    item = next((i for i in _LIXEIRA if i["id"] == item_id), None)
    if not item:
        return jsonify({"error": "Este item não está mais na lixeira."}), 404
    _LIXEIRA.remove(item)
    return jsonify({"status": "ok"})


@app.route("/api/health")
def health():
    # O mock nao carrega modelo nenhum, entao esta sempre pronto. E util assim:
    # o front consegue exercitar o caminho normal sem esperar 30 segundos.
    return jsonify({
        "servidor": "ok",
        "modelos": {"texto": {"estado": "pronto", "motivo": ""},
                    "visual": {"estado": "pronto", "motivo": ""}},
        "busca_pronta": True,
        "carregando": False,
    })


# Resumo da ultima indexacao. Comeca vazio (nunca indexou) e e preenchido
# quando a fila simulada zera -- assim o front exercita os DOIS estados: o
# "nunca rodou" e o resumo com erro para expandir.
_RESUMO = [None]


def _fechar_resumo_simulado():
    _RESUMO[0] = {
        "inicio": (_HOJE - timedelta(minutes=8)).isoformat(),
        "fim": _HOJE.isoformat(),
        "pastas": [
            {"caminho": _BASE, "indexados": 612, "ignorados": 24, "erros": 3,
             "arquivos_com_erro": [
                 {"nome": "foto-corrompida.jpg", "motivo": "não foi possível ler o conteúdo"},
                 {"nome": "camera_raw.cr2", "motivo": "não foi possível ler o conteúdo"},
                 {"nome": "scan-antigo.tiff", "motivo": "não foi possível ler o conteúdo"},
             ]},
            {"caminho": _DOCS, "indexados": 28, "ignorados": 5, "erros": 0,
             "arquivos_com_erro": []},
        ],
        "totais": {"indexados": 640, "ignorados": 29, "erros": 3},
    }


@app.route("/api/resumo_indexacao")
def resumo_indexacao():
    if not _logado():
        return _nao_autenticado()
    return jsonify({"resumo": _RESUMO[0]})


@app.route("/api/analyze_folders", methods=["POST"])
def analyze_folders():
    if not _logado():
        return _nao_autenticado()
    # Enche a fila simulada para o front conseguir ver a barra de progresso com
    # a estimativa de tempo, e o numero caindo a cada consulta de status.
    _FILA_SIMULADA[0] = 640
    return jsonify({"status": "ok", "enfileirados": _FILA_SIMULADA[0],
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
