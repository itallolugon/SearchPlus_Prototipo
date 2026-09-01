# -*- coding: utf-8 -*-
"""
Pastas geradas: registro, listagem, abertura e exclusão.

Duas funcionalidades apoiadas numa tabela só (`collection_folders`):

* **Abrir a pasta.** Exige que o app saiba onde a pasta está — o que só é
  possível porque toda pasta criada fica registrada. Antes disso, exportar era
  um retrato sem memória: as imagens adicionadas depois não tinham para onde
  ir, e o botão de abrir não tinha o que abrir.

* **Excluir com escolha.** Ao apagar a coleção, o usuário vê as pastas e decide
  uma a uma. Manter a pasta e descartar a coleção é uma escolha legítima.

`DELETE /folders` apaga arquivo do computador **sem lixeira**. A maior parte
desta bateria testa o que ele se RECUSA a fazer — as travas importam mais que
o caminho feliz.
"""

import os

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture()
def pasta_gerada(tmp_path):
    """Uma pasta com arquivos dentro, como uma exportação deixaria."""
    p = tmp_path / "Natureza"
    p.mkdir()
    for n in ("a.jpg", "b.jpg"):
        (p / n).write_text(n, encoding="utf-8")
    return p


def _rotas(pastas, vinculada=None, existe_colecao=True):
    return {
        "SELECT id, pasta_vinculada FROM collections": {
            "fetchone": {"id": 1, "pasta_vinculada": str(vinculada) if vinculada else None}
            if existe_colecao else None
        },
        "SELECT id FROM collections": {"fetchone": {"id": 1} if existe_colecao else None},
        "FROM collection_folders": {"fetchall": [{"caminho": str(p)} for p in pastas]},
    }


class TestListagem:
    def test_lista_as_pastas_com_contagem(self, client_logado, db_roteado, pasta_gerada):
        db_roteado(_rotas([pasta_gerada], vinculada=pasta_gerada))
        corpo = client_logado.get("/api/collections/1/folders").get_json()

        assert len(corpo["pastas"]) == 1
        p = corpo["pastas"][0]
        assert p["nome"] == "Natureza"
        assert p["existe"] is True
        assert p["vinculada"] is True
        assert p["arquivos"] == 2

    def test_marca_pasta_que_sumiu_do_disco(self, client_logado, db_roteado, tmp_path):
        fantasma = tmp_path / "ja_era"
        db_roteado(_rotas([fantasma]))
        p = client_logado.get("/api/collections/1/folders").get_json()["pastas"][0]

        assert p["existe"] is False
        assert p["arquivos"] == 0

    def test_colecao_sem_pastas(self, client_logado, db_roteado):
        db_roteado(_rotas([]))
        assert client_logado.get("/api/collections/1/folders").get_json()["pastas"] == []

    def test_colecao_de_outro_dono_da_404(self, client_logado, db_roteado):
        db_roteado(_rotas([], existe_colecao=False))
        assert client_logado.get("/api/collections/9/folders").status_code == 404

    def test_exige_sessao(self, client, db_roteado):
        db_roteado({})
        assert client.get("/api/collections/1/folders").status_code == 401


