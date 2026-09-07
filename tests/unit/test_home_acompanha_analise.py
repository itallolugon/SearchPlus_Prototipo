# -*- coding: utf-8 -*-
"""
A home acompanha a análise sozinha.

Quem adicionava uma pasta ficava olhando a barra de progresso andar com a home
vazia atrás, e só via as fotos depois de recarregar a página na mão. O aviso de
"análise concluída" já existia — e avisar sem mostrar é o pior dos dois mundos:
a pessoa fica sabendo que terminou e continua sem ver nada.

O front não tem runner de JavaScript neste projeto, então o que dá para fixar
daqui são as ligações que, se sumirem num refactor, quebram o comportamento em
silêncio — sem erro no console e sem teste vermelho. São elas:

  1. a barra de status é quem dispara a atualização;
  2. mostrar o resultado não depende de as notificações estarem ligadas;
  3. a atualização que não coube fica devendo, em vez de se perder.

O comportamento em si foi conferido no navegador, com a fila drenando.
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


def _corpo_de(js, nome):
    """Recorta o corpo de uma função, contando chaves."""
    i = js.index("function %s(" % nome)
    inicio = js.index("{", i)
    nivel, k = 0, inicio
    while k < len(js):
        if js[k] == "{":
            nivel += 1
        elif js[k] == "}":
            nivel -= 1
            if nivel == 0:
                return js[inicio : k + 1]
        k += 1
    raise AssertionError("função %s não fecha" % nome)


class TestOGatilho:
    def test_a_barra_de_status_atualiza_a_home(self):
        """
        `buscarStatus` roda a cada 2s e é o único lugar do front que sabe que a
        fila andou. Se a chamada sair dali, a home volta a esperar um F5.
        """
        corpo = _corpo_de(_ler(), "buscarStatus")
        assert "atualizarHomeSeCabe" in corpo, (
            "buscarStatus deixou de atualizar a home; sem isso a pessoa vê a "
            "análise terminar e continua com a tela vazia."
        )

    def test_atualiza_ao_terminar_e_durante_o_andamento(self):
        corpo = _corpo_de(_ler(), "buscarStatus")
        assert "atualizarHomeSeCabe('fim')" in corpo, "falta a atualização do fim da análise"
        assert "atualizarHomeSeCabe('andamento')" in corpo, (
            "falta a atualização durante a análise; sem ela as fotos só "
            "aparecem todas de uma vez, no fim."
        )

    def test_mostrar_o_resultado_nao_depende_das_notificacoes(self):
        """
        Quem desligou o aviso não pediu para a home ficar desatualizada. As
        duas coisas convivem no mesmo `if` original, e é fácil alguém juntá-las
        de novo sem perceber que são decisões diferentes.
        """
        corpo = _corpo_de(_ler(), "buscarStatus")
        i = corpo.index("atualizarHomeSeCabe('fim')")
        # a condição que governa essa chamada
        abre = corpo.rindex("if (", 0, i)
        condicao = corpo[abre : corpo.index(")", abre) + 1]
        assert "notificacoes" not in condicao, (
            "a atualização da home ficou presa à configuração de notificações: %r" % condicao
        )


class TestOsFreios:
    """
    Redesenhar a galeria reconstrói o container inteiro. Sem freio, isso
    aconteceria a cada 2 segundos, por baixo de uma janela aberta e no meio da
    leitura de uma busca.
    """

    def test_nao_redesenha_com_janela_aberta_nem_na_busca(self):
        corpo = _corpo_de(_ler(), "_homeEstaAparecendo")
        assert "_modaisAbertos()" in corpo, "sem esta checagem, redesenha por baixo de uma janela"
        assert "searchResultsView" in corpo, (
            "sem esta checagem, redesenha enquanto a pessoa lê os resultados"
        )

    def test_ha_intervalo_minimo_entre_atualizacoes(self):
        js = _ler()
        m = re.search(r"_ESPERA_ENTRE_ATUALIZACOES\s*=\s*(\d+)", js)
        assert m, "sumiu o intervalo mínimo entre atualizações"
        assert int(m.group(1)) >= 3000, (
            "intervalo curto demais (%sms): a barra bate a cada 2s e a galeria "
            "seria reconstruída quase toda vez." % m.group(1)
        )

    def test_o_fim_da_analise_ignora_o_intervalo(self):
        """A última atualização é a que não pode faltar."""
        corpo = _corpo_de(_ler(), "atualizarHomeSeCabe")
        assert "motivo !== 'fim'" in corpo, (
            "o fim da análise passou a respeitar o intervalo; a atualização "
            "que importa pode ser engolida por ele."
        )

    def test_a_rolagem_e_preservada(self):
        corpo = _corpo_de(_ler(), "atualizarHomeSeCabe")
        assert "scrollY" in corpo and "scrollTo" in corpo, (
            "sem guardar a rolagem, a página salta para o topo no meio da leitura"
        )


class TestADividaNaoSePerde:
    """
    Se a análise termina com uma janela aberta, não dá para redesenhar na hora.
    Voltar da busca passa por mostrarHome(), que recarrega; fechar uma janela
    não passa por lugar nenhum — era por aí que a home ficava velha.
    """

    def test_o_fim_que_nao_coube_fica_devendo(self):
        corpo = _corpo_de(_ler(), "atualizarHomeSeCabe")
        assert "_homeDeveAtualizar = true" in corpo, (
            "a atualização do fim da análise se perde quando há janela aberta"
        )

    def test_a_divida_e_paga_na_batida_seguinte(self):
        corpo = _corpo_de(_ler(), "buscarStatus")
        assert "_homeDeveAtualizar" in corpo, (
            "ninguém paga a atualização devida; a home fica velha até um F5"
        )

    def test_a_divida_e_quitada_ao_atualizar(self):
        corpo = _corpo_de(_ler(), "atualizarHomeSeCabe")
        assert "_homeDeveAtualizar = false" in corpo, (
            "a dívida nunca é quitada, e a home passa a redesenhar a cada batida"
        )


class TestVoltarDaBusca:
    def test_mostrar_home_recarrega_a_galeria(self):
        """
        É o outro caminho de volta, e o que já funcionava. Fixado porque a
        dívida acima foi desenhada contando com ele.
        """
        corpo = _corpo_de(_ler(), "mostrarHome")
        assert "carregarGaleria()" in corpo
