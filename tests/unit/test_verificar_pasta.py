# -*- coding: utf-8 -*-
"""
Verificar alterações: reconciliar uma pasta indexada com o disco.

A indexação é um retrato do momento da varredura. Depois disso o usuário
continua mexendo nos arquivos, e o Search+ só sabia somar: arquivo novo
entrava, mas arquivo editado nunca era relido — a varredura pula tudo que já
está `processado = 1` — e arquivo apagado ficava aparecendo na busca para
sempre, levando a um clique que não abre nada.

A regra que atravessa o arquivo inteiro: **nada é apagado**. O arquivo que
sumiu é marcado. O motivo mais comum de um arquivo sumir é um disco externo
desconectado, e apagar o registro jogaria fora a descrição da IA, os
embeddings e a participação dele em coleções por causa de um cabo solto.
"""

import os
from unittest import mock

import pytest

pytestmark = pytest.mark.unit

# O mesmo usuário que o conftest põe na sessão de `client_logado`.
UID_DA_SESSAO = 4242


# ──────────────────────────────────────────────────────────────────────────
# Assinatura do arquivo no disco
# ──────────────────────────────────────────────────────────────────────────


class TestAssinaturaNoDisco:
    def test_le_data_e_tamanho(self, app_module, tmp_path):
        arq = tmp_path / "foto.jpg"
        arq.write_text("conteudo", encoding="utf-8")

        mtime, tamanho = app_module._assinatura_no_disco(str(arq))

        assert tamanho == len("conteudo")
        assert mtime == pytest.approx(arq.stat().st_mtime)

    def test_arquivo_sumido_devolve_nao_sei(self, app_module, tmp_path):
        """
        (None, None), não (0, 0).

        Zero seria uma mentira com consequência: a verificação seguinte leria
        "o arquivo encolheu para zero byte", chamaria isso de alteração e
        mandaria o arquivo de volta para a fila da IA sem motivo.
        """
        assert app_module._assinatura_no_disco(str(tmp_path / "nao_existe.jpg")) == (None, None)

    def test_erro_de_permissao_nao_derruba(self, app_module, tmp_path):
        arq = tmp_path / "travado.jpg"
        arq.write_text("x", encoding="utf-8")

        with mock.patch("os.stat", side_effect=PermissionError("em uso")):
            assert app_module._assinatura_no_disco(str(arq)) == (None, None)


class TestDecisaoDeMudanca:
    def test_tamanho_diferente_e_mudanca(self, app_module):
        assert app_module._mudou_no_disco(1000.0, 500, 1000.0, 900) is True

    def test_data_diferente_e_mudanca(self, app_module):
        assert app_module._mudou_no_disco(1000.0, 500, 5000.0, 500) is True

    def test_igual_nao_e_mudanca(self, app_module):
        assert app_module._mudou_no_disco(1000.0, 500, 1000.0, 500) is False

    def test_tolera_dois_segundos_de_diferenca(self, app_module):
        """
        FAT32 e pendrives guardam a hora com resolução de 2 segundos. Copiar a
        mesma foto para um pendrive e de volta desloca o mtime sem que um byte
        tenha mudado — reanalisar isso é gasto de IA por nada.
        """
        assert app_module._mudou_no_disco(1000.0, 500, 1001.5, 500) is False
        assert app_module._mudou_no_disco(1000.0, 500, 1003.0, 500) is True

    def test_sem_assinatura_gravada_nao_e_mudanca(self, app_module):
        """
        Arquivo indexado antes das colunas existirem tem assinatura NULL.

        NULL é "nunca soube como era", não "mudou". Tratar como alteração
        mandaria a biblioteca inteira do usuário para a fila da IA na primeira
        verificação depois de atualizar o app — uma reanálise completa, cobrada
        em chamadas de IA, disparada por uma coluna nova.
        """
        assert app_module._mudou_no_disco(None, None, 1000.0, 500) is False

    def test_nao_conseguir_ler_agora_nao_e_mudanca(self, app_module):
        """Sem saber como o arquivo está, não dá para afirmar que mudou."""
        assert app_module._mudou_no_disco(1000.0, 500, None, None) is False


# ──────────────────────────────────────────────────────────────────────────
# Varredura compartilhada
# ──────────────────────────────────────────────────────────────────────────


