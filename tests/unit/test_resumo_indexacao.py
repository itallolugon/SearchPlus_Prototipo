# -*- coding: utf-8 -*-
"""
O que aconteceu na última indexação.

Ao terminar, o app dizia "Indexação concluída!" e pronto. Quem apontou uma
pasta com 4.000 arquivos e viu 3.200 indexados não tinha como saber o que
houve com os outros 800 — nem se houve. A pergunta "cadê minhas fotos?"
aparecia semanas depois, sem nada para responder.

A decisão que organiza o arquivo inteiro: **ignorado e erro são coisas
diferentes**. Juntos viram "800 problemas" e mandam a pessoa procurar defeito
onde não há — um `.zip` no meio das fotos não é falha do programa. Separados,
um deles não pede reação nenhuma e o outro pede.
"""

from unittest import mock

import pytest

pytestmark = pytest.mark.unit

UID = 4242


@pytest.fixture()
def resumo_limpo(app_module):
    """O acumulado é global; sem limpar, um teste enxerga o do outro."""
    app_module._resumo_aberto.clear()
    yield app_module
    app_module._resumo_aberto.clear()


class TestAcumulador:
    def test_sem_resumo_aberto_nada_e_registrado(self, resumo_limpo):
        """
        Indexação disparada por outro caminho (o scan automático de uma pasta
        recém-adicionada) não abre resumo. Registrar assim mesmo criaria um
        resumo órfão, sem começo, que apareceria na tela como se fosse a última
        rodada completa.
        """
        resumo_limpo._resumo_registrar_arquivo(UID, 1, "C:/Fotos", "a.jpg")
        assert resumo_limpo._resumo_fechar(UID) is None

    def test_conta_indexados(self, resumo_limpo):
        resumo_limpo._resumo_iniciar(UID)
        for nome in ("a.jpg", "b.jpg", "c.jpg"):
            resumo_limpo._resumo_registrar_arquivo(UID, 1, "C:/Fotos", nome)

        resumo = resumo_limpo._resumo_fechar(UID)
        assert resumo["totais"]["indexados"] == 3
        assert resumo["totais"]["erros"] == 0

    def test_conta_erros_com_o_motivo(self, resumo_limpo):
        resumo_limpo._resumo_iniciar(UID)
        resumo_limpo._resumo_registrar_arquivo(UID, 1, "C:/Fotos", "ok.jpg")
        resumo_limpo._resumo_registrar_arquivo(
            UID, 1, "C:/Fotos", "quebrada.jpg", motivo="não foi possível ler o conteúdo"
        )

        resumo = resumo_limpo._resumo_fechar(UID)
        pasta = resumo["pastas"][0]

        assert pasta["indexados"] == 1
        assert pasta["erros"] == 1
        assert pasta["arquivos_com_erro"] == [
            {"nome": "quebrada.jpg", "motivo": "não foi possível ler o conteúdo"}
        ]

    def test_ignorado_nao_e_erro(self, resumo_limpo):
        """A distinção que dá sentido ao resumo."""
        resumo_limpo._resumo_iniciar(UID)
        resumo_limpo._resumo_contar_ignorados(UID, 1, "C:/Fotos", 24)

        resumo = resumo_limpo._resumo_fechar(UID)
        assert resumo["totais"]["ignorados"] == 24
        assert resumo["totais"]["erros"] == 0

    def test_separa_por_pasta(self, resumo_limpo):
        resumo_limpo._resumo_iniciar(UID)
        resumo_limpo._resumo_registrar_arquivo(UID, 1, "C:/Fotos", "a.jpg")
        resumo_limpo._resumo_registrar_arquivo(UID, 2, "D:/Docs", "b.pdf")
        resumo_limpo._resumo_registrar_arquivo(UID, 2, "D:/Docs", "c.pdf")

        resumo = resumo_limpo._resumo_fechar(UID)
        por_caminho = {p["caminho"]: p for p in resumo["pastas"]}

        assert por_caminho["C:/Fotos"]["indexados"] == 1
        assert por_caminho["D:/Docs"]["indexados"] == 2

    def test_limita_a_lista_de_nomes_sem_perder_a_contagem(self, resumo_limpo):
        """
        A lista existe para investigar, não para inventariar: com 4.000 nomes
        ninguém lê nenhum e o JSON incha à toa. A contagem continua exata —
        é ela que diz o tamanho do problema.
        """
        resumo_limpo._resumo_iniciar(UID)
        for i in range(resumo_limpo.LIMITE_ERROS_LISTADOS + 30):
            resumo_limpo._resumo_registrar_arquivo(UID, 1, "C:/Fotos", f"f{i}.jpg", motivo="falhou")

        pasta = resumo_limpo._resumo_fechar(UID)["pastas"][0]

        assert pasta["erros"] == resumo_limpo.LIMITE_ERROS_LISTADOS + 30
        assert len(pasta["arquivos_com_erro"]) == resumo_limpo.LIMITE_ERROS_LISTADOS

    def test_fechar_duas_vezes_nao_duplica(self, resumo_limpo):
        resumo_limpo._resumo_iniciar(UID)
        resumo_limpo._resumo_registrar_arquivo(UID, 1, "C:/Fotos", "a.jpg")

        assert resumo_limpo._resumo_fechar(UID) is not None
        assert resumo_limpo._resumo_fechar(UID) is None

    def test_recomecar_zera_o_anterior(self, resumo_limpo):
        """
        Duas indexações seguidas não podem somar. "640 indexados" na segunda
        rodada, quando ela mexeu em 12 arquivos, seria um número inventado.
        """
        resumo_limpo._resumo_iniciar(UID)
        resumo_limpo._resumo_registrar_arquivo(UID, 1, "C:/Fotos", "a.jpg")

        resumo_limpo._resumo_iniciar(UID)
        resumo_limpo._resumo_registrar_arquivo(UID, 1, "C:/Fotos", "b.jpg")

        assert resumo_limpo._resumo_fechar(UID)["totais"]["indexados"] == 1

    def test_usuarios_nao_se_misturam(self, resumo_limpo):
        resumo_limpo._resumo_iniciar(1)
        resumo_limpo._resumo_iniciar(2)
        resumo_limpo._resumo_registrar_arquivo(1, 1, "C:/A", "a.jpg")
        resumo_limpo._resumo_registrar_arquivo(2, 9, "D:/B", "b.jpg")
        resumo_limpo._resumo_registrar_arquivo(2, 9, "D:/B", "c.jpg")

        assert resumo_limpo._resumo_fechar(1)["totais"]["indexados"] == 1
        assert resumo_limpo._resumo_fechar(2)["totais"]["indexados"] == 2


