# -*- coding: utf-8 -*-
"""
Quanto falta para a indexação terminar.

A barra dizia "N na fila". Isso não responde à pergunta que a pessoa tem na
cabeça: dá tempo de almoçar? Um número de arquivos só vira tempo se houver uma
taxa — e a taxa fixa de 0,5s por arquivo erra por ordens de grandeza. Um SSD
com JPEG pequeno e um HD externo com PDF de 300 páginas não têm o mesmo ritmo,
e nem a mesma máquina tem o mesmo ritmo o dia inteiro.

O aceite do item é que a estimativa **converge conforme a indexação avança, em
vez de oscilar**. É isso que a classe TestConvergencia mede.
"""

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture()
def ritmo_limpo(app_module):
    """Zera o histórico antes e depois: ele é global e vaza entre testes."""
    app_module._duracoes.clear()
    yield app_module
    app_module._duracoes.clear()


class TestRitmoObservado:
    def test_sem_medicao_usa_o_padrao(self, ritmo_limpo):
        """
        Antes de qualquer arquivo, a única resposta honesta é a estimativa
        genérica — a mesma que a tela de antes de indexar já usava, para as
        duas não se contradizerem.
        """
        assert ritmo_limpo._ritmo_observado() == ritmo_limpo.SEGUNDOS_POR_ARQUIVO_PADRAO

    def test_poucas_amostras_ainda_usam_o_padrao(self, ritmo_limpo):
        """
        Dois arquivos rápidos anunciariam "1 minuto" para uma pasta de dez mil.
        Amostra pequena não é medição, é coincidência.
        """
        for _ in range(ritmo_limpo._MINIMO_PARA_CONFIAR - 1):
            ritmo_limpo._registrar_duracao(0.01)

        assert ritmo_limpo._ritmo_observado() == ritmo_limpo.SEGUNDOS_POR_ARQUIVO_PADRAO

    def test_com_amostra_suficiente_passa_a_medir(self, ritmo_limpo):
        for _ in range(ritmo_limpo._MINIMO_PARA_CONFIAR):
            ritmo_limpo._registrar_duracao(2.0)

        assert ritmo_limpo._ritmo_observado() == 2.0

    def test_usa_mediana_e_nao_media(self, ritmo_limpo):
        """
        O caso que motivou a escolha: um PDF de 300 páginas no meio de fotos.
        A média saltaria de ~1s para ~18s e a estimativa passaria de "2 min"
        para "40 min" por causa de UM arquivo — exatamente a oscilação que o
        item pede para eliminar.
        """
        for _ in range(9):
            ritmo_limpo._registrar_duracao(1.0)
        ritmo_limpo._registrar_duracao(170.0)          # o monstro

        medido = ritmo_limpo._ritmo_observado()

        assert medido == 1.0
        media = (9 * 1.0 + 170.0) / 10
        assert medido < media / 10

    def test_esquece_o_passado_distante(self, ritmo_limpo):
        """
        Janela deslizante: quem começou numa pasta de vídeos e passou para
        fotos não pode ficar preso à estimativa dos vídeos para sempre.
        """
        for _ in range(ritmo_limpo._JANELA_RITMO):
            ritmo_limpo._registrar_duracao(30.0)
        for _ in range(ritmo_limpo._JANELA_RITMO):
            ritmo_limpo._registrar_duracao(0.4)

        assert ritmo_limpo._ritmo_observado() == 0.4

    def test_duracao_invalida_e_ignorada(self, ritmo_limpo):
        """
        Zero ou negativo só sai de relógio que andou para trás (ajuste de
        horário, sincronização de NTP). Entrando na conta, viraria "arquivo
        instantâneo" e prometeria um fim que não vem.
        """
        for _ in range(ritmo_limpo._MINIMO_PARA_CONFIAR):
            ritmo_limpo._registrar_duracao(2.0)
        ritmo_limpo._registrar_duracao(0)
        ritmo_limpo._registrar_duracao(-5)

        assert ritmo_limpo._ritmo_observado() == 2.0


