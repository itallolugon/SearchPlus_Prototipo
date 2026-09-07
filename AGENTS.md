# Instruções para agentes de IA neste repositório

Leia este arquivo antes de alterar qualquer coisa.

## O que é este projeto

**Search+** — busca semântica em imagens e documentos locais. Backend em Flask (Python) com busca vetorial, IA de visão e Postgres; frontend em HTML/CSS/JS puro, sem build.

Visão geral do produto e do pipeline de busca: [README.md](README.md).

---

## Se a tarefa é construir ou substituir o frontend

**Leia [docs/FRONTEND.md](docs/FRONTEND.md) antes de escrever qualquer código.** Ele contém o inventário do que pode ser substituído, os fluxos que a interface precisa entregar e os detalhes que causam bug se ignorados.

O resumo operacional:

```bash
py -m pip install flask flask-cors
py backend/mock_server.py     # http://127.0.0.1:5001
```

Isso sobe a API **e** o aplicativo atual com dados fictícios — sem Postgres, sem modelos de IA, sem chave de API. Qualquer usuário e senha entram. É o ambiente para desenvolver e testar a nova interface.

Três documentos, três finalidades:

| Arquivo | Para quê |
|---|---|
| [docs/FRONTEND.md](docs/FRONTEND.md) | O que construir e o que não tocar |
| [docs/API.md](docs/API.md) | Contrato de cada endpoint: payload, resposta, erros |
| `index.html`, `script.js`, `style.css` | O protótipo atual — especificação viva do comportamento |

**Explore o aplicativo rodando antes de reescrever.** O protótipo já resolve fluxos que nenhum documento captura por completo: separação dos resultados em faixas de relevância, painel lateral de detalhe, onboarding de pastas, galeria por categoria. O visual é livre; as funcionalidades não.

---

## Regras que valem para qualquer tarefa

**Não altere `backend/`.** `app.py`, `mock_server.py` e `schema.sql` são o motor compartilhado com a versão em produção. Se uma mudança de interface parecer exigir alteração no backend, quase sempre o endpoint necessário já existe — confira `docs/API.md` primeiro. Havendo necessidade real, descreva a proposta em vez de aplicá-la.

**Nunca crie nem preencha `backend/.env`.** Ele guarda a senha do banco e a chave da API, não existe no clone e não deve ser reconstruído. O `mock_server.py` funciona sem nenhuma credencial.

**Nunca escreva credenciais no código.** Nem chaves de API, nem strings de conexão, nem senhas — em nenhum arquivo, nem em comentários ou exemplos.

**Mantenha `app.py`, `mock_server.py` e `docs/API.md` em sincronia.** Se o formato de uma resposta mudar em um, mude nos três. Um mock que diverge do backend real é pior do que não ter mock.

**Windows:** use `py`, não `python`. O console é cp1252 e quebra com caracteres de desenho de caixa — prefixe com `PYTHONIOENCODING=utf-8` quando o script imprimir esses caracteres.
