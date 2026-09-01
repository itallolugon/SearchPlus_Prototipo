# -*- coding: utf-8 -*-
"""
Lixeira: desfazer a exclusão de coleções e de itens.

Excluir uma coleção apagava trabalho que não volta — o agrupamento montado à
mão e o vínculo com as pastas geradas no disco. Um clique errado custava tudo
isso sem recurso.

A abordagem escolhida guarda um RETRATO do que foi apagado, em vez de marcar a
linha original como excluída. A alternativa (`excluido_em` em collections e
collection_files) obrigaria a acrescentar `AND excluido_em IS NULL` a cada uma
das ~22 consultas que leem coleção. Esquecer uma não quebra nada de forma
visível: ela simplesmente passa a enxergar coleção excluída, e o usuário
consegue adicionar uma foto a uma coleção que está na lixeira. Com o retrato,
a linha some de verdade e nenhuma consulta precisa saber que a lixeira existe
— e é isso que a classe TestNenhumaConsultaPrecisaSaber trava.
"""

import json
from unittest import mock

import pytest

pytestmark = pytest.mark.unit


def _sqls(conexao):
    return [str(c.args[0]) for c in conexao.execute.call_args_list]


def _params(conexao, trecho):
    """Parâmetros da primeira consulta que contém `trecho`."""
    for chamada in conexao.execute.call_args_list:
        if trecho in str(chamada.args[0]):
            return chamada.args[1] if len(chamada.args) > 1 else None
    return None


class TestRetratoDaColecao:
    def test_guarda_o_id_original(self, app_module, db_roteado):
        """
        Restaurar com um id novo faria a coleção voltar como se fosse outra, e
        qualquer coisa que apontasse para a antiga passaria a apontar para o
        nada.
        """
        db_roteado({
            "SELECT id, nome, criado_em": {"fetchone": {
                "id": 7, "nome": "Viagem", "criado_em": None,
                "pasta_vinculada": None, "modo_sync": "manual"}},
            "SELECT file_id, adicionado_em": {"fetchall": []},
            "SELECT caminho, recebe": {"fetchall": []},
        })
        conn = app_module.get_db()
        retrato = app_module._retrato_da_colecao(conn, 1, 7)

        assert retrato["id"] == 7
        assert retrato["nome"] == "Viagem"

    def test_guarda_arquivos_e_pastas(self, app_module, db_roteado):
        db_roteado({
            "SELECT id, nome, criado_em": {"fetchone": {
                "id": 7, "nome": "Viagem", "criado_em": None,
                "pasta_vinculada": r"D:\Viagem", "modo_sync": "auto"}},
            "SELECT file_id, adicionado_em": {"fetchall": [
                {"file_id": 11, "adicionado_em": None},
                {"file_id": 12, "adicionado_em": None}]},
            "SELECT caminho, recebe": {"fetchall": [
                {"caminho": r"D:\Viagem", "recebe": True, "criado_em": None}]},
        })
        conn = app_module.get_db()
        retrato = app_module._retrato_da_colecao(conn, 1, 7)

        assert [a["file_id"] for a in retrato["arquivos"]] == [11, 12]
        assert retrato["pastas"][0]["caminho"] == r"D:\Viagem"
        assert retrato["pastas"][0]["recebe"] is True
        assert retrato["modo_sync"] == "auto"

    def test_colecao_de_outro_dono_nao_rende_retrato(self, app_module, db_roteado):
        db_roteado({"SELECT id, nome, criado_em": {"fetchone": None}})
        conn = app_module.get_db()
        assert app_module._retrato_da_colecao(conn, 1, 7) is None


