# -*- coding: utf-8 -*-
"""
Pasta vinculada: PATCH da coleção e sincronia com a pasta espelho.

O produto pergunta **uma vez**, ao criar a coleção, se ela tem uma pasta no
computador e o que fazer quando novas imagens entram. Depois disso a decisão
está no banco (`pasta_vinculada` + `modo_sync`) e o app obedece calado.

O que estes testes protegem:

1. **O PATCH é parcial.** Mandar só `modo_sync` não pode apagar a pasta já
   vinculada — seria perder configuração sem o usuário pedir.
2. **A sincronia espelha, não acumula.** Arquivo que já está no destino é
   pulado, não duplicado com sufixo. É o oposto da exportação, que nunca
   sobrescreve e sempre cria `nome_1`.
3. **Nada é destruído.** Origem intacta, e o que já estava na pasta continua lá.
"""

import os

import pytest

pytestmark = pytest.mark.unit


class TestPatchDaColecao:
    def test_renomeia(self, client_logado, db_roteado):
        db_roteado({
            "FROM collections": {"fetchone": {"id": 1, "nome": "Novo Nome",
                                              "pasta_vinculada": None,
                                              "modo_sync": "manual"}},
        })
        r = client_logado.patch("/api/collections/1", json={"nome": "Novo Nome"})
        assert r.status_code == 200
        assert r.get_json()["nome"] == "Novo Nome"

    def test_recusa_nome_vazio(self, client_logado, db_roteado):
        db_roteado({})
        assert client_logado.patch("/api/collections/1", json={"nome": "   "}).status_code == 400

    def test_recusa_modo_invalido(self, client_logado, db_roteado):
        db_roteado({})
        r = client_logado.patch("/api/collections/1", json={"modo_sync": "turbo"})
        assert r.status_code == 400

    @pytest.mark.parametrize("modo", ["auto", "perguntar", "manual"])
    def test_aceita_os_tres_modos(self, client_logado, db_roteado, modo):
        db_roteado({
            "FROM collections": {"fetchone": {"id": 1, "nome": "C",
                                              "pasta_vinculada": r"D:\Fotos\C",
                                              "modo_sync": modo}},
        })
        r = client_logado.patch("/api/collections/1", json={"modo_sync": modo})
        assert r.status_code == 200
        assert r.get_json()["modo_sync"] == modo

    def test_corpo_vazio_e_recusado(self, client_logado, db_roteado):
        db_roteado({})
        assert client_logado.patch("/api/collections/1", json={}).status_code == 400

    def test_patch_parcial_nao_apaga_a_pasta(self, client_logado, db_roteado):
        """Mandar só o modo não pode zerar `pasta_vinculada` (regressão)."""
        conexao = db_roteado({
            "FROM collections": {"fetchone": {"id": 1, "nome": "C",
                                              "pasta_vinculada": r"D:\Fotos\C",
                                              "modo_sync": "auto"}},
        })
        client_logado.patch("/api/collections/1", json={"modo_sync": "auto"})

        updates = [str(c.args[0]) for c in conexao.execute.call_args_list
                   if "UPDATE collections" in str(c.args[0])]
        assert updates, "nenhum UPDATE foi executado"
        assert "pasta_vinculada" not in updates[0]

    def test_desvincular_volta_para_manual(self, client_logado, db_roteado):
        conexao = db_roteado({
            "FROM collections": {"fetchone": {"id": 1, "nome": "C",
                                              "pasta_vinculada": None,
                                              "modo_sync": "manual"}},
        })
        client_logado.patch("/api/collections/1", json={"pasta_vinculada": None})

        sql = next(str(c.args[0]) for c in conexao.execute.call_args_list
                   if "UPDATE collections" in str(c.args[0]))
        assert "pasta_vinculada = NULL" in sql
        assert "modo_sync = 'manual'" in sql

    def test_pasta_inexistente_e_recusada(self, client_logado, db_roteado, tmp_path):
        db_roteado({})
        sumida = str(tmp_path / "nao_existe")
        r = client_logado.patch("/api/collections/1", json={"pasta_vinculada": sumida})
        assert r.status_code == 400

    def test_colecao_de_outro_dono_da_404(self, client_logado, db_roteado):
        db_roteado({"FROM collections": {"fetchone": None}})
        r = client_logado.patch("/api/collections/99", json={"nome": "X"})
        assert r.status_code == 404

    def test_exige_sessao(self, client, db_roteado):
        db_roteado({})
        assert client.patch("/api/collections/1", json={"nome": "X"}).status_code == 401


