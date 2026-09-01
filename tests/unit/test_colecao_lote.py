# -*- coding: utf-8 -*-
"""
Adição em lote de arquivos a uma coleção.

É o endpoint que a seleção múltipla e o "selecionar tudo" alimentam: uma
chamada com N ids, em vez de N chamadas. E é ele que informa quantos itens
entraram de fato — número que a confirmação de exportação imediata exibe.

Duas invariantes sustentam a feature:

1. **Idempotência.** Re-adicionar não duplica e não é erro. Quem garante é a PK
   composta `(collection_id, file_id)` mais o `ON CONFLICT DO NOTHING` — não a
   interface. Estes testes travam o contrato da resposta, não a regra do banco.
2. **Isolamento por usuário.** Nenhum id de outro dono pode entrar na coleção,
   mesmo vindo no meio de um lote legítimo.
"""

import pytest

pytestmark = pytest.mark.unit


def _params_do_sql(conexao, trecho):
    """Parâmetros da primeira consulta cujo SQL contém `trecho`."""
    for chamada in conexao.execute.call_args_list:
        if trecho in str(chamada.args[0]):
            return chamada.args[1] if len(chamada.args) > 1 else ()
    raise AssertionError(f"Nenhuma consulta com {trecho!r} foi executada.")


def _achatar(params):
    """Junta num só conjunto os ids de params que podem vir aninhados."""
    plano = set()
    for p in params:
        if isinstance(p, (list, tuple)):
            plano.update(p)
        else:
            plano.add(p)
    return plano


class TestNormalizacaoDeEntrada:
    def test_aceita_lista_em_file_ids(self, client_logado, db_roteado):
        db_roteado({
            "FROM collections": {"fetchone": {"id": 1}},
            "FROM files":       {"fetchall": [{"id": 1}, {"id": 2}, {"id": 3}]},
            "INSERT INTO collection_files": {"fetchall": [{"file_id": 1}, {"file_id": 2}, {"file_id": 3}]},
        })
        r = client_logado.post("/api/collections/1/files", json={"file_ids": [1, 2, 3]})
        assert r.status_code == 200
        assert r.get_json()["adicionados"] == 3

    def test_aceita_file_id_singular_formato_antigo(self, client_logado, db_roteado):
        # O painel lateral ainda chama assim; quebrar isso seria regressão.
        db_roteado({
            "FROM collections": {"fetchone": {"id": 1}},
            "FROM files":       {"fetchall": [{"id": 42}]},
            "INSERT INTO collection_files": {"fetchall": [{"file_id": 42}]},
        })
        r = client_logado.post("/api/collections/1/files", json={"file_id": 42})
        assert r.status_code == 200
        assert r.get_json()["adicionados"] == 1

    def test_remove_ids_repetidos_do_proprio_lote(self, client_logado, db_roteado):
        # "Selecionar tudo" sobre um grid já parcialmente marcado pode repetir.
        conexao = db_roteado({
            "FROM collections": {"fetchone": {"id": 1}},
            "FROM files":       {"fetchall": [{"id": 1}, {"id": 2}]},
            "INSERT INTO collection_files": {"fetchall": [{"file_id": 1}, {"file_id": 2}]},
        })
        client_logado.post("/api/collections/1/files", json={"file_ids": [1, 2, 1, 2, 1]})

        enviados = _params_do_sql(conexao, "SELECT id FROM files")
        assert enviados[0] == [1, 2]

    def test_recusa_file_ids_que_nao_e_lista(self, client_logado, db_roteado):
        db_roteado({})
        r = client_logado.post("/api/collections/1/files", json={"file_ids": "1,2,3"})
        assert r.status_code == 400

    def test_recusa_id_nao_numerico(self, client_logado, db_roteado):
        db_roteado({})
        r = client_logado.post("/api/collections/1/files", json={"file_ids": [1, "abc"]})
        assert r.status_code == 400

    def test_recusa_lote_vazio(self, client_logado, db_roteado):
        db_roteado({})
        r = client_logado.post("/api/collections/1/files", json={"file_ids": []})
        assert r.status_code == 400


