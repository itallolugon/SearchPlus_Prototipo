# -*- coding: utf-8 -*-
"""
Janela de processamento — "só indexe entre 22h e 6h".

A hora é LOCAL de propósito (os timestamps do banco são UTC, esta checagem não):
a janela é configurada pelo usuário no fuso da máquina dele. Os testes fixam a
hora para não dependerem de quando a suíte roda.
"""

from unittest import mock

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture()
def com_hora(app_module):
    """Congela `datetime.now().hour` no valor pedido."""

    def _fixar(hora: int):
        patch = mock.patch.object(app_module, "datetime")
        falso = patch.start()
        falso.now.return_value.hour = hora
        return patch

    patches = []

    def _aplicar(hora: int):
        p = _fixar(hora)
        patches.append(p)
        return app_module

    yield _aplicar
    for p in patches:
        p.stop()


class TestSemRestricao:
    @pytest.mark.parametrize("janela", ["always", "", None])
    def test_sempre_liberado(self, app_module, janela):
        assert app_module._is_within_window(janela) is True


class TestJanelaDiurna:
    """09:00-17:00 — não cruza a meia-noite."""

    @pytest.mark.parametrize(
        "hora,dentro", [(8, False), (9, True), (12, True), (16, True), (17, False), (20, False)]
    )
    def test_limites(self, com_hora, hora, dentro):
        app = com_hora(hora)
        assert app._is_within_window("09:00-17:00") is dentro


class TestJanelaNoturna:
    """22:00-06:00 — cruza a meia-noite, o caso que costuma quebrar."""

    @pytest.mark.parametrize(
        "hora,dentro",
        [
            (21, False),
            (22, True),
            (23, True),
            (0, True),
            (3, True),
            (5, True),
            (6, False),
            (12, False),
        ],
    )
    def test_limites(self, com_hora, hora, dentro):
        app = com_hora(hora)
        assert app._is_within_window("22:00-06:00") is dentro


class TestEntradaMalformada:
    """Config corrompida não pode travar a indexação — na dúvida, libera."""

    @pytest.mark.parametrize(
        "janela",
        ["invalido", "10-20-30", "abc:00-def:00", "22:00", "::", "-"],
    )
    def test_formato_invalido_libera(self, app_module, janela):
        assert app_module._is_within_window(janela) is True
