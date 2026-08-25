# -*- coding: utf-8 -*-
"""
Prefixo de pasta — a regra que decide "este arquivo está DENTRO desta pasta".

Errar aqui já causou três bugs distintos em produção: filtro de busca trazendo
pasta irmã, a mesma pasta indexada duas vezes por diferença de caixa, e a
exclusão de uma pasta pai levando junto o índice de uma subpasta que continuava
monitorada. Estes testes existem para que nenhum deles volte.

Os caminhos são montados com `caminho()` em vez de escritos à mão: o app roda no
Windows, mas o CI roda em Linux, e um caminho fixo no estilo de uma plataforma
não é comparável na outra.
"""

import os

import pytest

from tests.caminhos import caminho

pytestmark = pytest.mark.unit


class TestPrefixoPasta:
    def test_termina_com_separador(self, app_module):
        """Sem o separador no fim, 'Fotos' casa com 'Fotos_backup'."""
        assert app_module._prefixo_pasta(caminho("Fotos")).endswith(os.sep)

    def test_normaliza_caixa(self, app_module):
        """O Windows não diferencia maiúsculas; o UNIQUE do Postgres diferencia."""
        assert app_module._prefixo_pasta(caminho("Fotos")) == app_module._prefixo_pasta(
            caminho("Fotos").upper()
        )

    def test_barra_final_nao_muda_resultado(self, app_module):
        assert app_module._prefixo_pasta(caminho("Fotos")) == app_module._prefixo_pasta(
            caminho("Fotos") + os.sep
        )

    def test_resolve_ponto_ponto(self, app_module):
        assert app_module._prefixo_pasta(caminho("A", "B", "..")) == app_module._prefixo_pasta(
            caminho("A")
        )

    def test_nao_duplica_separador(self, app_module):
        resultado = app_module._prefixo_pasta(caminho("Fotos") + os.sep)
        assert not resultado.endswith(os.sep + os.sep)

    def test_resultado_e_minusculo(self, app_module):
        prefixo = app_module._prefixo_pasta(caminho("FOTOS"))
        assert prefixo == prefixo.lower()


class TestDentroDaPasta:
    """
    Exercita a comparação como as queries fazem: `left(lower(caminho), N) == prefixo`.
    É a regressão dos bugs de vazamento entre pastas irmãs.
    """

    @staticmethod
    def _esta_dentro(app_module, pasta: str, alvo: str) -> bool:
        prefixo = app_module._prefixo_pasta(pasta)
        return alvo.lower()[: len(prefixo)] == prefixo

    @pytest.mark.parametrize(
        "partes,esperado",
        [
            (("Fotos", "gato.jpg"), True),
            (("Fotos", "sub", "cao.jpg"), True),
            (("Fotos_backup", "segredo.jpg"), False),  # irmã com prefixo comum
            (("Fotos2", "privado.jpg"), False),  # irmã com sufixo numérico
            (("Outra", "x.jpg"), False),
            (("FotosX", "y.jpg"), False),
        ],
    )
    def test_delimita_pela_pasta_certa(self, app_module, partes, esperado):
        assert self._esta_dentro(app_module, caminho("Fotos"), caminho(*partes)) is esperado

    def test_caixa_diferente_ainda_casa(self, app_module):
        """O mesmo arquivo escrito com outra caixa continua dentro da pasta."""
        alvo = caminho("Fotos", "CAIXA_DIFERENTE.jpg").upper()
        assert self._esta_dentro(app_module, caminho("Fotos"), alvo)

    def test_subpasta_conta_como_dentro(self, app_module):
        """Remover a pasta pai precisa alcançar os arquivos das subpastas."""
        assert self._esta_dentro(app_module, caminho("A"), caminho("A", "B", "arquivo.jpg"))

    def test_pasta_filha_nao_contem_arquivo_da_pai(self, app_module):
        assert not self._esta_dentro(app_module, caminho("A", "B"), caminho("A", "raiz.jpg"))


class TestConvencaoPosix:
    """
    Prova que a regra vale também na convenção POSIX, sem precisar de um Linux.

    A suíte roda no Windows, mas o CI roda em Linux — e a primeira execução do
    pipeline quebrou exatamente aqui: os testes fixavam caminhos no estilo
    `C:\\Fotos`, que no Linux não têm separador reconhecível. Trocar `os.path`
    por `posixpath` exercita o mesmo código sob as regras do runner.
    """

    @pytest.fixture()
    def como_no_linux(self, app_module, monkeypatch):
        import posixpath

        monkeypatch.setattr(app_module.os, "path", posixpath)
        monkeypatch.setattr(app_module.os, "sep", "/")
        return app_module

    def test_prefixo_usa_a_barra_do_sistema(self, como_no_linux):
        assert como_no_linux._prefixo_pasta("/Fotos") == "/fotos/"

    def test_arquivo_de_dentro_casa(self, como_no_linux):
        prefixo = como_no_linux._prefixo_pasta("/Fotos")
        assert "/fotos/gato.jpg".startswith(prefixo)
        assert "/fotos/sub/cao.jpg".startswith(prefixo)

    def test_pasta_irma_nao_casa(self, como_no_linux):
        prefixo = como_no_linux._prefixo_pasta("/Fotos")
        assert not "/fotos_backup/segredo.jpg".startswith(prefixo)
        assert not "/fotos2/privado.jpg".startswith(prefixo)

    def test_ponto_ponto_resolvido(self, como_no_linux):
        assert como_no_linux._prefixo_pasta("/A/B/..") == como_no_linux._prefixo_pasta("/A")


class TestPrefixoComPastaReal:
    """Mesma regra contra uma árvore de verdade no disco."""

    def test_arvore_temporaria(self, app_module, tmp_pasta_com_arquivos):
        base = tmp_pasta_com_arquivos
        pref_fotos = app_module._prefixo_pasta(str(base / "Fotos"))

        dentro = str(base / "Fotos" / "a.jpg").lower()
        sub = str(base / "Fotos" / "sub" / "b.jpg").lower()
        irma = str(base / "Fotos_backup" / "c.jpg").lower()

        assert dentro.startswith(pref_fotos)
        assert sub.startswith(pref_fotos)
        assert not irma.startswith(pref_fotos), "pasta irmã não pode casar com o prefixo"
