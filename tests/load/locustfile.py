# -*- coding: utf-8 -*-
"""
Teste de carga do Search+.

Três perfis, selecionados por `SEARCHPLUS_LOAD_PROFILE`:

    smoke   poucos usuários, ~30s — verifica que o script e o ambiente funcionam
    load    rampa, carga sustentada, descida — uso normal com picos moderados
    stress  rampa progressiva acima do esperado — acha o ponto de degradação

    py -m locust -f tests/load/locustfile.py --headless \\
        --host http://127.0.0.1:5001 -u 2 -r 1 -t 30s

Alvo padrão: o `mock_server` (porta 5001), que responde o mesmo contrato sem
Postgres nem API paga. Apontar para o backend real (5000) mede o motor de
verdade — inclusive as chamadas ao Claude, que custam dinheiro. Faça isso
conscientemente e só em máquina local.

TRAVA DE SEGURANÇA: hosts fora de localhost são recusados, a menos que
`SEARCHPLUS_LOAD_ALLOW_REMOTE=1` seja definido explicitamente. Nunca aponte
para produção.
"""

from __future__ import annotations

import os
import sys
import time
from urllib.parse import urlparse

from locust import HttpUser, LoadTestShape, between, events, task

# ─────────────────────────────────────────────────────────────────────────────
# Configuração — tudo por variável de ambiente, com padrões seguros
# ─────────────────────────────────────────────────────────────────────────────
PERFIL = os.environ.get("SEARCHPLUS_LOAD_PROFILE", "smoke").lower()
USUARIO = os.environ.get("SEARCHPLUS_LOAD_USER", "carga_teste")
SENHA = os.environ.get("SEARCHPLUS_LOAD_PASSWORD", "carga_teste")
PERMITE_REMOTO = os.environ.get("SEARCHPLUS_LOAD_ALLOW_REMOTE") == "1"

# Pasta-mãe usada pela tarefa de coleção vinculada. Contra o MOCK nada é escrito
# em disco, então o valor é só um caminho de fachada. Contra o backend REAL, o
# Python cria subpastas de verdade aqui — aponte para um diretório descartável.
DESTINO_SYNC = os.environ.get("SEARCHPLUS_LOAD_SYNC_DIR", r"C:\Temp\searchplus-carga")

# Limites de aceitação. São referências iniciais: ajuste conforme a máquina e o
# ambiente, documentando a mudança.
MAX_TAXA_ERRO = float(os.environ.get("SEARCHPLUS_LOAD_MAX_ERROR_RATE", "0.01"))  # 1%
MAX_P95_MS = float(os.environ.get("SEARCHPLUS_LOAD_MAX_P95_MS", "1000"))  # 1s
MAX_P95_IA_MS = float(os.environ.get("SEARCHPLUS_LOAD_MAX_P95_IA_MS", "5000"))  # 5s

# Endpoints que dependem de IA toleram p95 maior: uma busca no backend real pode
# chamar o Claude para descrever imagem e para re-ranquear.
NOMES_DEPENDENTES_DE_IA = {"/api/search", "/api/search_by_image"}

CONSULTAS = [
    "cachorro",
    "gato",
    "foto de praia",
    "documento contrato",
    "desenho",
    "paisagem",
    "pessoa sorrindo",
    "gráfico de vendas",
]


@events.init.add_listener
def _validar_alvo(environment, **_kwargs):
    """Recusa alvo remoto: carga contra produção não pode acontecer por engano."""
    host = environment.host or ""
    nome = (urlparse(host).hostname or "").lower()
    local = nome in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
    if not local and not PERMITE_REMOTO:
        print(
            f"\n[CARGA] RECUSADO: host '{host}' não é local.\n"
            "        Teste de carga roda contra ambiente local ou de teste.\n"
            "        Se este é mesmo um ambiente de teste dedicado, defina\n"
            "        SEARCHPLUS_LOAD_ALLOW_REMOTE=1 conscientemente.\n"
        )
        sys.exit(1)


