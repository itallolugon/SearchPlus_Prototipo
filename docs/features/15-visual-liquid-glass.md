# Feature — Visual liquid glass

**Data:** 14/09/2026
**Branch:** `feature/visual-liquid-glass` (ver [`../07-git-fluxo.md`](../07-git-fluxo.md))
**Status:** **implementado**. Só camada visual: `backend/` não foi alterado, e
todo comportamento que chegou na `develop` (seleção em massa, lixeira, resumo
da análise, histórico de exportações, refino, pastas da coleção) foi mantido e
redesenhado, não substituído.

---

## 1. O que muda na tela

- **Fundo.** `theme-wave.js` desenha a paisagem em WebGL2 com quatro cenas
  (Vale, Cordilheira, Névoa, Fiorde). O desfoque padrão ficou menor e continua
  ajustável em Ajustes.
- **Paleta.** Roxo e rosa saem. O destaque é ardósia (`#6F87A8` / `#A2B5CB`),
  próximo do cinza do vidro. Quem tinha as cores antigas salvas é migrado
  (`FABRICAS_VELHAS`, que agora reconhece também o `#AB5AF7`).
- **Tela inicial limpa.** Logo, busca e quatro quadros nos cantos (Pastas,
  Acervo, Fila, Categorias). Os quadros só aparecem com a sessão aberta e
  somem quando o acervo está aberto. O da Fila dispara a análise.
- **Dock.** Trilho à esquerda com Início, Buscar, Acervo, Coleções, Favoritos,
  Pastas, Re-analisar, Ajustes, **Última análise, Exportações, Lixeira** e
  Ajuda. As três em negrito eram do menu lateral da `develop`, que o dock
  substituiu. Abaixo de 820px o dock vira barra inferior que rola de lado.
- **Acervo em prateleiras.** Uma faixa por categoria, com setas e a opção
  "Ver a pasta completa" no fim e no cabeçalho.
- **Folhas.** Todo modal usa o mesmo cabeçalho: rótulo miúdo, título, fechar
  redondo (`.sheet-head`, `.sheet-close`).
- **Laboratório.** `lab.js`: propostas visuais ligáveis em Ajustes.

---

## 2. Features da `develop` no design novo

| Feature | Onde aparece | Como ficou |
|---|---|---|
| Seleção em massa e por categoria | resultados, prateleiras | caixas de vidro nos cantos da capa (aparecem sob o ponteiro; marcadas ficam); "Selecionar tudo" no cabeçalho da prateleira; barra flutuante de vidro |
| Favoritar pela galeria | prateleiras | coração no canto oposto, mesmo estado dos resultados |
| Seletor de pastas da home | acervo | pílula discreta sob a saudação |
| Trilha do refino | resultados | chips de vidro com X |
| Busca sem resultado | resultados | chapa de vidro com sugestões |
| Lixeira, Última análise, Exportações | dock | folhas com linhas de lista |
| Confirmar e Digitar | qualquer fluxo | folhas; o X **cancela** |
| Coleções: status, configurações, pastas da coleção, exportar de novo, excluir pastas, vínculo, opções e progresso da exportação | coleções | folhas; ações destrutivas em vermelho sóbrio |

Estilos inline de aparência dessas telas viraram classe. As cores fixas da
`develop` (`rgba(168,85,247,…)`, `rgba(0,0,0,.3)`, `#ef4444`) foram trocadas por
tokens, que acompanham o tema claro.

---

## 3. Decisões que mexem em comportamento

- **Esc nos modais novos.** `fecharModalDeCima`, o foco inicial e o
  `_prepararModal` reconheciam só `.close-btn`. Sem `.sheet-close` na lista, o
  Esc escondia a folha por fora e pulava a rotina de fechar dela.
- **Confirmar e Digitar ganharam X que cancela.** Antes o Esc escondia o modal
  e deixava a promessa sem resposta.
- **Capa não é mais `<button>`.** Dentro dela moram selecionar e favoritar, e
  botão dentro de botão é inválido. A capa é um `div` com um botão "Abrir"
  cobrindo a imagem; o nome entra por `textContent` e o clique leva o índice.
- **`mostrarHome()`** continua recarregando a galeria (o que
  `test_home_acompanha_analise` exige), mas só revela as prateleiras com o
  Acervo aberto: a entrada é a tela limpa.
- **Esc sem nada aberto** volta pra tela inicial, exceto quando a tecla nasceu
  num modal que acabou de se fechar sozinho.
- **Painéis laterais fechados** ficam `visibility: hidden`. Escondidos só por
  `right: -420px`, sobravam 30px à mostra com a sombra, e o Tab passeava pelos
  botões de um painel invisível.
- **`formatImagePath`** é a da `develop`. O atalho de fotos de demonstração
  usado no protótipo local não entra: ele trocaria arquivos reais de mesmo
  nome.

---

## 4. Verificação

- `pytest tests/unit`: 791 passaram, 1 pulado (symlink sem permissão no Windows).
- `node --check` em `script.js`, `lab.js` e `theme-wave.js`.
- Capturas contra `backend/mock_server.py` nos temas escuro e claro e em 500px,
  comparadas com a versão anterior ao merge para separar regressão de defeito
  antigo.

---

## 5. Limites conhecidos

- Perfil, onboarding e o painel de personalização ainda têm estilo inline de
  **layout** (margem, flex, tamanho de fonte), sem cor. Candidatos a classe.
- O `style.css` tem blocos repetidos para `.poster-img` e `.dock`; vale o
  último, e os comentários apontam qual.
- WebGL não desenha dentro de `iframe`: capturas automatizadas mostram o fundo
  reserva, não a paisagem.
