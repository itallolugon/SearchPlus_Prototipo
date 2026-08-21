# -*- coding: utf-8 -*-
"""
Servir arquivos do frontend é uma ALLOWLIST, não uma blocklist.

A pasta servida é a raiz do projeto, que contém `backend/.env` (senha do banco e
chave de API), `.git/` e o código do servidor. `_pode_servir` só libera extensão
conhecidamente pública e recusa dotfile e pasta privada. Transformar isso numa
blocklist tornaria público por padrão todo arquivo novo — daí a bateria abaixo.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


class TestArquivosPublicos:
    @pytest.mark.parametrize(
        "caminho",
        [
            "index.html",
            "style.css",
            "script.js",
            "landing/index.html",
            "landing/style.css",
            "fonts/BebasNeue-Regular.ttf",
            "landing/img/dog1.jpg",
        ],
    )
    def test_libera_asset_do_frontend(self, app_module, caminho):
        assert app_module._pode_servir(Path(caminho)) is True


class TestSegredosBloqueados:
    @pytest.mark.parametrize(
        "caminho,motivo",
        [
            ("backend/.env", "senha do Postgres e chave da Anthropic"),
            ("backend/app.py", "código do servidor"),
            ("backend/mock_server.py", "código do servidor"),
            ("backend/requirements.txt", "pasta privada"),
            (".git/config", "pode conter credencial de remote"),
            (".gitignore", "dotfile"),
            ("docs/API.md", "pasta privada"),
            ("__pycache__/app.cpython-314.pyc", "pasta privada"),
            ("node_modules/pacote/index.js", "pasta privada"),
        ],
    )
    def test_recusa_arquivo_privado(self, app_module, caminho, motivo):
        assert app_module._pode_servir(Path(caminho)) is False, f"vazou: {motivo}"

    def test_recusa_dotfile_mesmo_com_extensao_publica(self, app_module):
        """A extensão ser pública não basta: dotfile é sempre recusado."""
        assert app_module._pode_servir(Path(".oculto.css")) is False

    def test_recusa_dotfile_em_subpasta(self, app_module):
        assert app_module._pode_servir(Path("landing/.env.local")) is False


class TestExtensoesDesconhecidas:
    @pytest.mark.parametrize(
        "caminho",
        ["config.yaml", "dump.sql", "backup.db", "script.sh", "app.exe", "chave.pem"],
    )
    def test_extensao_fora_da_allowlist_e_recusada(self, app_module, caminho):
        assert app_module._pode_servir(Path(caminho)) is False

    def test_arquivo_sem_extensao_e_recusado(self, app_module):
        assert app_module._pode_servir(Path("Procfile")) is False


class TestServeStaticPelaRota:
    """
    A mesma proteção, agora atravessando a rota HTTP de verdade.

    Um detalhe descoberto quando o CI rodou pela primeira vez: o status sozinho
    NÃO serve de asserção aqui. Para um arquivo que não existe, `serve_static`
    cai no fallback da SPA e devolve o index.html com 200 — comportamento
    correto, necessário para o roteamento do frontend. E `Path(".env").suffix`
    é vazio (dotfile não tem extensão para o Python), então `/backend/.env`
    entra nesse fallback justamente onde o arquivo não existe: na máquina de
    desenvolvimento ele está presente e dá 404; no CI, é gitignored e some.

    Por isso a garantia é sobre o CORPO: nunca pode conter o segredo. Quando o
    arquivo privado existe de fato (os versionados abaixo), aí sim o status é
    checado.
    """

    # Arquivos privados que estão no Git, logo existem em qualquer ambiente.
    PRIVADOS_VERSIONADOS = [
        "/backend/app.py",
        "/backend/mock_server.py",
        "/backend/requirements.txt",
        "/backend/schema.sql",
        "/docs/API.md",
    ]

    @pytest.mark.parametrize("rota", PRIVADOS_VERSIONADOS)
    def test_arquivo_privado_existente_e_recusado(self, client, rota):
        assert client.get(rota).status_code != 200, f"{rota} foi servido!"

    @pytest.mark.parametrize("rota", PRIVADOS_VERSIONADOS)
    def test_corpo_nunca_traz_o_codigo_do_servidor(self, client, rota):
        corpo = client.get(rota).get_data(as_text=True)
        assert "ANTHROPIC_API_KEY" not in corpo
        assert "def api_login" not in corpo
        assert "DATABASE_URL" not in corpo

    @pytest.mark.parametrize(
        "rota",
        [
            "/backend/.env",
            "/../backend/.env",
            "/..%2Fbackend%2F.env",
            "/landing/../backend/.env",
            "/.git/config",
        ],
    )
    def test_credenciais_nunca_aparecem_no_corpo(self, client, rota):
        """
        Vale existindo o arquivo ou não: com ele presente vem 404; ausente, vem
        o index.html da SPA. Em nenhum dos casos o segredo pode sair.
        """
        corpo = client.get(rota).get_data(as_text=True)
        for marcador in ("DATABASE_URL", "ANTHROPIC_API_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
            assert marcador not in corpo, f"{rota} vazou {marcador}"

    def test_traversal_nao_alcanca_arquivo_privado_existente(self, client):
        """Subir de pasta com '..' não pode contornar a allowlist."""
        assert client.get("/landing/../backend/app.py").status_code != 200
