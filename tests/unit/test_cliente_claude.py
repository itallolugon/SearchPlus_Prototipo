# -*- coding: utf-8 -*-
"""
O cliente da Anthropic nasce com teto de espera.

Sem `timeout`, o padrão do SDK são 10 minutos — o que na prática é não ter
teto. Isso importa porque o re-rank roda **dentro do request** da busca: uma
chamada lenta prende a busca inteira, e o fallback que já existe em
`_rerank_com_claude` (`return candidatos`) nunca chega a rodar, porque ele
cobre erro e não lentidão.

`max_retries=1` e não o padrão 2: com retry automático, um timeout de 20s vira
60s de espera real. É melhor degradar rápido — o motor tem resultado para
mostrar sem a IA.

Nenhum teste aqui fala com a rede: o módulo `anthropic` é substituído por um
duplo que só registra como foi construído.

Ver `docs/features/16-latencia-da-busca.md`, seção 7.
"""

import sys
import types
from unittest import mock

import pytest

pytestmark = pytest.mark.unit


def _anthropic_falso(registro):
    """Módulo `anthropic` de mentira: guarda os kwargs da construção."""
    modulo = types.ModuleType("anthropic")

    class Anthropic:
        def __init__(self, **kwargs):
            registro.update(kwargs)

    modulo.Anthropic = Anthropic
    return modulo


def _construir(app_module, env=None):
    """
    Roda `_iniciar_claude()` com o SDK substituído e devolve os kwargs usados.

    Os globais mexidos pela função são restaurados: outros testes leem
    `CLAUDE_OK` e não podem herdar um cliente de mentira.
    """
    registro = {}
    claude_antes, ok_antes = app_module._CLAUDE, app_module.CLAUDE_OK
    ambiente = {"ANTHROPIC_API_KEY": "sk-ant-teste"}
    ambiente.update(env or {})
    try:
        with (
            mock.patch.dict(sys.modules, {"anthropic": _anthropic_falso(registro)}),
            mock.patch.dict(app_module.os.environ, ambiente),
        ):
            app_module._iniciar_claude()
    finally:
        app_module._CLAUDE = claude_antes
        app_module.CLAUDE_OK = ok_antes
    return registro


class TestTetoDeEspera:
    def test_o_cliente_nasce_com_timeout(self, app_module):
        kwargs = _construir(app_module)
        assert "timeout" in kwargs, (
            "cliente sem timeout: o padrão do SDK são 10 minutos, e o re-rank "
            "roda dentro do request da busca."
        )
        assert kwargs["timeout"] == 20.0

    def test_uma_retentativa_e_nao_duas(self, app_module):
        """Com o padrão 2, um timeout de 20s vira 60s de espera real."""
        kwargs = _construir(app_module)
        assert kwargs.get("max_retries") == 1

    def test_o_timeout_e_ajustavel_pelo_env(self, app_module):
        """
        Quem quiser mais agressividade não deveria precisar editar código —
        e quem tiver rede ruim precisa poder afrouxar.
        """
        kwargs = _construir(app_module, {"CLAUDE_TIMEOUT": "5"})
        assert kwargs["timeout"] == 5.0

    def test_a_chave_continua_sendo_passada(self, app_module):
        """A mudança é de teto, não de autenticação."""
        kwargs = _construir(app_module)
        assert kwargs.get("api_key") == "sk-ant-teste"


class TestSemChave:
    def test_sem_chave_nao_constroi_cliente(self, app_module):
        """
        Chave vazia é o caso do ambiente de teste e de quem ainda não
        configurou. Tem que sair sem cliente e sem exceção.
        """
        kwargs = _construir(app_module, {"ANTHROPIC_API_KEY": ""})
        assert kwargs == {}, "construiu cliente sem chave"


class TestDocumentado:
    def test_o_env_example_explica_o_timeout(self):
        """
        Um valor que muda o comportamento e só existe no código é um valor que
        ninguém sabe que pode ajustar.
        """
        import io
        import os

        raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        exemplo = io.open(os.path.join(raiz, "backend", ".env.example"), encoding="utf-8").read()
        assert "CLAUDE_TIMEOUT" in exemplo