class TestExclusaoRecusada:
    """O que a rota NÃO faz. Cada teste aqui protege dado do usuário."""

    def test_sem_confirmacao_nao_apaga(self, client_logado, db_roteado, pasta_gerada):
        db_roteado(_rotas([pasta_gerada]))
        r = client_logado.delete("/api/collections/1/folders",
                                 json={"caminhos": [str(pasta_gerada)]})
        assert r.status_code == 400
        assert pasta_gerada.is_dir()          # continua lá

    def test_confirmacao_falsa_nao_apaga(self, client_logado, db_roteado, pasta_gerada):
        db_roteado(_rotas([pasta_gerada]))
        r = client_logado.delete("/api/collections/1/folders",
                                 json={"caminhos": [str(pasta_gerada)], "confirmar": False})
        assert r.status_code == 400
        assert pasta_gerada.is_dir()

    def test_confirmacao_precisa_ser_booleano(self, client_logado, db_roteado, pasta_gerada):
        # "true" (string) não é confirmação — evita aceitar coerção acidental.
        db_roteado(_rotas([pasta_gerada]))
        r = client_logado.delete("/api/collections/1/folders",
                                 json={"caminhos": [str(pasta_gerada)], "confirmar": "true"})
        assert r.status_code == 400
        assert pasta_gerada.is_dir()

    def test_sem_caminhos_nao_apaga_nada(self, client_logado, db_roteado, pasta_gerada):
        """Não existe 'apagar todas' implícito."""
        db_roteado(_rotas([pasta_gerada]))
        r = client_logado.delete("/api/collections/1/folders", json={"confirmar": True})
        assert r.status_code == 400
        assert pasta_gerada.is_dir()

    def test_lista_vazia_nao_apaga_nada(self, client_logado, db_roteado, pasta_gerada):
        db_roteado(_rotas([pasta_gerada]))
        r = client_logado.delete("/api/collections/1/folders",
                                 json={"caminhos": [], "confirmar": True})
        assert r.status_code == 400
        assert pasta_gerada.is_dir()

    def test_caminho_nao_registrado_e_recusado(self, client_logado, db_roteado, tmp_path):
        """A trava central: só apaga pasta que o app criou para esta coleção."""
        intrusa = tmp_path / "documentos_do_usuario"
        intrusa.mkdir()
        (intrusa / "importante.txt").write_text("nao apague", encoding="utf-8")

        db_roteado(_rotas([]))          # nada registrado
        corpo = client_logado.delete("/api/collections/1/folders",
                                     json={"caminhos": [str(intrusa)],
                                           "confirmar": True}).get_json()

        assert corpo["apagadas"] == []
        assert corpo["falhas"][0]["motivo"] == "nao_autorizada"
        assert (intrusa / "importante.txt").exists()

    def test_pasta_de_outra_colecao_e_recusada(self, client_logado, db_roteado, tmp_path):
        outra = tmp_path / "DeOutraColecao"
        outra.mkdir()
        (outra / "x.jpg").write_text("x", encoding="utf-8")

        db_roteado(_rotas([tmp_path / "MinhaPasta"]))   # registro não inclui `outra`
        corpo = client_logado.delete("/api/collections/1/folders",
                                     json={"caminhos": [str(outra)],
                                           "confirmar": True}).get_json()

        assert corpo["falhas"][0]["motivo"] == "nao_autorizada"
        assert outra.is_dir()

    def test_colecao_de_outro_dono_da_404(self, client_logado, db_roteado, pasta_gerada):
        db_roteado(_rotas([pasta_gerada], existe_colecao=False))
        r = client_logado.delete("/api/collections/9/folders",
                                 json={"caminhos": [str(pasta_gerada)], "confirmar": True})
        assert r.status_code == 404
        assert pasta_gerada.is_dir()

    def test_exige_sessao(self, client, db_roteado, pasta_gerada):
        db_roteado({})
        r = client.delete("/api/collections/1/folders",
                          json={"caminhos": [str(pasta_gerada)], "confirmar": True})
        assert r.status_code == 401
        assert pasta_gerada.is_dir()


