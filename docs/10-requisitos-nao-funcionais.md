# Requisitos Não Funcionais — Limpar busca e Coleções/Exportação

**Data:** 25/08/2026
**Escopo:** atributos de qualidade das duas features especificadas em
[`09-requisitos-funcionais.md`](09-requisitos-funcionais.md).
**Status:** especificação. Nenhum código de aplicação foi alterado.

Cada requisito abaixo é **verificável**. Requisitos do tipo "deve ser rápido"
ou "deve ser intuitivo" foram convertidos em número, procedimento de medição
ou regra binária — quando isso não foi possível, o item foi descartado.

---

## 1. Usabilidade

| ID | Requisito | Como verificar |
|---|---|---|
| **RNF-001** | Limpar a busca e iniciar uma nova pesquisa deve custar no máximo **2 ações**: um clique no `×` e a digitação. Hoje custa 3 (selecionar tudo, apagar, digitar). | Contagem manual de ações no fluxo. |
| **RNF-002** | O alvo de clique do botão `×` deve ter no mínimo **32 × 32 px** em desktop e **44 × 44 px** nos *breakpoints* móveis (`style.css:1042`, `style.css:1077`), mesmo que o glifo desenhado seja menor. | DevTools → caixa do elemento. |
| **RNF-003** | O botão `×` não pode causar deslocamento de layout (*layout shift*) ao aparecer ou sumir. O campo de busca deve manter largura e altura constantes. | Comparação visual antes/depois de digitar o primeiro caractere. |
| **RNF-004** | A distinção entre **favoritar** e **selecionar** deve ser compreensível sem legenda: ícones diferentes, posições diferentes e `title` explicativo em ambos. | Teste com usuário que nunca viu o app; deve acertar qual é qual na primeira tentativa. |
| **RNF-005** | Toda operação de exportação com mais de 2 s de duração deve exibir progresso contínuo. O usuário nunca pode ficar diante de uma tela parada sem indicação. | Exportar coleção com 50+ itens e observar. |
| **RNF-006** | Mensagens de sucesso, aviso e erro devem usar o sistema de *toast* já existente (`mostrarToast()`, `script.js:59`) e os modais `confirmarAcao()` / `pedirTexto()` (`script.js:94` e `script.js:116`). É proibido introduzir `alert()`, `confirm()` ou `prompt()` nativos — o projeto os eliminou de propósito. | Busca por `alert(`, `confirm(`, `prompt(` no diff. |

---

## 2. Performance

| ID | Requisito | Como verificar |
|---|---|---|
| **RNF-007** | Limpar o campo de busca deve ser **puramente local**: nenhuma requisição HTTP, nenhuma leitura de banco, nenhum `await`. Tempo até o campo ficar vazio ≤ **16 ms** (um quadro a 60 fps). | Aba Network vazia durante a ação; `performance.mark` se necessário. |
| **RNF-008** | Avaliar a visibilidade do botão `×` a cada tecla digitada não pode causar perda de quadros. A verificação é uma comparação de string vazia — não deve haver *debounce*, *timer* nem re-render de lista. | *Profiler* do DevTools durante digitação contínua. |
| **RNF-009** | Marcar/desmarcar um card não pode re-renderizar o grid inteiro. Hoje `renderizarResultados()` (`script.js:1666`) reconstrói tudo via `innerHTML`; a seleção deve alterar apenas o card afetado. | *Profiler*; contagem de nós recriados. |
| **RNF-010** | A exportação deve copiar em **fluxo (streaming)**, sem carregar arquivos inteiros em memória. O consumo de RAM do processo não pode crescer proporcionalmente ao tamanho da coleção. | Exportar coleção com arquivos grandes (vídeos) e observar o uso de memória do processo Python. |
| **RNF-011** | A exportação não pode bloquear as demais rotas da API. Buscar, favoritar e navegar devem continuar funcionando durante uma exportação longa. | Exportar 200 itens e, em paralelo, executar uma busca. |
| **RNF-012** | O *polling* de progresso deve consultar o backend a cada **300–500 ms** e ser **encerrado** ao término da exportação. Nenhum `setInterval` pode ficar órfão — falha já presente no padrão global `setInterval(buscarStatus, 2000)` (`script.js:2323`), que não deve ser replicada. | Inspecionar que o intervalo é limpo em sucesso, erro e cancelamento. |
| **RNF-013** | O progresso reportado pelo backend não pode exigir uma consulta ao banco por arquivo copiado. O estado do *job* fica em memória no processo. | Revisão de código. |

