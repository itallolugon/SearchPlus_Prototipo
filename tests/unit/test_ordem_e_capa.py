# -*- coding: utf-8 -*-
"""
Ordenar as coleções e escolher a capa.

A lista vinha sempre da mais recente para a mais antiga, e a capa era sempre o
mosaico das 4 imagens mais recentes. Duas decisões tomadas pelo app sobre algo
que é do usuário: a ordem em que ele quer procurar, e a foto que representa uma
coleção que ele montou à mão.

A parte sensível é a ordenação: o valor vem da URL e entra na cláusula
`ORDER BY`, que não aceita parâmetro. Concatenar o que o cliente mandou seria
injeção pela porta da frente — por isso só nomes de uma lista fechada viram SQL.
"""

import pytest

pytestmark = pytest.mark.unit

UID = 4242


def _colecao(**extra):
    base = {"id": 1, "nome": "Viagem", "total": 3, "criado_em": None,
            "pasta_vinculada": None, "modo_sync": "manual",
            "capa_file_id": None, "capa_caminho": None}
    base.update(extra)
    return base


def _rotas(linhas=None):
    return {"FROM collections c": {"fetchall": linhas or [_colecao()]}}


def _sql_listagem(conexao):
    return next(str(c.args[0]) for c in conexao.execute.call_args_list
                if "FROM collections c" in str(c.args[0]))


class TestOrdenacao:
    @pytest.mark.parametrize("valor,esperado", [
        ("recentes", "c.criado_em DESC"),
        ("antigas",  "c.criado_em ASC"),
        ("nome",     "lower(c.nome) ASC"),
        ("tamanho",  "COUNT(cf.file_id) DESC"),
    ])
    def test_ordens_conhecidas(self, client_logado, db_roteado, valor, esperado):
        conexao = db_roteado(_rotas())
        client_logado.get(f"/api/collections?ordem={valor}")

        assert esperado in _sql_listagem(conexao)

    def test_sem_parametro_e_a_ordem_de_sempre(self, client_logado, db_roteado):
        """Quem nunca escolheu continua vendo o que sempre viu."""
        conexao = db_roteado(_rotas())
        client_logado.get("/api/collections")

        assert "ORDER BY c.criado_em DESC" in _sql_listagem(conexao)

    def test_ordem_desconhecida_cai_no_padrao(self, client_logado, db_roteado):
        conexao = db_roteado(_rotas())
        r = client_logado.get("/api/collections?ordem=inventada")

        assert r.status_code == 200
        assert "ORDER BY c.criado_em DESC" in _sql_listagem(conexao)

    def test_ordem_maliciosa_nao_entra_na_sql(self, client_logado, db_roteado):
        """
        `ORDER BY` não aceita parâmetro, então o valor vira texto na consulta.
        Só nomes de uma lista fechada podem chegar lá — qualquer outra coisa
        cai no padrão sem sequer ser mencionada.
        """
        conexao = db_roteado(_rotas())
        r = client_logado.get(
            "/api/collections?ordem=c.nome; DROP TABLE collections--")

        assert r.status_code == 200
        sql = _sql_listagem(conexao)
        assert "DROP" not in sql.upper()
        assert "ORDER BY c.criado_em DESC" in sql

    def test_ordenar_por_tamanho_desempata_pelo_nome(self, client_logado, db_roteado):
        """
        Sem desempate, duas coleções do mesmo tamanho trocam de lugar entre
        recarregamentos e a lista parece instável.
        """
        conexao = db_roteado(_rotas())
        client_logado.get("/api/collections?ordem=tamanho")

        assert "COUNT(cf.file_id) DESC, lower(c.nome) ASC" in _sql_listagem(conexao)