class UsuarioDoSearchPlus(HttpUser):
    """
    Simula o uso real: entra uma vez e depois navega — buscando, filtrando e
    abrindo painéis. A busca pesa mais porque é o que o produto faz.
    """

    wait_time = between(1, 3)
    _contador = 0

    def on_start(self):
        """Uma sessão por usuário virtual, como no navegador."""
        with self.client.post(
            "/api/login",
            json={"username": USUARIO, "password": SENHA},
            catch_response=True,
            name="/api/login",
        ) as r:
            if r.status_code == 200:
                r.success()
            else:
                r.failure(f"login falhou: HTTP {r.status_code}")

    @task(10)
    def buscar(self):
        UsuarioDoSearchPlus._contador += 1
        consulta = CONSULTAS[UsuarioDoSearchPlus._contador % len(CONSULTAS)]
        with self.client.post(
            "/api/search",
            json={"query": consulta, "filtro": "all"},
            catch_response=True,
            name="/api/search",
        ) as r:
            if r.status_code != 200:
                r.failure(f"HTTP {r.status_code}")
            elif "resultados" not in (r.json() or {}):
                r.failure("resposta sem o campo 'resultados'")
            else:
                r.success()

    @task(4)
    def buscar_com_filtro(self):
        filtro = ["imagem", "documento", "midia"][UsuarioDoSearchPlus._contador % 3]
        self.client.post(
            "/api/search",
            json={"query": "foto", "filtro": filtro},
            name="/api/search (filtrado)",
        )

    @task(3)
    def abrir_painel_inicial(self):
        """O front dispara stats e galeria juntos ao abrir a home."""
        self.client.get("/api/stats", name="/api/stats")
        self.client.get("/api/gallery", name="/api/gallery")

    @task(2)
    def listar_colecoes(self):
        self.client.get("/api/collections", name="/api/collections")

    @task(2)
    def validar_sessao(self):
        self.client.get("/api/check_session", name="/api/check_session")

    @task(1)
    def listar_favoritos(self):
        self.client.get("/api/favorites", name="/api/favorites")

    @task(1)
    def consultar_status_do_motor(self):
        self.client.get("/api/status", name="/api/status")

    @task(3)
    def selecionar_tudo_e_adicionar_em_lote(self):
        """
        O fluxo que "selecionar tudo" cria: uma busca, e todos os resultados
        indo de uma vez para uma coleção.

        É a requisição de maior payload do produto — a lista de ids cresce com o
        tamanho do resultado. Medir aqui é o que evita descobrir em produção que
        uma busca com 200 imagens estoura o tempo do INSERT em lote.
        """
        consulta = CONSULTAS[UsuarioDoSearchPlus._contador % len(CONSULTAS)]
        r = self.client.post(
            "/api/search", json={"query": consulta, "filtro": "all"}, name="/api/search"
        )
        if r.status_code != 200:
            return
        ids = [item["id"] for item in (r.json() or {}).get("resultados", []) if item.get("id")]
        if not ids:
            return

        col = self.client.post(
            "/api/collections",
            json={"nome": f"carga-{UsuarioDoSearchPlus._contador}-{time.time_ns()}"},
            name="/api/collections (criar)",
        )
        # 409 = nome repetido; qualquer coisa fora de 200 não dá id para seguir.
        if col.status_code != 200:
            return
        col_id = (col.json() or {}).get("id")
        if not col_id:
            return

        with self.client.post(
            f"/api/collections/{col_id}/files",
            json={"file_ids": ids},
            catch_response=True,
            name="/api/collections/[id]/files (lote)",
        ) as add:
            if add.status_code != 200:
                add.failure(f"HTTP {add.status_code}")
            elif "adicionados" not in (add.json() or {}):
                add.failure("resposta sem o campo 'adicionados'")
            else:
                add.success()

        # A confirmação de exportação imediata relê a coleção para mostrar o
        # total: entra na medição porque acontece a cada adição em lote.
        self.client.get(f"/api/collections/{col_id}", name="/api/collections/[id]")

        # Não deixa lixo acumulando no banco entre execuções.
        self.client.delete(f"/api/collections/{col_id}", name="/api/collections/[id] (excluir)")

    @task(2)
    def colecao_com_pasta_vinculada(self):
        """
        Fluxo da coleção espelhada: vincula uma pasta e adiciona em lote.

        No modo 'auto' cada adição dispara um /sync logo depois do POST em
        /files — é o par de requisições que o usuário passa a fazer o tempo
        todo, então é o que precisa ser medido junto.
        """
        col = self.client.post(
            "/api/collections",
            json={"nome": f"carga-sync-{UsuarioDoSearchPlus._contador}-{time.time_ns()}"},
            name="/api/collections (criar)",
        )
        if col.status_code != 200:
            return
        col_id = (col.json() or {}).get("id")
        if not col_id:
            return

        with self.client.patch(
            f"/api/collections/{col_id}",
            json={"criar_pasta_em": DESTINO_SYNC, "modo_sync": "auto"},
            catch_response=True,
            name="/api/collections/[id] (vincular pasta)",
        ) as vinc:
            if vinc.status_code != 200:
                # Sem a pasta de destino no alvo, o resto da tarefa não se aplica.
                vinc.success()
                self.client.delete(
                    f"/api/collections/{col_id}", name="/api/collections/[id] (excluir)"
                )
                return
            vinc.success()

        consulta = CONSULTAS[UsuarioDoSearchPlus._contador % len(CONSULTAS)]
        r = self.client.post(
            "/api/search", json={"query": consulta, "filtro": "all"}, name="/api/search"
        )
        ids = (
            [item["id"] for item in (r.json() or {}).get("resultados", []) if item.get("id")]
            if r.status_code == 200
            else []
        )
        if not ids:
            self.client.delete(f"/api/collections/{col_id}", name="/api/collections/[id] (excluir)")
            return

        add = self.client.post(
            f"/api/collections/{col_id}/files",
            json={"file_ids": ids},
            name="/api/collections/[id]/files (lote)",
        )
        novos = (add.json() or {}).get("ids_adicionados", ids) if add.status_code == 200 else []

        if novos:
            with self.client.post(
                f"/api/collections/{col_id}/sync",
                json={"file_ids": novos},
                catch_response=True,
                name="/api/collections/[id]/sync",
            ) as sync:
                if sync.status_code != 200:
                    sync.failure(f"HTTP {sync.status_code}")
                elif "copiados" not in (sync.json() or {}):
                    sync.failure("resposta sem o campo 'copiados'")
                else:
                    sync.success()

        self.client.delete(f"/api/collections/{col_id}", name="/api/collections/[id] (excluir)")

    @task(4)
    def abrir_colecao_e_listar_pastas(self):
        """
        Caminho quente: `/folders` é chamado toda vez que uma coleção abre.

        Alimenta o botão "Abrir pasta exportada" e o modal de pastas. Ele lê o
        disco (os.path.isdir + os.listdir por pasta), então é o endpoint de
        coleção mais sensível a I/O — o que justifica o peso maior que as
        tarefas de escrita.
        """
        r = self.client.get("/api/collections", name="/api/collections")
        if r.status_code != 200:
            return
        colecoes = (r.json() or {}).get("colecoes", [])
        if not colecoes:
            return

        # 404 aqui é resposta CORRETA, não falha: entre listar e abrir, outro
        # usuário virtual pode ter excluído a coleção. Marcar como erro faria a
        # taxa de falha medir a concorrência do próprio teste, não o produto.
        col = colecoes[UsuarioDoSearchPlus._contador % len(colecoes)]
        with self.client.get(
            f"/api/collections/{col['id']}", catch_response=True, name="/api/collections/[id]"
        ) as det:
            if det.status_code in (200, 404):
                det.success()
            else:
                det.failure(f"HTTP {det.status_code}")

        with self.client.get(
            f"/api/collections/{col['id']}/folders",
            catch_response=True,
            name="/api/collections/[id]/folders",
        ) as pf:
            if pf.status_code == 404:
                pf.success()  # coleção excluída no meio
            elif pf.status_code != 200:
                pf.failure(f"HTTP {pf.status_code}")
            elif "pastas" not in (pf.json() or {}):
                pf.failure("resposta sem o campo 'pastas'")
            else:
                pf.success()

    @task(1)
    def exportar_colecao_e_acompanhar(self):
        """
        Exportação completa: dispara o job, acompanha o progresso e limpa.

        É a operação mais cara do produto — copia arquivo a arquivo em thread
        separada. O polling entra na medição porque o frontend consulta a cada
        400 ms enquanto a barra está na tela.

        A limpeza no fim usa DELETE /folders, que só aceita caminho registrado
        para a própria coleção: a carga não consegue apagar nada além do que
        ela mesma criou.
        """
        col = self.client.post(
            "/api/collections",
            json={"nome": f"carga-exp-{UsuarioDoSearchPlus._contador}-{time.time_ns()}"},
            name="/api/collections (criar)",
        )
        if col.status_code != 200:
            return
        col_id = (col.json() or {}).get("id")
        if not col_id:
            return

        consulta = CONSULTAS[UsuarioDoSearchPlus._contador % len(CONSULTAS)]
        r = self.client.post(
            "/api/search", json={"query": consulta, "filtro": "all"}, name="/api/search"
        )
        ids = (
            [i["id"] for i in (r.json() or {}).get("resultados", []) if i.get("id")]
            if r.status_code == 200
            else []
        )
        if ids:
            self.client.post(
                f"/api/collections/{col_id}/files",
                json={"file_ids": ids},
                name="/api/collections/[id]/files (lote)",
            )

        exp = self.client.post(
            f"/api/collections/{col_id}/export",
            json={"destino": DESTINO_SYNC},
            catch_response=True,
            name="/api/collections/[id]/export",
        )
        with exp:
            if exp.status_code == 400:
                # Coleção vazia ou destino ausente no alvo: não é falha do teste.
                exp.success()
                self.client.delete(
                    f"/api/collections/{col_id}", name="/api/collections/[id] (excluir)"
                )
                return
            if exp.status_code != 200:
                exp.failure(f"HTTP {exp.status_code}")
                self.client.delete(
                    f"/api/collections/{col_id}", name="/api/collections/[id] (excluir)"
                )
                return
            exp.success()

        job = (exp.json() or {}).get("job_id")
        # Acompanha até concluir, com teto: um job travado não pode prender o
        # usuário virtual para sempre.
        for _ in range(25):
            st = self.client.get(
                f"/api/collections/export/{job}", name="/api/collections/export/[job]"
            )
            if st.status_code != 200:
                break
            if (st.json() or {}).get("estado") != "executando":
                break
            time.sleep(0.4)

        pf = self.client.get(
            f"/api/collections/{col_id}/folders", name="/api/collections/[id]/folders"
        )
        caminhos = (
            [p["caminho"] for p in (pf.json() or {}).get("pastas", [])]
            if pf.status_code == 200
            else []
        )
        if caminhos:
            self.client.delete(
                f"/api/collections/{col_id}/folders",
                json={"caminhos": caminhos, "confirmar": True},
                name="/api/collections/[id]/folders (apagar)",
            )
        self.client.delete(f"/api/collections/{col_id}", name="/api/collections/[id] (excluir)")

    @task(2)
    def readicionar_lote_ja_existente(self):
        """
        Re-adicionar o mesmo lote: o caminho 100% idempotente.

        Custa um INSERT ... ON CONFLICT DO NOTHING que não grava nada. Se este
        ficar lento, o gargalo é o próprio lote — não a escrita.
        """
        # A consulta precisa devolver resultados, senão a tarefa sai sem medir
        # nada — e some silenciosamente do relatório. CONSULTAS é a mesma lista
        # que a task `buscar` usa, então acompanha o acervo do alvo.
        consulta = CONSULTAS[UsuarioDoSearchPlus._contador % len(CONSULTAS)]
        r = self.client.post(
            "/api/search", json={"query": consulta, "filtro": "all"}, name="/api/search"
        )
        if r.status_code != 200:
            return
        ids = [item["id"] for item in (r.json() or {}).get("resultados", []) if item.get("id")]
        if not ids:
            return

        col = self.client.post(
            "/api/collections",
            json={"nome": f"carga-dup-{UsuarioDoSearchPlus._contador}-{time.time_ns()}"},
            name="/api/collections (criar)",
        )
        if col.status_code != 200:
            return
        col_id = (col.json() or {}).get("id")
        if not col_id:
            return

        rota = f"/api/collections/{col_id}/files"
        self.client.post(rota, json={"file_ids": ids}, name="/api/collections/[id]/files (lote)")
        with self.client.post(
            rota,
            json={"file_ids": ids},
            catch_response=True,
            name="/api/collections/[id]/files (lote repetido)",
        ) as dup:
            if dup.status_code != 200:
                dup.failure(f"HTTP {dup.status_code}")
            elif (dup.json() or {}).get("adicionados") != 0:
                dup.failure("re-adicionar duplicou itens na coleção")
            else:
                dup.success()

        self.client.delete(f"/api/collections/{col_id}", name="/api/collections/[id] (excluir)")


