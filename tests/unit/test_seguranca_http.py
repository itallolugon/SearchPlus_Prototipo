# -*- coding: utf-8 -*-
"""
Travas de rede e de entrada do backend.

O Search+ roda na máquina do usuário e serve arquivos do disco dele. Por isso
o que importa aqui é o que o servidor RECUSA:

- Host desconhecido: é o que denuncia DNS rebinding, o truque que faz um site
  conversar com 127.0.0.1 como se fosse a mesma origem;
- origem "null" no CORS: liberada com credenciais, entregava a API a qualquer
  iframe com sandbox;
- arquivo do usuário servido como página: um .html na pasta monitorada rodaria
  script na origem do app;
- mensagem de exceção na resposta pública do cadastro;
- configuração de pasta fora do formato esperado.
"""

import hashlib
import os
import re
import subprocess
from pathlib import Path

import flask
import pytest

pytestmark = pytest.mark.unit

SCHEMA = Path(__file__).resolve().parent.parent.parent / "backend" / "schema.sql"


def _pastas(*caminhos):
    """Rota do db_roteado para a lista de pastas monitoradas do usuário."""
    return {"SELECT path FROM folders": {"fetchall": [{"path": str(p)} for p in caminhos]}}


def _junction(atalho: Path, destino: Path) -> bool:
    """Cria uma junction (Windows, sem privilégio). Devolve se deu certo."""
    subprocess.run(
        ["cmd", "/d", "/c", "mklink", "/J", str(atalho), str(destino)], capture_output=True
    )
    return atalho.exists()


def _servir(flask_app, app_module, caminho):
    """
    Chama a view de /api/file direto e devolve (status, cabeçalhos).

    Direto, e não pela rota: no Linux do CI o caminho absoluto começa com '/', e
    o conversor <path:> do Flask não aceita barra inicial. A resposta é fechada
    aqui para não deixar o arquivo preso — no Windows isso impede apagar o tmp.
    """
    with flask_app.test_request_context():
        flask.session["user_id"] = 4242
        resposta = flask_app.make_response(app_module.api_serve_file(str(caminho)))
        resposta.close()
        return resposta.status_code, resposta.headers


# ──────────────────────────────────────────────────────────────────────────────
# Host (anti DNS rebinding)
# ──────────────────────────────────────────────────────────────────────────────


class TestHost:
    @pytest.mark.parametrize(
        "host", ["127.0.0.1:5000", "localhost:5000", "localhost", "LOCALHOST:5000", "[::1]:5000"]
    )
    def test_nomes_locais_passam(self, app_module, host):
        assert app_module._host_permitido(host) is True

    @pytest.mark.parametrize(
        "host",
        [
            "evil.example",
            "evil.example:5000",
            "127.0.0.1.evil.example:5000",
            "localhost.evil.example",
            "",
        ],
    )
    def test_outros_nomes_sao_recusados(self, app_module, host):
        assert app_module._host_permitido(host) is False

    def test_rota_publica_recusa_host_desconhecido(self, client):
        r = client.get("/api/health", base_url="http://evil.example:5000")
        assert r.status_code == 400
        assert "ALLOWED_HOSTS" in r.get_json()["error"]

    def test_login_tambem_e_recusado(self, client):
        """O ataque começa criando conta e logando — a trava vale antes disso."""
        r = client.post(
            "/api/login",
            json={"username": "a", "password": "b"},
            base_url="http://evil.example:5000",
        )
        assert r.status_code == 400

    def test_host_local_continua_atendido(self, client):
        assert client.get("/api/health", base_url="http://127.0.0.1:5000").status_code == 200

    def test_host_do_env_e_aceito(self, client, app_module, monkeypatch):
        monkeypatch.setattr(
            app_module, "ALLOWED_HOSTS", app_module.ALLOWED_HOSTS | {"searchplus.exemplo"}
        )
        r = client.get("/api/health", base_url="http://searchplus.exemplo")
        assert r.status_code == 200


# ──────────────────────────────────────────────────────────────────────────────
# CORS e cabeçalhos
# ──────────────────────────────────────────────────────────────────────────────


class TestCorsECabecalhos:
    def test_origem_null_nao_recebe_permissao(self, client):
        r = client.get("/api/health", headers={"Origin": "null"})
        assert "Access-Control-Allow-Origin" not in r.headers

    def test_origem_de_dev_server_continua_liberada(self, client):
        r = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
        assert r.headers.get("Access-Control-Allow-Origin") == "http://localhost:5173"

    def test_site_qualquer_nao_recebe_permissao(self, client):
        r = client.get("/api/health", headers={"Origin": "https://evil.example"})
        assert "Access-Control-Allow-Origin" not in r.headers

    def test_cabecalhos_de_seguranca_em_toda_resposta(self, client):
        r = client.get("/api/health")
        assert r.headers["X-Frame-Options"] == "SAMEORIGIN"
        assert r.headers["Referrer-Policy"] == "same-origin"


