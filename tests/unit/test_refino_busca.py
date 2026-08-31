# -*- coding: utf-8 -*-
"""
Refinar a busca sem recomeçar.

Antes, cada tentativa jogava fora o que a anterior já tinha acertado: quem
procurou "praia" e recebeu trinta fotos com gente no meio só podia reescrever
a frase e torcer. Não havia como dizer "essas não", nem como buscar dentro do
que já apareceu.

Agora há duas formas de estreitar sem perder o caminho andado:

    praia -pessoas       tira o que casa com "pessoas", por texto E por imagem
    escopo: [ids]        limita a busca ao resultado anterior
"""

from unittest import mock

import pytest

pytestmark = pytest.mark.unit


class TestSepararExclusoes:
    @pytest.mark.parametrize("entrada,consulta,excluidos", [
        ("praia -pessoas",           "praia",        ["pessoas"]),
        ("praia",                    "praia",        []),
        ("-pessoas praia",           "praia",        ["pessoas"]),
        ("praia -pessoas -barco",    "praia",        ["pessoas", "barco"]),
        ("por do sol -pessoas",      "por do sol",   ["pessoas"]),
        ("",                         "",             []),
    ])
    def test_separa(self, app_module, entrada, consulta, excluidos):
        assert app_module._separar_exclusoes(entrada) == (consulta, excluidos)

    def test_hifen_no_meio_da_palavra_nao_e_exclusao(self, app_module):
        """
        Nome de arquivo e data são cheios de hífen. "bem-te-vi" viraria "bem"
        excluindo "te" e "vi"; "2024-2025" excluiria "2025".
        """
        assert app_module._separar_exclusoes("bem-te-vi") == ("bem-te-vi", [])
        assert app_module._separar_exclusoes("relatorio 2024-2025") == (
            "relatorio 2024-2025", [])

    def test_hifen_sozinho_e_ignorado(self, app_module):
        """Um traço solto é digitação, não intenção."""
        assert app_module._separar_exclusoes("praia -") == ("praia", [])

    def test_so_exclusao_nao_deixa_consulta(self, app_module):
        assert app_module._separar_exclusoes("-pessoas") == ("", ["pessoas"])


class TestCairNaExclusao:
    def test_casa_na_descricao(self, app_module):
        assert app_module._cai_na_exclusao(
            ["pessoas"], "praia com pessoas ao fundo", "img_001.jpg") is True

    def test_casa_no_nome_do_arquivo(self, app_module):
        """
        Quem exclui "pessoas" espera que "reuniao-com-pessoas.jpg" saia também,
        mesmo que a descrição não mencione ninguém.
        """
        assert app_module._cai_na_exclusao(
            ["pessoas"], "sala vazia", "reuniao-com-pessoas.jpg") is True

    def test_nao_casa_deixa_passar(self, app_module):
        assert app_module._cai_na_exclusao(
            ["pessoas"], "praia deserta", "img_001.jpg") is False

    def test_lista_vazia_nao_exclui_nada(self, app_module):
        assert app_module._cai_na_exclusao([], "qualquer coisa", "x.jpg") is False

    def test_termo_vazio_e_ignorado(self, app_module):
        """
        Um termo vazio casaria com TODA descrição (`"" in qualquer` é sempre
        verdadeiro) e esvaziaria a busca inteira.
        """
        assert app_module._cai_na_exclusao([""], "praia deserta", "x.jpg") is False

    def test_basta_um_termo_casar(self, app_module):
        assert app_module._cai_na_exclusao(
            ["barco", "pessoas"], "praia com pessoas", "x.jpg") is True


def _sbert_falso():
    """
    Duplo do modelo de texto.

    `SBERT_OK = True` sozinho não basta: o endpoint chama `_SBERT.encode(...)`
    logo em seguida, e no ambiente de teste `_SBERT` é None — o teste morreria
    em AttributeError antes de chegar ao que ele quer verificar.
    """
    import numpy as np
    falso = mock.MagicMock()
    falso.encode.return_value = np.zeros(384)
    return falso


def _rotas_busca(linhas=None):
    return {
        "SELECT id, folder_id, nome, caminho": {"fetchall": linhas or []},
        "COUNT(*) AS n": {"fetchone": {"n": 0}},
    }


