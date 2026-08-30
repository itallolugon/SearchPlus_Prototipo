# -*- coding: utf-8 -*-
"""
Renomear pastas: em cascata (junto da coleção) e sob demanda (só o sufixo).

O nome da pasta é `<nome da coleção>_<complemento>`. O prefixo é do sistema — é
o que liga a pasta à coleção no Explorer. O complemento é do usuário: foi ele
quem escolheu "backup" ou "praia", e isso precisa sobreviver a um rename.

Renomear a coleção sem tocar as pastas deixava "teste01_praia" apontando para
uma coleção que passou a se chamar outra coisa — some a relação que o prefixo
existia para criar.

O rename em cascata acontece **dentro do PATCH da coleção** porque só ali o
backend conhece os dois nomes ao mesmo tempo. Depois do UPDATE o antigo se
perde, e não há como separar prefixo de sufixo com segurança.
"""

import os

import pytest

pytestmark = pytest.mark.unit


class TestExtracaoDoSufixo:
    @pytest.mark.parametrize("pasta,colecao,esperado", [
        (r"D:\A\Ferias",         "Ferias", ""),        # exatamente o prefixo
        (r"D:\A\Ferias_backup",  "Ferias", "backup"),
        (r"D:\A\Ferias_praia_2", "Ferias", "praia_2"),
        (r"D:\A\Outra",          "Ferias", None),      # não deriva do prefixo
        (r"D:\A\FeriasXbackup",  "Ferias", None),      # sem o separador
        (r"D:\A\Feriasx",        "Ferias", None),      # prefixo é só um pedaço
    ])
    def test_separa_prefixo_de_sufixo(self, app_module, pasta, colecao, esperado):
        assert app_module._sufixo_da_pasta(pasta, colecao) == esperado

    def test_none_e_diferente_de_string_vazia(self, app_module):
        """
        A distinção que corrige o bug: "" significa "sem complemento",
        None significa "não é desta coleção". Confundir os dois fazia duas
        pastas disputarem o mesmo nome novo.
        """
        assert app_module._sufixo_da_pasta(r"D:\A\Ferias", "Ferias") == ""
        assert app_module._sufixo_da_pasta(r"D:\A\Outra", "Ferias") is None

    def test_usa_o_nome_sanitizado_como_prefixo(self, app_module):
        """A pasta guarda o nome já sanitizado — comparar com o cru não casa."""
        limpo = app_module._sanitizar_nome("Ferias 2024/2025", padrao="x")
        assert app_module._sufixo_da_pasta(
            os.path.join("D:\\A", f"{limpo}_backup"), "Ferias 2024/2025") == "backup"


class TestRenomearNoDisco:
    def test_renomeia_mantendo_a_pasta_mae(self, app_module, tmp_path):
        antiga = tmp_path / "Ferias"
        antiga.mkdir()
        (antiga / "a.jpg").write_text("x", encoding="utf-8")

        novo, motivo = app_module._renomear_pasta_no_disco(str(antiga), "Viagem")

        assert motivo is None
        assert os.path.basename(novo) == "Viagem"
        assert os.path.dirname(novo) == str(tmp_path)
        assert (tmp_path / "Viagem" / "a.jpg").exists()

    def test_nao_sobrescreve_pasta_existente(self, app_module, tmp_path):
        """Mesclar duas pastas em silêncio perderia arquivo."""
        origem = tmp_path / "Ferias"
        destino = tmp_path / "Viagem"
        origem.mkdir()
        destino.mkdir()
        (destino / "importante.jpg").write_text("nao apague", encoding="utf-8")

        novo, motivo = app_module._renomear_pasta_no_disco(str(origem), "Viagem")

        assert novo is None
        assert motivo == "nome_em_uso"
        assert (destino / "importante.jpg").read_text(encoding="utf-8") == "nao apague"
        assert origem.is_dir()          # a origem continua intacta

    def test_mesmo_nome_e_no_op(self, app_module, tmp_path):
        pasta = tmp_path / "Ferias"
        pasta.mkdir()
        novo, motivo = app_module._renomear_pasta_no_disco(str(pasta), "Ferias")

        assert motivo is None
        assert os.path.normpath(novo) == str(pasta)

    def test_pasta_ausente(self, app_module, tmp_path):
        novo, motivo = app_module._renomear_pasta_no_disco(
            str(tmp_path / "nao_existe"), "Qualquer")
        assert novo is None
        assert motivo == "nao_encontrada"