class TestPercorrerArquivos:
    def test_encontra_arquivos_indexaveis_em_subpastas(self, app_module, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "a.jpg").write_text("x", encoding="utf-8")
        (tmp_path / "sub" / "b.png").write_text("x", encoding="utf-8")

        achados = {n for _, n, _ in app_module._percorrer_arquivos(str(tmp_path), [])}
        assert achados == {"a.jpg", "b.png"}

    def test_ignora_extensao_desconhecida(self, app_module, tmp_path):
        (tmp_path / "foto.jpg").write_text("x", encoding="utf-8")
        (tmp_path / "programa.exe").write_text("x", encoding="utf-8")
        (tmp_path / "sem_extensao").write_text("x", encoding="utf-8")

        achados = {n for _, n, _ in app_module._percorrer_arquivos(str(tmp_path), [])}
        assert achados == {"foto.jpg"}

    def test_respeita_a_blacklist(self, app_module, tmp_path):
        (tmp_path / "ignorada").mkdir()
        (tmp_path / "boa.jpg").write_text("x", encoding="utf-8")
        (tmp_path / "ignorada" / "ruim.jpg").write_text("x", encoding="utf-8")

        bl = [os.path.normpath(str(tmp_path / "ignorada")).lower()]
        achados = {n for _, n, _ in app_module._percorrer_arquivos(str(tmp_path), bl)}
        assert achados == {"boa.jpg"}

    def test_a_mesma_varredura_serve_scan_e_verificacao(self, app_module, tmp_path):
        """
        Enquanto eram dois laços separados, bastava um deles ganhar um filtro
        para a verificação acusar como "novo" algo que a varredura ignorava de
        propósito — e o contador nunca zeraria.
        """
        import inspect

        fonte_scan = inspect.getsource(app_module._scan_folder)
        fonte_verif = inspect.getsource(app_module._verificar_pasta)
        assert "_percorrer_arquivos" in fonte_scan
        assert "_percorrer_arquivos" in fonte_verif


class TestBlacklist:
    def test_ignora_caixa_das_letras(self, app_module):
        """No Windows "C:\\Temp" e "c:\\temp" são a mesma pasta."""
        bl = app_module._blacklist_do_usuario('{"pastas_ignoradas": "C:\\\\Temp"}')
        assert app_module._esta_na_blacklist(r"c:\temp\lixo.jpg", bl) is True

    def test_config_vazia_nao_ignora_nada(self, app_module):
        assert app_module._blacklist_do_usuario(None) == []
        assert app_module._blacklist_do_usuario("{}") == []

    def test_aceita_varias_separadas_por_virgula(self, app_module):
        bl = app_module._blacklist_do_usuario('{"pastas_ignoradas": "C:\\\\Temp, D:\\\\Cache"}')
        assert len(bl) == 2


# ──────────────────────────────────────────────────────────────────────────
# A conciliação
# ──────────────────────────────────────────────────────────────────────────


def _indexado(id_, caminho, mtime=1000.0, tamanho=8, ausente_em=None):
    return {
        "id": id_,
        "caminho": str(caminho),
        "nome": os.path.basename(str(caminho)),
        "mtime": mtime,
        "tamanho": tamanho,
        "ausente_em": ausente_em,
    }


def _rotas(indexados):
    return {
        "SELECT config_json": {"fetchone": {"config_json": None}},
        "FROM files WHERE user_id": {"fetchall": indexados},
    }