---

## 3. Segurança

| ID | Requisito | Como verificar |
|---|---|---|
| **RNF-014** | Toda rota nova deve exigir sessão autenticada via `_uid()` (`backend/app.py:664`) e retornar **HTTP 401** quando ausente, exatamente como as rotas existentes. | Chamar cada endpoint novo sem cookie de sessão. |
| **RNF-015** | Toda leitura de arquivo durante a exportação deve passar pela validação anti-*path traversal* já usada em `GET /api/file` (`backend/app.py:1263-1278`): o caminho absoluto precisa estar contido em uma pasta monitorada **daquele usuário**, com comparação que exija separador de diretório (para `C:\foo` não casar com `C:\foobar`). | Teste com registro de `files` adulterado apontando para `C:\Windows\System32`. |
| **RNF-016** | A pasta de destino da exportação só pode vir do seletor nativo (`/api/choose_folder`). O backend **não** deve aceitar um caminho de destino arbitrário enviado no corpo da requisição sem validação — isso transformaria a API local em primitiva de escrita em disco. | Revisão do contrato do endpoint. |
| **RNF-017** | O endpoint de "abrir pasta" deve validar o caminho contra a lista de exportações da sessão. **Débito existente:** `/api/open_location` (`backend/app.py:3037`) hoje aceita qualquer caminho e passa direto ao `subprocess.Popen(["explorer", "/select,", filepath])`, sem a checagem que `/api/file` faz. Não replicar esse padrão. | Revisão de código; teste com caminho fora das pastas monitoradas. |
| **RNF-018** | Nenhum caminho absoluto do sistema de arquivos deve ser gravado em log de terceiros, telemetria ou enviado à API do Claude. A exportação é uma operação puramente local. | Revisão do código de exportação. |
| **RNF-019** | Todo texto de origem no servidor (nome de arquivo, nome de coleção, mensagem de erro) inserido no DOM deve usar `textContent`, não `innerHTML`. O projeto já segue essa regra em `mostrarToast()` (`script.js:72`), `mostrarHistorico()` (`script.js:1302`) e `carregarColecoes()` (`script.js:2449`). | Revisão do diff; procurar `innerHTML +=` com dados do servidor. |
| **RNF-020** | A exportação nunca pode apagar, mover ou sobrescrever arquivo algum — nem na origem, nem no destino. É uma operação estritamente aditiva. | Revisão de código: só `shutil.copy2` e `os.makedirs`; nenhum `remove`, `unlink`, `rmtree` ou `move`. |

---

## 4. Confiabilidade

