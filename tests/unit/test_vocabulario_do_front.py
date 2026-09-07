# -*- coding: utf-8 -*-
"""
Um nome por conceito, na tela.

A palavra "pasta" chegou a nomear cinco coisas diferentes ao mesmo tempo: a
pasta do usuário no computador, a pasta que o app cria para uma coleção, essa
mesma chamada de "vinculada" noutro lugar, onde ela é criada, e a subpasta por
mês da exportação.

O estrago não era estético. O aviso "A pasta vinculada não está mais no lugar"
fala de uma pasta que o APP criou, mas se lê como se as fotos do usuário
tivessem sumido — e a pessoa vai correndo conferir o computador.

    pasta monitorada / importada / indexada   →  pasta do computador
    pasta exportada / gerada / vinculada      →  pasta da coleção
    indexar / indexação                       →  analisar / análise

Este arquivo existe por causa de um risco específico, que é maior que o de
errar uma frase: aplicar a troca **pela metade**. Dois vocabulários convivendo
é pior que o vocabulário ruim de antes, porque aí nem a inconsistência tem
regra. Sem um teste, a próxima feature reintroduz "pasta vinculada" sem
ninguém notar.

O que este teste NÃO cobre, de propósito: nome de coluna do banco
(`pasta_vinculada`), campo da API (`pastas_ativas`), id de elemento
(`pastasExportadasModal`) e nome de função (`abrirPastaExportada`). Renomear
isso quebraria a paridade entre servidor real, mock e documentação em troca de
zero benefício — o usuário nunca vê o nome de uma coluna.
"""

import io
import os
import re

import pytest

pytestmark = pytest.mark.unit

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INDEX = os.path.join(RAIZ, "index.html")
SCRIPT = os.path.join(RAIZ, "script.js")

# Termos que saíram de circulação, com o que passou a valer.
APOSENTADOS = {
    "pasta monitorada": "pasta do computador",
    "pastas monitoradas": "pastas do computador",
    "pasta vinculada": "pasta da coleção",
    "pastas vinculadas": "pastas da coleção",
    "pasta exportada": "pasta da coleção",
    "pastas exportadas": "pastas da coleção",
    "importar nova pasta": "adicionar pasta",
    "gerenciar pastas": "pastas do computador",
}


def _ler(caminho):
    return io.open(caminho, encoding="utf-8").read()


def _sem_comentarios(fonte):
    """
    Tira comentário de bloco e de linha. Comentário fala do código e cita
    livremente o nome do campo do banco; acusá-lo seria ruído.
    """
    fonte = re.sub(r"/\*.*?\*/", " ", fonte, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", " ", fonte)


def _textos_de_tela(fonte):
    """
    Toda string literal do arquivo, e o texto entre tags no HTML.

    A primeira versão deste extrator enumerava os pontos de chamada
    (`textContent = `, `toastErro(`, …) e deixou passar exatamente o caso mais
    grave — `toastErro(d.error || 'A pasta vinculada não está mais no lugar.')`,
    onde a string não é o primeiro argumento. Enumerar sítios de chamada nunca
    termina; olhar toda string literal, sim.

    O falso positivo que isso poderia trazer não se materializa: as frases
    aposentadas têm espaço no meio ("pasta vinculada"), e o campo do banco não
    (`pasta_vinculada`). Comentários ficam de fora à parte.
    """
    fonte = _sem_comentarios(fonte)
    t = []
    t += re.findall(r"'([^'\n]{4,300})'", fonte)
    t += re.findall(r'"([^"\n]{4,300})"', fonte)
    t += re.findall(r"`([^`]{4,300})`", fonte)
    t += re.findall(r">([^<>{}]{4,300})<", fonte)

    # O que está dentro de `${...}` é código, não texto: `${t.indexados}` é o
    # nome de um campo da API, e o usuário lê o que sai dele, não ele. A
    # segunda passada trata a captura que parou no meio de um template e
    # deixou um `${` sem fechar — removidos os balanceados, o que sobrar a
    # partir de um `${` é resto de expressão, nunca texto.
    limpos = []
    for x in t:
        x = re.sub(r"\$\{[^{}]*\}", " ", x)
        x = re.sub(r"\$\{.*$", " ", x)
        limpos.append(" ".join(x.split()))
    return limpos


class TestVocabularioUnico:
    @pytest.mark.parametrize("arquivo", [INDEX, SCRIPT])
    def test_nenhum_termo_aposentado_na_tela(self, arquivo):
        textos = _textos_de_tela(_ler(arquivo))
        achados = []
        for frase in textos:
            baixo = frase.lower()
            for velho, novo in APOSENTADOS.items():
                if velho in baixo:
                    achados.append("%r → use %r em: %s" % (velho, novo, frase[:70]))
        assert achados == [], "%s voltou a usar vocabulário aposentado:\n  %s" % (
            os.path.basename(arquivo),
            "\n  ".join(achados[:6]),
        )

    def test_os_dois_conceitos_de_pasta_estao_na_tela(self):
        """
        A troca só vale se os nomes novos existirem de fato. Um teste que só
        proíbe palavra passaria com a interface inteira apagada.
        """
        tudo = " ".join(_textos_de_tela(_ler(INDEX)) + _textos_de_tela(_ler(SCRIPT)))
        assert "pasta do computador" in tudo.lower(), "sumiu o nome da pasta do usuário"
        assert "pasta da coleção" in tudo.lower(), "sumiu o nome da pasta criada pelo app"


class TestJargaoInterno:
    """
    Nome de tecnologia e termo de sistema não vão para a tela. Já valia para
    modelo de IA (RF-176); "indexar" é da mesma família — o usuário entende
    "analisar", que é o que ele vê acontecendo.
    """

    PROIBIDOS = ["indexação", "indexando", "indexado", "indexados", "reindex"]

    @pytest.mark.parametrize("arquivo", [INDEX, SCRIPT])
    def test_sem_jargao_de_indexacao(self, arquivo):
        achados = [
            "%r em: %s" % (p, frase[:70])
            for frase in _textos_de_tela(_ler(arquivo))
            for p in self.PROIBIDOS
            if p in frase.lower()
        ]
        assert achados == [], (
            "%s usa jargão de sistema na tela (prefira analisar/análise):\n  %s"
            % (os.path.basename(arquivo), "\n  ".join(achados[:6]))
        )


class TestEscopoDaTroca:
    """
    O limite que impede isto de virar uma reforma: o vocabulário mudou na tela,
    e SÓ na tela. Se alguém "terminar o serviço" renomeando campo de API, a
    paridade com o mock e a documentação quebra — e o usuário não ganha nada.
    """

    def test_o_campo_da_api_continua_o_mesmo(self):
        js = _ler(SCRIPT)
        assert "pasta_vinculada" in js, (
            "o campo da API foi renomeado junto com o texto; isso quebra a "
            "paridade com o backend e o mock, sem benefício para quem usa."
        )

    def test_o_id_do_modal_continua_o_mesmo(self):
        assert 'id="pastasExportadasModal"' in _ler(INDEX)