# ──────────────────────────────────────────────────────────────────────────────
# /api/file
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def monitorada(tmp_path):
    pasta = tmp_path / "Fotos"
    pasta.mkdir()
    (pasta / "pagina.html").write_text("<script>alert(1)</script>", encoding="utf-8")
    (pasta / "foto.jpg").write_bytes(b"\xff\xd8\xff")
    (pasta / "manual.pdf").write_bytes(b"%PDF-1.4")
    return pasta


class TestArquivoDoUsuario:
    def test_html_sai_em_sandbox_e_sem_adivinhar_tipo(
        self, flask_app, app_module, db_roteado, monitorada
    ):
        db_roteado(_pastas(monitorada))
        status, cab = _servir(flask_app, app_module, monitorada / "pagina.html")
        assert status == 200
        assert cab["Content-Security-Policy"] == "sandbox"
        assert cab["X-Content-Type-Options"] == "nosniff"

    def test_imagem_tambem_vai_em_sandbox(self, flask_app, app_module, db_roteado, monitorada):
        db_roteado(_pastas(monitorada))
        status, cab = _servir(flask_app, app_module, monitorada / "foto.jpg")
        assert status == 200
        assert cab["Content-Security-Policy"] == "sandbox"

    def test_pdf_fica_fora_do_sandbox(self, flask_app, app_module, db_roteado, monitorada):
        """O leitor de PDF do navegador não abre em documento com sandbox."""
        db_roteado(_pastas(monitorada))
        status, cab = _servir(flask_app, app_module, monitorada / "manual.pdf")
        assert status == 200
        assert "Content-Security-Policy" not in cab
        assert cab["X-Content-Type-Options"] == "nosniff"

    def test_fora_das_pastas_da_403_mesmo_se_nao_existir(
        self, flask_app, app_module, db_roteado, monitorada, tmp_path
    ):
        """404 aqui diria a quem pedisse se um arquivo qualquer do disco existe."""
        db_roteado(_pastas(monitorada))
        status, _ = _servir(flask_app, app_module, tmp_path / "nao-existe.txt")
        assert status == 403

    def test_fora_das_pastas_e_existente_da_403(
        self, flask_app, app_module, db_roteado, monitorada, tmp_path
    ):
        segredo = tmp_path / "segredo.txt"
        segredo.write_text("chave", encoding="utf-8")
        db_roteado(_pastas(monitorada))
        assert _servir(flask_app, app_module, segredo)[0] == 403

    def test_dentro_das_pastas_e_ausente_da_404(
        self, flask_app, app_module, db_roteado, monitorada
    ):
        db_roteado(_pastas(monitorada))
        assert _servir(flask_app, app_module, monitorada / "sumiu.jpg")[0] == 404

    def test_travessia_com_pontos(self, flask_app, app_module, db_roteado, monitorada, tmp_path):
        (tmp_path / "segredo.txt").write_text("chave", encoding="utf-8")
        db_roteado(_pastas(monitorada))
        alvo = f"{monitorada}{os.sep}..{os.sep}segredo.txt"
        assert _servir(flask_app, app_module, alvo)[0] == 403

    @pytest.mark.skipif(os.name != "nt", reason="junction é específica do Windows")
    def test_atalho_dentro_da_pasta_apontando_para_fora(
        self, flask_app, app_module, db_roteado, monitorada, tmp_path
    ):
        """O caminho escrito fica dentro; o destino, não. Só realpath pega."""
        fora = tmp_path / "Secreto"
        fora.mkdir()
        (fora / "chave.txt").write_text("segredo", encoding="utf-8")
        if not _junction(monitorada / "atalho", fora):
            pytest.skip("não foi possível criar junction neste ambiente")

        db_roteado(_pastas(monitorada))
        assert _servir(flask_app, app_module, monitorada / "atalho" / "chave.txt")[0] == 403

    def test_rota_exige_sessao(self, client):
        assert client.get("/api/file/C:%5Cqualquer%5Cpagina.html").status_code == 401