| ID | Requisito | Como verificar |
|---|---|---|
| **RNF-021** | O vínculo imagem↔coleção não pode ser perdido por uma exportação. A exportação é somente leitura sobre `collection_files`. | Comparar contagem da coleção antes e depois. |
| **RNF-022** | A unicidade `(collection_id, file_id)` deve continuar sendo garantida **pelo banco** (PK composta), não apenas pela interface. Adição em lote deve usar a mesma cláusula `ON CONFLICT DO NOTHING` já empregada (`backend/app.py:2645`). | Inserção concorrente do mesmo par. |
| **RNF-023** | Uma exportação interrompida (cancelamento, queda do backend, falha fatal) deve deixar o sistema em estado consistente: arquivos já copiados permanecem, nada é revertido pela metade, o banco não é alterado. | Matar o processo Flask no meio de uma exportação. |
| **RNF-024** | O estado de um *job* de exportação deve ser recuperável pelo frontend em qualquer momento durante sua execução, mesmo que o modal seja fechado e reaberto. | Fechar e reabrir o modal de coleções durante a exportação. |
| **RNF-025** | Falha ao copiar um arquivo não pode corromper a contagem de progresso nem impedir a conclusão do *job*. Total processado = copiados + falhos, sempre. | Exportar coleção com arquivos ausentes propositalmente. |
| **RNF-026** | Se o backend cair durante uma exportação, o frontend deve detectar em até 5 s e informar o usuário, em vez de girar indefinidamente. | Derrubar o Flask durante uma exportação. |

---

## 5. Compatibilidade

| ID | Requisito | Como verificar |
|---|---|---|
| **RNF-027** | Nenhuma dependência nova em `backend/requirements.txt`. Tudo o que a exportação precisa está na biblioteca padrão do Python: `os`, `shutil`, `pathlib`, `threading`, `uuid`. | Diff de `requirements.txt` deve ficar vazio. |
| **RNF-028** | Nenhuma dependência nova no frontend. O projeto é HTML/CSS/JS puro, sem framework e sem *build step* — declarado em `README.md`. | Diff de `index.html`: nenhuma `<script src>` externa nova. |
| **RNF-029** | As features devem funcionar nos navegadores modernos baseados em Chromium e no Firefox atuais. Nenhuma API experimental. Em particular, **não** usar a *File System Access API* (`showDirectoryPicker`): ela é restrita a Chromium, exige gesto do usuário e daria acesso muito mais limitado do que o backend local já possui. | Teste manual nos dois navegadores. |
| **RNF-030** | A plataforma-alvo é **Windows**, conforme já declarado no `README.md` ("os seletores de pasta usam diálogos nativos do Windows"). Código específico de Windows (`explorer`, `tkinter`) deve ficar isolado em funções nomeadas, para que uma futura porta não exija reescrita da lógica de exportação. | Revisão de código: a função que copia não pode conter chamada a `explorer`. |
| **RNF-031** | A sanitização de nomes deve aplicar as regras do **Windows** (mais restritivas que POSIX). Um nome válido no Windows é válido no Linux e no macOS; o inverso não vale. | Testes unitários da função de sanitização. |

---

## 6. Manutenibilidade