class TestGravacao:
    def test_grava_quando_ha_o_que_contar(self, resumo_limpo, db_roteado):
        conexao = db_roteado({})
        resumo_limpo._resumo_iniciar(UID)
        resumo_limpo._resumo_registrar_arquivo(UID, 1, "C:/Fotos", "a.jpg")

        resumo_limpo._gravar_resumo(UID)

        sqls = [str(c.args[0]) for c in conexao.execute.call_args_list]
        assert any("INSERT INTO resumos_indexacao" in q for q in sqls)

    def test_indexacao_vazia_nao_vira_linha(self, resumo_limpo, db_roteado):
        """Uma linha sem pasta nenhuma só atrapalharia a lista."""
        conexao = db_roteado({})
        resumo_limpo._resumo_iniciar(UID)

        resumo_limpo._gravar_resumo(UID)

        assert not conexao.execute.called

    def test_falha_ao_gravar_nao_derruba_o_worker(self, resumo_limpo, db_roteado):
        """
        Isto roda dentro do thread de indexação. Uma exceção aqui mataria o
        worker e a indexação pararia para sempre — com o status exibindo
        "Ocioso", sem sinal de que algo quebrou.
        """
        conexao = db_roteado({})
        conexao.execute.side_effect = RuntimeError("banco fora do ar")
        resumo_limpo._resumo_iniciar(UID)
        resumo_limpo._resumo_registrar_arquivo(UID, 1, "C:/Fotos", "a.jpg")

        resumo_limpo._gravar_resumo(UID)  # não pode levantar

        conexao.rollback.assert_called()