class TestConciliacao:
    def test_arquivo_novo_no_disco(self, app_module, db_roteado, tmp_path):
        (tmp_path / "nova.jpg").write_text("conteudo", encoding="utf-8")
        db_roteado(_rotas([]))

        achados = app_module._verificar_pasta(1, 1, str(tmp_path))

        assert [n["nome"] for n in achados["novos"]] == ["nova.jpg"]
        assert achados["ausentes"] == []

    def test_arquivo_intocado_nao_aparece_em_lista_nenhuma(self, app_module, db_roteado, tmp_path):
        arq = tmp_path / "estavel.jpg"
        arq.write_text("conteudo", encoding="utf-8")
        st = arq.stat()
        db_roteado(_rotas([_indexado(1, arq, st.st_mtime, st.st_size)]))

        achados = app_module._verificar_pasta(1, 1, str(tmp_path))

        assert achados == {"novos": [], "modificados": [], "ausentes": [], "voltaram": []}

    def test_arquivo_editado_e_modificado(self, app_module, db_roteado, tmp_path):
        arq = tmp_path / "editada.jpg"
        arq.write_text("conteudo bem maior que antes", encoding="utf-8")
        db_roteado(_rotas([_indexado(1, arq, 1000.0, 8)]))

        achados = app_module._verificar_pasta(1, 1, str(tmp_path))

        assert [m["nome"] for m in achados["modificados"]] == ["editada.jpg"]
        assert achados["novos"] == []

    def test_arquivo_apagado_fica_ausente(self, app_module, db_roteado, tmp_path):
        db_roteado(_rotas([_indexado(7, tmp_path / "sumida.jpg")]))

        achados = app_module._verificar_pasta(1, 1, str(tmp_path))

        assert [a["id"] for a in achados["ausentes"]] == [7]

    def test_ausente_nao_e_reacusado_toda_vez(self, app_module, db_roteado, tmp_path):
        """Já marcado, fica quieto — senão o contador nunca zera."""
        db_roteado(
            _rotas([_indexado(7, tmp_path / "sumida.jpg", ausente_em="2026-01-01T00:00:00Z")])
        )

        achados = app_module._verificar_pasta(1, 1, str(tmp_path))

        assert achados["ausentes"] == []

    def test_arquivo_que_reaparece_volta(self, app_module, db_roteado, tmp_path):
        """O caso do HD externo reconectado."""
        arq = tmp_path / "voltou.jpg"
        arq.write_text("conteudo", encoding="utf-8")
        st = arq.stat()
        db_roteado(
            _rotas([_indexado(3, arq, st.st_mtime, st.st_size, ausente_em="2026-01-01T00:00:00Z")])
        )

        achados = app_module._verificar_pasta(1, 1, str(tmp_path))

        assert [v["id"] for v in achados["voltaram"]] == [3]
        assert achados["ausentes"] == []

    def test_caixa_diferente_e_o_mesmo_arquivo(self, app_module, db_roteado, tmp_path):
        """
        No Windows o banco pode ter "FOTO.JPG" e o os.walk devolver "foto.jpg".
        Comparando cru, o mesmo arquivo apareceria como ausente E novo.
        """
        arq = tmp_path / "Foto.JPG"
        arq.write_text("conteudo", encoding="utf-8")
        st = arq.stat()
        gravado = str(tmp_path / "FOTO.JPG").upper()
        db_roteado(_rotas([_indexado(1, gravado, st.st_mtime, st.st_size)]))

        achados = app_module._verificar_pasta(1, 1, str(tmp_path))

        assert achados["novos"] == []
        assert achados["ausentes"] == []

    def test_arquivo_sem_assinatura_ganha_uma_sem_ser_reanalisado(
        self, app_module, db_roteado, tmp_path
    ):
        """
        O arquivo indexado antes desta feature: entra em `modificados`, mas
        marcado como `so_assinatura`. É contabilidade interna — não conta para
        o usuário e não vai para a fila da IA.
        """
        arq = tmp_path / "antiga.jpg"
        arq.write_text("conteudo", encoding="utf-8")
        db_roteado(_rotas([_indexado(1, arq, None, None)]))

        achados = app_module._verificar_pasta(1, 1, str(tmp_path))

        assert len(achados["modificados"]) == 1
        assert achados["modificados"][0]["so_assinatura"] is True

    def test_varios_de_uma_vez(self, app_module, db_roteado, tmp_path):
        intocada = tmp_path / "intocada.jpg"
        editada = tmp_path / "editada.jpg"
        intocada.write_text("conteudo", encoding="utf-8")
        editada.write_text("mudou de tamanho", encoding="utf-8")
        (tmp_path / "nova.jpg").write_text("x", encoding="utf-8")
        st = intocada.stat()

        db_roteado(
            _rotas(
                [
                    _indexado(1, intocada, st.st_mtime, st.st_size),
                    _indexado(2, editada, 1000.0, 3),
                    _indexado(3, tmp_path / "apagada.jpg"),
                ]
            )
        )

        achados = app_module._verificar_pasta(1, 1, str(tmp_path))

        assert [n["nome"] for n in achados["novos"]] == ["nova.jpg"]
        assert [m["nome"] for m in achados["modificados"]] == ["editada.jpg"]
        assert [a["id"] for a in achados["ausentes"]] == [3]


# ──────────────────────────────────────────────────────────────────────────
# Gravação do resultado
# ──────────────────────────────────────────────────────────────────────────


def _sqls(conexao):
    return [str(c.args[0]) for c in conexao.execute.call_args_list]