class TestExcluirGuardaAntes:
    def test_retrato_sai_antes_do_delete(self, client_logado, db_roteado):
        """
        Depois do DELETE o ON DELETE CASCADE já levou arquivos e pastas junto,
        e não há mais o que fotografar. A ordem é a feature.
        """
        conexao = db_roteado({
            "SELECT id FROM collections": {"fetchone": {"id": 7}},
            "SELECT id, nome, criado_em": {"fetchone": {
                "id": 7, "nome": "Viagem", "criado_em": None,
                "pasta_vinculada": None, "modo_sync": "manual"}},
            "SELECT file_id, adicionado_em": {"fetchall": []},
            "SELECT caminho, recebe": {"fetchall": []},
            "INSERT INTO lixeira": {"fetchone": {"id": 99}},
        })
        client_logado.delete("/api/collections/7")

        sqls = _sqls(conexao)
        pos_lixeira = next(i for i, q in enumerate(sqls) if "INSERT INTO lixeira" in q)
        pos_delete = next(i for i, q in enumerate(sqls) if "DELETE FROM collections" in q)
        assert pos_lixeira < pos_delete

    def test_devolve_o_id_para_o_desfazer(self, client_logado, db_roteado):
        db_roteado({
            "SELECT id FROM collections": {"fetchone": {"id": 7}},
            "SELECT id, nome, criado_em": {"fetchone": {
                "id": 7, "nome": "Viagem", "criado_em": None,
                "pasta_vinculada": None, "modo_sync": "manual"}},
            "SELECT file_id, adicionado_em": {"fetchall": []},
            "SELECT caminho, recebe": {"fetchall": []},
            "INSERT INTO lixeira": {"fetchone": {"id": 99}},
        })
        corpo = client_logado.delete("/api/collections/7").get_json()

        assert corpo["lixeira_id"] == 99
        assert corpo["nome"] == "Viagem"

    def test_colecao_de_outro_dono_continua_404(self, client_logado, db_roteado):
        db_roteado({"SELECT id FROM collections": {"fetchone": None}})
        assert client_logado.delete("/api/collections/999").status_code == 404


class TestRestaurar:
    def _retrato(self, **extra):
        base = {"id": 7, "nome": "Viagem", "criado_em": None,
                "pasta_vinculada": None, "modo_sync": "manual",
                "arquivos": [{"file_id": 11, "adicionado_em": None}],
                "pastas": []}
        base.update(extra)
        return base

    def test_recria_com_o_mesmo_id(self, app_module, db_roteado):
        conexao = db_roteado({
            "SELECT id FROM collections WHERE user_id": {"fetchone": None},
            "SELECT id FROM files": {"fetchall": [{"id": 11}]},
        })
        ok, motivo = app_module._restaurar_colecao(conexao, 1, self._retrato())

        assert ok is True and motivo == ""
        assert _params(conexao, "INSERT INTO collections")[0] == 7

    def test_recusa_se_o_nome_foi_reaproveitado(self, app_module, db_roteado):
        """
        O usuário criou outra coleção com o mesmo nome durante a espera. O
        UNIQUE (user_id, nome) recusaria o INSERT com um erro de banco; melhor
        explicar e dizer o que fazer.
        """
        conexao = db_roteado({
            "SELECT id FROM collections WHERE user_id": {"fetchone": {"id": 30}},
        })
        ok, motivo = app_module._restaurar_colecao(conexao, 1, self._retrato())

        assert ok is False
        assert "Renomeie" in motivo
        assert not any("INSERT INTO collections" in q for q in _sqls(conexao))

    def test_arquivo_apagado_no_meio_tempo_e_pulado(self, app_module, db_roteado):
        """
        Falhar a restauração inteira por causa de uma foto que o usuário tirou
        da biblioteca seria pior que devolver a coleção sem ela.
        """
        conexao = db_roteado({
            "SELECT id FROM collections WHERE user_id": {"fetchone": None},
            "SELECT id FROM files": {"fetchall": []},     # nenhum sobreviveu
        })
        ok, _ = app_module._restaurar_colecao(conexao, 1, self._retrato())

        assert ok is True
        assert not any("INSERT INTO collection_files" in q for q in _sqls(conexao))

    def test_devolve_as_pastas_geradas(self, app_module, db_roteado):
        conexao = db_roteado({
            "SELECT id FROM collections WHERE user_id": {"fetchone": None},
            "SELECT id FROM files": {"fetchall": [{"id": 11}]},
        })
        app_module._restaurar_colecao(conexao, 1, self._retrato(
            pastas=[{"caminho": r"D:\Viagem", "recebe": True, "criado_em": None}]))

        assert any("INSERT INTO collection_folders" in q for q in _sqls(conexao))

    def test_itens_voltam_para_a_colecao(self, app_module, db_roteado):
        conexao = db_roteado({
            "SELECT id FROM collections WHERE id": {"fetchone": {"id": 7}},
            "SELECT id FROM files": {"fetchall": [{"id": 11}]},
        })
        ok, _ = app_module._restaurar_itens(conexao, 1, {
            "collection_id": 7,
            "arquivos": [{"file_id": 11, "adicionado_em": None}]})

        assert ok is True
        assert any("INSERT INTO collection_files" in q for q in _sqls(conexao))

    def test_itens_sem_colecao_explicam_o_que_fazer(self, app_module, db_roteado):
        conexao = db_roteado({"SELECT id FROM collections WHERE id": {"fetchone": None}})
        ok, motivo = app_module._restaurar_itens(conexao, 1, {
            "collection_id": 7, "arquivos": []})

        assert ok is False
        assert "Restaure a coleção primeiro" in motivo


