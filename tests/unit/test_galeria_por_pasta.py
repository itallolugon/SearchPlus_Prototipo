# -*- coding: utf-8 -*-
"""
Escolher quais pastas a home mostra.

A home agrupa por categoria misturando tudo que foi indexado. Com duas pastas
importadas — as fotos do celular e o arquivo do trabalho, por exemplo — as duas
caem no mesmo "Pessoas", e não havia nem como saber de onde cada imagem veio,
nem como olhar uma pasta de cada vez.

São **três** estados, e confundir dois deles já custou uma correção:

    parâmetro ausente   todas      quem nunca escolheu vê tudo
    "nenhuma"           nenhuma    quem desmarcou tudo quer a home limpa
    "1,2"               essas

A primeira versão usava lista vazia para "todas", e por isso desmarcar a última
pasta voltava para "todas" — a escolha do usuário era simplesmente ignorada.
Quem desmarca tudo quer usar só a busca. A diferença entre "não escolhi" e
"escolhi zero" precisa existir no protocolo, não só na cabeça de quem clicou.
"""

import pytest

pytestmark = pytest.mark.unit

UID = 4242


def _rotas(arquivos=None, pastas=None):
    return {
        "FROM folders p": {"fetchall": pastas or []},
        "FROM files WHERE user_id": {"fetchall": arquivos or []},
    }


def _imagem(id_, descricao="pessoas na praia"):
    return {"id": id_, "nome": f"f{id_}.jpg", "caminho": f"C:/x/f{id_}.jpg",
            "tipo": "jpg", "descricao_ia": descricao,
            "data_adicionado": None, "favorito": 0}


def _pasta(id_, nome, imagens):
    return {"id": id_, "path": f"C:/{nome}", "name": nome, "imagens": imagens}


def _sqls(conexao):
    return [str(c.args[0]) for c in conexao.execute.call_args_list]


class TestSemFiltro:
    def test_sem_parametro_traz_tudo(self, client_logado, db_roteado):
        conexao = db_roteado(_rotas(arquivos=[_imagem(1), _imagem(2)]))
        corpo = client_logado.get("/api/gallery").get_json()

        assert corpo["total_imagens"] == 2
        assert corpo["pastas_ativas"] == []
        assert not any("folder_id = ANY" in q for q in _sqls(conexao))

    def test_parametro_vazio_e_o_mesmo_que_sem_filtro(self, client_logado, db_roteado):
        """
        `?pastas=` vem do front quando a pessoa volta para "todas". Ler isso
        como "nenhuma pasta" esvaziaria a home.
        """
        conexao = db_roteado(_rotas(arquivos=[_imagem(1)]))
        corpo = client_logado.get("/api/gallery?pastas=").get_json()

        assert corpo["total_imagens"] == 1
        assert not any("folder_id = ANY" in q for q in _sqls(conexao))


class TestComFiltro:
    def test_filtra_pelas_pastas_pedidas(self, client_logado, db_roteado):
        conexao = db_roteado(_rotas(arquivos=[_imagem(1)]))
        corpo = client_logado.get("/api/gallery?pastas=3,7").get_json()

        assert corpo["pastas_ativas"] == [3, 7]
        principal = next(q for q in _sqls(conexao) if "FROM files WHERE user_id" in q)
        assert "folder_id = ANY(%s)" in principal

    def test_id_invalido_e_descartado_sem_derrubar(self, client_logado, db_roteado):
        """
        O parâmetro vem da URL e pode chegar torto. Um id não numérico não
        pode virar 500 numa tela que é a primeira coisa que o usuário vê.
        """
        db_roteado(_rotas(arquivos=[]))
        r = client_logado.get("/api/gallery?pastas=3,abc,,7")

        assert r.status_code == 200
        assert r.get_json()["pastas_ativas"] == [3, 7]

    def test_so_lixo_equivale_a_sem_filtro(self, client_logado, db_roteado):
        conexao = db_roteado(_rotas(arquivos=[_imagem(1)]))
        corpo = client_logado.get("/api/gallery?pastas=abc,xyz").get_json()

        assert corpo["pastas_ativas"] == []
        assert not any("folder_id = ANY" in q for q in _sqls(conexao))


