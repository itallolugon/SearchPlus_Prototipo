# -*- coding: utf-8 -*-
"""
A seleção sobrevive ao recarregamento, mas não ao fechar a aba.

`_selecionados` vivia só em memória. Quem montou uma seleção de 40 imagens e
recarregou por engano — ou teve o servidor reiniciando no meio — perdia tudo e
tinha de refazer clique a clique.

Continua sendo um passo de trabalho, e não um estado guardado: por isso
`sessionStorage` no front, e não `localStorage`. O que este arquivo cobre é a
parte do servidor — dizer quais dos ids guardados ainda existem.

Sem essa checagem, restaurar uma seleção feita antes de o usuário remover uma
pasta do índice faria a barra dizer "12 imagens selecionadas" e a coleção
receber 9, sem ninguém entender a diferença.
"""

import pytest

pytestmark = pytest.mark.unit

UID = 4242


class TestIdsValidos:
    def test_devolve_so_os_que_existem(self, client_logado, db_roteado):
        db_roteado({"SELECT id FROM files": {"fetchall": [{"id": 1}, {"id": 3}]}})
        corpo = client_logado.post("/api/files/validos",
                                   json={"ids": [1, 2, 3]}).get_json()

        assert corpo["ids"] == [1, 3]

    def test_lista_vazia_nao_consulta_o_banco(self, client_logado, db_roteado):
        conexao = db_roteado({})
        corpo = client_logado.post("/api/files/validos", json={"ids": []}).get_json()

        assert corpo["ids"] == []
        assert not conexao.execute.called

    def test_ids_invalidos_sao_descartados(self, client_logado, db_roteado):
        """
        O conteúdo vem do armazenamento do navegador, que pode ter sido
        editado à mão ou ter sobrado de uma versão antiga do app.
        """
        conexao = db_roteado({"SELECT id FROM files": {"fetchall": [{"id": 1}]}})
        r = client_logado.post("/api/files/validos",
                               json={"ids": [1, "abc", None, {"x": 1}]})

        assert r.status_code == 200
        chamada = conexao.execute.call_args_list[0]
        assert chamada.args[1][0] == [1]

    def test_corpo_sem_lista_e_recusado(self, client_logado, db_roteado):
        db_roteado({})
        assert client_logado.post("/api/files/validos",
                                  json={"ids": "1,2,3"}).status_code == 400

    def test_corpo_vazio_e_recusado(self, client_logado, db_roteado):
        db_roteado({})
        assert client_logado.post("/api/files/validos", json={}).status_code == 400

    def test_limita_a_quantidade(self, client_logado, db_roteado):
        """Sem teto, um armazenamento corrompido viraria um IN gigante."""
        conexao = db_roteado({"SELECT id FROM files": {"fetchall": []}})
        client_logado.post("/api/files/validos", json={"ids": list(range(9000))})

        chamada = conexao.execute.call_args_list[0]
        assert len(chamada.args[1][0]) <= 5000

    def test_so_devolve_arquivo_do_dono(self, client_logado, db_roteado):
        """
        Os ids vêm do navegador e podem ser qualquer número. Sem o filtro de
        dono, isto viraria um jeito de descobrir quais ids existem na conta de
        outra pessoa.
        """
        conexao = db_roteado({"SELECT id FROM files": {"fetchall": []}})
        client_logado.post("/api/files/validos", json={"ids": [1, 2]})

        chamada = conexao.execute.call_args_list[0]
        assert "user_id = %s" in str(chamada.args[0])
        assert chamada.args[1][1] == UID

    def test_exige_sessao(self, client, db_roteado):
        db_roteado({})
        assert client.post("/api/files/validos",
                           json={"ids": [1]}).status_code == 401
