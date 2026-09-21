# -*- coding: utf-8 -*-
"""
A busca responde sem esperar a IA.

Até aqui a busca por assunto novo descrevia as candidatas **dentro do
request** — em paralelo depois da feature 16, mas ainda dentro. Agora ela só
enfileira e responde. O motor já pontua imagem sem descrição (o
`min(0.70, 0.85 * s_visual)` existe para o caso "só tenho CLIP"), então o
resultado aparece na hora e a descrição melhora a posição dele na busca
seguinte.

**Um erro da especificação que esta implementação corrigiu.** O documento dizia
que bastava enfileirar, porque "as descrições vão para o `_queue` do
`_process_worker`, que já existe". O worker existia, mas **não descrevia
imagem** — o comentário dele dizia, com todas as letras, *"Imagem: só o
embedding visual CLIP. Descrição vem na busca"*. Enfileirar sem ensiná-lo a
descrever teria feito as descrições simplesmente pararem de acontecer, e o
sintoma apareceria semanas depois como "a busca piorou".

Por isso o item da fila carrega `descrever: True`, e o worker só chama a IA
quando ele vem marcado: a varredura de pastas continua barata, e a chamada paga
só acontece quando alguém procurou por aquilo.

Ver `docs/features/17-busca-sem-esperar-a-ia.md`.
"""

from unittest import mock

import pytest

pytestmark = pytest.mark.unit


def _sbert_falso():
    import numpy as np

    falso = mock.MagicMock()
    falso.encode.return_value = np.zeros(384)
    return falso


def _linha(id_, nome, descricao=""):
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


def _motor(app_module, descrever_espiao=None):
    """Liga o mínimo para o bloco de enfileiramento ser alcançado."""
    return (
        mock.patch.object(app_module, "CLAUDE_OK", True),
        mock.patch.object(app_module, "CLIP_OK", True),
        mock.patch.object(app_module, "SKLEARN_OK", True),
        mock.patch.object(app_module, "SBERT_OK", True),
        mock.patch.object(app_module, "_SBERT", _sbert_falso()),
        mock.patch.object(app_module, "_gerar_embedding", lambda t: [0.1] * 384),
        mock.patch.object(app_module, "cosine_similarity", lambda a, b: [[0.9]]),
        mock.patch.object(app_module, "_gerar_embedding_clip_texto", lambda t: [0.1, 0.2, 0.3]),
        mock.patch.object(
            app_module,
            "_descrever_imagem_on_demand",
            descrever_espiao or mock.Mock(return_value="nao deveria ser chamada"),
        ),
    )


def _buscar(client_logado, app_module, ctx, query="praia"):
    for c in ctx:
        c.start()
    try:
        return client_logado.post("/api/search", json={"query": query})
    finally:
        for c in reversed(ctx):
            c.stop()


@pytest.fixture(autouse=True)
def _fila_limpa(app_module):
    """A fila e o conjunto de pendentes são globais; um teste não pode herdar o outro."""
    yield
    with app_module._lock_descricoes:
        app_module._descricoes_na_fila.clear()
    while not app_module._queue.empty():
        app_module._queue.get_nowait()


class TestABuscaNaoEsperaAIA:
    def test_a_visao_nao_e_chamada_dentro_do_request(self, client_logado, db_roteado, app_module):
        """É a feature inteira em uma linha."""
        db_roteado(_rotas([_linha(i, f"f{i}.jpg") for i in range(1, 6)]))
        visao = mock.Mock(return_value="descricao")

        r = _buscar(client_logado, app_module, _motor(app_module, visao))

        assert r.status_code == 200
        visao.assert_not_called()

    def test_as_candidatas_vao_para_a_fila(self, client_logado, db_roteado, app_module):
        db_roteado(_rotas([_linha(i, f"f{i}.jpg") for i in range(1, 4)]))
        _buscar(client_logado, app_module, _motor(app_module))
        assert app_module._queue.qsize() == 3

    def test_o_item_da_fila_pede_descricao(self, client_logado, db_roteado, app_module):
        """
        Sem `descrever: True` o worker trata como indexação comum e grava
        descrição vazia — as descrições parariam de acontecer em silêncio.
        """
        db_roteado(_rotas([_linha(1, "f1.jpg")]))
        _buscar(client_logado, app_module, _motor(app_module))

        item = app_module._queue.get_nowait()
        assert item.get("descrever") is True
        assert item["path"] == "C:/fotos/f1.jpg"
        assert item["uid"]


