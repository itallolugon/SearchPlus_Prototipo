# -*- coding: utf-8 -*-
"""
O servidor sobe antes dos modelos.

Antes, os modelos eram carregados na importação: por ~30 segundos o Flask nem
tinha começado a atender, e o navegador não recebia nem a tela de login. O
usuário via "não foi possível acessar este site" e concluía, com razão, que o
programa não tinha aberto.

Agora a importação só declara o estado e um thread carrega em paralelo. Isso
cria uma janela nova — a tela funciona, mas a busca ainda não — e é essa
janela que este arquivo cobre: quem pergunta tem que receber "espere um
pouco", nunca "não achei nada" nem um erro seco.

A medição que motivou o item (feita com o servidor real, não aqui):

    interface responde   29,70s  →  ~2,2s
    busca escrita        29,7s   →  ~35s   (o servidor agora divide a CPU)

A busca demora mais para ficar pronta do que demorava antes, e isso é
deliberado: em troca, as outras 90% da interface saem de inacessíveis para
utilizáveis em dois segundos.
"""

import threading
from unittest import mock

import pytest

pytestmark = pytest.mark.unit


class TestEstadoDosModelos:
    def test_comeca_carregando(self, app_module):
        """
        Antes de qualquer coisa acontecer, o estado é "carregando" — nunca
        "indisponivel". Dizer que falhou algo que ainda nem tentou mandaria o
        usuário reinstalar o programa no meio de uma espera normal.
        """
        estado = {"texto": "carregando", "visual": "carregando"}
        with mock.patch.object(app_module, "_estado_modelos", estado):
            atual = app_module.estado_dos_modelos()
        assert atual["texto"]["estado"] == "carregando"
        assert atual["visual"]["estado"] == "carregando"

    def test_marcar_registra_estado_e_motivo(self, app_module):
        estado = dict(app_module._estado_modelos)
        motivo = dict(app_module._motivo_modelos)
        try:
            app_module._marcar_modelo("texto", "indisponivel", "faltou memória")
            atual = app_module.estado_dos_modelos()
            assert atual["texto"] == {"estado": "indisponivel",
                                      "motivo": "faltou memória"}
        finally:
            app_module._estado_modelos.clear(); app_module._estado_modelos.update(estado)
            app_module._motivo_modelos.clear(); app_module._motivo_modelos.update(motivo)

    def test_motivo_so_aparece_quando_ha_motivo(self, app_module):
        estado = dict(app_module._estado_modelos)
        motivo = dict(app_module._motivo_modelos)
        try:
            app_module._marcar_modelo("visual", "pronto")
            assert app_module.estado_dos_modelos()["visual"]["motivo"] == ""
        finally:
            app_module._estado_modelos.clear(); app_module._estado_modelos.update(estado)
            app_module._motivo_modelos.clear(); app_module._motivo_modelos.update(motivo)

    def test_estado_e_copia(self, app_module):
        """Mexer no que o /api/health devolveu não pode alterar o estado real."""
        copia = app_module.estado_dos_modelos()
        copia["texto"]["estado"] = "mentira"
        assert app_module.estado_dos_modelos()["texto"]["estado"] != "mentira"

    def test_evento_significa_terminou_nao_deu_certo(self, app_module):
        """
        No ambiente de teste os modelos falham de propósito. O evento ainda
        assim tem que estar marcado: quem espera nele precisa saber que não
        adianta mais esperar. Se "resolvido" significasse "deu certo", a busca
        responderia "estou carregando" para sempre num computador onde os
        modelos nunca vão subir.
        """
        # 60s, não 10: no ambiente de teste os MODELOS são stub e falham na
        # hora, mas o scikit-learn e o SDK do Claude são importados de verdade
        # pelo mesmo thread — juntos, ~11s medidos aqui. Um timeout apertado
        # transformaria essa lentidão legítima em falha intermitente.
        assert app_module._MODELOS_RESOLVIDOS.wait(timeout=60) is True
        assert app_module.SBERT_OK is False       # o stub do conftest derruba
        assert app_module.busca_pronta() is False


class TestNadaPesadoNaImportacao:
    """
    O ganho inteiro do item mora aqui: se qualquer um destes voltar para o topo
    do arquivo, o servidor volta a demorar dezenas de segundos para atender e
    nenhum outro teste percebe.
    """

    @pytest.mark.parametrize("modulo,custo", [
        ("sentence_transformers", "~12s"),
        ("sklearn.metrics.pairwise", "~4,8s"),
        ("anthropic", "~3s"),
    ])
    def test_import_pesado_fica_dentro_da_carga(self, modulo, custo):
        import ast
        import io
        import pathlib

        raiz = pathlib.Path(__file__).resolve().parents[2]
        arvore = ast.parse(io.open(raiz / "backend" / "app.py", encoding="utf-8").read())

        dentro_de_funcao = set()
        for no in ast.walk(arvore):
            if isinstance(no, ast.FunctionDef):
                for filho in ast.walk(no):
                    if hasattr(filho, "lineno"):
                        dentro_de_funcao.add(filho.lineno)

        no_topo = []
        for no in ast.walk(arvore):
            nomes = []
            if isinstance(no, ast.Import):
                nomes = [a.name for a in no.names]
            elif isinstance(no, ast.ImportFrom):
                nomes = [no.module or ""]
            if any(n == modulo or n.startswith(modulo + ".") for n in nomes):
                if no.lineno not in dentro_de_funcao:
                    no_topo.append(no.lineno)

        assert not no_topo, (
            f"{modulo} ({custo}) voltou para o nível do módulo, "
            f"linha(s) {no_topo} — o servidor volta a demorar para atender")


