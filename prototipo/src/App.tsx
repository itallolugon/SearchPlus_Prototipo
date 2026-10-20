import { useEffect, useRef, useState } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import { Trilho } from './componentes/Trilho';
import { Cartao } from './componentes/Cartao';
import { buscar, entrar, numeros, type Arquivo, type Numeros } from './api';

const SAIDA = [0.23, 1, 0.32, 1] as const;

const EXEMPLOS = [
  'recibo do mercado',
  'foto da praia com guarda-sol',
  'contrato assinado em janeiro',
];

type Fase = 'casa' | 'buscando' | 'resultados';

export function App() {
  const [fase, setFase] = useState<Fase>('casa');
  const [consulta, setConsulta] = useState('');
  const [resultados, setResultados] = useState<Arquivo[]>([]);
  const [erro, setErro] = useState('');
  const [acervo, setAcervo] = useState<Numeros | null>(null);
  const campo = useRef<HTMLInputElement>(null);
  const quieto = useReducedMotion() ?? false;

  useEffect(() => {
    entrar().then(() => {
      numeros().then(setAcervo);
      // ?q=… já entra buscando: link de busca é link que a pessoa pode mandar
      // para alguém (e é como as telas deste protótipo são capturadas).
      const q = new URLSearchParams(location.search).get('q');
      if (q) enviar(q);
    });
  }, []);

  // "/" cai no campo de qualquer lugar; Esc volta pra casa. Nada disso anima
  // além do necessário: atalho de teclado repetido não pede espetáculo.
  useEffect(() => {
    function tecla(e: KeyboardEvent) {
      const alvo = e.target as HTMLElement | null;
      const digitando = alvo?.tagName === 'INPUT' || alvo?.tagName === 'TEXTAREA';
      if (e.key === '/' && !digitando) {
        e.preventDefault();
        campo.current?.focus();
      }
      if (e.key === 'Escape' && !digitando) setFase('casa');
    }
    window.addEventListener('keydown', tecla);
    return () => window.removeEventListener('keydown', tecla);
  }, []);

  async function enviar(texto: string) {
    const q = texto.trim();
    if (!q) return;
    setConsulta(q);
    setErro('');
    setFase('buscando');
    try {
      const achados = await buscar(q);
      setResultados(achados);
    } catch {
      setResultados([]);
      setErro('A busca não respondeu. O servidor de teste está no ar?');
    }
    // Sem piso de espera: a tela troca quando a resposta chega, não quando um
    // cronômetro deixa.
    setFase('resultados');
  }

  const campoBusca = (
    <motion.form
      layoutId="campo"
      layout="position"
      className="campo"
      transition={{ duration: quieto ? 0 : 0.34, ease: SAIDA }}
      onSubmit={(e) => {
        e.preventDefault();
        enviar(campo.current?.value ?? '');
      }}
    >
      <span className="campo-icone" aria-hidden="true">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
          <path
            d="M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14ZM20 20l-3.5-3.5"
            stroke="currentColor"
            strokeWidth="1.7"
            strokeLinecap="round"
          />
        </svg>
      </span>
      <input
        ref={campo}
        type="search"
        defaultValue={consulta}
        placeholder="descreva o que você lembra do arquivo"
        aria-label="Descreva o que você lembra do arquivo"
        autoComplete="off"
      />
      {fase === 'casa' && (
        <kbd className="campo-atalho" aria-hidden="true">
          /
        </kbd>
      )}
      <button type="submit" className="campo-acao">
        Buscar
      </button>
    </motion.form>
  );

  const sugestoes = EXEMPLOS.map((e) => (
    <button key={e} type="button" className="exemplo" onClick={() => enviar(e)}>
      {e}
    </button>
  ));

  return (
    <div className="app">
      <Trilho atual="buscar" />

      <main className="palco">
        {fase === 'casa' ? (
          <div className="casa">
            <h1 className="casa-titulo">Você não precisa lembrar o nome.</h1>
            <p className="casa-linha">
              Descreva a cena, o assunto ou o que estava escrito. O Search+ procura pelo
              conteúdo dos seus arquivos, não pelo nome que o celular deu a eles.
            </p>

            {campoBusca}

            <div className="exemplos">{sugestoes}</div>

            <p className="estado">
              {acervo ? (
                <>
                  <span className="estado-ponto" aria-hidden="true" />
                  <span>
                    <b>{acervo.arquivos}</b> arquivos prontos em <b>{acervo.pastas}</b> pastas
                    {acervo.fila > 0 && <> · {acervo.fila} na fila de leitura</>}
                  </span>
                </>
              ) : (
                <span>Conferindo o acervo…</span>
              )}
            </p>
          </div>
        ) : (
          <>
            <div className="topo">
              <div className="topo-linha">{campoBusca}</div>
            </div>

            {fase === 'buscando' ? (
              <>
                <p className="resumo" role="status">
                  Procurando por “{consulta}”…
                </p>
                <div className="espera" aria-hidden="true">
                  {Array.from({ length: 6 }, (_, i) => (
                    <div key={i} className="esqueleto" />
                  ))}
                </div>
              </>
            ) : (
              <>
                <p className="resumo" role="status">
                  {erro ||
                    (resultados.length === 0
                      ? ''
                      : `${resultados.length} ${
                          resultados.length === 1 ? 'arquivo combina' : 'arquivos combinam'
                        } com “${consulta}”`)}
                </p>

                {resultados.length === 0 && !erro ? (
                  <div className="vazio">
                    <h2>Nada com essa descrição.</h2>
                    <p>
                      Nenhum arquivo combina com “{consulta}”. Tente dizer o que aparece no
                      arquivo em vez de como ele se chama — “nota fiscal da geladeira” em vez
                      de “doc final v2”.
                    </p>
                    <div className="exemplos exemplos-centro">{sugestoes}</div>
                  </div>
                ) : (
                  <div className="grade">
                    {resultados.map((a, i) => (
                      <Cartao key={`${a.id}-${a.caminho}`} arquivo={a} indice={i} />
                    ))}
                  </div>
                )}
              </>
            )}
          </>
        )}
      </main>
    </div>
  );
}