class TestOContrato:
    def test_descrevendo_traz_os_ids_enfileirados(self, client_logado, db_roteado, app_module):
        db_roteado(_rotas([_linha(7, "a.jpg"), _linha(9, "b.jpg")]))
        corpo = _buscar(client_logado, app_module, _motor(app_module)).get_json()
        assert sorted(corpo["descrevendo"]) == [7, 9]

    def test_biblioteca_descrita_devolve_lista_vazia(self, client_logado, db_roteado, app_module):
        """É a condição de parada: sem ela o front reconsulta para sempre."""
        db_roteado(_rotas([_linha(1, "f1.jpg", descricao="uma praia ao entardecer")]))
        corpo = _buscar(client_logado, app_module, _motor(app_module)).get_json()
        assert corpo["descrevendo"] == []

    def test_o_campo_vem_ate_na_busca_sem_resultado(self, client_logado, db_roteado, app_module):
        """A forma da resposta não muda com o conteúdo."""
        db_roteado(_rotas([]))
        corpo = _buscar(client_logado, app_module, _motor(app_module)).get_json()
        assert corpo["descrevendo"] == []

    def test_os_campos_de_hoje_continuam(self, client_logado, db_roteado, app_module):
        """Um front que ignore o campo novo não pode quebrar."""
        db_roteado(_rotas([_linha(1, "f1.jpg")]))
        corpo = _buscar(client_logado, app_module, _motor(app_module)).get_json()
        for campo in ("resultados", "tempo", "consulta", "excluidos", "escopo"):
            assert campo in corpo


class TestNaoEnchendoAFila:
    def test_id_ja_na_fila_nao_e_reenfileirado(self, client_logado, db_roteado, app_module):
        """
        O laço que este teste impede: o front refaz a busca enquanto houver
        pendentes; se cada refação enfileirasse de novo, a fila cresceria
        sozinha e nunca esvaziaria.
        """
        db_roteado(_rotas([_linha(i, f"f{i}.jpg") for i in range(1, 4)]))

        _buscar(client_logado, app_module, _motor(app_module))
        apos_primeira = app_module._queue.qsize()

        db_roteado(_rotas([_linha(i, f"f{i}.jpg") for i in range(1, 4)]))
        corpo = _buscar(client_logado, app_module, _motor(app_module)).get_json()

        assert app_module._queue.qsize() == apos_primeira, "a fila cresceu na segunda busca"
        assert corpo["descrevendo"] == [], (
            "a segunda busca anunciou como pendente algo que já estava na fila"
        )

    def test_o_teto_por_busca_continua(self, client_logado, db_roteado, app_module):
        """O teto existe por custo: cada descrição é uma chamada paga."""
        db_roteado(_rotas([_linha(i, f"f{i}.jpg") for i in range(1, 12)]))
        corpo = _buscar(client_logado, app_module, _motor(app_module)).get_json()
        assert len(corpo["descrevendo"]) == app_module.TETO_DESCRICOES_POR_BUSCA == 5


class TestOWorkerDescreve:
    """
    O ponto onde a especificação errava. Sem isto, tudo acima passa e as
    descrições nunca acontecem.
    """

    def test_o_worker_chama_a_visao_para_item_marcado(self, app_module):
        fonte = _fonte_do_worker(app_module)
        assert "_descrever_imagem_on_demand" in fonte, (
            "o worker não descreve; enfileirar não adianta e as descrições param"
        )
        assert 'item.get("descrever")' in fonte, (
            "o worker descreveria TODA imagem da varredura — a biblioteca "
            "inteira viraria chamada paga sem ninguém ter procurado"
        )

    def test_o_pedido_de_busca_ignora_a_janela_de_horario(self, app_module):
        """
        A janela existe para a varredura não atrapalhar quem usa a máquina. Um
        pedido de busca é o oposto: a pessoa está esperando agora. Segurá-lo
        até a madrugada entregaria a descrição depois de a busca ser fechada.
        """
        fonte = _fonte_do_worker(app_module)
        assert 'not item.get("descrever") and not _is_within_window' in fonte

    def test_o_pendente_sai_do_conjunto_ao_terminar(self, app_module):
        """
        Se ficasse, a imagem nunca mais seria reenfileirada — e uma descrição
        que falhou não teria segunda chance.
        """
        fonte = _fonte_do_worker(app_module)
        assert "_descricoes_na_fila.discard" in fonte
        assert "finally:" in fonte, "a limpeza precisa valer também quando o item falha"


def _fonte_do_worker(app_module):
    import io
    import os

    raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    fonte = io.open(os.path.join(raiz, "backend", "app.py"), encoding="utf-8").read()
    i = fonte.index("def _process_worker")
    return fonte[i : fonte.index("\n# ─────", i)]
