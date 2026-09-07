# -*- coding: utf-8 -*-
"""Normalização de texto e saneamento antes do banco."""

import pytest

pytestmark = pytest.mark.unit


class TestNormalizar:
    """`_normalizar` tira acento e caixa — é a base de toda comparação da busca."""

    @pytest.mark.parametrize(
        "entrada,esperado",
        [
            ("Ação", "acao"),
            ("ÁÉÍÓÚ", "aeiou"),
            ("ção", "cao"),
            ("CACHORRO", "cachorro"),
            ("já é", "ja e"),
            ("coração partido", "coracao partido"),
            ("", ""),
            ("123", "123"),
            ("sem_acento", "sem_acento"),
        ],
    )
    def test_remove_acento_e_caixa(self, app_module, entrada, esperado):
        assert app_module._normalizar(entrada) == esperado

    def test_e_idempotente(self, app_module):
        """Normalizar duas vezes não pode mudar o resultado."""
        uma = app_module._normalizar("Ação É Ótimo")
        assert app_module._normalizar(uma) == uma

    def test_preserva_espacamento_interno(self, app_module):
        """Não é a função que colapsa espaço — quem depende disso precisa saber."""
        assert app_module._normalizar("  MÚLTIPLOS   espaços  ") == "  multiplos   espacos  "

    def test_none_estoura(self, app_module):
        """
        Comportamento ATUAL documentado: `_normalizar(None)` levanta AttributeError.

        Todos os chamadores hoje passam `x or ""`. O teste existe para que uma
        mudança nesse contrato seja uma decisão consciente, não um acidente.
        """
        with pytest.raises(AttributeError):
            app_module._normalizar(None)


class TestLimparTextoParaBanco:
    """
    O Postgres recusa \\x00 em coluna text. Um único arquivo corrompido com esse
    byte derrubava a thread de indexação inteira.
    """

    def test_remove_byte_nul(self, app_module):
        assert app_module._limpar_texto_para_banco("antes\x00depois") == "antesdepois"

    def test_remove_varios_nuls(self, app_module):
        assert app_module._limpar_texto_para_banco("\x00a\x00b\x00") == "ab"

    def test_texto_limpo_passa_intacto(self, app_module):
        texto = "relatório de vendas — 2026"
        assert app_module._limpar_texto_para_banco(texto) == texto

    @pytest.mark.parametrize("vazio", ["", None])
    def test_vazio_nao_estoura(self, app_module, vazio):
        assert app_module._limpar_texto_para_banco(vazio) == vazio

    def test_preserva_acento_e_quebra_de_linha(self, app_module):
        """Só o NUL sai: quebra de linha é o separador dos campos da descrição."""
        texto = "- Estilo: foto\n- Animais: cachorro"
        assert app_module._limpar_texto_para_banco(texto) == texto


class TestSafeJsonLoads:
    """Config e prioridades chegam do banco como TEXT ou já como dict."""

    def test_json_valido_vira_dict(self, app_module):
        assert app_module._safe_json_loads('{"a": 1}', {}) == {"a": 1}

    def test_json_valido_vira_lista(self, app_module):
        assert app_module._safe_json_loads("[1, 2]", []) == [1, 2]

    def test_dict_passa_direto(self, app_module):
        """JSONB do Postgres já chega desserializado — não pode passar por loads."""
        original = {"ja": "e dict"}
        assert app_module._safe_json_loads(original, {}) == original

    @pytest.mark.parametrize("ruim", ["quebrado{", "", "não é json"])
    def test_invalido_cai_no_padrao(self, app_module, ruim):
        assert app_module._safe_json_loads(ruim, "PADRAO") == "PADRAO"

    def test_none_cai_no_padrao(self, app_module):
        assert app_module._safe_json_loads(None, "PADRAO") == "PADRAO"

    def test_null_json_devolve_none_e_nao_o_padrao(self, app_module):
        """
        Sutileza real: a string "null" é JSON válido e desserializa para None,
        então NÃO cai no default. Quem trata o retorno precisa contar com isso.
        """
        assert app_module._safe_json_loads("null", "PADRAO") is None