class TestVarreduraContaIgnorados:
    def test_percorrer_reporta_o_que_pulou(self, app_module, tmp_path):
        (tmp_path / "foto.jpg").write_text("x", encoding="utf-8")
        (tmp_path / "programa.exe").write_text("x", encoding="utf-8")
        (tmp_path / "arquivo.zip").write_text("x", encoding="utf-8")

        ignorados = []
        achados = list(app_module._percorrer_arquivos(str(tmp_path), [], ignorados))

        assert [a[1] for a in achados] == ["foto.jpg"]
        assert sorted(ignorados) == ["arquivo.zip", "programa.exe"]

    def test_sem_lista_o_comportamento_e_o_de_antes(self, app_module, tmp_path):
        """A verificação de pastas chama sem a lista e não pode mudar."""
        (tmp_path / "foto.jpg").write_text("x", encoding="utf-8")
        (tmp_path / "programa.exe").write_text("x", encoding="utf-8")

        achados = list(app_module._percorrer_arquivos(str(tmp_path), []))
        assert [a[1] for a in achados] == ["foto.jpg"]


class TestEndpoint:
    def test_devolve_o_resumo_mais_recente(self, client_logado, db_roteado):
        db_roteado(
            {
                "FROM resumos_indexacao": {
                    "fetchone": {
                        "conteudo": {
                            "totais": {"indexados": 640, "ignorados": 29, "erros": 3},
                            "pastas": [],
                        },
                        "fim": None,
                    }
                }
            }
        )
        corpo = client_logado.get("/api/resumo_indexacao").get_json()

        assert corpo["resumo"]["totais"]["indexados"] == 640

    def test_sem_indexacao_devolve_nulo(self, client_logado, db_roteado):
        """
        `null` e não `{}`: a tela tem uma mensagem própria para "nunca rodou",
        diferente de "rodou e não achou nada".
        """
        db_roteado({"FROM resumos_indexacao": {"fetchone": None}})
        assert client_logado.get("/api/resumo_indexacao").get_json()["resumo"] is None

    def test_aceita_conteudo_como_texto(self, client_logado, db_roteado):
        """JSONB pode chegar como dict ou como texto, dependendo da conexão."""
        import json

        db_roteado(
            {
                "FROM resumos_indexacao": {
                    "fetchone": {"conteudo": json.dumps({"totais": {"indexados": 7}}), "fim": None}
                }
            }
        )

        corpo = client_logado.get("/api/resumo_indexacao").get_json()
        assert corpo["resumo"]["totais"]["indexados"] == 7

    def test_so_pega_o_do_proprio_usuario(self, client_logado, db_roteado):
        conexao = db_roteado({"FROM resumos_indexacao": {"fetchone": None}})
        client_logado.get("/api/resumo_indexacao")

        chamada = conexao.execute.call_args_list[0]
        assert "user_id = %s" in str(chamada.args[0])
        assert chamada.args[1][0] == UID

    def test_exige_sessao(self, client, db_roteado):
        db_roteado({})
        assert client.get("/api/resumo_indexacao").status_code == 401


class TestAnalisePreparaOResumo:
    def test_disparar_analise_abre_um_resumo(self, client_logado, db_roteado, resumo_limpo):
        db_roteado({"SELECT path FROM folders": {"fetchall": []}})
        with mock.patch.object(resumo_limpo, "threading"):
            client_logado.post("/api/analyze_folders")

        assert UID in resumo_limpo._resumo_aberto