def _rotas(nome_atual, pastas, existe=True):
    return {
        "SELECT nome FROM collections": {"fetchone": {"nome": nome_atual}},
        "SELECT id, nome FROM collections": {
            "fetchone": {"id": 1, "nome": nome_atual} if existe else None},
        "FROM collections": {"fetchone": {"id": 1, "nome": nome_atual,
                                          "pasta_vinculada": None,
                                          "modo_sync": "manual"} if existe else None},
        "FROM collection_folders": {"fetchall": [{"caminho": str(p)} for p in pastas]},
    }


class TestCascataAoRenomearColecao:
    def test_prefixo_muda_e_sufixo_fica(self, client_logado, db_roteado, tmp_path):
        """O caso central: Ferias/Ferias_praia → Viagem/Viagem_praia."""
        p1 = tmp_path / "Ferias"
        p2 = tmp_path / "Ferias_praia"
        p1.mkdir(); p2.mkdir()

        db_roteado(_rotas("Ferias", [p1, p2]))
        corpo = client_logado.patch("/api/collections/1", json={
            "nome": "Viagem", "renomear_pastas": True}).get_json()

        assert (tmp_path / "Viagem").is_dir()
        assert (tmp_path / "Viagem_praia").is_dir()
        assert not p1.exists() and not p2.exists()
        assert len(corpo["pastas_renomeadas"]) == 2

    def test_sem_a_flag_nao_toca_o_disco(self, client_logado, db_roteado, tmp_path):
        pasta = tmp_path / "Ferias"
        pasta.mkdir()

        db_roteado(_rotas("Ferias", [pasta]))
        corpo = client_logado.patch("/api/collections/1",
                                    json={"nome": "Viagem"}).get_json()

        assert pasta.is_dir()                       # continua com o nome antigo
        assert corpo["pastas_renomeadas"] == []

    def test_falha_no_disco_nao_desfaz_o_rename_da_colecao(self, client_logado,
                                                           db_roteado, tmp_path):
        """
        Reverter o nome da coleção por causa de uma pasta aberta no Explorer
        seria pior que a inconsistência — são operações independentes.
        """
        origem = tmp_path / "Ferias"
        origem.mkdir()
        (tmp_path / "Viagem").mkdir()               # destino ocupado

        db_roteado(_rotas("Ferias", [origem]))
        r = client_logado.patch("/api/collections/1", json={
            "nome": "Viagem", "renomear_pastas": True})

        assert r.status_code == 200                 # a coleção foi renomeada
        corpo = r.get_json()
        assert corpo["pastas_com_falha"][0]["motivo"] == "nome_em_uso"
        assert origem.is_dir()

    def test_pasta_fora_do_padrao_e_ignorada(self, client_logado, db_roteado, tmp_path):
        """
        Regressão do bug relatado: coleção "teste" com as pastas "testee" e
        "teste01" — nenhuma derivada de "teste". Antes as duas viravam
        candidatas ao mesmo nome: a primeira renomeava, a segunda falhava com
        `nome_em_uso`, e o usuário via metade do trabalho feito.
        """
        p1 = tmp_path / "testee"
        p2 = tmp_path / "teste01"
        p1.mkdir(); p2.mkdir()

        db_roteado(_rotas("teste", [p1, p2]))
        corpo = client_logado.patch("/api/collections/1", json={
            "nome": "viagem", "renomear_pastas": True}).get_json()

        # Nenhuma foi renomeada, e nenhuma falhou — foram ignoradas.
        assert p1.is_dir() and p2.is_dir()
        assert corpo["pastas_renomeadas"] == []
        assert corpo["pastas_com_falha"] == []
        assert sorted(corpo["pastas_ignoradas"]) == ["teste01", "testee"]

    def test_mistura_de_padrao_e_fora_do_padrao(self, client_logado, db_roteado, tmp_path):
        """A que segue o padrão é renomeada; a outra fica."""
        boa = tmp_path / "Ferias_praia"
        estranha = tmp_path / "OutraCoisa"
        boa.mkdir(); estranha.mkdir()

        db_roteado(_rotas("Ferias", [boa, estranha]))
        corpo = client_logado.patch("/api/collections/1", json={
            "nome": "Viagem", "renomear_pastas": True}).get_json()

        assert (tmp_path / "Viagem_praia").is_dir()
        assert estranha.is_dir()
        assert corpo["pastas_ignoradas"] == ["OutraCoisa"]

    def test_colecao_sem_pastas(self, client_logado, db_roteado):
        db_roteado(_rotas("Ferias", []))
        corpo = client_logado.patch("/api/collections/1", json={
            "nome": "Viagem", "renomear_pastas": True}).get_json()
        assert corpo["pastas_renomeadas"] == []


