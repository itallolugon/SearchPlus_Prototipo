# -*- coding: utf-8 -*-
"""
Interpretação da consulta do usuário.

`_analisar_query` decide o que a busca vai procurar: se é gente, bicho, foto ou
desenho, e quais sinônimos entram na expansão. As flags que ela produz alimentam
as regras de rejeição em `_ajustar_score`, então um erro aqui derruba resultado
legítimo do ranking.
"""

import pytest

pytestmark = pytest.mark.unit


class TestEstruturaDoRetorno:
    CHAVES = {
        "original",
        "normalizada",
        "palavras",
        "palavras_set",
        "expandida",
        "busca_pessoa",
        "busca_animal",
        "busca_feminino",
        "busca_masculino",
        "busca_desenho",
        "busca_foto",
    }

    def test_contrato_de_chaves(self, app_module):
        """Consumidores leem essas chaves por nome; sumir com uma quebra a busca."""
        assert self.CHAVES <= set(app_module._analisar_query("cachorro").keys())

    def test_preserva_a_query_original(self, app_module):
        assert app_module._analisar_query("Cachorro NA Praia")["original"] == "Cachorro NA Praia"

    def test_normalizada_sem_acento_nem_caixa(self, app_module):
        assert app_module._analisar_query("Ação")["normalizada"] == "acao"


class TestDeteccaoDeIntencao:
    @pytest.mark.parametrize("query", ["cachorro", "gato", "cavalo correndo"])
    def test_reconhece_busca_por_animal(self, app_module, query):
        assert app_module._analisar_query(query)["busca_animal"] is True

    @pytest.mark.parametrize("query", ["mulher", "homem de terno", "criança brincando"])
    def test_reconhece_busca_por_pessoa(self, app_module, query):
        assert app_module._analisar_query(query)["busca_pessoa"] is True

    def test_genero_feminino(self, app_module):
        q = app_module._analisar_query("mulher sorrindo")
        assert q["busca_feminino"] is True
        assert q["busca_masculino"] is False

    def test_genero_masculino(self, app_module):
        q = app_module._analisar_query("homem de terno")
        assert q["busca_masculino"] is True
        assert q["busca_feminino"] is False

    def test_sem_genero_quando_nao_ha_pista(self, app_module):
        q = app_module._analisar_query("bicicleta")
        assert q["busca_feminino"] is False
        assert q["busca_masculino"] is False

    def test_reconhece_pedido_de_foto(self, app_module):
        assert app_module._analisar_query("fotos de cachorro")["busca_foto"] is True

    def test_reconhece_pedido_de_desenho(self, app_module):
        assert app_module._analisar_query("desenho de cachorro")["busca_desenho"] is True

    def test_query_neutra_nao_marca_estilo(self, app_module):
        q = app_module._analisar_query("cachorro")
        assert q["busca_foto"] is False
        assert q["busca_desenho"] is False


class TestExpansaoDeSinonimos:
    def test_expande_animal(self, app_module):
        expandida = app_module._analisar_query("cachorro")["expandida"]
        assert "cao" in expandida
        assert "dog" in expandida

    def test_expansao_inclui_o_termo_original(self, app_module):
        assert "praia" in app_module._analisar_query("praia")["expandida"]

    def test_termo_sem_sinonimo_sobrevive(self, app_module):
        assert "bicicleta" in app_module._analisar_query("bicicleta")["expandida"]


class TestStopwordsEBordas:
    def test_remove_palavras_vazias(self, app_module):
        """'de', 'na' não podem virar termo de busca."""
        palavras = app_module._analisar_query("fotos de cachorro na praia")["palavras"]
        assert "de" not in palavras
        assert "na" not in palavras
        assert "cachorro" in palavras

    @pytest.mark.parametrize("query", ["", "   ", "de na o a"])
    def test_query_vazia_ou_so_stopword_nao_estoura(self, app_module, query):
        resultado = app_module._analisar_query(query)
        assert isinstance(resultado, dict)
        assert isinstance(resultado["palavras"], list)

    def test_palavras_set_bate_com_palavras(self, app_module):
        q = app_module._analisar_query("cachorro na praia")
        assert q["palavras_set"] == set(q["palavras"])

    def test_query_muito_longa_nao_estoura(self, app_module):
        assert isinstance(app_module._analisar_query("cachorro " * 500), dict)

    def test_caracteres_especiais_nao_estouram(self, app_module):
        assert isinstance(app_module._analisar_query("!@#$%^&*() 100%"), dict)