| ID | Requisito | Como verificar |
|---|---|---|
| **RNF-032** | A implementação deve seguir a arquitetura vigente: rotas Flask em `backend/app.py`, lógica de UI em `script.js`, estilos em `style.css`, marcação em `index.html`. Nenhum arquivo novo de frontend. | Diff. |
| **RNF-033** | As rotas novas devem seguir a nomenclatura existente: prefixo `/api/`, substantivos em inglês no plural (`/api/collections`, `/api/favorites`, `/api/folders`), e corpo/resposta em JSON com chaves em **português** (`{"status": "ok", "colecoes": [...]}`), como já é o padrão. | Revisão do diff. |
| **RNF-034** | Funções e variáveis novas em `script.js` devem seguir a convenção do arquivo: nomes em português, `camelCase`, prefixo `_` para estado de módulo (`_colecaoAtual`, `_fileIdAtual`, `_historicoCache`). | Revisão do diff. |
| **RNF-035** | Comentários devem manter a densidade e o tom do código existente: blocos `# ───` separando seções no Python, cabeçalhos `// ====` em JS, e explicação do **porquê** — não do quê. | Revisão do diff. |
| **RNF-036** | A sanitização de nome de arquivo/pasta deve ficar em **uma única** função pura, testável isoladamente e sem efeito colateral em disco. | Revisão de código. |
| **RNF-037** | Cada feature deve ser desenvolvida em sua própria branch, seguindo [`07-git-fluxo.md`](07-git-fluxo.md): `feature/limpar-busca` e `feature/colecoes-exportacao`, integradas em `develop` antes de `main`. | Histórico do Git. |
| **RNF-054** | `backend/app.py`, `backend/mock_server.py` e `docs/API.md` devem permanecer em sincronia, conforme o `AGENTS.md`. Toda rota nova entra nos três. | `pytest tests/integration/test_paridade_mock.py` |
| **RNF-055** | O trabalho de backend proposto aqui é **proposta**, não autorização. O `AGENTS.md` determina: *"Não altere `backend/`… descreva a proposta em vez de aplicá-la."* A aplicação depende de quem mantém o motor compartilhado com produção. | Revisão antes de abrir PR que toque `backend/`. |
| **RNF-056** | A suíte de testes existente deve continuar passando. Nenhuma feature nova pode quebrar `tests/unit/` ou `tests/integration/`. | `pytest` conforme [`TESTING.md`](TESTING.md). |
| **RNF-057** | Endpoints novos devem ganhar cobertura de teste no padrão já estabelecido em `tests/unit/test_endpoints_dados.py` e `tests/unit/test_permissoes_endpoints.py` — em particular o teste de que respondem 401 sem sessão. | Revisão do diff de `tests/`. |
| **RNF-058** | A interface nova não pode fixar `http://127.0.0.1:5000`. `script.js:5` já deriva a URL de `window.location.origin`, justamente para o mesmo código servir o backend real (`:5000`) e o mock (`:5001`). | Rodar a interface contra o mock sem editar nada. |

---

## 7. Acessibilidade

O projeto tem hoje **um único** `aria-label` (`#btnMenu`, `index.html:247`),
que combina `aria-label` + `title`. Esse é o padrão a ser seguido; a
recomendação é ampliá-lo, não inventar outro.

| ID | Requisito | Como verificar |
|---|---|---|
| **RNF-038** | O botão de limpar deve ter `aria-label="Limpar busca"` e `title="Limpar busca"`. O glifo `×` sozinho não comunica função a leitor de tela. | Inspeção do DOM; NVDA. |
| **RNF-039** | O botão de limpar deve ser um `<button type="button">`. Um `<div>` com `onclick` não é focável nem anunciado, e violaria RF-007. | Inspeção do DOM. |
| **RNF-040** | Todo controle interativo novo deve ter foco visível — contorno ou anel que não dependa só de mudança de cor de fundo. | Navegação apenas por `Tab`. |
| **RNF-041** | O controle de seleção do card deve expor seu estado programaticamente (`<input type="checkbox">` ou `aria-pressed`), não apenas via classe CSS. | Inspeção do DOM. |
| **RNF-042** | A distinção entre favorito e selecionado não pode depender **só** de cor: deve haver diferença de forma/ícone. Cerca de 8% dos homens têm alguma deficiência de visão de cores. | Simulação de daltonismo no DevTools. |
| **RNF-043** | O progresso da exportação deve ser anunciável: `role="progressbar"` com `aria-valuenow`, `aria-valuemin` e `aria-valuemax`, ou um `aria-live="polite"` com o texto `N de M`. | NVDA durante uma exportação. |
| **RNF-044** | Todo fluxo novo deve ser concluível **sem mouse**: selecionar imagens, adicionar à coleção, exportar e fechar o resultado. | Percorrer o fluxo usando só o teclado. |

---

## 8. Tratamento de erros

