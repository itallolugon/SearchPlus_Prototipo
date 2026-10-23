# -*- coding: utf-8 -*-
"""
Paridade entre o backend real, o mock e a documentação.

O AGENTS.md estabelece: "Mantenha app.py, mock_server.py e docs/API.md em
sincronia. Um mock que diverge do backend real é pior do que não ter mock."
Essa regra só vale se alguém a verificar — é o que este arquivo faz.

O frontend é desenvolvido inteiramente contra o mock. Um endpoint que exista só
de um lado vira bug descoberto tarde, já com a interface pronta.
"""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

RAIZ = Path(__file__).resolve().parent.parent.parent
API_MD = RAIZ / "docs" / "API.md"

# Rotas que existem só no mock, por natureza — não são contrato da API real.
SO_NO_MOCK = {"/__mock__"}

# Rotas do backend real que o mock não precisa reproduzir, com o motivo.
SO_NO_BACKEND = {
    "/api/debug/scores": "ferramenta de diagnóstico do ranking real",
}


def _rotas_api(flask_app) -> set[str]:
    return {str(r.rule) for r in flask_app.url_map.iter_rules() if str(r.rule).startswith("/api/")}


@pytest.fixture()
def rotas_reais(app_module):
    return _rotas_api(app_module.app)


@pytest.fixture()
def rotas_mock(mock_module):
    return _rotas_api(mock_module.app)


class TestParidadeDeRotas:
    def test_mock_cobre_os_endpoints_do_backend(self, rotas_reais, rotas_mock):
        faltando = rotas_reais - rotas_mock - set(SO_NO_BACKEND)
        assert not faltando, (
            "endpoints existem em app.py mas não no mock_server.py — o frontend "
            f"não tem como desenvolver contra eles: {sorted(faltando)}"
        )

    def test_mock_nao_inventa_endpoint(self, rotas_reais, rotas_mock):
        sobrando = rotas_mock - rotas_reais - SO_NO_MOCK
        assert not sobrando, (
            "endpoints existem no mock mas não no backend real — o frontend "
            f"construiria em cima de algo que não existe: {sorted(sobrando)}"
        )

    def test_metodos_http_batem(self, app_module, mock_module):
        """
        Um POST que no mock também aceita GET esconde erro de integração.

        Os métodos são somados por rota: o backend real registra
        `/api/search_history` em dois decoradores (um GET, um POST) enquanto o
        mock usa um só com ambos — equivalente, e não pode acusar divergência.
        """

        def _metodos(flask_app):
            acumulado: dict[str, set[str]] = {}
            for regra in flask_app.url_map.iter_rules():
                rota = str(regra.rule)
                if not rota.startswith("/api/"):
                    continue
                verbos = {m for m in regra.methods if m not in {"HEAD", "OPTIONS"}}
                acumulado.setdefault(rota, set()).update(verbos)
            return acumulado

        reais, mock = _metodos(app_module.app), _metodos(mock_module.app)
        divergentes = {
            rota: (reais[rota], mock[rota])
            for rota in set(reais) & set(mock)
            if reais[rota] != mock[rota]
        }
        assert not divergentes, f"métodos divergentes entre backend e mock: {divergentes}"


class TestParidadeComADocumentacao:
    def test_api_md_existe(self):
        assert API_MD.is_file(), "docs/API.md é o contrato entregue ao time de frontend"

    def test_endpoints_do_backend_estao_documentados(self, rotas_reais):
        """
        Toda rota /api/ precisa aparecer em docs/API.md. Endpoint não
        documentado é endpoint que o front descobre por acidente.
        """
        texto = API_MD.read_text(encoding="utf-8")

        def _documentada(rota: str) -> bool:
            # Compara ignorando o conversor do parâmetro: `/api/folders/<int:id>`
            # aparece na documentação como `/api/folders/<id>`.
            generica = re.sub(r"<[^>]+>", "<>", rota)
            for linha in texto.splitlines():
                if re.sub(r"<[^>]+>", "<>", linha).find(generica) != -1:
                    return True
            return False

        nao_documentadas = sorted(r for r in rotas_reais if not _documentada(r))
        assert not nao_documentadas, f"rotas ausentes em docs/API.md: {nao_documentadas}"


class TestParidadeDeComportamento:
    """Amostragem de respostas que o frontend consome diretamente."""

    def test_login_invalido_responde_igual_nos_dois(self, api, client):
        """Campos vazios têm que dar 400 no mock e no backend real."""
        vazio = {"username": "", "password": ""}
        assert api.post("/api/login", json=vazio).status_code == 400
        assert client.post("/api/login", json=vazio).status_code == 400

    def test_limite_de_senha_vale_nos_dois(self, api, client):
        longa = {"username": "u", "password": "a" * 100}
        assert api.post("/api/register", json=longa).status_code == 400
        assert client.post("/api/register", json=longa).status_code == 400

    def test_sem_sessao_ambos_recusam_a_busca(self, api, client):
        corpo = {"query": "cachorro"}
        assert api.post("/api/search", json=corpo).status_code == 401
        assert client.post("/api/search", json=corpo).status_code == 401

    def test_host_desconhecido_e_recusado_nos_dois(self, api, client):
        """Anti DNS rebinding: o front tem de ver o mesmo 400 no mock e no real."""
        for cliente in (api, client):
            r = cliente.get("/api/health", base_url="http://evil.example:5000")
            assert r.status_code == 400
            assert "error" in r.get_json()

    def test_origem_null_sem_permissao_nos_dois(self, api, client):
        for cliente in (api, client):
            r = cliente.get("/api/health", headers={"Origin": "null"})
            assert "Access-Control-Allow-Origin" not in r.headers

    def test_cabecalhos_de_seguranca_nos_dois(self, api, client):
        for cliente in (api, client):
            r = cliente.get("/api/health")
            assert r.headers["X-Frame-Options"] == "SAMEORIGIN"
            assert r.headers["Referrer-Policy"] == "same-origin"

    @pytest.mark.parametrize(
        "campo,valor",
        [("perfil_analise", "turbo"), ("janela_processamento", "sempre"), ("prioridades", [])],
    )
    def test_config_de_pasta_invalida_da_400_nos_dois(
        self, api_logada, client_logado, tmp_path, campo, valor
    ):
        corpo = {"pasta": str(tmp_path), campo: valor}
        assert api_logada.post("/api/folders", json=corpo).status_code == 400
        assert client_logado.post("/api/folders", json=corpo).status_code == 400
        atualizar = {"id": 1, campo: valor}
        assert api_logada.post("/api/folders/update_config", json=atualizar).status_code == 400
        assert client_logado.post("/api/folders/update_config", json=atualizar).status_code == 400

    def test_limpar_historico_devolve_a_lista_vazia_nos_dois(
        self, api_logada, client_logado, db_roteado, mock_module, monkeypatch
    ):
        # O histórico do mock é estado global: outros testes contam com ele.
        monkeypatch.setattr(mock_module, "_HISTORICO", list(mock_module._HISTORICO))
        db_roteado({})
        for cliente in (api_logada, client_logado):
            corpo = cliente.post("/api/clear_history").get_json()
            assert corpo == {"status": "ok", "historico": []}

    def test_arquivo_do_mock_tambem_vai_em_sandbox(self, api_logada):
        r = api_logada.get("/api/file/C:%5CUsers%5CDemo%5CImagens%5Cgato-janela.png")
        assert r.status_code == 200
        assert r.headers["Content-Security-Policy"] == "sandbox"
        assert r.headers["X-Content-Type-Options"] == "nosniff"
