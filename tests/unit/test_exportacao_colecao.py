# -*- coding: utf-8 -*-
"""
Exportação de coleção: sanitização de nomes, colisões e cópia em disco.

Exportar aqui é copiar arquivo local → pasta local (o backend roda na máquina do
usuário). Estes testes tocam o disco de verdade, em `tmp_path`, porque o valor
da feature está exatamente no efeito colateral: a pasta existe, o arquivo está
lá, e nada do que já existia foi sobrescrito.

A regra mais importante da bateria é negativa: **nenhuma exportação pode
destruir dado**. Nem na origem, nem no destino.
"""

import os

import pytest

pytestmark = pytest.mark.unit


# ──────────────────────────────────────────────────────────────────────────────
# Sanitização — RF-038, RF-039, RF-040
# ──────────────────────────────────────────────────────────────────────────────

class TestSanitizacaoDeNome:
    @pytest.mark.parametrize(
        "bruto,proibido",
        [
            ("Ferias 2024/2025", "/"),
            ("Praia: verao", ":"),
            ('Aspas "duplas"', '"'),
            ("Barra\\invertida", "\\"),
            ("Pipe|aqui", "|"),
            ("Interroga?cao", "?"),
            ("Asterisco*", "*"),
            ("Menor<maior>", "<"),
        ],
    )
    def test_remove_caractere_proibido_no_windows(self, app_module, bruto, proibido):
        limpo = app_module._sanitizar_nome(bruto, padrao="colecao_1")
        assert proibido not in limpo

    def test_preserva_nome_ja_valido(self, app_module):
        assert app_module._sanitizar_nome("Arquitetura Moderna", padrao="x") == "Arquitetura Moderna"

    def test_preserva_acentuacao(self, app_module):
        # Acento é válido no NTFS; remover mutilaria o nome escolhido pelo usuário.
        assert "é" in app_module._sanitizar_nome("Férias", padrao="x")

    @pytest.mark.parametrize("reservado", ["CON", "PRN", "AUX", "NUL", "COM1", "LPT1"])
    def test_escapa_nome_reservado_do_windows(self, app_module, reservado):
        # 'CON' não pode ser nome de pasta no Windows, em nenhuma variação.
        limpo = app_module._sanitizar_nome(reservado, padrao="colecao_1")
        assert limpo.upper() != reservado

    def test_corta_ponto_e_espaco_no_fim(self, app_module):
        # O Explorer não abre pasta terminada em '.' ou ' '.
        limpo = app_module._sanitizar_nome("relatorio ...  ", padrao="x")
        assert not limpo.endswith((".", " "))

    def test_usa_padrao_quando_sobra_vazio(self, app_module):
        assert app_module._sanitizar_nome("///:::***", padrao="colecao_7") == "colecao_7"

    def test_usa_padrao_quando_entrada_vazia(self, app_module):
        assert app_module._sanitizar_nome("   ", padrao="colecao_9") == "colecao_9"

    def test_trunca_nome_muito_longo(self, app_module):
        # MAX_PATH do Windows é 260 para o caminho inteiro.
        limpo = app_module._sanitizar_nome("x" * 500, padrao="x")
        assert 0 < len(limpo) <= 120


# ──────────────────────────────────────────────────────────────────────────────
# Colisões — RF-041, RF-042, RF-043
# ──────────────────────────────────────────────────────────────────────────────

