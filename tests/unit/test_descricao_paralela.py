# -*- coding: utf-8 -*-
"""
Descrição sob demanda em paralelo.

Uma busca por assunto ainda não descrito disparava até cinco chamadas de visão
**em fila indiana**, dentro do request: ~30 s só nessa fase. As cinco são
independentes entre si, então passaram a correr juntas — o custo vira o da mais
lenta, e não a soma.

O que **não** entrou na thread, e é o cerne da mudança:

  SBERT  — `_SBERT` é objeto global e a biblioteca não garante encode
           concorrente. A corrupção seria silenciosa: vetor errado gravado no
           banco, e a imagem passa a aparecer nas buscas erradas para sempre.
  banco  — `get_db()` só anota a conexão em `flask.g` havendo contexto de
           aplicação, e thread de executor não herda o do request. Sem a
           anotação, o `teardown_appcontext` não recolhe: alguns erros esgotam
           o pool e derrubam o servidor.

Ver `docs/features/16-latencia-da-busca.md`, seções 5.1 a 5.3.

Nota sobre o ambiente: o `conftest` zera a chave da API, então `CLAUDE_OK` é
False e este bloco inteiro é código morto na suíte. Todo teste daqui liga o
sinalizador e substitui a chamada de visão — nenhuma rede, nenhuma chave.
"""

import threading
import time
from unittest import mock

import pytest

pytestmark = pytest.mark.unit

UID = 4242


def _linha(id_, nome, descricao=""):
    """Imagem candidata: sem descrição e com embedding visual."""
    return {
        "id": id_,
        "folder_id": 1,
        "nome": nome,
        "caminho": f"C:/fotos/{nome}",
        "tipo": "jpg",
        "descricao_ia": descricao,
        "embedding_clip": [0.1, 0.2, 0.3],
        "data_adicionado": None,
        "favorito": 0,
        "sbert_score": None,
    }


def _rotas(linhas):
    return {
        "SELECT id, folder_id, nome, caminho": {"fetchall": linhas},
        "COUNT(*) AS n": {"fetchone": {"n": 0}},
    }


def _sbert_falso():
    """
    Duplo do modelo de texto.

    `SBERT_OK = True` sozinho nao basta: o endpoint chama `_SBERT.encode(...)`
    direto, e no ambiente de teste `_SBERT` e None.
    """
    import numpy as np

    falso = mock.MagicMock()
    falso.encode.return_value = np.zeros(384)
    return falso


def _motor_ligado(app_module, descrever):
    """
    Liga o mínimo para o bloco lazy ser alcançado, e substitui a visão.

    `clip_sims[i] > 0.15` é o que qualifica uma candidata; por isso o
    `cosine_similarity` devolve valor alto e o vetor da query não é nulo.
    """
    return (
        mock.patch.object(app_module, "CLAUDE_OK", True),
        mock.patch.object(app_module, "CLIP_OK", True),
        mock.patch.object(app_module, "SKLEARN_OK", True),
        # SBERT ligado porque `busca_pronta()` é o que destrava o endpoint:
        # com ele desligado a busca devolve 503 e nem chega no bloco lazy.
        # O encode em si fica substituído — nenhum modelo é carregado.
        mock.patch.object(app_module, "SBERT_OK", True),
        mock.patch.object(app_module, "_SBERT", _sbert_falso()),
        mock.patch.object(app_module, "_gerar_embedding", lambda t: [0.1] * 384),
        mock.patch.object(app_module, "cosine_similarity", lambda a, b: [[0.9]]),
        mock.patch.object(app_module, "_gerar_embedding_clip_texto", lambda t: [0.1, 0.2, 0.3]),
        mock.patch.object(app_module, "_descrever_imagem_on_demand", descrever),
        mock.patch.object(app_module, "_salvar_descricoes_em_lote", mock.Mock()),
    )


