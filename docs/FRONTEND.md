# Substituindo o frontend do Search+

Guia para quem vai construir a nova interface — inclusive para agentes de IA trabalhando neste repositório.

**O trabalho é trocar a roupa, não o motor.** O backend em Python fica exatamente como está: ele já faz busca semântica, indexação, descrição de imagens por IA e todo o acesso ao banco. O que muda é a camada visual que conversa com ele.

---

## Em 30 segundos

```bash
py -m pip install flask flask-cors
py backend/mock_server.py
```

Abra `http://127.0.0.1:5001` — o Search+ inteiro roda com dados fictícios. Qualquer usuário e senha entram.

Sem Postgres, sem baixar modelos de IA, sem chave de API. Esse é o ambiente de desenvolvimento do frontend: explore o aplicativo atual, veja como cada tela se comporta, e construa a substituição contra a mesma API.

---

## O que pode ser substituído e o que não pode

### Camada visual — reescreva à vontade

| Arquivo | O que é |
|---|---|
| `index.html` | Todas as telas em um arquivo só (~870 linhas) |
| `style.css` | Todos os estilos (~1.090 linhas) |
| `script.js` | Toda a lógica de interface (~2.750 linhas) |
| `fonts/` | Fontes locais — mantenha se quiser reaproveitar a identidade |
| `landing/` | Página de divulgação, independente do aplicativo |

### Backend — não altere

| Caminho | Por quê |
|---|---|
| `backend/app.py` | O servidor real: API, busca, IA, banco |
| `backend/mock_server.py` | A mesma API com dados falsos, usada no desenvolvimento |
| `backend/schema.sql` | Estrutura do banco |
| `backend/.env` | Credenciais. Não existe no clone e não deve ser criado por você |
| `docs/` | Este guia e o contrato da API |

Se algo na interface parecer exigir uma mudança de backend, **é quase sempre sinal de que o endpoint certo já existe** — confira `docs/API.md` antes. Havendo necessidade real, registre a proposta em vez de alterar: o backend é compartilhado com a versão em produção.

---

## Como o frontend conversa com o backend

A referência completa é **[API.md](API.md)** — leia antes da primeira chamada. O essencial:

### 1. Sessão por cookie

Não há token nem header `Authorization`. O login devolve um cookie e **toda** requisição precisa reenviá-lo:

```js
fetch(`${API_BASE_URL}/api/search`, {
  method: "POST",
  credentials: "include",              // ← sem isto, tudo responde 401
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ query, filtro }),
});
```

Em axios: `axios.defaults.withCredentials = true`.

### 2. A URL da API vem da própria página

```js
const API_BASE_URL = window.location.origin;
```

Assim o mesmo código funciona no mock (5001) e no backend real (5000). **Não fixe a porta.**

### 3. Se usar um dev server separado, configure proxy

Rodando Vite/Next em outra porta, o navegador trata `localhost:5173` e `localhost:5000` como sites diferentes e **não envia o cookie de sessão** — tudo responde 401 mesmo com o login funcionando. A saída simples é o proxy do próprio dev server:

```js
// vite.config.js
export default {
  server: { proxy: { "/api": "http://127.0.0.1:5001" } }
};
```

Isso mantém tudo na mesma origem e dispensa qualquer configuração de CORS. A alternativa (`CROSS_SITE_COOKIES=1` no backend) exige HTTPS e complica sem necessidade.

### 4. Entregando o resultado

- **HTML/CSS/JS puro:** sobrescreva `index.html`, `style.css` e `script.js` na raiz. Nada a configurar.
- **Com build (React, Vue, Svelte…):** deixe o projeto numa pasta própria e aponte o backend para o build, em `backend/.env`:
  ```ini
  FRONTEND_DIR=../front/dist
  ```
  O backend passa a servir essa pasta, com fallback de rota para SPA já implementado — roteamento client-side funciona sem configuração extra.

---

## O que a interface precisa entregar

O protótipo atual já resolve estes fluxos. Use-o rodando como especificação de comportamento: o visual é livre, as funcionalidades não.

### Entrada
- **Login / cadastro** — `POST /api/login`, `POST /api/register`
- **Onboarding** — primeiro acesso: escolher pastas para indexar, definir perfil de análise (`fast`/`deep`) e confirmar. Só então dispara `POST /api/analyze_folders`

