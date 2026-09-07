# -*- coding: utf-8 -*-
"""
A listagem de coleções dispara um número fixo de consultas.

Antes eram duas etapas: uma consulta trazia as coleções e, para cada uma
delas, outra buscava as 4 imagens da capa. Com 50 coleções isso virava 51
idas ao banco. Como o Postgres é remoto (Supabase), o custo não estava no
plano de execução — estava na latência de rede, multiplicada por coleção.

Agora uma única consulta traz as capas de todas as coleções de uma vez,
usando ROW_NUMBER() para pegar as 4 primeiras de cada grupo.

O que este arquivo protege não é a velocidade — é a *forma* da solução.
Um `for` inocente reintroduzindo um SELECT dentro do laço passaria em todos
os outros testes, porque a resposta continuaria correta. Só a contagem de
consultas denuncia a volta do problema.
"""

import pytest

pytestmark = pytest.mark.unit

# O mesmo usuário que o conftest põe na sessão de `client_logado`.
UID_DA_SESSAO = 4242


def _colecoes(n):
    return [
        {
            "id": i,
            "nome": f"Colecao {i}",
            "total": 4,
            "criado_em": None,
            "pasta_vinculada": None,
            "modo_sync": "manual",
            "capa_file_id": None,
            "capa_caminho": None,
        }
        for i in range(1, n + 1)
    ]


def _capas(n, por_colecao=4):
    return [
        {"colecao_id": i, "caminho": f"C:/Fotos/{i}_{k}.jpg"}
        for i in range(1, n + 1)
        for k in range(por_colecao)
    ]


def _consultas(conexao):
    """SQL de cada chamada a execute(), na ordem em que saíram."""
    return [str(c.args[0]) for c in conexao.execute.call_args_list]


def _rotas(n):
    return {"FROM collections": {"fetchall": _colecoes(n)}, "ROW_NUMBER": {"fetchall": _capas(n)}}


class TestNumeroDeConsultas:
    @pytest.mark.parametrize("n_colecoes", [1, 10, 30, 50])
    def test_nao_cresce_com_o_numero_de_colecoes(self, client_logado, db_roteado, n_colecoes):
        """O aceite do item: 2 consultas, tenha o usuário 1 coleção ou 50."""
        conexao = db_roteado(_rotas(n_colecoes))
        client_logado.get("/api/collections")

        assert len(_consultas(conexao)) == 2

    def test_uma_consulta_para_a_lista_e_uma_para_as_capas(self, client_logado, db_roteado):
        conexao = db_roteado(_rotas(5))
        client_logado.get("/api/collections")

        lista, capas = _consultas(conexao)
        assert "FROM collections c" in lista
        assert "ROW_NUMBER" in capas

    def test_sem_colecao_nao_consulta_capas(self, client_logado, db_roteado):
        """Sem coleção não há capa para buscar; a segunda ida ao banco é pura perda."""
        conexao = db_roteado({"FROM collections": {"fetchall": []}})
        corpo = client_logado.get("/api/collections").get_json()

        assert corpo["colecoes"] == []
        assert len(_consultas(conexao)) == 1


