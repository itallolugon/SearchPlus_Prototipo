# -*- coding: utf-8 -*-
"""
Espelho nos dois sentidos: remoção da pasta e diff coleção × pasta.

Adicionar à coleção copiava para a pasta, mas remover não apagava — a pasta ia
divergindo para sempre. `DELETE /sync` fecha o ciclo.

Como isso apaga arquivo do disco, a maior parte da bateria testa o que a rota
**se recusa** a fazer. A diferença para a exclusão de pastas é o que está em
jogo: aqui o alvo é uma **cópia** gerada pelo próprio app, não um arquivo do
usuário — o original nas pastas monitoradas nunca entra no caminho.

`GET /sync_status` responde a pergunta que o modo manual deixa em aberto:
quais imagens já foram copiadas e quais faltam.
"""

import os

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture()
def espelho(tmp_path):
    """Pasta espelho com duas cópias dentro."""
    p = tmp_path / "Colecao"
    p.mkdir()
    for n in ("a.jpg", "b.jpg"):
        (p / n).write_text(n, encoding="utf-8")
    return p


def _rotas(destinos, arquivos=(), existe_colecao=True):
    if not isinstance(destinos, (list, tuple)):
        destinos = [destinos]
    return {
        "SELECT id FROM collections": {"fetchone": {"id": 1} if existe_colecao else None},
        "SELECT id, modo_sync FROM collections": {
            "fetchone": {"id": 1, "modo_sync": "manual"} if existe_colecao else None
        },
        "FROM collection_folders": {"fetchall": [{"caminho": str(d)} for d in destinos]},
        "JOIN files f ON f.id = cf.file_id": {
            "fetchall": [{"id": i, "nome": n} for i, n in enumerate(arquivos, start=1)]
        },
    }


class TestRemocaoRecusada:
    """O que a rota NÃO faz."""

    def test_sem_nomes_e_recusado(self, client_logado, db_roteado, espelho):
        db_roteado(_rotas(espelho))
        r = client_logado.delete("/api/collections/1/sync", json={})
        assert r.status_code == 400
        assert sorted(os.listdir(espelho)) == ["a.jpg", "b.jpg"]

    def test_lista_vazia_e_recusada(self, client_logado, db_roteado, espelho):
        db_roteado(_rotas(espelho))
        r = client_logado.delete("/api/collections/1/sync", json={"nomes": []})
        assert r.status_code == 400
        assert len(os.listdir(espelho)) == 2

    def test_nomes_precisa_ser_lista(self, client_logado, db_roteado, espelho):
        db_roteado(_rotas(espelho))
        r = client_logado.delete("/api/collections/1/sync", json={"nomes": "a.jpg"})
        assert r.status_code == 400
        assert len(os.listdir(espelho)) == 2

    def test_travessia_de_caminho_nao_escapa_da_pasta(self, client_logado,
                                                      db_roteado, tmp_path):
        """`..\\..\\algo` não pode apagar fora da pasta espelho."""
        espelho = tmp_path / "Colecao"
        espelho.mkdir()
        vitima = tmp_path / "importante.txt"
        vitima.write_text("nao apague", encoding="utf-8")

        db_roteado(_rotas(espelho))
        client_logado.delete("/api/collections/1/sync",
                             json={"nomes": ["../importante.txt",
                                             r"..\importante.txt"]})

        assert vitima.read_text(encoding="utf-8") == "nao apague"

    def test_nao_apaga_diretorio(self, client_logado, db_roteado, espelho):
        sub = espelho / "subpasta"
        sub.mkdir()
        (sub / "dentro.jpg").write_text("x", encoding="utf-8")

        db_roteado(_rotas(espelho))
        client_logado.delete("/api/collections/1/sync", json={"nomes": ["subpasta"]})

        assert sub.is_dir()
        assert (sub / "dentro.jpg").exists()

    def test_colecao_de_outro_dono_da_404(self, client_logado, db_roteado, espelho):
        db_roteado(_rotas(espelho, existe_colecao=False))
        r = client_logado.delete("/api/collections/9/sync", json={"nomes": ["a.jpg"]})
        assert r.status_code == 404
        assert len(os.listdir(espelho)) == 2

    def test_exige_sessao(self, client, db_roteado, espelho):
        db_roteado({})
        r = client.delete("/api/collections/1/sync", json={"nomes": ["a.jpg"]})
        assert r.status_code == 401
        assert len(os.listdir(espelho)) == 2


