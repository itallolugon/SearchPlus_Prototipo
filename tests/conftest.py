# -*- coding: utf-8 -*-
"""
Preparação do ambiente de teste do Search+.

`backend/app.py` faz três coisas no momento do import que impedem um teste
unitário rápido:

  1. levanta RuntimeError se DATABASE_URL não estiver definida;
  2. abre um pool de conexões REAL no Postgres (app.py:472);
  3. baixa/carrega SBERT e CLIP, ~1 GB e dezenas de segundos.

Nenhuma dessas três é necessária para exercitar a lógica de negócio. Em vez de
alterar o backend — que o AGENTS.md declara intocável e é compartilhado com
produção — este módulo neutraliza as três ANTES do import:

  - aponta DATABASE_URL para um DSN que nunca é discado;
  - troca o construtor do pool por um mock;
  - substitui `sentence_transformers` por um stub que falha ao instanciar,
    caindo no try/except que o próprio app já tem (SBERT_OK/CLIP_OK = False).

O efeito é um `app` importado em ~10s, offline, com toda a lógica pura
acessível. As capacidades de IA ficam desligadas de propósito: isso também
exercita o caminho degradado, que é como o app roda quando um modelo falha.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

RAIZ = Path(__file__).resolve().parent.parent
BACKEND = RAIZ / "backend"


def _preparar_ambiente() -> None:
    """Variáveis de ambiente exigidas no import. Nenhuma aponta para serviço real."""
    os.environ["DATABASE_URL"] = os.environ.get(
        "SEARCHPLUS_TEST_DATABASE_URL",
        "postgresql://teste:teste@127.0.0.1:5432/searchplus_test_nao_conectado",
    )
    os.environ["SEARCHPLUS_OFFLINE"] = "1"  # nunca busca modelo na rede
    os.environ.setdefault("ANTHROPIC_API_KEY", "")  # vazio => CLAUDE_OK False
    os.environ.setdefault("SECRET_KEY", "chave-de-teste-nao-usar-em-producao")


def _stubar_modelos() -> None:
    """
    Substitui sentence_transformers por um stub que estoura ao instanciar.

    O app envolve o carregamento em try/except e apenas desliga a capacidade,
    então o efeito é SBERT_OK=False e CLIP_OK=False — sem 1 GB de download.
    """
    if "sentence_transformers" in sys.modules:
        return
    stub = types.ModuleType("sentence_transformers")

    class _ModeloDesabilitado:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("modelo de IA desabilitado no ambiente de teste")

    stub.SentenceTransformer = _ModeloDesabilitado
    sys.modules["sentence_transformers"] = stub


def _importar_app():
    """Importa backend/app.py com o pool de conexões mockado."""
    _preparar_ambiente()
    _stubar_modelos()
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    # O patch cobre só a janela do import, que é quando o pool é construído.
    with mock.patch("psycopg2.pool.ThreadedConnectionPool"):
        import app as modulo_app
    return modulo_app


# Import único por sessão: repetir custaria segundos por arquivo de teste.
app_importado = _importar_app()


@pytest.fixture(scope="session")
def app_module():
    """O módulo `backend/app.py` já importado e isolado."""
    return app_importado


@pytest.fixture()
def flask_app(app_module):
    """A instância Flask em modo de teste."""
    app_module.app.config.update(TESTING=True)
    return app_module.app


@pytest.fixture()
def client(flask_app):
    """Cliente HTTP sem sessão — serve para checar os 401."""
    return flask_app.test_client()


@pytest.fixture()
def client_logado(flask_app):
    """
    Cliente com sessão injetada direto, sem passar pelo login.

    Injetar a sessão evita depender do banco (o login consulta `users`) e
    mantém o teste focado no endpoint sob análise.
    """
    c = flask_app.test_client()
    with c.session_transaction() as sessao:
        sessao["user_id"] = 4242
    return c


@pytest.fixture()
def db_falso(app_module):
    """
    Troca `get_db` por um duplo controlável.

    Devolve `(mock_get_db, conexao)`. Configure o retorno assim:

        conexao.execute.return_value.fetchone.return_value = {"n": 3}
        conexao.execute.return_value.fetchall.return_value = []
    """
    conexao = mock.MagicMock(name="conexao")
    with mock.patch.object(app_module, "get_db", return_value=conexao) as m:
        yield m, conexao


@pytest.fixture()
def db_roteado(app_module):
    """
    Duplo de banco que responde conforme o SQL recebido.

    Vários endpoints disparam consultas diferentes no mesmo handler; um retorno
    único não serve. Aqui cada trecho de SQL mapeia para sua resposta:

        db_roteado({
            "COUNT(*) AS n": {"fetchone": {"n": 2}},
            "FROM files":    {"fetchall": [{"tipo": "jpg", "descricao_ia": ""}]},
        })

    Consultas sem regra recebem fetchone=None e fetchall=[], que é o que o
    código trata como "não achei nada".
    """

    def _montar(rotas: dict[str, dict]):
        conexao = mock.MagicMock(name="conexao")

        def _execute(sql, params=None):
            texto = str(sql)
            cursor = mock.MagicMock()
            cursor.fetchone.return_value = None
            cursor.fetchall.return_value = []
            cursor.rowcount = 0
            for trecho, resposta in rotas.items():
                if trecho in texto:
                    if "fetchone" in resposta:
                        cursor.fetchone.return_value = resposta["fetchone"]
                    if "fetchall" in resposta:
                        cursor.fetchall.return_value = resposta["fetchall"]
                    break
            return cursor

        conexao.execute.side_effect = _execute
        patch = mock.patch.object(app_module, "get_db", return_value=conexao)
        patch.start()
        _montar.patches.append(patch)
        return conexao

    _montar.patches = []
    yield _montar
    for p in _montar.patches:
        p.stop()


@pytest.fixture()
def tmp_pasta_com_arquivos(tmp_path):
    """Árvore de arquivos temporária para os testes de caminho."""
    (tmp_path / "Fotos").mkdir()
    (tmp_path / "Fotos_backup").mkdir()
    (tmp_path / "Fotos" / "sub").mkdir()
    (tmp_path / "Fotos" / "a.jpg").write_bytes(b"\xff\xd8\xff")
    (tmp_path / "Fotos" / "sub" / "b.jpg").write_bytes(b"\xff\xd8\xff")
    (tmp_path / "Fotos_backup" / "c.jpg").write_bytes(b"\xff\xd8\xff")
    return tmp_path
