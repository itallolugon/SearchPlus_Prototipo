# -*- coding: utf-8 -*-
"""
Endpoints de pastas monitoradas, com o banco substituído por um duplo.

Concentram a lógica que já produziu quatro defeitos distintos: normalização do
caminho, duplicata por diferença de caixa, transação abortada devolvendo 500 e
exclusão levando junto o índice de uma subpasta ainda monitorada.
"""

from unittest import mock

import pytest

pytestmark = pytest.mark.unit


class TestCadastroDePasta:
    def test_caminho_inexistente_e_recusado(self, client_logado):
        resposta = client_logado.post(
            "/api/folders", json={"pasta": r"C:\pasta\que\nao\existe\mesmo"}
        )
        assert resposta.status_code == 400

    def test_caminho_vazio_e_recusado(self, client_logado):
        assert client_logado.post("/api/folders", json={"pasta": ""}).status_code == 400

    def test_arquivo_nao_serve_como_pasta(self, client_logado, tmp_path):
        arquivo = tmp_path / "isto_e_um_arquivo.txt"
        arquivo.write_text("x", encoding="utf-8")
        resposta = client_logado.post("/api/folders", json={"pasta": str(arquivo)})
        assert resposta.status_code == 400

    def test_pasta_valida_e_gravada(self, client_logado, db_falso, tmp_path):
        _, conexao = db_falso
        conexao.execute.return_value.fetchone.return_value = None  # ainda não existe
        conexao.execute.return_value.fetchall.return_value = []

        resposta = client_logado.post("/api/folders", json={"pasta": str(tmp_path)})
        assert resposta.status_code == 200

        sqls = " ".join(str(c) for c in conexao.execute.call_args_list)
        assert "INSERT INTO folders" in sqls

    def test_duplicata_por_caixa_vira_update_e_nao_insert(self, client_logado, db_falso, tmp_path):
        """
        O UNIQUE do Postgres diferencia maiúsculas; o Windows não. Cadastrar a
        mesma pasta com outra caixa precisa atualizar a existente, senão o
        acervo é indexado duas vezes.
        """
        _, conexao = db_falso
        conexao.execute.return_value.fetchone.return_value = {"path": str(tmp_path)}
        conexao.execute.return_value.fetchall.return_value = []

        resposta = client_logado.post(
            "/api/folders", json={"pasta": str(tmp_path).upper(), "perfil_analise": "deep"}
        )
        assert resposta.status_code == 200

        sqls = " ".join(str(c) for c in conexao.execute.call_args_list)
        assert "UPDATE folders" in sqls
        assert "INSERT INTO folders" not in sqls

    def test_conflito_de_corrida_faz_rollback_antes_do_update(
        self, client_logado, db_falso, tmp_path, app_module
    ):
        """
        Sem `rollback()` a transação fica abortada e o UPDATE seguinte estoura
        InFailedSqlTransaction — que virava 500 no fluxo normal de reenviar a
        mesma pasta pela interface.
        """
        import psycopg2

        _, conexao = db_falso

        def _execute(sql, params=None):
            texto = str(sql)
            if "INSERT INTO folders" in texto:
                # Outro request inseriu primeiro, entre o SELECT e o INSERT.
                raise psycopg2.errors.UniqueViolation("duplicate key")
            cursor = mock.MagicMock()
            if "SELECT path FROM folders" in texto:
                # A pasta ainda não existe -> o fluxo segue para o INSERT.
                cursor.fetchone.return_value = None
            cursor.fetchall.return_value = []
            return cursor

        conexao.execute.side_effect = _execute

        resposta = client_logado.post("/api/folders", json={"pasta": str(tmp_path)})

        assert resposta.status_code == 200, "conflito de corrida não pode virar 500"
        assert conexao.rollback.called, "rollback é obrigatório antes de reusar a conexão"


class TestRemocaoDePasta:
    def test_remove_por_caminho(self, client_logado, db_falso, tmp_path):
        _, conexao = db_falso
        conexao.execute.return_value.fetchall.return_value = []
        resposta = client_logado.delete("/api/folders", json={"pasta": str(tmp_path)})
        assert resposta.status_code == 200
        sqls = " ".join(str(c) for c in conexao.execute.call_args_list)
        assert "DELETE FROM folders" in sqls

    def test_exclusao_preserva_subpasta_monitorada(self, app_module, tmp_path):
        """
        Monitorando 'A' e 'A/B', remover só 'A' não pode apagar o índice de
        'A/B' — que continua na lista e não seria reindexado sozinho.
        """
        pai = str(tmp_path / "A")
        filha = str(tmp_path / "A" / "B")
        conexao = mock.MagicMock()
        conexao.execute.return_value.fetchall.return_value = [{"path": pai}, {"path": filha}]

        app_module._apagar_arquivos_da_pasta(conexao, 42, pai)

        sql_delete = next(
            str(c[0][0]) for c in conexao.execute.call_args_list if "DELETE FROM files" in str(c)
        )
        assert "<>" in sql_delete, "faltou a exclusão da subpasta ainda monitorada"

    def test_sem_subpasta_o_delete_e_simples(self, app_module, tmp_path):
        conexao = mock.MagicMock()
        conexao.execute.return_value.fetchall.return_value = [{"path": str(tmp_path)}]

        app_module._apagar_arquivos_da_pasta(conexao, 42, str(tmp_path))

        sql_delete = next(
            str(c[0][0]) for c in conexao.execute.call_args_list if "DELETE FROM files" in str(c)
        )
        assert "<>" not in sql_delete


class TestConfiguracaoDaPasta:
    def test_sem_id_nem_path_e_recusado(self, client_logado, db_falso):
        resposta = client_logado.post("/api/folders/update_config", json={"perfil_analise": "deep"})
        assert resposta.status_code == 400

    def test_sem_campo_algum_e_recusado(self, client_logado, db_falso):
        resposta = client_logado.post("/api/folders/update_config", json={"id": 1})
        assert resposta.status_code == 400

    def test_get_nao_e_suportado(self, client_logado):
        assert client_logado.get("/api/folders/update_config").status_code == 400

    def test_atualiza_por_id(self, client_logado, db_falso):
        _, conexao = db_falso
        conexao.execute.return_value.fetchall.return_value = []
        resposta = client_logado.post(
            "/api/folders/update_config", json={"id": 7, "perfil_analise": "deep"}
        )
        assert resposta.status_code == 200
        sqls = " ".join(str(c) for c in conexao.execute.call_args_list)
        assert "UPDATE folders" in sqls


class TestManutencaoDoIndice:
    def test_limpar_cache_filtra_por_usuario(self, client_logado, db_falso):
        """Sem o filtro de user_id, limparia o acervo de todo mundo."""
        _, conexao = db_falso
        assert client_logado.post("/api/clear_cache", json={}).status_code == 200
        sqls = " ".join(str(c) for c in conexao.execute.call_args_list)
        assert "DELETE FROM files" in sqls
        assert "user_id" in sqls

    def test_cancelar_analise_esvazia_a_fila(self, client_logado, app_module):
        app_module._queue.put({"path": "x", "nome": "x", "ext": "jpg", "uid": 4242})
        resposta = client_logado.post("/api/cancel_analysis", json={})
        assert resposta.status_code == 200
        assert app_module._queue.empty()