class TestEndpointRestaurar:
    def _rotas(self, tipo="colecao", conteudo=None):
        conteudo = conteudo or {
            "id": 7, "nome": "Viagem", "criado_em": None, "pasta_vinculada": None,
            "modo_sync": "manual", "arquivos": [], "pastas": []}
        return {
            "SELECT id, tipo, rotulo, conteudo FROM lixeira": {"fetchone": {
                "id": 5, "tipo": tipo, "rotulo": "Viagem",
                "conteudo": conteudo}},
            "SELECT id FROM collections WHERE user_id": {"fetchone": None},
            "SELECT id FROM collections WHERE id": {"fetchone": {"id": 7}},
            "SELECT id FROM files": {"fetchall": []},
        }

    def test_restaura_e_tira_da_lixeira(self, client_logado, db_roteado):
        conexao = db_roteado(self._rotas())
        r = client_logado.post("/api/lixeira/5/restaurar")

        assert r.status_code == 200
        assert any("DELETE FROM lixeira" in q for q in _sqls(conexao))

    def test_so_sai_da_lixeira_depois_de_dar_certo(self, client_logado, db_roteado):
        """
        Apagar o retrato antes deixaria o usuário sem a coleção E sem o que a
        traria de volta — a pior combinação possível.
        """
        rotas = self._rotas()
        rotas["SELECT id FROM collections WHERE user_id"] = {"fetchone": {"id": 30}}
        conexao = db_roteado(rotas)

        r = client_logado.post("/api/lixeira/5/restaurar")

        assert r.status_code == 409
        assert not any("DELETE FROM lixeira" in q for q in _sqls(conexao))
        conexao.rollback.assert_called()

    def test_aceita_conteudo_como_texto(self, app_module, client_logado, db_roteado):
        """
        Dependendo de como a conexão está configurada, JSONB pode chegar como
        dict ou como texto. Só um dos dois funcionar seria uma falha que só
        aparece em produção.
        """
        conteudo = {"id": 7, "nome": "Viagem", "criado_em": None,
                    "pasta_vinculada": None, "modo_sync": "manual",
                    "arquivos": [], "pastas": []}
        db_roteado(self._rotas(conteudo=json.dumps(conteudo)))

        assert client_logado.post("/api/lixeira/5/restaurar").status_code == 200

    def test_item_que_nao_existe_da_404(self, client_logado, db_roteado):
        db_roteado({"SELECT id, tipo, rotulo, conteudo FROM lixeira": {"fetchone": None}})
        assert client_logado.post("/api/lixeira/999/restaurar").status_code == 404

    def test_tipo_desconhecido_nao_apaga_o_retrato(self, client_logado, db_roteado):
        conexao = db_roteado(self._rotas(tipo="algo_novo"))
        r = client_logado.post("/api/lixeira/5/restaurar")

        assert r.status_code == 409
        assert not any("DELETE FROM lixeira" in q for q in _sqls(conexao))

    def test_exige_sessao(self, client, db_roteado):
        db_roteado({})
        assert client.post("/api/lixeira/5/restaurar").status_code == 401


