# -*- coding: utf-8 -*-
"""
Endpoints que leem o acervo: painel, galeria, favoritos, coleções e histórico.

O banco é substituído por um duplo que responde por SQL, então o que se
exercita aqui é a camada de cima: agregação, formato de resposta e o filtro por
`user_id`. É essa camada que o frontend consome — um campo renomeado quebra a
tela sem quebrar nenhuma query.
"""

import pytest

pytestmark = pytest.mark.unit

# Uma linha de `files` como o RealDictCursor entrega.
_ARQUIVO = {
    "id": 1,
    "folder_id": 10,
    "nome": "cachorro.jpg",
    "caminho": r"C:\Fotos\cachorro.jpg",
    "tipo": "jpg",
    "descricao_ia": "- Estilo: foto\n- Animais: cachorro\n- Pessoas: nenhuma",
    "data_adicionado": None,
    "favorito": 0,
    "processado": 1,
}


class TestPainelDeEstatisticas:
    def test_conta_por_formato(self, client_logado, db_roteado):
        db_roteado(
            {
                "FROM files": {
                    "fetchall": [
                        {"tipo": "jpg", "descricao_ia": "- Animais: cachorro"},
                        {"tipo": "png", "descricao_ia": "- Pessoas: mulher"},
                        {"tipo": "pdf", "descricao_ia": "contrato"},
                        {"tipo": "mp4", "descricao_ia": "video"},
                    ]
                },
                "COUNT(*) AS n": {"fetchone": {"n": 2}},
            }
        )
        corpo = client_logado.get("/api/stats").get_json()
        assert corpo["por_formato"]["imagem"] == 2
        assert corpo["por_formato"]["documento"] == 1
        assert corpo["por_formato"]["midia"] == 1
        assert corpo["total_arquivos"] == 4
        assert corpo["total_pastas"] == 2

    def test_acervo_vazio_nao_estoura(self, client_logado, db_roteado):
        db_roteado({"FROM files": {"fetchall": []}, "COUNT(*) AS n": {"fetchone": {"n": 0}}})
        corpo = client_logado.get("/api/stats").get_json()
        assert corpo["total_arquivos"] == 0
        assert corpo["por_categoria"] == []

    def test_negacao_nao_vira_categoria(self, client_logado, db_roteado):
        """ "Animais: nenhum" não pode classificar o arquivo em `animais`."""
        db_roteado(
            {
                "FROM files": {
                    "fetchall": [
                        {"tipo": "jpg", "descricao_ia": "- Pessoas: nenhuma\n- Animais: nenhum"}
                    ]
                },
                "COUNT(*) AS n": {"fetchone": {"n": 1}},
            }
        )
        categorias = {
            c["categoria"] for c in client_logado.get("/api/stats").get_json()["por_categoria"]
        }
        assert "animais" not in categorias
        assert "pessoas" not in categorias


class TestGaleria:
    def test_agrupa_imagens(self, client_logado, db_roteado):
        db_roteado({"FROM files": {"fetchall": [_ARQUIVO]}})
        corpo = client_logado.get("/api/gallery").get_json()
        assert "grupos" in corpo
        assert corpo["total_imagens"] >= 0

    def test_sem_imagem_devolve_estrutura_vazia(self, client_logado, db_roteado):
        db_roteado({"FROM files": {"fetchall": []}})
        corpo = client_logado.get("/api/gallery").get_json()
        assert corpo["grupos"] == []
        assert corpo["total_imagens"] == 0


class TestFavoritos:
    def test_listagem_traz_os_campos_do_card(self, client_logado, db_roteado):
        db_roteado({"FROM files": {"fetchall": [dict(_ARQUIVO, favorito=1)]}})
        resultados = client_logado.get("/api/favorites").get_json()["resultados"]
        assert resultados
        assert {"id", "nome", "caminho", "tipo"} <= set(resultados[0])

    def test_toggle_de_arquivo_inexistente_da_404(self, client_logado, db_roteado):
        db_roteado({"UPDATE files": {"fetchone": None}})
        assert client_logado.post("/api/favorites/toggle", json={"id": 999}).status_code == 404

    def test_toggle_devolve_o_novo_estado(self, client_logado, db_roteado):
        db_roteado({"UPDATE files": {"fetchone": {"favorito": 1}}})
        corpo = client_logado.post("/api/favorites/toggle", json={"id": 1}).get_json()
        assert corpo["favorito"] is True

    def test_toggle_e_atomico(self, client_logado, db_roteado):
        """
        A inversão acontece dentro do UPDATE. Ler e depois escrever perdia
        cliques rápidos e estourava quando a coluna era NULL.
        """
        conexao = db_roteado({"UPDATE files": {"fetchone": {"favorito": 0}}})
        client_logado.post("/api/favorites/toggle", json={"id": 1})
        sqls = " ".join(str(c) for c in conexao.execute.call_args_list)
        assert "UPDATE files" in sqls and "RETURNING" in sqls
        assert "SELECT favorito" not in sqls