class TestColisaoDeNomes:
    def test_pasta_livre_mantem_o_nome(self, app_module, tmp_path):
        destino = app_module._pasta_disponivel(str(tmp_path), "Natureza")
        assert os.path.basename(destino) == "Natureza"

    def test_pasta_ocupada_ganha_sufixo(self, app_module, tmp_path):
        (tmp_path / "Natureza").mkdir()
        destino = app_module._pasta_disponivel(str(tmp_path), "Natureza")
        assert os.path.basename(destino) == "Natureza (1)"

    def test_sufixo_incrementa_ate_achar_livre(self, app_module, tmp_path):
        (tmp_path / "Natureza").mkdir()
        (tmp_path / "Natureza (1)").mkdir()
        destino = app_module._pasta_disponivel(str(tmp_path), "Natureza")
        assert os.path.basename(destino) == "Natureza (2)"

    def test_nao_escreve_dentro_de_pasta_preexistente(self, app_module, tmp_path):
        # Exportar duas vezes para o mesmo lugar não pode misturar os conteúdos.
        antiga = tmp_path / "Natureza"
        antiga.mkdir()
        (antiga / "arquivo_antigo.txt").write_text("preciso", encoding="utf-8")

        destino = app_module._pasta_disponivel(str(tmp_path), "Natureza")

        assert destino != str(antiga)
        assert (antiga / "arquivo_antigo.txt").read_text(encoding="utf-8") == "preciso"

    def test_arquivo_livre_mantem_o_nome(self, app_module, tmp_path):
        assert app_module._nome_disponivel(str(tmp_path), "foto.jpg") == "foto.jpg"

    def test_arquivo_ocupado_ganha_sufixo_antes_da_extensao(self, app_module, tmp_path):
        (tmp_path / "foto.jpg").write_text("a", encoding="utf-8")
        # A extensão precisa sobreviver: 'foto.jpg_1' não abriria como imagem.
        assert app_module._nome_disponivel(str(tmp_path), "foto.jpg") == "foto_1.jpg"

    def test_sufixo_de_arquivo_incrementa(self, app_module, tmp_path):
        (tmp_path / "foto.jpg").write_text("a", encoding="utf-8")
        (tmp_path / "foto_1.jpg").write_text("b", encoding="utf-8")
        assert app_module._nome_disponivel(str(tmp_path), "foto.jpg") == "foto_2.jpg"

    def test_arquivo_sem_extensao(self, app_module, tmp_path):
        (tmp_path / "LEIAME").write_text("a", encoding="utf-8")
        assert app_module._nome_disponivel(str(tmp_path), "LEIAME") == "LEIAME_1"


# ──────────────────────────────────────────────────────────────────────────────
# Autorização de origem — RF-045
# ──────────────────────────────────────────────────────────────────────────────

class TestOrigemAutorizada:
    def test_aceita_arquivo_dentro_da_pasta_monitorada(self, app_module, tmp_path):
        pasta = tmp_path / "Fotos"
        pasta.mkdir()
        alvo = pasta / "a.jpg"
        alvo.write_text("x", encoding="utf-8")
        assert app_module._dentro_das_pastas(str(alvo), [str(pasta)]) is True

    def test_aceita_arquivo_em_subpasta(self, app_module, tmp_path):
        pasta = tmp_path / "Fotos"
        (pasta / "2024").mkdir(parents=True)
        alvo = pasta / "2024" / "a.jpg"
        alvo.write_text("x", encoding="utf-8")
        assert app_module._dentro_das_pastas(str(alvo), [str(pasta)]) is True

    def test_recusa_arquivo_fora_das_pastas(self, app_module, tmp_path):
        pasta = tmp_path / "Fotos"
        pasta.mkdir()
        fora = tmp_path / "outra" / "segredo.txt"
        fora.parent.mkdir()
        fora.write_text("x", encoding="utf-8")
        assert app_module._dentro_das_pastas(str(fora), [str(pasta)]) is False

    def test_prefixo_parecido_nao_autoriza(self, app_module, tmp_path):
        # 'C:\Fotos' não pode autorizar 'C:\Fotos_privado' — o separador importa.
        (tmp_path / "Fotos").mkdir()
        vizinha = tmp_path / "Fotos_privado"
        vizinha.mkdir()
        alvo = vizinha / "a.jpg"
        alvo.write_text("x", encoding="utf-8")
        assert app_module._dentro_das_pastas(str(alvo), [str(tmp_path / "Fotos")]) is False

    def test_sem_pastas_monitoradas_nada_e_autorizado(self, app_module, tmp_path):
        alvo = tmp_path / "a.jpg"
        alvo.write_text("x", encoding="utf-8")
        assert app_module._dentro_das_pastas(str(alvo), []) is False


