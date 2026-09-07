# -*- coding: utf-8 -*-
"""
Nome de arquivo não pode virar HTML nem código.

Os nomes exibidos vêm de arquivos do disco. Parecem inofensivos porque são "do
próprio usuário", mas basta receber um arquivo por e-mail, pendrive ou pasta
compartilhada para o nome deixar de ser confiável.

O caso que existiu neste projeto, nos cards de "recentes":

    innerHTML += `<div onclick="abrirPainelPeloNome('${r.nome}')">
                  <p>${r.nome}</p></div>`

Dois furos na mesma linha, os dois confirmados no navegador antes da correção:

  - `Ana's foto.jpg` — apóstrofo comum em nome — fechava a string do onclick e
    o card parava de abrir (SyntaxError);
  - um nome contendo `<img src=x onerror=...>` executava o script.

A correção não foi escapar, foi montar pelo DOM: `textContent` não interpreta
HTML, e um `onclick` que é função de verdade não tem como ser fechado por
aspas no meio de um nome.
"""

import io
import os
import re

import pytest

pytestmark = pytest.mark.unit

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(RAIZ, "script.js")

# Campos que carregam texto que o app não escreveu: nome de arquivo, caminho,
# descrição gerada, nome de coleção, o que a pessoa digitou na busca.
DE_FORA = ["nome", "caminho", "descricao", "trecho", "rotulo", "colecao", "consulta", "termo"]


def _ler():
    return io.open(SCRIPT, encoding="utf-8").read()


def _sem_comentarios(js):
    js = re.sub(r"/\*.*?\*/", " ", js, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", " ", js)


class TestAtributoDeEvento:
    def test_nenhum_onclick_de_texto_recebe_dado_de_fora(self):
        """
        `onclick="f('${algo}')"` dentro de um template é o pior dos dois
        mundos: o dado atravessa HTML e depois JavaScript, e escapar para os
        dois ao mesmo tempo quase nunca sai certo. Use um handler de verdade.
        """
        js = _sem_comentarios(_ler())
        achados = []
        for m in re.finditer(r'on\w+\s*=\s*"[^"]*\$\{([^}]{1,80})\}', js):
            campo = m.group(1)
            if any(p in campo.lower() for p in DE_FORA):
                linha = js[: m.start()].count("\n") + 1
                achados.append("linha %d: ${%s}" % (linha, campo.strip()))
        assert achados == [], (
            "dado de fora dentro de atributo de evento:\n  %s\n"
            "Monte o elemento pelo DOM e use addEventListener/elemento.onclick."
            % "\n  ".join(achados)
        )


class TestTextoVisivel:
    def test_nome_de_arquivo_nao_entra_cru_em_innerHTML(self):
        """
        O alvo aqui é o texto que o usuário lê. Atributos como `alt` e `title`
        já passam por _attr(); o corpo do elemento é que ficou de fora.
        """
        js = _sem_comentarios(_ler())
        achados = []
        for m in re.finditer(r"(innerHTML|insertAdjacentHTML)[^\n]*", js):
            trecho = m.group(0)
            # `>${...}<` é conteúdo de elemento, não valor de atributo
            for campo in re.findall(r">\s*\$\{([^}]{1,60})\}", trecho):
                limpo = campo.strip()
                if any(p in limpo.lower() for p in DE_FORA) and "_attr(" not in limpo:
                    linha = js[: m.start()].count("\n") + 1
                    achados.append("linha %d: >${%s}<" % (linha, limpo))
        assert achados == [], (
            "nome/descrição indo cru para dentro de HTML:\n  %s\n"
            "Use textContent, ou _attr() se precisar mesmo montar a string." % "\n  ".join(achados)
        )


class TestOsCardsDeRecentes:
    """O ponto exato onde o furo existia."""

    def test_popular_dashboard_monta_pelo_dom(self):
        # Sem comentários: o próprio comentário desta função cita a linha
        # antiga para explicar o que não fazer, e acusá-lo seria absurdo.
        js = _sem_comentarios(_ler())
        i = js.index("function popularDashboard(")
        corpo = js[i : js.index("\nfunction ", i + 10)]
        assert "innerHTML" not in corpo, (
            "popularDashboard voltou a usar innerHTML; um apóstrofo no nome do "
            "arquivo quebra o card e um `<` injeta HTML."
        )
        assert "textContent" in corpo, "o nome do arquivo precisa entrar como texto"

    def test_o_clique_leva_o_indice_e_nao_o_nome(self):
        """
        Procurar o arquivo pelo nome depois do clique abria o errado quando
        duas pastas tinham arquivos de mesmo nome. O índice não tem esse
        problema, e ainda tira o nome do caminho do código.
        """
        js = _sem_comentarios(_ler())
        assert "abrirPainelPeloNome" not in js, (
            "voltou a resolver o clique pelo nome do arquivo; nomes se repetem "
            "entre pastas e o painel abre o item errado."
        )