class TestIdempotencia:
    def test_informa_quantos_ja_estavam_na_colecao(self, client_logado, db_roteado):
        # 3 enviados, o banco aceitou 1 → os outros 2 já estavam lá.
        db_roteado({
            "FROM collections": {"fetchone": {"id": 1}},
            "FROM files":       {"fetchall": [{"id": 1}, {"id": 2}, {"id": 3}]},
            "INSERT INTO collection_files": {"fetchall": [{"file_id": 3}]},
        })
        corpo = client_logado.post(
            "/api/collections/1/files", json={"file_ids": [1, 2, 3]}
        ).get_json()
        assert corpo["adicionados"] == 1
        assert corpo["ja_existiam"] == 2

    def test_reenviar_tudo_nao_e_erro(self, client_logado, db_roteado):
        # Nenhuma linha nova, mas a operação é bem-sucedida.
        db_roteado({
            "FROM collections": {"fetchone": {"id": 1}},
            "FROM files":       {"fetchall": [{"id": 1}, {"id": 2}]},
            "INSERT INTO collection_files": {"fetchall": []},
        })
        r = client_logado.post("/api/collections/1/files", json={"file_ids": [1, 2]})
        assert r.status_code == 200
        corpo = r.get_json()
        assert corpo["adicionados"] == 0
        assert corpo["ja_existiam"] == 2

    def test_soma_bate_com_o_lote_enviado(self, client_logado, db_roteado):
        db_roteado({
            "FROM collections": {"fetchone": {"id": 1}},
            "FROM files":       {"fetchall": [{"id": i} for i in range(1, 6)]},
            "INSERT INTO collection_files": {"fetchall": [{"file_id": 4}, {"file_id": 5}]},
        })
        corpo = client_logado.post(
            "/api/collections/1/files", json={"file_ids": [1, 2, 3, 4, 5]}
        ).get_json()
        assert corpo["adicionados"] + corpo["ja_existiam"] == 5


class TestIsolamentoPorUsuario:
    def test_ignora_arquivo_de_outro_dono_dentro_do_lote(self, client_logado, db_roteado):
        # 3 enviados, o filtro por user_id devolve 2: o intruso não entra.
        conexao = db_roteado({
            "FROM collections": {"fetchone": {"id": 1}},
            "FROM files":       {"fetchall": [{"id": 1}, {"id": 2}]},
            "INSERT INTO collection_files": {"fetchall": [{"file_id": 1}, {"file_id": 2}]},
        })
        client_logado.post("/api/collections/1/files", json={"file_ids": [1, 2, 999]})

        inseridos = _params_do_sql(conexao, "INSERT INTO collection_files")
        assert 999 not in _achatar(inseridos)

    def test_colecao_de_outro_dono_da_404(self, client_logado, db_roteado):
        db_roteado({"FROM collections": {"fetchone": None}})
        r = client_logado.post("/api/collections/77/files", json={"file_ids": [1]})
        assert r.status_code == 404

    def test_nenhum_arquivo_proprio_da_404(self, client_logado, db_roteado):
        db_roteado({
            "FROM collections": {"fetchone": {"id": 1}},
            "FROM files":       {"fetchall": []},
        })
        r = client_logado.post("/api/collections/1/files", json={"file_ids": [999]})
        assert r.status_code == 404

    def test_exige_sessao(self, client, db_roteado):
        db_roteado({})
        r = client.post("/api/collections/1/files", json={"file_ids": [1]})
        assert r.status_code == 401


class TestRemocaoEmLote:
    def test_remove_varios_de_uma_vez(self, client_logado, db_roteado):
        db_roteado({
            # `nome` vem junto: depois do DELETE não há mais como saber que
            # arquivo era, e é pelo nome que a cópia é achada na pasta espelho.
            "SELECT nome FROM files": {"fetchall": [{"nome": "a.jpg"}, {"nome": "b.jpg"}]},
            "FROM collections": {"fetchone": {"id": 1, "modo_sync": "manual"}},
            "FROM files":       {"fetchall": [{"id": 1}, {"id": 2}]},
            "FROM collection_folders": {"fetchall": []},
            "DELETE FROM collection_files": {"fetchall": []},
        })
        corpo = client_logado.delete(
            "/api/collections/1/files", json={"file_ids": [1, 2]}
        ).get_json()
        assert corpo["acao"] == "removido"
        assert corpo["removidos"] == 2
        assert corpo["nomes_removidos"] == ["a.jpg", "b.jpg"]
        assert corpo["modo_sync"] == "manual"
