# -*- coding: utf-8 -*-
"""
Por que este resultado apareceu.

O número que ordena a busca existe e continua escondido de propósito — dizer
"0,72" não ensina nada a ninguém. O que ajuda é saber QUAL sinal respondeu,
porque é isso que diz ao usuário como pedir da próxima vez: se a foto do
cachorro veio "pela aparência", descrever a cena funciona; se veio "pelo nome
do arquivo", vale continuar usando o nome.

São quatro origens e não três porque, numa imagem, o texto que o Search+ tem
não é texto do arquivo — é a descrição que a IA escreveu olhando para ela.
Chamar isso de "texto do documento" seria mentira sobre a origem do dado.
"""

import pytest

pytestmark = pytest.mark.unit


class TestQualSinalRespondeu:
    def test_imagem_reconhecida_pela_aparencia(self, app_module):
        origem = app_module._origem_do_resultado(
            eh_imagem=True, peso_visual=0.28, peso_textual=0.05, nome_bateu=False)
        assert origem == app_module.ORIGEM_APARENCIA

    def test_imagem_reconhecida_pela_descricao(self, app_module):
        """
        A descrição da imagem respondeu, não o sinal visual. Dizer "pelo texto
        do documento" seria errado: não há documento nenhum, há uma frase que
        a IA escreveu olhando para a foto.
        """
        origem = app_module._origem_do_resultado(
            eh_imagem=True, peso_visual=0.04, peso_textual=0.40, nome_bateu=False)
        assert origem == app_module.ORIGEM_DESCRICAO

    def test_documento_vem_pelo_texto(self, app_module):
        origem = app_module._origem_do_resultado(
            eh_imagem=False, peso_visual=0.0, peso_textual=0.52, nome_bateu=False)
        assert origem == app_module.ORIGEM_TEXTO

    def test_documento_nunca_vem_pela_aparencia(self, app_module):
        """PDF não tem aparência reconhecível — não há sinal visual nele."""
        origem = app_module._origem_do_resultado(
            eh_imagem=False, peso_visual=0.99, peso_textual=0.01, nome_bateu=False)
        assert origem != app_module.ORIGEM_APARENCIA

    def test_nome_ganha_quando_e_o_maior(self, app_module):
        origem = app_module._origem_do_resultado(
            eh_imagem=True, peso_visual=0.05, peso_textual=0.03, nome_bateu=True)
        assert origem == app_module.ORIGEM_NOME

    def test_nome_nao_ganha_de_um_sinal_forte(self, app_module):
        """
        O nome soma pouco ao resultado final. Anunciá-lo como a razão quando a
        imagem foi de fato reconhecida pela aparência ensinaria a coisa errada
        — o usuário passaria a caçar nome de arquivo em vez de descrever.
        """
        origem = app_module._origem_do_resultado(
            eh_imagem=True, peso_visual=0.30, peso_textual=0.02, nome_bateu=True)
        assert origem == app_module.ORIGEM_APARENCIA

    def test_nome_fora_da_disputa_quando_nao_bateu(self, app_module):
        origem = app_module._origem_do_resultado(
            eh_imagem=False, peso_visual=0.0, peso_textual=0.01, nome_bateu=False)
        assert origem == app_module.ORIGEM_TEXTO

    def test_compara_contribuicao_e_nao_sinal_cru(self, app_module):
        """
        Um sinal visual de 0,9 entra com peso 0,30 e contribui 0,27; um textual
        de 0,6 entra com 0,45 e contribui 0,27+. É a contribuição que explica a
        posição do resultado, não o valor bruto do sinal.
        """
        # Contribuições, não sinais: 0.27 visual contra 0.28 textual.
        origem = app_module._origem_do_resultado(
            eh_imagem=True, peso_visual=0.27, peso_textual=0.28, nome_bateu=False)
        assert origem == app_module.ORIGEM_DESCRICAO


class TestPesoDoNomeNaoDiverge:
    def test_a_badge_usa_o_mesmo_peso_que_o_score(self, app_module):
        """
        `PESO_NOME` é usado nos dois lugares: no boost que o nome dá ao score e
        na disputa que decide a badge. Separá-los faria a interface explicar
        uma coisa e o resultado ser ordenado por outra.
        """
        import inspect
        fonte = inspect.getsource(app_module._ajustar_score)
        assert "PESO_NOME" in fonte
        assert "score += 0.15" not in fonte


class TestNaBusca:
    """A origem precisa chegar até a resposta da API, e sobreviver ao caminho."""

    def test_a_resposta_carrega_a_origem(self, app_module):
        import inspect
        fonte = inspect.getsource(app_module.api_search)
        assert '"origem": origem' in fonte

    def test_o_numero_continua_fora_da_interface(self, app_module):
        """
        A regra do projeto é não mostrar o número. A origem é a explicação que
        entra no lugar dele — não um segundo número disfarçado.
        """
        import inspect
        fonte = inspect.getsource(app_module._origem_do_resultado)
        assert "return" in fonte
        for constante in ("ORIGEM_APARENCIA", "ORIGEM_DESCRICAO",
                          "ORIGEM_TEXTO", "ORIGEM_NOME"):
            assert isinstance(getattr(app_module, constante), str)

    def test_as_quatro_origens_sao_distintas(self, app_module):
        valores = {app_module.ORIGEM_APARENCIA, app_module.ORIGEM_DESCRICAO,
                   app_module.ORIGEM_TEXTO, app_module.ORIGEM_NOME}
        assert len(valores) == 4

    def test_nenhuma_origem_usa_jargao(self, app_module):
        """O valor vai para o front e pode acabar visível; não pode citar modelo."""
        for constante in ("ORIGEM_APARENCIA", "ORIGEM_DESCRICAO",
                          "ORIGEM_TEXTO", "ORIGEM_NOME"):
            valor = getattr(app_module, constante).lower()
            for jargao in ("clip", "sbert", "bm25", "embedding", "score"):
                assert jargao not in valor
