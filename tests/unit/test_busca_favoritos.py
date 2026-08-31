# -*- coding: utf-8 -*-
"""
Buscar só entre os favoritos.

Favoritar marcava o arquivo e não servia para mais nada na busca. Quem separou
as fotos boas ao longo de meses não conseguia procurar dentro delas — tinha de
buscar em tudo e reconhecer as favoritas no meio do resultado.

O filtro entra em `avancado`, junto de data, tamanho e pasta, porque é da mesma
natureza: reduz o conjunto antes da busca, compondo com a consulta em vez de
substituí-la.
"""

import numpy as np
from unittest import mock

import pytest

pytestmark = pytest.mark.unit


def _sbert_falso():
    falso = mock.MagicMock()
    falso.encode.return_value = np.zeros(384)
    return falso


def _rotas():
    return {"SELECT id, folder_id, nome, caminho": {"fetchall": []},
            "COUNT(*) AS n": {"fetchone": {"n": 0}}}


def _sql_principal(conexao):
    return next(str(c.args[0]) for c in conexao.execute.call_args_list
                if "SELECT id, folder_id, nome, caminho" in str(c.args[0]))


class TestFiltroDeFavoritos:
    def test_liga_o_filtro(self, client_logado, db_roteado, app_module):
        conexao = db_roteado(_rotas())
        with mock.patch.object(app_module, "SBERT_OK", True), \
             mock.patch.object(app_module, "_SBERT", _sbert_falso()), \
             mock.patch.object(app_module, "_gerar_embedding", return_value=[0.1] * 384):
            client_logado.post("/api/search", json={
                "query": "praia", "avancado": {"so_favoritos": True}})

        assert "favorito = 1" in _sql_principal(conexao)

    def test_sem_o_filtro_a_busca_e_a_de_sempre(self, client_logado, db_roteado,
                                                 app_module):
        conexao = db_roteado(_rotas())
        with mock.patch.object(app_module, "SBERT_OK", True), \
             mock.patch.object(app_module, "_SBERT", _sbert_falso()), \
             mock.patch.object(app_module, "_gerar_embedding", return_value=[0.1] * 384):
            client_logado.post("/api/search", json={"query": "praia"})

        assert "favorito = 1" not in _sql_principal(conexao)

    def test_valor_falso_nao_liga_o_filtro(self, client_logado, db_roteado,
                                            app_module):
        """
        O front manda o campo só quando está ligado, mas `false` explícito tem
        de ser respeitado — senão desligar o botão não desligaria nada.
        """
        conexao = db_roteado(_rotas())
        with mock.patch.object(app_module, "SBERT_OK", True), \
             mock.patch.object(app_module, "_SBERT", _sbert_falso()), \
             mock.patch.object(app_module, "_gerar_embedding", return_value=[0.1] * 384):
            client_logado.post("/api/search", json={
                "query": "praia", "avancado": {"so_favoritos": False}})

        assert "favorito = 1" not in _sql_principal(conexao)

    def test_compoe_com_os_outros_filtros(self, client_logado, db_roteado,
                                           app_module):
        """
        "as fotos favoritas da viagem, daquele mês" é uma pergunta só. Os
        filtros somam; nenhum substitui o outro.
        """
        conexao = db_roteado(_rotas())
        with mock.patch.object(app_module, "SBERT_OK", True), \
             mock.patch.object(app_module, "_SBERT", _sbert_falso()), \
             mock.patch.object(app_module, "_gerar_embedding", return_value=[0.1] * 384):
            client_logado.post("/api/search", json={
                "query": "praia",
                "avancado": {"so_favoritos": True, "data_de": "2026-01-01"},
            })

        sql = _sql_principal(conexao)
        assert "favorito = 1" in sql
        assert "data_adicionado >= %s" in sql

    def test_compoe_com_o_escopo(self, client_logado, db_roteado, app_module):
        conexao = db_roteado(_rotas())
        with mock.patch.object(app_module, "SBERT_OK", True), \
             mock.patch.object(app_module, "_SBERT", _sbert_falso()), \
             mock.patch.object(app_module, "_gerar_embedding", return_value=[0.1] * 384):
            client_logado.post("/api/search", json={
                "query": "praia", "escopo": [1, 2],
                "avancado": {"so_favoritos": True},
            })

        sql = _sql_principal(conexao)
        assert "favorito = 1" in sql
        assert "id = ANY(%s)" in sql

    def test_nao_dispensa_a_posse(self, client_logado, db_roteado, app_module):
        """Favorito de outra pessoa não é favorito de ninguém aqui."""
        conexao = db_roteado(_rotas())
        with mock.patch.object(app_module, "SBERT_OK", True), \
             mock.patch.object(app_module, "_SBERT", _sbert_falso()), \
             mock.patch.object(app_module, "_gerar_embedding", return_value=[0.1] * 384):
            client_logado.post("/api/search", json={
                "query": "praia", "avancado": {"so_favoritos": True}})

        assert "user_id = %s" in _sql_principal(conexao)
