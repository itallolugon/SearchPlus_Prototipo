# -*- coding: utf-8 -*-
"""
Chave de sessão: ambiente → arquivo → gerar.

Antes existia só o primeiro passo, com um literal de desenvolvimento como
fallback. O literal era o mesmo em toda execução, então a sessão até
sobrevivia ao reinício — o problema era outro: **uma chave conhecida e
versionada permite forjar cookie de sessão**.

Gerar e guardar resolve os dois lados: a chave passa a ser secreta *e* estável.

A propriedade que sustenta o resto: **a mesma chave entre reinícios**. Sem
isso, todo boot invalida os cookies e desloga o usuário.
"""

import os
from unittest import mock

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture()
def segredo_em(tmp_path, app_module, monkeypatch):
    """Aponta o arquivo de segredo para um temporário, sem tocar o do projeto."""
    alvo = tmp_path / ".secret_key"
    monkeypatch.setattr(app_module, "ARQUIVO_SEGREDO", alvo)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    return alvo


class TestPrecedencia:
    def test_ambiente_vence_tudo(self, app_module, segredo_em, monkeypatch):
        segredo_em.write_text("do-arquivo", encoding="utf-8")
        monkeypatch.setenv("SECRET_KEY", "do-ambiente")

        assert app_module._resolver_secret_key() == "do-ambiente"

    def test_ambiente_vazio_e_ignorado(self, app_module, segredo_em, monkeypatch):
        """`SECRET_KEY=` no .env não pode virar chave vazia."""
        segredo_em.write_text("do-arquivo", encoding="utf-8")
        monkeypatch.setenv("SECRET_KEY", "   ")

        assert app_module._resolver_secret_key() == "do-arquivo"

    def test_arquivo_vence_geracao(self, app_module, segredo_em):
        segredo_em.write_text("ja-existia", encoding="utf-8")
        assert app_module._resolver_secret_key() == "ja-existia"

    def test_gera_quando_nao_ha_nada(self, app_module, segredo_em):
        chave = app_module._resolver_secret_key()

        assert len(chave) == 64  # token_hex(32)
        assert segredo_em.exists()
        assert segredo_em.read_text(encoding="utf-8").strip() == chave


class TestEstabilidade:
    def test_mesma_chave_entre_reinicios(self, app_module, segredo_em):
        """A propriedade central: reiniciar não pode deslogar o usuário."""
        primeira = app_module._resolver_secret_key()
        segunda = app_module._resolver_secret_key()  # simula outro boot

        assert primeira == segunda

    def test_chaves_diferentes_em_instalacoes_diferentes(self, app_module, tmp_path, monkeypatch):
        """Duas máquinas não podem acabar com a mesma chave."""
        monkeypatch.delenv("SECRET_KEY", raising=False)
        chaves = set()
        for i in range(3):
            monkeypatch.setattr(
                app_module, "ARQUIVO_SEGREDO", tmp_path / f"inst{i}" / ".secret_key"
            )
            (tmp_path / f"inst{i}").mkdir()
            chaves.add(app_module._resolver_secret_key())

        assert len(chaves) == 3

    def test_arquivo_vazio_gera_nova(self, app_module, segredo_em):
        segredo_em.write_text("   \n", encoding="utf-8")
        chave = app_module._resolver_secret_key()

        assert len(chave) == 64


class TestFalhas:
    def test_disco_somente_leitura_nao_derruba_o_app(self, app_module, segredo_em):
        """
        Sem poder gravar, a chave vale para esta execução. Subir sem sessão
        persistente é pior que não subir? Não — o app fica utilizável.
        """
        with mock.patch.object(
            type(segredo_em), "write_text", side_effect=OSError("somente leitura")
        ):
            chave = app_module._resolver_secret_key()

        assert len(chave) == 64  # continua devolvendo chave válida

    def test_arquivo_ilegivel_gera_nova(self, app_module, segredo_em):
        segredo_em.write_text("qualquer", encoding="utf-8")
        with mock.patch.object(type(segredo_em), "read_text", side_effect=OSError("sem permissão")):
            chave = app_module._resolver_secret_key()

        assert len(chave) == 64


class TestSegredoNaoVersionado:
    def test_gitignore_cobre_o_arquivo(self, app_module):
        """Chave de sessão em repositório compartilhado seria pior que a antiga."""
        raiz = app_module.BASE_DIR.parent
        conteudo = (raiz / ".gitignore").read_text(encoding="utf-8")
        assert ".secret_key" in conteudo

    def test_nao_ha_mais_chave_literal_no_codigo(self, app_module):
        fonte = (app_module.BASE_DIR / "app.py").read_text(encoding="utf-8")
        assert "searchplus_dev_only_key" not in fonte
