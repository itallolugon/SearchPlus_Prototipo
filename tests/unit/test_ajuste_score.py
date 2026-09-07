# -*- coding: utf-8 -*-
"""
Regras de ajuste do score da busca.

`_ajustar_score` é o filtro determinístico que roda ANTES do julgamento do
Claude: rejeita combinações impossíveis (retorna None) e reforça ou penaliza as
demais. É a camada mais barata do ranking e a que decide se um arquivo chega a
ser avaliado — por isso cada regra tem teste próprio.
"""

import pytest

pytestmark = pytest.mark.unit

_FOTO_CACHORRO = """- Estilo: foto
- O que é: um cachorro correndo
- Pessoas: nenhuma
- Animais: cachorro (beagle)
- Objetos: bola
- Ações: correndo
- Texto: nenhum
- Tags: foto, cachorro"""

_FOTO_MULHER = """- Estilo: foto
- O que é: retrato de uma mulher
- Pessoas: mulher jovem
- Animais: nenhum
- Objetos: cadeira
- Ações: sorrindo
- Texto: nenhum
- Tags: foto, mulher, retrato"""

_DESENHO_CACHORRO = """- Estilo: desenho, cartoon
- O que é: desenho de um cachorro
- Pessoas: nenhuma
- Animais: cachorro
- Objetos: osso
- Ações: sentado
- Texto: nenhum
- Tags: desenho, cartoon, cachorro"""

BASE = 0.5


@pytest.fixture()
def ajustar(app_module):
    """Aplica a regra já normalizando descrição e nome, como a busca faz."""

    def _aplicar(query: str, descricao: str, nome: str = "arquivo.jpg"):
        return app_module._ajustar_score(
            BASE,
            app_module._analisar_query(query),
            app_module._normalizar(descricao),
            app_module._normalizar(nome),
        )

    return _aplicar


class TestRejeicoes:
    """None significa "impossível" — o item é descartado antes do re-rank."""

    def test_pessoa_pedida_em_imagem_sem_pessoas(self, ajustar):
        assert ajustar("mulher", _FOTO_CACHORRO) is None

    def test_animal_pedido_em_imagem_sem_animais(self, ajustar):
        assert ajustar("cachorro", _FOTO_MULHER) is None

    def test_genero_oposto(self, ajustar):
        """Procurar 'homem' não pode devolver o retrato de uma mulher."""
        assert ajustar("homem", _FOTO_MULHER) is None

    def test_genero_correto_nao_rejeita(self, ajustar):
        assert ajustar("mulher", _FOTO_MULHER) is not None


class TestReforcos:
    def test_animal_correspondente_recebe_reforco(self, ajustar):
        assert ajustar("cachorro", _FOTO_CACHORRO) > BASE

    def test_pessoa_correspondente_recebe_reforco(self, ajustar):
        assert ajustar("mulher", _FOTO_MULHER) > BASE

    def test_objeto_citado_recebe_reforco(self, ajustar):
        assert ajustar("bola", _FOTO_CACHORRO) > BASE

    def test_nome_do_arquivo_pesa(self, ajustar):
        """Quem lembra do nome do arquivo tem que achá-lo no topo."""
        com_nome = ajustar("cachorro", _FOTO_CACHORRO, "cachorro_praia.jpg")
        sem_nome = ajustar("cachorro", _FOTO_CACHORRO, "IMG_0042.jpg")
        assert com_nome > sem_nome


class TestEstilo:
    """Pedir 'desenho' ou 'foto' reordena, mas nunca elimina."""

    def test_desenho_pedido_favorece_desenho(self, ajustar):
        assert ajustar("desenho de cachorro", _DESENHO_CACHORRO) > BASE

    def test_desenho_pedido_penaliza_foto(self, ajustar):
        resultado = ajustar("desenho de cachorro", _FOTO_CACHORRO)
        assert resultado is not None, "penalizar sim, eliminar não"
        assert resultado < BASE

    def test_foto_pedida_favorece_foto(self, ajustar):
        assert ajustar("foto de cachorro", _FOTO_CACHORRO) > BASE

    def test_foto_pedida_penaliza_desenho(self, ajustar):
        resultado = ajustar("foto de cachorro", _DESENHO_CACHORRO)
        assert resultado is not None
        assert resultado < BASE

    def test_desenho_de_animal_conta_como_animal(self, ajustar):
        """
        Regra central do produto: um cachorro de cartoon é um cachorro. Buscar
        'cachorro' não pode rejeitar o desenho.
        """
        assert ajustar("cachorro", _DESENHO_CACHORRO) is not None


class TestNeutralidadeEBordas:
    def test_query_sem_relacao_mantem_o_score(self, ajustar):
        """Sem regra aplicável, o score do motor passa intacto."""
        assert ajustar("xyzabc", _FOTO_CACHORRO) == BASE

    def test_descricao_vazia_nao_estoura(self, ajustar):
        resultado = ajustar("cachorro", "")
        assert resultado is None or isinstance(resultado, float)

    @pytest.mark.parametrize("entrada", [0.0, 1.0])
    def test_score_limite_nao_estoura(self, app_module, entrada):
        resultado = app_module._ajustar_score(
            entrada,
            app_module._analisar_query("cachorro"),
            app_module._normalizar(_FOTO_CACHORRO),
            "dog.jpg",
        )
        assert resultado is None or isinstance(resultado, float)

    def test_resultado_permanece_numerico(self, ajustar):
        resultado = ajustar("cachorro", _FOTO_CACHORRO)
        assert isinstance(resultado, float)