### Home
- **Painel de estatísticas** — total de arquivos, pastas e distribuição por formato e categoria (`GET /api/stats`)
- **Galeria por categoria** — imagens agrupadas em `pessoas`, `animais`, `comida`, `natureza`, `urbano`, `desenhos`, `outras` (`GET /api/gallery`). O mesmo arquivo pode aparecer em vários grupos

### Busca — o coração do produto
- Campo de busca com histórico (`GET`/`POST /api/search_history`)
- Filtro por tipo: tudo / imagens / documentos / mídia
- Filtros avançados: intervalo de datas, pasta, tamanho em MB
- **Resultados em duas faixas:** "Melhores" (score ≥ 0.60) e "Semânticos" (o resto)
- **Estado de carregamento obrigatório** — a busca real leva de 1 a 8 segundos
- Busca por imagem: enviar arquivo ou partir de um resultado existente (`POST /api/search_by_image`)

### Resultados
- Painel lateral de detalhe do arquivo
- Pré-visualização ao passar o mouse
- Abrir a pasta do arquivo no explorador (`GET /api/open_location`)
- Favoritar (`POST /api/favorites/toggle`)
- Adicionar a uma coleção

### Organização
- **Favoritos** (`GET /api/favorites`)
- **Coleções** — criar, listar com capa em mosaico de até 4 imagens, adicionar e remover arquivos

### Configurações
- Perfil: nome, apelido, biografia, cargo, local, avatar e capa (com recorte de imagem)
- Aparência: tema claro/escuro, cores primária e secundária, imagem de fundo com desfoque
- Pastas monitoradas: adicionar, remover, configurar prioridade, perfil e janela de processamento
- Preferências: idioma, notificações, atalho de busca, modo privado, modo de desempenho

### Indexação
- Barra de progresso durante o processamento (`GET /api/status`, consultado periodicamente)
- Cancelar indexação em andamento
- Reanalisar arquivos e limpar cache

---

## Detalhes que causam bug se ignorados

**Descrição vazia é normal, não é erro.** Imagens são indexadas só com o vetor visual; a descrição em texto é gerada depois, sob demanda, quando alguma busca alcança aquela imagem. Uma imagem recém-indexada aparece com `descricao_ia: ""` e ganha texto mais tarde. Nunca exiba "falha ao processar" nesse caso.

**A busca é lenta e isso é esperado.** De 1 a 8 segundos no backend real, porque pode chamar a IA duas vezes. Trate como operação longa: indicador de progresso, botão desabilitado durante a chamada. O mock responde em ~250ms, então teste a interface pensando no tempo real, não no do mock.

**Caminhos são absolutos e do Windows.** Vêm como `C:\Users\...\foto.jpg`. Para montar a URL da imagem:
```js
const src = `${API_BASE_URL}/api/file/${encodeURIComponent(arquivo.caminho)}`;
```

**Não existe paginação.** A busca devolve no máximo 60 itens e a galeria devolve tudo de uma vez. Para acervos grandes, virtualize a lista.

**Dois endpoints abrem janelas nativas no servidor.** `/api/choose_folder` e `/api/choose_image` abrem um seletor do Windows **na máquina onde o backend roda**, e a requisição fica pendurada até alguém responder. Sempre ofereça alternativa na interface: um `<input type="file">` para imagens e um campo de texto para o caminho da pasta.

**Categorias podem crescer.** As sete atuais são fixas hoje, mas trate chave desconhecida com um rótulo e ícone genéricos, em vez de quebrar a tela.

**Erros não têm formato único.** Alguns endpoints devolvem `{"error": "..."}`, outros `{"mensagem": "..."}`. Trate as duas chaves.

---

## Checklist antes de entregar

- [ ] Todos os fluxos da seção anterior funcionam contra o mock
- [ ] Nenhuma porta fixa no código — `API_BASE_URL` derivado da origem
- [ ] `credentials: "include"` em todas as chamadas
- [ ] Estado de carregamento na busca, dimensionado para 8 segundos
- [ ] Imagem sem descrição não é exibida como erro
- [ ] Alternativa aos seletores nativos do Windows
- [ ] Layout responsivo
- [ ] Nada em `backend/` foi alterado
- [ ] Nenhuma credencial no código ou no repositório

---

## Referências

| Documento | Conteúdo |
|---|---|
| [API.md](API.md) | Contrato completo: payloads, respostas, códigos de erro |
| `backend/mock_server.py` | Os dados fictícios e o comportamento simulado de cada endpoint |
| `index.html`, `script.js` | O protótipo atual — a especificação viva do comportamento |
| `CLAUDE.md` | Visão geral da arquitetura do projeto |
