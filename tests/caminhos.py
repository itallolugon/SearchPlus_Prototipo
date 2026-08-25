# -*- coding: utf-8 -*-
"""
Caminhos absolutos no estilo da plataforma onde a suíte está rodando.

O Search+ roda no Windows, então é natural escrever `C:\\Fotos\\gato.jpg` nos
testes. Só que o CI roda em Linux, onde `os.path.normpath` não reconhece a barra
invertida como separador: `_prefixo_pasta(r"C:\\Fotos")` devolve `c:\\fotos/` e
nenhuma comparação de prefixo casa.

Isso não é defeito do backend — é o teste amarrado a uma plataforma. O helper
monta o caminho com o separador nativo, então a MESMA regra é exercitada nos
dois sistemas:

    caminho("Fotos", "gato.jpg")
    # Windows -> C:\\Fotos\\gato.jpg
    # Linux   -> /Fotos/gato.jpg
"""

from __future__ import annotations

import os

# Raiz absoluta da plataforma. No Windows o app sempre lida com caminho de
# unidade; no Linux, com a barra inicial.
RAIZ = "C:\\" if os.name == "nt" else "/"


def caminho(*partes: str) -> str:
    """Junta as partes em um caminho absoluto no estilo da plataforma atual."""
    return os.path.join(RAIZ, *partes)


def caminho_alterando_caixa(*partes: str) -> str:
    """
    O mesmo caminho, com a caixa trocada.

    Serve para o cenário que já duplicou o índice em produção: no Windows
    `C:\\Fotos` e `c:\\fotos` são a mesma pasta, mas o UNIQUE do Postgres as
    trata como distintas.
    """
    return caminho(*partes).upper()
