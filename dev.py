#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Atalhos de desenvolvimento do Search+.

Python não tem o equivalente aos scripts do package.json, então os comandos
ficam aqui — os mesmos que o CI executa, para que "passou local" signifique
"vai passar no CI".

    py dev.py <comando>

    testes        testes unitários e de integração (sem banco)
    unitarios     só os unitários (rápido)
    integracao    só os de integração (contra o mock)
    banco         os que exigem Postgres com pgvector
    cobertura     testes + relatório HTML de cobertura
    observar      re-executa os testes a cada alteração de arquivo
    lint          ruff nos testes (bloqueante) e no backend (informativo)
    formatar      aplica o formatador nos testes
    tipos         verificação de tipos (informativa)
    build         compila os módulos e confere os arquivos do frontend
    mock          sobe o servidor mock na porta 5001
    smoke         teste de carga curto contra o mock
    carga         perfil de carga sustentada (precisa de alvo no ar)
    estresse      perfil de estresse — manual, nunca em produção
    ci            tudo que o CI roda, na mesma ordem

    py dev.py ci
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
PY = [sys.executable]


def _rodar(argumentos: list[str], titulo: str, *, ambiente: dict | None = None) -> int:
    print(f"\n\033[1m>>> {titulo}\033[0m")
    print(f"    {' '.join(argumentos)}\n")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", **(ambiente or {})}
    return subprocess.call(argumentos, cwd=RAIZ, env=env)


def testes() -> int:
    return _rodar(PY + ["-m", "pytest", "tests", "-m", "not requires_db"], "Testes")


def unitarios() -> int:
    return _rodar(PY + ["-m", "pytest", "tests/unit", "-q"], "Testes unitários")


def integracao() -> int:
    return _rodar(
        PY + ["-m", "pytest", "tests/integration", "-m", "not requires_db", "-q"],
        "Testes de integração",
    )


def banco() -> int:
    if not os.environ.get("SEARCHPLUS_TEST_DATABASE_URL"):
        print(
            "\nSEARCHPLUS_TEST_DATABASE_URL não definida.\n"
            "Aponte para um Postgres COM pgvector DEDICADO A TESTES — nunca o de\n"
            "produção: estes testes criam e apagam linhas.\n\n"
            "  docker run --rm -p 5433:5432 -e POSTGRES_PASSWORD=teste \\\n"
            "    -e POSTGRES_DB=searchplus_test pgvector/pgvector:pg16\n\n"
            "  set SEARCHPLUS_TEST_DATABASE_URL=postgresql://postgres:teste@localhost:5433/searchplus_test\n"
        )
        return 1
    return _rodar(PY + ["-m", "pytest", "tests", "-m", "requires_db", "-v"], "Integração com banco")


def cobertura() -> int:
    codigo = _rodar(
        PY + ["-m", "pytest", "tests", "-m", "not requires_db",
              "--cov", "--cov-report=term-missing", "--cov-report=html"],
        "Cobertura",
    )
    destino = RAIZ / "htmlcov" / "index.html"
    if destino.exists():
        print(f"\n  Relatório navegável: {destino}")
    return codigo


def observar() -> int:
    """Re-executa os testes quando algum arquivo muda. Sem dependência extra."""
    print("\n\033[1m>>> Observando alterações (Ctrl+C para sair)\033[0m\n")
    alvos = [RAIZ / "tests", RAIZ / "backend"]
    assinatura_anterior = None
    try:
        while True:
            assinatura = sorted(
                (str(p), p.stat().st_mtime)
                for alvo in alvos
                for p in alvo.rglob("*.py")
                if "__pycache__" not in str(p)
            )
            if assinatura != assinatura_anterior:
                if assinatura_anterior is not None:
                    print("\n\033[1m--- alteração detectada ---\033[0m")
                subprocess.call(
                    PY + ["-m", "pytest", "tests", "-m", "not requires_db", "-q"],
                    cwd=RAIZ,
                    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                )
                assinatura_anterior = assinatura
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nencerrado.")
        return 0