class TestBuscaComExclusao:
    def test_termo_excluido_sai_da_consulta_enviada(self, client_logado, db_roteado,
                                                     app_module):
        """
        Deixar "-pessoas" na frase faria o motor procurar POR pessoas — o
        oposto do pedido.
        """
        db_roteado(_rotas_busca())
        with mock.patch.object(app_module, "SBERT_OK", True), \
             mock.patch.object(app_module, "_SBERT", _sbert_falso()), \
             mock.patch.object(app_module, "_gerar_embedding", return_value=[0.1] * 384), \
             mock.patch.object(app_module, "_analisar_query",
                               wraps=app_module._analisar_query) as analisou:
            client_logado.post("/api/search", json={"query": "praia -pessoas"})

        assert analisou.call_args.args[0] == "praia"

    def test_a_resposta_diz_o_que_entendeu(self, client_logado, db_roteado, app_module):
        """
        O front desenha a trilha a partir disto. Se o parser separar de um
        jeito e a tela mostrar de outro, remover um chip não muda a busca e o
        usuário fica sem entender por quê.
        """
        db_roteado(_rotas_busca())
        with mock.patch.object(app_module, "SBERT_OK", True), \
             mock.patch.object(app_module, "_SBERT", _sbert_falso()), \
             mock.patch.object(app_module, "_gerar_embedding", return_value=[0.1] * 384):
            corpo = client_logado.post(
                "/api/search", json={"query": "praia -pessoas -barco"}).get_json()

        assert corpo["consulta"] == "praia"
        assert corpo["excluidos"] == ["pessoas", "barco"]

    def test_so_exclusao_explica_o_que_falta(self, client_logado, db_roteado):
        """
        "-pessoas" sozinho não é buscável: não dá para pedir "tudo menos
        pessoas". A resposta ensina a sintaxe em vez de devolver vazio.
        """
        db_roteado(_rotas_busca())
        corpo = client_logado.post("/api/search", json={"query": "-pessoas"}).get_json()

        assert corpo["resultados"] == []
        assert "procura" in corpo["erro"]

    def test_busca_vazia_continua_sem_erro(self, client_logado, db_roteado):
        """Campo em branco não é engano do usuário; é só nada a fazer."""
        db_roteado(_rotas_busca())
        corpo = client_logado.post("/api/search", json={"query": "   "}).get_json()

        assert corpo["resultados"] == []
        assert "erro" not in corpo


class TestEscopo:
    def test_escopo_vira_filtro_do_banco(self, client_logado, db_roteado, app_module):
        """
        Cortar depois faria os 100 candidatos serem escolhidos entre a
        biblioteca inteira e só então reduzidos ao escopo — a maioria
        descartada, e o refino trazendo MENOS do que existia dentro dele.
        """
        conexao = db_roteado(_rotas_busca())
        with mock.patch.object(app_module, "SBERT_OK", True), \
             mock.patch.object(app_module, "_SBERT", _sbert_falso()), \
             mock.patch.object(app_module, "_gerar_embedding", return_value=[0.1] * 384):
            client_logado.post("/api/search",
                               json={"query": "praia", "escopo": [1, 2, 3]})

        sqls = [str(c.args[0]) for c in conexao.execute.call_args_list]
        assert any("id = ANY(%s)" in q for q in sqls)

    def test_ids_invalidos_sao_descartados(self, client_logado, db_roteado, app_module):
        """Um id que não é número não pode derrubar a busca inteira."""
        db_roteado(_rotas_busca())
        with mock.patch.object(app_module, "SBERT_OK", True), \
             mock.patch.object(app_module, "_SBERT", _sbert_falso()), \
             mock.patch.object(app_module, "_gerar_embedding", return_value=[0.1] * 384):
            r = client_logado.post("/api/search", json={
                "query": "praia", "escopo": [1, "abc", None, 3]})

        assert r.status_code == 200

    def test_escopo_e_limitado(self, client_logado, db_roteado, app_module):
        """
        Um escopo sem teto viraria um `IN` com dezenas de milhares de ids —
        consulta gigante para dizer "busque em quase tudo".
        """
        conexao = db_roteado(_rotas_busca())
        with mock.patch.object(app_module, "SBERT_OK", True), \
             mock.patch.object(app_module, "_SBERT", _sbert_falso()), \
             mock.patch.object(app_module, "_gerar_embedding", return_value=[0.1] * 384):
            client_logado.post("/api/search",
                               json={"query": "praia", "escopo": list(range(9000))})

        for chamada in conexao.execute.call_args_list:
            if "id = ANY(%s)" in str(chamada.args[0]):
                ids = [p for p in chamada.args[1] if isinstance(p, list) and len(p) > 100]
                assert all(len(x) <= 5000 for x in ids)

    def test_a_resposta_confirma_o_escopo(self, client_logado, db_roteado, app_module):
        db_roteado(_rotas_busca())
        with mock.patch.object(app_module, "SBERT_OK", True), \
             mock.patch.object(app_module, "_SBERT", _sbert_falso()), \
             mock.patch.object(app_module, "_gerar_embedding", return_value=[0.1] * 384):
            corpo = client_logado.post(
                "/api/search", json={"query": "praia", "escopo": [1, 2, 3]}).get_json()

        assert corpo["escopo"] == 3

    def test_sem_escopo_a_busca_e_a_de_sempre(self, client_logado, db_roteado,
                                               app_module):
        conexao = db_roteado(_rotas_busca())
        with mock.patch.object(app_module, "SBERT_OK", True), \
             mock.patch.object(app_module, "_SBERT", _sbert_falso()), \
             mock.patch.object(app_module, "_gerar_embedding", return_value=[0.1] * 384):
            corpo = client_logado.post("/api/search", json={"query": "praia"}).get_json()

        sqls = [str(c.args[0]) for c in conexao.execute.call_args_list]
        assert not any("id = ANY(%s)" in q for q in sqls)
        assert corpo["escopo"] == 0


