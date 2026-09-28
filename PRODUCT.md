# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Pessoa comum com acervo pessoal no próprio computador: milhares de fotos e
documentos acumulados em pastas que ninguém organizou — família, viagens,
notas fiscais, contratos, prints. Ela usa Windows, mexe nos arquivos pelo
Explorer e não mantém nomenclatura nenhuma: o arquivo se chama `IMG_8472.jpg`.

A situação de uso é pontual e com pressa: ela precisa de **um** arquivo
específico, lembra do conteúdo ("a foto do cachorro na grama", "a nota de
luz"), e não lembra o nome nem a pasta. Hoje ela abre o Explorer e rola.

## Product Purpose

Encontrar um arquivo do próprio computador descrevendo o que ele mostra, em
linguagem natural, em vez de depender do nome ou do lugar onde ele foi parar.

Sucesso, confirmado pelo dono do projeto: **achar sem lembrar o nome**. Juntar
em coleções, favoritar e salvar de volta numa pasta são apoio ao redor da
busca, não o centro.

## Positioning

A busca é híbrida e roda sobre os arquivos que já estão na máquina, sem subir
o acervo para lugar nenhum: vetor visual (CLIP) e vetor de texto (SBERT)
calculados localmente, palavra-chave (BM25) e, só na hora da busca, a API do
Claude descreve as imagens candidatas que ainda não têm texto e julga quais
respondem à frase.

A indexação é preguiçosa de propósito: ao adicionar uma pasta, nenhuma chamada
de IA acontece — só o vetor visual e a extração de texto dos documentos. Isso
é o que separa o produto de um indexador que cobra (em tempo e em crédito)
para descrever um acervo inteiro que a pessoa talvez nunca busque.

## Operating Context

- Windows. O app abre o seletor de pasta nativo, guarda caminhos absolutos do
  Windows e abre a pasta no Explorer.
- O servidor roda na própria máquina (`http://127.0.0.1:5000`, `rodar.bat`);
  o banco fica no Supabase e a IA na API do Claude, ambos na nuvem.
- Existe um caminho de demonstração sem banco, sem chave e sem IA:
  `py backend/mock_server.py` em `http://127.0.0.1:5001`, com dados
  fictícios e login livre. É o que se usa para mostrar a interface.
- A primeira busca de um assunto novo demora alguns segundos, porque é quando
  a IA descreve as candidatas; as seguintes usam o que ficou salvo.

## Capabilities and Constraints

Confirmado em código e testes:

- busca por texto em linguagem natural, com filtros (tipo, data, favoritos),
  refino sobre os resultados e histórico de buscas;
- busca por imagem: envia uma foto e recebe as parecidas;
- acervo agrupado por categoria (pessoas, animais, comida, natureza, urbano,
  desenhos e arte), com seleção da categoria inteira;
- favoritos, coleções (capa, ordem, renomear), seleção em massa;
- salvar coleção numa pasta do computador, com renomeação por padrão, redução
  de imagem e subpastas por mês; histórico das exportações com as falhas
  nomeadas; pasta da coleção que acompanha a coleção (automático, perguntar
  ou manual);
- lixeira com restaurar; resumo da última análise (indexados, ignorados,
  com erro); tema claro/escuro, cores e fundo.

Restrições duráveis:

- **O dono do projeto trabalha só no front-end: tudo que é back-end se
  preserva.** `backend/app.py`, `backend/mock_server.py` e `schema.sql` são o
  motor compartilhado com a versão em produção; mudança ali é proposta
  escrita, não código (`AGENTS.md`).
- O contrato da API está em `docs/API.md` e vale para os dois servidores: rota
  nova entra no real, no mock e na documentação.
- Frontend sem framework e sem etapa de build: HTML, CSS e JS puros.
- Não há paginação: a busca devolve no máximo 60 itens e a galeria devolve o
  acervo inteiro de uma vez.
- Descrição vazia é estado normal (a imagem foi indexada e ainda não foi
  descrita), nunca erro.
- Dois endpoints abrem diálogo nativo do Windows **no servidor** e ficam
  pendurados até alguém responder; a interface sempre precisa de alternativa.
- Erros chegam com `error` ou com `mensagem`, conforme o endpoint.

Em aberto, não decidido: se o produto sai do escopo acadêmico para uso real
por terceiros, e o que aconteceria com acervos muito grandes (hoje sem
virtualização de lista).

## Brand Commitments

- Nome: **Search+**.
- Vocabulário fixo, com teste automatizado que reprova o que foi aposentado:
  "pasta do computador" (nunca monitorada/importada/vinculada), "pasta da
  coleção", "Salvar no computador", "Adicionar pasta", "analisar/análise"
  (nunca indexar/indexação) — `docs/FRONTEND.md`.
- Sem emoji na interface: os ícones vêm de um sprite SVG com traço
  `currentColor`, para acompanhar tema e cor de destaque.
- Português direto, frase curta, sem jargão técnico na tela. Mensagem de erro
  diz o que aconteceu e o que fazer.

## Evidence on Hand

- `backend/mock_server.py`: 12 arquivos fictícios com descrições coerentes —
  é a base de toda demonstração.
- `demo-fotos/`: nove fotos de exemplo. **Oito não correspondem ao nome nem à
  descrição do mock** (`sushi-combinado.jpg` é mato, `gato-janela.jpg` é
  neblina); não servem como prova visual até serem trocadas.
- 792 testes automatizados (unitários e de integração) com CI no GitHub
  Actions; testes de carga com Locust.
- `docs/`: requisitos funcionais e não funcionais, casos de uso, DER, dossiê
  de sprints, contrato da API, guia do front.
- `landing/`: página estática de apresentação do produto.
- Não existem usuários reais, métricas de uso, depoimentos ou benchmark de
  campo: nada disso pode ser afirmado em tela ou em documento.

## Product Principles

1. **Achar vem antes de organizar.** Qualquer tela disputa espaço com a busca;
   quando houver conflito, a busca ganha.
2. **O arquivo original é sagrado.** O app lê e copia; nunca move, renomeia ou
   apaga o que está nas pastas do computador.
3. **A IA trabalha quando é pedida.** Nada de descrever acervo inteiro por
   antecipação: custo e espera só existem a serviço de uma busca real.
4. **Uma coisa, um nome.** O vocabulário da tela é fixo e testado; termo novo
   entra pela tabela, não pela frase.
5. **O front-end é livre, o motor não.** A interface pode ser reescrita
   inteira; o backend e o contrato da API se preservam.

## Accessibility & Inclusion

Compromissos já implementados e cobertos por requisito ou teste:

- botão só de ícone tem `aria-label`; foco visível em todo controle novo;
- diferença de estado nunca depende só de cor (favorito muda a forma do
  ícone, seleção muda forma e posição);
- fluxo completo pelo teclado, incluindo selecionar, adicionar à coleção e
  exportar; `Esc` fecha o que está aberto;
- progresso anunciável (`role="progressbar"`, `aria-live`);
- alvo de toque de 44px nos tamanhos de tela pequenos.