# ──────────────────────────────────────────────────────────────────────────────
# Cópia de verdade — RF-044, RF-046, RF-052, RF-056
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def exportar(app_module):
    """Roda um job de exportação síncrono e devolve o estado final."""
    import time

    def _rodar(itens, pasta_destino, cancelar_apos=None):
        job_id = "teste"
        with app_module._export_lock:
            app_module._export_jobs[job_id] = {
                "user_id": 1, "collection_id": 1, "colecao": "Teste",
                "pasta": pasta_destino, "total": len(itens), "copiados": 0,
                "falhas": [], "estado": "executando", "cancelar": False,
                "erro": None, "criado_em": time.time(),
            }
        if cancelar_apos is not None:
            import threading

            def _cancelar():
                while True:
                    with app_module._export_lock:
                        job = app_module._export_jobs[job_id]
                        if job["copiados"] >= cancelar_apos:
                            job["cancelar"] = True
                            return
                        if job["estado"] != "executando":
                            return
            threading.Thread(target=_cancelar, daemon=True).start()

        app_module._worker_exportacao(job_id, itens, pasta_destino)
        return app_module._export_jobs.pop(job_id)

    return _rodar


def _item(caminho, nome=None, autorizado=True):
    return {"nome": nome or os.path.basename(caminho),
            "caminho": str(caminho), "autorizado": autorizado}


class TestCopiaDeArquivos:
    def test_copia_todos_os_arquivos(self, tmp_path, exportar):
        origem, destino = tmp_path / "o", tmp_path / "d"
        origem.mkdir(); destino.mkdir()
        for n in ("a.jpg", "b.jpg", "c.jpg"):
            (origem / n).write_text(n, encoding="utf-8")

        job = exportar([_item(origem / n) for n in ("a.jpg", "b.jpg", "c.jpg")], str(destino))

        assert job["estado"] == "concluido"
        assert job["copiados"] == 3
        assert sorted(os.listdir(destino)) == ["a.jpg", "b.jpg", "c.jpg"]

    def test_conteudo_e_preservado(self, tmp_path, exportar):
        origem, destino = tmp_path / "o", tmp_path / "d"
        origem.mkdir(); destino.mkdir()
        (origem / "a.jpg").write_text("conteudo exato", encoding="utf-8")

        exportar([_item(origem / "a.jpg")], str(destino))

        assert (destino / "a.jpg").read_text(encoding="utf-8") == "conteudo exato"

    def test_originais_permanecem_intactos(self, tmp_path, exportar):
        # Exportar COPIA. Se movesse, a coleção apontaria para o vazio.
        origem, destino = tmp_path / "o", tmp_path / "d"
        origem.mkdir(); destino.mkdir()
        (origem / "a.jpg").write_text("original", encoding="utf-8")

        exportar([_item(origem / "a.jpg")], str(destino))

        assert (origem / "a.jpg").exists()
        assert (origem / "a.jpg").read_text(encoding="utf-8") == "original"

    def test_nomes_iguais_de_pastas_diferentes_nao_se_sobrescrevem(self, tmp_path, exportar):
        # Caso comum: toda câmera gera IMG_0001.jpg.
        a, b, destino = tmp_path / "a", tmp_path / "b", tmp_path / "d"
        a.mkdir(); b.mkdir(); destino.mkdir()
        (a / "IMG_0001.jpg").write_text("da pasta A", encoding="utf-8")
        (b / "IMG_0001.jpg").write_text("da pasta B", encoding="utf-8")

        job = exportar([_item(a / "IMG_0001.jpg"), _item(b / "IMG_0001.jpg")], str(destino))

        assert job["copiados"] == 2
        assert (destino / "IMG_0001.jpg").read_text(encoding="utf-8") == "da pasta A"
        assert (destino / "IMG_0001_1.jpg").read_text(encoding="utf-8") == "da pasta B"