class TestColecoes:
    def test_listagem(self, client_logado, db_roteado):
        db_roteado(
            {
                "FROM collections": {
                    "fetchall": [{"id": 1, "nome": "Viagem", "total": 3, "criado_em": None,
                                  "pasta_vinculada": None, "modo_sync": "manual",
                                  "capa_file_id": None, "capa_caminho": None}]
                }
            }
        )
        corpo = client_logado.get("/api/collections").get_json()
        assert isinstance(corpo["colecoes"], list)
        assert corpo["colecoes"][0]["nome"] == "Viagem"

    def test_listagem_monta_capas_em_mosaico(self, client_logado, db_roteado):
        """
        Cada coleção leva até 4 imagens para a capa; o front espera a lista.

        As capas de todas as coleções vêm numa consulta só, então cada linha
        diz a que coleção pertence — é o `colecao_id` que distribui o mosaico.
        """
        db_roteado(
            {
                "FROM collections": {
                    "fetchall": [
                        {"id": 1, "nome": "Viagem", "total": 2, "criado_em": None,
                         "pasta_vinculada": None, "modo_sync": "manual",
                                  "capa_file_id": None, "capa_caminho": None},
                        {"id": 2, "nome": "Praia", "total": 1, "criado_em": None,
                         "pasta_vinculada": None, "modo_sync": "manual",
                                  "capa_file_id": None, "capa_caminho": None},
                    ]
                },
                "ROW_NUMBER": {
                    "fetchall": [
                        {"colecao_id": 1, "caminho": r"C:\Fotos\a.jpg"},
                        {"colecao_id": 1, "caminho": r"C:\Fotos\b.jpg"},
                        {"colecao_id": 2, "caminho": r"C:\Fotos\c.jpg"},
                    ]
                },
            }
        )
        colecoes = client_logado.get("/api/collections").get_json()["colecoes"]
        por_id = {c["id"]: c for c in colecoes}

        assert por_id[1]["capas"] == [r"C:\Fotos\a.jpg", r"C:\Fotos\b.jpg"]
        assert por_id[2]["capas"] == [r"C:\Fotos\c.jpg"]

    def test_colecao_sem_imagem_fica_sem_capa(self, client_logado, db_roteado):
        """Coleção só com PDF não aparece no resultado das capas — e não quebra."""
        db_roteado(
            {
                "FROM collections": {
                    "fetchall": [{"id": 7, "nome": "Documentos", "total": 3,
                                  "criado_em": None, "pasta_vinculada": None,
                                  "modo_sync": "manual",
                                  "capa_file_id": None, "capa_caminho": None}]
                },
            }
        )
        colecao = client_logado.get("/api/collections").get_json()["colecoes"][0]
        assert colecao["capas"] == []

    def test_criar_sem_nome_e_recusado(self, client_logado, db_roteado):
        db_roteado({})
        assert client_logado.post("/api/collections", json={"nome": "  "}).status_code == 400

    def test_colecao_de_outro_usuario_da_404(self, client_logado, db_roteado):
        """A posse é conferida antes de qualquer leitura — sem isso, é IDOR."""
        db_roteado({"FROM collections WHERE id": {"fetchone": None}})
        assert client_logado.get("/api/collections/999").status_code == 404

    def test_associar_exige_arquivo_do_proprio_usuario(self, client_logado, db_roteado):
        db_roteado(
            {
                "FROM collections WHERE id": {"fetchone": {"id": 1}},
                "FROM files WHERE id": {"fetchone": None},  # arquivo não é dele
            }
        )
        resposta = client_logado.post("/api/collections/1/files", json={"file_id": 999})
        assert resposta.status_code == 404

    def test_associar_sem_file_id_e_recusado(self, client_logado, db_roteado):
        db_roteado({})
        assert client_logado.post("/api/collections/1/files", json={}).status_code == 400


class TestHistoricoDeBusca:
    def test_registrar_query(self, client_logado, db_roteado):
        db_roteado({"SELECT config_json": {"fetchone": {"config_json": "{}"}}})
        resposta = client_logado.post("/api/search_history", json={"query": "cachorro"})
        assert resposta.status_code == 200
        assert "cachorro" in resposta.get_json()["historico"]

    def test_query_vazia_e_recusada(self, client_logado, db_roteado):
        db_roteado({})
        assert client_logado.post("/api/search_history", json={"query": "  "}).status_code == 400

    def test_historico_guarda_no_maximo_dez(self, client_logado, db_roteado):
        anteriores = [f"busca {i}" for i in range(10)]
        db_roteado(
            {
                "SELECT config_json": {
                    "fetchone": {
                        "config_json": f'{{"search_history": {anteriores!r}}}'.replace("'", '"')
                    }
                }
            }
        )
        corpo = client_logado.post("/api/search_history", json={"query": "nova"}).get_json()
        assert len(corpo["historico"]) <= 10
        assert corpo["historico"][0] == "nova", "a mais recente vai para o topo"

    def test_query_repetida_nao_duplica(self, client_logado, db_roteado):
        db_roteado(
            {
                "SELECT config_json": {
                    "fetchone": {"config_json": '{"search_history": ["gato", "cachorro"]}'}
                }
            }
        )
        historico = client_logado.post("/api/search_history", json={"query": "gato"}).get_json()[
            "historico"
        ]
        assert historico.count("gato") == 1
        assert historico[0] == "gato"


class TestDiagnostico:
    def test_debug_files_reporta_capacidades(self, client_logado, db_roteado):
        db_roteado({"FROM files": {"fetchall": [_ARQUIVO]}})
        corpo = client_logado.get("/api/debug/files").get_json()
        assert "sbert_disponivel" in corpo
        assert "claude_disponivel" in corpo

    def test_debug_scores_exige_query(self, client_logado, db_roteado):
        db_roteado({})
        assert client_logado.get("/api/debug/scores").status_code == 400
