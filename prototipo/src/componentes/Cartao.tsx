import { capa, frase, pasta, type Arquivo } from '../api';

const IMAGENS = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'];

// Por que este arquivo apareceu. A API manda a palavra sem acento.
const ORIGEM: Record<string, string> = {
  aparencia: 'pela aparência',
  texto: 'pelo texto',
};

type Props = { arquivo: Arquivo; indice: number };

export function Cartao({ arquivo, indice }: Props) {
  const ext = (arquivo.tipo || '').toLowerCase();
  const eImagem = IMAGENS.includes(ext);
  const texto = frase(arquivo);
  const onde = pasta(arquivo);

  return (
    <button
      type="button"
      className="cartao"
      // Entrada escalonada de 40ms: rápida o bastante para parecer uma lista
      // só, lenta o bastante para o olho seguir a ordem. A animação é CSS de
      // propósito — roda fora da thread principal, que na hora de renderizar
      // resultados está ocupada.
      style={{ animationDelay: `${Math.min(indice, 8) * 40}ms` }}
    >
      <span className="cartao-capa">
        {eImagem ? (
          <img src={capa(arquivo)} alt={texto || arquivo.nome} loading="lazy" />
        ) : (
          ext.toUpperCase()
        )}
      </span>

      <span className="cartao-corpo">
        {/* O que é vem primeiro: é o que a pessoa lembra e o que ela veio
            confirmar. Sem descrição ainda, o nome assume a manchete. */}
        <p className="cartao-frase">{texto || arquivo.nome}</p>
        <p className="cartao-apoio">
          {texto ? [arquivo.nome, onde].filter(Boolean).join('  ·  ') : onde}
        </p>
        <span className="cartao-selos">
          <span className="selo">{ext.toUpperCase()}</span>
          {arquivo.origem && (
            <span className="selo">{ORIGEM[arquivo.origem] ?? arquivo.origem}</span>
          )}
        </span>
      </span>
    </button>
  );
}
