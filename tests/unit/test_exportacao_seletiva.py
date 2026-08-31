# -*- coding: utf-8 -*-
"""
Exportação seletiva: tipo, nome, tamanho e organização.

Exportava-se a coleção inteira, com os nomes originais, tamanho original e tudo
numa pasta só. Isso serve para levar as fotos para um pendrive; não serve para
entregar um trabalho, mandar por e-mail ou organizar um arquivo.

Quatro escolhas, na ordem de complexidade que o backlog pediu:

    tipos                só imagens, só documentos, ou tudo
    padrao_nome          renomeação em lote com marcadores
    largura_max          redimensionamento na saída
    subpastas_por_data   organização em subpastas
"""

import os
from datetime import datetime

import pytest

pytestmark = pytest.mark.unit


def _arquivo(nome, tipo, data=None):
    return {"nome": nome, "tipo": tipo, "caminho": f"C:/x/{nome}",
            "data_adicionado": data}


class TestFiltroPorTipo:
    def test_so_imagens(self, app_module):
        arquivos = [_arquivo("a.jpg", "jpg"), _arquivo("b.pdf", "pdf"),
                    _arquivo("c.png", "png")]
        saida = app_module._filtrar_por_tipo(arquivos, "imagens")
        assert [a["nome"] for a in saida] == ["a.jpg", "c.png"]

    def test_so_documentos(self, app_module):
        """Vídeo e áudio não são documento — são mídia."""
        arquivos = [_arquivo("a.jpg", "jpg"), _arquivo("b.pdf", "pdf"),
                    _arquivo("c.mp4", "mp4"), _arquivo("d.docx", "docx")]
        saida = app_module._filtrar_por_tipo(arquivos, "documentos")
        assert [a["nome"] for a in saida] == ["b.pdf", "d.docx"]

    def test_tudo_nao_filtra(self, app_module):
        arquivos = [_arquivo("a.jpg", "jpg"), _arquivo("b.pdf", "pdf")]
        assert len(app_module._filtrar_por_tipo(arquivos, "tudo")) == 2

    def test_tipo_em_maiuscula(self, app_module):
        """O tipo vem do nome do arquivo e pode chegar em qualquer caixa."""
        assert len(app_module._filtrar_por_tipo(
            [_arquivo("A.JPG", "JPG")], "imagens")) == 1


class TestPadraoDeNome:
    def test_padrao_vazio_mantem_o_nome(self, app_module):
        """O comportamento de sempre, para quem não pediu nada."""
        assert app_module._nome_exportado("", "foto.jpg", 1, "Viagem", None) == "foto.jpg"

    def test_numeracao_com_zeros(self, app_module):
        """
        Sem zeros à esquerda, o Explorer ordena 1, 10, 11, 2 — e a numeração
        que existia para preservar a ordem faz o contrário.
        """
        assert app_module._nome_exportado("{n}", "foto.jpg", 7, "V", None) == "007.jpg"
        assert app_module._nome_exportado("{n}", "foto.jpg", 42, "V", None) == "042.jpg"

    def test_combina_marcadores(self, app_module):
        saida = app_module._nome_exportado(
            "{colecao}_{n}_{nome}", "praia.jpg", 3, "Viagem", None)
        assert saida == "Viagem_003_praia.jpg"

    def test_data_no_nome(self, app_module):
        saida = app_module._nome_exportado(
            "{data}_{nome}", "foto.jpg", 1, "V", datetime(2026, 8, 31))
        assert saida == "2026-08-31_foto.jpg"

    def test_sem_data_o_marcador_some(self, app_module):
        saida = app_module._nome_exportado("{data}_{nome}", "foto.jpg", 1, "V", None)
        assert saida.endswith("foto.jpg")

    def test_a_extensao_nunca_vem_do_padrao(self, app_module):
        """
        Trocar a extensão não converte o arquivo — só faz o sistema abrir com
        o programa errado. A extensão original é sempre preservada.
        """
        saida = app_module._nome_exportado("{nome}.png", "foto.jpg", 1, "V", None)
        assert saida.endswith(".jpg")

    def test_padrao_com_caractere_invalido_e_sanitizado(self, app_module):
        saida = app_module._nome_exportado("a/b:c*{nome}", "foto.jpg", 1, "V", None)
        for proibido in '/\\:*?"<>|':
            assert proibido not in saida

    def test_nome_gigante_e_cortado(self, app_module):
        """O Windows para em 260 caracteres para o caminho inteiro."""
        saida = app_module._nome_exportado("x" * 400, "foto.jpg", 1, "V", None)
        assert len(saida) <= app_module.LIMITE_NOME_EXPORTADO + len(".jpg")

    def test_padrao_que_zera_o_nome_cai_no_original(self, app_module):
        """"///" sanitizado não sobra nada; sem o padrão, o arquivo ficaria sem nome."""
        saida = app_module._nome_exportado("///", "foto.jpg", 1, "V", None)
        assert saida == "foto.jpg"


class TestSubpastaPorData:
    def test_ano_e_mes(self, app_module):
        """
        Ano/mês e não o dia: uma pasta por dia produz centenas de pastas com
        uma foto dentro, que é pior que não organizar.
        """
        assert app_module._subpasta_por_data(datetime(2026, 8, 31)) == "2026-08"

    def test_sem_data_tem_pasta_propria(self, app_module):
        """Solto na raiz, ficaria misturado com as próprias subpastas."""
        assert app_module._subpasta_por_data(None) == "sem-data"

    def test_data_como_texto(self, app_module):
        assert app_module._subpasta_por_data("2026-08-31T10:00:00") == "2026-08"

    def test_texto_curto_demais_vira_sem_data(self, app_module):
        assert app_module._subpasta_por_data("2026") == "sem-data"


