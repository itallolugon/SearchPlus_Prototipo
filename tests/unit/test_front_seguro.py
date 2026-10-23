# -*- coding: utf-8 -*-
"""
Onboarding, scripts de CDN e envio de imagem no front.

A lista de pastas do onboarding escapou do teste de HTML que já existia
(test_html_do_front.py) por dois motivos que valem registrar: a variável se
chamava `p`, e não `caminho`, e o template ocupava várias linhas — o teste olha
o nome do campo e só a linha do `innerHTML`. O caminho ia cru para o HTML e
para um `onclick` com o escape na ordem errada.

Junto, dois defeitos de funcionamento da mesma tela: o botão de remover pasta
tinha 0x0 px (ficou sem conteúdo na troca dos emoji) e as escolhas de foco,
intensidade e janela, que ficam ABAIXO da lista, não chegavam às pastas já
adicionadas.
"""

import io
import os
import re

import pytest

pytestmark = pytest.mark.unit

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(RAIZ, "script.js")
INDEX = os.path.join(RAIZ, "index.html")


def _ler(caminho):
    return io.open(caminho, encoding="utf-8").read()


def _sem_comentarios(js):
    js = re.sub(r"/\*.*?\*/", " ", js, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", " ", js)


def _corpo(js, assinatura):
    """Texto da função, da assinatura até a próxima função de topo."""
    i = js.index(assinatura)
    fim = re.search(r"\n(async )?function ", js[i + len(assinatura) :])
    return js[i : i + len(assinatura) + (fim.start() if fim else len(js))]


class TestListaDePastasDoOnboarding:
    def test_caminho_entra_como_texto(self):
        corpo = _corpo(
            _sem_comentarios(_ler(SCRIPT)), "async function atualizarListaPastasOnboarding("
        )
        # setAttribute e textContent com ${...} são seguros; innerHTML, não.
        assert not re.search(r"innerHTML\s*=[^;]*\$\{", corpo, flags=re.S), (
            "o caminho voltou a ir cru para dentro de HTML"
        )
        assert 'onclick="' not in corpo, "onclick de texto com caminho dentro: monte pelo DOM"
        assert "textContent = p" in corpo

    def test_botao_de_remover_tem_conteudo_e_nome(self):
        """Sem ícone, o botão tinha 0x0 px; sem aria-label, não tinha nome."""
        corpo = _corpo(
            _sem_comentarios(_ler(SCRIPT)), "async function atualizarListaPastasOnboarding("
        )
        assert "icone('x')" in corpo
        assert "aria-label" in corpo


class TestEscolhasDoOnboarding:
    def test_janela_customizada_e_respeitada_ao_adicionar(self):
        corpo = _corpo(_sem_comentarios(_ler(SCRIPT)), "async function adicionarPastaOnboarding(")
        assert "getJanelaValue('ob')" in corpo
        assert "janela_processamento: _obJanela" not in corpo

    def test_avancar_aplica_as_escolhas_as_pastas(self):
        js = _sem_comentarios(_ler(SCRIPT))
        avancar = _corpo(js, "async function irParaOnboardingStep2(")
        assert "await aplicarEscolhasDoOnboarding()" in avancar
        aplicar = _corpo(js, "async function aplicarEscolhasDoOnboarding(")
        assert "/api/folders/update_config" in aplicar
        for campo in ("prioridades", "perfil_analise", "janela_processamento"):
            assert campo in aplicar


class TestRecursosDeCdn:
    def test_script_e_css_de_cdn_tem_integrity(self):
        """
        Sem `integrity`, quem alterasse o arquivo no CDN rodaria script na
        origem do app — que lê arquivos locais pela API. O Google Fonts fica de
        fora porque o CSS dele muda por navegador e não tem hash fixo.
        """
        html = _ler(INDEX)
        externos = re.findall(r"<(?:script|link)\b[^>]*https://cdnjs[^>]*>", html, flags=re.S)
        assert externos, "premissa: o cropper vem do cdnjs"
        for tag in externos:
            assert 'integrity="sha384-' in tag, f"sem integrity: {tag[:90]}"
            assert 'crossorigin="anonymous"' in tag, f"sem crossorigin: {tag[:90]}"

    def test_aba_tem_icone(self):
        """Sem <link rel="icon"> o navegador pede /favicon.ico e loga um 404."""
        assert '<link rel="icon"' in _ler(INDEX)


class TestBuscaPorImagem:
    def test_imagem_grande_e_recusada_antes_de_enviar(self):
        corpo = _corpo(_sem_comentarios(_ler(SCRIPT)), "function _carregarArquivoImagem(")
        assert "file.size > 20 * 1024 * 1024" in corpo

    def test_erro_geral_do_servidor_aparece(self):
        """`error` é a chave do 401 e do 413; só `erro` deixava a tela muda."""
        corpo = _corpo(_sem_comentarios(_ler(SCRIPT)), "async function _renderBuscaVisual(")
        assert "d.erro || d.error" in corpo