class TestDentroDasPastas:
    @pytest.mark.skipif(os.name != "nt", reason="junction é específica do Windows")
    def test_pasta_monitorada_que_e_atalho_continua_funcionando(self, app_module, tmp_path):
        """Resolver só o lado do arquivo faria nada casar dentro da pasta-atalho."""
        real = tmp_path / "Real"
        real.mkdir()
        (real / "a.jpg").write_bytes(b"x")
        atalho = tmp_path / "Atalho"
        if not _junction(atalho, real):
            pytest.skip("não foi possível criar junction neste ambiente")

        assert app_module._dentro_das_pastas(str(atalho / "a.jpg"), [str(atalho)]) is True

    def test_unidade_inteira_monitorada_autoriza(self, app_module, tmp_path):
        """'C:\\' monitorado virava 'c:\\\\' e não autorizava arquivo nenhum."""
        alvo = tmp_path / "a.jpg"
        alvo.write_bytes(b"x")
        raiz = Path(os.path.realpath(tmp_path)).anchor
        assert app_module._dentro_das_pastas(str(alvo), [raiz]) is True

    def test_vizinha_com_prefixo_parecido_segue_recusada(self, app_module, tmp_path):
        (tmp_path / "Fotos").mkdir()
        (tmp_path / "Fotos_privado").mkdir()
        alvo = tmp_path / "Fotos_privado" / "a.jpg"
        alvo.write_bytes(b"x")
        assert app_module._dentro_das_pastas(str(alvo), [str(tmp_path / "Fotos")]) is False


# ──────────────────────────────────────────────────────────────────────────────
# Cadastro e login
# ──────────────────────────────────────────────────────────────────────────────

PISTAS_DO_BANCO = ("supabase", "10.0.0.7", "5432", "postgres")
ERRO_DO_DRIVER = (
    'connection to server at "db.exemplo.supabase.co" (10.0.0.7), port 5432 failed: '
    'FATAL: password authentication failed for user "postgres"'
)


class TestCadastroNaoVazaInfraestrutura:
    def _sem_pistas(self, resposta):
        corpo = resposta.get_data(as_text=True).lower()
        return [p for p in PISTAS_DO_BANCO if p in corpo]

    def test_falha_de_conexao(self, client, app_module, monkeypatch):
        def _quebra():
            raise Exception(ERRO_DO_DRIVER)

        monkeypatch.setattr(app_module, "get_db", _quebra)
        r = client.post("/api/register", json={"username": "u", "password": "senha"})
        assert r.status_code == 500
        assert not self._sem_pistas(r), "a resposta pública vazou dado do banco"

    def test_falha_ao_gravar(self, client, db_falso):
        _, conexao = db_falso
        conexao.execute.side_effect = Exception(ERRO_DO_DRIVER)
        r = client.post("/api/register", json={"username": "u", "password": "senha"})
        assert r.status_code == 500
        assert not self._sem_pistas(r), "a resposta pública vazou dado do banco"


class TestHashLegado:
    def test_hash_com_caractere_estranho_nao_estoura(self, app_module):
        """Valor corrompido no banco é senha errada, não 500."""
        assert app_module._verificar_senha("x", "ççç-não-é-hash") is False

    def test_legado_com_senha_errada_segue_recusado(self, app_module):
        legado = hashlib.sha256(b"antiga").hexdigest()
        assert app_module._verificar_senha("antigA", legado) is False


class TestLoginComecaComSessaoLimpa:
    def test_nada_da_sessao_anterior_atravessa_o_login(self, client, db_roteado, app_module):
        usuario = {"id": 7, "password_hash": app_module._hash("s3nha")}
        db_roteado({"FROM users WHERE username": {"fetchone": usuario}})
        with client.session_transaction() as sessao:
            sessao["user_id"] = 99
            sessao["resto_de_outra_conta"] = "x"

        r = client.post("/api/login", json={"username": "ana", "password": "s3nha"})

        assert r.status_code == 200
        with client.session_transaction() as sessao:
            assert sessao["user_id"] == 7
            assert "resto_de_outra_conta" not in sessao


# ──────────────────────────────────────────────────────────────────────────────
# Configuração de pasta
# ──────────────────────────────────────────────────────────────────────────────


