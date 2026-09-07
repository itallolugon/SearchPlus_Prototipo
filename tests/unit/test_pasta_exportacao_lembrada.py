# -*- coding: utf-8 -*-
"""
Última pasta de exportação lembrada em `config_json`.

Quem sempre exporta para o mesmo lugar reescolhia o caminho a cada exportação.
A preferência vive no JSONB de config — não exige coluna nova.

A regra que sustenta o resto: **uma preferência não pode virar obstáculo**. Se
a pasta lembrada sumiu (HD desconectado, pasta apagada), o seletor abre no
padrão do sistema em silêncio. Falha ao gravar também não pode derrubar a
exportação, que é a operação que o usuário pediu.
"""

import json
from unittest import mock

import pytest

pytestmark = pytest.mark.unit


class TestLeitura:
    def test_devolve_a_pasta_guardada(self, app_module, db_roteado, tmp_path):
        pasta = tmp_path / "Exportacoes"
        pasta.mkdir()
        db_roteado(
            {
                "SELECT config_json FROM users": {
                    "fetchone": {"config_json": json.dumps({"ultima_pasta_exportacao": str(pasta)})}
                }
            }
        )
        assert app_module._ultima_pasta_exportacao(1) == str(pasta)

    def test_pasta_que_sumiu_cai_no_padrao(self, app_module, db_roteado, tmp_path):
        """Sem erro: devolve vazio e o seletor decide sozinho."""
        db_roteado(
            {
                "SELECT config_json FROM users": {
                    "fetchone": {
                        "config_json": json.dumps(
                            {"ultima_pasta_exportacao": str(tmp_path / "foi_embora")}
                        )
                    }
                }
            }
        )
        assert app_module._ultima_pasta_exportacao(1) == ""

    def test_config_sem_a_chave(self, app_module, db_roteado):
        db_roteado(
            {
                "SELECT config_json FROM users": {
                    "fetchone": {"config_json": json.dumps({"tema": "dark"})}
                }
            }
        )
        assert app_module._ultima_pasta_exportacao(1) == ""

    def test_config_corrompido_nao_estoura(self, app_module, db_roteado):
        db_roteado(
            {"SELECT config_json FROM users": {"fetchone": {"config_json": "{ isto não é json"}}}
        )
        assert app_module._ultima_pasta_exportacao(1) == ""

    def test_sem_usuario(self, app_module, db_roteado):
        db_roteado({})
        assert app_module._ultima_pasta_exportacao(None) == ""

    def test_banco_fora_do_ar_nao_impede_o_seletor(self, app_module, tmp_path):
        """Sem banco o diálogo ainda tem de abrir — só sem pré-preencher."""
        with mock.patch.object(app_module, "get_db", side_effect=OSError("sem banco")):
            assert app_module._ultima_pasta_exportacao(1) == ""


class TestEscrita:
    def test_grava_a_pasta_escolhida(self, app_module, db_roteado, tmp_path):
        conexao = db_roteado(
            {
                "SELECT config_json FROM users": {
                    "fetchone": {"config_json": json.dumps({"tema": "dark"})}
                }
            }
        )
        app_module._lembrar_pasta_exportacao(1, str(tmp_path))

        update = next(c for c in conexao.execute.call_args_list if "UPDATE users" in str(c.args[0]))
        gravado = json.loads(update.args[1][0])
        assert gravado["ultima_pasta_exportacao"] == str(tmp_path)
        assert gravado["tema"] == "dark"  # não apaga o resto do config

    def test_nao_reescreve_quando_nada_muda(self, app_module, db_roteado, tmp_path):
        """Exportar 10 vezes para o mesmo lugar não gera 10 escritas."""
        conexao = db_roteado(
            {
                "SELECT config_json FROM users": {
                    "fetchone": {
                        "config_json": json.dumps({"ultima_pasta_exportacao": str(tmp_path)})
                    }
                }
            }
        )
        app_module._lembrar_pasta_exportacao(1, str(tmp_path))

        assert not any("UPDATE users" in str(c.args[0]) for c in conexao.execute.call_args_list)

    def test_destino_vazio_e_ignorado(self, app_module, db_roteado):
        conexao = db_roteado({})
        app_module._lembrar_pasta_exportacao(1, "")
        assert conexao.execute.call_count == 0

    def test_falha_ao_gravar_nao_propaga(self, app_module, tmp_path):
        """A exportação é o que o usuário pediu; lembrar é conveniência."""
        with mock.patch.object(app_module, "get_db", side_effect=OSError("sem banco")):
            app_module._lembrar_pasta_exportacao(1, str(tmp_path))  # não levanta


class TestSeletor:
    def test_seletor_recebe_a_pasta_lembrada(self, app_module, db_roteado, tmp_path):
        pasta = tmp_path / "Exportacoes"
        pasta.mkdir()
        db_roteado(
            {
                "SELECT config_json FROM users": {
                    "fetchone": {"config_json": json.dumps({"ultima_pasta_exportacao": str(pasta)})}
                }
            }
        )
        assert app_module._ultima_pasta_exportacao(1) == str(pasta)