class TestOTeto:
    def test_cinco_candidatas_geram_cinco_chamadas(self, client_logado, db_roteado, app_module):
        """O teto existe por custo: cada descrição é uma chamada paga."""
        db_roteado(_rotas([_linha(i, f"f{i}.jpg") for i in range(1, 9)]))
        chamadas = []

        def descrever(caminho, nome):
            chamadas.append(nome)
            return f"descricao de {nome}"

        ctx = _motor_ligado(app_module, descrever)
        for c in ctx:
            c.start()
        try:
            client_logado.post("/api/search", json={"query": "praia"})
        finally:
            for c in reversed(ctx):
                c.stop()

        assert len(chamadas) == app_module.TETO_DESCRICOES_POR_BUSCA == 5, (
            "o teto de descrições por busca se perdeu no refactor: %d chamadas" % len(chamadas)
        )

    def test_sem_candidata_nenhuma_thread_e_criada(self, client_logado, db_roteado, app_module):
        """Busca com cache quente não pode pagar o custo de montar o pool."""
        db_roteado(_rotas([_linha(1, "f1.jpg", descricao="ja descrita")]))
        chamou = mock.Mock(return_value="x")

        ctx = _motor_ligado(app_module, chamou)
        for c in ctx:
            c.start()
        try:
            antes = threading.active_count()
            client_logado.post("/api/search", json={"query": "praia"})
            depois = threading.active_count()
        finally:
            for c in reversed(ctx):
                c.stop()

        chamou.assert_not_called()
        assert depois <= antes, "sobrou thread de um pool que nem precisava existir"


class TestParaleloDeVerdade:
    def test_as_chamadas_se_sobrepoem_no_tempo(self, client_logado, db_roteado, app_module):
        """
        O ponto da feature. Em série, a concorrência máxima observada é 1.
        Cada descrição segura a sua por um instante para que a sobreposição
        seja mensurável sem depender de temporização frágil.
        """
        db_roteado(_rotas([_linha(i, f"f{i}.jpg") for i in range(1, 6)]))
        dentro = 0
        maximo = 0
        trava = threading.Lock()

        def descrever(caminho, nome):
            nonlocal dentro, maximo
            with trava:
                dentro += 1
                maximo = max(maximo, dentro)
            time.sleep(0.15)
            with trava:
                dentro -= 1
            return f"descricao de {nome}"

        ctx = _motor_ligado(app_module, descrever)
        for c in ctx:
            c.start()
        try:
            client_logado.post("/api/search", json={"query": "praia"})
        finally:
            for c in reversed(ctx):
                c.stop()

        assert maximo > 1, "as descrições voltaram a rodar em série (concorrência máxima 1)"
        assert maximo == 5, "esperava as cinco sobrepostas, observei %d" % maximo


class TestFalhaIsolada:
    def test_uma_que_estoura_nao_derruba_as_outras(self, client_logado, db_roteado, app_module):
        """
        O motor tem resultado a mostrar mesmo sem descrição nenhuma. Uma
        imagem ilegível não pode zerar a busca inteira.
        """
        db_roteado(_rotas([_linha(i, f"f{i}.jpg") for i in range(1, 6)]))
        ok = []

        def descrever(caminho, nome):
            if nome == "f3.jpg":
                raise OSError("arquivo corrompido")
            ok.append(nome)
            return f"descricao de {nome}"

        ctx = _motor_ligado(app_module, descrever)
        for c in ctx:
            c.start()
        try:
            r = client_logado.post("/api/search", json={"query": "praia"})
        finally:
            for c in reversed(ctx):
                c.stop()

        assert r.status_code == 200, "uma descrição que falhou derrubou a busca"
        assert len(ok) == 4, "as outras quatro tinham que ter sido descritas"