class TestCriarPastaAoVincular:
    def test_cria_a_subpasta_com_o_nome_da_colecao(self, client_logado, db_roteado, tmp_path):
        db_roteado({
            "SELECT nome FROM collections": {"fetchone": {"nome": "Arquitetura"}},
            "FROM collections": {"fetchone": {"id": 1, "nome": "Arquitetura",
                                              "pasta_vinculada": None,
                                              "modo_sync": "auto"}},
        })
        r = client_logado.patch("/api/collections/1",
                                json={"criar_pasta_em": str(tmp_path), "modo_sync": "auto"})
        assert r.status_code == 200
        assert (tmp_path / "Arquitetura").is_dir()

    def test_sanitiza_o_nome_da_pasta(self, client_logado, db_roteado, tmp_path):
        db_roteado({
            "SELECT nome FROM collections": {"fetchone": {"nome": "Ferias 2024/2025"}},
            "FROM collections": {"fetchone": {"id": 1, "nome": "Ferias 2024/2025",
                                              "pasta_vinculada": None,
                                              "modo_sync": "manual"}},
        })
        client_logado.patch("/api/collections/1", json={"criar_pasta_em": str(tmp_path)})
        criadas = [p.name for p in tmp_path.iterdir() if p.is_dir()]
        assert criadas and "/" not in criadas[0]

    def test_nao_escreve_dentro_de_pasta_existente(self, client_logado, db_roteado, tmp_path):
        antiga = tmp_path / "Natureza"
        antiga.mkdir()
        (antiga / "preciso.txt").write_text("nao apague", encoding="utf-8")

        db_roteado({
            "SELECT nome FROM collections": {"fetchone": {"nome": "Natureza"}},
            "FROM collections": {"fetchone": {"id": 1, "nome": "Natureza",
                                              "pasta_vinculada": None,
                                              "modo_sync": "manual"}},
        })
        client_logado.patch("/api/collections/1", json={"criar_pasta_em": str(tmp_path)})

        assert (antiga / "preciso.txt").read_text(encoding="utf-8") == "nao apague"
        assert (tmp_path / "Natureza (1)").is_dir()

    def test_destino_inexistente_e_recusado(self, client_logado, db_roteado, tmp_path):
        db_roteado({})
        r = client_logado.patch("/api/collections/1",
                                json={"criar_pasta_em": str(tmp_path / "fantasma")})
        assert r.status_code == 400


@pytest.fixture()
def cenario_sync(tmp_path):
    """Pasta monitorada com arquivos + pasta vinculada de destino."""
    origem = tmp_path / "Fotos"
    destino = tmp_path / "Espelho"
    origem.mkdir()
    destino.mkdir()
    for n in ("a.jpg", "b.jpg", "c.jpg"):
        (origem / n).write_text(n, encoding="utf-8")
    return origem, destino


def _rotas_sync(origem, destino, arquivos, modo="auto"):
    return {
        "FROM collections": {"fetchone": {"id": 1, "nome": "C",
                                          "pasta_vinculada": str(destino),
                                          "modo_sync": modo}},
        "JOIN files f ON f.id = cf.file_id": {
            "fetchall": [{"nome": n, "caminho": str(origem / n)} for n in arquivos]
        },
        "SELECT path FROM folders": {"fetchall": [{"path": str(origem)}]},
    }


