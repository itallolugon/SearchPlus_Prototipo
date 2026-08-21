# -*- coding: utf-8 -*-
"""
Fotografia do ambiente ANTES de a suíte mexer nele.

`tests/conftest.py` precisa apontar `DATABASE_URL` para um DSN de teste, senão
`backend/app.py` nem importa. Só que a trava que impede rodar os testes de banco
contra produção compara a URL de teste com `DATABASE_URL` — e, depois daquela
sobrescrita, as duas são idênticas por construção. A trava passava a bloquear a
si mesma, derrubando o job de Postgres no CI.

Este módulo é importado pelo conftest antes de qualquer alteração, então guarda
o valor verdadeiro: a `DATABASE_URL` da aplicação, se existir. Como o Python
cacheia módulos, a leitura acontece uma única vez, no momento certo.
"""

from __future__ import annotations

import os

# A URL real da aplicação. Vazia quando ninguém a exportou — o caso do CI, que
# sobe um Postgres efêmero e não tem .env algum.
DATABASE_URL_DA_APLICACAO = (os.environ.get("DATABASE_URL") or "").strip()
