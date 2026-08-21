# -*- coding: utf-8 -*-
"""
Integração contra um Postgres real com pgvector.

DESLIGADO POR PADRÃO. Só roda quando `SEARCHPLUS_TEST_DATABASE_URL` aponta para
um banco DEDICADO A TESTES — no CI, o service container efêmero. O módulo se
recusa a rodar se essa URL for igual à `DATABASE_URL` da aplicação, porque estes
testes criam e apagam linhas.

Cobre o que o mock não alcança: as constraints do schema, o comportamento real
das queries de caminho e o isolamento por `user_id`.

    SEARCHPLUS_TEST_DATABASE_URL=postgresql://... py -m pytest -m requires_db
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.caminhos import caminho

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 não instalado")

URL_TESTE = os.environ.get("SEARCHPLUS_TEST_DATABASE_URL", "").strip()
SCHEMA = Path(__file__).resolve().parent.parent.parent / "backend" / "schema.sql"

pytestmark.append(
    pytest.mark.skipif(
        not URL_TESTE,
        reason="defina SEARCHPLUS_TEST_DATABASE_URL (banco de teste dedicado) para rodar",
    )
)


def _guardar_contra_producao() -> None:
    """Impede o apontamento acidental para o banco da aplicação."""
    producao = (os.environ.get("DATABASE_URL") or "").strip()
    if producao and URL_TESTE == producao:
        pytest.fail(
            "SEARCHPLUS_TEST_DATABASE_URL é idêntica a DATABASE_URL. Estes testes "
            "escrevem e apagam dados — aponte para um banco de teste dedicado."
        )


@pytest.fixture(scope="module")
def conexao():
    _guardar_contra_producao()
    conn = psycopg2.connect(URL_TESTE)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(SCHEMA.read_text(encoding="utf-8"))
    yield conn
    conn.close()


@pytest.fixture()
def usuario(conexao):
    """Usuário descartável, removido ao fim de cada teste (cascata leva o resto)."""
    with conexao.cursor() as cur:
        cur.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id",
            (f"pytest_{os.urandom(4).hex()}", "$2b$12$hash-de-teste"),
        )
        uid = cur.fetchone()[0]
    yield uid
    with conexao.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id = %s", (uid,))


def _inserir_arquivo(conexao, uid: int, caminho: str, nome: str = "x.jpg"):
    with conexao.cursor() as cur:
        cur.execute(
            "INSERT INTO files (user_id, nome, caminho, tipo, processado) "
            "VALUES (%s, %s, %s, 'jpg', 1) RETURNING id",
            (uid, nome, caminho),
        )
        return cur.fetchone()[0]


class TestSchema:
    def test_extensao_vector_habilitada(self, conexao):
        with conexao.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            assert cur.fetchone(), "pgvector é obrigatório para a busca semântica"

    def test_tabelas_existem(self, conexao):
        with conexao.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            )
            tabelas = {r[0] for r in cur.fetchall()}
        assert {"users", "folders", "files"} <= tabelas

    def test_caminho_e_unico_por_usuario(self, conexao, usuario):
        _inserir_arquivo(conexao, usuario, caminho("A", "x.jpg"))
        with pytest.raises(psycopg2.errors.UniqueViolation):
            _inserir_arquivo(conexao, usuario, caminho("A", "x.jpg"))

    def test_apagar_usuario_leva_os_arquivos(self, conexao):
        with conexao.cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, password_hash) VALUES (%s,'h') RETURNING id",
                (f"cascata_{os.urandom(4).hex()}",),
            )
            uid = cur.fetchone()[0]
        _inserir_arquivo(conexao, uid, caminho("B", "y.jpg"))
        with conexao.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s", (uid,))
            cur.execute("SELECT count(*) FROM files WHERE user_id = %s", (uid,))
            assert cur.fetchone()[0] == 0


class TestIsolamentoEntreUsuarios:
    def test_um_usuario_nao_ve_arquivo_do_outro(self, conexao, usuario):
        with conexao.cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, password_hash) VALUES (%s,'h') RETURNING id",
                (f"outro_{os.urandom(4).hex()}",),
            )
            outro = cur.fetchone()[0]
        try:
            _inserir_arquivo(conexao, outro, caminho("Privado", "segredo.jpg"), "segredo.jpg")
            with conexao.cursor() as cur:
                cur.execute("SELECT count(*) FROM files WHERE user_id = %s", (usuario,))
                assert cur.fetchone()[0] == 0
        finally:
            with conexao.cursor() as cur:
                cur.execute("DELETE FROM users WHERE id = %s", (outro,))


class TestPrefixoDePastaNoBanco:
    """
    A query real de "arquivo dentro desta pasta", que já vazou entre pastas
    irmãs por falta do separador no fim do prefixo.
    """

    def test_prefixo_nao_alcanca_pasta_irma(self, conexao, usuario, app_module):
        _inserir_arquivo(conexao, usuario, caminho("Fotos", "dentro.jpg"), "dentro.jpg")
        _inserir_arquivo(conexao, usuario, caminho("Fotos_backup", "irma.jpg"), "irma.jpg")
        _inserir_arquivo(conexao, usuario, caminho("Fotos", "sub", "neta.jpg"), "neta.jpg")

        prefixo = app_module._prefixo_pasta(caminho("Fotos"))
        with conexao.cursor() as cur:
            cur.execute(
                "SELECT nome FROM files WHERE user_id = %s AND left(lower(caminho), %s) = %s",
                (usuario, len(prefixo), prefixo),
            )
            achados = {r[0] for r in cur.fetchall()}

        assert achados == {"dentro.jpg", "neta.jpg"}
        assert "irma.jpg" not in achados

    def test_prefixo_ignora_diferenca_de_caixa(self, conexao, usuario, app_module):
        _inserir_arquivo(conexao, usuario, caminho("Fotos", "CAIXA.jpg").upper(), "CAIXA.jpg")
        prefixo = app_module._prefixo_pasta(caminho("Fotos"))
        with conexao.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM files WHERE user_id = %s AND left(lower(caminho), %s) = %s",
                (usuario, len(prefixo), prefixo),
            )
            assert cur.fetchone()[0] == 1


class TestTimestamps:
    def test_data_adicionado_grava_em_utc(self, conexao, usuario):
        """
        Gravar hora local numa coluna timestamptz com a sessão em UTC deslocava
        a data — arquivo da madrugada aparecia no dia anterior.
        """
        import datetime as dt

        agora = dt.datetime.now(dt.timezone.utc)
        with conexao.cursor() as cur:
            cur.execute(
                "INSERT INTO files (user_id, nome, caminho, tipo, processado, data_adicionado) "
                "VALUES (%s,'t.jpg',%s,'jpg',1,%s) RETURNING data_adicionado",
                (usuario, caminho("T", f"{os.urandom(3).hex()}.jpg"), agora.isoformat()),
            )
            gravado = cur.fetchone()[0]
        assert abs((gravado - agora).total_seconds()) < 5
