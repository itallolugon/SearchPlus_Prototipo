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
    """A mesma proteção, agora atravessando a rota HTTP de verdade."""

    @pytest.mark.parametrize(
        "rota", ["/backend/.env", "/.git/config", "/backend/app.py", "/backend/requirements.txt"]
    )
    def test_rota_nao_entrega_segredo(self, client, rota):
        resposta = client.get(rota)
        assert resposta.status_code != 200, f"{rota} foi servido!"

    def test_conteudo_do_env_nunca_aparece_no_corpo(self, client):
        """Mesmo num fallback de SPA, o conteúdo do .env não pode vazar."""
        corpo = client.get("/backend/.env").get_data(as_text=True)
        assert "DATABASE_URL" not in corpo
        assert "ANTHROPIC_API_KEY" not in corpo

    @pytest.mark.parametrize(
        "rota",
        [
            "/../backend/.env",
            "/..%2Fbackend%2F.env",
            "/landing/../backend/.env",
        ],
    )
    def test_traversal_nao_escapa_da_pasta(self, client, rota):
        assert client.get(rota).status_code != 200
