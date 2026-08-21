# -*- coding: utf-8 -*-
"""
Extração de texto dos documentos.

É o passo do indexador que lê o disco, e a origem do defeito mais grave que o
projeto teve: um .txt contendo o byte NUL fazia o Postgres recusar o UPDATE, a
exceção subia no worker e a indexação inteira parava — em silêncio, com o status
exibindo "Ocioso".

Arquivo ilegível não pode derrubar nada: o contrato é devolver um texto de
fallback e seguir.
"""

import pytest

pytestmark = pytest.mark.unit


class TestExtracaoDeTexto:
    def test_le_txt_simples(self, app_module, tmp_path):
        arquivo = tmp_path / "nota.txt"
        arquivo.write_text("relatório de vendas de 2026", encoding="utf-8")
        assert "relatório" in app_module._extract_txt(str(arquivo))

    def test_le_csv(self, app_module, tmp_path):
        arquivo = tmp_path / "dados.csv"
        arquivo.write_text("nome,valor\ncachorro,10", encoding="utf-8")
        assert "cachorro" in app_module._extract_txt(str(arquivo))

    def test_arquivo_vazio_devolve_string(self, app_module, tmp_path):
        arquivo = tmp_path / "vazio.txt"
        arquivo.write_text("", encoding="utf-8")
        assert app_module._extract_txt(str(arquivo)) == ""

    def test_arquivo_inexistente_cai_no_fallback(self, app_module, tmp_path):
        """Sem exceção: o worker precisa continuar com os próximos arquivos."""
        resultado = app_module._extract_txt(str(tmp_path / "nao_existe.txt"))
        assert "nao_existe.txt" in resultado

    def test_encoding_invalido_nao_estoura(self, app_module, tmp_path):
        """Bytes que não são UTF-8 são ignorados, não derrubam a extração."""
        arquivo = tmp_path / "latin.txt"
        arquivo.write_bytes("relatório".encode("latin-1"))
        assert isinstance(app_module._extract_txt(str(arquivo)), str)

    def test_arquivo_grande_e_truncado(self, app_module, tmp_path):
        """A descrição vai para o embedding; texto sem limite estouraria o modelo."""
        arquivo = tmp_path / "grande.txt"
        arquivo.write_text("palavra " * 50_000, encoding="utf-8")
        assert len(app_module._extract_txt(str(arquivo))) <= 6000


class TestByteNulNaExtracao:
    """
    O NUL sobrevive à leitura do arquivo — quem tem de removê-lo é
    `_limpar_texto_para_banco`, aplicado no worker antes do UPDATE.
    """

    def test_txt_com_nul_e_lido_sem_estourar(self, app_module, tmp_path):
        arquivo = tmp_path / "corrompido.txt"
        arquivo.write_bytes(b"antes\x00depois")
        assert isinstance(app_module._extract_txt(str(arquivo)), str)

    def test_saneamento_deixa_o_texto_gravavel(self, app_module, tmp_path):
        arquivo = tmp_path / "corrompido.txt"
        arquivo.write_bytes(b"relatorio\x00de vendas")
        texto = app_module._limpar_texto_para_banco(app_module._extract_txt(str(arquivo)))
        assert "\x00" not in texto, "com NUL, o Postgres recusa o UPDATE e o worker morre"
        assert "relatorio" in texto


class TestRoteamentoPorExtensao:
    def test_txt_vai_para_o_extrator_de_texto(self, app_module, tmp_path):
        arquivo = tmp_path / "a.txt"
        arquivo.write_text("conteúdo de teste", encoding="utf-8")
        assert "conteúdo" in app_module._analyze_file(str(arquivo), "txt")

    def test_extensao_desconhecida_devolve_rotulo(self, app_module, tmp_path):
        """Sem extrator, sobra o nome — que ainda é buscável."""
        arquivo = tmp_path / "planilha.xyz"
        arquivo.write_text("x", encoding="utf-8")
        resultado = app_module._analyze_file(str(arquivo), "xyz")
        assert "planilha.xyz" in resultado

    def test_pdf_corrompido_nao_estoura(self, app_module, tmp_path):
        arquivo = tmp_path / "falso.pdf"
        arquivo.write_bytes(b"isto nao e um PDF de verdade")
        assert isinstance(app_module._extract_pdf(str(arquivo)), str)

    def test_docx_corrompido_nao_estoura(self, app_module, tmp_path):
        arquivo = tmp_path / "falso.docx"
        arquivo.write_bytes(b"nem isto e um DOCX")
        assert isinstance(app_module._extract_docx(str(arquivo)), str)


class TestDescricoesDeFallback:
    """
    Fallback marca `processado = 0`: o arquivo fica fora da busca e entra na
    fila do "Re-analisar". O prefixo é o sinal disso.
    """

    def test_prefixos_de_fallback_declarados(self, app_module):
        assert "PDF:" in app_module._DESCRICOES_RUINS
        assert "Texto:" in app_module._DESCRICOES_RUINS

    def test_fallback_de_arquivo_ausente_casa_com_o_prefixo(self, app_module, tmp_path):
        resultado = app_module._extract_txt(str(tmp_path / "sumiu.txt"))
        assert any(resultado.startswith(p) for p in app_module._DESCRICOES_RUINS)
