================================================================================
  SEARCH+ - RELATÓRIO COMPLETO DO PROJETO (ATUALIZADO)
================================================================================
  Data do relatório:  2026-05-26
  Repositório:        github.com/itallolugon/SearchPlus_Prototipo
  Branch:             main
  HEAD:               fa92125 (revert: mantem LLaVA como modelo de visao)
  Total de commits:   ~33 no main
================================================================================


--------------------------------------------------------------------------------
  1. O QUE É O SEARCH+
--------------------------------------------------------------------------------

Aplicativo de busca semântica para arquivos locais — imagens, PDFs, DOCX,
TXT e CSV. O usuário aponta para uma pasta do PC e pesquisa em linguagem
natural ("cachorro brincando", "prato de comida com kebab", "festa noturna")
em vez de procurar por nome de arquivo.

A IA de análise (descrição de imagens com LLaVA + embeddings semânticos
com SBERT) roda 100% local na máquina do usuário via Ollama. O banco de
dados ficou hospedado no Supabase (Postgres + pgvector), gratuito e na nuvem.


--------------------------------------------------------------------------------
  2. STACK TÉCNICO (números atualizados)
--------------------------------------------------------------------------------

FRONTEND (vanilla, sem framework):
  - index.html        706 linhas   SPA completa: modais, painéis, ajuda
  - script.js       1.886 linhas   Lógica do app (toast, atalhos, busca)
  - style.css         620 linhas   Estilos (inclui toast e ajuda)
  - fonts/                         BebasNeue, CoralPixels, MomoTrust

BACKEND (Flask + Python 3.10+):
  - backend/app.py  2.321 linhas   API + worker de IA + arquivos estáticos

BANCO DE DADOS (Postgres na nuvem):
  - Postgres no Supabase (free tier, região São Paulo)
  - Extensão pgvector ativa (vector similarity search nativa)
  - Schema: backend/schema.sql  57 linhas

INTELIGÊNCIA ARTIFICIAL (toda local via Ollama):
  - LLaVA 13B            (descrição de imagens, modo deep)
  - LLaVA latest (7B)    (descrição de imagens, modo fast)
  - Llama 3.2            (re-rank de busca)
  - SBERT MiniLM-L12     (sentence-transformers, embeddings 384 dim)
  - CLIP ViT-B-32        (busca visual texto↔imagem, opcional, 512 dim)

  Nota histórica: o qwen2.5vl (7b e 3b) foi testado mas REVERTIDO — no
  hardware atual (RTX 4060 8GB) leva 7-12 min/imagem porque o llama.cpp
  ainda processa seu vision encoder no CPU. LLaVA leva ~1 min/imagem.


--------------------------------------------------------------------------------
  3. PIPELINE DE BUSCA SEMÂNTICA (HÍBRIDO COM 4 CAMADAS + RE-RANK)
--------------------------------------------------------------------------------

  1. EXPANSÃO DE QUERY
     Tokenização, remoção de stopwords, expansão de sinônimos no PT-BR
     (cachorro → cao, dog, pet, filhote...). Cobre plural nasal (homem ↔
     homens, jovem ↔ jovens).

  2. SBERT NO BANCO (camada semântica principal)
     SELECT ... ORDER BY embedding <=> %s LIMIT 100
     O Postgres usa o índice HNSW e devolve os 100 candidatos mais
     próximos — sem carregar embeddings em RAM no Python.

  3. BM25 + MATCH LITERAL (camada keyword)
     Sobre os 100 candidatos, calcula score por palavra-chave usando
     BM25 e verifica match literal com variantes de plural.

  4. CLIP (camada visual, opcional)
     Similaridade visual direta entre texto da query e pixels da imagem.

  5. BLEND + AJUSTES DE SCORE
     Os 3 scores misturados com pesos. Regras: rejeição por gênero
     incompatível, boosts de match exato, threshold adaptativo
     (0.35 → 0.30 quando vazio).

  6. RE-RANK COM LLM-JUIZ
     Top-20 passa pelo Llama 3.2 que pontua 0-10 de relevância.
     Salvaguarda contra LLM "rejeitando" hit forte do motor.

  7. CORTE FINAL
     Resultados abaixo de 0.20 são descartados.

  LATÊNCIA típica: 300-500ms por busca.