class TestExclusaoExecutada:
    def test_apaga_a_pasta_escolhida(self, client_logado, db_roteado, pasta_gerada):
        db_roteado(_rotas([pasta_gerada]))
        corpo = client_logado.delete("/api/collections/1/folders",
                                     json={"caminhos": [str(pasta_gerada)],
                                           "confirmar": True}).get_json()

        assert corpo["apagadas"] == [str(pasta_gerada)]
        assert not pasta_gerada.exists()

    def test_apaga_so_a_selecionada(self, client_logado, db_roteado, tmp_path):
        """O ponto do pedido: excluir uma pasta e manter a outra."""
        a = tmp_path / "Natureza"
        b = tmp_path / "Natureza (1)"
        a.mkdir(); b.mkdir()
        (a / "x.jpg").write_text("x", encoding="utf-8")
        (b / "y.jpg").write_text("y", encoding="utf-8")

        db_roteado(_rotas([a, b]))
        client_logado.delete("/api/collections/1/folders",
                             json={"caminhos": [str(b)], "confirmar": True})

        assert a.is_dir() and (a / "x.jpg").exists()   # preservada
        assert not b.exists()                           # apagada

    def test_pasta_ja_ausente_nao_e_erro(self, client_logado, db_roteado, tmp_path):
        fantasma = tmp_path / "sumiu"
        db_roteado(_rotas([fantasma]))
        r = client_logado.delete("/api/collections/1/folders",
                                 json={"caminhos": [str(fantasma)], "confirmar": True})

        assert r.status_code == 200
        assert r.get_json()["falhas"] == []

    def test_pasta_apagada_sai_do_conjunto_de_destinos(self, client_logado,
                                                       db_roteado, pasta_gerada):
        """Sem isto, a próxima adição tentaria copiar para um caminho morto."""
        conexao = db_roteado(_rotas([pasta_gerada], vinculada=pasta_gerada))
        client_logado.delete("/api/collections/1/folders",
                             json={"caminhos": [str(pasta_gerada)], "confirmar": True})

        # A linha de collection_folders some junto com a pasta — é o que a tira
        # do conjunto. Resta ajustar o espelho em collections.
        sqls = [str(c.args[0]) for c in conexao.execute.call_args_list]
        assert any("DELETE FROM collection_folders" in q for q in sqls)
        assert any("UPDATE collections SET pasta_vinculada" in q for q in sqls)

    def test_nao_toca_o_que_esta_fora_da_pasta(self, client_logado, db_roteado, tmp_path):
        """rmtree é recursivo: confirma que o raio de ação para na pasta."""
        alvo = tmp_path / "Colecao"
        alvo.mkdir()
        (alvo / "dentro.jpg").write_text("x", encoding="utf-8")
        vizinho = tmp_path / "vizinho.txt"
        vizinho.write_text("intocado", encoding="utf-8")

        db_roteado(_rotas([alvo]))
        client_logado.delete("/api/collections/1/folders",
                             json={"caminhos": [str(alvo)], "confirmar": True})

        assert not alvo.exists()
        assert vizinho.read_text(encoding="utf-8") == "intocado"


class TestAbrirPasta:
    def test_recusa_caminho_nao_registrado(self, client_logado, db_roteado, tmp_path):
        qualquer = tmp_path / "particular"
        qualquer.mkdir()
        db_roteado({"FROM collection_folders": {"fetchall": []}})

        r = client_logado.get(f"/api/open_folder?path={qualquer}")
        assert r.status_code == 403

    def test_pasta_registrada_passa_pela_autorizacao(self, client_logado,
                                                     db_roteado, pasta_gerada):
        db_roteado({"FROM collection_folders": {"fetchall": [{"caminho": str(pasta_gerada)}]}})
        r = client_logado.get(f"/api/open_folder?path={pasta_gerada}")
        # 200 no Windows; 501 em outro SO — o que importa é NÃO ser 403.
        assert r.status_code != 403

    def test_registrada_mas_ausente_da_404(self, client_logado, db_roteado, tmp_path):
        fantasma = tmp_path / "sumiu"
        db_roteado({"FROM collection_folders": {"fetchall": [{"caminho": str(fantasma)}]}})
        assert client_logado.get(f"/api/open_folder?path={fantasma}").status_code == 404

    def test_exige_sessao(self, client, db_roteado, pasta_gerada):
        db_roteado({})
        assert client.get(f"/api/open_folder?path={pasta_gerada}").status_code == 401
