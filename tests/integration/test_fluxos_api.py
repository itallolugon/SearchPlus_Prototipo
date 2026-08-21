# -*- coding: utf-8 -*-
"""Fluxos ponta a ponta da API, do login à coleção."""

import pytest

pytestmark = pytest.mark.integration


class TestFluxoDeAutenticacao:
    def test_sem_login_a_sessao_nao_existe(self, api):
        assert api.get("/api/check_session").status_code == 401

    def test_login_cria_sessao(self, api):
        api.post("/api/login", json={"username": "tester", "password": "x"})
        resposta = api.get("/api/check_session")
        assert resposta.status_code == 200
        assert resposta.get_json()["username"] == "tester"

    def test_login_sem_campos_e_recusado(self, api):
        assert api.post("/api/login", json={"username": "", "password": ""}).status_code == 400

    def test_logout_encerra_a_sessao(self, api_logada):
        api_logada.post("/api/logout")
        assert api_logada.get("/api/check_session").status_code == 401

    def test_sessao_sobrevive_entre_requisicoes(self, api_logada):
        """O cookie precisa persistir — sem isso o front cai no login a cada clique."""
        for _ in range(3):
            assert api_logada.get("/api/check_session").status_code == 200


class TestFluxoDeBusca:
    def test_busca_retorna_estrutura_esperada(self, api_logada):
        corpo = api_logada.post("/api/search", json={"query": "cachorro"}).get_json()
        assert "resultados" in corpo
        assert isinstance(corpo["resultados"], list)

    def test_resultado_traz_os_campos_que_o_front_usa(self, api_logada):
        resultados = api_logada.post("/api/search", json={"query": "foto"}).get_json()["resultados"]
        assert resultados, "a busca do mock casa por substring; 'foto' tem que achar"
        obrigatorios = {"id", "nome", "caminho", "tipo", "score"}
        assert obrigatorios <= set(resultados[0]), "campo removido quebra renderizarResultados()"

    def test_resultados_vem_ordenados_por_score(self, api_logada):
        resultados = api_logada.post("/api/search", json={"query": "foto"}).get_json()["resultados"]
        scores = [r["score"] for r in resultados]
        assert scores == sorted(scores, reverse=True)

    def test_busca_vazia_nao_estoura(self, api_logada):
        assert api_logada.post("/api/search", json={"query": ""}).status_code in (200, 400)

    def test_busca_sem_sessao_e_recusada(self, api):
        assert api.post("/api/search", json={"query": "x"}).status_code == 401

    @pytest.mark.parametrize("filtro", ["all", "imagem", "documento", "midia"])
    def test_filtros_de_tipo_sao_aceitos(self, api_logada, filtro):
        resposta = api_logada.post("/api/search", json={"query": "foto", "filtro": filtro})
        assert resposta.status_code == 200


class TestFluxoDeColecoes:
    """Criar, listar, associar arquivo, remover e apagar."""

    def test_ciclo_completo(self, api_logada):
        criada = api_logada.post("/api/collections", json={"nome": "Viagem 2026"})
        assert criada.status_code in (200, 201)

        colecoes = api_logada.get("/api/collections").get_json()["colecoes"]
        alvo = next((c for c in colecoes if c["nome"] == "Viagem 2026"), None)
        assert alvo is not None, "a coleção criada tem que aparecer na listagem"

        col_id = alvo["id"]
        arquivo_id = api_logada.post("/api/search", json={"query": "foto"}).get_json()[
            "resultados"
        ][0]["id"]

        assert (
            api_logada.post(
                f"/api/collections/{col_id}/files", json={"file_id": arquivo_id}
            ).status_code
            == 200
        )

        dentro = api_logada.get(f"/api/collections/{col_id}").get_json()["resultados"]
        assert any(r["id"] == arquivo_id for r in dentro)

        assert (
            api_logada.delete(
                f"/api/collections/{col_id}/files", json={"file_id": arquivo_id}
            ).status_code
            == 200
        )
        assert api_logada.delete(f"/api/collections/{col_id}").status_code == 200

    def test_colecao_sem_nome_e_recusada(self, api_logada):
        assert api_logada.post("/api/collections", json={"nome": ""}).status_code == 400

    def test_colecao_inexistente_devolve_404(self, api_logada):
        assert api_logada.get("/api/collections/999999").status_code == 404

    def test_sem_sessao_nao_lista_colecoes(self, api):
        assert api.get("/api/collections").status_code == 401


class TestFluxoDeFavoritos:
    def test_marcar_e_desmarcar(self, api_logada):
        arquivo_id = api_logada.post("/api/search", json={"query": "foto"}).get_json()[
            "resultados"
        ][0]["id"]

        primeiro = api_logada.post("/api/favorites/toggle", json={"id": arquivo_id}).get_json()
        segundo = api_logada.post("/api/favorites/toggle", json={"id": arquivo_id}).get_json()
        assert primeiro["favorito"] != segundo["favorito"], "toggle tem que alternar"

    def test_favorito_aparece_na_listagem(self, api_logada):
        arquivo_id = api_logada.post("/api/search", json={"query": "foto"}).get_json()[
            "resultados"
        ][0]["id"]
        estado = api_logada.post("/api/favorites/toggle", json={"id": arquivo_id}).get_json()
        if not estado["favorito"]:
            estado = api_logada.post("/api/favorites/toggle", json={"id": arquivo_id}).get_json()

        favoritos = api_logada.get("/api/favorites").get_json()["resultados"]
        assert any(r["id"] == arquivo_id for r in favoritos)


class TestFluxoDePastas:
    def test_listagem_tem_formato_esperado(self, api_logada):
        corpo = api_logada.get("/api/folders").get_json()
        assert isinstance(corpo["pastas"], list)

    def test_pasta_traz_campos_de_configuracao(self, api_logada):
        pastas = api_logada.get("/api/folders").get_json()["pastas"]
        if pastas:
            assert {"id", "path", "prioridades", "perfil_analise"} <= set(pastas[0])


class TestFluxoDeHistorico:
    def test_registrar_e_recuperar(self, api_logada):
        api_logada.post("/api/search_history", json={"query": "gato de óculos"})
        assert "gato de óculos" in api_logada.get("/api/search_history").get_json()["historico"]

    def test_limpar_esvazia(self, api_logada):
        api_logada.post("/api/search_history", json={"query": "x"})
        api_logada.post("/api/clear_history")
        assert api_logada.get("/api/search_history").get_json()["historico"] == []


class TestPainelInicial:
    def test_stats_traz_os_totais(self, api_logada):
        corpo = api_logada.get("/api/stats").get_json()
        assert {"total_arquivos", "total_pastas", "por_formato"} <= set(corpo)

    def test_galeria_traz_grupos(self, api_logada):
        corpo = api_logada.get("/api/gallery").get_json()
        assert "grupos" in corpo

    def test_status_do_motor(self, api_logada):
        corpo = api_logada.get("/api/status").get_json()
        assert {"status", "arquivos_pendentes"} <= set(corpo)