class TestNenhumaPasta:
    """
    O caso que a primeira versão ignorava: às vezes a pessoa quer a home limpa
    e só a barra de busca.
    """

    def test_nenhuma_nao_traz_imagem(self, client_logado, db_roteado):
        db_roteado(_rotas(arquivos=[_imagem(1), _imagem(2)]))
        corpo = client_logado.get("/api/gallery?pastas=nenhuma").get_json()

        assert corpo["grupos"] == []
        assert corpo["total_imagens"] == 0

    def test_nenhuma_nao_consulta_arquivo_nenhum(self, client_logado, db_roteado):
        """
        Trazer a biblioteca inteira do banco remoto para descartar tudo em
        seguida seria pagar o custo da consulta sem usar nada dela.
        """
        conexao = db_roteado(_rotas(arquivos=[_imagem(1)]))
        client_logado.get("/api/gallery?pastas=nenhuma")

        assert not any("FROM files WHERE user_id" in q for q in _sqls(conexao))

    def test_nenhuma_ainda_lista_as_pastas(self, client_logado, db_roteado):
        """
        O seletor continua na tela e precisa dos nomes — é por ele que a
        pessoa desfaz a escolha.
        """
        db_roteado(_rotas(pastas=[_pasta(1, "Fotos", 612)]))
        corpo = client_logado.get("/api/gallery?pastas=nenhuma").get_json()

        assert [p["nome"] for p in corpo["pastas"]] == ["Fotos"]

    def test_a_resposta_distingue_os_tres_estados(self, client_logado, db_roteado):
        """
        `pastas_ativas` vem vazio tanto em "todas" quanto em "nenhuma". Sem um
        campo próprio, o front não teria como saber qual dos dois desenhar.
        """
        db_roteado(_rotas(arquivos=[_imagem(1)]))
        assert client_logado.get("/api/gallery").get_json()["mostrando"] == "todas"

        db_roteado(_rotas(arquivos=[_imagem(1)]))
        assert client_logado.get(
            "/api/gallery?pastas=nenhuma").get_json()["mostrando"] == "nenhuma"

        db_roteado(_rotas(arquivos=[_imagem(1)]))
        assert client_logado.get(
            "/api/gallery?pastas=3").get_json()["mostrando"] == "algumas"

    def test_nenhuma_ignora_caixa(self, client_logado, db_roteado):
        db_roteado(_rotas(arquivos=[_imagem(1)]))
        assert client_logado.get(
            "/api/gallery?pastas=NENHUMA").get_json()["total_imagens"] == 0

    def test_uma_pasta_chamada_nenhuma_nao_confunde(self, client_logado, db_roteado):
        """
        O valor é comparado com a palavra inteira, não procurado dentro da
        lista: `?pastas=1,2` com uma pasta chamada "nenhuma" não some com tudo.
        """
        conexao = db_roteado(_rotas(arquivos=[_imagem(1)]))
        corpo = client_logado.get("/api/gallery?pastas=1,2").get_json()

        assert corpo["mostrando"] == "algumas"
        assert any("FROM files WHERE user_id" in q for q in _sqls(conexao))


class TestPastasDisponiveis:
    def test_lista_as_pastas_com_a_contagem(self, client_logado, db_roteado):
        """
        Nomes E números vão junto da galeria de propósito: o seletor precisa
        dos dois, e uma segunda chamada faria a tela montar em dois tempos.
        """
        db_roteado(_rotas(
            arquivos=[_imagem(1)],
            pastas=[_pasta(1, "Fotos", 612), _pasta(2, "Trabalho", 28)]))

        corpo = client_logado.get("/api/gallery").get_json()

        assert [p["nome"] for p in corpo["pastas"]] == ["Fotos", "Trabalho"]
        assert [p["imagens"] for p in corpo["pastas"]] == [612, 28]

    def test_pasta_sem_imagem_ainda_aparece(self, client_logado, db_roteado):
        """
        Some da lista, e quem importou uma pasta e ainda não a analisou acha
        que o app perdeu a pasta. O LEFT JOIN existe para isso.
        """
        db_roteado(_rotas(arquivos=[], pastas=[_pasta(9, "Nova", 0)]))
        corpo = client_logado.get("/api/gallery").get_json()

        assert corpo["pastas"] == [
            {"id": 9, "nome": "Nova", "caminho": "C:/Nova", "imagens": 0}]

    def test_pasta_sem_nome_cai_para_o_caminho(self, client_logado, db_roteado):
        db_roteado(_rotas(pastas=[{"id": 1, "path": "D:/Sem", "name": None,
                                   "imagens": 3}]))
        corpo = client_logado.get("/api/gallery").get_json()

        assert corpo["pastas"][0]["nome"] == "D:/Sem"

    def test_so_conta_imagem_indexada(self, client_logado, db_roteado):
        conexao = db_roteado(_rotas())
        client_logado.get("/api/gallery")

        das_pastas = next(q for q in _sqls(conexao) if "FROM folders p" in q)
        assert "f.processado = 1" in das_pastas
        assert "f.tipo = ANY(%s)" in das_pastas


class TestPosse:
    def test_so_as_pastas_do_proprio_usuario(self, client_logado, db_roteado):
        conexao = db_roteado(_rotas())
        client_logado.get("/api/gallery")

        das_pastas = next(q for q in _sqls(conexao) if "FROM folders p" in q)
        assert "p.user_id = %s" in das_pastas

    def test_filtrar_por_pasta_alheia_nao_vaza(self, client_logado, db_roteado):
        """
        O id vem da URL e pode ser qualquer número. O filtro por pasta é um AND
        sobre uma consulta que já exige `user_id` — pedir a pasta de outra
        pessoa devolve vazio, não o conteúdo dela.
        """
        conexao = db_roteado(_rotas(arquivos=[]))
        client_logado.get("/api/gallery?pastas=99999")

        principal = next(q for q in _sqls(conexao) if "FROM files WHERE user_id" in q)
        assert "user_id = %s" in principal
        assert "folder_id = ANY(%s)" in principal

    def test_exige_sessao(self, client, db_roteado):
        db_roteado({})
        assert client.get("/api/gallery").status_code == 401
