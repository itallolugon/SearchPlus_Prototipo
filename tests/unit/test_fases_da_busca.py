# -*- coding: utf-8 -*-
"""
Tempo por fase da busca.

O endpoint devolvia só o tempo total. Sem separar as fases, qualquer
otimização é chute e não há como provar o ganho depois — foi por isso que a
paralelização das descrições entrou sem número de antes e depois.

Critério de aceite da especificação (seção 4): numa busca, a soma das fases
bate com o total dentro de 0,3 s.

Onde a medição sai, e por quê:

  log do servidor  sempre. É onde se olha quando a busca está lenta.
  JSON             só em `/api/debug/scores`. O payload de `/api/search` é
                   contrato público (`docs/API.md`) e não pode mudar de forma
                   por causa de diagnóstico — o front quebraria por um número
                   que não é dele.

Ver `docs/features/16-latencia-da-busca.md`, seção 4.
"""

from unittest import mock

import pytest

pytestmark = pytest.mark.unit


def _sbert_falso():
    import numpy as np

    falso = mock.MagicMock()
    falso.encode.return_value = np.zeros(384)
    return falso


def _linha(id_, nome, descricao="ja descrita"):
    return {
        "id": id_,
        "folder_id": 1,
        "nome": nome,
        "caminho": f"C:/fotos/{nome}",
        "tipo": "jpg",
        "descricao_ia": descricao,
        "embedding_clip": None,
        "data_adicionado": None,
        "favorito": 0,
        "sbert_score": 0.8,
    }


def _rotas(linhas):
    return {
        "SELECT id, folder_id, nome, caminho": {"fetchall": linhas},
        "COUNT(*) AS n": {"fetchone": {"n": 0}},
    }


def _buscar(client_logado, app_module, linhas, query="praia"):
    with (
        mock.patch.object(app_module, "SBERT_OK", True),
        mock.patch.object(app_module, "_SBERT", _sbert_falso()),
        mock.patch.object(app_module, "_gerar_embedding", lambda t: [0.1] * 384),
    ):
        return client_logado.post("/api/search", json={"query": query})


class TestCriterioDeAceite:
    def test_a_soma_das_fases_bate_com_o_total(self, client_logado, db_roteado, app_module):
        """
        A folga de 0,3 s é o que sobra fora das fases medidas: montagem da
        resposta, filtros em memória, o próprio jsonify. Se a diferença
        crescer, é sinal de que apareceu uma fase cara ainda não instrumentada
        — e é justamente isso que este teste existe para revelar.
        """
        db_roteado(_rotas([_linha(i, f"f{i}.jpg") for i in range(1, 4)]))
        r = _buscar(client_logado, app_module, None)
        assert r.status_code == 200

        fases = dict(app_module._ULTIMAS_FASES)
        total = fases.pop("total")
        soma = sum(v for k, v in fases.items() if not k.endswith("_n"))

        assert total - soma <= 0.3, (
            "sobrou %.2fs fora das fases medidas (total %.2f, soma %.2f): "
            "há fase cara sem instrumentação" % (total - soma, total, soma)
        )

    def test_as_fases_esperadas_aparecem(self, client_logado, db_roteado, app_module):
        db_roteado(_rotas([_linha(1, "f1.jpg")]))
        _buscar(client_logado, app_module, None)
        assert "sql" in app_module._ULTIMAS_FASES
        assert "clip" in app_module._ULTIMAS_FASES
        assert "total" in app_module._ULTIMAS_FASES


class TestOContratoPublicoNaoMuda:
    def test_as_fases_nao_vazam_no_payload_da_busca(self, client_logado, db_roteado, app_module):
        """
        O front lê esta resposta. Um campo novo de diagnóstico ali vira
        contrato sem ninguém decidir isso, e some com a liberdade de mudar a
        medição depois.
        """
        db_roteado(_rotas([_linha(1, "f1.jpg")]))
        corpo = _buscar(client_logado, app_module, None).get_json()

        for proibido in ("fases", "descricao_n", "persistencia", "rerank"):
            assert proibido not in corpo, (
                "%r apareceu no payload de /api/search, que é contrato público" % proibido
            )
        # e o que o front usa continua lá
        for esperado in ("resultados", "tempo", "consulta"):
            assert esperado in corpo

    def test_a_busca_sem_resultado_tambem_e_medida(self, client_logado, db_roteado, app_module):
        """
        A saída antecipada existe, e uma busca lenta que não acha nada é
        exatamente a que se quer investigar.
        """
        db_roteado(_rotas([]))
        corpo = _buscar(client_logado, app_module, None).get_json()
        assert corpo["resultados"] == []
        assert "fases" not in corpo
        assert "sql" in app_module._ULTIMAS_FASES


class TestOLog:
    def test_o_log_sai_com_o_total_e_as_fases(self, client_logado, db_roteado, app_module, capsys):
        """É o que se lê quando a busca está lenta, sem precisar de debug."""
        db_roteado(_rotas([_linha(1, "f1.jpg")]))
        _buscar(client_logado, app_module, None)

        saida = capsys.readouterr().out
        assert "[Busca]" in saida, "nenhuma linha de log da busca"
        assert "sql" in saida

    def test_o_numero_de_descricoes_aparece_junto_da_fase(self, app_module, capsys):
        """
        `descricao 31.2 (5)` — o tempo sozinho não diz se foram cinco chamadas
        lentas ou uma só. Sem o número, a fase não responde nada.
        """
        app_module._registrar_fases(31.4, {"descricao": 31.2, "descricao_n": 5})
        saida = capsys.readouterr().out
        assert "descricao 31.2 (5)" in saida


class TestOEndpointDeDiagnostico:
    def test_o_debug_expoe_a_ultima_medicao(self, app_module):
        """
        A medição precisa ser legível de algum lugar além do terminal — quem
        roda pelo `rodar.bat` não vê o log com facilidade.
        """
        import io
        import os

        raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        fonte = io.open(os.path.join(raiz, "backend", "app.py"), encoding="utf-8").read()

        corpo = fonte[fonte.index("def api_debug_scores") :]
        corpo = corpo[: corpo.index("\n@app.route")]
        assert "_ULTIMAS_FASES" in corpo, (
            "a medição por fase não é legível por lugar nenhum além do log"
        )