class TestRedimensionamento:
    def _imagem(self, caminho, largura, altura):
        from PIL import Image
        Image.new("RGB", (largura, altura), (120, 90, 200)).save(caminho)

    def test_reduz_mantendo_a_proporcao(self, app_module, tmp_path):
        origem = tmp_path / "grande.jpg"
        alvo = tmp_path / "saida.jpg"
        self._imagem(str(origem), 2000, 1000)

        assert app_module._copiar_redimensionando(str(origem), str(alvo), 800) is True

        from PIL import Image
        with Image.open(alvo) as img:
            assert img.width == 800
            assert img.height == 400        # proporção preservada

    def test_imagem_menor_e_copiada_intacta(self, app_module, tmp_path):
        """
        Reprocessar recomprime o JPEG e piora a qualidade sem economizar nada.
        """
        origem = tmp_path / "pequena.jpg"
        alvo = tmp_path / "saida.jpg"
        self._imagem(str(origem), 400, 300)

        assert app_module._copiar_redimensionando(str(origem), str(alvo), 800) is False
        assert alvo.stat().st_size == origem.stat().st_size

    def test_png_com_transparencia_vira_jpeg_sem_estourar(self, app_module, tmp_path):
        """RGBA em JPEG levanta erro; converter mantém o formato pedido."""
        from PIL import Image
        origem = tmp_path / "transparente.png"
        alvo = tmp_path / "saida.jpg"
        Image.new("RGBA", (1200, 600), (10, 20, 30, 128)).save(origem)

        app_module._copiar_redimensionando(str(origem), str(alvo), 300)

        with Image.open(alvo) as img:
            assert img.width == 300

    def test_arquivo_ilegivel_cai_para_copia(self, app_module, tmp_path):
        """
        Sem o fallback, uma imagem que o leitor não abre sairia da exportação
        em silêncio.
        """
        origem = tmp_path / "corrompida.jpg"
        alvo = tmp_path / "saida.jpg"
        origem.write_bytes(b"isto nao e uma imagem")

        assert app_module._copiar_redimensionando(str(origem), str(alvo), 800) is False
        assert alvo.read_bytes() == b"isto nao e uma imagem"


class TestValidacaoDasOpcoes:
    def test_padrao_sem_opcoes(self, app_module):
        opcoes, erro = app_module._validar_opcoes_export({})
        assert erro is None
        assert opcoes == {"tipos": "tudo", "padrao_nome": "",
                          "largura_max": None, "subpastas_por_data": False}

    def test_tipo_desconhecido_e_recusado(self, app_module):
        _, erro = app_module._validar_opcoes_export({"tipos": "planilhas"})
        assert erro is not None

    def test_largura_fora_da_faixa(self, app_module):
        _, erro = app_module._validar_opcoes_export({"largura_max": 10})
        assert "entre" in erro
        _, erro = app_module._validar_opcoes_export({"largura_max": 99999})
        assert "entre" in erro

    def test_largura_nao_numerica(self, app_module):
        _, erro = app_module._validar_opcoes_export({"largura_max": "grande"})
        assert "número" in erro

    def test_largura_vazia_e_o_mesmo_que_ausente(self, app_module):
        """Campo em branco no formulário não é pedido de redimensionar."""
        opcoes, erro = app_module._validar_opcoes_export({"largura_max": ""})
        assert erro is None and opcoes["largura_max"] is None

    def test_sem_leitor_de_imagem_avisa_antes(self, app_module):
        """
        Exportar em tamanho original e deixar o usuário descobrir depois que
        nada foi reduzido é pior que recusar na hora.
        """
        from unittest import mock
        with mock.patch.object(app_module, "PIL_OK", False):
            _, erro = app_module._validar_opcoes_export({"largura_max": 800})
        assert "redimensionar" in erro


class TestNoEndpoint:
    def _rotas(self, arquivos):
        return {
            "SELECT id, nome FROM collections": {"fetchone": {"id": 1, "nome": "Viagem"}},
            "FROM collection_files cf": {"fetchall": arquivos},
            "SELECT path FROM folders": {"fetchall": [{"path": "C:/x"}]},
        }

    def test_tipo_sem_nada_correspondente_explica(self, client_logado, db_roteado,
                                                   tmp_path):
        """
        A coleção tem conteúdo, mas nada do tipo pedido. Dizer "coleção vazia"
        mandaria o usuário procurar o problema no lugar errado.
        """
        db_roteado(self._rotas([_arquivo("a.pdf", "pdf")]))
        r = client_logado.post("/api/collections/1/export", json={
            "destino": str(tmp_path), "tipos": "imagens"})

        assert r.status_code == 400
        assert "Nenhuma imagem" in r.get_json()["error"]

    def test_opcao_invalida_e_recusada_antes_de_criar_pasta(self, client_logado,
                                                             db_roteado, tmp_path):
        """
        Recusar depois de criar a pasta deixaria uma pasta vazia no destino a
        cada tentativa errada.
        """
        db_roteado(self._rotas([_arquivo("a.jpg", "jpg")]))
        r = client_logado.post("/api/collections/1/export", json={
            "destino": str(tmp_path), "largura_max": 5})

        assert r.status_code == 400
        assert list(tmp_path.iterdir()) == []

    def test_exige_sessao(self, client, db_roteado, tmp_path):
        db_roteado({})
        assert client.post("/api/collections/1/export",
                           json={"destino": str(tmp_path)}).status_code == 401
