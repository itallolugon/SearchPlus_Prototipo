import { useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';

type Destino = { id: string; rotulo: string; caminho: string };

// Ícone de 20px, traço de 1.6: o mesmo peso em todos, senão um parece mais
// escuro que o outro sem ninguém saber dizer por quê.
const DESTINOS: Destino[] = [
  { id: 'buscar', rotulo: 'Buscar', caminho: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14ZM20 20l-3.5-3.5' },
  { id: 'acervo', rotulo: 'Acervo', caminho: 'M4 5h6v6H4zM14 5h6v6h-6zM4 15h6v4H4zM14 15h6v4h-6z' },
  { id: 'colecoes', rotulo: 'Coleções', caminho: 'M4 6h16v5H4zM4 14h16v4H4z' },
  { id: 'favoritos', rotulo: 'Favoritos', caminho: 'M12 20 5 13a4.2 4.2 0 0 1 6-6l1 1 1-1a4.2 4.2 0 0 1 6 6z' },
  { id: 'pastas', rotulo: 'Pastas', caminho: 'M4 7a2 2 0 0 1 2-2h3l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z' },
  { id: 'atividade', rotulo: 'Atividade', caminho: 'M4 12h4l2 5 4-12 2 7h4' },
];

export function Trilho({ atual }: { atual: string }) {
  const [sobre, setSobre] = useState<string | null>(null);

  return (
    <nav className="trilho" aria-label="Navegação">
      <div className="marca" aria-hidden="true">
        S
      </div>

      {DESTINOS.map((d) => (
        <button
          key={d.id}
          type="button"
          className="trilho-btn"
          aria-label={d.rotulo}
          aria-current={d.id === atual ? 'page' : undefined}
          onMouseEnter={() => setSobre(d.id)}
          onMouseLeave={() => setSobre((s) => (s === d.id ? null : s))}
          onFocus={() => setSobre(d.id)}
          onBlur={() => setSobre((s) => (s === d.id ? null : s))}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d={d.caminho}
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>

          {/* O balão nasce em 0.97 e some rápido: entrada explica, saída não
              precisa ser vista. */}
          <AnimatePresence>
            {sobre === d.id && (
              <motion.span
                className="trilho-dica"
                role="tooltip"
                initial={{ opacity: 0, transform: 'translateY(-50%) scale(0.97)' }}
                animate={{ opacity: 1, transform: 'translateY(-50%) scale(1)' }}
                exit={{ opacity: 0, transform: 'translateY(-50%) scale(0.97)' }}
                transition={{ duration: 0.14, ease: [0.23, 1, 0.32, 1] }}
                style={{ top: '50%', transformOrigin: 'left center' }}
              >
                {d.rotulo}
              </motion.span>
            )}
          </AnimatePresence>
        </button>
      ))}
    </nav>
  );
}