class TestConsultaDasCapas:
    def test_limita_a_quatro_por_colecao(self, client_logado, db_roteado):
        """
        O corte das 4 é do banco, não do Python: trazer todas as imagens de
        todas as coleções para descartar no servidor desperdiçaria justamente
        a rede que o item veio economizar.
        """
        conexao = db_roteado(_rotas(3))
        client_logado.get("/api/collections")

        capas = _consultas(conexao)[1]
        assert "posicao <= 4" in capas

    def test_agrupa_por_colecao_e_ordena_pela_mais_recente(self, client_logado, db_roteado):
        conexao = db_roteado(_rotas(3))
        client_logado.get("/api/collections")

        capas = _consultas(conexao)[1]
        assert "PARTITION BY cf.collection_id" in capas
        assert "ORDER BY cf.adicionado_em DESC" in capas

    def test_ordem_das_capas_e_estavel(self, client_logado, db_roteado):
        """
        Sem ORDER BY no SELECT de fora o Postgres pode devolver as 4 capas em
        qualquer ordem, e o mosaico da coleção mudaria de arranjo a cada
        recarga da tela sem nada ter mudado.
        """
        conexao = db_roteado(_rotas(3))
        client_logado.get("/api/collections")

        assert "ORDER BY colecao_id, posicao" in _consultas(conexao)[1]

    def test_filtra_pelo_dono_dentro_da_consulta(self, client_logado, db_roteado):
        """
        A consulta das capas parte de collection_files, que não tem dono. Sem
        o JOIN em collections com o user_id, a capa de uma coleção alheia
        entraria no mosaico — vazamento de caminho de arquivo de outra pessoa.
        """
        conexao = db_roteado(_rotas(2))
        client_logado.get("/api/collections")

        capas_sql = _consultas(conexao)[1]
        assert "JOIN collections c ON c.id = cf.collection_id" in capas_sql
        assert "c.user_id = %s" in capas_sql

        chamada_capas = conexao.execute.call_args_list[1]
        assert chamada_capas.args[1][0] == UID_DA_SESSAO

    def test_traz_so_imagem(self, client_logado, db_roteado):
        """PDF e vídeo não entram no mosaico."""
        conexao = db_roteado(_rotas(2))
        client_logado.get("/api/collections")

        chamada_capas = conexao.execute.call_args_list[1]
        assert "f.tipo = ANY(%s)" in str(chamada_capas.args[0])
        assert "jpg" in chamada_capas.args[1][1]


class TestRespostaContinuaIgual:
    def test_distribui_as_capas_pela_colecao_certa(self, client_logado, db_roteado):
        """O risco da consulta única: misturar as capas entre coleções."""
        db_roteado(
            {
                "FROM collections": {"fetchall": _colecoes(3)},
                "ROW_NUMBER": {
                    "fetchall": [
                        {"colecao_id": 1, "caminho": "C:/a.jpg"},
                        {"colecao_id": 3, "caminho": "C:/c1.jpg"},
                        {"colecao_id": 3, "caminho": "C:/c2.jpg"},
                    ]
                },
            }
        )
        por_id = {c["id"]: c for c in client_logado.get("/api/collections").get_json()["colecoes"]}

        assert por_id[1]["capas"] == ["C:/a.jpg"]
        assert por_id[2]["capas"] == []  # sem imagem, sem capa
        assert por_id[3]["capas"] == ["C:/c1.jpg", "C:/c2.jpg"]

    def test_preserva_a_ordem_que_o_banco_devolveu(self, client_logado, db_roteado):
        db_roteado(
            {
                "FROM collections": {"fetchall": _colecoes(1)},
                "ROW_NUMBER": {
                    "fetchall": [
                        {"colecao_id": 1, "caminho": "C:/nova.jpg"},
                        {"colecao_id": 1, "caminho": "C:/antiga.jpg"},
                    ]
                },
            }
        )
        colecao = client_logado.get("/api/collections").get_json()["colecoes"][0]
        assert colecao["capas"] == ["C:/nova.jpg", "C:/antiga.jpg"]

    def test_campos_da_colecao_seguem_os_mesmos(self, client_logado, db_roteado):
        """O front já consome estas chaves; a otimização não pode mexer nelas."""
        db_roteado(_rotas(1))
        colecao = client_logado.get("/api/collections").get_json()["colecoes"][0]

        assert set(colecao) == {
            "id",
            "nome",
            "total",
            "criado_em",
            "capas",
            "capa",
            "capa_file_id",
            "pasta_vinculada",
            "modo_sync",
        }

    def test_exige_sessao(self, client, db_roteado):
        db_roteado({})
        assert client.get("/api/collections").status_code == 401
