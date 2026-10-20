// Mesma API do app: o protótipo não simula nada por conta própria. O proxy do
// Vite manda /api e /demo-fotos para o servidor de teste na porta 5001.

export type Arquivo = {
  id: number;
  nome: string;
  caminho: string;
  tipo: string;
  descricao_ia?: string;
  trecho?: string;
  favorito?: boolean;
  origem?: string;
  data?: string;
};

const JSON_HEADERS = { 'Content-Type': 'application/json' };

export async function entrar(usuario = 'demo'): Promise<void> {
  // check_session é o único endpoint que responde 401 sem sessão; o histórico
  // devolve 200 com lista vazia e enganaria a verificação.
  const r = await fetch('/api/check_session');
  if (r.ok) return;
  await fetch('/api/login', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ username: usuario, password: usuario }),
  });
}

export async function buscar(consulta: string): Promise<Arquivo[]> {
  const r = await fetch('/api/search', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ query: consulta, filtro: 'all' }),
  });
  if (!r.ok) throw new Error('busca falhou');
  const d = await r.json();
  return Array.isArray(d) ? d : d.resultados || [];
}

export type Numeros = { arquivos: number; pastas: number; fila: number };

export async function numeros(): Promise<Numeros> {
  try {
    const [stats, status] = await Promise.all([
      fetch('/api/stats').then((r) => r.json()),
      fetch('/api/status').then((r) => r.json()),
    ]);
    return {
      arquivos: stats.total_arquivos ?? 0,
      pastas: stats.total_pastas ?? 0,
      fila: status.arquivos_pendentes ?? 0,
    };
  } catch {
    return { arquivos: 0, pastas: 0, fila: 0 };
  }
}

// A descrição da IA vem em campos ("- Estilo: … - O que é: …"). Na tela cabe
// uma frase: a que responde "o que é isto".
export function frase(arquivo: Arquivo): string {
  const bruto = (arquivo.descricao_ia || arquivo.trecho || '').trim();
  if (!bruto || bruto.startsWith('Nenhum conteúdo')) return '';
  const linhas = bruto.split(/\n|(?= - )/);
  const oQueE = linhas.find((l) => /o que é\s*:/i.test(l));
  const escolhida = oQueE || linhas[0] || '';
  return escolhida.replace(/^[-•\s]*/, '').replace(/^o que é\s*:\s*/i, '').trim();
}

export function pasta(arquivo: Arquivo): string {
  const partes = (arquivo.caminho || '').split(/[\\/]/);
  return partes.length > 1 ? partes[partes.length - 2] : '';
}

// As fotos de exemplo do servidor de teste. No app real este atalho não existe:
// o caminho do usuário vai direto para /api/file.
const DEMO = new Set([
  'praia-por-do-sol', 'cachorro-parque', 'gato-janela', 'equipe-reuniao',
  'desenho-dragao', 'sushi-combinado', 'cidade-noite', 'anime-personagem',
  'montanha-neve',
]);

export function capa(arquivo: Arquivo): string {
  const base = (arquivo.nome || '').replace(/\.[^.]+$/, '');
  if (DEMO.has(base)) return `/demo-fotos/${base}.jpg`;
  return `/api/file/${encodeURIComponent(arquivo.caminho)}`;
}