# ─────────────────────────────────────────────────────────────────────────────
# Perfis de carga
# ─────────────────────────────────────────────────────────────────────────────
# (segundo_final, usuários, taxa de subida por segundo)
ESTAGIOS: dict[str, list[tuple[int, int, int]]] = {
    # Sobe até 20, sustenta, desce — uso normal com pico moderado.
    "load": [
        (30, 5, 1),  # rampa inicial
        (90, 20, 2),  # carga sustentada
        (150, 20, 2),
        (180, 5, 2),  # descida controlada
    ],
    # Sobe além do esperado até achar onde degrada. Rodar só sob supervisão.
    "stress": [
        (30, 10, 2),
        (60, 30, 3),
        (90, 60, 5),
        (120, 100, 8),
        (150, 150, 10),
    ],
}

# A classe de shape só é DEFINIDA quando o perfil a usa. O Locust encontra
# qualquer LoadTestShape no arquivo e passa a ignorar -u/-r/-t; deixá-la sempre
# presente fazia o smoke encerrar antes da primeira requisição.
if PERFIL in ESTAGIOS:

    class FormaDeCarga(LoadTestShape):
        """Rampa do perfil ativo; None encerra o teste."""

        estagios = ESTAGIOS[PERFIL]

        def tick(self):
            decorrido = self.get_run_time()
            for fim, usuarios, taxa in self.estagios:
                if decorrido < fim:
                    return (usuarios, taxa)
            return None