class TestGravacao:
    def test_ausente_e_marcado_e_nao_apagado(self, app_module, db_roteado):
        """A garantia central da feature."""
        conexao = db_roteado({})
        app_module._aplicar_verificacao(
            1,
            1,
            {
                "novos": [],
                "modificados": [],
                "ausentes": [{"id": 7, "caminho": "C:/x.jpg", "nome": "x.jpg"}],
                "voltaram": [],
            },
        )

        sql = " ".join(_sqls(conexao))
        assert "ausente_em" in sql
        assert "DELETE" not in sql.upper()

    def test_reaparecido_perde_a_marca(self, app_module, db_roteado):
        conexao = db_roteado({})
        app_module._aplicar_verificacao(
            1,
            1,
            {
                "novos": [],
                "modificados": [],
                "ausentes": [],
                "voltaram": [{"id": 3, "caminho": "C:/v.jpg", "nome": "v.jpg"}],
            },
        )

        assert any("ausente_em = NULL" in s for s in _sqls(conexao))

    def test_modificado_perde_a_descricao_antiga(self, app_module, db_roteado):
        """
        A descrição foi gerada a partir do conteúdo anterior. Mantê-la faria a
        busca encontrar a foto pelo que ela *era*, não pelo que é.
        """
        conexao = db_roteado({})
        app_module._aplicar_verificacao(
            1,
            1,
            {
                "novos": [],
                "modificados": [
                    {
                        "id": 5,
                        "caminho": "C:/m.jpg",
                        "nome": "m.jpg",
                        "tipo": "jpg",
                        "mtime": 2000.0,
                        "tamanho": 99,
                    }
                ],
                "ausentes": [],
                "voltaram": [],
            },
        )

        sql = " ".join(_sqls(conexao))
        assert "descricao_ia = ''" in sql
        assert "processado = 0" in sql

    def test_so_assinatura_nao_zera_descricao(self, app_module, db_roteado):
        """
        O arquivo antigo só está ganhando a assinatura que faltava. Zerar a
        descrição aqui mandaria a biblioteca inteira para a fila da IA na
        primeira verificação depois de atualizar o app.
        """
        conexao = db_roteado({})
        app_module._aplicar_verificacao(
            1,
            1,
            {
                "novos": [],
                "modificados": [
                    {
                        "id": 5,
                        "caminho": "C:/a.jpg",
                        "nome": "a.jpg",
                        "tipo": "jpg",
                        "mtime": 2000.0,
                        "tamanho": 99,
                        "so_assinatura": True,
                    }
                ],
                "ausentes": [],
                "voltaram": [],
            },
        )

        sql = " ".join(_sqls(conexao))
        assert "descricao_ia" not in sql
        assert "mtime" in sql

    def test_so_assinatura_nao_vai_para_a_fila(self, app_module, db_roteado):
        db_roteado({})
        with mock.patch.object(app_module._queue, "put") as posto:
            app_module._aplicar_verificacao(
                1,
                1,
                {
                    "novos": [],
                    "modificados": [
                        {
                            "id": 5,
                            "caminho": "C:/a.jpg",
                            "nome": "a.jpg",
                            "tipo": "jpg",
                            "mtime": 1.0,
                            "tamanho": 9,
                            "so_assinatura": True,
                        }
                    ],
                    "ausentes": [],
                    "voltaram": [],
                },
            )
        posto.assert_not_called()

    def test_novo_e_modificado_entram_na_fila(self, app_module, db_roteado):
        db_roteado({})
        with mock.patch.object(app_module._queue, "put") as posto:
            app_module._aplicar_verificacao(
                1,
                1,
                {
                    "novos": [
                        {
                            "caminho": "C:/n.jpg",
                            "nome": "n.jpg",
                            "tipo": "jpg",
                            "mtime": 1.0,
                            "tamanho": 9,
                        }
                    ],
                    "modificados": [
                        {
                            "id": 5,
                            "caminho": "C:/m.jpg",
                            "nome": "m.jpg",
                            "tipo": "jpg",
                            "mtime": 2.0,
                            "tamanho": 8,
                        }
                    ],
                    "ausentes": [],
                    "voltaram": [],
                },
            )

        enfileirados = {c.args[0]["nome"] for c in posto.call_args_list}
        assert enfileirados == {"n.jpg", "m.jpg"}

    def test_arquivo_ja_indexado_por_outra_pasta_nao_quebra(self, app_module, db_roteado):
        """
        Pastas aninhadas: "C:\\Fotos" e "C:\\Fotos\\2024" as duas indexadas. O
        UNIQUE (user_id, caminho) recusa o segundo INSERT, e sem o rollback a
        transação fica abortada — o resto da verificação viraria erro 500.
        """
        conexao = db_roteado({})
        conexao.execute.side_effect = app_module.psycopg2.errors.UniqueViolation("duplicado")

        app_module._aplicar_verificacao(
            1,
            1,
            {
                "novos": [
                    {
                        "caminho": "C:/n.jpg",
                        "nome": "n.jpg",
                        "tipo": "jpg",
                        "mtime": 1.0,
                        "tamanho": 9,
                    }
                ],
                "modificados": [],
                "ausentes": [],
                "voltaram": [],
            },
        )

        conexao.rollback.assert_called()


