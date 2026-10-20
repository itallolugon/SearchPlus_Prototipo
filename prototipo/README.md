# Protótipo de design

Tela de busca do Search+ reconstruída em React + Vite + Motion, para comparar
com a interface atual lado a lado. **Não substitui nada**: o app continua
sendo `index.html` + `script.js` na raiz.

```bash
py backend/mock_server.py   # na raiz do projeto, porta 5001
cd prototipo && npm install && npm run dev
```

Abra http://localhost:5173. O Vite manda `/api` e `/demo-fotos` para a porta
5001 — é o mesmo servidor de teste, os mesmos dados, o mesmo login. O backend
não foi tocado.

`?q=alguma coisa` na URL já entra buscando.

## O que este protótipo defende

- O cartão começa pela descrição da IA; o nome do arquivo desce para a linha
  de apoio, junto da pasta. O nome é a string que a pessoa nunca soube.
- A busca troca de tela quando a resposta chega, sem piso de espera.
- Movimento curto e com curva própria (`cubic-bezier(.23,1,.32,1)`): 240ms
  nos cartões, 140ms nas dicas, `scale(0.97)` em tudo que se pressiona.
- A entrada dos cartões é CSS, não JS — roda fora da thread principal, que na
  hora de desenhar resultados está ocupada.
- `prefers-reduced-motion` desliga o deslocamento sem tirar conteúdo.