class TestSincronia:
    def test_copia_para_a_pasta_vinculada(self, client_logado, db_roteado, cenario_sync):
        origem, destino = cenario_sync
        db_roteado(_rotas_sync(origem, destino, ["a.jpg", "b.jpg"]))

        corpo = client_logado.post("/api/collections/1/sync", json={}).get_json()

        assert corpo["copiados"] == 2
        assert sorted(os.listdir(destino)) == ["a.jpg", "b.jpg"]

    def test_originais_intactos(self, client_logado, db_roteado, cenario_sync):
        origem, destino = cenario_sync
        db_roteado(_rotas_sync(origem, destino, ["a.jpg"]))
        client_logado.post("/api/collections/1/sync", json={})
        assert (origem / "a.jpg").read_text(encoding="utf-8") == "a.jpg"

    def test_arquivo_ja_no_destino_e_pulado_nao_duplicado(self, client_logado,
                                                          db_roteado, cenario_sync):
        """A pasta é um espelho: sincronizar duas vezes não gera `a_1.jpg`."""
        origem, destino = cenario_sync
        (destino / "a.jpg").write_text("a.jpg", encoding="utf-8")
        db_roteado(_rotas_sync(origem, destino, ["a.jpg"]))

        corpo = client_logado.post("/api/collections/1/sync", json={}).get_json()

        assert corpo["copiados"] == 0
        assert corpo["ja_existiam"] == 1
        assert os.listdir(destino) == ["a.jpg"]

    def test_arquivo_ausente_vira_falha_sem_abortar(self, client_logado,
                                                   db_roteado, cenario_sync):
        origem, destino = cenario_sync
        db_roteado(_rotas_sync(origem, destino, ["a.jpg", "sumiu.jpg"]))

        corpo = client_logado.post("/api/collections/1/sync", json={}).get_json()

        assert corpo["copiados"] == 1
        assert [f["motivo"] for f in corpo["falhas"]] == ["nao_encontrado"]

    def test_arquivo_fora_das_pastas_monitoradas_e_recusado(self, client_logado,
                                                            db_roteado, tmp_path):
        origem = tmp_path / "Fotos"
        destino = tmp_path / "Espelho"
        origem.mkdir()
        destino.mkdir()
        intruso = tmp_path / "segredo.txt"
        intruso.write_text("chave", encoding="utf-8")

        db_roteado({
            "FROM collections": {"fetchone": {"id": 1, "nome": "C",
                                              "pasta_vinculada": str(destino),
                                              "modo_sync": "auto"}},
            "JOIN files f ON f.id = cf.file_id": {
                "fetchall": [{"nome": "segredo.txt", "caminho": str(intruso)}]
            },
            "SELECT path FROM folders": {"fetchall": [{"path": str(origem)}]},
        })

        corpo = client_logado.post("/api/collections/1/sync", json={}).get_json()

        assert corpo["copiados"] == 0
        assert corpo["falhas"][0]["motivo"] == "fora_das_pastas"
        assert os.listdir(destino) == []

    def test_sem_pasta_vinculada_e_recusado(self, client_logado, db_roteado):
        db_roteado({
            "FROM collections": {"fetchone": {"id": 1, "nome": "C",
                                              "pasta_vinculada": None,
                                              "modo_sync": "manual"}},
        })
        assert client_logado.post("/api/collections/1/sync", json={}).status_code == 400

    def test_pasta_vinculada_sumiu_do_disco(self, client_logado, db_roteado, tmp_path):
        """409, e a mensagem orienta — não é um erro técnico."""
        db_roteado({
            "FROM collections": {"fetchone": {"id": 1, "nome": "C",
                                              "pasta_vinculada": str(tmp_path / "foi_embora"),
                                              "modo_sync": "auto"}},
        })
        r = client_logado.post("/api/collections/1/sync", json={})
        assert r.status_code == 409
        assert "Vincule" in r.get_json()["error"]

    def test_lista_vazia_nao_faz_nada(self, client_logado, db_roteado, cenario_sync):
        origem, destino = cenario_sync
        db_roteado(_rotas_sync(origem, destino, []))
        corpo = client_logado.post("/api/collections/1/sync",
                                   json={"file_ids": []}).get_json()
        assert corpo["copiados"] == 0
        assert os.listdir(destino) == []

    def test_file_ids_invalido_e_recusado(self, client_logado, db_roteado, cenario_sync):
        origem, destino = cenario_sync
        db_roteado(_rotas_sync(origem, destino, []))
        r = client_logado.post("/api/collections/1/sync", json={"file_ids": "1,2"})
        assert r.status_code == 400

    def test_exige_sessao(self, client, db_roteado):
        db_roteado({})
        assert client.post("/api/collections/1/sync", json={}).status_code == 401