class TestOrdemDeChegada:
    def test_descricao_fora_de_ordem_vai_para_o_indice_certo(
        self, client_logado, db_roteado, app_module
    ):
        """
        `as_completed` devolve na ordem em que TERMINAM. Se o índice viesse
        daí em vez do dicionário de futuros, a descrição de uma foto seria
        gravada em cima de outra — e o erro fica no banco.
        """
        linhas = [_linha(i, f"f{i}.jpg") for i in range(1, 6)]
        db_roteado(_rotas(linhas))

        # A primeira submetida é a que mais demora: força a inversão.
        atrasos = {"f1.jpg": 0.30, "f2.jpg": 0.01, "f3.jpg": 0.01, "f4.jpg": 0.01, "f5.jpg": 0.01}

        def descrever(caminho, nome):
            time.sleep(atrasos.get(nome, 0.01))
            return f"sou a {nome}"

        gravados = {}

        def espiar_lote(uid, itens):
            for caminho, desc, _emb in itens:
                gravados[caminho.rsplit("/", 1)[-1]] = desc

        ctx = (
            mock.patch.object(app_module, "CLAUDE_OK", True),
            mock.patch.object(app_module, "CLIP_OK", True),
            mock.patch.object(app_module, "SKLEARN_OK", True),
            mock.patch.object(app_module, "SBERT_OK", True),
            mock.patch.object(app_module, "_SBERT", _sbert_falso()),
            mock.patch.object(app_module, "_gerar_embedding", lambda t: [0.1] * 384),
            mock.patch.object(app_module, "cosine_similarity", lambda a, b: [[0.9]]),
            mock.patch.object(app_module, "_gerar_embedding_clip_texto", lambda t: [0.1, 0.2, 0.3]),
            mock.patch.object(app_module, "_descrever_imagem_on_demand", descrever),
            mock.patch.object(app_module, "_salvar_descricoes_em_lote", espiar_lote),
        )
        for c in ctx:
            c.start()
        try:
            client_logado.post("/api/search", json={"query": "praia"})
        finally:
            for c in reversed(ctx):
                c.stop()

        for nome, desc in gravados.items():
            assert desc == f"sou a {nome}", (
                "a descrição de %r foi parar no arquivo errado (%r) — o índice "
                "está vindo da ordem de chegada" % (desc, nome)
            )


class TestBM25:
    def test_sem_descricao_obtida_o_bm25_nao_e_recalculado(
        self, client_logado, db_roteado, app_module
    ):
        """
        Antes bastava ter havido candidatas. Com a API fora, nenhuma descrição
        chega, o corpus não muda — e se pagava o recálculo do corpus inteiro
        à toa.
        """
        db_roteado(_rotas([_linha(i, f"f{i}.jpg") for i in range(1, 6)]))

        with mock.patch.object(app_module, "_bm25_scores", wraps=app_module._bm25_scores) as bm25:
            ctx = _motor_ligado(app_module, lambda caminho, nome: None)  # API fora
            for c in ctx:
                c.start()
            try:
                client_logado.post("/api/search", json={"query": "praia"})
            finally:
                for c in reversed(ctx):
                    c.stop()

        assert bm25.call_count == 1, (
            "BM25 recalculado sem nenhuma descrição nova: %d chamadas" % bm25.call_count
        )


class TestGravacaoEmLote:
    def test_uma_conexao_para_todas_as_descricoes(self, app_module, db_falso):
        """
        Cinco conexões e cinco commits contra o Postgres na nuvem custam mais
        que os próprios UPDATEs.
        """
        abriu, conn = db_falso
        itens = [(f"C:/fotos/f{i}.jpg", f"desc {i}", [0.1] * 384) for i in range(5)]

        app_module._salvar_descricoes_em_lote(UID, itens)

        assert abriu.call_count == 1, "abriu mais de uma conexão para o lote"
        assert conn.execute.call_count == 5, "esperava um UPDATE por item"
        assert conn.commit.call_count == 1, "esperava um único commit no fim"

    def test_falha_no_lote_nao_deixa_conexao_aberta(self, app_module, db_falso):
        """
        O `close()` está no `finally` por isto: em thread não há teardown de
        request para recolher a conexão esquecida, e algumas dezenas de erros
        esgotam o pool.
        """
        _abriu, conn = db_falso
        conn.execute.side_effect = RuntimeError("banco caiu")

        app_module._salvar_descricoes_em_lote(UID, [("C:/fotos/a.jpg", "d", None)])

        assert conn.close.called, "a conexão vazou quando o UPDATE falhou"

    def test_lista_vazia_nem_abre_conexao(self, app_module, db_falso):
        abriu, conn = db_falso
        app_module._salvar_descricoes_em_lote(UID, [])
        assert not abriu.called, "abriu conexão para uma lista vazia"
        assert not conn.execute.called