# ─────────────────────────────────────────────────────────────────────────────
# Verificação dos limites ao final — sai com código 1 se algum for violado
# ─────────────────────────────────────────────────────────────────────────────
@events.quitting.add_listener
def _verificar_limites(environment, **_kwargs):
    estatisticas = environment.stats
    total = estatisticas.total
    problemas: list[str] = []

    if total.num_requests == 0:
        problemas.append("nenhuma requisição executada — o alvo estava no ar?")
    else:
        taxa_erro = total.num_failures / total.num_requests
        if taxa_erro > MAX_TAXA_ERRO:
            problemas.append(f"taxa de erro {taxa_erro:.2%} acima do limite de {MAX_TAXA_ERRO:.2%}")

    for nome, entrada in estatisticas.entries.items():
        if entrada.num_requests == 0:
            continue
        rotulo = nome[0] if isinstance(nome, tuple) else str(nome)
        limite = (
            MAX_P95_IA_MS if any(ia in rotulo for ia in NOMES_DEPENDENTES_DE_IA) else MAX_P95_MS
        )
        p95 = entrada.get_response_time_percentile(0.95)
        if p95 and p95 > limite:
            problemas.append(f"{rotulo}: p95 {p95:.0f}ms acima do limite de {limite:.0f}ms")

    print("\n" + "=" * 70)
    print(f"  PERFIL: {PERFIL}   requisições: {total.num_requests}   falhas: {total.num_failures}")
    if total.num_requests:
        print(f"  p95 geral: {total.get_response_time_percentile(0.95):.0f}ms")
    print("=" * 70)

    if problemas:
        print("  LIMITES VIOLADOS:")
        for p in problemas:
            print(f"    - {p}")
        print("=" * 70)
        environment.process_exit_code = 1
    else:
        print("  Todos os limites respeitados.")
        print("=" * 70)
        environment.process_exit_code = 0
