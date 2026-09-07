# -*- coding: utf-8 -*-
"""
Queda de rede não pode ser silêncio.

Boa parte do front trata erro HTTP (`if (!r.ok)`) e não trata a rede cair. São
coisas diferentes: com o servidor fora do ar o `fetch` **rejeita**, a função
morre ali, e a pessoa fica olhando para um clique que não fez nada — sem
mensagem, sem "carregando", sem nada. É o pior tipo de falha, porque ela nem
sabe se deu errado ou se não clicou direito.

Levantei 10 funções assim (adicionar pasta, remover pasta, enviar favoritos
para coleção, salvar configurações, finalizar onboarding, entre outras).
Consertar uma a uma resolveria as de hoje e não a próxima que alguém escrever,
então o piso é um ouvinte de `unhandledrejection`.

O ouvinte não substitui tratamento específico: quando dá para dizer O QUE
falhou, a função continua dizendo. Ele garante que nunca seja silêncio.

Conferido no navegador: rejeição de rede avisa uma vez, cinco seguidas avisam
uma só, erro que não é de rede vai só para o console, e a operação normal do
app não gera aviso nenhum.
"""

import io
import os
import re

import pytest

pytestmark = pytest.mark.unit

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(RAIZ, "script.js")


def _ler():
    return io.open(SCRIPT, encoding="utf-8").read()


def _bloco_do_ouvinte(js):
    i = js.index("addEventListener('unhandledrejection'")
    return js[i : i + 1600]


class TestARedeDeSeguranca:
    def test_o_ouvinte_existe(self):
        assert "addEventListener('unhandledrejection'" in _ler(), (
            "sem este ouvinte, uma falha de rede numa função sem try/catch "
            "vira silêncio: o clique não faz nada e ninguém explica por quê."
        )

    def test_avisa_o_usuario_e_nao_so_o_console(self):
        bloco = _bloco_do_ouvinte(_ler())
        assert "toastErro" in bloco, "o usuário precisa ser avisado, não só o console"
        assert "console.error" in bloco, (
            "o erro completo precisa continuar no console; quem depura precisa "
            "dele, não do resumo amigável."
        )

    def test_so_avisa_quando_e_falha_de_rede(self):
        """
        Um bug de lógica também chega aqui como promessa rejeitada. Avisar
        'não foi possível falar com o servidor' nesse caso seria mentira, e
        mandaria a pessoa conferir a conexão por nada.
        """
        bloco = _bloco_do_ouvinte(_ler())
        assert "TypeError" in bloco, "falta distinguir falha de rede de outros erros"

    def test_nao_vira_avalanche(self):
        """
        Uma tela que dispara várias chamadas de uma vez geraria um aviso por
        chamada, e a pessoa passaria a fechar avisos em vez de ler.
        """
        js = _ler()
        assert "_ultimoAvisoDeRede" in js, "falta o intervalo entre avisos"
        bloco = _bloco_do_ouvinte(js)
        m = re.search(r"agora - _ultimoAvisoDeRede < (\d+)", bloco)
        assert m, "o intervalo entre avisos sumiu"
        assert int(m.group(1)) >= 2000, "intervalo curto demais para conter uma rajada"


class TestTratamentoEspecifico:
    """
    Onde a mensagem genérica seria pior que uma específica, a função continua
    dizendo o que falhou.
    """

    def test_remover_pasta_diz_o_que_falhou(self):
        js = _ler()
        i = js.index("async function removerPasta(")
        corpo = js[i : js.index("\nasync function ", i + 10)]
        assert "try {" in corpo and "toastErro" in corpo, (
            "removerPasta voltou a falhar em silêncio; ela também engolia erro "
            "HTTP, não só queda de rede."
        )
