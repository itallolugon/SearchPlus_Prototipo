# Organização do Git — Search+ (main / develop / feature)

A equipe adota o fluxo **Git Flow simplificado**, exigido na N2.

## Branches

| Branch | Papel |
|---|---|
| **main** | Versão estável, sempre funcional. É o que se apresenta. |
| **develop** | Integração do trabalho em andamento. Recebe as `feature/*` antes de irem pra `main`. |
| **feature/\*** | Uma branch por funcionalidade nova. Ex: `feature/busca-por-imagem`. |

## Fluxo de trabalho

```
feature/nome  ──►  develop  ──►  main
   (desenvolve)    (integra)    (estável/release)
```

1. Para uma tarefa nova, crie a branch a partir de `develop`:
   ```bash
   git checkout develop
   git checkout -b feature/nome-da-tarefa
   ```
2. Desenvolva e faça commits na `feature/*`.
3. Quando pronta, integre na `develop`:
   ```bash
   git checkout develop
   git merge feature/nome-da-tarefa
   ```
4. Quando a `develop` estiver estável, promova para `main`:
   ```bash
   git checkout main
   git merge develop
   git push origin main
   ```

## Exemplos de nomes de feature (baseados no que já foi feito)
- `feature/busca-por-imagem`
- `feature/colecoes`
- `feature/menu-lateral`
- `feature/exportar-tema`
- `fix/categorizacao-galeria`

## Convenção de mensagens de commit
O projeto usa prefixos semânticos:
- `feat:` nova funcionalidade
- `fix:` correção de bug
- `docs:` documentação
- `chore:` manutenção/organização
- `merge:` integração de branches

## Estado atual
- `main` — estável, com todo o sistema funcionando (N2).
- `develop` — criada a partir de `main` para receber as próximas features.
- Histórico completo (≈45 commits) documentado no
  [Dossiê de Sprint](06-dossie-tecnico-sprints.md).