class TestListarEDescartar:
    def test_lista_o_que_esta_na_lixeira(self, client_logado, db_roteado):
        db_roteado({
            "SELECT id, tipo, rotulo, excluido_em": {"fetchall": [
                {"id": 5, "tipo": "colecao", "rotulo": "Viagem",
                 "excluido_em": None,
                 "conteudo": {"arquivos": [{"file_id": 1}, {"file_id": 2}]}}]},
            "DELETE FROM lixeira": {"fetchall": []},
        })
        corpo = client_logado.get("/api/lixeira").get_json()

        assert corpo["itens"][0]["rotulo"] == "Viagem"
        assert corpo["itens"][0]["imagens"] == 2
        assert corpo["dias"] == 30

    def test_expurga_o_vencido_ao_abrir(self, client_logado, db_roteado):
        conexao = db_roteado({
            "SELECT id, tipo, rotulo, excluido_em": {"fetchall": []},
            "DELETE FROM lixeira": {"fetchall": []},
        })
        client_logado.get("/api/lixeira")

        expurgo = next(q for q in _sqls(conexao) if "DELETE FROM lixeira" in q)
        assert "make_interval" in expurgo

    def test_descartar_apaga_de_vez(self, client_logado, db_roteado):
        db_roteado({"DELETE FROM lixeira": {"fetchone": {"id": 5}}})
        assert client_logado.delete("/api/lixeira/5").status_code == 200

    def test_descartar_o_que_nao_existe_da_404(self, client_logado, db_roteado):
        db_roteado({"DELETE FROM lixeira": {"fetchone": None}})
        assert client_logado.delete("/api/lixeira/999").status_code == 404

    def test_listar_exige_sessao(self, client, db_roteado):
        db_roteado({})
        assert client.get("/api/lixeira").status_code == 401

    def test_descartar_exige_sessao(self, client, db_roteado):
        db_roteado({})
        assert client.delete("/api/lixeira/5").status_code == 401


class TestNenhumaConsultaPrecisaSaber:
    """
    O que justifica ter escolhido o retrato em vez de `excluido_em`.

    Se alguém trocar a abordagem depois e marcar a linha em vez de apagá-la,
    estes testes falham — e é o aviso de que agora existem ~22 consultas
    obrigadas a filtrar, cada uma um lugar onde dá para esquecer.
    """

    def test_a_exclusao_apaga_a_linha_de_verdade(self, client_logado, db_roteado):
        conexao = db_roteado({
            "SELECT id FROM collections": {"fetchone": {"id": 7}},
            "SELECT id, nome, criado_em": {"fetchone": {
                "id": 7, "nome": "Viagem", "criado_em": None,
                "pasta_vinculada": None, "modo_sync": "manual"}},
            "SELECT file_id, adicionado_em": {"fetchall": []},
            "SELECT caminho, recebe": {"fetchall": []},
            "INSERT INTO lixeira": {"fetchone": {"id": 99}},
        })
        client_logado.delete("/api/collections/7")

        assert any("DELETE FROM collections" in q for q in _sqls(conexao))

    def test_a_listagem_nao_filtra_excluidos(self, client_logado, db_roteado):
        """
        Não precisa: a coleção excluída não está mais na tabela. Se um dia
        precisar, é sinal de que a abordagem mudou.
        """
        conexao = db_roteado({"FROM collections": {"fetchall": []}})
        client_logado.get("/api/collections")

        for consulta in _sqls(conexao):
            assert "excluido_em" not in consulta