class TestFalhasPorItem:
    def test_arquivo_ausente_nao_aborta_a_exportacao(self, tmp_path, exportar):
        # O índice envelhece: o usuário move arquivos fora do app.
        origem, destino = tmp_path / "o", tmp_path / "d"
        origem.mkdir(); destino.mkdir()
        (origem / "existe.jpg").write_text("x", encoding="utf-8")

        job = exportar(
            [_item(origem / "existe.jpg"), _item(origem / "sumiu.jpg")], str(destino)
        )

        assert job["estado"] == "concluido"
        assert job["copiados"] == 1
        assert [f["motivo"] for f in job["falhas"]] == ["nao_encontrado"]

    def test_falha_registra_o_nome_do_arquivo(self, tmp_path, exportar):
        # Sem o nome, o usuário não consegue reconciliar a coleção com o disco.
        destino = tmp_path / "d"
        destino.mkdir()
        job = exportar([_item(tmp_path / "sumiu.jpg")], str(destino))
        assert job["falhas"][0]["nome"] == "sumiu.jpg"

    def test_arquivo_fora_das_pastas_e_recusado(self, tmp_path, exportar):
        destino = tmp_path / "d"
        destino.mkdir()
        alvo = tmp_path / "segredo.txt"
        alvo.write_text("chave privada", encoding="utf-8")

        job = exportar([_item(alvo, autorizado=False)], str(destino))

        assert job["copiados"] == 0
        assert job["falhas"][0]["motivo"] == "fora_das_pastas"
        assert os.listdir(destino) == []

    def test_total_bate_com_copiados_mais_falhas(self, tmp_path, exportar):
        origem, destino = tmp_path / "o", tmp_path / "d"
        origem.mkdir(); destino.mkdir()
        (origem / "ok.jpg").write_text("x", encoding="utf-8")

        itens = [_item(origem / "ok.jpg"),
                 _item(origem / "sumiu.jpg"),
                 _item(origem / "bloqueado.jpg", autorizado=False)]
        job = exportar(itens, str(destino))

        assert job["copiados"] + len(job["falhas"]) == job["total"] == 3


class TestCancelamento:
    def test_cancelar_interrompe_e_preserva_o_copiado(self, tmp_path, exportar):
        origem, destino = tmp_path / "o", tmp_path / "d"
        origem.mkdir(); destino.mkdir()
        itens = []
        for i in range(30):
            (origem / f"f{i}.jpg").write_text(str(i), encoding="utf-8")
            itens.append(_item(origem / f"f{i}.jpg"))

        job = exportar(itens, str(destino), cancelar_apos=3)

        assert job["estado"] == "cancelado"
        # Não há rollback: o que foi copiado fica.
        assert len(os.listdir(destino)) == job["copiados"]
        assert job["copiados"] < 30

    def test_cancelar_nao_apaga_a_origem(self, tmp_path, exportar):
        origem, destino = tmp_path / "o", tmp_path / "d"
        origem.mkdir(); destino.mkdir()
        itens = []
        for i in range(20):
            (origem / f"f{i}.jpg").write_text(str(i), encoding="utf-8")
            itens.append(_item(origem / f"f{i}.jpg"))

        exportar(itens, str(destino), cancelar_apos=2)

        assert len(os.listdir(origem)) == 20


class TestColecaoVazia:
    def test_exportar_nada_conclui_sem_erro(self, tmp_path, exportar):
        destino = tmp_path / "d"
        destino.mkdir()
        job = exportar([], str(destino))
        assert job["estado"] == "concluido"
        assert job["copiados"] == 0
        assert os.listdir(destino) == []