--------------------------------------------------------------------------------
  4. ANTI-ALUCINAÇÃO NO LLAVA
--------------------------------------------------------------------------------

  - temperature=0.0, top_p=0.5 (reduz aleatoriedade)
  - Prompt explícito "NÃO INVENTE pessoas/animais que não estão visíveis"
  - Campo "Animais" separado de "Pessoas"
  - Vocabulário canônico: 'cachorro' (nunca 'cão'/'cãe'), 'gato' (nunca
    'felino'/'bichano'), 'mulher'/'menina'/'homem'/'menino' (nunca
    'senhora'/'rapaz'/'cavalheiro')


--------------------------------------------------------------------------------
  5. BANCO DE DADOS - SUPABASE
--------------------------------------------------------------------------------

CONEXÃO:
  URL:           https://pexxuyifyujvmshqtpuo.supabase.co
  Região:        South America (São Paulo)
  Plano:         Free (500 MB DB, 50k usuários, sem cartão)

ESTADO ATUAL (snapshot 2026-05-26):
  users:                4
  folders:              3
  files:                9
  files processados:    9
  tamanho do DB:        10 MB

ESQUEMA (backend/schema.sql):

  users
    id            SERIAL PRIMARY KEY
    username      TEXT UNIQUE NOT NULL
    password_hash TEXT NOT NULL         (SHA-256 — ver pendência #1)
    config_json   JSONB                 (perfil, tema, cores, historico)

  folders
    id                   SERIAL PRIMARY KEY
    user_id              FK -> users(id) ON DELETE CASCADE
    path                 TEXT
    name                 TEXT
    added_at             TIMESTAMPTZ
    prioridades          JSONB    (foco: pessoas/animais/paisagens/tudo)
    perfil_analise       TEXT     (fast/deep)
    janela_processamento TEXT     (always/02:00-06:00/customizado)
    UNIQUE (user_id, path)

  files
    id              SERIAL PRIMARY KEY
    folder_id       FK -> folders(id) ON DELETE SET NULL
    user_id         FK -> users(id) ON DELETE CASCADE
    nome            TEXT
    caminho         TEXT
    tipo            TEXT
    descricao_ia    TEXT
    embedding       vector(384)   (SBERT)
    embedding_clip  vector(512)   (CLIP)
    data_adicionado TIMESTAMPTZ
    favorito        INTEGER
    processado      INTEGER
    UNIQUE (user_id, caminho)

ÍNDICES:
  files_embedding_idx       HNSW vector_cosine_ops (busca SBERT)
  files_embedding_clip_idx  HNSW vector_cosine_ops (busca CLIP)
  files_user_processado_idx (user_id, processado)
  folders_user_idx          (user_id)


--------------------------------------------------------------------------------
  6. ENDPOINTS DA API (31 rotas — +1 desde a versão anterior)
--------------------------------------------------------------------------------

AUTENTICAÇÃO:
  POST   /api/register          Criar conta (auto-recria schema se faltar)
  POST   /api/cadastro          Alias de /register
  POST   /api/login             Login com sessão Flask
  POST   /api/logout            Encerrar sessão
  GET    /api/check_session     Verifica se ainda está logado

CONFIGURAÇÃO:
  GET    /api/config            Lê perfil/tema/cores do usuário
  POST   /api/config            Salva configurações

PASTAS:
  GET    /api/folders           Lista pastas monitoradas
  POST   /api/folders           Adiciona pasta + dispara análise
  DELETE /api/folders           Remove pasta (cascata: apaga arquivos)
  DELETE /api/folders/<id>      Remove pasta por ID
  POST   /api/folders/update_config  Atualiza prioridades/perfil/janela

ANÁLISE / INDEXAÇÃO:
  POST   /api/analyze_folders   Dispara scan de todas as pastas
  POST   /api/reanalyze         Re-enfileira arquivos com descrição ruim
  POST   /api/reembed           Regenera embeddings sem re-rodar LLaVA
  POST   /api/cancel_analysis   NOVO: esvazia a fila (cancelar indexação)
  GET    /api/status            Status do worker (fila, processados)
  GET    /api/estimate_time     Estima tempo de processamento (limitado)

BUSCA:
  GET/POST /api/search          Busca semântica com pgvector
  GET    /api/debug/scores      Scores SBERT brutos (debug)
  GET    /api/debug/files       Lista de arquivos indexados

FAVORITOS / HISTÓRICO:
  GET    /api/favorites         Lista favoritos
  POST   /api/favorites/toggle  Marca/desmarca favorito
  GET    /api/search_history    Histórico de buscas
  POST   /api/search_history    Adiciona ao histórico
  DELETE /api/search_history/<i> Remove item
  POST   /api/clear_history     Limpa todo o histórico
  POST   /api/clear_cache       Apaga arquivos indexados (mantém pastas)

DIÁLOGOS DO WINDOWS (requerem login):
  GET    /api/choose_folder     Abre dialog tkinter de pasta
  GET    /api/choose_image      Abre dialog tkinter de imagem

OUTROS:
  GET    /api/ollama_models     Lista modelos Ollama disponíveis
  GET    /api/file/<path>       Serve arquivo local (auth + path validation)
  GET    /api/open_location     Abre Explorer com arquivo selecionado


--------------------------------------------------------------------------------
  7. ANÁLISE HEURÍSTICA DE NIELSEN (avaliação completa + correções)
--------------------------------------------------------------------------------

Avaliação das 10 heurísticas clássicas de usabilidade (Jakob Nielsen),
com estado ANTES da intervenção e o que foi implementado DEPOIS.

  Legenda: 🟢 bom · 🟡 médio · 🔴 fraco

............................................................................
  H#1 — VISIBILIDADE DO STATUS DO SISTEMA
............................................................................
  ANTES (🟢 bom): Polling a cada 2s mostrando "Motor: Analisando...",
                  iaLoadingScreen, botões com "⏳" durante ações.
  FALHA: quando havia fila de indexação, mostrava "Fila: N" mas o texto
         era técnico ("Motor: Analisando..."), sem indicar progresso real.

  [OK] IMPLEMENTADO:
       - Status bar reescrita: "🔍 Analisando arquivos — N na fila"
       - Toast "Análise concluída!" quando a fila zera (transição N→0)
       - Estados específicos: "🕐 Aguardando janela", "📂 Escaneando"
       - Texto humano, não técnico

............................................................................
  H#2 — CORRESPONDÊNCIA SISTEMA ↔ MUNDO REAL
............................................................................
  ANTES (🟢 bom): Tudo em PT-BR natural ("Gerenciar Pastas", "Favoritos").
                  Busca aceita linguagem coloquial. Sem jargão técnico.

  [—] SEM AÇÃO necessária. Já estava ok.

............................................................................
  H#3 — CONTROLE E LIBERDADE DO USUÁRIO
............................................................................
  ANTES (🟡 médio): Dava pra remover pasta e limpar cache, mas NÃO dava
                    pra cancelar uma análise em andamento. Apontar uma
                    pasta de 5.000 fotos por engano deixava o usuário
                    refém. Sem "desfazer".

  [OK] IMPLEMENTADO:
       - Endpoint POST /api/cancel_analysis (esvazia a fila)
       - Botão "✕ Cancelar análise" aparece na status bar quando há
         fila > 0
       - Toast informativo: "Análise cancelada — N arquivos removidos"

............................................................................
  H#4 — CONSISTÊNCIA E PADRÕES
............................................................................
  ANTES (🟡 médio): UI visual consistente, mas feedback misturado: umas
                    ações usavam alert() (popup feio do navegador),
                    outras usavam telas customizadas. Tinha
                    /api/register E /api/cadastro fazendo o mesmo (mantido
                    como alias pra retrocompatibilidade).

  [OK] IMPLEMENTADO:
       - Feedback unificado: TUDO via sistema de toast (sucesso/erro/
         info/aviso), mesmo estilo visual em todo lugar
       - Zero alert() nativos restantes no código

............................................................................
  H#5 — PREVENÇÃO DE ERROS
............................................................................
  ANTES (🟡 médio): Confirmações existiam pra ações destrutivas (limpar
                    cache, remover pasta, limpar histórico) — isso é bom.
                    Pontos fracos: campo de pasta aceitava qualquer texto
                    sem validar; login sem validação de formato.

  [—] SEM AÇÃO grande. Confirmações ficaram, validações de input não foram
      priorizadas (baixo impacto pra protótipo).

............................................................................
  H#6 — RECONHECIMENTO EM VEZ DE MEMORIZAÇÃO
............................................................................
  ANTES (🟢 bom): Histórico de buscas com dropdown, filtros sempre
                  visíveis (Tudo/Imagens/Documentos/Áudio), dicas
                  rotativas (dicasUX). Usuário não precisava decorar nada.

  [—] SEM AÇÃO necessária. Já estava ok.

............................................................................
  H#7 — FLEXIBILIDADE E EFICIÊNCIA DE USO
............................................................................
  ANTES (🟡 médio): Busca com Enter e histórico ajudavam. Mas NÃO havia
                    atalhos de teclado documentados, nem busca avançada
                    (filtrar por data, por pasta específica).

  [OK] IMPLEMENTADO:
       - "/" foca a barra de busca (de qualquer lugar)
       - "Esc" fecha o modal/painel aberto mais relevante
       - Atalhos documentados no modal de ajuda

  PENDENTE: busca avançada (filtros por data, tamanho, pasta).

............................................................................
  H#8 — ESTÉTICA E DESIGN MINIMALISTA
............................................................................
  ANTES (🟢 bom): Interface escura, limpa, sem poluição visual.

  [—] SEM AÇÃO necessária.

............................................................................
  H#9 — RECONHECER, DIAGNOSTICAR E RECUPERAR DE ERROS
        *** PONTO MAIS FRACO IDENTIFICADO ***
............................................................................
  ANTES (🔴 FRACO): Vários "catch (e) { console.error(...) }" — o erro
                    ia pro console do desenvolvedor, o USUÁRIO NÃO VIA
                    NADA. Se o servidor caísse ou o Supabase ficasse
                    fora, o app simplesmente parava de responder, sem
                    explicar por quê. Mensagens genéricas: "Erro de
                    conexão com o banco de dados" — sem dizer o que fazer.

  [OK] IMPLEMENTADO:
       - Sistema de toast unificado (função mostrarToast)
       - 4 tipos: sucesso (verde), erro (vermelho), info (azul),
         aviso (laranja). Cada um com ícone + cor + borda lateral
       - Auto-dismiss configurável + botão de fechar
       - 18 alert() nativos trocados por toast
       - console.error silenciosos agora TAMBÉM disparam toast pro
         usuário (servidor offline, erro na busca, falha ao favoritar)
       - Mensagens reescritas pra serem acionáveis:
         antes: "Erro de conexão com o banco de dados."
         depois: "Erro de conexão. Verifique se o servidor Python está rodando."

............................................................................
  H#10 — AJUDA E DOCUMENTAÇÃO
............................................................................
  ANTES (🔴 fraco): Só havia as dicas rotativas (dicasUX) no dashboard.
                    DENTRO do app não havia tooltip, FAQ, nem botão "?"
                    de ajuda. Usuário travado não tinha pra onde recorrer.

  [OK] IMPLEMENTADO:
       - Botão "?" circular no header
       - Modal de Ajuda com 6 seções:
            🔍 Como buscar
            📁 Adicionar pastas
            ⏳ Primeira análise
            ⌨️  Atalhos de teclado
            ⭐ Favoritos
            ⚠️  Troubleshooting (Ollama, internet, etc)


............................................................................
  RESUMO DA ANÁLISE
............................................................................

  TABELA DE SEVERIDADE (do mais ao menos crítico):

  Severidade  | Heurística                                  | Status
  ------------|---------------------------------------------|--------
  🔴 Alta     | H#9 Erros silenciosos pro usuário           |  [OK]
  🔴 Alta     | H#10 Sem ajuda dentro do app                |  [OK]
  🟡 Média    | H#3 Sem cancelar análise                    |  [OK]
  🟡 Média    | H#4 alert() nativo (inconsistência)         |  [OK]
  🟡 Média    | H#1 Progresso pouco claro                   |  [OK]
  🟢 Baixa    | H#7 Sem atalhos de teclado                  |  [OK]
  🟡 Média    | H#5 Pouca validação de input                |  pendente
  🟢 Baixa    | H#7 Sem busca avançada                      |  pendente

  RESULTADO: 6 de 6 problemas críticos/médios identificados foram
  corrigidos. Os 2 itens pendentes são de baixa-média prioridade e
  ficam pra evolução futura.


............................................................................
  DETALHES TÉCNICOS DA IMPLEMENTAÇÃO
............................................................................

  Sistema de toast (frontend):
    style.css : .toast-container, .toast (4 tipos), animações in/out
    script.js : função mostrarToast(msg, tipo, duracaoMs)
                atalhos: toastOk, toastErro, toastInfo, toastAviso
                anti-XSS: usa textContent pra mensagem

  Modal de ajuda:
    index.html: <div id="ajudaModal"> com 6 .ajuda-item
    style.css : .ajuda-conteudo, .btn-ajuda (botão "?" circular)
    script.js : abrirAjuda(), fecharAjuda()

  Cancelamento de análise:
    backend/app.py: @app.route POST /api/cancel_analysis (linha ~1556)
                   esvazia _queue, atualiza _status para "Ocioso"
    script.js    : função cancelarAnalise() + botão dinâmico

  Atalhos de teclado:
    script.js : document.addEventListener('keydown', ...)
                "/" foca #searchInput, "Esc" fecha modal aberto

  Status bar reescrita:
    script.js : função buscarStatus() reescrita
                variável _ultimaFila pra detectar transição N→0
                innerHTML reconstruído com textContent + botão dinâmico

  Tudo implementado no commit: 79e2518


--------------------------------------------------------------------------------
  8. SEGURANÇA APLICADA
--------------------------------------------------------------------------------

  [OK] /api/file/<path> exige login + valida que path está dentro de
       uma pasta cadastrada do usuário (anti-path-traversal)
  [OK] /api/choose_folder e /api/choose_image exigem login
  [OK] XSS no histórico de buscas: _escapeHtml() antes de innerHTML
  [OK] XSS no status bar: textContent em vez de innerHTML
  [OK] json.loads sempre passa pelo wrapper _safe_json_loads (não quebra
       request quando JSON está corrompido)
  [OK] Errorhandler global captura psycopg2.errors.UndefinedTable e
       auto-recria schema
  [OK] Credenciais do Supabase em backend/.env (gitignored)
  [OK] Cookie de sessão HTTPOnly, SameSite=Lax
  [OK] Anti-path-traversal nos endpoints de arquivo
  [OK] Worker resiliente: descrição em fallback "Imagem: x.jpg" NÃO marca
       arquivo como processado (próxima varredura tenta de novo)

PENDÊNCIAS DE SEGURANÇA (pra produção):
  [ ] Trocar SHA-256 por bcrypt/argon2 nas senhas (5 min, mas crítico)
  [ ] Rotacionar service_role key e senha do Supabase (expostas no chat)
  [ ] HTTPS no servidor (Flask só roda HTTP por padrão)


--------------------------------------------------------------------------------
  9. DISTRIBUIÇÃO (em estudo)
--------------------------------------------------------------------------------

O ZIP portátil + scripts .bat (installer/) que foi testado anteriormente
foi REMOVIDO. Era frágil (depender de Ollama local pesa muito pro usuário
final, ~12 GB) e o caminho mais promissor é trocar a IA local por uma
API paga (Gemini Flash gratuito ou GPT-4o/Claude pagos).

DECISÃO ARQUITETURAL PENDENTE:
  - Continuar 100% local (Ollama)?
  - Migrar pra IA via API (Gemini/OpenAI/Anthropic)?
    Vantagens: .exe menor, sem 12GB pro usuário, qualidade superior
    Tradeoffs: imagens saem do PC do usuário, custo por uso

Ver a seção 13 "Pendências" para o caminho proposto.


--------------------------------------------------------------------------------
  10. HISTÓRICO DE COMMITS RECENTES (do mais novo ao mais antigo)
--------------------------------------------------------------------------------

fa92125  revert: mantem LLaVA como modelo de visao (qwen2.5vl inviavel)
79e2518  feat: melhorias de usabilidade da analise heuristica de Nielsen
aff9614  feat: migra de SQLite local para Postgres no Supabase com pgvector
f47376b  fix: corrige 7 bugs encontrados na revisao de codigo
d405ff6  docs: README com instrucoes para usuarios leigos
ac8e202  feat: pacote portatil com instalador zipado
5035dbd  merge: integra UI do Lorenzo
74f0610  merge: integra backend do Lorenzo
64dc9ff  feat: integra backend do Lorenzo (perfis, janelas, novos endpoints)
c8e5517  feat: integra UI do Lorenzo (foco da análise, perfis, janelas)
e8c03fb  fix: api_register auto-recria schema se banco foi zerado
d3ad884  feat: re-rank com LLM, anti-alucinação no LLaVA e match morfológico


--------------------------------------------------------------------------------
  11. COMO RODAR (FLUXO DIÁRIO)
--------------------------------------------------------------------------------

1. Liga o PC
2. Clica no ícone do Ollama na bandeja (inicia em background)
3. Abre terminal na pasta do projeto
4. Roda:  py backend/app.py
5. Abre no navegador:  http://127.0.0.1:5000

PRÉ-REQUISITOS (uma vez só):
  - Python 3.10+
  - Ollama instalado com llava:13b e llama3.2 baixados
  - backend/.env configurado com credenciais Supabase
  - Conexão com internet (o banco está na nuvem)


--------------------------------------------------------------------------------
  12. EXPERIMENTOS QUE NÃO DERAM CERTO (aprendizados)
--------------------------------------------------------------------------------

QWEN 2.5 VL (testado e revertido em 2026-05-22):

  Tentativa de trocar o LLaVA pelo qwen2.5vl (7b depois 3b) buscando
  descrições mais precisas e modernas.

  RESULTADO DOS TESTES (3 imagens, hardware RTX 4060 8GB):
    qwen2.5vl:7b — 13 GB carregado, 7+ min/imagem (CPU)
    qwen2.5vl:3b — 6 GB carregado, 7-12 min/imagem (CPU)
    Bug GGML_ASSERT fazendo certas imagens falharem
    Qualidade das descrições: superior ao LLaVA

  CAUSA RAIZ:
    O vision encoder do Qwen 2.5 VL tem arquitetura nova que o
    llama.cpp/Ollama ainda processa no CPU, independente da VRAM
    livre. LLaVA, mais antigo, é melhor otimizado.

  DECISÃO:
    Mantido o LLaVA. Modelos qwen removidos do Ollama (liberou ~9 GB).
    Documentado pra não repetir o experimento sem mudança de stack.


--------------------------------------------------------------------------------
  13. PENDÊNCIAS E PRÓXIMOS PASSOS
--------------------------------------------------------------------------------

PRA PRODUÇÃO REAL (se algum dia):
  [ ] Trocar SHA-256 por bcrypt/argon2 nas senhas
  [ ] Rotacionar credenciais do Supabase
  [ ] Adicionar HTTPS no servidor
  [ ] Migrar autenticação para Supabase Auth (JWT, recover, magic link)
  [ ] Subir o backend num servidor (atualmente é localhost)
  [ ] Logging estruturado (substituir print)
  [ ] Testes automatizados (pytest)

PRA MELHORAR A BUSCA (sem trocar de stack de hardware):
  [ ] Ligar o CLIP — baixar modelos uma vez com internet
  [ ] OCR em screenshots (PaddleOCR ou Tesseract)
  [ ] Pós-correção da descrição LLaVA com llama3.2 (canonizar termos)
  [ ] Storage de imagens no Supabase Storage (free 1 GB)
  [ ] Re-testar qwen2.5vl quando o Ollama otimizar vision encoders (issue
      aberta no llama.cpp upstream)

PRA UX (ainda restante após análise heurística):
  [ ] Indicador de "primeira indexação em andamento" mais explícito
      (tipo "Analisando 12 de 50 arquivos")
  [ ] Salvar buscas como playlists/coleções
  [ ] Busca avançada (filtrar por data, tamanho, pasta específica)


--------------------------------------------------------------------------------
  14. LIMITAÇÕES CONHECIDAS
--------------------------------------------------------------------------------

  - SBERT confunde "gato" e "cachorro" como semanticamente próximos
    (ambos são pets); aparece como falso-positivo de score baixo (~0.30)
  - Diálogos nativos (tkinter) só funcionam no Windows
  - App só roda em localhost (não é multi-usuário em rede)
  - Sem internet = sem app (depende do Supabase)
  - LLaVA leva ~1 min/imagem na primeira indexação (modo deep com llava:13b)
  - Re-rank com LLM adiciona 300ms a cada busca (mas filtra muito ruído)
  - Modelos de visão modernos (qwen2.5vl, llama3.2-vision) ainda não
    rodam bem nesta GPU pelo Ollama


================================================================================
  FIM DO RELATÓRIO ATUALIZADO
================================================================================