class TestCapaNaListagem:
    def test_sem_capa_escolhida_vem_vazia(self, client_logado, db_roteado):
        db_roteado(_rotas())
        c = client_logado.get("/api/collections").get_json()["colecoes"][0]

        assert c["capa"] == ""
        assert c["capa_file_id"] is None

    def test_capa_escolhida_vem_com_o_caminho(self, client_logado, db_roteado):
        db_roteado(_rotas([_colecao(capa_file_id=42,
                                    capa_caminho=r"C:\Fotos\escolhida.jpg")]))
        c = client_logado.get("/api/collections").get_json()["colecoes"][0]

        assert c["capa"] == r"C:\Fotos\escolhida.jpg"
        assert c["capa_file_id"] == 42

    def test_capa_apontando_para_arquivo_sumido_volta_ao_mosaico(self, client_logado,
                                                                  db_roteado):
        """
        O LEFT JOIN devolve caminho nulo quando a imagem saiu da biblioteca. A
        coleção volta ao mosaico sozinha, em vez de mostrar imagem quebrada —
        é por isso que a coluna não tem chave estrangeira.
        """
        db_roteado(_rotas([_colecao(capa_file_id=42, capa_caminho=None)]))
        c = client_logado.get("/api/collections").get_json()["colecoes"][0]

        assert c["capa"] == ""

    def test_a_capa_e_do_dono(self, client_logado, db_roteado):
        conexao = db_roteado(_rotas())
        client_logado.get("/api/collections")

        assert "f.user_id = c.user_id" in _sql_listagem(conexao)


class TestDefinirCapa:
    def _rotas_patch(self, pertence=True):
        return {
            "SELECT id, nome FROM collections": {
                "fetchone": {"id": 1, "nome": "Viagem"}},
            "FROM collections": {"fetchone": {"id": 1, "nome": "Viagem",
                                              "pasta_vinculada": None,
                                              "modo_sync": "manual"}},
            "FROM collection_files cf": {"fetchone": {"?column?": 1} if pertence else None},
            "FROM collection_folders": {"fetchall": []},
        }

    def test_define_a_capa(self, client_logado, db_roteado):
        conexao = db_roteado(self._rotas_patch())
        r = client_logado.patch("/api/collections/1", json={"capa_file_id": 42})

        assert r.status_code == 200
        assert any("capa_file_id = %s" in str(c.args[0])
                   for c in conexao.execute.call_args_list)

    def test_nulo_volta_ao_mosaico(self, client_logado, db_roteado):
        conexao = db_roteado(self._rotas_patch())
        r = client_logado.patch("/api/collections/1", json={"capa_file_id": None})

        assert r.status_code == 200
        assert any("capa_file_id = NULL" in str(c.args[0])
                   for c in conexao.execute.call_args_list)

    def test_imagem_fora_da_colecao_e_recusada(self, client_logado, db_roteado):
        """
        Sem esta checagem dava para pôr como capa qualquer arquivo do acervo, e
        a capa deixaria de representar a coleção.
        """
        db_roteado(self._rotas_patch(pertence=False))
        r = client_logado.patch("/api/collections/1", json={"capa_file_id": 999})

        assert r.status_code == 400
        assert "nesta coleção" in r.get_json()["error"]

    def test_id_invalido_e_recusado(self, client_logado, db_roteado):
        db_roteado(self._rotas_patch())
        r = client_logado.patch("/api/collections/1", json={"capa_file_id": "abc"})

        assert r.status_code == 400

    def test_nao_mexer_na_capa_nao_a_apaga(self, client_logado, db_roteado):
        """
        Mandar só `{"nome": ...}` não pode zerar a capa escolhida — o PATCH só
        toca os campos presentes no corpo.
        """
        conexao = db_roteado(self._rotas_patch())
        client_logado.patch("/api/collections/1", json={"nome": "Outro"})

        assert not any("capa_file_id" in str(c.args[0])
                       for c in conexao.execute.call_args_list)

    def test_exige_sessao(self, client, db_roteado):
        db_roteado({})
        assert client.patch("/api/collections/1",
                            json={"capa_file_id": 1}).status_code == 401