class TestConvergencia:
    """
    O aceite do item, medido.

    Com ritmo real constante, a estimativa tem que estabilizar. Com um outlier
    no meio, não pode saltar.
    """

    def test_estabiliza_com_ritmo_constante(self, ritmo_limpo):
        estimativas = []
        for i in range(40):
            ritmo_limpo._registrar_duracao(1.2)
            if i >= ritmo_limpo._MINIMO_PARA_CONFIAR:
                estimativas.append(ritmo_limpo._ritmo_observado())

        assert len(set(estimativas)) == 1
        assert estimativas[-1] == 1.2

    def test_um_arquivo_lento_nao_desloca_a_estimativa(self, ritmo_limpo):
        for _ in range(20):
            ritmo_limpo._registrar_duracao(1.0)
        antes = ritmo_limpo._ritmo_observado()

        ritmo_limpo._registrar_duracao(300.0)
        depois = ritmo_limpo._ritmo_observado()

        assert depois == antes

    def test_mudanca_real_de_ritmo_e_acompanhada(self, ritmo_limpo):
        """
        O outro lado: ignorar outlier não pode virar ignorar a realidade. Se a
        indexação DE FATO ficou lenta, a estimativa tem que subir.
        """
        for _ in range(ritmo_limpo._JANELA_RITMO):
            ritmo_limpo._registrar_duracao(1.0)
        rapido = ritmo_limpo._ritmo_observado()

        for _ in range(ritmo_limpo._JANELA_RITMO):
            ritmo_limpo._registrar_duracao(8.0)

        assert ritmo_limpo._ritmo_observado() > rapido * 4

    def test_o_texto_e_grosso_e_nao_acompanha_cada_arquivo(self, ritmo_limpo):
        """
        Uma fila de 1800 arquivos passa por 1800 estados. O usuário não pode
        ver 1800 textos.

        O limite não é arbitrário: acima de 10 min o texto anda de 5 em 5
        (30, 25, 20, 15), abaixo de 10 anda de 1 em 1 (9 até 1), e abaixo de
        1 min vira "quase terminando" — cerca de 16 valores possíveis em toda
        a descida. Vinte dá folga para mexer nas faixas sem reescrever o
        teste, e ainda pega qualquer volta ao texto por segundo.
        """
        vistos = [ritmo_limpo._texto_do_restante(p, 1.0)
                  for p in range(1800, 0, -1)]
        trocas = sum(1 for a, b in zip(vistos, vistos[1:]) if a != b)

        assert trocas <= 20, f"o texto mudou {trocas} vezes drenando a fila"

    def test_o_texto_nunca_volta_atras(self, ritmo_limpo):
        """
        Monotonia de verdade: com a fila encolhendo e o ritmo constante, cada
        texto aparece num bloco contínuo e nunca reaparece depois de ter sido
        substituído. Estimativa que sobe sozinha é o que mais destrói a
        confiança numa barra de progresso.
        """
        vistos = [ritmo_limpo._texto_do_restante(p, 1.0)
                  for p in range(1800, 0, -1)]

        ja_encerrados = set()
        anterior = None
        for texto in vistos:
            if texto != anterior:
                assert texto not in ja_encerrados, f"o texto voltou para {texto!r}"
                if anterior is not None:
                    ja_encerrados.add(anterior)
                anterior = texto

        assert vistos[-1] == "quase terminando"


class TestComoAPessoaLe:
    @pytest.mark.parametrize("pendentes,segundos,esperado", [
        (0,    1.0, ""),                          # nada na fila, nada a dizer
        (10,   1.0, "quase terminando"),          # menos de 1 min
        (59,   1.0, "quase terminando"),
        (120,  1.0, "≈ 2 min restantes"),
        (300,  1.0, "≈ 5 min restantes"),
        (1500, 1.0, "≈ 25 min restantes"),        # de 5 em 5 acima de 10 min
        (5400, 1.0, "≈ 1 hora restante"),
        (18000, 1.0, "≈ 5 horas restantes"),
    ])
    def test_faixas(self, app_module, pendentes, segundos, esperado):
        assert app_module._texto_do_restante(pendentes, segundos) == esperado

    def test_fila_negativa_nao_inventa_texto(self, app_module):
        assert app_module._texto_do_restante(-3, 1.0) == ""

    def test_nao_usa_jargao(self, app_module):
        for pendentes in (10, 200, 2000, 20000):
            texto = app_module._texto_do_restante(pendentes, 1.0).lower()
            for jargao in ("embedding", "clip", "sbert", "throughput", "queue"):
                assert jargao not in texto


class TestNoStatus:
    def test_status_traz_a_estimativa(self, client_logado, db_roteado):
        db_roteado({"COUNT(*) AS n": {"fetchone": {"n": 12}}})
        corpo = client_logado.get("/api/status").get_json()

        assert "restante_texto" in corpo
        assert "segundos_por_arquivo" in corpo

    def test_fila_vazia_nao_promete_nada(self, client_logado, db_roteado):
        db_roteado({"COUNT(*) AS n": {"fetchone": {"n": 12}}})
        corpo = client_logado.get("/api/status").get_json()

        assert corpo["arquivos_pendentes"] == 0
        assert corpo["restante_texto"] == ""

    def test_sem_sessao_continua_respondendo_ocioso(self, client, db_roteado):
        """
        O status é consultado antes do login para desenhar a barra; virar 401
        aqui quebraria a tela inicial.
        """
        db_roteado({})
        r = client.get("/api/status")
        assert r.status_code == 200
        assert r.get_json()["arquivos_pendentes"] == 0


class TestSoContaOQueFoiProcessado:
    def test_arquivo_devolvido_a_fila_nao_entra_na_conta(self, app_module):
        """
        Arquivo fora da janela de horário volta para a fila sem ter gasto
        tempo de processamento. Contado, entraria como "arquivo instantâneo" e
        puxaria a estimativa para baixo, prometendo um fim que não vem.
        """
        import inspect
        fonte = inspect.getsource(app_module._process_worker)

        pos_registro = fonte.index("_registrar_duracao")
        pos_reenfileira = fonte.index("_queue.put(item)")
        assert pos_reenfileira < pos_registro, (
            "o re-enfileiramento tem que sair antes do registro de duração")