class TestConfigDePasta:
    @pytest.mark.parametrize(
        "campo,valor",
        [
            ("perfil_analise", "turbo"),
            ("perfil_analise", ["fast"]),
            ("janela_processamento", "sempre"),
            ("janela_processamento", "25:00-06:00"),
            ("janela_processamento", 5),
            ("prioridades", "tudo"),
            ("prioridades", []),
            ("prioridades", ["tudo", {"x": 1}]),
            ("prioridades", ["carros"]),
        ],
    )
    def test_cadastro_recusa_configuracao_fora_do_formato(
        self, client_logado, tmp_path, campo, valor
    ):
        r = client_logado.post("/api/folders", json={"pasta": str(tmp_path), campo: valor})
        assert r.status_code == 400, r.get_json()

    @pytest.mark.parametrize("janela", ["always", "02:00-06:00", "22:30-6:00"])
    def test_janelas_que_o_front_manda_passam(self, client_logado, db_roteado, tmp_path, janela):
        db_roteado({})
        r = client_logado.post(
            "/api/folders",
            json={
                "pasta": str(tmp_path),
                "prioridades": ["pessoas", "animais"],
                "perfil_analise": "deep",
                "janela_processamento": janela,
            },
        )
        assert r.status_code == 200, r.get_json()

    def test_update_config_recusa_id_que_nao_e_numero(self, client_logado, db_roteado):
        db_roteado({})
        r = client_logado.post(
            "/api/folders/update_config", json={"id": "abc", "perfil_analise": "deep"}
        )
        assert r.status_code == 400

    def test_update_config_recusa_perfil_invalido(self, client_logado, db_roteado):
        db_roteado({})
        r = client_logado.post(
            "/api/folders/update_config", json={"id": 1, "perfil_analise": "turbo"}
        )
        assert r.status_code == 400

    def test_update_config_valido(self, client_logado, db_roteado):
        db_roteado({})
        r = client_logado.post(
            "/api/folders/update_config",
            json={"id": 1, "perfil_analise": "deep", "janela_processamento": "22:00-06:00"},
        )
        assert r.status_code == 200


# ──────────────────────────────────────────────────────────────────────────────
# Tamanho do corpo
# ──────────────────────────────────────────────────────────────────────────────


class TestTetoDoCorpo:
    def test_teto_cabe_a_maior_imagem_aceita(self, flask_app):
        """20 MB de imagem viram ~27 MB em base64: o teto não pode barrar isso."""
        assert flask_app.config["MAX_CONTENT_LENGTH"] >= 28 * 1024 * 1024

    def test_corpo_acima_do_teto_responde_413_em_json(self, client_logado, flask_app, monkeypatch):
        monkeypatch.setitem(flask_app.config, "MAX_CONTENT_LENGTH", 100)
        r = client_logado.post("/api/config", json={"perfil_bio": "x" * 1000})
        assert r.status_code == 413
        assert "error" in r.get_json()


# ──────────────────────────────────────────────────────────────────────────────
# Row Level Security no schema
# ──────────────────────────────────────────────────────────────────────────────


class TestRlsNoSchema:
    def test_toda_tabela_criada_entra_na_lista_da_rls(self):
        """
        Tabela nova sem RLS fica aberta pela API REST do Supabase. A lista do
        bloco DO precisa crescer junto com os CREATE TABLE.
        """
        sql = SCHEMA.read_text(encoding="utf-8")
        criadas = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", sql))
        bloco = re.search(r"FOREACH tabela IN ARRAY ARRAY\[(.*?)\]", sql, re.S)
        assert bloco, "o schema perdeu o bloco que liga a RLS"
        com_rls = set(re.findall(r"'(\w+)'", bloco.group(1)))
        assert criadas, "premissa: o schema cria tabelas"
        assert criadas <= com_rls, f"tabelas sem RLS: {sorted(criadas - com_rls)}"


class TestCaminhoComByteNulo:
    """
    No Linux, realpath levanta ValueError com byte nulo, e as rotas que o
    chamavam viravam 500. O byte nulo é recusado de saída (mesma resposta em
    qualquer SO); o ValueError que sobrar é simulado, para valer no Windows.
    """

    PASTA = os.path.join(os.sep, "Fotos")

    @pytest.fixture()
    def realpath_que_levanta(self, app_module, monkeypatch):
        def _levanta(_caminho, *a, **k):
            raise ValueError("lstat: embedded null character in path")

        monkeypatch.setattr(app_module.os.path, "realpath", _levanta)

    def test_byte_nulo_nao_e_caminho(self, app_module):
        assert app_module._caminho_real("a\x00b") is None
        assert app_module._dentro_das_pastas("a\x00b", [self.PASTA]) is False

    def test_arquivo_com_byte_nulo_responde_404(self, flask_app, app_module, db_roteado):
        db_roteado(_pastas(self.PASTA))
        assert _servir(flask_app, app_module, "a\x00b")[0] == 404

    def test_abrir_local_com_byte_nulo_responde_400(self, client_logado, db_roteado):
        db_roteado(_pastas(self.PASTA))
        assert client_logado.get("/api/open_location?path=a%00b").status_code == 400

    def test_valueerror_do_realpath_vira_recusa(
        self, flask_app, app_module, db_roteado, realpath_que_levanta
    ):
        alvo = os.path.join(self.PASTA, "a.jpg")
        assert app_module._dentro_das_pastas(alvo, [self.PASTA]) is False
        db_roteado(_pastas(self.PASTA))
        assert _servir(flask_app, app_module, alvo)[0] == 404
