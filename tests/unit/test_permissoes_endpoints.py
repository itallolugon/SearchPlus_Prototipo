# -*- coding: utf-8 -*-
"""
Isolamento por sessão.

Todo endpoint de dados lê o usuário de `_uid()` e filtra por `user_id`.
Esquecer esse filtro num endpoint novo vazaria o acervo de outra conta, então a
regra "sem sessão => 401" é testada endpoint a endpoint.
"""

import pytest

pytestmark = pytest.mark.unit

GETS_PROTEGIDOS = [
    "/api/folders",
    "/api/stats",
    "/api/gallery",
    "/api/collections",
    "/api/debug/files",
    "/api/open_location",
]

# Estes NÃO devolvem 401 por decisão de projeto: o frontend os consulta antes do
# login (cores do tema, estado do motor) e um 401 poluiria o console. A garantia
# que importa não é o status, e sim que a resposta venha vazia — nunca com dado
# de outra conta. É isso que TestEndpointsPublicosDegradados verifica.
GETS_PUBLICOS_DEGRADADOS = [
    "/api/config",
    "/api/favorites",
    "/api/status",
    "/api/estimate_time",
    "/api/search_history",
]

POSTS_PROTEGIDOS = [
    ("/api/search", {"query": "cachorro"}),
    ("/api/search_by_image", {"file_id": 1}),
    ("/api/folders", {"pasta": "C:\\qualquer"}),
    ("/api/analyze_folders", {}),
    ("/api/reanalyze", {}),
    ("/api/reembed", {}),
    ("/api/favorites/toggle", {"id": 1}),
    ("/api/collections", {"nome": "x"}),
    ("/api/clear_cache", {}),
    ("/api/cancel_analysis", {}),
    ("/api/config", {"tema": "escuro"}),
]


class TestSemSessao:
    @pytest.mark.parametrize("rota", GETS_PROTEGIDOS)
    def test_get_exige_login(self, client, rota):
        assert client.get(rota).status_code == 401, f"{rota} respondeu sem sessão"

    @pytest.mark.parametrize("rota,payload", POSTS_PROTEGIDOS)
    def test_post_exige_login(self, client, rota, payload):
        assert client.post(rota, json=payload).status_code == 401, f"{rota} respondeu sem sessão"

    def test_serve_file_exige_login(self, client):
        assert client.get("/api/file/C:%5Cqualquer%5Cx.jpg").status_code == 401

    def test_check_session_responde_401_sem_login(self, client):
        assert client.get("/api/check_session").status_code == 401


class TestEndpointsPublicosDegradados:
    """
    Endpoints que respondem sem sessão. O contrato aqui é: resposta VAZIA.
    Se algum dia um deles passar a devolver dado real sem login, estes testes
    quebram — que é exatamente o alarme desejado.
    """

    @pytest.mark.parametrize("rota", GETS_PUBLICOS_DEGRADADOS)
    def test_responde_sem_estourar(self, client, rota):
        assert client.get(rota).status_code == 200

    def test_historico_vem_vazio(self, client):
        assert client.get("/api/search_history").get_json() == {"historico": []}

    def test_favoritos_vem_vazio(self, client):
        assert client.get("/api/favorites").get_json() == {"resultados": []}

    def test_estimativa_vem_zerada(self, client):
        corpo = client.get("/api/estimate_time").get_json()
        assert corpo["total_imagens"] == 0
        assert corpo["estimativa_minutos"] == 0

    def test_config_traz_so_os_padroes(self, client):
        """
        Sem sessão, `/api/config` devolve o tema padrão para o front pintar a
        tela de login. Não pode trazer pasta nem histórico de ninguém.
        """
        corpo = client.get("/api/config").get_json()
        assert corpo["pastas"] == []
        assert corpo["historico_pastas"] is False
        assert "search_history" not in corpo


class TestComSessao:
    def test_check_session_reconhece_a_sessao(self, client_logado, db_falso):
        _, conexao = db_falso
        conexao.execute.return_value.fetchone.return_value = {"username": "fulano"}
        assert client_logado.get("/api/check_session").status_code == 200

    def test_logout_encerra_a_sessao(self, client_logado):
        client_logado.post("/api/logout")
        assert client_logado.get("/api/stats").status_code == 401


class TestFalhaDeDependencia:
    """
    Banco fora do ar tem que virar erro, nunca um 200 com dado incompleto.

    `PROPAGATE_EXCEPTIONS=False` faz o Flask responder como em produção (500) em
    vez de reerguer a exceção no cliente de teste.
    """

    @pytest.fixture()
    def client_producao(self, flask_app):
        flask_app.config.update(PROPAGATE_EXCEPTIONS=False)
        cliente = flask_app.test_client()
        with cliente.session_transaction() as sessao:
            sessao["user_id"] = 4242
        yield cliente
        flask_app.config.update(PROPAGATE_EXCEPTIONS=None)

    def test_pool_esgotado_vira_erro_e_nao_200(self, client_producao, app_module, monkeypatch):
        def _explode():
            raise RuntimeError("connection pool exhausted")

        monkeypatch.setattr(app_module, "get_db", _explode)
        assert client_producao.get("/api/stats").status_code >= 500


class TestDegradacaoDaIA:
    """
    Modelos de IA indisponíveis é estado esperado, não exceção: o app sobe com
    SBERT_OK/CLIP_OK em False quando um modelo falha ao carregar. Toda esta
    suíte roda nesse modo, então é o cenário real.

    O contrato: a busca não pode fingir que o acervo está vazio. Ela responde
    dizendo que a capacidade está desligada — senão o usuário conclui que
    perdeu os arquivos.
    """

    def test_suite_roda_com_modelos_desligados(self, app_module):
        assert app_module.SBERT_OK is False
        assert app_module.CLIP_OK is False

    def test_busca_sem_sbert_sinaliza_o_motivo(self, client_logado):
        corpo = client_logado.post("/api/search", json={"query": "cachorro"}).get_json()
        assert corpo.get("erro"), "sem SBERT a resposta precisa explicar o porquê"
        assert corpo["resultados"] == []

    def test_busca_por_imagem_sem_clip_sinaliza_o_motivo(self, client_logado):
        corpo = client_logado.post("/api/search_by_image", json={"file_id": 1}).get_json()
        assert corpo.get("erro")

    def test_status_continua_respondendo_sem_ia(self, client_logado, db_falso):
        """O painel de status não pode depender de modelo carregado."""
        _, conexao = db_falso
        conexao.execute.return_value.fetchone.return_value = {"n": 0}
        resposta = client_logado.get("/api/status")
        assert resposta.status_code == 200
        assert "status" in resposta.get_json()
