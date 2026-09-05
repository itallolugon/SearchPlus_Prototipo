# -*- coding: utf-8 -*-
"""
Os ícones do front.

O front usava emoji como ícone. Três problemas, e nenhum deles aparece na
máquina de quem escreveu:

  - a cor vem da fonte do sistema, então o ícone ignorava o tema e a cor de
    destaque escolhida pelo usuário, e não dava para corrigir o contraste dele
    como corrigimos o do texto;
  - o desenho muda de máquina para máquina — Windows, Android e cada navegador
    desenham o mesmo código de um jeito;
  - em fonte mais antiga, alguns simplesmente não existem e viram um retângulo
    vazio.

Hoje são símbolos SVG definidos uma vez no `index.html` e referenciados por
`<use href="#ic-nome">`, com o traço em `currentColor`.

Este arquivo cobre os dois jeitos de a troca se desfazer sem ninguém perceber:

  1. alguém acrescenta um emoji novo num texto de tela;
  2. alguém referencia um ícone com o nome errado.

O (2) é o mais traiçoeiro: `<use>` para um id inexistente **não é erro**. Não
quebra o carregamento, não vai para o console, não some do DOM. O botão
simplesmente aparece sem desenho, e só quem abrir aquela tela específica vai
notar.
"""

import io
import os
import re
import unicodedata

import pytest

pytestmark = pytest.mark.unit

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INDEX = os.path.join(RAIZ, "index.html")
SCRIPT = os.path.join(RAIZ, "script.js")
ESTILO = os.path.join(RAIZ, "style.css")

# Pontuação tipográfica e caracteres de desenho de caixa que aparecem em texto
# e em comentário. São monocromáticos e legítimos — o alvo aqui é emoji.
PERMITIDOS = set("—–…“”‘’ «»·•×─→←")


def _eh_emoji(ch: str) -> bool:
    if ch in PERMITIDOS or ord(ch) < 0x2000:
        return False
    # "So" = símbolo de outra natureza (onde caem os pictogramas); acima de
    # U+1F000 é o território dos emoji propriamente ditos.
    return unicodedata.category(ch) in ("So", "Sk", "Cf") or ord(ch) >= 0x1F000


def _ler(caminho):
    return io.open(caminho, encoding="utf-8").read()


def _emojis_em(caminho):
    """Devolve (linha, caractere) de cada emoji encontrado."""
    achados = []
    for n, linha in enumerate(io.open(caminho, encoding="utf-8"), 1):
        for ch in linha:
            if _eh_emoji(ch):
                achados.append((n, "U+%04X" % ord(ch)))
    return achados


class TestSemEmoji:
    @pytest.mark.parametrize("arquivo", [INDEX, SCRIPT, ESTILO])
    def test_o_front_nao_tem_emoji(self, arquivo):
        achados = _emojis_em(arquivo)
        assert achados == [], (
            "%s voltou a ter emoji nas linhas %s. Use um símbolo do sprite: "
            "iconeHTML('nome') nos templates, icone('nome') quando o rótulo ao "
            "lado vier de dado do usuário." % (os.path.basename(arquivo), achados[:8])
        )


class TestSprite:
    def test_todo_icone_usado_existe(self):
        """
        Um `<use href="#ic-inexistente">` não dá erro em lugar nenhum: o botão
        só aparece vazio. Este teste é o único lugar onde o engano aparece.
        """
        definidos = set(re.findall(r'<symbol id="ic-([a-z-]+)"', _ler(INDEX)))
        assert definidos, "o sprite sumiu do index.html"

        js = _ler(SCRIPT)
        usados = set(re.findall(r'href="#ic-([a-z-]+)"', _ler(INDEX)))
        usados |= set(re.findall(r"icone\(\s*'([a-z-]+)'", js))
        usados |= set(re.findall(r"iconeHTML\(\s*'([a-z-]+)'", js))
        usados |= set(re.findall(r"rotularCom\([^,]+,\s*'([a-z-]+)'", js))
        usados |= set(re.findall(r"icone:\s*'([a-z-]+)'", js))
        # Escolhas em ternário: rotularCom(el, x ? 'a' : 'b', ...)
        for par in re.findall(r"\?\s*'([a-z-]+)'\s*:\s*'([a-z-]+)'", js):
            usados |= set(par)

        # O ternário acima também pega strings que não são nome de ícone; só
        # interessa o que se parece com um id do sprite.
        faltando = sorted(n for n in usados - definidos if n in _CANDIDATOS_DE_ICONE(js))
        assert faltando == [], (
            "ícone referenciado que não existe no sprite do index.html: %s" % faltando
        )

    def test_ids_do_sprite_sao_unicos(self):
        ids = re.findall(r'<symbol id="(ic-[a-z-]+)"', _ler(INDEX))
        repetidos = sorted({i for i in ids if ids.count(i) > 1})
        assert repetidos == [], (
            "id repetido no sprite: %s. O `<use>` resolve para o primeiro, "
            "então o segundo desenho nunca aparece." % repetidos
        )

    def test_os_simbolos_tem_o_mesmo_grid(self):
        """
        Um símbolo com viewBox diferente sai de escala no meio dos outros — é
        o tipo de coisa que faz um conjunto parecer figurinha avulsa.
        """
        fora = [
            (i, vb)
            for i, vb in re.findall(r'<symbol id="(ic-[a-z-]+)" viewBox="([^"]+)"', _ler(INDEX))
            if vb != "0 0 24 24"
        ]
        assert fora == [], "símbolo fora do grid 24x24: %s" % fora


class TestContratoDosHelpers:
    def test_o_helper_de_elemento_existe_para_dado_do_usuario(self):
        """
        `rotularCom` monta ícone + texto pelo DOM. Ele existe para que um nome
        de pasta ou de coleção nunca precise passar por innerHTML.
        """
        js = _ler(SCRIPT)
        assert "function rotularCom(" in js
        assert "createTextNode" in js, (
            "rotularCom precisa inserir o rótulo como TEXTO; montar com "
            "innerHTML abriria injeção através de um nome de pasta."
        )

    def test_o_sprite_e_inline_e_nao_um_arquivo_externo(self):
        """O app roda offline; um .svg externo seria uma requisição a mais."""
        html = _ler(INDEX)
        assert '<svg class="sprite-icones"' in html
        assert 'href="#ic-' in html or "iconeHTML" in _ler(SCRIPT)

    def test_o_traco_segue_a_cor_do_texto(self):
        css = _ler(ESTILO)
        bloco = css[css.index(".ic {") : css.index(".ic {") + 400]
        assert "currentColor" in bloco, (
            "sem currentColor o ícone deixa de acompanhar o tema, que é a "
            "razão de ter saído do emoji."
        )


def _CANDIDATOS_DE_ICONE(js):
    """
    Nomes que aparecem em posição de ícone. Serve para não acusar strings de
    ternário que nada têm a ver com o sprite (ex.: `x ? 'true' : 'false'`).
    """
    nomes = set()
    for chamada in re.findall(r"(?:icone|iconeHTML)\(([^)]*)\)", js):
        nomes |= set(re.findall(r"'([a-z-]+)'", chamada))
    for chamada in re.findall(r"rotularCom\(([^;]*?)\)\s*;", js, re.S):
        nomes |= set(re.findall(r"'([a-z-]+)'", chamada))
    return nomes