| ID | Requisito | Como verificar |
|---|---|---|
| **RNF-045** | Toda mensagem de erro exibida ao usuário deve dizer **o que aconteceu** e **o que fazer**. "Erro ao exportar" não satisfaz; "Não foi possível gravar em `D:\Fotos` — escolha outra pasta ou verifique as permissões" satisfaz. | Revisão do catálogo de mensagens em [`features/12-colecoes-exportacao.md` §8](features/12-colecoes-exportacao.md). |
| **RNF-046** | Exceções do Python jamais devem chegar à interface. O padrão atual de `/api/choose_folder` — `return jsonify({"status": "erro", "mensagem": str(exc)})` (`backend/app.py:1358`) — **não** deve ser replicado na exportação: `str(exc)` vaza caminhos internos e jargão. | Revisão do diff. |
| **RNF-047** | Todo erro capturado deve ser registrado no console do backend com contexto suficiente para diagnóstico (arquivo, operação, exceção), mesmo quando a mensagem ao usuário for genérica. | Revisão do diff. |
| **RNF-048** | Erros por item devem ser **classificados** por tipo (`nao_encontrado`, `sem_permissao`, `fora_das_pastas`, `erro_leitura`, `erro_escrita`), não apenas acumulados como texto livre. Isso permite agrupar no resumo. | Revisão do contrato do endpoint de status. |
| **RNF-049** | O frontend deve tratar `fetch` rejeitado (backend fora do ar) em toda chamada nova, seguindo o `try/catch` + `toastErro` já usado em todo o `script.js`. | Derrubar o backend e exercitar cada ação nova. |

---

## 9. Escalabilidade

| ID | Requisito | Como verificar |
|---|---|---|
| **RNF-050** | A exportação deve concluir corretamente para uma coleção de **1 000 arquivos** sem reestruturação da arquitetura. Consumo de memória constante, progresso preciso do início ao fim. | Teste de carga com coleção sintética. |
| **RNF-051** | A listagem de coleções não pode degradar de forma linear com o número de coleções. **Débito conhecido:** `GET /api/collections` (`backend/app.py:2508`) executa **uma consulta de capas por coleção** dentro de um laço — clássico N+1. Com 50 coleções, são 51 idas ao Postgres remoto (Supabase). A feature não introduz esse problema, mas o agrava ao tornar as coleções mais usadas. | `EXPLAIN`/contagem de consultas; medir com 50 coleções. |
| **RNF-052** | A tela de conteúdo de uma coleção deve permanecer utilizável com centenas de itens. Hoje `verColecao()` (`script.js:2502`) renderiza **todos** os itens de uma vez, sem paginação nem virtualização. Deve haver, no mínimo, `loading="lazy"` nas imagens — padrão que `carregarColecoes()` já aplica nas capas (`script.js:2440`). | Abrir coleção com 300 itens. |
| **RNF-053** | O modelo de dados **não** precisa mudar para suportar as features. Nenhuma migração de schema é exigida por RF-001…RF-060. Qualquer coluna nova (ex.: *hash* de conteúdo, decisão `D-4`) é opcional e deve ser tratada como escopo separado. | Diff de `backend/schema.sql` deve ficar vazio. |

---

## 10. Resumo dos débitos técnicos preexistentes

Encontrados durante a análise. **Nenhum é causado pelas features novas**, mas
todos são tocados por elas e devem ser conhecidos antes da implementação.

| # | Débito | Onde | Gravidade |
|---|---|---|---|
| 1 | `/api/open_location` não valida o caminho recebido antes de passá-lo ao `explorer`. Diferente de `/api/file`, que valida. | `backend/app.py:3037` | **Alta** (segurança) |
| 2 | `GET /api/collections` faz N+1 consultas para montar as capas em mosaico. | `backend/app.py:2508` | Média (performance) |
| 3 | `renderizarResultados()` reconstrói todo o grid via `innerHTML`, o que destrói qualquer estado de DOM — inclusive o de seleção. | `script.js:1666` | Média (bloqueia RF-019) |
| 4 | `setInterval(buscarStatus, 2000)` nunca é interrompido, nem sem sessão ativa. | `script.js:2323` | Baixa |
| 5 | Cobertura de acessibilidade quase nula: um `aria-label` em todo o `index.html`. | `index.html` | Média |
| 6 | `/api/choose_folder` devolve `str(exc)` cru ao frontend. | `backend/app.py:1358` | Baixa |