class TestTrocarSufixoSobDemanda:
    def test_troca_o_complemento(self, client_logado, db_roteado, tmp_path):
        pasta = tmp_path / "Ferias_backup"
        pasta.mkdir()

        db_roteado(_rotas("Ferias", [pasta]))
        corpo = client_logado.patch("/api/collections/1/folders", json={
            "caminho": str(pasta), "sufixo": "praia"}).get_json()

        assert corpo["nome"] == "Ferias_praia"
        assert (tmp_path / "Ferias_praia").is_dir()

    def test_sufixo_vazio_deixa_so_o_prefixo(self, client_logado, db_roteado, tmp_path):
        pasta = tmp_path / "Ferias_backup"
        pasta.mkdir()

        db_roteado(_rotas("Ferias", [pasta]))
        corpo = client_logado.patch("/api/collections/1/folders", json={
            "caminho": str(pasta), "sufixo": ""}).get_json()

        assert corpo["nome"] == "Ferias"

    def test_sufixo_e_sanitizado(self, client_logado, db_roteado, tmp_path):
        pasta = tmp_path / "Ferias"
        pasta.mkdir()

        db_roteado(_rotas("Ferias", [pasta]))
        corpo = client_logado.patch("/api/collections/1/folders", json={
            "caminho": str(pasta), "sufixo": "a/b:c"}).get_json()

        assert "/" not in corpo["nome"] and ":" not in corpo["nome"]

    def test_pasta_nao_registrada_e_recusada(self, client_logado, db_roteado, tmp_path):
        """Só renomeia pasta que o app criou para ESTA coleção."""
        intrusa = tmp_path / "documentos_do_usuario"
        intrusa.mkdir()

        db_roteado(_rotas("Ferias", []))
        r = client_logado.patch("/api/collections/1/folders", json={
            "caminho": str(intrusa), "sufixo": "x"})

        assert r.status_code == 403
        assert intrusa.is_dir()

    def test_nome_em_uso_da_409_com_motivo(self, client_logado, db_roteado, tmp_path):
        origem = tmp_path / "Ferias_backup"
        origem.mkdir()
        (tmp_path / "Ferias_praia").mkdir()

        db_roteado(_rotas("Ferias", [origem]))
        r = client_logado.patch("/api/collections/1/folders", json={
            "caminho": str(origem), "sufixo": "praia"})

        assert r.status_code == 409
        assert "Já existe" in r.get_json()["error"]

    def test_sem_sufixo_no_corpo_e_recusado(self, client_logado, db_roteado, tmp_path):
        pasta = tmp_path / "Ferias"
        pasta.mkdir()
        db_roteado(_rotas("Ferias", [pasta]))
        r = client_logado.patch("/api/collections/1/folders",
                                json={"caminho": str(pasta)})
        assert r.status_code == 400

    def test_colecao_de_outro_dono_da_404(self, client_logado, db_roteado, tmp_path):
        pasta = tmp_path / "Ferias"
        pasta.mkdir()
        db_roteado(_rotas("Ferias", [pasta], existe=False))
        r = client_logado.patch("/api/collections/9/folders", json={
            "caminho": str(pasta), "sufixo": "x"})
        assert r.status_code == 404

    def test_exige_sessao(self, client, db_roteado, tmp_path):
        db_roteado({})
        r = client.patch("/api/collections/1/folders", json={
            "caminho": str(tmp_path), "sufixo": "x"})
        assert r.status_code == 401
