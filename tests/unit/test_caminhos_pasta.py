# -*- coding: utf-8 -*-
"""
Prefixo de pasta — a regra que decide "este arquivo está DENTRO desta pasta".

Errar aqui já causou três bugs distintos em produção: filtro de busca trazendo
pasta irmã, a mesma pasta indexada duas vezes por diferença de caixa, e a
exclusão de uma pasta pai levando junto o índice de uma subpasta que continuava
monitorada. Estes testes existem para que nenhum deles volte.
"""

import os

import pytest

pytestmark = pytest.mark.unit


class TestPrefixoPasta:
    def test_termina_com_separador(self, app_module):
        """Sem o separador no fim, 'C:\\Fotos' casa com 'C:\\Fotos_backup'."""
        assert app_module._prefixo_pasta(r"C:\Fotos").endswith(os.sep)

    def test_normaliza_caixa(self, app_module):
        """Windows não diferencia maiúsculas; o UNIQUE do Postgres diferencia."""
        assert app_module._prefixo_pasta(r"C:\Fotos") == app_module._prefixo_pasta(r"c:\fotos")

    def test_barra_final_nao_muda_resultado(self, app_module):
        assert app_module._prefixo_pasta(r"C:\Fotos") == app_module._prefixo_pasta("C:\\Fotos\\")

    def test_unifica_separadores(self, app_module):
        assert app_module._prefixo_pasta("C:/Fotos") == app_module._prefixo_pasta(r"C:\Fotos")

    def test_resolve_ponto_ponto(self, app_module):
        assert app_module._prefixo_pasta(r"C:\A\B\..") == app_module._prefixo_pasta(r"C:\A")

    def test_nao_duplica_separador(self, app_module):
        resultado = app_module._prefixo_pasta("C:\\Fotos\\")
        assert not resultado.endswith(os.sep + os.sep)


class TestDentroDaPasta:
    """
    Exercita a comparação como as queries fazem: `left(lower(caminho), N) == prefixo`.
    É a regressão dos bugs de vazamento entre pastas irmãs.
    """

    @staticmethod
    def _esta_dentro(app_module, pasta: str, caminho: str) -> bool:
        prefixo = app_module._prefixo_pasta(pasta)
        return caminho.lower()[: len(prefixo)] == prefixo

    @pytest.mark.parametrize(
        "caminho,esperado",
        [
            (r"C:\Fotos\gato.jpg", True),
            (r"C:\Fotos\sub\cao.jpg", True),
            (r"c:\fotos\CAIXA_DIFERENTE.jpg", True),
            (r"C:\Fotos_backup\segredo.jpg", False),  # irmã com prefixo comum
            (r"C:\Fotos2\privado.jpg", False),  # irmã com sufixo numérico
            (r"C:\Outra\x.jpg", False),
            (r"C:\FotosX\y.jpg", False),
        ],
    )
    def test_delimita_pela_pasta_certa(self, app_module, caminho, esperado):
        assert self._esta_dentro(app_module, r"C:\Fotos", caminho) is esperado

    def test_subpasta_conta_como_dentro(self, app_module):
        """Remover a pasta pai precisa alcançar os arquivos das subpastas."""
        assert self._esta_dentro(app_module, r"C:\A", r"C:\A\B\arquivo.jpg")

    def test_pasta_filha_nao_contem_arquivo_da_pai(self, app_module):
        assert not self._esta_dentro(app_module, r"C:\A\B", r"C:\A\raiz.jpg")


class TestPrefixoComPastaReal(object):
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