class TestFiltrosComponem:
    def test_filtro_avancado_soma_a_consulta(self, client_logado, db_roteado,
                                              app_module):
        """
        O item suspeitava que os filtros substituíssem a consulta. Não
        substituem — entram como AND no mesmo SELECT. Este teste existe para
        que continue assim.
        """
        conexao = db_roteado(_rotas_busca())
        with mock.patch.object(app_module, "SBERT_OK", True), \
             mock.patch.object(app_module, "_SBERT", _sbert_falso()), \
             mock.patch.object(app_module, "_gerar_embedding", return_value=[0.1] * 384):
            client_logado.post("/api/search", json={
                "query": "praia",
                "avancado": {"data_de": "2026-01-01", "pasta": "C:/Fotos"},
            })

        principal = next(q for q in (str(c.args[0]) for c in conexao.execute.call_args_list)
                         if "SELECT id, folder_id, nome, caminho" in q)
        assert "data_adicionado >= %s" in principal
        assert "left(lower(caminho), %s)" in principal
        assert "embedding" in principal          # a consulta continua lá

    def test_escopo_e_filtro_convivem(self, client_logado, db_roteado, app_module):
        conexao = db_roteado(_rotas_busca())
        with mock.patch.object(app_module, "SBERT_OK", True), \
             mock.patch.object(app_module, "_SBERT", _sbert_falso()), \
             mock.patch.object(app_module, "_gerar_embedding", return_value=[0.1] * 384):
            client_logado.post("/api/search", json={
                "query": "praia", "escopo": [1, 2],
                "avancado": {"data_de": "2026-01-01"},
            })

        principal = next(q for q in (str(c.args[0]) for c in conexao.execute.call_args_list)
                         if "SELECT id, folder_id, nome, caminho" in q)
        assert "id = ANY(%s)" in principal
        assert "data_adicionado >= %s" in principal


class TestExclusaoVisual:
    def test_limiar_visual_e_mais_exigente_que_o_da_busca(self, app_module):
        """
        Descartar por engano é pior que deixar passar: quem pediu para excluir
        ainda vê o resultado e pode refinar de novo; o que sumiu sem motivo, a
        pessoa nunca fica sabendo que existia.
        """
        import inspect
        fonte = inspect.getsource(app_module.api_search)

        assert "LIMIAR_EXCLUSAO_VISUAL = 0.25" in fonte
        # O limiar da busca normal, para comparar.
        assert "clip_sims[i] > 0.15" in fonte

    def test_a_exclusao_visual_roda_antes_da_pontuacao(self, app_module):
        """O que o usuário mandou tirar não disputa posição — sai."""
        import inspect
        fonte = inspect.getsource(app_module.api_search)

        pos_visual = fonte.index("excluidos_visualmente = set()")
        pos_filtro = fonte.index("def _filtrar_e_pontuar")
        assert pos_visual < pos_filtro