def lint() -> int:
    codigo = _rodar(PY + ["-m", "ruff", "check", "tests/"], "Lint dos testes")
    codigo |= _rodar(PY + ["-m", "ruff", "format", "--check", "tests/"], "Formatação dos testes")
    # Informativo: backend/ é legado e o AGENTS.md pede para não alterá-lo.
    _rodar(PY + ["-m", "ruff", "check", "backend/"], "Lint do backend (informativo)")
    return codigo


def formatar() -> int:
    return _rodar(PY + ["-m", "ruff", "format", "tests/"], "Formatando os testes")


def tipos() -> int:
    _rodar(
        PY + ["-m", "mypy", "backend/app.py", "--ignore-missing-imports"],
        "Verificação de tipos (informativa)",
    )
    return 0


def build() -> int:
    codigo = _rodar(PY + ["-m", "compileall", "-q", "backend/", "tests/"], "Compilando módulos")
    faltando = [
        nome
        for nome in ("index.html", "style.css", "script.js", "landing/index.html")
        if not (RAIZ / nome).exists()
    ]
    if faltando:
        print(f"  arquivos do frontend ausentes: {faltando}")
        return 1
    print("  frontend íntegro")
    return codigo


def mock() -> int:
    return _rodar(PY + ["backend/mock_server.py"], "Servidor mock (porta 5001)")


def _carga(perfil: str, extras: list[str]) -> int:
    alvo = os.environ.get("SEARCHPLUS_LOAD_URL", "http://127.0.0.1:5001")
    return _rodar(
        PY + ["-m", "locust", "-f", "tests/load/locustfile.py", "--headless",
              "--host", alvo, *extras],
        f"Carga — perfil {perfil} contra {alvo}",
        ambiente={"SEARCHPLUS_LOAD_PROFILE": perfil},
    )


def smoke() -> int:
    return _carga("smoke", ["-u", "5", "-r", "1", "-t", "30s", "--only-summary"])


def carga() -> int:
    return _carga("load", ["--only-summary"])


def estresse() -> int:
    print(
        "\n  ATENÇÃO: o perfil de estresse leva a carga muito além do esperado.\n"
        "  Rode apenas contra ambiente local ou dedicado a testes, com alguém\n"
        "  acompanhando. Nunca contra produção.\n"
    )
    if input("  Continuar? [s/N] ").strip().lower() not in {"s", "sim"}:
        print("  cancelado.")
        return 0
    return _carga("stress", ["--only-summary"])


def ci() -> int:
    """A mesma sequência do pipeline, para conferir antes de abrir a PR."""
    etapas = [("Lint", lint), ("Build", build), ("Cobertura", cobertura)]
    falhas = []
    for nome, funcao in etapas:
        if funcao() != 0:
            falhas.append(nome)

    print("\n" + "=" * 62)
    if falhas:
        print(f"  FALHOU: {', '.join(falhas)}")
        print("=" * 62)
        return 1
    print("  Tudo passou. O smoke de carga precisa de um alvo no ar:")
    print("     py dev.py mock      (num terminal)")
    print("     py dev.py smoke     (noutro)")
    print("=" * 62)
    return 0


COMANDOS = {
    "testes": testes,
    "unitarios": unitarios,
    "integracao": integracao,
    "banco": banco,
    "cobertura": cobertura,
    "observar": observar,
    "lint": lint,
    "formatar": formatar,
    "tipos": tipos,
    "build": build,
    "mock": mock,
    "smoke": smoke,
    "carga": carga,
    "estresse": estresse,
    "ci": ci,
}


if __name__ == "__main__":
    escolhido = sys.argv[1] if len(sys.argv) > 1 else ""
    if escolhido not in COMANDOS:
        print(__doc__)
        if escolhido:
            print(f"\nComando desconhecido: {escolhido!r}")
        sys.exit(0 if not escolhido else 2)
    sys.exit(COMANDOS[escolhido]())