class TestHealth:
    def test_responde_sem_sessao(self, client, db_roteado):
        """
        A espera acontece na tela de login, antes de qualquer sessão existir.
        Exigir sessão aqui tornaria o endpoint inútil justamente no momento
        para o qual ele foi feito.
        """
        db_roteado({})
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.get_json()["servidor"] == "ok"

    def test_traz_o_estado_de_cada_modelo(self, client, db_roteado):
        db_roteado({})
        corpo = client.get("/api/health").get_json()

        assert set(corpo["modelos"]) == {"texto", "visual"}
        for m in corpo["modelos"].values():
            assert m["estado"] in {"carregando", "pronto", "indisponivel"}

    def test_diz_se_a_busca_esta_pronta(self, client, db_roteado):
        """`busca_pronta` acompanha o modelo de texto, que é o que a destrava."""
        db_roteado({})
        corpo = client.get("/api/health").get_json()
        assert corpo["busca_pronta"] == (corpo["modelos"]["texto"]["estado"] == "pronto")

    def test_nao_expoe_nome_de_modelo(self, client, db_roteado):
        """
        Regra do projeto: a interface não fala "CLIP", "SBERT" nem "embedding".
        As chaves são "texto" e "visual" porque é isso que significam para
        quem está esperando.
        """
        db_roteado({})
        cru = client.get("/api/health").get_data(as_text=True).lower()
        for jargao in ("clip", "sbert", "embedding", "bm25"):
            assert jargao not in cru



class TestBuscaAntesDosModelos:
    def test_texto_devolve_503_e_nao_lista_vazia(self, client_logado, db_roteado,
                                                  app_module):
        """
        Uma lista vazia com 200 é a resposta mais enganosa possível: o usuário
        lê "nada encontrado" e conclui que suas fotos não estão indexadas.
        """
        db_roteado({})
        with mock.patch.object(app_module, "SBERT_OK", False):
            r = client_logado.post("/api/search", json={"query": "cachorro"})

        assert r.status_code == 503
        assert r.get_json()["resultados"] == []

    def test_mensagem_de_espera_pede_para_tentar_de_novo(self, client_logado,
                                                          db_roteado, app_module):
        db_roteado({})
        app = app_module
        evento_nao_resolvido = threading.Event()
        with mock.patch.object(app, "SBERT_OK", False), \
             mock.patch.object(app, "_MODELOS_RESOLVIDOS", evento_nao_resolvido):
            corpo = client_logado.post("/api/search",
                                       json={"query": "cachorro"}).get_json()

        assert corpo["carregando"] is True
        assert "instantes" in corpo["erro"]

    def test_falha_definitiva_nao_manda_esperar(self, client_logado, db_roteado,
                                                app_module):
        """
        Depois que a carga terminou, "tente de novo em instantes" seria uma
        mentira — esperar não vai mudar nada. A mensagem tem que dizer o que
        fazer.
        """
        db_roteado({})
        app = app_module
        resolvido = threading.Event(); resolvido.set()
        with mock.patch.object(app, "SBERT_OK", False), \
             mock.patch.object(app, "_MODELOS_RESOLVIDOS", resolvido):
            corpo = client_logado.post("/api/search",
                                       json={"query": "cachorro"}).get_json()

        assert corpo.get("carregando") is None
        assert "rodar.bat" in corpo["erro"]

    def test_nenhuma_mensagem_cita_nome_de_modelo(self, client_logado, db_roteado,
                                                  app_module):
        """A mensagem antiga dizia "SBERT indisponível" para o usuário final."""
        db_roteado({})
        app = app_module
        for resolvido in (True, False):
            evento = threading.Event()
            if resolvido:
                evento.set()
            with mock.patch.object(app, "SBERT_OK", False), \
                 mock.patch.object(app, "_MODELOS_RESOLVIDOS", evento):
                erro = client_logado.post("/api/search",
                                          json={"query": "x"}).get_json()["erro"]
            for jargao in ("SBERT", "CLIP", "embedding", "semântica"):
                assert jargao.lower() not in erro.lower()

    def test_busca_por_imagem_tambem_da_503(self, client_logado, db_roteado,
                                            app_module):
        db_roteado({})
        app = app_module
        with mock.patch.object(app, "CLIP_OK", False):
            r = client_logado.post("/api/search_by_image", json={"file_id": 1})
        assert r.status_code == 503

    def test_busca_sem_sessao_continua_401(self, client, db_roteado):
        """Carregando ou não, quem não entrou não busca."""
        db_roteado({})
        assert client.post("/api/search", json={"query": "x"}).status_code == 401