# ──────────────────────────────────────────────────────────────────────────
# O endpoint
# ──────────────────────────────────────────────────────────────────────────


class TestEndpoint:
    def test_devolve_o_resumo(self, client_logado, db_roteado, tmp_path):
        (tmp_path / "nova.jpg").write_text("x", encoding="utf-8")
        db_roteado(
            {
                "SELECT id, path FROM folders": {"fetchone": {"id": 1, "path": str(tmp_path)}},
                "SELECT config_json": {"fetchone": {"config_json": None}},
                "FROM files WHERE user_id": {"fetchall": []},
            }
        )

        corpo = client_logado.post("/api/folders/1/verificar").get_json()

        assert corpo["status"] == "ok"
        assert corpo["resumo"]["novos"] == 1
        assert corpo["novos"] == ["nova.jpg"]

    def test_resumo_esconde_a_contabilidade_interna(self, client_logado, db_roteado, tmp_path):
        """
        O arquivo que só ganhou assinatura não mudou para o usuário. Contá-lo
        como "1 modificado" seria o app relatando o próprio trabalho de casa
        como se fosse alteração feita por quem está lendo.
        """
        arq = tmp_path / "antiga.jpg"
        arq.write_text("x", encoding="utf-8")
        db_roteado(
            {
                "SELECT id, path FROM folders": {"fetchone": {"id": 1, "path": str(tmp_path)}},
                "SELECT config_json": {"fetchone": {"config_json": None}},
                "FROM files WHERE user_id": {
                    "fetchall": [
                        {
                            "id": 1,
                            "caminho": str(arq),
                            "nome": "antiga.jpg",
                            "mtime": None,
                            "tamanho": None,
                            "ausente_em": None,
                        }
                    ]
                },
            }
        )

        corpo = client_logado.post("/api/folders/1/verificar").get_json()

        assert corpo["resumo"]["modificados"] == 0
        assert corpo["modificados"] == []

    def test_pasta_de_outro_dono_da_404(self, client_logado, db_roteado):
        db_roteado({"SELECT id, path FROM folders": {"fetchone": None}})
        assert client_logado.post("/api/folders/999/verificar").status_code == 404

    def test_pasta_sumida_do_disco_da_409_sem_marcar_nada(
        self, client_logado, db_roteado, tmp_path
    ):
        """
        Um HD externo desconectado apagaria a pasta inteira da busca de uma vez.
        Melhor avisar e não tocar em nada.
        """
        sumida = tmp_path / "disco_removido"
        conexao = db_roteado(
            {
                "SELECT id, path FROM folders": {"fetchone": {"id": 1, "path": str(sumida)}},
            }
        )

        r = client_logado.post("/api/folders/1/verificar")

        assert r.status_code == 409
        assert r.get_json()["pasta_sumiu"] is True
        assert not any("ausente_em" in s for s in _sqls(conexao))

    def test_exige_sessao(self, client, db_roteado):
        db_roteado({})
        assert client.post("/api/folders/1/verificar").status_code == 401

    def test_get_nao_executa_a_verificacao(self, client_logado, db_roteado):
        """
        Verificar grava no banco, então não pode acontecer por GET — um link ou
        um prefetch do navegador dispararia reindexação sozinho.

        Não é 405: a rota `/<path:filename>` que serve o front captura todo GET
        antes do roteamento chegar aqui, e devolve 404 de arquivo não achado.
        O que este teste garante é o que importa — nada foi escrito.
        """
        conexao = db_roteado({})
        r = client_logado.get("/api/folders/1/verificar")

        assert r.status_code == 404
        conexao.execute.assert_not_called()