class TestRemocaoExecutada:
    def test_apaga_a_copia_da_pasta(self, client_logado, db_roteado, espelho):
        db_roteado(_rotas(espelho))
        corpo = client_logado.delete("/api/collections/1/sync",
                                     json={"nomes": ["a.jpg"]}).get_json()

        assert corpo["apagados"] == 1
        assert os.listdir(espelho) == ["b.jpg"]

    def test_apaga_em_todas_as_pastas_do_conjunto(self, client_logado,
                                                  db_roteado, tmp_path):
        d1, d2 = tmp_path / "E1", tmp_path / "E2"
        for d in (d1, d2):
            d.mkdir()
            (d / "a.jpg").write_text("a", encoding="utf-8")

        db_roteado(_rotas([d1, d2]))
        corpo = client_logado.delete("/api/collections/1/sync",
                                     json={"nomes": ["a.jpg"]}).get_json()

        assert corpo["apagados"] == 2          # uma por pasta
        assert os.listdir(d1) == [] and os.listdir(d2) == []

    def test_arquivo_ausente_nao_e_erro(self, client_logado, db_roteado, espelho):
        db_roteado(_rotas(espelho))
        r = client_logado.delete("/api/collections/1/sync",
                                 json={"nomes": ["nunca_existiu.jpg"]})
        assert r.status_code == 200
        assert r.get_json()["apagados"] == 0

    def test_original_nunca_e_tocado(self, client_logado, db_roteado, tmp_path):
        """A árvore monitorada não entra no laço — só a pasta espelho."""
        monitorada = tmp_path / "Fotos"
        espelho = tmp_path / "Espelho"
        monitorada.mkdir()
        espelho.mkdir()
        (monitorada / "a.jpg").write_text("ORIGINAL", encoding="utf-8")
        (espelho / "a.jpg").write_text("copia", encoding="utf-8")

        db_roteado(_rotas(espelho))
        client_logado.delete("/api/collections/1/sync", json={"nomes": ["a.jpg"]})

        assert (monitorada / "a.jpg").read_text(encoding="utf-8") == "ORIGINAL"
        assert not (espelho / "a.jpg").exists()

    def test_sem_pasta_recebendo_nao_faz_nada(self, client_logado, db_roteado):
        db_roteado(_rotas([]))
        corpo = client_logado.delete("/api/collections/1/sync",
                                     json={"nomes": ["a.jpg"]}).get_json()
        assert corpo["apagados"] == 0


class TestStatusDaPasta:
    def test_separa_o_que_esta_e_o_que_falta(self, client_logado, db_roteado, espelho):
        # Coleção com 3; a pasta tem a.jpg e b.jpg → falta c.jpg
        db_roteado(_rotas(espelho, arquivos=("a.jpg", "b.jpg", "c.jpg")))
        corpo = client_logado.get("/api/collections/1/sync_status").get_json()

        assert corpo["total_colecao"] == 3
        p = corpo["pastas"][0]
        assert sorted(a["nome"] for a in p["na_pasta"]) == ["a.jpg", "b.jpg"]
        assert [a["nome"] for a in p["faltando"]] == ["c.jpg"]

    def test_lista_extras_fora_da_colecao(self, client_logado, db_roteado, espelho):
        """Cópia órfã: saiu da coleção mas ficou no disco."""
        db_roteado(_rotas(espelho, arquivos=("a.jpg",)))
        p = client_logado.get("/api/collections/1/sync_status").get_json()["pastas"][0]

        assert p["extras"] == ["b.jpg"]

    def test_compara_pelo_nome_sanitizado(self, client_logado, db_roteado,
                                          app_module, tmp_path):
        """
        O destino recebe o nome sanitizado. Comparar com o nome cru marcaria
        como "faltando" todo arquivo com caractere inválido no Windows.
        """
        espelho = tmp_path / "Espelho"
        espelho.mkdir()
        bruto = "foto: praia.jpg"
        limpo = app_module._sanitizar_nome(bruto, padrao="arquivo")
        (espelho / limpo).write_text("x", encoding="utf-8")

        db_roteado(_rotas(espelho, arquivos=(bruto,)))
        p = client_logado.get("/api/collections/1/sync_status").get_json()["pastas"][0]

        assert [a["nome"] for a in p["na_pasta"]] == [bruto]
        assert p["faltando"] == []

    def test_pasta_sumida_aparece_como_inexistente(self, client_logado,
                                                   db_roteado, tmp_path):
        db_roteado(_rotas(tmp_path / "foi_embora", arquivos=("a.jpg",)))
        p = client_logado.get("/api/collections/1/sync_status").get_json()["pastas"][0]

        assert p["existe"] is False
        assert p["na_pasta"] == [] and p["faltando"] == []

    def test_colecao_vazia(self, client_logado, db_roteado, espelho):
        db_roteado(_rotas(espelho, arquivos=()))
        corpo = client_logado.get("/api/collections/1/sync_status").get_json()

        assert corpo["total_colecao"] == 0
        assert sorted(corpo["pastas"][0]["extras"]) == ["a.jpg", "b.jpg"]

    def test_colecao_de_outro_dono_da_404(self, client_logado, db_roteado, espelho):
        db_roteado(_rotas(espelho, existe_colecao=False))
        assert client_logado.get("/api/collections/9/sync_status").status_code == 404

    def test_exige_sessao(self, client, db_roteado):
        db_roteado({})
        assert client.get("/api/collections/1/sync_status").status_code == 401
