# -*- coding: utf-8 -*-
"""
Histórico das exportações e o que fazer com o que falhou.

O resultado de uma exportação sumia junto com o modal. Quem exportou 200 fotos,
viu "8 falharam" e fechou a janela ficava sem saber quais eram, para onde tinha
exportado, nem se aquilo era de hoje ou da semana passada.

Com o histórico, duas ações passam a ser possíveis — e a separação entre elas é
o que dá sentido ao item:

    repetir          para falhas que o tempo pode ter resolvido
    limpar_sumidos   para arquivos que não vão voltar

Insistir num arquivo apagado daria a mesma falha para sempre; tirar da coleção
um arquivo que só estava num disco desconectado destruiria trabalho.
"""

import json
from unittest import mock

import pytest

pytestmark = pytest.mark.unit

UID = 4242


# `None` explícito significa "não existe"; sem sentinela, o valor padrão do
# helper engoliria o caso que os testes de 404 precisam montar.
_PADRAO = object()


def _falhas(*pares):
    return [{"nome": n, "motivo": m} for n, m in pares]


def _registro(**extra):
    base = {
        "id": 1,
        "collection_id": 3,
        "colecao": "Viagem",
        "pasta": "D:/Fotos/Viagem",
        "total": 12,
        "copiados": 9,
        "falhas": _falhas(("a.jpg", "sem_permissao"), ("b.jpg", "nao_encontrado")),
        "estado": "concluido",
        "quando": None,
    }
    base.update(extra)
    return base


def _sqls(conexao):
    return [str(c.args[0]) for c in conexao.execute.call_args_list]


class TestListagem:
    def test_lista_as_exportacoes(self, client_logado, db_roteado):
        db_roteado({"FROM exportacoes": {"fetchall": [_registro()]}})
        corpo = client_logado.get("/api/exportacoes").get_json()

        e = corpo["exportacoes"][0]
        assert e["colecao"] == "Viagem"
        assert e["copiados"] == 9
        assert len(e["falhas"]) == 2

    def test_diz_se_a_pasta_ainda_existe(self, client_logado, db_roteado, tmp_path):
        """
        A pasta pode ter sido movida ou apagada depois. Um botão "abrir pasta"
        que não abre nada é pior que nenhum botão.
        """
        db_roteado(
            {
                "FROM exportacoes": {
                    "fetchall": [
                        _registro(pasta=str(tmp_path)),
                        _registro(id=2, pasta=str(tmp_path / "sumiu")),
                    ]
                }
            }
        )
        itens = client_logado.get("/api/exportacoes").get_json()["exportacoes"]

        assert itens[0]["pasta_existe"] is True
        assert itens[1]["pasta_existe"] is False

    def test_aceita_falhas_como_texto(self, client_logado, db_roteado):
        """JSONB chega como dict ou como texto conforme a conexão."""
        db_roteado(
            {
                "FROM exportacoes": {
                    "fetchall": [_registro(falhas=json.dumps(_falhas(("x.jpg", "erro_leitura"))))]
                }
            }
        )
        e = client_logado.get("/api/exportacoes").get_json()["exportacoes"][0]

        assert e["falhas"][0]["nome"] == "x.jpg"

    def test_limita_a_trinta(self, client_logado, db_roteado):
        """O histórico responde "o que aconteceu naquela vez", não é livro-caixa."""
        conexao = db_roteado({"FROM exportacoes": {"fetchall": []}})
        client_logado.get("/api/exportacoes")

        assert "LIMIT 30" in _sqls(conexao)[0]

    def test_so_as_do_proprio_usuario(self, client_logado, db_roteado):
        conexao = db_roteado({"FROM exportacoes": {"fetchall": []}})
        client_logado.get("/api/exportacoes")

        assert "user_id = %s" in _sqls(conexao)[0]

    def test_exige_sessao(self, client, db_roteado):
        db_roteado({})
        assert client.get("/api/exportacoes").status_code == 401


class TestRegistro:
    def test_falha_ao_registrar_nao_derruba_o_worker(self, app_module, db_roteado):
        """
        Isto roda no thread da exportação. Uma exceção aqui mataria o worker
        DEPOIS de copiar tudo — o trabalho feito, e o usuário vendo a barra
        parada para sempre.
        """
        conexao = db_roteado({})
        conexao.execute.side_effect = RuntimeError("banco fora do ar")

        app_module._registrar_exportacao(
            {
                "user_id": 1,
                "collection_id": 1,
                "colecao": "V",
                "pasta": "D:/x",
                "total": 1,
                "copiados": 1,
                "falhas": [],
                "estado": "concluido",
            }
        )

        conexao.rollback.assert_called()


