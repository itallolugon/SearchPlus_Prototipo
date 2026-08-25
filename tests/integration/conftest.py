# -*- coding: utf-8 -*-
"""
Fixtures de integração.

Os testes falam HTTP com o `mock_server`, que o próprio repositório mantém como
"versão executável do contrato" descrito em docs/API.md. Isso dá fluxos ponta a
ponta — login, busca, coleções, favoritos — sem Postgres, sem modelo de IA e sem
chave de API, o que os torna executáveis em qualquer máquina e no CI.

O que estes testes NÃO cobrem: o comportamento real do motor de busca (ranking,
pgvector, re-rank do Claude). Isso exige infraestrutura e está em
`test_banco_real.py`, atrás do marker `requires_db`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent.parent / "backend"


@pytest.fixture(scope="session")
def mock_module():
    """Importa `backend/mock_server.py` uma vez por sessão."""
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    import mock_server

    return mock_server


@pytest.fixture()
def api(mock_module):
    """Cliente HTTP anônimo contra a API mock."""
    mock_module.app.config.update(TESTING=True)
    return mock_module.app.test_client()


@pytest.fixture()
def api_logada(api):
    """
    Cliente já autenticado.

    O mock aceita qualquer credencial de propósito — o que se exercita aqui é o
    fluxo (a sessão passa a existir), não a validação de senha, que tem cobertura
    unitária própria em tests/unit/test_autenticacao.py.
    """
    resposta = api.post("/api/login", json={"username": "tester", "password": "qualquer"})
    assert resposta.status_code == 200, "o mock deveria aceitar qualquer login"
    return api