class TestRepetir:
    def _rotas(self, reg=_PADRAO, arquivos=None):
        return {
            "SELECT id, collection_id, colecao, pasta, falhas": {
                "fetchone": _registro() if reg is _PADRAO else reg
            },
            "FROM collection_files cf": {"fetchall": arquivos or []},
            "SELECT path FROM folders": {"fetchall": [{"path": "C:/Fotos"}]},
        }

    def test_repete_so_o_que_pode_dar_certo(self, client_logado, db_roteado, tmp_path):
        """
        `nao_encontrado` fica de fora: o arquivo sumiu do disco e tentar de
        novo daria exatamente a mesma coisa.
        """
        conexao = db_roteado(
            self._rotas(
                reg=_registro(pasta=str(tmp_path)),
                arquivos=[
                    {
                        "nome": "a.jpg",
                        "caminho": "C:/Fotos/a.jpg",
                        "tipo": "jpg",
                        "data_adicionado": None,
                    }
                ],
            )
        )
        with mock.patch.object(__import__("threading"), "Thread"):
            corpo = client_logado.post("/api/exportacoes/1/repetir").get_json()

        assert corpo["total"] == 1
        consulta = next(q for q in _sqls(conexao) if "FROM collection_files cf" in q)
        assert "f.nome = ANY(%s)" in consulta

    def test_so_sumidos_nao_da_o_que_repetir(self, client_logado, db_roteado, tmp_path):
        db_roteado(
            self._rotas(
                reg=_registro(pasta=str(tmp_path), falhas=_falhas(("b.jpg", "nao_encontrado")))
            )
        )
        r = client_logado.post("/api/exportacoes/1/repetir")

        assert r.status_code == 400
        assert "não estão mais no computador" in r.get_json()["error"]

    def test_pasta_que_sumiu_e_recusada(self, client_logado, db_roteado, tmp_path):
        db_roteado(self._rotas(reg=_registro(pasta=str(tmp_path / "nao_existe"))))
        r = client_logado.post("/api/exportacoes/1/repetir")

        assert r.status_code == 400
        assert "pasta" in r.get_json()["error"]

    def test_arquivos_fora_da_colecao_e_recusado(self, client_logado, db_roteado, tmp_path):
        """Removidos da coleção depois da exportação: não há o que copiar."""
        db_roteado(self._rotas(reg=_registro(pasta=str(tmp_path)), arquivos=[]))
        r = client_logado.post("/api/exportacoes/1/repetir")

        assert r.status_code == 400

    def test_exportacao_alheia_da_404(self, client_logado, db_roteado):
        db_roteado(self._rotas(reg=None))
        assert client_logado.post("/api/exportacoes/999/repetir").status_code == 404

    def test_exige_sessao(self, client, db_roteado):
        db_roteado({})
        assert client.post("/api/exportacoes/1/repetir").status_code == 401


class TestLimparSumidos:
    def _rotas(self, reg=_PADRAO, candidatos=None):
        return {
            "SELECT id, collection_id, colecao, falhas": {
                "fetchone": _registro() if reg is _PADRAO else reg
            },
            "FROM collection_files cf": {"fetchall": candidatos or []},
            "INSERT INTO lixeira": {"fetchone": {"id": 55}},
        }

    def test_tira_da_colecao_o_que_sumiu(self, client_logado, db_roteado, tmp_path):
        conexao = db_roteado(
            self._rotas(
                candidatos=[
                    {
                        "id": 7,
                        "nome": "b.jpg",
                        "caminho": str(tmp_path / "sumida.jpg"),
                        "adicionado_em": None,
                    }
                ]
            )
        )
        corpo = client_logado.post("/api/exportacoes/1/limpar_sumidos").get_json()

        assert corpo["removidos"] == 1
        assert any("DELETE FROM collection_files" in q for q in _sqls(conexao))

    def test_passa_pela_lixeira(self, client_logado, db_roteado, tmp_path):
        """Disco desconectado e não apagado: tem de dar para desfazer."""
        conexao = db_roteado(
            self._rotas(
                candidatos=[
                    {
                        "id": 7,
                        "nome": "b.jpg",
                        "caminho": str(tmp_path / "sumida.jpg"),
                        "adicionado_em": None,
                    }
                ]
            )
        )
        corpo = client_logado.post("/api/exportacoes/1/limpar_sumidos").get_json()

        assert corpo["lixeira_id"] == 55
        assert any("INSERT INTO lixeira" in q for q in _sqls(conexao))

    def test_arquivo_que_voltou_nao_e_removido(self, client_logado, db_roteado, tmp_path):
        """
        A existência é conferida NA HORA, não pelo que a exportação registrou:
        entre uma coisa e outra o disco externo pode ter sido reconectado, e
        tirar da coleção um arquivo que voltou seria destruir trabalho.
        """
        voltou = tmp_path / "voltou.jpg"
        voltou.write_text("x", encoding="utf-8")

        conexao = db_roteado(
            self._rotas(
                candidatos=[
                    {"id": 7, "nome": "b.jpg", "caminho": str(voltou), "adicionado_em": None}
                ]
            )
        )
        corpo = client_logado.post("/api/exportacoes/1/limpar_sumidos").get_json()

        assert corpo["removidos"] == 0
        assert "voltaram" in corpo["mensagem"]
        assert not any("DELETE FROM collection_files" in q for q in _sqls(conexao))

    def test_sem_sumidos_explica(self, client_logado, db_roteado):
        db_roteado(self._rotas(reg=_registro(falhas=_falhas(("a.jpg", "sem_permissao")))))
        r = client_logado.post("/api/exportacoes/1/limpar_sumidos")

        assert r.status_code == 400
        assert "sumiu" in r.get_json()["error"]

    def test_colecao_excluida_depois(self, client_logado, db_roteado):
        """
        A FK é ON DELETE SET NULL: o histórico sobrevive à exclusão da coleção,
        mas não há de onde remover nada.
        """
        db_roteado(self._rotas(reg=_registro(collection_id=None)))
        r = client_logado.post("/api/exportacoes/1/limpar_sumidos")

        assert r.status_code == 400
        assert "não existe mais" in r.get_json()["error"]

    def test_exportacao_alheia_da_404(self, client_logado, db_roteado):
        db_roteado(self._rotas(reg=None))
        assert client_logado.post("/api/exportacoes/999/limpar_sumidos").status_code == 404

    def test_exige_sessao(self, client, db_roteado):
        db_roteado({})
        assert client.post("/api/exportacoes/1/limpar_sumidos").status_code == 401
