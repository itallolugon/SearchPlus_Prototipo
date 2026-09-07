// Deriva a URL da API da própria página, em vez de fixar uma porta: o mesmo
// arquivo serve tanto o backend real (5000) quanto o servidor mock (5001), sem
// editar nada. Só cai no valor fixo quando a página é aberta pelo file://,
// onde não há origem HTTP para herdar.
const API_BASE_URL =
    window.location.protocol.startsWith("http")
        ? window.location.origin
        : "http://127.0.0.1:5000";
// ---------------------------------------------------------------------------
// ICONES
// ---------------------------------------------------------------------------
// Os simbolos ficam definidos uma vez no index.html; aqui so referenciamos.
//
// Duas formas, e a escolha entre elas nao e de gosto:
//
//   icone()      devolve um ELEMENTO. Use quando o rotulo ao lado vier de
//                dado do usuario -- nome de pasta, de colecao, de arquivo.
//                Montar isso com template string e innerHTML abriria injecao
//                de HTML atraves de um nome de pasta.
//   iconeHTML()  devolve texto, para os templates que ja usam innerHTML. So
//                recebe nomes de icone escritos aqui no codigo, nunca dado de
//                fora, entao nao ha o que injetar.
//
// `aria-hidden` em todos: o icone e decoracao ao lado de um rotulo que o
// leitor de tela ja anuncia. Quando o botao e SO o icone, quem chama poe um
// `aria-label` no botao -- e ha um teste de acessibilidade cobrindo isso.

const _SVG_NS = 'http://www.w3.org/2000/svg';

function icone(nome, classe) {
    const svg = document.createElementNS(_SVG_NS, 'svg');
    svg.setAttribute('class', 'ic' + (classe ? ' ' + classe : ''));
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    const uso = document.createElementNS(_SVG_NS, 'use');
    uso.setAttribute('href', '#ic-' + nome);
    svg.appendChild(uso);
    return svg;
}

function iconeHTML(nome, classe) {
    return '<svg class="ic' + (classe ? ' ' + classe : '') + '" aria-hidden="true" ' +
           'focusable="false"><use href="#ic-' + nome + '"></use></svg>';
}

// Troca o conteudo de um elemento por "icone + texto". Substitui os
// `el.textContent = '\ud83d\udcc1 ' + nome` que existiam antes: o texto continua
// entrando como texto, e nao como HTML.
function rotularCom(el, nome, texto, classe) {
    if (!el) return;
    el.replaceChildren(icone(nome, classe), document.createTextNode(' ' + texto));
}

// Marca ou desmarca uma caixa de selecao. Existia como
// `btn.textContent = marcado ? '\u2713' : ''` em cinco lugares; virou funcao para
// que os cinco concordem sobre o que "marcado" desenha.
function marcarBotaoSelecao(btn, marcado) {
    if (!btn) return;
    btn.replaceChildren();
    if (marcado) btn.appendChild(icone('check'));
}

// Favorito: o MESMO coracao, vazado ou preenchido.
//
// Antes eram dois glifos de texto diferentes (vazado e cheio). A propriedade
// que importa se manteve: a diferenca entre favoritado e nao favoritado nao e
// so de cor -- a forma muda tambem, entao quem nao distingue as duas cores
// continua enxergando o estado. Ver o comentario correspondente no style.css.
function iconeFav(favoritado) {
    return icone('coracao', favoritado ? 'ic--cheio' : '');
}

function iconeFavHTML(favoritado) {
    return iconeHTML('coracao', favoritado ? 'ic--cheio' : '');
}

let currentConfig = {};
let tempConfig = {};

let cropper;
let targetCropInput = '';

window.resultadosAtuais = [];
window.ultimoTempoBusca = 0;
let filtroAtual = 'all';

// Cores padrão do tema. Auditadas contra o mínimo de contraste da WCAG (4,5:1
// para texto normal) — ver o comentário em style.css sobre os dois papéis do
// destaque. Ficam aqui porque é o JS que aplica o tema, sobrescrevendo o CSS.
const COR_PRIMARIA_PADRAO = '#AB5AF7';
const COR_SECUNDARIA_PADRAO = '#E879F9';

// Indexação Inteligente Seletiva — estado local
let _obPrioridades = ['tudo'];
let _obPerfil = 'fast';
let _obJanela = 'always';
let _obLastFolder = '';
let _modalPrioridades = ['tudo'];
let _modalPerfil = 'fast';
let _modalJanela = 'always';
let _modalEditingFolderId = null;
let _modalEditingFolderPath = '';
let _foldersData = []; // cache dos objetos completos de pastas

const fetchOptions = { headers: { 'Content-Type': 'application/json' } };

const extensoesImagem = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'];
const extensoesVideo = ['mp4', 'avi', 'mkv', 'mov', 'webm'];
const extensoesAudio = ['mp3', 'wav', 'ogg', 'm4a', 'flac'];
// Imagem preta pura 1x1 
const placeholderPreto = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=";

document.addEventListener('DOMContentLoaded', () => {
    carregarFavoritosDash();
    // Só os botões de TIPO trocam o filtro. Os outros que moram nesta barra
    // ("Filtros", "Favoritos") não têm data-filter, e sem esta checagem
    // clicar neles zerava `filtroAtual`. Com ele nulo, resultadosVisiveis()
    // caía no último ramo e devolvia só documentos — abrir os filtros
    // avançados escondia todas as imagens do resultado, em silêncio.
    document.querySelectorAll('.filter-tag[data-filter]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const alvo = e.currentTarget;
            document.querySelectorAll('.filter-tag[data-filter]')
                .forEach(b => b.classList.remove('active'));
            alvo.classList.add('active');
            filtroAtual = alvo.getAttribute('data-filter');
            if (document.getElementById('searchResultsView').style.display === 'block') {
                renderizarResultados();
            }
        });
    });
});

// Falha silenciosa: a rede de segurança.
// ---------------------------------------------------------------------------
// Boa parte do app trata erro HTTP (`if (!r.ok)`) mas não trata a rede cair.
// São coisas diferentes: com o servidor fora do ar o `fetch` REJEITA, a função
// morre ali, e o usuário fica olhando para um clique que não fez nada — sem
// mensagem, sem carregando, sem nada. É o pior tipo de falha, porque a pessoa
// não sabe se deu errado ou se ela é que não clicou direito.
//
// Consertar as funções uma a uma resolve as de hoje e não resolve a próxima
// que alguém escrever. Este ouvinte pega a classe inteira, inclusive o código
// que ainda não existe.
//
// Não substitui tratamento específico: quando dá para dizer O QUE falhou
// ("não foi possível remover a pasta"), a função continua dizendo. Isto aqui é
// o piso, para que nunca seja silêncio.
let _ultimoAvisoDeRede = 0;

window.addEventListener('unhandledrejection', (evento) => {
    const motivo = evento.reason;
    const ehRede = motivo instanceof TypeError
        && /fetch|network|failed|load/i.test(String(motivo.message || ''));

    // O log continua saindo em qualquer caso: quem está depurando precisa do
    // erro inteiro, não do resumo amigável.
    console.error('Promessa rejeitada sem tratamento:', motivo);

    if (!ehRede) return;

    // Uma tela que dispara várias chamadas de uma vez geraria um aviso por
    // chamada. Um a cada 5s basta para informar sem virar avalanche.
    const agora = Date.now();
    if (agora - _ultimoAvisoDeRede < 5000) return;
    _ultimoAvisoDeRede = agora;

    if (typeof toastErro === 'function') {
        toastErro('Não foi possível falar com o servidor. '
                  + 'Verifique se o Search+ ainda está rodando e tente de novo.');
    }
});

// ==========================================
// SISTEMA DE TOAST (notificações ao usuário)
// ==========================================
// Substitui alert() nativo e os console.error silenciosos.
// Tipos: 'sucesso' | 'erro' | 'info' | 'aviso'
function mostrarToast(mensagem, tipo = 'info', duracaoMs = 4500) {
    const container = document.getElementById('toastContainer');
    if (!container) { console.log(`[${tipo}] ${mensagem}`); return; }

    const icones = { sucesso: 'check-circulo', erro: 'x', info: 'info', aviso: 'alerta' };
    const toast = document.createElement('div');
    toast.className = `toast toast-${tipo}`;

    // Erro interrompe a leitura; o resto espera a pausa. Anunciar um "salvo
    // com sucesso" por cima do que a pessoa está lendo é tão ruim quanto
    // deixar um erro passar em silêncio.
    const grave = (tipo === 'erro');
    toast.setAttribute('role', grave ? 'alert' : 'status');
    toast.setAttribute('aria-live', grave ? 'assertive' : 'polite');

    toast.innerHTML = `
        <span class="toast-icone" aria-hidden="true">${iconeHTML(icones[tipo] || 'info')}</span>
        <span class="toast-msg"></span>
        <button class="toast-fechar" aria-label="Fechar">&times;</button>
    `;
    // textContent evita XSS — a mensagem pode conter dados do servidor
    toast.querySelector('.toast-msg').textContent = mensagem;

    const remover = () => {
        toast.classList.add('saindo');
        setTimeout(() => toast.remove(), 300);
    };
    toast.querySelector('.toast-fechar').onclick = remover;
    container.appendChild(toast);

    if (duracaoMs > 0) setTimeout(remover, duracaoMs);
}

// Toast com um botão de ação — hoje só "desfazer".
//
// Oito segundos: tempo de ler a frase, entender que era a coleção errada e
// alcançar o botão, sem que a faixa fique atravancando a tela. Quem perder a
// janela ainda encontra o item na lixeira, dentro das Configurações.
function toastComDesfazer(mensagem, aoDesfazer, duracaoMs = 8000) {
    return toastComAcao(mensagem, 'Desfazer', aoDesfazer, duracaoMs);
}

// Toast com um botão de ação nomeada. `toastComDesfazer` é o caso mais comum.
function toastComAcao(mensagem, rotulo, aoAgir, duracaoMs = 8000) {
    const container = document.getElementById('toastContainer');
    if (!container) { console.log(mensagem); return; }

    const toast = document.createElement('div');
    toast.className = 'toast toast-info toast-com-acao';
    // O botão de desfazer é o motivo de este aviso existir. Sem `aria-live`,
    // quem não vê a tela descobre a ação depois que ela já sumiu.
    toast.setAttribute('role', 'status');
    toast.setAttribute('aria-live', 'polite');
    toast.innerHTML = `
        <span class="toast-icone" aria-hidden="true">ℹ</span>
        <span class="toast-msg"></span>
        <button type="button" class="toast-acao"></button>
        <button type="button" class="toast-fechar" aria-label="Fechar">&times;</button>
    `;
    toast.querySelector('.toast-msg').textContent = mensagem;
    toast.querySelector('.toast-acao').textContent = rotulo;

    let encerrado = false;
    const remover = () => {
        if (encerrado) return;
        encerrado = true;
        clearTimeout(prazo);
        toast.classList.add('saindo');
        setTimeout(() => toast.remove(), 300);
    };
    const prazo = setTimeout(remover, duracaoMs);

    toast.querySelector('.toast-fechar').onclick = remover;
    toast.querySelector('.toast-acao').onclick = async (ev) => {
        // Desabilita antes de esperar a rede: dois cliques mandariam dois
        // pedidos de restauração, e o segundo acharia o item já restaurado e
        // devolveria 404 — um erro na tela por ter clicado com vontade.
        ev.currentTarget.disabled = true;
        ev.currentTarget.textContent = 'Um instante...';
        clearTimeout(prazo);
        try {
            await aoAgir();
        } finally {
            remover();
        }
    };

    container.appendChild(toast);
}

async function desfazerExclusao(lixeiraId, aoTerminar) {
    try {
        const r = await fetch(`${API_BASE_URL}/api/lixeira/${lixeiraId}/restaurar`,
                              { method: 'POST', headers: fetchOptions.headers });
        if (!r.ok) {
            toastErro(await _erroDaResposta(r, 'Não foi possível desfazer'));
            return;
        }
        const d = await r.json();
        toastOk(d.tipo === 'colecao'
            ? `“${d.rotulo}” foi restaurada.`
            : `${d.rotulo} de volta na coleção.`);
        if (aoTerminar) await aoTerminar();
    } catch (e) {
        toastErro('Não foi possível desfazer. O servidor respondeu?');
    }
}

// ==========================================
// HISTÓRICO DAS EXPORTAÇÕES
// ==========================================
// O resultado de uma exportação sumia junto com o modal: quem exportou 200
// fotos, viu "8 falharam" e fechou a janela ficava sem saber quais eram, para
// onde tinha exportado, nem se aquilo era de hoje ou da semana passada.
const _MOTIVO_FALHA = {
    nao_encontrado: 'não está mais no computador',
    sem_permissao: 'o Windows não deixou copiar',
    fora_das_pastas: 'está fora das pastas do computador',
    erro_leitura: 'não foi possível ler o arquivo',
};

async function abrirHistoricoExport() {
    const modal = document.getElementById('historicoExportModal');
    const corpo = document.getElementById('historicoExportCorpo');
    modal.style.display = 'flex';
    corpo.innerHTML = '<p style="color:var(--text-secondary);">Carregando...</p>';

    let d;
    try {
        const r = await fetch(`${API_BASE_URL}/api/exportacoes`);
        if (!r.ok) {
            corpo.innerHTML = '<p style="color:var(--text-secondary);">Não foi possível abrir o histórico.</p>';
            return;
        }
        d = await r.json();
    } catch (e) {
        corpo.innerHTML = '<p style="color:var(--text-secondary);">Não foi possível abrir o histórico. O servidor respondeu?</p>';
        return;
    }

    const itens = d.exportacoes || [];
    if (!itens.length) {
        corpo.innerHTML = '<p style="color:var(--text-secondary);">' +
            'Você ainda não exportou nenhuma coleção.</p>';
        return;
    }

    corpo.innerHTML = '';
    itens.forEach(e => corpo.appendChild(_linhaDeExportacao(e)));
}

function _linhaDeExportacao(e) {
    const bloco = document.createElement('div');
    bloco.className = 'export-hist';

    const quando = e.quando
        ? new Date(e.quando).toLocaleString('pt-BR',
            { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
        : '';

    const titulo = document.createElement('div');
    titulo.className = 'export-hist-titulo';
    titulo.textContent = e.colecao;
    bloco.appendChild(titulo);

    const meta = document.createElement('div');
    meta.className = 'export-hist-meta';
    const falhas = (e.falhas || []).length;
    meta.textContent = `${e.copiados} de ${e.total} ${e.total === 1 ? 'arquivo' : 'arquivos'}` +
        `${falhas ? `, ${falhas} ${falhas === 1 ? 'falhou' : 'falharam'}` : ''} · ${quando}`;
    bloco.appendChild(meta);

    const caminho = document.createElement('div');
    caminho.className = 'export-hist-caminho';
    caminho.textContent = e.pasta;
    bloco.appendChild(caminho);

    const acoes = document.createElement('div');
    acoes.className = 'export-hist-acoes';

    // O botão só aparece se a pasta ainda existir: um "abrir pasta" que não
    // abre nada é pior que nenhum botão.
    if (e.pasta_existe) {
        const abrir = document.createElement('button');
        abrir.type = 'button';
        abrir.className = 'action-btn';
        abrir.textContent = 'Abrir a pasta';
        abrir.onclick = () => abrirPastaExportada(e.pasta);
        acoes.appendChild(abrir);
    } else {
        const sumiu = document.createElement('span');
        sumiu.className = 'export-hist-sumiu';
        sumiu.textContent = 'A pasta não está mais aí.';
        acoes.appendChild(sumiu);
    }

    const podeRepetir = (e.falhas || []).some(f => f.motivo !== 'nao_encontrado');
    const temSumidos = (e.falhas || []).some(f => f.motivo === 'nao_encontrado');

    if (podeRepetir && e.pasta_existe) {
        const repetir = document.createElement('button');
        repetir.type = 'button';
        repetir.className = 'action-btn';
        repetir.textContent = 'Tentar de novo os que falharam';
        repetir.onclick = () => repetirExportacao(e.id);
        acoes.appendChild(repetir);
    }
    if (temSumidos) {
        const limpar = document.createElement('button');
        limpar.type = 'button';
        limpar.className = 'action-btn';
        limpar.textContent = 'Tirar da coleção os que sumiram';
        limpar.onclick = () => limparSumidos(e.id);
        acoes.appendChild(limpar);
    }
    bloco.appendChild(acoes);

    if (falhas) {
        const det = document.createElement('details');
        det.className = 'export-hist-falhas';
        const sum = document.createElement('summary');
        sum.textContent = `Ver ${falhas === 1 ? 'o arquivo' : `os ${falhas} arquivos`} que ${falhas === 1 ? 'falhou' : 'falharam'}`;
        det.appendChild(sum);
        const ul = document.createElement('ul');
        e.falhas.forEach(f => {
            const li = document.createElement('li');
            li.textContent = `${f.nome} — ${_MOTIVO_FALHA[f.motivo] || f.motivo}`;
            ul.appendChild(li);
        });
        det.appendChild(ul);
        bloco.appendChild(det);
    }

    return bloco;
}

async function repetirExportacao(exportId) {
    try {
        const r = await fetch(`${API_BASE_URL}/api/exportacoes/${exportId}/repetir`,
                              { method: 'POST', headers: fetchOptions.headers });
        if (!r.ok) {
            toastErro(await _erroDaResposta(r, 'Não foi possível tentar de novo'));
            return;
        }
        const d = await r.json();
        fecharHistoricoExport();
        _exportJobId = d.job_id;
        abrirModalExportacao(d.total);
        _exportTimer = setInterval(consultarExportacao, 400);
    } catch (e) {
        toastErro('Não foi possível tentar de novo. O servidor respondeu?');
    }
}

async function limparSumidos(exportId) {
    const ok = await confirmarAcao(
        'Tirar da coleção',
        'Os arquivos que não estão mais no computador saem da coleção. ' +
        'Dá para desfazer pela lixeira.',
        'Tirar da coleção');
    if (!ok) return;

    try {
        const r = await fetch(`${API_BASE_URL}/api/exportacoes/${exportId}/limpar_sumidos`,
                              { method: 'POST', headers: fetchOptions.headers });
        if (!r.ok) {
            toastErro(await _erroDaResposta(r, 'Não foi possível limpar a coleção'));
            return;
        }
        const d = await r.json();

        if (!d.removidos) {
            toastOk(d.mensagem || 'Nada foi removido.');
        } else if (d.lixeira_id) {
            toastComDesfazer(
                `${d.removidos} ${d.removidos === 1 ? 'arquivo saiu' : 'arquivos saíram'} da coleção.`,
                () => desfazerExclusao(d.lixeira_id, abrirHistoricoExport));
        }
        abrirHistoricoExport();
    } catch (e) {
        toastErro('Não foi possível limpar a coleção. O servidor respondeu?');
    }
}

function fecharHistoricoExport() {
    document.getElementById('historicoExportModal').style.display = 'none';
}

// ==========================================
// RESUMO DA INDEXAÇÃO
// ==========================================
// Antes, ao terminar, aparecia "Indexação concluída!" e mais nada. Quem
// apontou uma pasta com 4.000 arquivos e viu 3.200 indexados não tinha como
// saber o que houve com os outros 800 — nem se houve. A pergunta "cadê minhas
// fotos?" aparecia semanas depois, sem nada para responder.
async function abrirResumoIndexacao() {
    const modal = document.getElementById('resumoModal');
    const corpo = document.getElementById('resumoCorpo');
    modal.style.display = 'flex';
    corpo.innerHTML = '<p style="color:var(--text-secondary);">Carregando...</p>';

    let d;
    try {
        const r = await fetch(`${API_BASE_URL}/api/resumo_indexacao`);
        if (!r.ok) {
            corpo.innerHTML = '<p style="color:var(--text-secondary);">' +
                'Não foi possível abrir o resumo.</p>';
            return;
        }
        d = await r.json();
    } catch (e) {
        corpo.innerHTML = '<p style="color:var(--text-secondary);">' +
            'Não foi possível abrir o resumo. O servidor respondeu?</p>';
        return;
    }

    if (!d.resumo) {
        corpo.innerHTML = '<p style="color:var(--text-secondary);">' +
            'Nenhuma análise foi concluída ainda. Depois de analisar suas ' +
            'pastas, o resultado aparece aqui.</p>';
        return;
    }

    corpo.innerHTML = '';
    corpo.appendChild(_resumoCabecalho(d.resumo));
    (d.resumo.pastas || []).forEach(p => corpo.appendChild(_resumoDaPasta(p)));
}

function _resumoCabecalho(resumo) {
    const t = resumo.totais || {};
    const box = document.createElement('div');
    box.className = 'resumo-totais';

    const quando = resumo.fim
        ? new Date(resumo.fim).toLocaleString('pt-BR',
            { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
        : '';

    box.innerHTML = `
        <div class="resumo-linha-total"></div>
        <div class="resumo-quando"></div>
    `;
    box.querySelector('.resumo-linha-total').textContent =
        `${t.indexados || 0} ${t.indexados === 1 ? 'arquivo analisado' : 'arquivos analisados'}` +
        `${t.ignorados ? `, ${t.ignorados} ignorados` : ''}` +
        `${t.erros ? `, ${t.erros} com erro` : ''}.`;
    box.querySelector('.resumo-quando').textContent =
        quando ? `Concluída em ${quando}.` : '';
    return box;
}

function _resumoDaPasta(pasta) {
    const bloco = document.createElement('div');
    bloco.className = 'resumo-pasta';

    const nome = document.createElement('div');
    nome.className = 'resumo-pasta-caminho';
    nome.textContent = pasta.caminho || '(pasta desconhecida)';
    bloco.appendChild(nome);

    const linha = document.createElement('div');
    linha.className = 'resumo-pasta-numeros';

    // Ignorado e erro ficam separados de propósito. Juntos virariam "800
    // problemas" e a pessoa iria procurar defeito onde não há: um .zip no meio
    // das fotos não é falha do programa.
    const parte = (n, rotulo, ajuda) => {
        const el = document.createElement('span');
        el.className = 'resumo-numero';
        el.textContent = `${n} ${rotulo}`;
        el.title = ajuda;
        return el;
    };
    linha.appendChild(parte(pasta.indexados || 0, 'analisados',
        'Entraram na busca.'));
    linha.appendChild(parte(pasta.ignorados || 0, 'ignorados',
        'Tipos de arquivo que o Search+ não abre. Não é falha.'));
    linha.appendChild(parte(pasta.erros || 0, 'com erro',
        'Deviam ter entrado e não entraram.'));
    bloco.appendChild(linha);

    const comErro = pasta.arquivos_com_erro || [];
    if (comErro.length) {
        const det = document.createElement('details');
        det.className = 'resumo-erros';
        const sum = document.createElement('summary');
        sum.textContent = `Ver os ${comErro.length} ` +
            `${comErro.length === 1 ? 'arquivo' : 'arquivos'} com erro`;
        det.appendChild(sum);

        const lista = document.createElement('ul');
        comErro.forEach(a => {
            const li = document.createElement('li');
            li.textContent = `${a.nome} — ${a.motivo}`;
            lista.appendChild(li);
        });
        det.appendChild(lista);

        if ((pasta.erros || 0) > comErro.length) {
            const nota = document.createElement('p');
            nota.className = 'resumo-nota';
            nota.textContent =
                `Mais ${pasta.erros - comErro.length} não estão listados aqui.`;
            det.appendChild(nota);
        }
        bloco.appendChild(det);
    }

    return bloco;
}

function fecharResumoIndexacao() {
    document.getElementById('resumoModal').style.display = 'none';
}

// ==========================================
// LIXEIRA (Configurações)
// ==========================================
async function abrirLixeira() {
    const modal = document.getElementById('lixeiraModal');
    const lista = document.getElementById('lixeiraLista');
    modal.style.display = 'flex';
    lista.innerHTML = '<p style="color:var(--text-secondary);">Carregando...</p>';

    try {
        const r = await fetch(`${API_BASE_URL}/api/lixeira`);
        if (!r.ok) {
            lista.innerHTML = '<p style="color:var(--text-secondary);">' +
                'Não foi possível abrir a lixeira.</p>';
            return;
        }
        const d = await r.json();
        document.getElementById('lixeiraPrazo').textContent =
            `O que você exclui fica aqui por ${d.dias} dias e depois é descartado.`;

        if (!d.itens.length) {
            lista.innerHTML = '<p style="color:var(--text-secondary);">' +
                'A lixeira está vazia.</p>';
            return;
        }

        lista.innerHTML = '';
        d.itens.forEach(i => {
            const quando = new Date(i.excluido_em).toLocaleString('pt-BR', {
                day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
            const detalhe = i.tipo === 'colecao'
                ? `Coleção · ${i.imagens} ${i.imagens === 1 ? 'imagem' : 'imagens'}`
                : 'Imagens de uma coleção';
            const linha = document.createElement('div');
            linha.className = 'lixeira-item';
            linha.innerHTML = `
                <div style="flex:1; min-width:0;">
                    <div class="lixeira-item-nome"></div>
                    <div class="lixeira-item-meta"></div>
                </div>
                <button type="button" class="btn-config-folder">Restaurar</button>
                <button type="button" class="btn-remover">Descartar</button>
            `;
            linha.querySelector('.lixeira-item-nome').textContent = i.rotulo;
            linha.querySelector('.lixeira-item-meta').textContent = `${detalhe} · ${quando}`;

            const [btnRestaurar, btnDescartar] = linha.querySelectorAll('button');
            btnRestaurar.onclick = async () => {
                btnRestaurar.disabled = true;
                await desfazerExclusao(i.id, abrirLixeira);
                if (typeof carregarColecoes === 'function') carregarColecoes();
            };
            btnDescartar.onclick = () => descartarDaLixeira(i.id, i.rotulo);
            lista.appendChild(linha);
        });
    } catch (e) {
        lista.innerHTML = '<p style="color:var(--text-secondary);">' +
            'Não foi possível abrir a lixeira. O servidor respondeu?</p>';
    }
}

async function descartarDaLixeira(itemId, rotulo) {
    // Daqui não volta, então confirma. É a única exclusão do app sem desfazer,
    // e é assim de propósito: a lixeira é justamente o desfazer.
    const ok = await confirmarAcao(
        'Descartar de vez',
        `“${rotulo}” sai da lixeira e não poderá mais ser restaurado.`,
        'Descartar');
    if (!ok) return;

    try {
        const r = await fetch(`${API_BASE_URL}/api/lixeira/${itemId}`,
                              { method: 'DELETE', headers: fetchOptions.headers });
        if (!r.ok) {
            toastErro(await _erroDaResposta(r, 'Não foi possível descartar'));
            return;
        }
        abrirLixeira();
    } catch (e) {
        toastErro('Não foi possível descartar. O servidor respondeu?');
    }
}

function fecharLixeira() {
    document.getElementById('lixeiraModal').style.display = 'none';
}

// Atalhos semânticos
const toastOk   = (m) => mostrarToast(m, 'sucesso');
const toastErro = (m) => mostrarToast(m, 'erro', 6000);
const toastInfo = (m) => mostrarToast(m, 'info');
const toastAviso = (m) => mostrarToast(m, 'aviso', 5500);

// ==========================================
// MODAL DE CONFIRMAÇÃO (substitui o confirm() nativo)
// Uso: if (await confirmarAcao("Excluir?", "Essa ação...")) { ... }
// ==========================================
function confirmarAcao(titulo, texto, textoBotao = 'Confirmar', textoCancelar = 'Cancelar') {
    return new Promise((resolve) => {
        const modal = document.getElementById('confirmModal');
        document.getElementById('confirmTitulo').textContent = titulo;
        document.getElementById('confirmTexto').textContent = texto || '';
        const btnOk = document.getElementById('confirmOk');
        const btnCancel = document.getElementById('confirmCancelar');
        btnOk.textContent = textoBotao;
        // Sempre reatribuído: sem isto, um rótulo customizado por uma chamada
        // vazaria para todas as outras (o botão é compartilhado no DOM).
        btnCancel.textContent = textoCancelar;

        const fechar = (resultado) => {
            modal.style.display = 'none';
            btnOk.onclick = null;
            btnCancel.onclick = null;
            resolve(resultado);
        };
        btnOk.onclick = () => fechar(true);
        btnCancel.onclick = () => fechar(false);
        modal.style.display = 'flex';
    });
}

// Modal de entrada de texto (substitui o prompt() nativo)
function pedirTexto(titulo, label, valorInicial = '') {
    return new Promise((resolve) => {
        const modal = document.getElementById('inputModal');
        document.getElementById('inputTitulo').textContent = titulo;
        document.getElementById('inputLabel').textContent = label;
        const campo = document.getElementById('inputCampo');
        campo.value = valorInicial;
        const btnOk = document.getElementById('inputOk');
        const btnCancel = document.getElementById('inputCancelar');

        const fechar = (resultado) => {
            modal.style.display = 'none';
            btnOk.onclick = null;
            btnCancel.onclick = null;
            campo.onkeydown = null;
            resolve(resultado);
        };
        btnOk.onclick = () => fechar(campo.value);
        btnCancel.onclick = () => fechar(null);
        campo.onkeydown = (e) => {
            if (e.key === 'Enter') fechar(campo.value);
            if (e.key === 'Escape') fechar(null);
        };
        modal.style.display = 'flex';
        setTimeout(() => campo.focus(), 50);
    });
}

const dicasUX = [
    "A IA faz buscas semânticas. Descreva o arquivo com linguagem natural.",
    "O motor lê textos dentro de Imagens e PDFs automaticamente.",
    "Pesquise algo como: 'Planilha financeira do ano passado'.",
    "Personalize o aplicativo usando o menu do seu perfil."
];
let tipInterval;

// ==========================================
// TEXTO ALTERNATIVO DAS IMAGENS
// ==========================================
// A descrição gerada pela IA já está no banco e não era usada onde teria mais
// valor: o `alt`. Nenhuma das nove tags <img> do app tinha um.
//
// Truncar `descricao_ia` cru em 125 caracteres daria
// "- Estilo: foto - O que é: boia inflá" — pior que nada para quem ouve. O
// campo tem formato fixo ("- Estilo: … - O que é: …"), então o que serve como
// alt é o "O que é": uma frase que descreve a cena.
function textoAlternativo(item) {
    const desc = (item && (item.descricao_ia || item.conteudo)) || '';

    const oQueE = desc.match(/^-\s*O que é:\s*(.+)$/im);
    if (oQueE && oQueE[1].trim()) return _limitar(oQueE[1].trim(), 125);

    // Documento não usa o formato de campos — traz o texto extraído direto.
    const primeiraLinha = desc.split('\n').map(l => l.trim())
        .find(l => l && !l.startsWith('-'));
    if (primeiraLinha) return _limitar(primeiraLinha, 125);

    // Sem descrição (imagem ainda não analisada — a indexação é sob demanda):
    // o nome do arquivo sem extensão ainda diz mais que "imagem".
    const nome = (item && item.nome) || '';
    return nome.replace(/\.[^.]+$/, '') || 'Imagem sem descrição';
}

function _limitar(texto, max) {
    if (texto.length <= max) return texto;
    // Corta na palavra, não no meio dela
    const corte = texto.slice(0, max);
    const ultimoEspaco = corte.lastIndexOf(' ');
    return (ultimoEspaco > max * 0.6 ? corte.slice(0, ultimoEspaco) : corte) + '…';
}

// Escapa para uso dentro de atributo HTML montado por template string.
function _attr(texto) {
    return String(texto).replace(/&/g, '&amp;').replace(/"/g, '&quot;')
                        .replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function formatImagePath(path) {
    if (!path) return '';
    if (path.startsWith('http') || path.startsWith('data:')) return path;
    return `${API_BASE_URL}/api/file/${encodeURIComponent(path)}`;
}

window.onload = async () => {
    const savedUser = localStorage.getItem('searchplus_user');
    if (savedUser) {
        document.getElementById('loginUser').value = savedUser;
        document.getElementById('lembrarLogin').checked = true;
    }

    await carregarConfiguracoesUX();

    // Sem await: o preparo da busca não pode atrasar a tela de login.
    acompanharPreparoDaBusca();

    // A seleção de trabalho volta depois de um F5 acidental.
    restaurarSelecao();

    try {
        const res = await fetch(`${API_BASE_URL}/api/check_session`);
        if (res.ok) {
            const userData = await res.json();
            loginBemSucedido(userData.username);
        } else {
            document.getElementById('authOverlay').style.display = 'flex';
        }
    } catch (e) { console.error(e); toastErro("Servidor offline. Verifique se o backend Python está rodando."); }
};

// ==========================================
// PREPARO DA BUSCA (os modelos carregam em segundo plano)
// ==========================================
// O servidor passou a atender em ~2s em vez de ~30s, carregando os modelos
// depois de já estar de pé. O efeito colateral é uma janela em que a tela
// funciona mas a busca ainda não: sem avisar, o usuário digita, recebe um erro
// e conclui que o programa está quebrado.
let _sondaBusca = null;

function marcarBuscaPreparando(preparando) {
    let faixa = document.getElementById('faixaPreparando');

    if (!preparando) {
        if (faixa) faixa.remove();
        return;
    }

    if (!faixa) {
        faixa = document.createElement('div');
        faixa.id = 'faixaPreparando';
        faixa.className = 'faixa-preparando';
        faixa.setAttribute('role', 'status');
        faixa.setAttribute('aria-live', 'polite');
        faixa.innerHTML = '<span class="faixa-preparando-ponto" aria-hidden="true"></span>' +
            '<span>Preparando a busca. Isso leva alguns segundos na primeira vez ' +
            'que o programa abre — o resto do Search+ já funciona.</span>';
        document.body.appendChild(faixa);
    }
}

async function acompanharPreparoDaBusca() {
    // Uma consulta antes de qualquer espera: quando os modelos já estão
    // carregados (o caso comum, de quem não acabou de abrir o programa), nada
    // aparece na tela e a sondagem nem começa.
    try {
        const r = await fetch(`${API_BASE_URL}/api/health`);
        const d = await r.json();
        if (!d.carregando) { marcarBuscaPreparando(false); return; }
    } catch (e) {
        return;   // servidor fora do ar é outro problema, com outro aviso
    }

    marcarBuscaPreparando(true);

    if (_sondaBusca) clearInterval(_sondaBusca);
    _sondaBusca = setInterval(async () => {
        try {
            const r = await fetch(`${API_BASE_URL}/api/health`);
            const d = await r.json();
            if (d.carregando) return;

            clearInterval(_sondaBusca);
            _sondaBusca = null;
            marcarBuscaPreparando(false);

            if (d.busca_pronta) {
                toastOk('Busca pronta.');
            } else {
                const motivo = (d.modelos && d.modelos.texto && d.modelos.texto.estado) || '';
                if (motivo === 'indisponivel') {
                    toastErro('A busca por texto não subiu. Feche o programa e abra de novo; ' +
                              'se continuar, rode o rodar.bat uma vez com a internet conectada.');
                }
            }
        } catch (e) {
            // Servidor caiu no meio da carga: para de sondar em vez de encher
            // o console de erro a cada 1,5s.
            clearInterval(_sondaBusca);
            _sondaBusca = null;
        }
    }, 1500);
}

// ==========================================
// SELETOR E CROPPER DE IMAGEM
// ==========================================
async function selecionarImagemExplorer(inputId) {
    try {
        const res = await fetch(`${API_BASE_URL}/api/choose_image`);
        const data = await res.json();

        if (data.status === "sucesso") {
            // O backend já devolve a imagem em base64 (data URL). Carregar
            // direto evita o /api/file (que bloqueia imagens fora das pastas
            // monitoradas) e não contamina o canvas do cropper.
            targetCropInput = inputId;
            abrirEditorCorte(data.data_url, inputId);
        } else if (data.status === "erro") {
            toastErro(data.mensagem || "Erro ao selecionar imagem.");
        }
    } catch (e) {
        console.error("Erro ao selecionar imagem:", e);
        toastErro("Erro ao abrir a imagem selecionada.");
    }
}

function abrirEditorCorte(imgSrc, inputId) {
    const cropImg = document.getElementById('cropperImage');
    // imgSrc é uma blob: URL local — não precisa de crossOrigin e não
    // contamina o canvas.
    cropImg.removeAttribute('crossorigin');
    cropImg.src = imgSrc;
    document.getElementById('cropperModal').style.display = 'flex';

    cropImg.onload = () => {
        if (cropper) { cropper.destroy(); cropper = null; }

        let ratio = NaN;

        if (inputId.toLowerCase().includes('banner')) ratio = 16 / 9;
        else if (inputId.toLowerCase().includes('avatar')) ratio = 1 / 1;

        cropper = new Cropper(cropImg, {
            aspectRatio: ratio,
            viewMode: 1,
            movable: true,
            zoomable: true,
            rotatable: false,
            scalable: false,
            background: false
        });
    };
}

function fecharCropper() {
    document.getElementById('cropperModal').style.display = 'none';
    if (cropper) { cropper.destroy(); cropper = null; }
    // Libera a blob URL local pra não vazar memória
    const cropImg = document.getElementById('cropperImage');
    if (cropImg && cropImg.src.startsWith('blob:')) {
        URL.revokeObjectURL(cropImg.src);
    }
}

function salvarCropper() {
    if (!cropper) return;

    // COMPRESSÃO E LIMITES DE RESOLUÇÃO
    const isHighRes = targetCropInput.toLowerCase().includes('banner') || targetCropInput === 'bgUrl';

    try {
        const canvas = cropper.getCroppedCanvas({
            maxWidth: isHighRes ? 1920 : 600,
            maxHeight: isHighRes ? 1080 : 600
        });

        if (!canvas) { toastErro("Não foi possível processar a área recortada."); return; }

        const croppedDataUrl = canvas.toDataURL('image/jpeg', isHighRes ? 0.8 : 0.6);
        const targetEl = document.getElementById(targetCropInput);
        if (targetEl) targetEl.value = croppedDataUrl;

        aplicarCorteNoPreview(targetCropInput, croppedDataUrl);
        fecharCropper();
    } catch (e) {
        console.error("Erro no Cropper:", e);
        toastErro("Não foi possível processar essa imagem. Tente outra.");
    }
}

function aplicarCorteNoPreview(inputId, base64Img) {
    const imgUrl = `url('${base64Img}')`;

    // Se a imagem for um Avatar (Perfil)
    if (inputId.toLowerCase().includes('avatar')) {
        const avatares = ['navAvatar', 'dropAvatar', 'viewAvatar', 'previewAvatar', 'obPreviewAvatar'];
        avatares.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.src = base64Img;
        });
        document.getElementById('editAvatar').value = base64Img;

        // Exibe botão de remover no onboarding, se existir
        const btnRem = document.getElementById('btnRemObAvatar');
        if (btnRem) btnRem.style.display = 'block';
    }
    // Se a imagem for um Banner de Fundo
    else if (inputId.toLowerCase().includes('banner')) {
        const bannersFundo = ['viewBanner', 'obPreviewBanner'];
        bannersFundo.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.style.backgroundImage = imgUrl;
        });

        const bannersImagem = ['previewBanner'];
        bannersImagem.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.src = base64Img;
        });
        document.getElementById('editBanner').value = base64Img;

        // Exibe botão de remover no onboarding, se existir
        const btnRem = document.getElementById('btnRemObBanner');
        if (btnRem) btnRem.style.display = 'block';
    }
    // Se a imagem for o Fundo Global do Sistema (Background)
    else if (inputId === 'bgUrl') {
        document.getElementById('previewBg').src = base64Img;
        document.getElementById('btnRemoverFundo').style.display = 'flex';
        tempConfig.bg_url = base64Img;
        aplicarLivePreviewUX();
    }
    // Se a imagem for a textura do Botão
    else if (inputId === 'btnBgUrl') {
        document.getElementById('previewBtnBg').src = base64Img;
        document.getElementById('btnRemoverFundoBotao').style.display = 'flex';
        tempConfig.botao_img_url = base64Img;
        aplicarLivePreviewUX();
    }
}

function removerImagemOnboarding(inputId) {
    document.getElementById(inputId).value = "";
    if (inputId === 'obAvatar') {
        document.getElementById('obPreviewAvatar').src = placeholderPreto;
        document.getElementById('btnRemObAvatar').style.display = 'none';
    } else if (inputId === 'obBanner') {
        document.getElementById('obPreviewBanner').style.backgroundImage = 'none';
        document.getElementById('btnRemObBanner').style.display = 'none';
    }
}

function removerFundoSistema() {
    document.getElementById('bgUrl').value = "";
    tempConfig.bg_url = "";
    document.getElementById('previewBg').src = placeholderPreto;
    document.getElementById('btnRemoverFundo').style.display = 'none';
    aplicarLivePreviewUX();
}

function removerFundoBotao() {
    document.getElementById('btnBgUrl').value = "";
    tempConfig.botao_img_url = "";
    document.getElementById('previewBtnBg').src = placeholderPreto;
    document.getElementById('btnRemoverFundoBotao').style.display = 'none';
    aplicarLivePreviewUX();
}

function toggleOpcoesBotao() {
    const estilo = document.getElementById('botaoEstilo').value;
    tempConfig.botao_estilo = estilo;
    document.getElementById('btnGroupGradient').style.display = estilo === 'gradient' ? 'block' : 'none';
    document.getElementById('btnGroupImage').style.display = estilo === 'image' ? 'block' : 'none';
    aplicarLivePreviewUX();
}

// ==========================================
// LOGIN & CADASTRO
// ==========================================
function toggleAuthMode(mode) {
    if (mode === 'login') {
        document.getElementById('loginForm').style.display = 'block'; document.getElementById('registerForm').style.display = 'none';
        document.getElementById('tabLogin').classList.add('active'); document.getElementById('tabRegister').classList.remove('active');
        document.getElementById('authSubtitle').innerText = "Identifique-se para acessar o motor de IA.";
    } else {
        document.getElementById('loginForm').style.display = 'none'; document.getElementById('registerForm').style.display = 'block';
        document.getElementById('tabLogin').classList.remove('active'); document.getElementById('tabRegister').classList.add('active');
        document.getElementById('authSubtitle').innerText = "Crie sua conta para começar.";
    }
}

async function fazerLogin() {
    const user = document.getElementById('loginUser').value.trim();
    const pass = document.getElementById('loginPass').value.trim();
    const lembrar = document.getElementById('lembrarLogin').checked;

    if (!user || !pass) { toastAviso("Preencha usuário e senha."); return; }

    try {
        const res = await fetch(`${API_BASE_URL}/api/login`, { method: 'POST', headers: fetchOptions.headers, body: JSON.stringify({ username: user, password: pass }) });
        if (res.ok) {
            if (lembrar) localStorage.setItem('searchplus_user', user);
            else localStorage.removeItem('searchplus_user');
            loginBemSucedido(user);
        } else { const data = await res.json(); toastErro(data.mensagem || "Não foi possível entrar."); }
    } catch (e) {
        console.error(e);
        toastErro("Erro de conexão. Verifique se o servidor Python está rodando.");
    }
}

async function fazerCadastro() {
    const user = document.getElementById('regUser').value.trim();
    const handle = document.getElementById('regHandle').value.trim();
    const pass = document.getElementById('regPass').value.trim();
    if (!user || !pass || !handle) { toastAviso("Preencha usuário, handle e senha."); return; }

    try {
        const res = await fetch(`${API_BASE_URL}/api/register`, { method: 'POST', headers: fetchOptions.headers, body: JSON.stringify({ username: user, handle: handle, password: pass }) });
        if (res.ok) { document.getElementById('loginUser').value = user; document.getElementById('loginPass').value = pass; fazerLogin(); }
        else { const data = await res.json(); toastErro(data.mensagem || "Não foi possível criar a conta."); }
    } catch (e) { console.error(e); toastErro("Erro de conexão com o banco de dados."); }
}

async function loginBemSucedido(username) {
    await carregarConfiguracoesUX();
    await carregarHistorico();

    const handle = currentConfig.perfil_handle || username;

    document.getElementById('dropHandle').innerText = '@' + handle;
    document.getElementById('dashHandle').innerText = '@' + handle;

    document.getElementById('authOverlay').style.display = 'none';
    verificarOnboarding();
    mostrarHome();
}

// A home é a galeria por categoria (Pessoas, Animais, Lugares…). Ela precisa
// aparecer JÁ no login: é o que mostra ao usuário o que existe indexado antes
// de ele pensar no que pesquisar. Antes disso ficava escondida atrás de
// `searchHistoryExists`, que só virava true depois da primeira busca — quem
// entrava pela primeira vez via uma tela vazia, e clicar no logo não trazia
// nada de volta.
function mostrarHome() {
    const dash = document.getElementById('dashboardView');
    if (!dash) return;
    dash.style.display = 'block';
    dash.classList.remove('fade-out');
    // Reflow forçado em vez de requestAnimationFrame: o rAF não dispara em aba
    // em segundo plano, e a home ficaria com opacity 0 — visível no DOM, em
    // branco na tela. O reflow libera a transição de forma síncrona.
    void dash.offsetHeight;
    dash.style.opacity = '1';
    carregarFavoritosDash();
    carregarGaleria();
}

async function fazerLogout() {
    await fetch(`${API_BASE_URL}/api/logout`, { method: 'POST' });
    limparBusca();
    document.getElementById('profileDropdown').style.display = 'none';
    document.getElementById('authOverlay').style.display = 'flex';
}

// ==========================================
// ONBOARDING
// ==========================================
async function verificarOnboarding() {
    if (!currentConfig.historico_pastas || currentConfig.pastas.length === 0) {
        document.getElementById('onboardingOverlay').style.display = 'flex';
        document.getElementById('onboardingStep1').style.display = 'block';
        document.getElementById('onboardingStep2').style.display = 'none';
        atualizarListaPastasOnboarding();
    }
}

async function adicionarPastaOnboarding() {
    try {
        const res = await fetch(`${API_BASE_URL}/api/choose_folder`);
        const data = await res.json();
        if (data.status === "sucesso") {
            await fetch(`${API_BASE_URL}/api/folders`, {
                method: 'POST', headers: fetchOptions.headers,
                body: JSON.stringify({
                    pasta: data.pasta,
                    prioridades: _obPrioridades,
                    perfil_analise: _obPerfil,
                    janela_processamento: _obJanela
                })
            });
            currentConfig.historico_pastas = true;
            atualizarListaPastasOnboarding();
            _obLastFolder = data.pasta;
            atualizarEstimativa('ob', data.pasta);
        }
    } catch (e) { }
}

async function atualizarListaPastasOnboarding() {
    const res = await fetch(`${API_BASE_URL}/api/folders`);
    const config = await res.json();
    const list = document.getElementById('onboardingFoldersList');
    const pastas = config.pastas || [];
    if (pastas.length > 0) {
        list.innerHTML = pastas.map(f => {
            const p = typeof f === 'string' ? f : f.path;
            const pEsc = p.replace(/'/g, "\\'").replace(/"/g, '&quot;').replace(/\\/g, '\\\\');
            return `<div style="color:var(--telemetry); padding: 5px 0; display:flex; justify-content:center; align-items:center; gap: 10px;">
                <span>${p}</span>
                <span style="cursor:pointer; color:var(--text-secondary); opacity:0.7; font-size:0.9rem;" onclick="removerPastaOnboarding('${pEsc}')" title="Remover pasta"></span>
            </div>`;
        }).join('');
    } else {
        list.innerHTML = `<p style="color: var(--text-secondary); font-size: 0.9rem; text-align:center;">Nenhuma pasta selecionada ainda.</p>`;
    }
}

async function removerPastaOnboarding(path) {
    try {
        await fetch(`${API_BASE_URL}/api/folders`, {
            method: 'DELETE',
            headers: fetchOptions.headers,
            body: JSON.stringify({ pasta: path })
        });
        if (_obLastFolder === path) {
            _obLastFolder = '';
            document.getElementById('obEstimativa').style.display = 'none';
        }
        atualizarListaPastasOnboarding();
    } catch (e) { console.error(e); toastErro("Não foi possível remover a pasta."); }
}

function irParaOnboardingStep2() {
    document.getElementById('onboardingStep1').style.display = 'none';
    document.getElementById('onboardingStep2').style.display = 'block';

    document.getElementById('obNome').value = currentConfig.perfil_nome || "";
    document.getElementById('obHandle').value = currentConfig.perfil_handle || "";
    document.getElementById('obCargo').value = currentConfig.perfil_cargo || "";
    document.getElementById('obBio').value = currentConfig.perfil_bio || "";
    updateProfilePreview();
}

function voltarParaOnboardingStep1() {
    document.getElementById('onboardingStep2').style.display = 'none';
    document.getElementById('onboardingStep1').style.display = 'block';
}

function updateProfilePreview() {
    const nome = document.getElementById('obNome').value.trim() || "Seu Nome";
    const handle = document.getElementById('obHandle').value.trim() || "handle";
    const cargo = document.getElementById('obCargo').value.trim() || "Cargo";
    const bio = document.getElementById('obBio').value.trim() || "Sua biografia aparecerá aqui.";

    document.getElementById('obPreviewName').innerText = nome;
    document.getElementById('obPreviewHandle').innerText = "@" + handle;
    document.getElementById('obPreviewCargo').innerText = cargo;
    document.getElementById('obPreviewBio').innerText = bio;

    if (!document.getElementById('obAvatar').value) {
        const url = formatImagePath(currentConfig.perfil_avatar);
        document.getElementById('obPreviewAvatar').src = url || placeholderPreto;
    }
    if (!document.getElementById('obBanner').value) {
        const bannerUrl = formatImagePath(currentConfig.perfil_banner);
        if (bannerUrl) document.getElementById('obPreviewBanner').style.backgroundImage = `url('${bannerUrl}')`;
        else document.getElementById('obPreviewBanner').style.backgroundImage = 'none';
    }
}

async function finalizarOnboarding() {
    const btn = document.getElementById('btnConcluirOnboarding');
    btn.innerText = "Salvando..."; btn.disabled = true;

    const foldersRes = await fetch(`${API_BASE_URL}/api/folders`);
    const foldersData = await foldersRes.json();
    if (!foldersData.pastas || foldersData.pastas.length === 0) {
        toastAviso("Adicione pelo menos uma pasta antes de concluir.");
        voltarParaOnboardingStep1();
        btn.innerText = "Concluir "; btn.disabled = false;
        return;
    }

    currentConfig.perfil_nome = document.getElementById('obNome').value.trim() || currentConfig.perfil_nome;
    currentConfig.perfil_handle = document.getElementById('obHandle').value.trim() || currentConfig.perfil_handle;
    currentConfig.perfil_cargo = document.getElementById('obCargo').value.trim() || currentConfig.perfil_cargo;
    currentConfig.perfil_bio = document.getElementById('obBio').value.trim();

    if (document.getElementById('obAvatar').value) currentConfig.perfil_avatar = document.getElementById('obAvatar').value;
    if (document.getElementById('obBanner').value) currentConfig.perfil_banner = document.getElementById('obBanner').value;

    await fetch(`${API_BASE_URL}/api/config`, { method: 'POST', headers: fetchOptions.headers, body: JSON.stringify(currentConfig) });

    // Só AGORA, na confirmação, dispara a análise das pastas (com o perfil
    // deep/relâmpago que o usuário escolheu). Antes disso, nada é analisado.
    await fetch(`${API_BASE_URL}/api/analyze_folders`, { method: 'POST', headers: fetchOptions.headers });

    await carregarConfiguracoesUX();
    document.getElementById('onboardingOverlay').style.display = 'none';
    toastOk("Tudo pronto! A IA começou a analisar suas pastas.");

    btn.innerText = "Concluir "; btn.disabled = false;
}

// ==========================================
// CONFIGURAÇÕES VISUAIS (LIVE PREVIEW)
// ==========================================
async function carregarConfiguracoesUX() {
    try {
        const res = await fetch(`${API_BASE_URL}/api/config`);
        currentConfig = await res.json();

        // Quais pastas a home mostra. Vem da conta, não do navegador: quem
        // separou as pastas de trabalho das pessoais espera reencontrar isso.
        // Ausente é `null` ("mostra todas"), NÃO lista vazia — que agora
        // significa "não mostra nada". Trocar os dois faria a home nascer
        // vazia para quem nunca mexeu no seletor.
        _pastasVisiveis = Array.isArray(currentConfig.pastas_visiveis)
            ? currentConfig.pastas_visiveis : null;

        // #AB5AF7, e não o #A855F7 de antes: como TEXTO sobre a superfície dos
        // cards, o tom anterior media 4,38:1 e não passava no mínimo de
        // 4,5:1. A diferença é imperceptível a olho; o número, não.
        // Este é o padrão que vale — ele sobrescreve o do CSS ao aplicar o tema.
        currentConfig.cor_primaria = currentConfig.cor_primaria || COR_PRIMARIA_PADRAO;
        currentConfig.cor_secundaria = currentConfig.cor_secundaria || COR_SECUNDARIA_PADRAO;
        currentConfig.cor_texto_botao = currentConfig.cor_texto_botao || "#FFFFFF";

        aplicarTemaNoDOM(currentConfig);

        const safeSetSrc = (id, val) => { const el = document.getElementById(id); if (el) el.src = val; };
        const safeSetTx = (id, val) => { const el = document.getElementById(id); if (el) el.innerText = val; };
        const safeSetVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
        const safeSetBg = (id, val) => { const el = document.getElementById(id); if (el) el.style.backgroundImage = val; };

        safeSetSrc('navAvatar', formatImagePath(currentConfig.perfil_avatar) || placeholderPreto);
        safeSetSrc('dropAvatar', formatImagePath(currentConfig.perfil_avatar) || placeholderPreto);
        safeSetTx('dropName', currentConfig.perfil_nome);
        safeSetTx('dropHandle', '@' + currentConfig.perfil_handle);

        safeSetSrc('viewAvatar', formatImagePath(currentConfig.perfil_avatar) || placeholderPreto);
        const bannerUrl = formatImagePath(currentConfig.perfil_banner);
        safeSetBg('viewBanner', bannerUrl ? `url('${bannerUrl}')` : 'none');

        safeSetTx('viewProfileName', currentConfig.perfil_nome);
        safeSetTx('viewProfileHandle', '@' + currentConfig.perfil_handle);
        safeSetTx('viewProfileCargo', currentConfig.perfil_cargo || "Cargo não definido");
        safeSetTx('viewProfileLocal', "" + (currentConfig.perfil_local || "Localização não definida"));
        safeSetTx('viewProfileBio', currentConfig.perfil_bio);

        safeSetVal('editNome', currentConfig.perfil_nome);
        safeSetVal('editHandle', currentConfig.perfil_handle);
        safeSetVal('editCargo', currentConfig.perfil_cargo || "");
        safeSetVal('editLocal', currentConfig.perfil_local || "");
        safeSetVal('editBio', currentConfig.perfil_bio);

        safeSetSrc('previewAvatar', formatImagePath(currentConfig.perfil_avatar) || placeholderPreto);
        safeSetSrc('previewBanner', formatImagePath(currentConfig.perfil_banner) || placeholderPreto);
        safeSetVal('editAvatar', "");
        safeSetVal('editBanner', "");

        if (currentConfig.idioma) safeSetVal('idiomaSelect', currentConfig.idioma);

        // Load General Settings
        const safeSetCheck = (id, val) => { const el = document.getElementById(id); if (el) el.checked = !!val; };
        safeSetCheck('cgNotificacoes', currentConfig.notificacoes !== false);
        safeSetVal('cgAtalho', currentConfig.atalho_busca || "Ctrl+Shift+F");
        safeSetCheck('cgModoPrivado', currentConfig.modo_privado);
        safeSetVal('cgPastasIgnoradas', currentConfig.pastas_ignoradas || "");
        safeSetVal('cgModoDesempenho', currentConfig.modo_desempenho || "economico");

    } catch (e) { console.error("Erro ao carregar UX:", e); }
}

function aplicarLivePreviewUX() { aplicarTemaNoDOM(tempConfig); }
function setLiveTema(tema) { tempConfig.tema = tema; aplicarLivePreviewUX(); }

document.getElementById('corPrimaria').addEventListener('input', function () { tempConfig.cor_primaria = this.value; aplicarLivePreviewUX(); });
document.getElementById('corSecundaria').addEventListener('input', function () { tempConfig.cor_secundaria = this.value; aplicarLivePreviewUX(); });
document.getElementById('corTextoBotao').addEventListener('input', function () { tempConfig.cor_texto_botao = this.value; aplicarLivePreviewUX(); });
document.getElementById('idiomaSelect').addEventListener('change', function () { tempConfig.idioma = this.value; });
document.getElementById('bgBlur').addEventListener('input', function () {
    document.getElementById('blurValue').innerText = this.value;
    tempConfig.bg_blur = parseInt(this.value);
    aplicarLivePreviewUX();
});

// Listeners dos novos campos de Design dos Botões
function addSafeListener(id, event, fn) {
    const el = document.getElementById(id);
    if (el) el.addEventListener(event, fn);
}
addSafeListener('botaoFonte',  'change', function() { tempConfig.botao_fonte  = this.value; aplicarLivePreviewUX(); });
addSafeListener('botaoEstilo', 'change', function() { tempConfig.botao_estilo = this.value; toggleOpcoesBotao(); });
addSafeListener('btnGrad1',    'input',  function() { tempConfig.botao_grad1  = this.value; aplicarLivePreviewUX(); });
addSafeListener('btnGrad2',    'input',  function() { tempConfig.botao_grad2  = this.value; aplicarLivePreviewUX(); });

function aplicarTemaNoDOM(config) {
    const root = document.documentElement;
    if (config.tema === 'light') {
        root.style.setProperty('--bg-deep', '#F8FAFC'); root.style.setProperty('--surface', '#FFFFFF');
        root.style.setProperty('--text-primary', '#0B0F19'); root.style.setProperty('--text-secondary', '#475569');
        root.style.setProperty('--border-light', 'rgba(0, 0, 0, 0.08)');
    } else {
        root.style.setProperty('--bg-deep', '#0B0F19'); root.style.setProperty('--surface', '#151A2A');
        root.style.setProperty('--text-primary', '#F8FAFC'); root.style.setProperty('--text-secondary', '#94A3B8');
        root.style.setProperty('--border-light', 'rgba(255, 255, 255, 0.08)');
    }
    root.style.setProperty('--accent-primary', config.cor_primaria);
    root.style.setProperty('--accent-secondary', config.cor_secundaria);
    root.style.setProperty('--btn-text-color', config.cor_texto_botao || '#FFFFFF');

    // ======== INJEÇÃO DO DESIGN DINÂMICO DOS BOTÕES ========
    let btnStyleTag = document.getElementById('dynamicBtnStyles');
    if(!btnStyleTag) {
        btnStyleTag = document.createElement('style');
        btnStyleTag.id = 'dynamicBtnStyles';
        document.head.appendChild(btnStyleTag);
    }
    
    let btnCss = '';
    const bFont = config.botao_fonte || "system-ui, -apple-system, sans-serif";
    const bStyle = config.botao_estilo || "default";
    
    if (bStyle === "default") {
        btnCss = `
            .action-btn, .gradient-btn, .filter-tag { font-family: ${bFont} !important; }
            .gradient-btn { background: linear-gradient(135deg, var(--accent-primary), var(--accent-secondary)) !important; color: var(--btn-text-color) !important; border: none !important; }
        `;
    } else if (bStyle === "glass") {
        btnCss = `
            .action-btn, .gradient-btn, .filter-tag { font-family: ${bFont} !important; }
            .gradient-btn, .action-btn {
                background: rgba(255, 255, 255, 0.08) !important;
                backdrop-filter: blur(20px) saturate(180%) !important;
                -webkit-backdrop-filter: blur(20px) saturate(180%) !important;
                border: 1px solid rgba(255, 255, 255, 0.18) !important;
                box-shadow: 0 4px 24px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.15) !important;
                color: var(--text-primary) !important;
            }
            .gradient-btn:hover, .action-btn:hover {
                background: rgba(255, 255, 255, 0.15) !important;
                box-shadow: 0 8px 32px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.2) !important;
                transform: translateY(-2px) !important;
            }
        `;
    } else if (bStyle === "gradient") {
        const c1 = config.botao_grad1 || "#FF512F";
        const c2 = config.botao_grad2 || "#DD2476";
        btnCss = `
            .action-btn, .gradient-btn, .filter-tag { font-family: ${bFont} !important; }
            .gradient-btn { background: linear-gradient(135deg, ${c1}, ${c2}) !important; color: var(--btn-text-color) !important; border: none !important; }
        `;
    } else if (bStyle === "image") {
        const imgUrl = config.botao_img_url || "";
        if (imgUrl.trim() !== "") {
            btnCss = `
                .action-btn, .gradient-btn, .filter-tag { font-family: ${bFont} !important; }
                .gradient-btn { 
                    background-image: url('${formatImagePath(imgUrl)}') !important; 
                    background-size: cover !important; background-position: center !important; 
                    background-color: transparent !important;
                    color: var(--btn-text-color) !important; border: none !important; box-shadow: inset 0 0 0 2000px rgba(0,0,0,0.4) !important; 
                }
                .gradient-btn:hover { box-shadow: inset 0 0 0 2000px rgba(0,0,0,0.2) !important; }
            `;
        } else {
            btnCss = `.action-btn, .gradient-btn, .filter-tag { font-family: ${bFont}; }`;
        }
    }
    btnStyleTag.innerHTML = btnCss;
    // =======================================================

    // Apply individual button overrides (per-button custom styles)
    aplicarEstilosBotaoIndividualNoDOM(config);

    const appBg = document.getElementById('appBackground');
    const realImg = document.getElementById('realBgImage');

    // Gradientes base continuam existindo
    appBg.style.backgroundImage = `radial-gradient(circle at 0% 100%, ${config.cor_primaria}26 0%, transparent 50%), radial-gradient(circle at 100% 0%, ${config.cor_secundaria}26 0%, transparent 40%)`;

    if (config.bg_url && config.bg_url.trim() !== "") {
        if (realImg) {
            realImg.src = formatImagePath(config.bg_url);
            realImg.style.display = 'block';
            realImg.style.filter = `blur(${config.bg_blur || 0}px)`;
            realImg.style.transition = 'filter 0.3s ease';
        }
        appBg.style.filter = 'none'; // Previne duplo blur
    }
    else {
        if (realImg) realImg.style.display = 'none';
        appBg.style.filter = `blur(${config.bg_blur || 0}px)`;
    }
}

async function restaurarPadroesUX() {
    tempConfig.tema = "dark";
    tempConfig.cor_primaria = COR_PRIMARIA_PADRAO;
    tempConfig.cor_secundaria = COR_SECUNDARIA_PADRAO;
    tempConfig.cor_texto_botao = "#FFFFFF";
    tempConfig.bg_url = "";
    tempConfig.bg_blur = 15;
    tempConfig.botao_estilo = "default";
    tempConfig.botao_fonte = "system-ui, -apple-system, sans-serif";
    tempConfig.botao_grad1 = "#FF512F";
    tempConfig.botao_grad2 = "#DD2476";
    tempConfig.botao_img_url = "";
    // Reset per-button individual styles
    tempConfig.btn_search_estilo = "inherit";
    tempConfig.btn_search_cor = "#A855F7";
    tempConfig.btn_search_texto = "#FFFFFF";
    tempConfig.btn_topbar_estilo = "inherit";
    tempConfig.btn_topbar_cor = "#151A2A";
    tempConfig.btn_topbar_texto = "#F8FAFC";
    tempConfig.btn_actions_estilo = "inherit";
    tempConfig.btn_actions_cor = "#151A2A";
    tempConfig.btn_actions_texto = "#F8FAFC";
    tempConfig.btn_filters_estilo = "inherit";
    tempConfig.btn_filters_cor = "#A855F7";
    tempConfig.btn_filters_texto = "#FFFFFF";
    
    const safeSetVal = (id, val) => { const el = document.getElementById(id); if(el) el.value = val; };
    
    safeSetVal('corPrimaria', tempConfig.cor_primaria);
    safeSetVal('corSecundaria', tempConfig.cor_secundaria);
    safeSetVal('corTextoBotao', tempConfig.cor_texto_botao);
    safeSetVal('bgUrl', tempConfig.bg_url);
    safeSetVal('botaoFonte', tempConfig.botao_fonte);
    safeSetVal('botaoEstilo', tempConfig.botao_estilo);
    safeSetVal('btnGrad1', tempConfig.botao_grad1);
    safeSetVal('btnGrad2', tempConfig.botao_grad2);
    safeSetVal('btnSearchEstilo', 'inherit');
    safeSetVal('btnTopbarEstilo', 'inherit');
    safeSetVal('btnActionsEstilo', 'inherit');
    safeSetVal('btnFiltersEstilo', 'inherit');
    
    const preBg = document.getElementById('previewBg'); if(preBg) preBg.src = placeholderPreto; 
    const btnRemoverFundo = document.getElementById('btnRemoverFundo');
    if (btnRemoverFundo) btnRemoverFundo.style.display = 'none';

    const preBtnBg = document.getElementById('previewBtnBg'); if(preBtnBg) preBtnBg.src = placeholderPreto;
    const remBtnFundo = document.getElementById('btnRemoverFundoBotao');
    if(remBtnFundo) remBtnFundo.style.display = 'none';
    
    document.getElementById('bgBlur').value = tempConfig.bg_blur;
    document.getElementById('blurValue').innerText = tempConfig.bg_blur;

    aplicarLivePreviewUX();
}

async function salvarConfiguracoesUX() {
    // Capture per-button individual configs before saving
    const sv = (id) => { const el = document.getElementById(id); return el ? el.value : null; };
    if (sv('btnSearchEstilo') !== null)  tempConfig.btn_search_estilo  = sv('btnSearchEstilo');
    if (sv('btnSearchCor') !== null)     tempConfig.btn_search_cor     = sv('btnSearchCor');
    if (sv('btnSearchTexto') !== null)   tempConfig.btn_search_texto   = sv('btnSearchTexto');
    if (sv('btnTopbarEstilo') !== null)  tempConfig.btn_topbar_estilo  = sv('btnTopbarEstilo');
    if (sv('btnTopbarCor') !== null)     tempConfig.btn_topbar_cor     = sv('btnTopbarCor');
    if (sv('btnTopbarTexto') !== null)   tempConfig.btn_topbar_texto   = sv('btnTopbarTexto');
    if (sv('btnActionsEstilo') !== null) tempConfig.btn_actions_estilo = sv('btnActionsEstilo');
    if (sv('btnActionsCor') !== null)    tempConfig.btn_actions_cor    = sv('btnActionsCor');
    if (sv('btnActionsTexto') !== null)  tempConfig.btn_actions_texto  = sv('btnActionsTexto');
    if (sv('btnFiltersEstilo') !== null) tempConfig.btn_filters_estilo = sv('btnFiltersEstilo');
    if (sv('btnFiltersCor') !== null)    tempConfig.btn_filters_cor    = sv('btnFiltersCor');
    if (sv('btnFiltersTexto') !== null)  tempConfig.btn_filters_texto  = sv('btnFiltersTexto');

    currentConfig = { ...tempConfig };
    await fetch(`${API_BASE_URL}/api/config`, { method: 'POST', headers: fetchOptions.headers, body: JSON.stringify(currentConfig) });
    fecharSidebarConfig();
}

// ==========================================
// PRESETS DE TEMA (exportar / importar)
// ==========================================
// Campos puramente VISUAIS — não inclui dados de conta (nome, avatar,
// banner, handle, histórico). Assim o tema é compartilhável sem vazar perfil.
const _CAMPOS_TEMA = [
    'tema', 'cor_primaria', 'cor_secundaria', 'cor_texto_botao',
    'bg_url', 'bg_blur', 'botao_fonte', 'botao_estilo',
    'btn_search_estilo', 'btn_search_cor', 'btn_search_texto',
    'btn_topbar_estilo', 'btn_topbar_cor', 'btn_topbar_texto',
    'btn_actions_estilo', 'btn_actions_cor', 'btn_actions_texto',
    'btn_filters_estilo', 'btn_filters_cor', 'btn_filters_texto',
];

function exportarTema() {
    const tema = { _searchplus_tema: 1, exportado_em: new Date().toISOString() };
    _CAMPOS_TEMA.forEach(k => {
        if (currentConfig[k] !== undefined) tema[k] = currentConfig[k];
    });

    const blob = new Blob([JSON.stringify(tema, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const nome = (currentConfig.perfil_handle || 'searchplus').replace(/[^a-z0-9_-]/gi, '');
    a.href = url;
    a.download = `tema-${nome}.json`;
    a.click();
    URL.revokeObjectURL(url);
    toastOk('Tema exportado! Compartilhe o arquivo .json.');
}

async function importarTema(event) {
    const file = event.target.files && event.target.files[0];
    if (!file) return;
    try {
        const texto = await file.text();
        const tema = JSON.parse(texto);
        if (!tema._searchplus_tema) {
            toastErro('Esse arquivo não é um tema válido do Search+.');
            return;
        }
        // Aplica só os campos de tema reconhecidos sobre a config atual
        _CAMPOS_TEMA.forEach(k => {
            if (tema[k] !== undefined) {
                currentConfig[k] = tema[k];
                tempConfig[k] = tema[k];
            }
        });

        // Aplica visualmente e persiste
        aplicarTemaNoDOM(currentConfig);
        if (typeof aplicarEstilosBotaoIndividualNoDOM === 'function') {
            aplicarEstilosBotaoIndividualNoDOM(currentConfig);
        }
        await fetch(`${API_BASE_URL}/api/config`, {
            method: 'POST', headers: fetchOptions.headers,
            body: JSON.stringify(currentConfig)
        });
        toastOk('Tema importado e aplicado!');
    } catch (e) {
        console.error(e);
        toastErro('Não foi possível ler o arquivo de tema.');
    } finally {
        event.target.value = '';  // permite reimportar o mesmo arquivo
    }
}

// ==========================================
// PER-BUTTON CUSTOMIZATION FUNCTIONS
// ==========================================
function selecionarTabBotao(tab, el) {
    ['global', 'search', 'topbar', 'actions', 'filters'].forEach(t => {
        const div = document.getElementById('btnTab' + t.charAt(0).toUpperCase() + t.slice(1));
        if (div) div.style.display = 'none';
    });
    const div = document.getElementById('btnTab' + tab.charAt(0).toUpperCase() + tab.slice(1));
    if (div) div.style.display = 'block';
    document.querySelectorAll('.btn-tab-selector').forEach(b => b.classList.remove('active'));
    if (el) el.classList.add('active');
}

function aplicarEstilosBotaoIndividual() {
    const sv = (id) => { const el = document.getElementById(id); return el ? el.value : null; };
    tempConfig.btn_search_estilo  = sv('btnSearchEstilo')  || 'inherit';
    tempConfig.btn_search_cor     = sv('btnSearchCor')     || '#A855F7';
    tempConfig.btn_search_texto   = sv('btnSearchTexto')   || '#FFFFFF';
    tempConfig.btn_topbar_estilo  = sv('btnTopbarEstilo')  || 'inherit';
    tempConfig.btn_topbar_cor     = sv('btnTopbarCor')     || '#151A2A';
    tempConfig.btn_topbar_texto   = sv('btnTopbarTexto')   || '#F8FAFC';
    tempConfig.btn_actions_estilo = sv('btnActionsEstilo') || 'inherit';
    tempConfig.btn_actions_cor    = sv('btnActionsCor')    || '#151A2A';
    tempConfig.btn_actions_texto  = sv('btnActionsTexto')  || '#F8FAFC';
    tempConfig.btn_filters_estilo = sv('btnFiltersEstilo') || 'inherit';
    tempConfig.btn_filters_cor    = sv('btnFiltersCor')    || '#A855F7';
    tempConfig.btn_filters_texto  = sv('btnFiltersTexto')  || '#FFFFFF';
    aplicarLivePreviewUX();
}

function aplicarEstilosBotaoIndividualNoDOM(config) {
    let perBtnTag = document.getElementById('perBtnStyles');
    if (!perBtnTag) {
        perBtnTag = document.createElement('style');
        perBtnTag.id = 'perBtnStyles';
        document.head.appendChild(perBtnTag);
    }

    function buildGlass() {
        return `
            background: rgba(255,255,255,0.08) !important;
            backdrop-filter: blur(20px) saturate(180%) !important;
            -webkit-backdrop-filter: blur(20px) saturate(180%) !important;
            border: 1px solid rgba(255,255,255,0.18) !important;
            box-shadow: 0 4px 24px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.15) !important;
            color: var(--text-primary) !important;
        `;
    }
    function buildSolid(cor, txt) {
        return `background: ${cor} !important; color: ${txt} !important; border: none !important;`;
    }
    function buildOutline(cor, txt) {
        return `background: transparent !important; color: ${cor} !important; border: 2px solid ${cor} !important;`;
    }

    let css = '';

    // Search button
    const se = config.btn_search_estilo || 'inherit';
    if (se !== 'inherit') {
        const sc = config.btn_search_cor || '#A855F7', st = config.btn_search_texto || '#fff';
        const sRule = se === 'glass' ? buildGlass() : se === 'solid' ? buildSolid(sc, st) : buildOutline(sc, st);
        css += `.search-btn { ${sRule} background-clip: padding-box !important; }\n`;
    }

    // Top bar buttons
    const te = config.btn_topbar_estilo || 'inherit';
    if (te !== 'inherit') {
        const tc = config.btn_topbar_cor || '#151A2A', tt = config.btn_topbar_texto || '#F8FAFC';
        const tRule = te === 'glass' ? buildGlass() : te === 'solid' ? buildSolid(tc, tt) : buildOutline(tc, tt);
        css += `.top-bar .action-btn, .top-bar .gradient-btn { ${tRule} background-clip: padding-box !important; }\n`;
    }

    // Action buttons (modals, sidepanel, etc.)
    const ae = config.btn_actions_estilo || 'inherit';
    if (ae !== 'inherit') {
        const ac = config.btn_actions_cor || '#151A2A', at = config.btn_actions_texto || '#F8FAFC';
        const aRule = ae === 'glass' ? buildGlass() : ae === 'solid' ? buildSolid(ac, at) : buildOutline(ac, at);
        css += `.modal .action-btn, .modal .gradient-btn, .sidebar-body .action-btn, .sidebar-body .gradient-btn { ${aRule} background-clip: padding-box !important; }\n`;
    }

    // Filter tags
    const fe = config.btn_filters_estilo || 'inherit';
    if (fe !== 'inherit') {
        const fc = config.btn_filters_cor || '#A855F7', ft = config.btn_filters_texto || '#fff';
        if (fe === 'glass') {
            css += `.filter-tag { ${buildGlass()} }\n.filter-tag.active { background: rgba(255,255,255,0.18) !important; color: #fff !important; }\n`;
        } else if (fe === 'pill') {
            css += `.filter-tag { background: transparent !important; color: var(--text-secondary) !important; border: 1px solid var(--border-light) !important; }\n.filter-tag.active { background: ${fc} !important; color: ${ft} !important; border-color: ${fc} !important; background-clip: padding-box !important; }\n`;
        } else if (fe === 'outline') {
            css += `.filter-tag { background: transparent !important; border: 1px solid ${fc} !important; color: ${fc} !important; }\n.filter-tag.active { background: ${fc} !important; color: ${ft} !important; background-clip: padding-box !important; }\n`;
        }
    }

    perBtnTag.innerHTML = css;
}

// ==========================================
// MENUS E MODAIS DE PERFIL
// ==========================================
function toggleProfileMenu(e) {
    e.stopPropagation();
    const menu = document.getElementById('profileDropdown');
    const avatar = document.querySelector('.mini-profile');
    if (menu.style.display === 'block') {
        menu.style.display = 'none'; avatar.classList.remove('active');
    } else {
        menu.style.display = 'block'; avatar.classList.add('active');
    }
}
window.addEventListener('click', (e) => {
    const menu = document.getElementById('profileDropdown');
    if (menu.style.display === 'block' && !menu.contains(e.target) && !e.target.closest('.mini-profile')) {
        menu.style.display = 'none'; document.querySelector('.mini-profile').classList.remove('active');
    }
});

function abrirSidebarConfig() {
    tempConfig = { ...currentConfig };
    const safeSetVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };

    safeSetVal('corPrimaria', tempConfig.cor_primaria);
    safeSetVal('corSecundaria', tempConfig.cor_secundaria);
    safeSetVal('corTextoBotao', tempConfig.cor_texto_botao || '#FFFFFF');
    safeSetVal('bgUrl', tempConfig.bg_url);
    safeSetVal('botaoEstilo', tempConfig.botao_estilo || 'default');
    safeSetVal('botaoFonte', tempConfig.botao_fonte || "system-ui, -apple-system, sans-serif");
    safeSetVal('btnGrad1', tempConfig.botao_grad1 || "#FF512F");
    safeSetVal('btnGrad2', tempConfig.botao_grad2 || "#DD2476");
    
    toggleOpcoesBotao(); // Updates visibility
    
    const preBg = document.getElementById('previewBg'); 
    if(preBg) preBg.src = formatImagePath(tempConfig.bg_url) || placeholderPreto;
    
    const preBtnBg = document.getElementById('previewBtnBg');
    if(preBtnBg) preBtnBg.src = formatImagePath(tempConfig.botao_img_url) || placeholderPreto;
    
    const btnRemoverFundo = document.getElementById('btnRemoverFundo');
    if (btnRemoverFundo) {
        if (tempConfig.bg_url && tempConfig.bg_url.trim() !== '') btnRemoverFundo.style.display = 'flex';
        else btnRemoverFundo.style.display = 'none';
    }

    const remFundoBotao = document.getElementById('btnRemoverFundoBotao');
    if (remFundoBotao) {
        if (tempConfig.botao_img_url && tempConfig.botao_img_url.trim() !== '') remFundoBotao.style.display = 'flex';
        else remFundoBotao.style.display = 'none';
    }

    document.getElementById('bgBlur').value = tempConfig.bg_blur;
    document.getElementById('blurValue').innerText = tempConfig.bg_blur;
    if (tempConfig.idioma) document.getElementById('idiomaSelect').value = tempConfig.idioma;

    document.getElementById('sidebarConfig').classList.add('open');
    document.getElementById('sidebarOverlay').style.display = 'block';
    document.getElementById('profileDropdown').style.display = 'none';
}

function fecharSidebarConfig() {
    document.getElementById('sidebarConfig').classList.remove('open');
    document.getElementById('sidebarOverlay').style.display = 'none';
    aplicarTemaNoDOM(currentConfig);
}

async function abrirViewPerfil() {
    document.getElementById('viewPerfilModal').style.display = 'flex';
    document.getElementById('profileDropdown').style.display = 'none';

    // Valores provisórios enquanto carrega
    document.getElementById('statPastas').innerText = currentConfig.pastas ? currentConfig.pastas.length : 0;
    document.getElementById('statArquivos').innerText = '...';

    await carregarEstatisticas();
}

// Rótulos e ícones por categoria. `icone` guarda o id de um símbolo do
// sprite definido no index.html, não um caractere.
const _CATEGORIA_LABEL = {
    pessoas:  { icone: 'pessoas',  nome: 'Pessoas' },
    animais:  { icone: 'animais',  nome: 'Animais' },
    comida:   { icone: 'comida',   nome: 'Comida' },
    natureza: { icone: 'natureza', nome: 'Natureza' },
    urbano:   { icone: 'urbano',   nome: 'Urbano' },
    desenhos: { icone: 'paleta',   nome: 'Desenhos e Arte' },
};

async function carregarEstatisticas() {
    try {
        const res = await fetch(`${API_BASE_URL}/api/stats`);
        if (!res.ok) return;
        const s = await res.json();

        document.getElementById('statPastas').innerText = s.total_pastas ?? 0;
        document.getElementById('statArquivos').innerText = s.total_arquivos ?? 0;

        const box = document.getElementById('statsAcervo');
        const lista = document.getElementById('statsCategorias');
        const cats = s.por_categoria || [];

        if (cats.length === 0 || s.total_arquivos === 0) {
            box.style.display = 'none';
            return;
        }

        const maxVal = Math.max(...cats.map(c => c.total));
        lista.innerHTML = '';
        cats.forEach(c => {
            const meta = _CATEGORIA_LABEL[c.categoria] || { icone: 'caixa', nome: c.categoria };
            const pct = maxVal > 0 ? Math.round((c.total / maxVal) * 100) : 0;
            const row = document.createElement('div');
            row.style.cssText = 'display:flex; align-items:center; gap:10px; font-size:0.85rem;';
            // Estrutura: ícone+nome | barra | contagem (tudo via DOM, sem innerHTML de dado externo)
            const label = document.createElement('span');
            label.style.cssText = 'width:90px; color:var(--text-primary);';
            rotularCom(label, meta.icone, meta.nome);
            const barWrap = document.createElement('div');
            barWrap.style.cssText = 'flex:1; height:8px; background:rgba(255,255,255,0.08); border-radius:4px; overflow:hidden;';
            const bar = document.createElement('div');
            bar.style.cssText = `height:100%; width:${pct}%; background:var(--accent-primary); border-radius:4px;`;
            barWrap.appendChild(bar);
            const count = document.createElement('b');
            count.style.cssText = 'width:32px; text-align:right; color:var(--text-secondary);';
            count.textContent = c.total;
            row.append(label, barWrap, count);
            lista.appendChild(row);
        });
        box.style.display = 'block';
    } catch (e) {
        console.error(e);
    }
}
function fecharViewPerfil() { document.getElementById('viewPerfilModal').style.display = 'none'; }
function abrirEditPerfil() { fecharViewPerfil(); document.getElementById('editPerfilModal').style.display = 'flex'; }
function fecharEditPerfil() { document.getElementById('editPerfilModal').style.display = 'none'; }

// Configurações Gerais Modal
function abrirModalConfigGerais() {
    document.getElementById('profileDropdown').style.display = 'none';
    carregarConfiguracoesUX(); // Refresh the values
    document.getElementById('modalConfigGerais').style.display = 'flex';
}

function fecharModalConfigGerais() {
    document.getElementById('modalConfigGerais').style.display = 'none';
}

function selecionarTabCg(tab, el) {
    ['cg-geral', 'cg-privacidade', 'cg-desempenho'].forEach(t => {
        const tId = t.replace('cg-', 'cgTab').replace(/^(cgTab)(.)(.*)/, (m, p1, p2, p3) => p1 + p2.toUpperCase() + p3);
        const div = document.getElementById(tId);
        if (div) div.style.display = 'none';
    });
    const selectedId = tab.replace('cg-', 'cgTab').replace(/^(cgTab)(.)(.*)/, (m, p1, p2, p3) => p1 + p2.toUpperCase() + p3);
    const div = document.getElementById(selectedId);
    if (div) div.style.display = 'block';
    
    document.querySelectorAll('#modalConfigGerais .btn-tab-selector').forEach(b => b.classList.remove('active'));
    if (el) el.classList.add('active');
}

function capturarAtalho(e) {
    e.preventDefault();
    let keys = [];
    if (e.ctrlKey) keys.push('Ctrl');
    if (e.shiftKey) keys.push('Shift');
    if (e.altKey) keys.push('Alt');
    if (e.key !== 'Control' && e.key !== 'Shift' && e.key !== 'Alt') {
        let key = e.key.length === 1 ? e.key.toUpperCase() : e.key;
        keys.push(key);
    }
    if (keys.length > 0) {
        document.getElementById('cgAtalho').value = keys.join('+');
    }
}

async function salvarConfigGerais() {
    // Lê cada campo com guard (alguns podem não existir dependendo da aba)
    const getCheck = (id) => { const el = document.getElementById(id); return el ? el.checked : undefined; };
    const getVal   = (id) => { const el = document.getElementById(id); return el ? el.value : undefined; };

    const notif = getCheck('cgNotificacoes');   if (notif !== undefined) currentConfig.notificacoes = notif;
    const atalho = getVal('cgAtalho');           if (atalho !== undefined) currentConfig.atalho_busca = atalho.trim();
    const priv = getCheck('cgModoPrivado');      if (priv !== undefined) currentConfig.modo_privado = priv;
    const ign = getVal('cgPastasIgnoradas');     if (ign !== undefined) currentConfig.pastas_ignoradas = ign.trim();
    const desemp = getVal('cgModoDesempenho');   if (desemp !== undefined) currentConfig.modo_desempenho = desemp;

    try {
        const res = await fetch(`${API_BASE_URL}/api/config`, {
            method: 'POST', headers: fetchOptions.headers,
            body: JSON.stringify(currentConfig)
        });
        if (res.ok) toastOk("Configurações salvas.");
        else toastErro("Não foi possível salvar as configurações.");
    } catch (e) {
        console.error(e); toastErro("Erro de conexão ao salvar.");
    }
    fecharModalConfigGerais();
}

async function limparHistoricoBusca() {
    if (!await confirmarAcao("Limpar histórico", "Tem certeza que deseja limpar todo o histórico de busca?", "Limpar")) return;
    try {
        const res = await fetch(`${API_BASE_URL}/api/clear_history`, { method: 'POST' });
        if (!res.ok) { toastErro("Não foi possível limpar o histórico."); return; }
        _historicoCache = [];
        const list = document.getElementById('searchHistoryList');
        if (list) list.innerHTML = "";
        const dd = document.getElementById('searchHistoryDropdown');
        if (dd) dd.classList.remove('aberto');
        toastOk("Histórico de busca limpo.");
    } catch (e) { console.error(e); toastErro("Erro de conexão."); }
}

async function limparCacheIA() {
    if (!await confirmarAcao("Limpar banco da IA", "Isto vai apagar todas as descrições e vetores da IA gerados até agora. O motor precisará reanalisar todos os arquivos do zero. Deseja continuar?", "Limpar tudo")) return;
    try {
        const res = await fetch(`${API_BASE_URL}/api/clear_cache`, { method: 'POST' });
        if (!res.ok) { toastErro("Não foi possível limpar o cache da IA."); return; }
        toastOk("Cache da IA limpo. Use 'Re-analisar arquivos' para gerar tudo de novo.");
    } catch (e) { console.error(e); toastErro("Erro de conexão."); }
}

// Global hotkey listener
document.addEventListener('keydown', (e) => {
    if (!currentConfig || !currentConfig.atalho_busca) return;
    
    let keys = [];
    if (e.ctrlKey) keys.push('Ctrl');
    if (e.shiftKey) keys.push('Shift');
    if (e.altKey) keys.push('Alt');
    if (e.key !== 'Control' && e.key !== 'Shift' && e.key !== 'Alt') {
        let key = e.key.length === 1 ? e.key.toUpperCase() : e.key;
        keys.push(key);
    }
    const pressedKeyStr = keys.join('+');
    
    if (pressedKeyStr === currentConfig.atalho_busca) {
        e.preventDefault();
        const searchInput = document.getElementById('searchInput');
        if (searchInput) {
            searchInput.focus();
            searchInput.select();
        }
    }
});

async function salvarPerfil() {
    const btn = document.getElementById('btnSalvarEditPerfil');
    btn.innerText = "Salvando..."; btn.disabled = true;

    currentConfig.perfil_nome = document.getElementById('editNome').value.trim() || currentConfig.perfil_nome;
    currentConfig.perfil_handle = document.getElementById('editHandle').value.trim() || currentConfig.perfil_handle;
    currentConfig.perfil_cargo = document.getElementById('editCargo').value.trim() || currentConfig.perfil_cargo;
    currentConfig.perfil_local = document.getElementById('editLocal').value.trim() || currentConfig.perfil_local;
    currentConfig.perfil_bio = document.getElementById('editBio').value.trim();

    const newAvatar = document.getElementById('editAvatar').value;
    const newBanner = document.getElementById('editBanner').value;
    if (newAvatar) currentConfig.perfil_avatar = newAvatar;
    if (newBanner) currentConfig.perfil_banner = newBanner;

    try {
        const res = await fetch(`${API_BASE_URL}/api/config`, {
            method: 'POST',
            headers: fetchOptions.headers,
            body: JSON.stringify(currentConfig)
        });

        if (res.ok) {
            await carregarConfiguracoesUX();
            fecharEditPerfil();
            abrirViewPerfil();
        } else {
            toastErro("Não foi possível salvar o perfil.");
        }
    } catch (e) {
        console.error("Erro de rede:", e);
        toastErro("Erro de conexão ao salvar o perfil.");
    } finally {
        btn.innerText = "Salvar Alterações"; btn.disabled = false;
    }
}

// ==========================================
// HISTÓRICO DE BUSCAS (do amigo)
// ==========================================
let _historicoCache = [];

async function carregarHistorico() {
    try {
        const res = await fetch(`${API_BASE_URL}/api/search_history`);
        const data = await res.json();
        _historicoCache = data.historico || [];
    } catch(e) {}
}

// Escapa caracteres HTML perigosos pra evitar XSS quando texto vai para innerHTML
function _escapeHtml(s) {
    return String(s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function mostrarHistorico() {
    if (_historicoCache.length === 0) return;
    const dropdown = document.getElementById('searchHistoryDropdown');
    const list = document.getElementById('searchHistoryList');

    // Render via DOM (anti-XSS) com itens animados em cascata
    list.innerHTML = '';
    _historicoCache.forEach((q, i) => {
        const item = document.createElement('div');
        item.className = 'history-item';
        item.style.animationDelay = `${i * 0.03}s`;

        const texto = document.createElement('span');
        texto.className = 'history-item-text';
        texto.textContent = q;
        texto.onclick = () => usarHistorico(q);

        const lupa = document.createElement('span');
        lupa.className = 'history-item-icon';
        lupa.replaceChildren(icone('lupa'));

        const remover = document.createElement('span');
        remover.className = 'history-item-remove';
        remover.textContent = '×';
        remover.title = 'Remover do histórico';
        remover.onclick = (e) => { e.stopPropagation(); removerHistorico(i); };

        item.append(lupa, texto, remover);
        list.appendChild(item);
    });

    // Mostra e dispara a animação de entrada (classe 'aberto')
    dropdown.style.display = 'block';
    requestAnimationFrame(() => dropdown.classList.add('aberto'));
}

function esconderHistorico() {
    const dropdown = document.getElementById('searchHistoryDropdown');
    dropdown.classList.remove('aberto');
    // Espera a transição de saída antes de ocultar de fato
    setTimeout(() => {
        if (!dropdown.classList.contains('aberto')) dropdown.style.display = 'none';
    }, 200);
}

function usarHistorico(query) {
    definirTextoBusca(query);
    esconderHistorico();
    realizarBusca();
}

async function removerHistorico(index) {
    await fetch(`${API_BASE_URL}/api/search_history/${index}`, { method: 'DELETE' });
    await carregarHistorico();
    if (_historicoCache.length === 0) {
        esconderHistorico();  // sem itens: fecha o dropdown
    } else {
        mostrarHistorico();
    }
}

async function salvarBuscaNoHistorico(query) {
    if (currentConfig.modo_privado) return;
    await fetch(`${API_BASE_URL}/api/search_history`, {
        method: 'POST',
        headers: fetchOptions.headers,
        body: JSON.stringify({ query })
    });
    _historicoCache = [query, ..._historicoCache.filter(q => q !== query)].slice(0, 10);
}

// ==========================================
// RE-ANÁLISE SELETIVA (do amigo)
// ==========================================
async function reAnalizarArquivos() {
    // O botão só existe na tela de pastas; quando chamado pelo menu lateral,
    // usamos toast pra dar feedback.
    const btn = document.getElementById('btnReanalizar');
    if (btn) { rotularCom(btn, 'ampulheta', 'Enfileirando...'); btn.disabled = true; }
    else { toastInfo('Reanalisando arquivos com descrição ruim...'); }
    try {
        const res = await fetch(`${API_BASE_URL}/api/reanalyze`, { method: 'POST' });
        const data = await res.json();
        // Imagens com descrição em formato antigo não vão pra fila: elas são
        // redescritas sozinhas na próxima busca em que aparecerem.
        const limpas = data.descricoes_limpas || 0;
        const extra = limpas ? ` + ${limpas} imagem(ns) marcada(s) pra redescrever` : '';
        if (btn) {
            rotularCom(btn, 'check-circulo', `${data.reenfileirados} arquivo(s) na fila!`);
            setTimeout(() => { btn.innerText = 'Re-analisar Arquivos com Descrição Ruim'; btn.disabled = false; }, 3000);
            if (limpas) toastOk(`${limpas} imagem(ns) serão redescritas na próxima busca.`);
        } else {
            toastOk(`${data.reenfileirados} arquivo(s) na fila de reanálise${extra}.`);
        }
    } catch(e) {
        if (btn) { btn.innerText = 'Re-analisar Arquivos com Descrição Ruim'; btn.disabled = false; }
        else { toastErro('Não foi possível reanalisar.'); }
    }
}

// ==========================================
// ABRIR LOCAL NO EXPLORER (do amigo)
// ==========================================
let _caminhoArquivoAtual = '';

async function abrirLocalDoArquivo() {
    if (!_caminhoArquivoAtual) return;
    try {
        await fetch(`${API_BASE_URL}/api/open_location?path=${encodeURIComponent(_caminhoArquivoAtual)}`);
    } catch(e) { console.error('Erro ao abrir local:', e); }
}

// ==========================================
// BUSCA E DASHBOARD (SOFT TRANSITIONS GLOBAIS)
// ==========================================
function voltarParaHomeSmooth() {
    definirTextoBusca('');
    document.getElementById('searchResultsView').classList.add('fade-out');
    document.getElementById('searchResultsView').style.opacity = '0';
    document.getElementById('filterBarContainer').style.opacity = '0';
    fecharPainelLateral();

    setTimeout(() => {
        document.getElementById('searchResultsView').style.display = 'none';
        document.getElementById('filterBarContainer').style.display = 'none';

        const wrapper = document.getElementById('mainAppWrapper');
        wrapper.classList.remove('layout-top');
        wrapper.classList.add('layout-centered');

        // Sem condição: clicar no logo sempre devolve a home. Antes isso era
        // guardado por `searchHistoryExists` e, antes da primeira busca, o
        // clique só apagava os resultados e deixava a tela em branco.
        mostrarHome();
    }, 400);
}

// ==========================================
// FILTROS AVANÇADOS
// ==========================================
function toggleFiltrosAvancados() {
    const painel = document.getElementById('filtrosAvancados');
    const aberto = painel.style.display !== 'none';
    if (!aberto) preencherPastasFiltro();
    painel.style.display = aberto ? 'none' : 'grid';
    document.getElementById('btnFiltrosAvancados').classList.toggle('active', !aberto);
}

function preencherPastasFiltro() {
    const sel = document.getElementById('filtroPasta');
    const atual = sel.value;
    sel.innerHTML = '<option value="">Todas as pastas</option>';
    (currentConfig.pastas || []).forEach(p => {
        const opt = document.createElement('option');
        opt.value = p;
        // Mostra só o nome final da pasta pra não ficar gigante
        opt.textContent = p.split(/[\\/]/).filter(Boolean).pop() || p;
        sel.appendChild(opt);
    });
    sel.value = atual;
}

// Coleta os filtros preenchidos num objeto (só inclui o que tem valor)
function coletarFiltrosAvancados() {
    const av = {};
    const dataDe  = document.getElementById('filtroDataDe')?.value;
    const dataAte = document.getElementById('filtroDataAte')?.value;
    const tamMin  = document.getElementById('filtroTamMin')?.value;
    const tamMax  = document.getElementById('filtroTamMax')?.value;
    const pasta   = document.getElementById('filtroPasta')?.value;
    if (dataDe)  av.data_de = dataDe;
    if (dataAte) av.data_ate = dataAte;
    if (tamMin)  av.tam_min = parseFloat(tamMin);
    if (tamMax)  av.tam_max = parseFloat(tamMax);
    if (pasta)   av.pasta = pasta;
    if (_soFavoritos) av.so_favoritos = true;
    return av;
}

// Buscar só entre os favoritos. Fica na barra de filtros, junto de "Imagens" e
// "Documentos", porque é da mesma natureza: reduz o conjunto antes da busca.
let _soFavoritos = false;

function alternarBuscaSoFavoritos() {
    _soFavoritos = !_soFavoritos;

    const btn = document.getElementById('btnFiltroFavoritos');
    btn.classList.toggle('active', _soFavoritos);
    btn.setAttribute('aria-pressed', _soFavoritos ? 'true' : 'false');
    btn.replaceChildren(iconeFav(_soFavoritos), document.createTextNode(' Favoritos'));

    if (document.getElementById('searchInput').value.trim()) realizarBusca();
}

function temFiltrosAtivos() {
    return Object.keys(coletarFiltrosAvancados()).length > 0;
}

function aplicarFiltrosAvancados() {
    const n = Object.keys(coletarFiltrosAvancados()).length;
    document.getElementById('btnFiltrosAvancados').classList.toggle('tem-filtro', n > 0);
    if (document.getElementById('searchInput').value.trim()) {
        realizarBusca();
    } else {
        toastInfo("Digite algo para buscar com os filtros.");
    }
}

function limparFiltrosAvancados() {
    ['filtroDataDe','filtroDataAte','filtroTamMin','filtroTamMax'].forEach(id => {
        const el = document.getElementById(id); if (el) el.value = '';
    });
    const sel = document.getElementById('filtroPasta'); if (sel) sel.value = '';
    document.getElementById('btnFiltrosAvancados').classList.remove('tem-filtro');
    toastInfo("Filtros limpos.");
}

async function realizarBusca() {
    const query = document.getElementById('searchInput').value;
    if (!query.trim()) return;

    // Contexto novo: não faz sentido carregar a seleção da busca anterior
    if (typeof limparSelecao === 'function') limparSelecao();


    document.getElementById('dashboardView').classList.add('fade-out');
    fecharPainelLateral();

    setTimeout(() => {
        document.getElementById('dashboardView').style.display = 'none';

        const wrapper = document.getElementById('mainAppWrapper');
        wrapper.classList.remove('layout-centered');
        wrapper.classList.add('layout-top');

        document.getElementById('filterBarContainer').style.display = 'flex';
        setTimeout(() => document.getElementById('filterBarContainer').style.opacity = '1', 50);

        document.getElementById('searchResultsView').style.display = 'block';
        document.getElementById('searchResultsView').classList.add('fade-out');
    }, 400);

    const loadingScreen = document.getElementById('iaLoadingScreen');
    const tipElement = document.getElementById('tipCarousel');
    loadingScreen.style.display = 'flex';

    let tipIndex = 0; tipElement.innerText = dicasUX[tipIndex];
    tipInterval = setInterval(() => { tipIndex = (tipIndex + 1) % dicasUX.length; tipElement.innerText = dicasUX[tipIndex]; }, 3000);

    const startTime = Date.now();

    try {
        const corpo = { query: query, filtro: filtroAtual, avancado: coletarFiltrosAvancados() };
        if (_refino.escopo && _refino.escopo.ids.length) {
            corpo.escopo = _refino.escopo.ids;
        }
        const res = await fetch(`${API_BASE_URL}/api/search`, { method: 'POST', headers: fetchOptions.headers, body: JSON.stringify(corpo) });
        const dados = await res.json();

        // Sem esta checagem, um 503 caía no `dados.resultados || []` e virava
        // uma tela de "nada encontrado" — a resposta mais enganosa possível
        // para quem só precisava esperar dez segundos.
        if (!res.ok) {
            toastAviso(dados.erro || 'A busca não está disponível agora.');
            if (dados.carregando) marcarBuscaPreparando(true);
            window.resultadosAtuais = [];
            return;
        }

        window.resultadosAtuais = Array.isArray(dados) ? dados : (dados.resultados || []);
        salvarBuscaNoHistorico(query.trim());

        // A trilha reflete o que o servidor entendeu do pedido.
        _refino.consulta = dados.consulta || query.trim();
        _refino.excluidos = dados.excluidos || [];
        if (!dados.escopo) _refino.escopo = null;
        desenharTrilhaDeRefino();

    } catch (e) { console.error(e); toastErro("Erro ao buscar. Verifique a conexão."); } finally {
        const tempoRestante = Math.max(0, 2000 - (Date.now() - startTime));
        setTimeout(() => {
            clearInterval(tipInterval);
            loadingScreen.style.display = 'none';
            renderizarResultados();
            popularDashboard(window.resultadosAtuais);

            // CORREÇÃO: Força a visibilidade dos resultados
            document.getElementById('searchResultsView').classList.remove('fade-out');
            document.getElementById('searchResultsView').style.opacity = '1';

            const hora = new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
            document.getElementById('statTempo').innerText = hora;

        }, tempoRestante);
    }
}

// Cards de "recentes", montados pelo DOM.
//
// A versão anterior montava isto com template string e innerHTML, e o nome do
// arquivo entrava em DOIS lugares onde não podia:
//
//   onclick="abrirPainelPeloNome('${r.nome}')"   e   <p>${r.nome}</p>
//
// Um apóstrofo no nome — "Ana's foto.jpg", coisa comuníssima — fechava a
// string do onclick e o card parava de abrir. Um `<` no nome injetava HTML.
// Como os nomes vêm de arquivos do disco, basta alguém receber um arquivo com
// nome preparado para isso virar execução de script.
//
// Montar pelo DOM resolve os dois de uma vez: `textContent` não interpreta
// HTML, e o clique é uma função de verdade, não texto que vira código.
//
// De quebra, o índice vai na closure em vez de o clique procurar o arquivo
// pelo nome depois — dois arquivos com o mesmo nome em pastas diferentes
// abriam o errado.
function popularDashboard(resultados) {
    const rGridImg = document.getElementById('recentImgs');
    const rGridDoc = document.getElementById('recentDocs');
    if (!rGridImg || !rGridDoc) return;

    const imagens = document.createDocumentFragment();
    const documentos = document.createDocumentFragment();
    let imgs = 0, docs = 0;

    resultados.forEach((r, indice) => {
        const ext = (r.tipo || '').toLowerCase();
        const ehImagem = extensoesImagem.includes(ext);
        if (ehImagem ? imgs >= 4 : docs >= 4) return;

        const card = document.createElement('div');
        card.className = 'recent-card';
        card.onclick = () => abrirPainelLateral(indice);

        const midia = document.createElement('div');
        if (ehImagem) {
            midia.className = 'recent-img';
            const img = document.createElement('img');
            img.src = formatImagePath(r.caminho);
            img.alt = textoAlternativo(r);
            midia.appendChild(img);
        } else {
            midia.className = 'recent-img doc-icon';
            midia.textContent = ext.toUpperCase();
        }

        const nome = document.createElement('p');
        nome.textContent = r.nome;

        card.append(midia, nome);
        if (ehImagem) { imagens.appendChild(card); imgs++; }
        else { documentos.appendChild(card); docs++; }
    });

    // Uma escrita por grade, e não uma por card: `innerHTML +=` dentro do laço
    // reconstruía tudo que já estava lá a cada volta.
    rGridImg.replaceChildren(imagens);
    rGridDoc.replaceChildren(documentos);
}

// ==========================================
// MODAL PASTAS E FILTROS
// ==========================================
function fecharModalPastas() { document.getElementById('foldersModal').style.display = 'none'; }
async function abrirModalPastas() {
    document.getElementById('foldersModal').style.display = 'flex';
    document.getElementById('foldersList').innerHTML = '<p>Carregando...</p>';
    const res = await fetch(`${API_BASE_URL}/api/folders`);
    const config = await res.json();
    atualizarListaModalPastas(config.pastas);
}
function atualizarListaModalPastas(pastas) {
    const list = document.getElementById('foldersList');
    _foldersData = pastas || [];
    if (!pastas || pastas.length === 0) {
        list.innerHTML = '<p style="color:var(--text-secondary);">Nenhuma pasta do computador ainda.</p>';
        document.getElementById('folderConfigInline').style.display = 'none';
        return;
    }
    list.innerHTML = '';
    pastas.forEach(f => {
        const p = typeof f === 'string' ? f : f.path;
        const prio = (f.prioridades || ['tudo']).join(', ');
        const perfil = f.perfil_analise || 'fast';
        const janela = f.janela_processamento || 'always';
        const fId = f.id || 0;
        const escapedPath = p.replace(/\\/g, '\\\\');
        list.innerHTML += `<div class="folder-item" style="flex-wrap:wrap;">
            <div style="flex:1; min-width:0;">
                <span class="folder-path">${p}</span>
                <div class="folder-config-badges">
                    <span class="folder-badge badge-foco">${prio}</span>
                    <span class="folder-badge badge-perfil">${perfil === 'deep' ? 'Deep' : 'Fast'}</span>
                    <span class="folder-badge badge-janela">${janela === 'always' ? 'Sempre' : '' + janela}</span>
                </div>
            </div>
            <div style="display:flex; gap:6px; align-items:center; margin-top:5px;">
                <button class="btn-verificar-pasta" id="btnVerificar${fId}"
                        onclick="verificarPasta(${fId})"
                        title="Procura arquivos novos, alterados ou apagados nesta pasta">Verificar</button>
                <button class="btn-config-folder" onclick="abrirConfigPasta(${fId}, '${escapedPath}')">Config</button>
                <button class="btn-remover" onclick="removerPasta('${escapedPath}')">Excluir</button>
            </div>
        </div>`;
    });
}

// ==========================================
// VERIFICAR ALTERACOES NUMA PASTA INDEXADA
// ==========================================
// O Search+ indexa a pasta uma vez. Depois disso o usuario continua mexendo
// nos arquivos, e ate agora o app so sabia somar: arquivo editado nunca era
// relido, e arquivo apagado continuava aparecendo na busca -- levando a um
// clique que nao abre nada.
async function verificarPasta(folderId) {
    const btn = document.getElementById(`btnVerificar${folderId}`);
    const rotulo = btn ? btn.textContent : 'Verificar';
    if (btn) { btn.disabled = true; btn.textContent = 'Verificando...'; }

    try {
        const r = await fetch(`${API_BASE_URL}/api/folders/${folderId}/verificar`, {
            method: 'POST', headers: fetchOptions.headers
        });

        if (!r.ok) {
            toastErro(await _erroDaResposta(r, 'Não foi possível verificar a pasta'));
            return;
        }

        const d = await r.json();
        mostrarResultadoDaVerificacao(d.resumo, d);
    } catch (e) {
        toastErro('Não foi possível verificar a pasta. O servidor respondeu?');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = rotulo; }
    }
}

function mostrarResultadoDaVerificacao(resumo, detalhe) {
    const partes = [];
    if (resumo.novos)       partes.push(`${resumo.novos} ${resumo.novos === 1 ? 'arquivo novo' : 'arquivos novos'}`);
    if (resumo.modificados) partes.push(`${resumo.modificados} ${resumo.modificados === 1 ? 'alterado' : 'alterados'}`);
    if (resumo.ausentes)    partes.push(`${resumo.ausentes} que não está mais na pasta`);
    if (resumo.voltaram)    partes.push(`${resumo.voltaram} que reapareceu`);

    if (partes.length === 0) {
        toastOk('Nada mudou nesta pasta desde a última vez.');
        return;
    }

    // Dizer o que foi achado e parar ali deixaria o usuario sem saber se
    // precisa fazer mais alguma coisa. Novos e alterados ja entraram na fila;
    // o ausente e o unico que fica so marcado, e vale dizer por que.
    let msg = `Encontrei ${partes.join(', ')}.`;
    if (resumo.novos || resumo.modificados) {
        msg += ' Já comecei a analisar.';
    }
    if (resumo.ausentes) {
        msg += ' Os que sumiram ficaram marcados, não apaguei nada — se estiverem'
             + ' num disco desconectado, é só reconectar e verificar de novo.';
    }
    toastInfo(msg);

    const listar = (rotulo, nomes) => nomes.length
        ? `${rotulo}: ${nomes.slice(0, 8).join(', ')}${nomes.length > 8 ? ` e mais ${nomes.length - 8}` : ''}`
        : '';
    console.log([
        listar('Novos', detalhe.novos || []),
        listar('Alterados', detalhe.modificados || []),
        listar('Fora da pasta', detalhe.ausentes || []),
        listar('Reapareceram', detalhe.voltaram || []),
    ].filter(Boolean).join('\n'));
}

async function adicionarPasta() {
    const btn = document.getElementById('btnAdicionarPasta'); rotularCom(btn, 'ampulheta', 'Abrindo Windows...');
    const res = await fetch(`${API_BASE_URL}/api/choose_folder`); const data = await res.json();
    if (data.status === "sucesso") {
        rotularCom(btn, 'ampulheta', 'Salvando...');
        const updateRes = await fetch(`${API_BASE_URL}/api/folders`, {
            method: 'POST', headers: fetchOptions.headers,
            body: JSON.stringify({ pasta: data.pasta, prioridades: ['tudo'], perfil_analise: 'fast', janela_processamento: 'always' })
        });
        const config = await updateRes.json();
        atualizarListaModalPastas(config.pastas);
        toastInfo("Pasta adicionada. Clique em \"Analisar Pastas\" quando quiser iniciar a IA.");
    }
    btn.innerText = "+ Adicionar pasta";
}

async function removerPasta(p) {
    if (!await confirmarAcao("Remover pasta", "Remover esta pasta do computador? O Search+ não vai mais buscar nela.", "Remover")) return;
    try {
        const res = await fetch(`${API_BASE_URL}/api/folders`, { method: 'DELETE', headers: fetchOptions.headers, body: JSON.stringify({ pasta: p }) });
        if (!res.ok) {
            toastErro(await _erroDaResposta(res, 'Não foi possível remover a pasta'));
            return;
        }
        const config = await res.json();
        atualizarListaModalPastas(config.pastas);
    } catch (e) {
        console.error(e);
        toastErro('Não foi possível remover a pasta. O servidor respondeu?');
    }
}

async function forcarAnalise() {
    const btn = document.getElementById('btnAnalisarPastas');
    const textoOriginal = btn.innerHTML;
    rotularCom(btn, 'ampulheta', 'Atualizando embeddings...');
    btn.disabled = true;
    try {
        // 1. Re-gera embeddings dos arquivos já processados (rápido, sem LLaVA)
        await fetch(`${API_BASE_URL}/api/reembed`, { method: 'POST', headers: fetchOptions.headers });
        rotularCom(btn, 'ampulheta', 'Sincronizando com a IA...');
        // 2. Escaneia pastas em busca de arquivos novos
        await fetch(`${API_BASE_URL}/api/analyze_folders`, { method: 'POST', headers: fetchOptions.headers });
        rotularCom(btn, 'check-circulo', 'Análise Iniciada!');
        setTimeout(() => {
            btn.innerHTML = textoOriginal;
            btn.disabled = false;
            fecharModalPastas();
            buscarStatus();
        }, 1500);
    } catch(e) {
        btn.innerHTML = textoOriginal;
        btn.disabled = false;
    }
}

// Resultados que o filtro atual deixa passar. Extraído de renderizarResultados()
// porque "selecionar tudo" precisa da MESMA lista que está na tela — se as duas
// aplicassem o filtro por conta própria, uma mudança em uma delas dessincronizaria
// o contador do que o usuário enxerga.
function resultadosVisiveis() {
    return (window.resultadosAtuais || []).filter(r => {
        const ext = (r.tipo || '').toLowerCase();
        if (filtroAtual === 'all') return true;
        if (filtroAtual === 'imagem') return extensoesImagem.includes(ext);
        if (filtroAtual === 'midia') return extensoesAudio.includes(ext) || extensoesVideo.includes(ext);
        return !extensoesImagem.includes(ext) && !extensoesAudio.includes(ext) && !extensoesVideo.includes(ext);
    });
}

// ==========================================
// FAVORITOS COMO ORIGEM DE COLEÇÃO
// ==========================================
// Favoritar era um beco sem saída: a estrela marcava o arquivo e parava por
// aí. Quem passou meses favoritando as fotos boas não tinha como transformar
// isso numa coleção sem reabrir cada uma.
function favoritosSelecionados() {
    return (window._favoritosCarregados || []).filter(r => _selecionados.has(r.id));
}

function atualizarAcoesFavoritos() {
    const barra = document.getElementById('favoritosAcoes');
    if (!barra) return;

    const todos = window._favoritosCarregados || [];
    const marcados = favoritosSelecionados().length;

    // Sem favorito não há o que selecionar, e a barra vira ruído.
    barra.style.display = todos.length ? 'flex' : 'none';

    const btnTodos = document.getElementById('favSelecionarTodos');
    const tudoMarcado = todos.length > 0 && marcados === todos.length;
    rotularCom(btnTodos, tudoMarcado ? 'desmarcar-tudo' : 'marcar-tudo',
               tudoMarcado ? 'Desmarcar tudo' : 'Selecionar tudo');
    btnTodos.setAttribute('aria-pressed', tudoMarcado ? 'true' : 'false');

    const resumo = document.getElementById('favResumo');
    resumo.textContent = marcados
        ? `${marcados} ${marcados === 1 ? 'selecionado' : 'selecionados'}`
        : `${todos.length} ${todos.length === 1 ? 'favorito' : 'favoritos'}`;

    // Enviar zero imagens para uma coleção não faz nada; o botão desligado
    // diz isso antes do clique, em vez de um aviso depois.
    document.getElementById('favEnviar').disabled = marcados === 0;
}

function alternarSelecionarTodosFavoritos() {
    const todos = window._favoritosCarregados || [];
    if (!todos.length) return;

    const tudoMarcado = todos.every(r => _selecionados.has(r.id));
    todos.forEach(r => {
        if (tudoMarcado) _selecionados.delete(r.id);
        else _selecionados.add(r.id);
    });

    sincronizarCardsDeFavoritos();
    atualizarAcoesFavoritos();
    _salvarSelecao();
    atualizarBarraSelecao();
}

function sincronizarCardsDeFavoritos() {
    document.querySelectorAll('.fav-card[data-file-id]').forEach(card => {
        const marcado = _selecionados.has(Number(card.dataset.fileId));
        card.classList.toggle('card-selecionado', marcado);
        const btn = card.querySelector('.btn-sel-fav');
        if (btn) {
            btn.classList.toggle('is-sel', marcado);
            marcarBotaoSelecao(btn, marcado);
            btn.setAttribute('aria-checked', marcado ? 'true' : 'false');
        }
    });
}

// Enviar os favoritos marcados para uma coleção — existente ou nova.
async function enviarFavoritosParaColecao() {
    const marcados = favoritosSelecionados();
    if (!marcados.length) return;

    const escolha = await escolherColecaoParaFavoritos(marcados.length);
    if (!escolha) return;

    const r = await fetch(`${API_BASE_URL}/api/collections/${escolha.id}/files`, {
        method: 'POST', headers: fetchOptions.headers,
        body: JSON.stringify({ file_ids: marcados.map(x => x.id) }),
    });
    if (!r.ok) {
        toastErro(await _erroDaResposta(r, 'Não foi possível adicionar à coleção'));
        return;
    }
    const d = await r.json();

    const n = d.adicionados || 0;
    const jaEstavam = d.ja_existiam || 0;
    let msg = n
        ? `${n} ${n === 1 ? 'imagem foi' : 'imagens foram'} para “${escolha.nome}”.`
        : 'Essas imagens já estavam na coleção.';
    if (n && jaEstavam) msg += ` ${jaEstavam} já ${jaEstavam === 1 ? 'estava' : 'estavam'} lá.`;
    toastOk(msg);

    limparSelecao();
    fecharFavoritos();

    // Levar a pessoa até a coleção fecha o ciclo: ela pediu para mandar as
    // fotos para lá, e ver o resultado é a confirmação de que deu certo.
    verColecao(escolha.id, escolha.nome);
}

// Modal de escolha reaproveitado, mas devolvendo a coleção em vez de agir
// sozinho — aqui quem adiciona é o chamador, que precisa saber para onde
// redirecionar depois.
//
// Enquanto uma escolha está pendente, este resolvedor fica guardado aqui. É o
// que permite ao X, ao clique no fundo e ao Esc cancelarem o envio: sem ele, a
// promessa ficaria pendurada e o botão "criar nova coleção" continuaria
// sequestrado para o fluxo dos favoritos.
let _resolverEscolhaColecao = null;

function _encerrarEscolhaColecao(valor) {
    document.getElementById('escolherColecaoModal').style.display = 'none';

    // Devolve o botão ao comportamento normal, usado pelo painel lateral.
    const btnNova = document.getElementById('escolherColecaoNova');
    if (btnNova) btnNova.onclick = () => criarColecaoEAdicionar();

    const resolver = _resolverEscolhaColecao;
    _resolverEscolhaColecao = null;
    if (resolver) resolver(valor);
}

function escolherColecaoParaFavoritos(quantas) {
    return new Promise(async (resolve) => {
        _resolverEscolhaColecao = resolve;

        const lista = document.getElementById('escolherColecaoLista');
        const modal = document.getElementById('escolherColecaoModal');
        lista.innerHTML = '<p style="color:var(--text-secondary);">Carregando...</p>';
        modal.style.display = 'flex';

        // "Criar nova coleção" a partir dos favoritos: o caso de quem
        // favoritou durante meses e agora quer juntar tudo num lugar novo.
        document.getElementById('escolherColecaoNova').onclick = async () => {
            const nome = await pedirTexto('Nova coleção',
                `Nome da coleção para ${quantas} ${quantas === 1 ? 'imagem' : 'imagens'}:`);
            if (!nome) return;
            const r = await fetch(`${API_BASE_URL}/api/collections`, {
                method: 'POST', headers: fetchOptions.headers,
                body: JSON.stringify({ nome }),
            });
            if (!r.ok) {
                toastErro(await _erroDaResposta(r, 'Não foi possível criar a coleção'));
                return;
            }
            const nova = await r.json();
            _encerrarEscolhaColecao({ id: nova.id, nome: nova.nome });
        };

        try {
            const res = await fetch(`${API_BASE_URL}/api/collections`);
            const cols = (await res.json()).colecoes || [];
            lista.innerHTML = '';
            if (!cols.length) {
                lista.innerHTML = '<p style="color:var(--text-secondary);">' +
                    'Você ainda não tem coleções. Crie uma abaixo.</p>';
            }
            cols.forEach(c => {
                const btn = document.createElement('button');
                btn.className = 'escolher-colecao-item';
                const nm = document.createElement('span');
                nm.textContent = c.nome;
                const cnt = document.createElement('span');
                cnt.className = 'escolher-colecao-count';
                cnt.textContent = `${c.total} ${c.total === 1 ? 'item' : 'itens'}`;
                btn.append(nm, cnt);
                btn.onclick = () => _encerrarEscolhaColecao({ id: c.id, nome: c.nome });
                lista.appendChild(btn);
            });
        } catch (e) {
            lista.innerHTML = '<p style="color:#f87171;">Erro ao carregar coleções.</p>';
        }
    });
}

// ==========================================
// REFINAR SEM RECOMEÇAR
// ==========================================
// Antes, cada tentativa jogava fora o que a busca anterior já tinha acertado:
// quem procurou "praia" e recebeu trinta fotos com gente no meio só podia
// reescrever a frase e torcer. Agora o refino se acumula, e cada pedaço dele
// aparece na tela e pode ser removido sozinho.
//
// A trilha é desenhada a partir do que o SERVIDOR entendeu, não do que foi
// digitado. Se o parser separasse "-pessoas" de um jeito e a tela mostrasse
// de outro, remover um chip não mudaria a busca e ninguém entenderia por quê.
let _refino = { consulta: '', excluidos: [], escopo: null };

function _limparRefino() {
    _refino = { consulta: '', excluidos: [], escopo: null };
    desenharTrilhaDeRefino();
}

function desenharTrilhaDeRefino() {
    const faixa = document.getElementById('trilhaRefino');
    if (!faixa) return;

    faixa.innerHTML = '';
    const chips = [];

    if (_refino.consulta) {
        chips.push({ rotulo: _refino.consulta, tipo: 'consulta',
                     ajuda: 'O que você procurou.' });
    }
    (_refino.excluidos || []).forEach(termo => {
        chips.push({ rotulo: `sem ${termo}`, tipo: 'excluido', valor: termo,
                     ajuda: `Resultados com "${termo}" foram deixados de fora.` });
    });
    if (_refino.escopo) {
        const n = _refino.escopo.ids.length;
        chips.push({ rotulo: n === 1 ? 'dentro de 1 resultado'
                                     : `dentro de ${n} resultados`,
                     tipo: 'escopo',
                     ajuda: 'A busca está limitada ao resultado anterior.' });
    }

    // Um chip só (a própria consulta) não é uma trilha — é a caixa de busca
    // repetida logo abaixo dela.
    if (chips.length < 2) {
        faixa.style.display = 'none';
        return;
    }
    faixa.style.display = 'flex';

    chips.forEach(c => {
        const chip = document.createElement('span');
        chip.className = `chip-refino chip-refino-${c.tipo}`;
        chip.title = c.ajuda;

        const txt = document.createElement('span');
        txt.textContent = c.rotulo;
        chip.appendChild(txt);

        // A consulta em si não some por um X: sem ela não sobra busca. Quem
        // quer trocá-la usa a caixa, que está logo acima.
        if (c.tipo !== 'consulta') {
            const x = document.createElement('button');
            x.type = 'button';
            x.className = 'chip-refino-x';
            x.setAttribute('aria-label', `Remover: ${c.rotulo}`);
            x.textContent = '×';
            x.onclick = () => removerRefino(c.tipo, c.valor);
            chip.appendChild(x);
        }
        faixa.appendChild(chip);
    });
}

async function removerRefino(tipo, valor) {
    if (tipo === 'escopo') {
        _refino.escopo = null;
    } else if (tipo === 'excluido') {
        _refino.excluidos = (_refino.excluidos || []).filter(t => t !== valor);
        // A caixa de busca precisa acompanhar: o "-termo" que saiu da trilha
        // não pode continuar escrito lá, ou a próxima busca o traz de volta.
        const campo = document.getElementById('searchInput');
        campo.value = campo.value
            .split(/\s+/)
            .filter(p => p.toLowerCase() !== `-${valor}`.toLowerCase())
            .join(' ')
            .trim();
    }
    desenharTrilhaDeRefino();
    await realizarBusca();
}

// "Buscar dentro destes resultados": o próximo pedido fica limitado ao que
// está na tela agora.
function buscarDentroDosResultados() {
    const ids = resultadosVisiveis().map(r => r.id);
    if (!ids.length) return;

    _refino.escopo = { ids };
    desenharTrilhaDeRefino();

    const campo = document.getElementById('searchInput');
    campo.focus();
    campo.select();
    toastInfo(`A próxima busca vai olhar só estes ${ids.length} resultados.`);
}

// Por que este resultado apareceu.
//
// O número que ordena a busca continua escondido: "0,72" não ensina nada a
// ninguém. O que ajuda é saber QUAL sinal respondeu, porque é isso que diz
// como pedir da próxima vez — se a foto veio pela aparência, descrever a cena
// funciona; se veio pelo nome, vale continuar usando o nome.
const ROTULO_ORIGEM = {
    aparencia: { texto: 'pela aparência',
                 ajuda: 'A imagem foi reconhecida pelo que aparece nela. ' +
                        'Descrever a cena costuma funcionar bem.' },
    descricao: { texto: 'pelo que a imagem mostra',
                 ajuda: 'Bateu com a descrição que o Search+ escreveu sobre esta imagem.' },
    texto:     { texto: 'pelo texto do documento',
                 ajuda: 'O termo que você procurou está escrito dentro do arquivo.' },
    nome:      { texto: 'pelo nome do arquivo',
                 ajuda: 'O nome do arquivo contém o que você digitou.' },
};

function badgeDeOrigem(origem) {
    const r = ROTULO_ORIGEM[origem];
    if (!r) return '';   // origem desconhecida: melhor nada que um rótulo errado
    return `<span class="badge origem" title="${_attr(r.ajuda)}">${r.texto}</span>`;
}

function renderizarResultados() {
    const mGrid = document.getElementById('melhoresGrid'); const oGrid = document.getElementById('outrasGrid');
    mGrid.innerHTML = ''; oGrid.innerHTML = '';

    const filtrados = resultadosVisiveis();

    if (filtrados.length > 0) {
        document.getElementById('tituloMelhores').style.display = 'block';
    } else {
        document.getElementById('tituloMelhores').style.display = 'none';
        // Sem resultados não há o que selecionar: a barra de ações some (CA-005).
        atualizarAcoesResultados();
        mGrid.innerHTML = '';
        montarEstadoVazio(mGrid);
        atualizarAcoesResultados();
        return;
    }

    // Lista única, ordenada do melhor pro pior. O Claude já garante que todos
    // os resultados são relevantes, então não há mais divisão Exato/Semântico.
    const ordenados = [...filtrados].sort((a, b) => b.score - a.score);

    const buildCard = (r) => {
        const ext = r.tipo.toLowerCase(); const link = formatImagePath(r.caminho);
        let midia = `<div class="document-icon-wrapper"><svg viewBox='0 0 24 24'><path d='M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2h12c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z'/></svg></div>`;
        if (extensoesVideo.includes(ext)) midia = `<video controls><source src="${link}"></video>`;
        else if (extensoesAudio.includes(ext)) midia = `<audio controls><source src="${link}"></audio>`;
        else if (extensoesImagem.includes(ext)) midia = `<img src="${link}" alt="${_attr(textoAlternativo(r))}">`;

        const idx = window.resultadosAtuais.indexOf(r);
        let trecho = r.trecho && r.trecho !== "Nenhum conteúdo..." ? `<div class="trecho-preview">"${r.trecho}"</div>` : '';

        const favClass = r.favorito ? 'is-fav' : '';
        const favBtn = `<button type="button" class="btn-fav-abs ${favClass}" ` +
            `aria-pressed="${!!r.favorito}" aria-label="${r.favorito ? 'Remover dos favoritos' : 'Favoritar'}" ` +
            `title="${r.favorito ? 'Remover dos favoritos' : 'Favoritar'}" ` +
            `onclick="toggleFavorito(event, ${r.id}, this)">${iconeFavHTML(r.favorito)}</button>`;

        // Seleção ≠ favorito: caixa quadrada à esquerda, coração à direita.
        // O estado vem do Set em memória, não do DOM — o grid é reconstruído
        // inteiro a cada troca de filtro e levaria a marcação junto.
        const sel = _selecionados.has(r.id);
        const selBtn = `<button type="button" class="btn-sel-abs${sel ? ' is-sel' : ''}" role="checkbox" aria-checked="${sel}" aria-label="Selecionar para coleção" title="Selecionar para coleção" onclick="alternarSelecao(event, ${r.id}, this)">${sel ? iconeHTML('check') : ''}</button>`;

        return `<div class="card${sel ? ' card-selecionado' : ''}" data-file-id="${r.id}" data-idx="${idx}" onclick="abrirPainelLateral(${idx})" onmouseenter="mostrarHoverPreview(event, ${idx})" onmousemove="moverHoverPreview(event)" onmouseleave="esconderHoverPreview()">${selBtn}${favBtn}<div class="media-container">${midia}</div><div class="card-content"><h3>${r.nome}</h3><div class="tags"><span class="badge type">${ext.toUpperCase()}</span>${badgeDeOrigem(r.origem)}</div>${trecho}</div></div>`;
    };

    mGrid.innerHTML = ordenados.map(buildCard).join('');
    oGrid.innerHTML = '';
    atualizarAcoesResultados();
}

// ==========================================
// ESTADO VAZIO DA BUSCA
// ==========================================
// "Nada encontrado." sozinho faz o usuário achar que escreveu errado. Numa
// busca semântica ele não tem como saber se o problema foi a frase, o filtro,
// a pasta que não está indexada, ou se realmente não existe. Aqui a tela diz
// qual dos quatro é — e oferece um caminho de saída clicável.

async function montarEstadoVazio(grid) {
    const consulta = (document.getElementById('searchInput').value || '').trim();
    const box = document.createElement('div');
    box.className = 'vazio-box';

    const titulo = document.createElement('h3');
    titulo.className = 'vazio-titulo';
    const motivo = document.createElement('p');
    motivo.className = 'vazio-motivo';
    box.append(titulo, motivo);

    // Causa 1 — o filtro escondeu tudo. Detectável na hora, sem rede: há
    // resultados, mas nenhum sobrevive ao filtro ativo.
    const totalSemFiltro = (window.resultadosAtuais || []).length;
    const rotuloFiltro = { imagem: 'Imagens', documento: 'Documentos', midia: 'Áudio / Vídeo' }[filtroAtual];
    if (totalSemFiltro > 0 && rotuloFiltro) {
        titulo.textContent = `Nenhum resultado em "${rotuloFiltro}"`;
        motivo.textContent =
            `A busca por "${consulta}" encontrou ${totalSemFiltro} ` +
            `${totalSemFiltro === 1 ? 'item' : 'itens'}, mas ${totalSemFiltro === 1 ? 'ele não é' : 'nenhum é'} ` +
            `do tipo ${rotuloFiltro.toLowerCase()}.`;
        box.appendChild(_botaoVazio('Ver todos os tipos', () => {
            const tudo = document.querySelector('.filter-tag[data-filter="all"]');
            if (tudo) tudo.click();
        }));
        grid.appendChild(box);
        return;
    }

    titulo.textContent = `Nada encontrado para "${consulta}"`;
    motivo.textContent = 'Carregando sugestões…';
    grid.appendChild(box);

    // Causa 2 — não há nada indexado. Sem isso, qualquer busca falharia, e
    // sugerir termos seria enganoso.
    let indexados = null, categorias = [];
    try {
        const [rs, rg] = await Promise.all([
            fetch(`${API_BASE_URL}/api/stats`),
            fetch(`${API_BASE_URL}/api/gallery`),
        ]);
        if (rs.ok) indexados = ((await rs.json()).total_arquivos ?? null);
        if (rg.ok) categorias = ((await rg.json()).grupos || []).filter(c => c.total > 0);
    } catch (e) { console.error(e); }

    if (indexados === 0) {
        titulo.textContent = 'Nenhuma imagem analisada ainda';
        motivo.textContent =
            'O Search+ só encontra o que já analisou. Adicione uma pasta do seu ' +
            'computador para ele começar a analisar as imagens e documentos.';
        box.appendChild(_botaoVazio('Adicionar pasta', () => {
            if (typeof abrirModalPastas === 'function') abrirModalPastas();
        }));
        return;
    }

    // Causa 3 — há acervo, a frase é que não casou. Sugere o que EXISTE:
    // categorias com conteúdo levam a resultado garantido, ao contrário de um
    // "você quis dizer" adivinhado que também não acharia nada.
    motivo.textContent = indexados
        ? `Há ${indexados} ${indexados === 1 ? 'arquivo analisado' : 'arquivos analisados'}, ` +
          'mas nenhum corresponde a essa descrição. Tente palavras mais gerais — ' +
          'a busca entende o significado, não o nome do arquivo.'
        : 'Tente palavras mais gerais — a busca entende o significado da imagem, ' +
          'não o nome do arquivo.';

    if (categorias.length > 0) {
        box.appendChild(_secaoSugestoes(
            'Talvez você queira dizer:',
            categorias.slice(0, 6).map(c => {
                const meta = _CAT_GALERIA[c.categoria] || { icone: 'pasta', nome: c.categoria };
                return { icone: meta.icone, rotulo: meta.nome, badge: c.total, termo: meta.nome };
            })));
    }

    const recentes = (_historicoCache || []).filter(q => q.toLowerCase() !== consulta.toLowerCase());
    if (recentes.length > 0) {
        box.appendChild(_secaoSugestoes(
            'Ou uma busca recente:',
            recentes.slice(0, 5).map(q => ({ rotulo: q, termo: q }))));
    }
}

function _secaoSugestoes(titulo, itens) {
    const sec = document.createElement('div');
    sec.className = 'vazio-secao';
    const h = document.createElement('p');
    h.className = 'vazio-secao-titulo';
    h.textContent = titulo;
    const lista = document.createElement('div');
    lista.className = 'vazio-chips';
    itens.forEach(it => {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'vazio-chip';
        if (it.icone) {
            chip.classList.add('tem-icone');
            chip.append(icone(it.icone), document.createTextNode(it.rotulo));
        } else {
            chip.textContent = it.rotulo;
        }
        if (it.badge != null) {
            const b = document.createElement('span');
            b.className = 'vazio-chip-badge';
            b.textContent = it.badge;
            chip.appendChild(b);
        }
        chip.onclick = () => {
            document.getElementById('searchInput').value = it.termo;
            atualizarBotaoLimpar();
            realizarBusca();
        };
        lista.appendChild(chip);
    });
    sec.append(h, lista);
    return sec;
}

function _botaoVazio(rotulo, aoClicar) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'action-btn gradient-btn';
    b.style.marginTop = '18px';
    b.textContent = rotulo;
    b.onclick = aoClicar;
    return b;
}

// ==========================================
// INSPEÇÃO RÁPIDA (preview no hover)
// ==========================================
let _hoverTimer = null;

function mostrarHoverPreview(ev, idx) {
    const r = window.resultadosAtuais[idx];
    if (!r) return;
    const ext = (r.tipo || '').toLowerCase();
    const box = document.getElementById('hoverPreview');
    const img = document.getElementById('hoverPreviewImg');
    const doc = document.getElementById('hoverPreviewDoc');

    // Pequeno atraso pra não piscar ao passar rápido
    clearTimeout(_hoverTimer);
    _hoverTimer = setTimeout(() => {
        if (extensoesImagem.includes(ext)) {
            img.src = formatImagePath(r.caminho);
            img.alt = textoAlternativo(r);
            img.style.display = 'block';
            doc.style.display = 'none';
        } else {
            // Documento / mídia: mostra nome + trecho da descrição
            img.style.display = 'none';
            doc.style.display = 'block';
            document.getElementById('hoverPreviewNome').textContent = r.nome;
            const txt = (r.descricao_ia || r.trecho || 'Sem descrição disponível.').slice(0, 300);
            document.getElementById('hoverPreviewTexto').textContent = txt;
        }
        box.style.display = 'block';
        moverHoverPreview(ev);
    }, 250);
}

function moverHoverPreview(ev) {
    const box = document.getElementById('hoverPreview');
    if (box.style.display === 'none') return;
    // Posiciona perto do cursor, evitando sair da tela
    const margem = 18;
    const w = box.offsetWidth || 280;
    const h = box.offsetHeight || 220;
    let x = ev.clientX + margem;
    let y = ev.clientY + margem;
    if (x + w > window.innerWidth)  x = ev.clientX - w - margem;
    if (y + h > window.innerHeight) y = ev.clientY - h - margem;
    box.style.left = Math.max(8, x) + 'px';
    box.style.top  = Math.max(8, y) + 'px';
}

function esconderHoverPreview() {
    clearTimeout(_hoverTimer);
    const box = document.getElementById('hoverPreview');
    box.style.display = 'none';
    document.getElementById('hoverPreviewImg').src = '';
}

function abrirPainelLateral(id) {
    const res = window.resultadosAtuais[id];
    const q = document.getElementById('searchInput').value.trim().toLowerCase();

    _caminhoArquivoAtual = res.caminho;
    _fileIdAtual = res.id;

    document.getElementById('sideTitle').innerText = res.nome;
    document.getElementById('sideBadgeType').innerText = res.tipo.toUpperCase();
    // Score escondido do usuário — informação técnica, não interessa pra quem busca.
    const _sbScore = document.getElementById('sideBadgeScore');
    if (_sbScore) _sbScore.style.display = 'none';
    document.getElementById('sideDownloadBtn').href = formatImagePath(res.caminho);

    const ext = res.tipo.toLowerCase(); const link = formatImagePath(res.caminho);
    const mediaBox = document.getElementById('sideMediaPreview');
    if (extensoesVideo.includes(ext)) mediaBox.innerHTML = `<video controls autoplay><source src="${link}"></video>`;
    else if (extensoesAudio.includes(ext)) mediaBox.innerHTML = `<audio controls autoplay><source src="${link}"></audio>`;
    else if (extensoesImagem.includes(ext)) mediaBox.innerHTML = `<img src="${link}" alt="${_attr(textoAlternativo(res))}">`;
    else mediaBox.innerHTML = `<div class="document-icon-wrapper" style="width:100%; height:100%;"><svg viewBox='0 0 24 24'><path d='M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2h12c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z'/></svg></div>`;

    let txt = res.conteudo || res.trecho || "Nenhum conteúdo legível.";
    if (q && txt !== "Nenhum conteúdo legível.") {
        const reg = new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
        txt = txt.replace(reg, '<span class="highlight">$1</span>');
    }
    document.getElementById('sideText').innerHTML = txt;

    document.getElementById('sidePanel').classList.add('open');
    document.getElementById('mainContentArea').classList.add('shifted');
}

function fecharPainelLateral() {
    document.getElementById('sidePanel').classList.remove('open');
    document.getElementById('mainContentArea').classList.remove('shifted');
    document.getElementById('sideMediaPreview').innerHTML = '';
}

window.onclick = function (e) {
    if (e.target.closest('.modal') && !e.target.closest('.modal-content') && !e.target.closest('.fav-modal-content')) {
        e.target.closest('.modal').style.display = 'none';
        if (cropper) { cropper.destroy(); cropper = null; }
    }
}

// ---------------------------------------------------
// SISTEMA DE FAVORITOS
// ---------------------------------------------------

function abrirFavoritos() {
    document.getElementById('modalFavoritos').style.display = 'flex';
    carregarFavoritos();
}

function fecharFavoritos() {
    document.getElementById('modalFavoritos').style.display = 'none';
}

async function carregarFavoritos() {
    const list = document.getElementById('favoritosList');
    list.innerHTML = '<p style="text-align:center; color: var(--text-secondary);">Carregando favoritos...</p>';

    try {
        const res = await fetch(`${API_BASE_URL}/api/favorites`, { headers: fetchOptions.headers });
        const dados = await res.json();

        // Guardados para o "selecionar todos" saber sobre o que age.
        window._favoritosCarregados = dados.resultados || [];
        atualizarAcoesFavoritos();

        if (dados.resultados && dados.resultados.length > 0) {
            list.innerHTML = '';
            dados.resultados.forEach(r => {
                const ext = r.tipo.toLowerCase();
                let iconText = "";
                if (extensoesVideo.includes(ext)) iconText = iconeHTML('video', 'ic--g');
                else if (extensoesAudio.includes(ext)) iconText = iconeHTML('musica', 'ic--g');
                else if (extensoesImagem.includes(ext)) iconText = "";

                let thumbHtml = `<div class="fav-thumb" style="display:flex; align-items:center; justify-content:center; font-size:1.5rem;">${iconText}</div>`;
                if (extensoesImagem.includes(ext)) {
                    thumbHtml = `<img src="${formatImagePath(r.caminho)}" class="fav-thumb" alt="${_attr(textoAlternativo(r))}">`;
                }

                const dataAdd = r.data ? new Date(r.data).toLocaleDateString('pt-BR') : "Desconhecido";

                const marcado = _selecionados.has(r.id);
                const card = `
                <div class="fav-card${marcado ? ' card-selecionado' : ''}" id="favCard_${r.id}" data-file-id="${r.id}">
                    <button type="button" class="btn-sel-fav${marcado ? ' is-sel' : ''}"
                            role="checkbox" aria-checked="${marcado}"
                            aria-label="Selecionar para coleção" title="Selecionar para coleção"
                            onclick="alternarSelecao(event, ${r.id}, this)">${marcado ? iconeHTML('check') : ''}</button>
                    ${thumbHtml}
                    <div class="fav-info">
                        <strong>${r.nome}</strong>
                        <span>${ext.toUpperCase()}</span>
                        <span>Adicionado: ${dataAdd}</span>
                    </div>
                    <div class="fav-actions">
                        <button type="button" class="btn-fav-icon" aria-label="Remover dos favoritos" title="Remover dos favoritos" onclick="toggleFavorito(event, ${r.id}, null, true)">${iconeFavHTML(true)}</button>
                    </div>
                </div>`;
                list.innerHTML += card;
            });
        } else {
            list.innerHTML = '<p style="text-align:center; color: var(--text-secondary);">Nenhum favorito ainda.</p>';
        }
    } catch (e) {
        list.innerHTML = '<p style="text-align:center; color: red;">Erro ao carregar favoritos.</p>';
    }
}

// Coração vazado x preenchido -- ver iconeFav() no topo do arquivo.
// com cor própria e ignora `color`, então a regra `.is-fav` não conseguia
// pintá-lo. O favoritado chegava a renderizar string vazia — um círculo em
// branco, sem indicação nenhuma de que estava favoritado.
const ICONE_FAV = { sim: true, nao: false };   // mantido só por compatibilidade

function aplicarEstadoFavorito(btn, isFav) {
    if (!btn) return;
    btn.classList.toggle('is-fav', !!isFav);
    btn.replaceChildren(iconeFav(isFav));
    btn.setAttribute('aria-pressed', isFav ? 'true' : 'false');
    const rotulo = isFav ? 'Remover dos favoritos' : 'Favoritar';
    btn.setAttribute('aria-label', rotulo);
    btn.title = rotulo;
}

async function toggleFavorito(event, id, btnElement, fromModal = false) {
    event.stopPropagation();
    try {
        const res = await fetch(`${API_BASE_URL}/api/favorites/toggle`, {
            method: 'POST',
            headers: fetchOptions.headers,
            body: JSON.stringify({ id: id })
        });
        const dados = await res.json();

        if (dados.status === 'sucesso') {
            const isFav = dados.favorito;

            if (window.resultadosAtuais) {
                window.resultadosAtuais.forEach(r => {
                    if (r.id === id) r.favorito = isFav;
                });
            }

            // A galeria da home guarda seus próprios itens. Sem atualizar
            // aqui, a estrela voltaria ao estado antigo assim que a galeria
            // fosse redesenhada — ao trocar o filtro de pastas, por exemplo.
            Object.values(window._galeriaGrupos || {}).forEach(itens => {
                itens.forEach(r => { if (r.id === id) r.favorito = isFav; });
            });

            if (btnElement) aplicarEstadoFavorito(btnElement, isFav);

            // A mesma imagem pode estar em duas categorias ao mesmo tempo (um
            // desenho de cachorro entra em Animais e em Desenhos), e cada uma
            // desenha o seu botão. Atualizar só o clicado deixaria a mesma
            // foto com estrela cheia num lugar e vazia no outro.
            document.querySelectorAll(`.recent-card[data-file-id="${id}"] .btn-fav-abs`)
                .forEach(b => { if (b !== btnElement) aplicarEstadoFavorito(b, isFav); });

            if (fromModal && !isFav) {
                const card = document.getElementById(`favCard_${id}`);
                if (card) card.remove();

                const list = document.getElementById('favoritosList');
                if (list && !list.innerHTML.trim().includes('fav-card')) {
                    list.innerHTML = '<p style="text-align:center; color: var(--text-secondary);">Nenhum favorito ainda.</p>';
                }

                carregarFavoritosDash();
            }

            if (document.getElementById('searchResultsView').style.display === 'block') {
                renderizarResultados();
            }
        }
    } catch (e) {
        console.error(e); toastErro("Não foi possível favoritar.");
    }
}

async function carregarFavoritosDash() {
    try {
        const res = await fetch(`${API_BASE_URL}/api/favorites`, { headers: fetchOptions.headers });
        const dados = await res.json();

        const grid = document.getElementById('recentFavsDash');
        const title = document.getElementById('favDashTitle');
        if (!grid) return;

        grid.innerHTML = '';

        if (dados.resultados && dados.resultados.length > 0) {
            title.style.display = 'block';

            const topFavs = dados.resultados.slice(0, 8);

            topFavs.forEach(r => {
                const ext = r.tipo.toLowerCase();
                let iconText = "";
                if (extensoesVideo.includes(ext)) iconText = iconeHTML('video', 'ic--gg');
                else if (extensoesAudio.includes(ext)) iconText = iconeHTML('musica', 'ic--gg');
                else if (extensoesImagem.includes(ext)) iconText = "";

                let midia = `<div class="recent-img" style="font-size:3rem; background:transparent;">${iconText}</div>`;
                if (extensoesImagem.includes(ext)) {
                    midia = `<div class="recent-img"><img src="${formatImagePath(r.caminho)}" alt="${_attr(textoAlternativo(r))}"></div>`;
                }

                const cardBox = `<div class="recent-card" onclick="abrirFavoritos()" id="favDash_${r.id}">
                    <div style="position:relative; width:100%; height:100%; pointer-events: none;">
                        ${midia}
                    </div>
                    <p style="pointer-events: auto;">${r.nome}</p>
                    <button type="button" class="btn-fav-abs is-fav" aria-pressed="true" aria-label="Remover dos favoritos" title="Remover dos favoritos" onclick="event.stopPropagation(); toggleFavorito(event, ${r.id}, this, true)" style="top:5px; right:5px; width:30px; height:30px; pointer-events: auto;">${iconeFavHTML(true)}</button>
                </div>`;

                grid.innerHTML += cardBox;
            });
        } else {
            title.style.display = 'none';
        }
    } catch (e) { }
}

// ==========================================
// GALERIA AGRUPADA POR CATEGORIA (home)
// ==========================================
const _CAT_GALERIA = {
    pessoas:  { icone: 'pessoas',  nome: 'Pessoas' },
    animais:  { icone: 'animais',  nome: 'Animais' },
    comida:   { icone: 'comida',   nome: 'Comida' },
    natureza: { icone: 'natureza', nome: 'Natureza' },
    urbano:   { icone: 'urbano',   nome: 'Urbano' },
    desenhos: { icone: 'paleta',   nome: 'Desenhos e Arte' },
    outras:   { icone: 'caixa',    nome: 'Outras' },
};

// ==========================================
// QUAIS PASTAS A HOME ESTÁ MOSTRANDO
// ==========================================
function desenharSeletorDePastas(pastas) {
    const caixa = document.getElementById('seletorPastas');
    if (!caixa) return;

    // Com uma pasta só não há o que escolher, e o botão viraria decoração.
    if (!pastas || pastas.length < 2) {
        caixa.style.display = 'none';
        return;
    }
    caixa.style.display = 'block';
    window._pastasDaGaleria = pastas;

    const btn = document.getElementById('seletorPastasBotao');
    if (!Array.isArray(_pastasVisiveis)) {
        rotularCom(btn, 'pasta', `Todas as pastas (${pastas.length})`);
    } else if (_pastasVisiveis.length === 0) {
        rotularCom(btn, 'pasta', 'Nenhuma pasta');
    } else if (_pastasVisiveis.length === pastas.length) {
        rotularCom(btn, 'pasta', `Todas as pastas (${pastas.length})`);
    } else {
        rotularCom(btn, 'pasta', `${_pastasVisiveis.length} de ${pastas.length} pastas`);
    }
    btn.setAttribute('aria-expanded', 'false');
}

function alternarSeletorDePastas() {
    const menu = document.getElementById('seletorPastasMenu');
    const btn = document.getElementById('seletorPastasBotao');
    const abrindo = menu.style.display !== 'block';

    if (!abrindo) {
        menu.style.display = 'none';
        btn.setAttribute('aria-expanded', 'false');
        return;
    }

    const pastas = window._pastasDaGaleria || [];
    menu.innerHTML = '';

    pastas.forEach(p => {
        // `null` (nunca escolheu) marca todas; `[]` (escolheu zero) marca nenhuma.
        const marcada = !Array.isArray(_pastasVisiveis)
            || _pastasVisiveis.includes(p.id);

        const linha = document.createElement('label');
        linha.className = 'pasta-opcao';

        const cx = document.createElement('input');
        cx.type = 'checkbox';
        cx.checked = marcada;
        cx.onchange = () => escolherPastaDaGaleria(p.id, cx.checked);

        const nome = document.createElement('span');
        nome.className = 'pasta-opcao-nome';
        nome.textContent = p.nome;
        nome.title = p.caminho;

        const qtd = document.createElement('span');
        qtd.className = 'pasta-opcao-qtd';
        qtd.textContent = `${p.imagens} ${p.imagens === 1 ? 'imagem' : 'imagens'}`;

        linha.append(cx, nome, qtd);
        menu.appendChild(linha);
    });

    const todas = document.createElement('button');
    todas.type = 'button';
    todas.className = 'pasta-opcao-todas';
    todas.textContent = 'Mostrar todas';
    todas.onclick = async () => {
        _pastasVisiveis = null;         // volta a "todas"
        fecharSeletorDePastas();
        await salvarPastasVisiveis();
        carregarGaleria();
    };
    menu.appendChild(todas);

    // Desmarcar quatro pastas uma a uma para limpar a home é trabalho que o
    // botão poupa — e é o pedido que motivou esta correção.
    const nenhuma = document.createElement('button');
    nenhuma.type = 'button';
    nenhuma.className = 'pasta-opcao-todas';
    nenhuma.textContent = 'Não mostrar nenhuma';
    nenhuma.onclick = async () => {
        _pastasVisiveis = [];
        fecharSeletorDePastas();
        await salvarPastasVisiveis();
        carregarGaleria();
    };
    menu.appendChild(nenhuma);

    menu.style.display = 'block';
    btn.setAttribute('aria-expanded', 'true');

    // Clicar fora fecha. Sem isto o único jeito de sair do menu sem escolher
    // nada seria clicar de novo no botão, que fica atrás dele.
    setTimeout(() => {
        document.addEventListener('click', function foraDoMenu(ev) {
            if (menu.contains(ev.target) || btn.contains(ev.target)) return;
            document.removeEventListener('click', foraDoMenu);
            fecharSeletorDePastas();
        });
    }, 0);
}

async function escolherPastaDaGaleria(pastaId, marcada) {
    const pastas = window._pastasDaGaleria || [];

    // `null` significa "nunca escolheu, mostra todas". Ao mexer na primeira
    // caixa, materializa a lista completa antes de tirar uma — senão desmarcar
    // uma pasta não mudaria nada.
    if (!Array.isArray(_pastasVisiveis)) _pastasVisiveis = pastas.map(p => p.id);

    if (marcada) {
        if (!_pastasVisiveis.includes(pastaId)) _pastasVisiveis.push(pastaId);
    } else {
        _pastasVisiveis = _pastasVisiveis.filter(id => id !== pastaId);
    }

    // Zero pastas continua sendo zero pastas. A versão anterior voltava para
    // "todas" aqui, achando que esconder a home seria pior — mas quem desmarca
    // tudo quer justamente a home limpa, para usar só a busca.
    //
    // Marcar todas também continua sendo uma escolha explícita, e não vira
    // `null`: o rótulo do botão já diz "Todas as pastas", e reescrever o
    // estado só criaria uma diferença invisível entre dois cliques iguais.

    // Fecha ao escolher. Um menu que fica aberto por cima do resultado esconde
    // justamente a mudança que a pessoa acabou de pedir para ver.
    fecharSeletorDePastas();

    await salvarPastasVisiveis();
    carregarGaleria();
}

function fecharSeletorDePastas() {
    const menu = document.getElementById('seletorPastasMenu');
    const btn = document.getElementById('seletorPastasBotao');
    if (menu) menu.style.display = 'none';
    if (btn) btn.setAttribute('aria-expanded', 'false');
}

async function salvarPastasVisiveis() {
    // A escolha vive na conta, não no navegador: quem separou as pastas de
    // trabalho das pessoais espera reencontrar isso amanhã.
    try {
        await fetch(`${API_BASE_URL}/api/config`, {
            method: 'POST', headers: fetchOptions.headers,
            body: JSON.stringify({ pastas_visiveis: _pastasVisiveis }),
        });
    } catch (e) { /* preferência de exibição: não vale um alarme na tela */ }
}

// Quais pastas a galeria está mostrando. TRÊS estados:
//
//     null    nunca escolheu  → mostra todas
//     []      escolheu zero   → mostra nenhuma
//     [1, 2]  escolheu essas
//
// A primeira versão usava lista vazia para "todas", e por isso desmarcar a
// última pasta voltava para "todas" — a escolha do usuário era simplesmente
// ignorada. Quem desmarca tudo quer a home limpa, para usar só a busca. A
// diferença entre "não escolhi" e "escolhi zero" precisa existir no dado, não
// só na cabeça de quem clicou.
let _pastasVisiveis = null;

// A home tem QUATRO motivos para estar vazia, e cada um pede uma frase e um
// botão diferentes. A versão anterior cobria dois, e — pior — condicionava a
// mensagem a `_pastasVisiveis` ser lista: quem nunca escolheu pasta nenhuma
// (`null`) caía fora de todos os casos e via a tela em branco, sem uma palavra.
//
// Isso acertava justamente quem acabou de instalar. A tela inicial é a
// primeira coisa que aparece depois do login, e não havia segunda chance de
// explicar o que o programa faz.
//
//   sem pasta importada    → nunca vai encher sozinha; oferece o caminho
//   pastas, mas nada pronto → a análise ainda está rodando; é só esperar
//   escolheu nenhuma        → escolha da pessoa; a home limpa é o que ela pediu
//   as escolhidas vazias    → filtrou demais; o seletor é o caminho de volta
function desenharHomeVazia(container, pastas) {
    const vazio = document.createElement('div');
    vazio.className = 'galeria-vazia';

    const frase = document.createElement('p');
    frase.className = 'galeria-vazia-frase';

    if (pastas.length === 0) {
        frase.textContent = 'O Search+ ainda não conhece suas imagens. '
            + 'Escolha uma pasta do computador para ele começar a analisar.';
        vazio.appendChild(frase);
        // O botão é metade do recado: sem ele, a frase diz o que fazer mas não
        // onde. É o único estado dos quatro em que a pessoa precisa agir.
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'action-btn gradient-btn galeria-vazia-acao';
        rotularCom(btn, 'pasta', 'Adicionar pasta');
        btn.onclick = () => {
            if (typeof abrirModalPastas === 'function') abrirModalPastas();
        };
        vazio.appendChild(btn);
    } else if (!Array.isArray(_pastasVisiveis)) {
        frase.textContent = 'Suas imagens estão sendo analisadas. '
            + 'As categorias aparecem aqui conforme ficam prontas.';
        vazio.appendChild(frase);
    } else if (_pastasVisiveis.length === 0) {
        frase.textContent = 'A home está limpa. Use a busca acima, '
            + 'ou escolha uma pasta para ver as categorias.';
        vazio.appendChild(frase);
    } else {
        frase.textContent = 'Nenhuma imagem nas pastas escolhidas.';
        vazio.appendChild(frase);
    }

    container.appendChild(vazio);
}

async function carregarGaleria() {
    const container = document.getElementById('galeriaCategorias');
    if (!container) return;
    try {
        let filtro = '';
        if (Array.isArray(_pastasVisiveis)) {
            filtro = _pastasVisiveis.length
                ? `?pastas=${_pastasVisiveis.join(',')}`
                : '?pastas=nenhuma';
        }
        const res = await fetch(`${API_BASE_URL}/api/gallery${filtro}`,
                                { headers: fetchOptions.headers });
        const d = await res.json();
        const grupos = d.grupos || [];

        desenharSeletorDePastas(d.pastas || []);

        container.innerHTML = '';
        if (grupos.length === 0) {
            desenharHomeVazia(container, d.pastas || []);
            return;
        }

        grupos.forEach(g => {
            const meta = _CAT_GALERIA[g.categoria] || { icone: 'pasta', nome: g.categoria };

            const secao = document.createElement('div');
            secao.style.cssText = 'margin-bottom: 32px;';

            const titulo = document.createElement('h3');
            titulo.style.cssText = 'color: var(--text-primary); margin: 0 0 14px 0; display:flex; align-items:center; gap:8px; justify-content:center;';
            rotularCom(titulo, meta.icone, meta.nome);
            const cont = document.createElement('span');
            cont.style.cssText = 'font-size:0.8rem; color:var(--text-secondary); font-weight:normal;';
            cont.textContent = `(${g.total})`;
            titulo.appendChild(cont);

            // Selecionar a categoria inteira. É o motivo de a pessoa estar
            // aqui em vez de na busca: ela já sabe que quer "todas as fotos de
            // animais", e marcar de uma em uma seria o trabalho que o
            // agrupamento existe para poupar.
            const btnCat = document.createElement('button');
            btnCat.type = 'button';
            btnCat.className = 'btn-sel-categoria';
            btnCat.dataset.categoria = g.categoria;
            btnCat.onclick = () => alternarSelecaoDaCategoria(g.categoria);
            titulo.appendChild(btnCat);

            secao.appendChild(titulo);

            const grid = document.createElement('div');
            grid.className = 'recent-grid';

            // Guarda os itens do grupo numa janela global pra reusar o painel lateral
            g.itens.forEach(r => {
                const card = document.createElement('div');
                card.className = 'recent-card';
                if (_selecionados.has(r.id)) card.classList.add('card-selecionado');
                card.dataset.fileId = r.id;
                card.onclick = () => abrirPainelGaleria(g.categoria, r.id);

                // Mesma caixa de seleção dos resultados de busca, e o mesmo
                // Set por trás. Quem navega por categoria em vez de buscar
                // precisa poder montar coleção do mesmo jeito.
                const sel = document.createElement('button');
                sel.type = 'button';
                sel.className = 'btn-sel-abs' + (_selecionados.has(r.id) ? ' is-sel' : '');
                sel.setAttribute('role', 'checkbox');
                sel.setAttribute('aria-checked', _selecionados.has(r.id) ? 'true' : 'false');
                sel.setAttribute('aria-label', 'Selecionar para coleção');
                sel.title = 'Selecionar para coleção';
                marcarBotaoSelecao(sel, _selecionados.has(r.id));
                sel.onclick = (ev) => alternarSelecao(ev, r.id, sel);
                card.appendChild(sel);

                // Favoritar sem precisar abrir a imagem. Quem navega por
                // categoria está justamente olhando muita coisa de uma vez —
                // ter de abrir cada uma para marcar a estrela desfaz a
                // vantagem de estar aqui em vez de na busca.
                const fav = document.createElement('button');
                fav.type = 'button';
                fav.className = 'btn-fav-abs' + (r.favorito ? ' is-fav' : '');
                fav.setAttribute('aria-pressed', r.favorito ? 'true' : 'false');
                fav.setAttribute('aria-label',
                    r.favorito ? 'Remover dos favoritos' : 'Favoritar');
                fav.title = fav.getAttribute('aria-label');
                fav.replaceChildren(iconeFav(r.favorito));
                fav.onclick = (ev) => toggleFavorito(ev, r.id, fav);
                card.appendChild(fav);

                const ext = (r.tipo || '').toLowerCase();
                const imgBox = document.createElement('div');
                imgBox.className = 'recent-img';
                if (extensoesImagem.includes(ext)) {
                    const img = document.createElement('img');
                    img.src = formatImagePath(r.caminho);
                    img.alt = textoAlternativo(r);
                    img.loading = 'lazy';
                    imgBox.appendChild(img);
                }
                const nm = document.createElement('p');
                nm.textContent = r.nome;
                card.append(imgBox, nm);
                grid.appendChild(card);
            });

            secao.appendChild(grid);
            container.appendChild(secao);
        });

        // Mapa categoria -> itens, pra abrir o painel lateral corretamente
        window._galeriaGrupos = {};
        grupos.forEach(g => { window._galeriaGrupos[g.categoria] = g.itens; });

        atualizarBotoesDeCategoria();
        atualizarBarraSelecao();
    } catch (e) { console.error(e); }
}

// ── Seleção por categoria ───────────────────────────────────────────────────
// O rótulo do botão diz o que o clique FAZ, não o estado atual: "Selecionar
// tudo" quando falta alguém, "Desmarcar" quando a categoria inteira já está
// marcada. Um botão que anuncia o estado deixa a pessoa sem saber o que
// acontece ao clicar.
function alternarSelecaoDaCategoria(categoria) {
    const itens = (window._galeriaGrupos || {})[categoria] || [];
    if (!itens.length) return;

    const todosMarcados = itens.every(r => _selecionados.has(r.id));
    itens.forEach(r => {
        if (todosMarcados) _selecionados.delete(r.id);
        else _selecionados.add(r.id);
    });

    sincronizarCardsDaGaleria();
    atualizarBotoesDeCategoria();
    _salvarSelecao();
    atualizarBarraSelecao();
}

function atualizarBotoesDeCategoria() {
    document.querySelectorAll('.btn-sel-categoria').forEach(btn => {
        const itens = (window._galeriaGrupos || {})[btn.dataset.categoria] || [];
        const todos = itens.length > 0 && itens.every(r => _selecionados.has(r.id));
        rotularCom(btn, todos ? 'desmarcar-tudo' : 'marcar-tudo',
               todos ? 'Desmarcar' : 'Selecionar tudo');
        btn.setAttribute('aria-pressed', todos ? 'true' : 'false');
        btn.setAttribute('aria-label', todos
            ? 'Desmarcar todas as imagens desta categoria'
            : 'Selecionar todas as imagens desta categoria');
    });
}

// A mesma imagem pode estar em mais de uma categoria (um desenho de cachorro
// entra em "Animais" e em "Desenhos"). Por isso a marcação é aplicada por
// file_id em toda a galeria, e não só nos cards da categoria clicada — senão
// a mesma foto apareceria marcada num lugar e desmarcada no outro.
function sincronizarCardsDaGaleria() {
    document.querySelectorAll('.recent-card[data-file-id]').forEach(card => {
        const id = Number(card.dataset.fileId);
        const marcado = _selecionados.has(id);
        card.classList.toggle('card-selecionado', marcado);
        const btn = card.querySelector('.btn-sel-abs');
        if (btn) {
            btn.classList.toggle('is-sel', marcado);
            marcarBotaoSelecao(btn, marcado);
            btn.setAttribute('aria-checked', marcado ? 'true' : 'false');
        }
    });
}

// Abre o painel lateral usando os itens da categoria como resultadosAtuais
function abrirPainelGaleria(categoria, fileId) {
    const itens = (window._galeriaGrupos || {})[categoria] || [];
    const idx = itens.findIndex(x => x.id === fileId);
    if (idx === -1) return;
    window.resultadosAtuais = itens;
    abrirPainelLateral(idx);
}

// Restaura a função de apertar Enter no teclado para buscar
function verificarEnter(e) {
    if (e.key === "Enter") realizarBusca();
}

// ==========================================
// LIMPAR O CAMPO DE BUSCA (botão ×)
// ==========================================
// O botão só existe enquanto há texto. Como atribuir .value por código não
// dispara o evento 'input', todo ponto que mexe no campo precisa passar por
// definirTextoBusca() — senão o botão dessincroniza do conteúdo.

function atualizarBotaoLimpar() {
    const campo = document.getElementById('searchInput');
    const btn   = document.getElementById('btnLimparBusca');
    if (!campo || !btn) return;
    // .length, não .trim(): com o campo só de espaços o botão precisa aparecer,
    // senão não há como apagá-los num clique.
    btn.classList.toggle('visivel', campo.value.length > 0);
}

// Escreve no campo e mantém o botão em sincronia. Use sempre esta função.
function definirTextoBusca(valor) {
    const campo = document.getElementById('searchInput');
    if (!campo) return;
    campo.value = valor;
    atualizarBotaoLimpar();
}

// Ação do botão ×: limpa o texto e devolve o foco. Não busca, não navega,
// não mexe nos resultados já na tela.
function limparCampoBusca() {
    definirTextoBusca('');
    const campo = document.getElementById('searchInput');
    if (campo) campo.focus();
}

// Função placeholder para limpar busca (usada no logout)
function limparBusca() {
    definirTextoBusca('');
    // Sem isto, o escopo de uma busca anterior sobreviveria à limpeza e a
    // busca seguinte viria misteriosamente reduzida.
    _limparRefino();
    if (typeof limparSelecao === 'function') limparSelecao();
    document.getElementById('searchResultsView').style.display = 'none';
    document.getElementById('filterBarContainer').style.display = 'none';
    document.getElementById('dashboardView').style.display = 'none';
    const wrapper = document.getElementById('mainAppWrapper');
    wrapper.classList.remove('layout-top');
    wrapper.classList.add('layout-centered');
    fecharPainelLateral();
}
// ==========================================
// INDEXAÇÃO INTELIGENTE SELETIVA
// ==========================================

function toggleChipFoco(el, ctx) {
    const foco = el.getAttribute('data-foco');
    const container = document.getElementById(ctx === 'ob' ? 'obChipsFoco' : 'modalChipsFoco');
    const chips = container.querySelectorAll('.chip-foco');
    const prioRef = ctx === 'ob' ? '_obPrioridades' : '_modalPrioridades';

    if (foco === 'tudo') {
        // Selecionar "tudo" desmarca os outros
        chips.forEach(c => c.classList.remove('active'));
        el.classList.add('active');
        if (ctx === 'ob') _obPrioridades = ['tudo'];
        else _modalPrioridades = ['tudo'];
    } else {
        // Desmarcar "tudo" ao selecionar específico
        chips.forEach(c => { if (c.getAttribute('data-foco') === 'tudo') c.classList.remove('active'); });
        el.classList.toggle('active');

        const selecionados = [];
        chips.forEach(c => { if (c.classList.contains('active')) selecionados.push(c.getAttribute('data-foco')); });

        if (selecionados.length === 0) {
            // Nada selecionado → volta para "tudo"
            chips.forEach(c => { if (c.getAttribute('data-foco') === 'tudo') c.classList.add('active'); });
            if (ctx === 'ob') _obPrioridades = ['tudo'];
            else _modalPrioridades = ['tudo'];
        } else {
            if (ctx === 'ob') _obPrioridades = selecionados;
            else _modalPrioridades = selecionados;
        }
    }

    // Atualiza estimativa
    if (ctx === 'modal' && _modalEditingFolderPath) {
        atualizarEstimativa(ctx, _modalEditingFolderPath);
    } else if (ctx === 'ob' && _obLastFolder) {
        atualizarEstimativa(ctx, _obLastFolder);
    }

    // Feedback: foco ativado/desativado
    const nomeFoco = el.textContent.trim();
    if (foco === 'tudo') {
        toastInfo(`Foco: ${nomeFoco}`);
    } else {
        toastInfo(`Foco "${nomeFoco}" ${el.classList.contains('active') ? 'ativado' : 'desativado'}`);
    }
}

function togglePerfil(ctx) {
    const toggle = document.getElementById(ctx + 'TogglePerfil');
    const labelFast = document.getElementById(ctx + 'LabelFast');
    const labelDeep = document.getElementById(ctx + 'LabelDeep');

    if (toggle.classList.contains('active')) {
        toggle.classList.remove('active');
        labelFast.classList.add('active-label');
        labelDeep.classList.remove('active-label');
        if (ctx === 'ob') _obPerfil = 'fast';
        else _modalPerfil = 'fast';
    } else {
        toggle.classList.add('active');
        labelFast.classList.remove('active-label');
        labelDeep.classList.add('active-label');
        if (ctx === 'ob') _obPerfil = 'deep';
        else _modalPerfil = 'deep';
    }

    // Atualiza estimativa se tiver pasta
    if (ctx === 'modal' && _modalEditingFolderPath) {
        atualizarEstimativa(ctx, _modalEditingFolderPath);
    } else if (ctx === 'ob' && _obLastFolder) {
        atualizarEstimativa(ctx, _obLastFolder);
    }

    // Feedback: perfil de análise selecionado
    const perfilAtivo = document.getElementById(ctx + 'TogglePerfil').classList.contains('active');
    toastInfo(`Modo de análise: ${perfilAtivo ? 'Profundo' : 'Relâmpago'}`);
}

function onJanelaChange(ctx) {
    const select = document.getElementById(ctx + 'JanelaSelect');
    const customDiv = document.getElementById(ctx + 'JanelaCustom');

    if (select.value === 'custom') {
        customDiv.style.display = 'flex';
    } else {
        customDiv.style.display = 'none';
        if (ctx === 'ob') _obJanela = select.value;
        else _modalJanela = select.value;
    }
}

function getJanelaValue(ctx) {
    const select = document.getElementById(ctx + 'JanelaSelect');
    if (select.value === 'custom') {
        const inicio = document.getElementById(ctx + 'JanelaInicio').value || '02:00';
        const fim = document.getElementById(ctx + 'JanelaFim').value || '06:00';
        return `${inicio}-${fim}`;
    }
    return select.value;
}

async function atualizarEstimativa(ctx, pasta) {
    const perfil = ctx === 'ob' ? _obPerfil : _modalPerfil;
    const prio = ctx === 'ob' ? _obPrioridades : _modalPrioridades;
    const focoStr = prio.join(',');
    
    const box = document.getElementById(ctx + 'Estimativa');
    if (!pasta || !box) return;

    try {
        const res = await fetch(`${API_BASE_URL}/api/estimate_time?pasta=${encodeURIComponent(pasta)}&perfil=${perfil}&foco=${focoStr}`);
        const data = await res.json();
        box.style.display = 'block';
        if (data.total_imagens === 0) {
            box.innerText = 'Nenhum arquivo suportado encontrado nesta pasta.';
        } else {
            box.innerText = `${data.total_imagens} arquivos · Tempo estimado: ~${data.estimativa_minutos} min (${perfil === 'deep' ? 'Profundo' : 'Relâmpago'})`;
        }
    } catch (e) {
        box.style.display = 'none';
    }
}

function abrirConfigPasta(folderId, folderPath) {
    _modalEditingFolderId = folderId;
    _modalEditingFolderPath = folderPath;
    const section = document.getElementById('folderConfigInline');
    section.style.display = 'block';
    document.getElementById('folderConfigName').innerText = folderPath.split('\\').pop() || folderPath;

    // Buscar config existente do cache
    const folder = _foldersData.find(f => (typeof f === 'object' ? f.id : 0) === folderId);
    const prio = folder ? (folder.prioridades || ['tudo']) : ['tudo'];
    const perfil = folder ? (folder.perfil_analise || 'fast') : 'fast';
    const janela = folder ? (folder.janela_processamento || 'always') : 'always';

    // Setar chips
    _modalPrioridades = [...prio];
    document.querySelectorAll('#modalChipsFoco .chip-foco').forEach(c => {
        c.classList.toggle('active', prio.includes(c.getAttribute('data-foco')));
    });

    // Setar perfil toggle
    _modalPerfil = perfil;
    const toggle = document.getElementById('modalTogglePerfil');
    if (perfil === 'deep') {
        toggle.classList.add('active');
        document.getElementById('modalLabelFast').classList.remove('active-label');
        document.getElementById('modalLabelDeep').classList.add('active-label');
    } else {
        toggle.classList.remove('active');
        document.getElementById('modalLabelFast').classList.add('active-label');
        document.getElementById('modalLabelDeep').classList.remove('active-label');
    }

    // Setar janela
    _modalJanela = janela;
    const select = document.getElementById('modalJanelaSelect');
    const customDiv = document.getElementById('modalJanelaCustom');
    if (janela === 'always' || janela === '02:00-06:00') {
        select.value = janela;
        customDiv.style.display = 'none';
    } else {
        select.value = 'custom';
        customDiv.style.display = 'flex';
        const parts = janela.split('-');
        if (parts.length === 2) {
            document.getElementById('modalJanelaInicio').value = parts[0];
            document.getElementById('modalJanelaFim').value = parts[1];
        }
    }

    atualizarEstimativa('modal', folderPath);
    section.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

async function salvarConfigPasta() {
    if (_modalEditingFolderId === null && !_modalEditingFolderPath) return;

    const janela = getJanelaValue('modal');
    try {
        const res = await fetch(`${API_BASE_URL}/api/folders/update_config?v=${Date.now()}`, {
            method: 'POST', headers: fetchOptions.headers,
            body: JSON.stringify({
                id: _modalEditingFolderId,
                path: _modalEditingFolderPath,
                prioridades: _modalPrioridades,
                perfil_analise: _modalPerfil,
                janela_processamento: janela
            })
        });
        const data = await res.json();
        if (data.pastas) atualizarListaModalPastas(data.pastas);
        document.getElementById('folderConfigInline').style.display = 'none';
    } catch (e) {
        console.error('Erro ao salvar config da pasta:', e);
    }
}

// STATUS BAR COM FEEDBACK DE CONCLUSÃO
let _ultimaFila = 0;  // pra detectar quando a análise termina

// A home acompanha a análise sozinha.
// ---------------------------------------------------------------------------
// Antes, quem adicionava uma pasta ficava olhando a barra de progresso andar
// com a home vazia atrás, e só via as fotos depois de recarregar a página na
// mão. O aviso de "análise concluída" existia, mas avisar sem mostrar é o pior
// dos dois mundos: a pessoa fica sabendo que terminou e continua sem ver nada.
//
// Redesenhar a galeria custa uma requisição e reconstrói o container inteiro,
// então não dá para fazer isso nas mesmas batidas de 2s da barra de status. As
// regras abaixo existem para atualizar quando ADIANTA e ficar quieto quando
// atrapalharia.
const _ESPERA_ENTRE_ATUALIZACOES = 8000;   // ms; a análise leva minutos
let _ultimaAtualizacaoDaHome = 0;

// A análise pode terminar enquanto a pessoa está numa janela ou lendo os
// resultados de uma busca. Nesse caso não dá para redesenhar na hora, mas a
// atualização não pode simplesmente se perder: ela fica devendo, e a próxima
// batida da barra de status paga assim que a home reaparecer.
//
// Voltar da busca já passa por mostrarHome(), que recarrega a galeria. Fechar
// uma janela, não — e era por aí que a home ficava velha sem ninguém notar.
let _homeDeveAtualizar = false;

// Redesenhar por baixo de uma janela aberta, ou enquanto a pessoa lê os
// resultados de uma busca, seria trabalho jogado fora no melhor caso e um
// susto no pior.
function _homeEstaAparecendo() {
    const dash = document.getElementById('dashboardView');
    if (!dash || dash.style.display === 'none') return false;
    const busca = document.getElementById('searchResultsView');
    if (busca && busca.style.display === 'block') return false;
    return _modaisAbertos().length === 0;
}

// `motivo` distingue os dois casos: 'fim' é a atualização que não pode faltar,
// e por isso ignora o intervalo; 'andamento' é a que deixa as fotos irem
// aparecendo, e respeita o intervalo para não redesenhar a cada 2 segundos.
async function atualizarHomeSeCabe(motivo) {
    if (!_homeEstaAparecendo()) {
        // Guarda a dívida só para o fim da análise. Uma atualização de
        // andamento perdida não faz falta: vem outra em seguida.
        if (motivo === 'fim') _homeDeveAtualizar = true;
        return false;
    }

    const agora = Date.now();
    if (motivo !== 'fim' && agora - _ultimaAtualizacaoDaHome < _ESPERA_ENTRE_ATUALIZACOES) {
        return false;
    }
    _ultimaAtualizacaoDaHome = agora;
    _homeDeveAtualizar = false;

    // A galeria é reconstruída do zero; sem guardar a rolagem, a página salta
    // para o topo no meio da leitura. A seleção não precisa disso — ela vive
    // num Set em memória e é redesenhada a partir dele.
    const rolagem = window.scrollY;
    await carregarGaleria();
    window.scrollTo({ top: rolagem, behavior: 'instant' });
    return true;
}


async function buscarStatus() {
    const b = document.getElementById('statusBar');
    try {
        const res = await fetch(`${API_BASE_URL}/api/status`);
        const s = await res.json();
        const pend = s.arquivos_pendentes || 0;

        // Detecta transição fila>0 -> fila=0: análise terminou.
        // Só notifica se as notificações estiverem ativadas nas configs.
        const terminou = (_ultimaFila > 0 && pend === 0);

        if (terminou && currentConfig.notificacoes !== false) {
            // Com o resumo a um clique: é o momento em que a pessoa está
            // olhando e a pergunta "entrou tudo?" está viva. Depois ela ainda
            // encontra o mesmo resumo nas Configurações.
            toastComAcao('Análise concluída! Os arquivos já podem ser buscados.',
                         'Ver resumo', abrirResumoIndexacao);
        }

        // Mostrar o resultado NÃO depende de as notificações estarem ligadas:
        // quem desligou o aviso não pediu para a home ficar desatualizada.
        if (terminou || _homeDeveAtualizar) {
            atualizarHomeSeCabe('fim');
        } else if (pend > 0 && pend !== _ultimaFila) {
            // `pend !== _ultimaFila` é o sinal de que alguma coisa andou desde
            // a última batida. Sem ele, uma fila parada (fora da janela de
            // horário, por exemplo) redesenharia a galeria à toa.
            atualizarHomeSeCabe('andamento');
        }

        _ultimaFila = pend;

        // Monta o texto do status
        let texto;
        let simbolo = '';       // id do icone que acompanha o texto
        if (pend > 0) {
            // "N na fila" não responde à pergunta que a pessoa tem: dá tempo
            // de almoçar? O tempo restante vem calibrado pelo ritmo que a
            // indexação está de fato conseguindo nesta máquina, e só aparece
            // quando o servidor tem medição suficiente para arriscar um número.
            const resta = s.restante_texto ? ` · ${s.restante_texto}` : '';
            simbolo = 'lupa';
            texto = `Analisando arquivos — ${pend} na fila${resta}`;
        } else if (s.status && s.status.startsWith('Aguardando janela')) {
            simbolo = 'relogio';
            texto = s.status;
        } else if (s.status && s.status.startsWith('Escaneando')) {
            simbolo = 'pasta-aberta';
            texto = s.status;
        } else {
            texto = "Motor pronto";
        }

        // Reconstrói a barra: texto (textContent, anti-XSS) + botão cancelar
        b.innerHTML = '';
        const span = document.createElement('span');
        if (simbolo) rotularCom(span, simbolo, texto, '');
        else span.textContent = texto;
        span.classList.toggle('tem-icone', !!simbolo);
        b.appendChild(span);

        if (pend > 0) {
            const btn = document.createElement('button');
            rotularCom(btn, 'x', 'Cancelar análise');
            btn.className = 'status-cancelar';
            btn.onclick = cancelarAnalise;
            b.appendChild(btn);
        }
        b.style.color = "var(--telemetry)";
    } catch (e) {
        rotularCom(b, 'alerta',
                   'Servidor desconectado — verifique se o backend está rodando.');
        b.style.color = "#ef4444";
    }
}

async function cancelarAnalise() {
    try {
        const res = await fetch(`${API_BASE_URL}/api/cancel_analysis`, { method: 'POST' });
        const d = await res.json();
        toastInfo(`Análise cancelada — ${d.descartados || 0} arquivo(s) removidos da fila.`);
        _ultimaFila = 0;
    } catch (e) {
        console.error(e);
        toastErro("Não foi possível cancelar a análise.");
    }
}
setInterval(buscarStatus, 2000);

// Helper de feedback pra toggles (checkboxes/switches): "X ativado/desativado"
function avisarToggle(nome, ativado) {
    toastInfo(`${nome} ${ativado ? 'ativado' : 'desativado'}`);
}

// ==========================================
// MENU LATERAL (navegação hamburguer)
// ==========================================
function abrirMenuLateral() {
    document.getElementById('menuLateral').classList.add('aberto');
    document.getElementById('menuOverlay').classList.add('aberto');
}
function fecharMenuLateral() {
    document.getElementById('menuLateral').classList.remove('aberto');
    document.getElementById('menuOverlay').classList.remove('aberto');
}

// ==========================================
// MODAL DE AJUDA
// ==========================================
function abrirAjuda() {
    document.getElementById('ajudaModal').style.display = 'flex';
}
function fecharAjuda() {
    document.getElementById('ajudaModal').style.display = 'none';
}

// ==========================================
// CONTRASTE DAS CORES ESCOLHIDAS
// ==========================================
// O tema é customizável, e nada impedia escolher amarelo claro sobre branco.
// O app ficava ilegível e a culpa parecia ser dele — a pessoa não tem como
// saber que o problema é a combinação, nem qual das duas cores mexer.
//
// A régua é a da WCAG: 4,5:1 para texto normal. Não é opinião de design, é o
// limite abaixo do qual parte das pessoas simplesmente não lê.
const CONTRASTE_MINIMO = 4.5;

function _hexParaRgb(hex) {
    const limpo = String(hex || '').replace('#', '').trim();
    const completo = limpo.length === 3
        ? limpo.split('').map(c => c + c).join('')
        : limpo;
    if (!/^[0-9a-fA-F]{6}$/.test(completo)) return null;
    return [
        parseInt(completo.slice(0, 2), 16),
        parseInt(completo.slice(2, 4), 16),
        parseInt(completo.slice(4, 6), 16),
    ];
}

// Luminância relativa da WCAG. A correção de gama (o expoente 2.4) existe
// porque o olho não enxerga o dobro de valor como o dobro de brilho — sem
// ela, cores escuras pareceriam ter muito mais contraste do que têm.
function _luminancia(rgb) {
    const [r, g, b] = rgb.map(v => {
        const c = v / 255;
        return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrasteEntre(corA, corB) {
    const a = _hexParaRgb(corA), b = _hexParaRgb(corB);
    if (!a || !b) return null;
    const la = _luminancia(a), lb = _luminancia(b);
    const claro = Math.max(la, lb), escuro = Math.min(la, lb);
    return (claro + 0.05) / (escuro + 0.05);
}

// A cor mais PRÓXIMA que passa, e não uma cor bonita qualquer: quem escolheu
// aquele tom queria aquele tom. Ajusta só o brilho, mantendo matiz e
// saturação, e caminha para o lado que aumenta o contraste.
function corMaisProximaQuePassa(cor, fundo, minimo = CONTRASTE_MINIMO) {
    const rgb = _hexParaRgb(cor), fundoRgb = _hexParaRgb(fundo);
    if (!rgb || !fundoRgb) return null;

    const hex = (v) => Math.round(Math.max(0, Math.min(255, v)))
        .toString(16).padStart(2, '0');

    // Tenta os DOIS sentidos e fica com o que resolve com menos mudança.
    // Escolher o sentido só pela luminância do fundo falha quando a cor já
    // está no extremo: branco sobre roxo médio não tem como clarear, e a
    // função devolvia "não dá" para um caso que escurecendo resolve.
    const candidatos = [];
    for (const paraEscuro of [true, false]) {
        for (let passo = 1; passo <= 100; passo++) {
            const fator = passo / 100;
            const ajustada = '#' + rgb.map(v => hex(
                paraEscuro ? v * (1 - fator) : v + (255 - v) * fator
            )).join('');
            if (contrasteEntre(ajustada, fundo) >= minimo) {
                candidatos.push({ cor: ajustada, distancia: passo });
                break;
            }
        }
    }
    if (candidatos.length) {
        candidatos.sort((a, b) => a.distancia - b.distancia);
        return candidatos[0].cor;
    }
    // Nem preto nem branco resolvem só quando o fundo é cinza médio — aí a
    // cor a mudar é a do fundo, e dizer isso é mais útil que devolver algo.
    return null;
}

// Fundo contra o qual cada cor será lida de verdade. Comparar contra a cor
// errada produziria um aviso que não corresponde ao que aparece na tela.
const _FUNDO_DE_LEITURA = {
    corPrimaria:    () => _corDeFundoDaTela(),
    corSecundaria:  () => _corDeFundoDaTela(),
    corTextoBotao:  () => document.getElementById('corPrimaria')?.value || '#A855F7',
    btnSearchTexto: () => document.getElementById('btnSearchCor')?.value || '#A855F7',
    btnTopbarTexto: () => document.getElementById('btnTopbarCor')?.value || '#151A2A',
};

function _corDeFundoDaTela() {
    const cs = getComputedStyle(document.body).backgroundColor;
    const m = cs.match(/\d+/g);
    if (!m) return '#0B0614';
    const hex = (v) => Number(v).toString(16).padStart(2, '0');
    return '#' + hex(m[0]) + hex(m[1]) + hex(m[2]);
}

function conferirContraste(campoId) {
    const campo = document.getElementById(campoId);
    if (!campo) return;

    const obterFundo = _FUNDO_DE_LEITURA[campoId];
    if (!obterFundo) return;

    const fundo = obterFundo();
    const razao = contrasteEntre(campo.value, fundo);
    let aviso = document.getElementById(`contraste-${campoId}`);

    if (razao === null || razao >= CONTRASTE_MINIMO) {
        if (aviso) aviso.remove();
        campo.removeAttribute('aria-describedby');
        return;
    }

    if (!aviso) {
        aviso = document.createElement('div');
        aviso.id = `contraste-${campoId}`;
        aviso.className = 'aviso-contraste';
        // `polite`: a pessoa está mexendo no seletor de cor, e interromper a
        // cada tom testado seria insuportável.
        aviso.setAttribute('role', 'status');
        aviso.setAttribute('aria-live', 'polite');
        campo.insertAdjacentElement('afterend', aviso);
        campo.setAttribute('aria-describedby', aviso.id);
    }

    aviso.innerHTML = '';
    const texto = document.createElement('span');
    texto.textContent = `Contraste baixo (${razao.toFixed(1)}:1). ` +
        `Abaixo de ${CONTRASTE_MINIMO}:1 fica difícil de ler.`;
    aviso.appendChild(texto);

    const sugerida = corMaisProximaQuePassa(campo.value, fundo);
    if (sugerida) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'aviso-contraste-usar';
        btn.style.background = sugerida;
        btn.textContent = `Usar ${sugerida.toUpperCase()}`;
        btn.setAttribute('aria-label', `Usar a cor ${sugerida} em vez desta`);
        btn.onclick = () => {
            campo.value = sugerida;
            campo.dispatchEvent(new Event('input', { bubbles: true }));
            campo.dispatchEvent(new Event('change', { bubbles: true }));
            conferirContraste(campoId);
        };
        aviso.appendChild(btn);
    } else {
        const nota = document.createElement('span');
        nota.textContent = ' Nenhum tom desta cor passa sobre este fundo — ' +
                           'mude a cor de fundo.';
        aviso.appendChild(nota);
    }
}

function vigiarContraste() {
    Object.keys(_FUNDO_DE_LEITURA).forEach(id => {
        const campo = document.getElementById(id);
        if (!campo) return;
        campo.addEventListener('input', () => conferirContraste(id));
        campo.addEventListener('change', () => conferirContraste(id));
        conferirContraste(id);      // avisa também sobre o que já estava salvo
    });
}

document.addEventListener('DOMContentLoaded', vigiarContraste);

// ==========================================
// ACESSIBILIDADE DOS MODAIS
// ==========================================
// O index.html tinha um único aria-label antes das features recentes, e nenhum
// dos 23 modais se anunciava como diálogo. Para quem usa leitor de tela, abrir
// um deles não dizia nada: o foco continuava na página atrás, e o Tab passeava
// por links que estavam visualmente cobertos.
//
// Tudo aqui é genérico, aplicado por observação do DOM. A alternativa seria
// marcar cada modal à mão — e foi assim que a lista fixa do Esc nasceu com 14
// dos 23 modais, deixando os outros nove sem tecla de fechar sem ninguém
// perceber.

let _focoAntesDoModal = new WeakMap();

function _modalEstaVisivel(el) {
    return el && getComputedStyle(el).display !== 'none';
}

// Do mais acima para o mais abaixo: com dois modais abertos, o Esc e o Tab
// pertencem ao de cima.
function _modaisAbertos() {
    return [...document.querySelectorAll('.modal')]
        .filter(_modalEstaVisivel)
        .sort((a, b) => (parseInt(getComputedStyle(b).zIndex, 10) || 0)
                      - (parseInt(getComputedStyle(a).zIndex, 10) || 0));
}

function _focaveis(container) {
    const seletor = 'a[href], button:not([disabled]), input:not([disabled]), ' +
                    'select:not([disabled]), textarea:not([disabled]), ' +
                    'details > summary, [tabindex]:not([tabindex="-1"])';
    return [...container.querySelectorAll(seletor)].filter(el => {
        // Elemento escondido dentro do modal não pode receber foco: o Tab
        // pararia num campo que ninguém vê.
        const cs = getComputedStyle(el);
        return cs.display !== 'none' && cs.visibility !== 'hidden' && el.offsetParent !== null;
    });
}

// Um modal que se anuncia como diálogo precisa dizer QUAL é. O título já está
// lá em todos eles; só falta amarrá-lo por id.
function _prepararModal(modal) {
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');

    if (!modal.getAttribute('aria-labelledby')) {
        const titulo = modal.querySelector('h1, h2, h3');
        if (titulo) {
            if (!titulo.id) titulo.id = `titulo-${modal.id || Math.random().toString(36).slice(2)}`;
            modal.setAttribute('aria-labelledby', titulo.id);
        }
    }

    // O X é um <span> em vários modais: sem role e tabindex, o teclado não
    // alcança o único jeito de fechar.
    modal.querySelectorAll('.close-btn').forEach(x => {
        if (x.tagName !== 'BUTTON') {
            x.setAttribute('role', 'button');
            if (!x.hasAttribute('tabindex')) x.setAttribute('tabindex', '0');
        }
        if (!x.getAttribute('aria-label')) x.setAttribute('aria-label', 'Fechar');
    });
}

function _aoAbrirModal(modal) {
    _prepararModal(modal);

    // Guarda quem abriu, para devolver o foco no fim. Sem isso o foco volta
    // para o começo da página e a pessoa refaz todo o caminho de navegação.
    const anterior = document.activeElement;
    if (anterior && anterior !== document.body) _focoAntesDoModal.set(modal, anterior);

    // Pula o X: começar o foco no botão de fechar é anunciar a saída antes do
    // conteúdo. Quando ele é o ÚNICO foco possível — modal ainda carregando,
    // ou só com texto —, o foco vai para o próprio diálogo, que faz o leitor
    // de tela ler o título em vez de dizer "Fechar".
    const alvos = _focaveis(modal).filter(el => !el.classList.contains('close-btn'));
    if (alvos.length) {
        alvos[0].focus();
    } else {
        modal.setAttribute('tabindex', '-1');
        modal.focus();
    }
}

function _aoFecharModal(modal) {
    const anterior = _focoAntesDoModal.get(modal);
    _focoAntesDoModal.delete(modal);
    if (anterior && document.body.contains(anterior)) {
        try { anterior.focus(); } catch (e) { }
    }
}

// Observa o `style` de cada modal: é assim que o app os abre e fecha. Detectar
// aqui evita ter de alterar as 23 funções de abrir — e evita que a 24ª nasça
// sem acessibilidade.
function _vigiarModais() {
    const observador = new MutationObserver(mudancas => {
        mudancas.forEach(m => {
            const modal = m.target;
            if (!modal.classList || !modal.classList.contains('modal')) return;
            const visivel = _modalEstaVisivel(modal);
            const estava = modal.dataset.aberto === '1';
            if (visivel && !estava) {
                modal.dataset.aberto = '1';
                _aoAbrirModal(modal);
            } else if (!visivel && estava) {
                modal.dataset.aberto = '0';
                _aoFecharModal(modal);
            }
        });
    });

    document.querySelectorAll('.modal').forEach(modal => {
        _prepararModal(modal);
        modal.dataset.aberto = _modalEstaVisivel(modal) ? '1' : '0';
        observador.observe(modal, { attributes: true, attributeFilter: ['style', 'class'] });
    });
}

// Fecha o modal de cima usando o botão que ELE já tem. Assim cada modal
// executa a própria rotina de fechar — que às vezes cancela uma promessa ou
// devolve um estado, e simplesmente esconder passaria por cima disso.
function fecharModalDeCima() {
    const [topo] = _modaisAbertos();
    if (!topo) return false;

    const x = topo.querySelector('.close-btn');
    if (x) { x.click(); return true; }
    topo.style.display = 'none';
    return true;
}

document.addEventListener('DOMContentLoaded', _vigiarModais);

// Prende o Tab dentro do modal de cima. Sem isso o foco escapa para a página
// atrás — que está visualmente coberta, então a pessoa navega às cegas.
document.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab') return;
    const [topo] = _modaisAbertos();
    if (!topo) return;

    const alvos = _focaveis(topo);
    if (!alvos.length) return;

    const primeiro = alvos[0];
    const ultimo = alvos[alvos.length - 1];

    if (!topo.contains(document.activeElement)) {
        e.preventDefault();
        primeiro.focus();
        return;
    }
    if (e.shiftKey && document.activeElement === primeiro) {
        e.preventDefault();
        ultimo.focus();
    } else if (!e.shiftKey && document.activeElement === ultimo) {
        e.preventDefault();
        primeiro.focus();
    }
});

// O X é <span> em vários modais; teclado precisa de Enter e Espaço.
document.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const alvo = e.target;
    if (alvo && alvo.classList && alvo.classList.contains('close-btn')
            && alvo.tagName !== 'BUTTON') {
        e.preventDefault();
        alvo.click();
    }
});

// ==========================================
// ATALHOS DE TECLADO
// ==========================================
// "/" foca a busca · "Esc" fecha janelas abertas
document.addEventListener('keydown', (e) => {
    // Esc: fecha o modal/painel aberto mais relevante
    if (e.key === 'Escape') {
        // Menu lateral aberto? fecha ele primeiro
        const ml = document.getElementById('menuLateral');
        if (ml && ml.classList.contains('aberto')) { fecharMenuLateral(); return; }

        // Qualquer modal aberto, sem lista para manter. A versão anterior
        // enumerava os modais um a um, e nasceu cobrindo 14 dos 23 — os outros
        // nove ficaram sem tecla de fechar, sem ninguém perceber.
        if (fecharModalDeCima()) return;

        return;
    }

    // "/" foca a barra de busca (se não estiver digitando em outro campo)
    if (e.key === '/' ) {
        const tag = (document.activeElement && document.activeElement.tagName) || '';
        if (tag !== 'INPUT' && tag !== 'TEXTAREA') {
            const busca = document.getElementById('searchInput');
            if (busca && getComputedStyle(busca).display !== 'none') {
                e.preventDefault();
                busca.focus();
            }
        }
    }
});

// ==========================================
// SELEÇÃO DE IMAGENS (para adicionar em lote a uma coleção)
// ==========================================
// Selecionar NÃO é favoritar. Favoritar é um julgamento sobre a imagem e mora
// no banco (files.favorito). Selecionar é um passo de fluxo de trabalho: vive
// só aqui, em memória, e some ao recarregar a página.

let _selecionados = new Set();   // file_id dos itens marcados

// ── A seleção sobrevive ao recarregamento, mas não ao fechar a aba ──────────
//
// Ela continua sendo um passo de trabalho, e não um estado guardado: por isso
// `sessionStorage` e não `localStorage`. Fechar a aba encerra o trabalho e
// limpa; um F5 acidental, ou o servidor reiniciando no meio, não.
//
// Quem montou uma seleção de 40 imagens e recarregou por engano perdia tudo e
// tinha de refazer clique a clique.
const _CHAVE_SELECAO = 'searchplus_selecao';

function _salvarSelecao() {
    try {
        sessionStorage.setItem(_CHAVE_SELECAO, JSON.stringify([..._selecionados]));
    } catch (e) { /* aba anônima ou storage cheio: a seleção só não persiste */ }
}

async function restaurarSelecao() {
    let guardados = [];
    try {
        guardados = JSON.parse(sessionStorage.getItem(_CHAVE_SELECAO) || '[]');
    } catch (e) { return; }
    if (!Array.isArray(guardados) || !guardados.length) return;

    // Entre um carregamento e outro o usuário pode ter removido uma pasta do
    // índice. Restaurar sem conferir faria a barra dizer "12 imagens
    // selecionadas" e a coleção receber 9 — e ninguém entenderia a diferença.
    try {
        const r = await fetch(`${API_BASE_URL}/api/files/validos`, {
            method: 'POST', headers: fetchOptions.headers,
            body: JSON.stringify({ ids: guardados }),
        });
        if (!r.ok) return;
        const vivos = (await r.json()).ids || [];

        _selecionados = new Set(vivos);
        _salvarSelecao();

        if (vivos.length < guardados.length) {
            const sumiram = guardados.length - vivos.length;
            toastInfo(`${sumiram} ${sumiram === 1 ? 'imagem que estava' : 'imagens que estavam'} ` +
                      `selecionada${sumiram === 1 ? '' : 's'} não ${sumiram === 1 ? 'está' : 'estão'} ` +
                      `mais na biblioteca.`);
        }
        atualizarBarraSelecao();
    } catch (e) { /* servidor fora do ar tem aviso próprio */ }
}

function alternarSelecao(event, fileId, btn) {
    event.stopPropagation();     // não abre o painel lateral
    // `.card` nos resultados de busca, `.recent-card` na galeria da home.
    const card = btn.closest('.card') || btn.closest('.recent-card');

    if (_selecionados.has(fileId)) {
        _selecionados.delete(fileId);
        btn.classList.remove('is-sel');
        marcarBotaoSelecao(btn, false);
        btn.setAttribute('aria-checked', 'false');
        if (card) card.classList.remove('card-selecionado');
    } else {
        _selecionados.add(fileId);
        btn.classList.add('is-sel');
        marcarBotaoSelecao(btn, true);
        btn.setAttribute('aria-checked', 'true');
        if (card) card.classList.add('card-selecionado');
    }
    // A mesma imagem pode estar em duas categorias da home ao mesmo tempo.
    if (typeof sincronizarCardsDaGaleria === 'function') sincronizarCardsDaGaleria();
    if (typeof atualizarBotoesDeCategoria === 'function') atualizarBotoesDeCategoria();
    if (typeof atualizarAcoesFavoritos === 'function') atualizarAcoesFavoritos();
    _salvarSelecao();
    atualizarBarraSelecao();
}

function atualizarBarraSelecao() {
    const barra = document.getElementById('barraSelecao');
    const cont  = document.getElementById('selecaoContador');
    if (!barra || !cont) return;

    const n = _selecionados.size;
    if (n === 0) {
        barra.classList.remove('visivel');
        atualizarAcoesResultados();
        return;
    }
    cont.textContent = `${n} ${n === 1 ? 'imagem selecionada' : 'imagens selecionadas'}`;
    barra.classList.add('visivel');
    atualizarAcoesResultados();
}

function limparSelecao() {
    _selecionados.clear();
    document.querySelectorAll('.btn-sel-abs.is-sel').forEach(b => {
        b.classList.remove('is-sel');
        b.textContent = '';
        b.setAttribute('aria-checked', 'false');
    });
    document.querySelectorAll('.card-selecionado').forEach(c => c.classList.remove('card-selecionado'));
    if (typeof atualizarBotoesDeCategoria === 'function') atualizarBotoesDeCategoria();
    if (typeof atualizarAcoesFavoritos === 'function') atualizarAcoesFavoritos();
    _salvarSelecao();
    atualizarBarraSelecao();
}

// ── Seleção em massa ────────────────────────────────────────────────────────
// "Tudo" é o que está na tela agora: os resultados da busca atual que passam
// pelo filtro ativo. Não é o acervo inteiro — a busca já devolve a lista
// completa de uma vez (não há paginação nem scroll infinito no /api/search),
// então "carregado" e "exibido" são a mesma coisa aqui.

function todosVisiveisSelecionados() {
    const vis = resultadosVisiveis();
    return vis.length > 0 && vis.every(r => _selecionados.has(r.id));
}

function alternarSelecionarTodos() {
    const vis = resultadosVisiveis();
    if (vis.length === 0) return;

    if (todosVisiveisSelecionados()) {
        // Desmarca só os visíveis — uma seleção feita sob outro filtro continua de pé.
        vis.forEach(r => _selecionados.delete(r.id));
    } else {
        vis.forEach(r => _selecionados.add(r.id));
    }

    sincronizarCardsComSelecao();
    _salvarSelecao();
    atualizarBarraSelecao();
}

// Reflete o Set no DOM sem reconstruir o grid: mexer no innerHTML aqui
// recriaria centenas de nós e descartaria o scroll do usuário.
function sincronizarCardsComSelecao() {
    document.querySelectorAll('.card[data-file-id]').forEach(card => {
        const id  = Number(card.getAttribute('data-file-id'));
        const btn = card.querySelector('.btn-sel-abs');
        const sel = _selecionados.has(id);
        card.classList.toggle('card-selecionado', sel);
        if (!btn) return;
        btn.classList.toggle('is-sel', sel);
        marcarBotaoSelecao(btn, sel);
        btn.setAttribute('aria-checked', sel ? 'true' : 'false');
    });
}

function atualizarAcoesResultados() {
    const acoes  = document.getElementById('resultadosAcoes');
    const resumo = document.getElementById('resultadosResumo');
    const btn    = document.getElementById('btnSelecionarTodos');
    if (!acoes || !resumo || !btn) return;

    const vis = resultadosVisiveis();
    if (vis.length === 0) { acoes.style.display = 'none'; return; }
    acoes.style.display = 'flex';

    const marcados = vis.filter(r => _selecionados.has(r.id)).length;
    resumo.textContent = marcados > 0
        ? `${vis.length} ${vis.length === 1 ? 'resultado' : 'resultados'} · ${marcados} ${marcados === 1 ? 'selecionada' : 'selecionadas'}`
        : `${vis.length} ${vis.length === 1 ? 'resultado' : 'resultados'}`;

    const todos = marcados === vis.length;
    rotularCom(btn, todos ? 'desmarcar-tudo' : 'marcar-tudo',
               todos ? 'Desmarcar tudo' : 'Selecionar tudo');
    btn.setAttribute('aria-pressed', todos ? 'true' : 'false');
    const rotulo = todos ? 'Desmarcar todas as imagens dos resultados'
                         : 'Selecionar todas as imagens dos resultados';
    btn.setAttribute('aria-label', rotulo);
    btn.title = rotulo;
    btn.classList.toggle('is-ativo', todos);
}

// ==========================================
// COLEÇÕES (playlists de arquivos)
// ==========================================
let _fileIdAtual = null;

async function abrirColecoes() {
    document.getElementById('colecoesModal').style.display = 'flex';
    document.getElementById('colecoesTitulo').innerText = 'Minhas Coleções';
    if (typeof cancelarRenomearColecao === 'function') cancelarRenomearColecao();
    const btnR = document.getElementById('btnRenomearColecao');
    if (btnR) btnR.style.display = 'none';
    document.getElementById('colecaoConteudo').style.display = 'none';
    document.getElementById('colecoesLista').style.display = 'grid';
    document.getElementById('colecoesCriar').style.display = 'flex';
    document.getElementById('colecoesOrdem').style.display = 'flex';
    await carregarColecoes();
}
function fecharColecoes() {
    document.getElementById('colecoesModal').style.display = 'none';
}

// Como as coleções aparecem ordenadas. Guardado entre recarregamentos porque
// é preferência de leitura, não um estado de trabalho.
let _ordemColecoes = localStorage.getItem('searchplus_ordem_colecoes') || 'recentes';

function trocarOrdemDasColecoes(valor) {
    _ordemColecoes = valor;
    try { localStorage.setItem('searchplus_ordem_colecoes', valor); } catch (e) { }
    carregarColecoes();
}

async function carregarColecoes() {
    const lista = document.getElementById('colecoesLista');
    lista.innerHTML = '<p style="color:var(--text-secondary);">Carregando...</p>';

    const seletor = document.getElementById('ordemColecoes');
    if (seletor) seletor.value = _ordemColecoes;

    try {
        const res = await fetch(`${API_BASE_URL}/api/collections?ordem=${encodeURIComponent(_ordemColecoes)}`);
        const d = await res.json();
        const cols = d.colecoes || [];
        if (cols.length === 0) {
            lista.innerHTML = '<p style="color:var(--text-secondary);">Nenhuma coleção ainda. Crie uma acima ou use "Adicionar à coleção" num resultado.</p>';
            return;
        }
        lista.innerHTML = '';
        cols.forEach(c => {
            const card = document.createElement('div');
            card.className = 'colecao-card';
            card.onclick = () => verColecao(c.id, c.nome);

            // Capa: mosaico das primeiras imagens (ou placeholder se vazia)
            const capa = document.createElement('div');
            capa.className = 'colecao-capa';
            const caps = c.capas || [];
            if (c.capa) {
                // Capa escolhida a dedo vence o mosaico. Se a imagem escolhida
                // sair da biblioteca, o backend devolve `capa` vazia e a
                // coleção volta ao mosaico sozinha.
                capa.classList.add('colecao-capa-unica');
                const img = document.createElement('img');
                img.src = formatImagePath(c.capa);
                img.alt = '';
                img.loading = 'lazy';
                capa.appendChild(img);
            } else if (caps.length === 0) {
                capa.classList.add('colecao-capa-vazia');
                capa.replaceChildren(icone('pasta', 'ic--gg'));
            } else {
                capa.classList.add(`mosaico-${Math.min(caps.length, 4)}`);
                caps.slice(0, 4).forEach(caminho => {
                    const img = document.createElement('img');
                    img.src = formatImagePath(caminho);
                    // Mosaico da capa é DECORATIVO: o nome e a contagem da
                    // coleção já são anunciados logo abaixo. alt="" faz o
                    // leitor de tela pular, em vez de ler quatro descrições
                    // que não ajudam a escolher a coleção.
                    img.alt = '';
                    img.loading = 'lazy';
                    capa.appendChild(img);
                });
            }

            const info = document.createElement('div');
            info.className = 'colecao-info';
            const titulo = document.createElement('div');
            titulo.className = 'colecao-card-nome';
            titulo.textContent = c.nome;
            const meta = document.createElement('div');
            meta.className = 'colecao-card-meta';
            meta.textContent = c.total + (c.total === 1 ? ' item' : ' itens');

            // Botão excluir flutuante no canto
            const delBtn = document.createElement('button');
            delBtn.className = 'colecao-del-flutuante';
            delBtn.replaceChildren(icone('lixeira'));
            delBtn.title = 'Excluir coleção';
            delBtn.onclick = (e) => { e.stopPropagation(); excluirColecao(c.id, c.nome); };

            info.append(titulo, meta);

            // Selo da pasta vinculada: o usuário precisa ver que a coleção
            // espelha algo no disco, e em que modo.
            if (c.pasta_vinculada) {
                const auto = c.modo_sync === 'auto';
                const selo = document.createElement('div');
                selo.className = 'colecao-vinculo' + (auto ? ' colecao-vinculo-auto' : '');
                rotularCom(selo, 'seta-canto',
                           (auto ? 'envia para ' : 'pasta: ') + _nomeDaPasta(c.pasta_vinculada));
                selo.title = c.pasta_vinculada;
                info.appendChild(selo);
            }
            card.append(capa, info, delBtn);
            lista.appendChild(card);
        });
    } catch (e) {
        console.error(e);
        lista.innerHTML = '<p style="color:#f87171;">Erro ao carregar coleções.</p>';
    }
}

async function criarColecao() {
    const input = document.getElementById('novaColecaoNome');
    const nome = input.value.trim();
    if (!nome) { toastAviso("Digite um nome para a coleção."); return; }
    try {
        const res = await fetch(`${API_BASE_URL}/api/collections`, {
            method: 'POST', headers: fetchOptions.headers,
            body: JSON.stringify({ nome })
        });
        const d = await res.json();
        if (res.ok) {
            input.value = '';
            toastOk(`Coleção "${nome}" criada.`);
            // Único momento em que se pergunta sobre pasta: na criação.
            await configurarPastaDaColecao(d.id, nome);
            carregarColecoes();
        } else {
            toastErro(d.error || "Não foi possível criar a coleção.");
        }
    } catch (e) { console.error(e); toastErro("Erro de conexão."); }
}

async function excluirColecao(id, nome) {
    if (!await confirmarAcao("Excluir coleção",
        `Excluir a coleção "${nome}"? As imagens originais não são apagadas.`,
        "Excluir")) return;

    // Etapa 2: se a coleção gerou pastas no disco, o usuário precisa VER quais
    // são e decidir uma a uma. Excluir a coleção não pode apagar pasta em
    // silêncio — e manter a pasta é uma escolha legítima, não um resto.
    let pastas = [];
    try {
        const r = await fetch(`${API_BASE_URL}/api/collections/${id}/folders`);
        if (r.ok) pastas = ((await r.json()).pastas || []).filter(p => p.existe);
    } catch (e) { console.error(e); }   // sem a lista, segue como antes

    if (pastas.length > 0) {
        const decisao = await perguntarSobrePastas(id, nome, pastas);
        if (decisao === 'cancelado') return;   // desistiu: coleção continua
    }

    try {
        const r = await fetch(`${API_BASE_URL}/api/collections/${id}`,
                              { method: 'DELETE', headers: fetchOptions.headers });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { toastErro(await _erroDaResposta(r, 'Não foi possível excluir')); return; }

        carregarColecoes();

        // As pastas no disco NÃO voltam com o desfazer — quem escolheu apagá-las
        // já confirmou isso em duas etapas, e ressuscitar arquivo apagado não é
        // algo que o app possa prometer. O desfazer traz a coleção e o vínculo.
        if (d.lixeira_id) {
            toastComDesfazer(`Coleção "${nome}" excluída.`,
                             () => desfazerExclusao(d.lixeira_id, carregarColecoes));
        } else {
            toastInfo(`Coleção "${nome}" excluída.`);
        }
    } catch (e) { console.error(e); toastErro("Não foi possível excluir."); }
}

// ── Diálogo de pastas geradas ──────────────────────────────────────────────
// Duas etapas: a primeira lista o que existe no disco e deixa marcar; a
// segunda cobra uma confirmação explícita, porque apagar não tem volta.
let _pastasCtx = null;

function perguntarSobrePastas(colId, nomeColecao, pastas) {
    return new Promise((resolve) => {
        _pastasCtx = { colId, nome: nomeColecao, pastas, resolve, confirmando: false };

        document.getElementById('pastasTitulo').textContent =
            pastas.length === 1 ? 'Excluir também a pasta?' : 'Excluir também as pastas?';
        document.getElementById('pastasTexto').textContent =
            `A coleção "${nomeColecao}" gerou ${pastas.length === 1 ? 'esta pasta' : `estas ${pastas.length} pastas`} ` +
            `no seu computador. Marque o que quiser apagar — o que ficar desmarcado permanece no disco.`;

        const lista = document.getElementById('pastasLista');
        lista.innerHTML = '';
        pastas.forEach((p, i) => {
            const item = document.createElement('label');
            item.className = 'pasta-item';

            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.dataset.idx = i;
            cb.setAttribute('aria-label', `Apagar a pasta ${p.nome}`);

            const info = document.createElement('div');
            info.className = 'pasta-item-info';

            const nome = document.createElement('span');
            nome.className = 'pasta-item-nome';
            nome.textContent = p.nome;
            if (p.vinculada) {
                const selo = document.createElement('span');
                selo.className = 'pasta-item-selo';
                selo.textContent = 'recebe novas';
                nome.appendChild(selo);
            }

            const caminho = document.createElement('span');
            caminho.className = 'pasta-item-caminho';
            caminho.textContent = p.caminho;

            const meta = document.createElement('span');
            meta.className = 'pasta-item-meta';
            meta.textContent = `${p.arquivos} ${p.arquivos === 1 ? 'arquivo' : 'arquivos'}`;

            info.append(nome, caminho, meta);
            item.append(cb, info);
            lista.appendChild(item);
        });

        document.getElementById('pastasAviso').style.display = 'none';
        document.getElementById('pastasApagar').textContent = 'Apagar selecionadas';
        document.getElementById('pastasColecaoModal').style.display = 'flex';
    });
}

function _pastasMarcadas() {
    return [...document.querySelectorAll('#pastasLista input[type="checkbox"]:checked')]
        .map(cb => _pastasCtx.pastas[Number(cb.dataset.idx)]);
}

async function confirmarExclusaoPastas(apagar) {
    if (!_pastasCtx) return;

    if (!apagar) {                       // "Manter as pastas"
        _fecharPastas('manteve');
        return;
    }

    const escolhidas = _pastasMarcadas();
    if (escolhidas.length === 0) {
        toastAviso('Marque ao menos uma pasta, ou escolha "Manter as pastas".');
        return;
    }

    // ETAPA 2 — o primeiro clique só avisa; o segundo executa.
    if (!_pastasCtx.confirmando) {
        _pastasCtx.confirmando = true;
        const aviso = document.getElementById('pastasAviso');
        const total = escolhidas.reduce((s, p) => s + p.arquivos, 0);
        aviso.textContent =
            `Isto apaga ${escolhidas.length === 1 ? 'a pasta' : `${escolhidas.length} pastas`} ` +
            `e ${total} ${total === 1 ? 'arquivo' : 'arquivos'} do seu computador, sem ir para a ` +
            `Lixeira. Os originais nas pastas do computador não são tocados. ` +
            `Clique novamente para confirmar.`;
        aviso.style.display = 'block';
        document.getElementById('pastasApagar').textContent = 'Confirmar exclusão';
        return;
    }

    const { colId, nome } = _pastasCtx;
    const caminhos = escolhidas.map(p => p.caminho);
    try {
        const r = await fetch(`${API_BASE_URL}/api/collections/${colId}/folders`, {
            method: 'DELETE', headers: fetchOptions.headers,
            body: JSON.stringify({ caminhos, confirmar: true })
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { toastErro(await _erroDaResposta(r, 'Não foi possível apagar as pastas.')); return; }

        const n = (d.apagadas || []).length;
        const falhas = (d.falhas || []).length;
        if (n > 0 && falhas === 0)      toastOk(`${n} ${n === 1 ? 'pasta apagada' : 'pastas apagadas'}.`);
        else if (n > 0)                 toastAviso(`${n} ${n === 1 ? 'apagada' : 'apagadas'} — ${falhas} não ${falhas === 1 ? 'pôde' : 'puderam'} ser apagada(s).`);
        else                            toastErro('Nenhuma pasta pôde ser apagada.');
    } catch (e) { console.error(e); toastErro('Erro de conexão.'); return; }

    _fecharPastas('apagou');
}

function _fecharPastas(resultado) {
    document.getElementById('pastasColecaoModal').style.display = 'none';
    const ctx = _pastasCtx;
    _pastasCtx = null;
    if (ctx) ctx.resolve(resultado);
}

function fecharPastasColecao() {
    // Cancelar aqui cancela a exclusão da COLEÇÃO também: o usuário voltou
    // atrás no meio de uma operação destrutiva.
    if (_pastasCtx) _fecharPastas('cancelado');
    else document.getElementById('pastasColecaoModal').style.display = 'none';
}

// O botão só existe se houver pasta de verdade no disco. Mostrar um "abrir
// pasta" que dá erro ao clicar é pior do que não mostrar nada.
async function atualizarBotaoAbrirPasta(colId) {
    const btn = document.getElementById('btnAbrirPastaColecao');
    if (!btn) return;
    btn.style.display = 'none';
    const stBtn = document.getElementById('btnStatusPasta');
    if (stBtn) stBtn.style.display = 'none';
    try {
        const r = await fetch(`${API_BASE_URL}/api/collections/${colId}/folders`);
        if (!r.ok) return;
        const pastas = ((await r.json()).pastas || []).filter(p => p.existe);
        if (pastas.length === 0) return;

        const alvo = pastas.find(p => p.vinculada) || pastas[0];
        btn.style.display = 'inline-block';
        const st = document.getElementById('btnStatusPasta');
        if (st) st.style.display = 'inline-block';
        rotularCom(btn, 'pasta-aberta', pastas.length > 1
            ? `Abrir pasta da coleção (${pastas.length})`
            : 'Abrir pasta da coleção');
        btn.title = `Abrir no Explorer: ${alvo.caminho}`;
    } catch (e) { console.error(e); }
}

// Lista as pastas exportadas e deixa o usuário escolher qual abrir — e qual
// recebe as próximas fotos. Com uma pasta só, abre direto: um modal de um item
// para escolher entre uma opção é burocracia.
async function abrirPastaDaColecao() {
    if (!_colecaoAtual.id) return;
    let pastas;
    try {
        const r = await fetch(`${API_BASE_URL}/api/collections/${_colecaoAtual.id}/folders`);
        if (!r.ok) { toastErro(await _erroDaResposta(r, 'Não foi possível localizar as pastas.')); return; }
        pastas = ((await r.json()).pastas || []).filter(p => p.existe);
    } catch (e) { console.error(e); toastErro('Erro de conexão.'); return; }

    if (pastas.length === 0) {
        toastAviso('Esta coleção ainda não tem pasta no computador. Use "Salvar no computador".');
        return;
    }
    if (pastas.length === 1) { await abrirPastaExportada(pastas[0].caminho); return; }

    renderizarPastasExportadas(pastas);
    document.getElementById('pastasExportadasModal').style.display = 'flex';
}

// O destino é um CONJUNTO: marcar várias espelha a coleção em todas, e
// desmarcar todas simplesmente para de enviar — sem perder as pastas já
// criadas. Daí caixas de marcação, e não escolha única.
let _pastasExpCache = [];

function renderizarPastasExportadas(pastas) {
    _pastasExpCache = pastas;
    const recebendo = pastas.filter(p => p.recebe);
    document.getElementById('pastasExpTexto').textContent =
        recebendo.length === 0
            ? 'Nenhuma pasta está recebendo as novas fotos. Marque quantas quiser — ou deixe todas desmarcadas para não enviar nada.'
        : recebendo.length === 1
            ? `As fotos que você adicionar a esta coleção vão para "${recebendo[0].nome}". Marque mais de uma para enviar a várias pastas.`
            : `As fotos vão para ${recebendo.length} pastas ao mesmo tempo: ${recebendo.map(p => `"${p.nome}"`).join(', ')}.`;

    const lista = document.getElementById('pastasExpLista');
    lista.innerHTML = '';
    pastas.forEach((p, i) => {
        const item = document.createElement('div');
        item.className = 'pasta-exp';

        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = !!p.recebe;
        cb.dataset.idx = i;
        cb.setAttribute('aria-label', `Enviar as novas fotos para ${p.nome}`);
        cb.title = 'Receber as novas fotos desta coleção';
        cb.onchange = () => aplicarPastasQueRecebem();

        const info = document.createElement('div');
        info.className = 'pasta-exp-info';
        const nome = document.createElement('span');
        nome.className = 'pasta-exp-nome';
        nome.textContent = p.nome;
        if (p.recebe) {
            const selo = document.createElement('span');
            selo.className = 'pasta-item-selo';
            selo.textContent = 'recebe as fotos';
            nome.appendChild(selo);
        }
        const caminho = document.createElement('span');
        caminho.className = 'pasta-exp-caminho';
        caminho.textContent = `${p.caminho} · ${p.arquivos} ${p.arquivos === 1 ? 'arquivo' : 'arquivos'}`;
        info.append(nome, caminho);

        const acoes = document.createElement('div');
        acoes.className = 'pasta-exp-acoes';

        const renomear = document.createElement('button');
        renomear.type = 'button';
        renomear.className = 'action-btn';
        renomear.style.background = 'transparent';
        renomear.replaceChildren(icone('lapis'));
        renomear.setAttribute('aria-label', `Mudar o complemento do nome de ${p.nome}`);
        renomear.title = 'Mudar o complemento do nome desta pasta';
        renomear.onclick = () => renomearSufixoDaPasta(p);
        acoes.appendChild(renomear);

        const abrir = document.createElement('button');
        abrir.className = 'action-btn gradient-btn';
        abrir.textContent = 'Abrir';
        abrir.onclick = () => { fecharPastasExportadas(); abrirPastaExportada(p.caminho); };
        acoes.appendChild(abrir);

        item.append(cb, info, acoes);
        lista.appendChild(item);
    });
    atualizarBotaoMarcarTodas();
}

// ── Renomear coleção ───────────────────────────────────────────────────────
// Edição no próprio cabeçalho: o nome já está ali, e abrir um modal para trocar
// uma palavra seria desproporcional. `_renomeando` evita que o `onblur` dispare
// uma segunda vez enquanto a primeira ainda está no ar.
let _renomeando = false;

function iniciarRenomearColecao() {
    if (!_colecaoAtual.id) return;
    const campo = document.getElementById('colecaoNomeEdit');
    const titulo = document.getElementById('colecoesTitulo');
    const botao = document.getElementById('btnRenomearColecao');

    campo.value = _colecaoAtual.nome;
    titulo.parentElement.style.display = 'none';
    campo.style.display = 'block';
    campo.focus();
    campo.select();
    if (botao) botao.style.display = 'none';
}

// Pergunta se as pastas exportadas devem acompanhar o novo nome, explicando
// o que muda e o que fica. Só aparece quando existe pasta no disco.
// Devolve true, false ou 'cancelado'.
async function _perguntarSobrePastasAoRenomear(novoNome) {
    let pastas = [];
    try {
        const r = await fetch(`${API_BASE_URL}/api/collections/${_colecaoAtual.id}/folders`);
        if (r.ok) pastas = ((await r.json()).pastas || []).filter(p => p.existe);
    } catch (e) { console.error(e); }

    if (pastas.length === 0) return false;      // nada no disco: nada a perguntar

    // Mostra o "de → para" real de cada pasta. Dizer "o prefixo muda" no
    // abstrato não deixa claro o que vai acontecer com "teste01_praia".
    const antigo = _colecaoAtual.nome;
    const exemplos = pastas.slice(0, 3).map(p => {
        const sufixo = p.nome.startsWith(antigo + '_') ? p.nome.slice(antigo.length + 1) : '';
        return `${p.nome} → ${sufixo ? `${novoNome}_${sufixo}` : novoNome}`;
    }).join('\n');

    const n = pastas.length;
    const ok = await confirmarAcao(
        'Renomear também as pastas?',
        `${n === 1 ? 'Esta coleção tem uma pasta' : `Esta coleção tem ${n} pastas`} no seu computador. ` +
        `O nome da coleção é o começo do nome ${n === 1 ? 'dela' : 'delas'} — o complemento que ` +
        `você escolheu não muda:\n\n${exemplos}${n > 3 ? `\n… e mais ${n - 3}` : ''}`,
        'Renomear as pastas', 'Manter os nomes atuais');

    return ok;
}

function cancelarRenomearColecao() {
    const campo = document.getElementById('colecaoNomeEdit');
    campo.value = '';                       // impede o onblur de tentar salvar
    _fecharEdicaoDeNome();
}

function _fecharEdicaoDeNome() {
    document.getElementById('colecaoNomeEdit').style.display = 'none';
    document.getElementById('colecoesTitulo').parentElement.style.display = 'flex';
    const botao = document.getElementById('btnRenomearColecao');
    if (botao) botao.style.display = 'inline-block';
}

async function confirmarRenomearColecao() {
    if (_renomeando) return;
    const campo = document.getElementById('colecaoNomeEdit');
    if (campo.style.display === 'none') return;

    const novo = campo.value.trim();
    if (!novo || novo === _colecaoAtual.nome) { _fecharEdicaoDeNome(); return; }

    _renomeando = true;
    try {
        // As pastas exportadas usam o nome da coleção como prefixo. Renomear a
        // coleção sem tocá-las deixa "teste01_praia" apontando para uma coleção
        // que agora se chama outra coisa — some a relação que o prefixo existia
        // para criar. Perguntar é obrigatório: renomear pasta no disco do
        // usuário sem avisar seria pior que a inconsistência.
        const renomearPastas = await _perguntarSobrePastasAoRenomear(novo);
        if (renomearPastas === 'cancelado') { campo.focus(); return; }

        const r = await fetch(`${API_BASE_URL}/api/collections/${_colecaoAtual.id}`, {
            method: 'PATCH', headers: fetchOptions.headers,
            body: JSON.stringify({ nome: novo, renomear_pastas: renomearPastas })
        });
        if (!r.ok) {
            // 409 traz o motivo real ("já tem uma coleção com esse nome"). Manter
            // o campo aberto deixa o usuário corrigir sem redigitar tudo.
            toastErro(await _erroDaResposta(r, 'Não foi possível renomear.'));
            campo.focus();
            return;
        }
        const d = await r.json();
        _colecaoAtual.nome = d.nome;
        document.getElementById('colecoesTitulo').textContent = d.nome;
        _fecharEdicaoDeNome();
        toastOk(`Coleção renomeada para "${d.nome}".`);

        const renom = d.pastas_renomeadas || [];
        const falhas = d.pastas_com_falha || [];
        if (renom.length) {
            toastOk(`${renom.length} ${renom.length === 1 ? 'pasta renomeada' : 'pastas renomeadas'} no computador.`);
        }
        const ignoradas = d.pastas_ignoradas || [];
        if (ignoradas.length) {
            // Silêncio aqui seria pior: o usuário aceitou renomear e veria
            // pastas com o nome antigo sem entender por quê. A mensagem aponta
            // a saída — o lápis da lista de pastas reescreve o nome inteiro,
            // usando o nome atual da coleção como prefixo.
            const n = ignoradas.length;
            toastAviso(
                `${n === 1 ? 'Uma pasta manteve o nome' : `${n} pastas mantiveram o nome`} ` +
                `(${ignoradas.join(', ')}): ${n === 1 ? 'ela não foi criada' : 'não foram criadas'} ` +
                `com o nome anterior da coleção. Use o lápis em "Abrir pasta da coleção" ` +
                `para renomear ${n === 1 ? 'essa pasta' : 'cada uma'}.`);
        }
        if (falhas.length) {
            // Motivo específico: "pasta aberta no Explorer" é acionável,
            // "erro ao renomear" não é.
            const motivos = { nome_em_uso: 'já existe pasta com esse nome',
                              sem_permissao: 'pasta em uso — feche-a no Explorer',
                              nao_encontrada: 'pasta não está mais no lugar' };
            const detalhe = falhas.map(f => `"${f.pasta}" (${motivos[f.motivo] || 'erro'})`).join('; ');
            toastAviso(`Não foi possível renomear: ${detalhe}. A coleção foi renomeada normalmente.`);
        }
        carregarColecoes();
        atualizarBotaoAbrirPasta(_colecaoAtual.id);
    } catch (e) { console.error(e); toastErro('Erro de conexão.'); }
    finally { _renomeando = false; }
}

// ── Status da pasta: o que já foi copiado e o que falta ────────────────────
// Responde a pergunta que o modo manual deixa em aberto. Sem isto, quem copia
// manualmente só vê "3 arquivos" na pasta e não sabe QUAIS — nem onde parou.

async function abrirStatusPasta() {
    if (!_colecaoAtual.id) return;
    let d;
    try {
        const r = await fetch(`${API_BASE_URL}/api/collections/${_colecaoAtual.id}/sync_status`);
        if (!r.ok) { toastErro(await _erroDaResposta(r, 'Não foi possível ler o status.')); return; }
        d = await r.json();
    } catch (e) { console.error(e); toastErro('Erro de conexão.'); return; }

    const pastas = (d.pastas || []).filter(p => p.existe);
    document.getElementById('statusPastaTitulo').textContent = `Status — ${_colecaoAtual.nome}`;

    const rotuloModo = { auto: 'envio automático', perguntar: 'perguntando antes', manual: 'envio manual' }[d.modo_sync] || d.modo_sync;
    document.getElementById('statusPastaTexto').textContent =
        `A coleção tem ${d.total_colecao} ${d.total_colecao === 1 ? 'imagem' : 'imagens'}. ` +
        `Modo: ${rotuloModo}. Abaixo, o que já foi copiado para cada pasta.`;

    const corpo = document.getElementById('statusPastaCorpo');
    corpo.innerHTML = '';

    if (pastas.length === 0) {
        const p = document.createElement('p');
        p.style.cssText = 'color:var(--text-secondary); font-size:0.92rem;';
        p.textContent = 'Esta coleção ainda não tem pasta no computador. Use "Salvar no computador" para criar uma.';
        corpo.appendChild(p);
    } else {
        pastas.forEach(p => corpo.appendChild(_blocoStatusPasta(p, d.total_colecao)));
    }

    document.getElementById('statusPastaModal').style.display = 'flex';
}

function _blocoStatusPasta(p, totalColecao) {
    const bloco = document.createElement('div');
    bloco.className = 'status-pasta-bloco';

    const cab = document.createElement('div');
    cab.className = 'status-pasta-cabecalho';
    const esq = document.createElement('div');
    const nome = document.createElement('div');
    nome.className = 'status-pasta-nome';
    nome.textContent = p.nome;
    if (p.recebe) {
        const selo = document.createElement('span');
        selo.className = 'pasta-item-selo';
        selo.textContent = 'recebe as fotos';
        nome.appendChild(selo);
    }
    const caminho = document.createElement('div');
    caminho.className = 'status-pasta-caminho';
    caminho.textContent = p.caminho;
    esq.append(nome, caminho);
    cab.appendChild(esq);
    bloco.appendChild(cab);

    const dentro = p.na_pasta.length;
    const pct = totalColecao > 0 ? Math.round((dentro / totalColecao) * 100) : 0;
    const trilha = document.createElement('div');
    trilha.className = 'status-barra-trilha';
    trilha.setAttribute('role', 'progressbar');
    trilha.setAttribute('aria-valuenow', String(dentro));
    trilha.setAttribute('aria-valuemin', '0');
    trilha.setAttribute('aria-valuemax', String(totalColecao));
    trilha.setAttribute('aria-label', `${dentro} de ${totalColecao} imagens em ${p.nome}`);
    const barra = document.createElement('div');
    barra.className = 'status-barra-preenchida';
    barra.style.width = pct + '%';
    trilha.appendChild(barra);
    bloco.appendChild(trilha);

    const cont = document.createElement('div');
    cont.className = 'status-contagem';
    cont.append(
        _contagem('status-ponto-ok', dentro, 'na pasta'),
        _contagem('status-ponto-falta', p.faltando.length, 'faltando'),
    );
    if (p.extras.length > 0) {
        cont.appendChild(_contagem('status-ponto-extra', p.extras.length, 'fora da coleção'));
    }
    bloco.appendChild(cont);

    if (p.na_pasta.length)  bloco.appendChild(_listaNomes(`Já na pasta (${p.na_pasta.length})`, p.na_pasta.map(a => a.nome)));
    if (p.faltando.length)  bloco.appendChild(_listaNomes(`Faltando (${p.faltando.length})`, p.faltando.map(a => a.nome)));
    if (p.extras.length)    bloco.appendChild(_listaNomes(
        `Na pasta mas fora da coleção (${p.extras.length})`, p.extras,
        'Foram removidas da coleção depois de copiadas, ou vieram de outro lugar.'));

    // Copiar o que falta, direto daqui — o motivo de a pessoa abrir esta tela
    // no modo manual é justamente descobrir o que falta e mandar.
    if (p.faltando.length > 0 && p.recebe) {
        const b = document.createElement('button');
        b.className = 'action-btn gradient-btn';
        b.style.marginTop = '12px';
        b.textContent = `Copiar as ${p.faltando.length} que faltam`;
        b.onclick = async () => {
            fecharStatusPasta();
            await enviarParaPastaVinculada(_colecaoAtual.id, _colecaoAtual.nome,
                                           p.faltando.map(a => a.id));
        };
        bloco.appendChild(b);
    }
    return bloco;
}

function _contagem(classePonto, n, rotulo) {
    const s = document.createElement('span');
    const ponto = document.createElement('span');
    ponto.className = 'status-ponto ' + classePonto;
    const b = document.createElement('b');
    b.textContent = String(n);
    s.append(ponto, b, document.createTextNode(' ' + rotulo));
    return s;
}

function _listaNomes(titulo, nomes, nota) {
    const det = document.createElement('details');
    det.className = 'status-lista';
    const sum = document.createElement('summary');
    sum.textContent = titulo;
    det.appendChild(sum);
    if (nota) {
        const p = document.createElement('p');
        p.style.cssText = 'color:var(--text-secondary); font-size:0.79rem; margin:6px 0 0;';
        p.textContent = nota;
        det.appendChild(p);
    }
    const ul = document.createElement('ul');
    ul.className = 'status-nomes';
    nomes.forEach(n => {
        const li = document.createElement('li');
        li.textContent = n;
        ul.appendChild(li);
    });
    det.appendChild(ul);
    return det;
}

function fecharStatusPasta() {
    document.getElementById('statusPastaModal').style.display = 'none';
}

// ── Configurações da coleção: QUANDO enviar ────────────────────────────────
// O modo era escolhido só na criação e ficava sem como mudar. Aqui ele volta,
// com a mesma ilustração — quem abre isto meses depois precisa reentender o
// conceito, não só ver três opções soltas.
// As descrições dizem o que acontece nos DOIS sentidos. A remoção era o ponto
// cego: quem escolhia "enviar sempre" não imaginava que tirar da coleção também
// apagaria a cópia — e precisa saber disso antes de escolher, não depois.
const _MODOS = [
    { id: 'auto',      titulo: 'Manter a pasta igual à coleção',
      desc: 'Adicionar uma foto copia para a pasta; remover da coleção apaga a cópia. ' +
            'Sem perguntar. O arquivo original nunca é tocado.' },
    { id: 'perguntar', titulo: 'Perguntar antes de cada mudança',
      desc: 'Você confirma a cada adição e a cada remoção.' },
    { id: 'manual',    titulo: 'Não mexer na pasta automaticamente',
      desc: 'Nada é copiado nem apagado sozinho. Use "Salvar no computador" e ' +
            '"Status da pasta" para controlar na mão.' },
];

async function abrirConfigColecao() {
    if (!_colecaoAtual.id) return;

    let modo = 'manual', pastas = [];
    try {
        const [rc, rf] = await Promise.all([
            fetch(`${API_BASE_URL}/api/collections`),
            fetch(`${API_BASE_URL}/api/collections/${_colecaoAtual.id}/folders`),
        ]);
        if (rc.ok) {
            const c = ((await rc.json()).colecoes || []).find(x => x.id === _colecaoAtual.id);
            if (c) modo = c.modo_sync || 'manual';
        }
        if (rf.ok) pastas = ((await rf.json()).pastas || []).filter(p => p.existe);
    } catch (e) { console.error(e); toastErro('Erro de conexão.'); return; }

    document.getElementById('configColecaoTitulo').textContent = `Configurações — ${_colecaoAtual.nome}`;
    document.getElementById('configColecaoTexto').textContent =
        'Escolha o que acontece quando você adicionar fotos a esta coleção. ' +
        'Pode mudar quando quiser.';

    // Renomear também daqui: quem abre "Configurações" espera achar o nome
    // entre as coisas configuráveis, não só no lápis do cabeçalho.
    const acaoNome = document.getElementById('configRenomear');
    if (acaoNome) {
        acaoNome.onclick = () => { fecharConfigColecao(); iniciarRenomearColecao(); };
    }

    // Clona a ilustração do modal de vínculo: o SVG tem uma origem só.
    const box = document.getElementById('configIlustracao');
    box.innerHTML = '';
    const original = document.querySelector('#vincularPastaModal .vincular-ilustracao');
    if (original) box.appendChild(original.cloneNode(true));

    const opcoes = document.getElementById('configColecaoOpcoes');
    opcoes.innerHTML = '';
    _MODOS.forEach(m => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'vincular-opcao' + (m.id === modo ? ' is-atual' : '');
        btn.setAttribute('aria-pressed', m.id === modo ? 'true' : 'false');
        const t = document.createElement('span');
        t.className = 'vincular-opcao-titulo';
        t.textContent = m.titulo;
        if (m.id === modo) {
            const selo = document.createElement('span');
            selo.className = 'vincular-opcao-atual-selo';
            selo.textContent = 'atual';
            t.appendChild(selo);
        }
        const d = document.createElement('span');
        d.className = 'vincular-opcao-desc';
        d.textContent = m.desc;
        btn.append(t, d);
        btn.onclick = () => salvarModoDaColecao(m.id);
        opcoes.appendChild(btn);
    });

    // Sem pasta marcada, os modos 'auto' e 'perguntar' não têm para onde
    // enviar — dizer isso evita a configuração que não faz nada.
    const rodape = document.getElementById('configColecaoRodape');
    if (pastas.length === 0) {
        rodape.textContent = 'Esta coleção ainda não tem pasta no computador. ' +
            'Use "Salvar no computador" para criar uma — só então o envio automático tem destino.';
    } else {
        const recebendo = pastas.filter(p => p.recebe);
        rodape.textContent = recebendo.length === 0
            ? `${pastas.length} ${pastas.length === 1 ? 'pasta criada' : 'pastas criadas'}, mas nenhuma marcada para receber. ` +
              'Escolha em "Abrir pasta da coleção".'
            : `Destino: ${recebendo.map(p => p.nome).join(', ')}. ` +
              'Para mudar, use "Abrir pasta da coleção".';
    }

    document.getElementById('configColecaoModal').style.display = 'flex';
}

async function salvarModoDaColecao(modo) {
    try {
        const r = await fetch(`${API_BASE_URL}/api/collections/${_colecaoAtual.id}`, {
            method: 'PATCH', headers: fetchOptions.headers,
            body: JSON.stringify({ modo_sync: modo })
        });
        if (!r.ok) { toastErro(await _erroDaResposta(r, 'Não foi possível salvar.')); return; }
        const rotulo = (_MODOS.find(m => m.id === modo) || {}).titulo || modo;
        toastOk(`Configuração salva: ${rotulo.toLowerCase()}.`);
        fecharConfigColecao();
    } catch (e) { console.error(e); toastErro('Erro de conexão.'); }
}

function fecharConfigColecao() {
    document.getElementById('configColecaoModal').style.display = 'none';
}

// Marca ou desmarca todas de uma vez. Com muitas pastas, "todas" e "nenhuma"
// são os dois casos que custariam N cliques.
async function alternarTodasAsPastas() {
    const caixas = [...document.querySelectorAll('#pastasExpLista input[type="checkbox"]')];
    if (caixas.length === 0) return;
    const marcarTodas = caixas.some(cb => !cb.checked);
    caixas.forEach(cb => { cb.checked = marcarTodas; });
    await aplicarPastasQueRecebem();
}

function atualizarBotaoMarcarTodas() {
    const btn = document.getElementById('btnMarcarTodasPastas');
    const acoes = document.getElementById('pastasExpAcoes');
    if (!btn || !acoes) return;
    const caixas = [...document.querySelectorAll('#pastasExpLista input[type="checkbox"]')];
    // Com uma pasta só, "marcar todas" não significa nada além do próprio item.
    acoes.style.display = caixas.length > 1 ? 'flex' : 'none';
    const vaiMarcarTodas = caixas.some(cb => !cb.checked);
    rotularCom(btn, vaiMarcarTodas ? 'marcar-tudo' : 'caixa-vazia',
               vaiMarcarTodas ? 'Enviar para todas as pastas'
                              : 'Não enviar para nenhuma');
}

// Envia o conjunto inteiro a cada mudança: o backend recebe a lista completa,
// então não há estado parcial nem ordem de operações a coordenar.
async function aplicarPastasQueRecebem() {
    const marcadas = [...document.querySelectorAll('#pastasExpLista input[type="checkbox"]')]
        .filter(cb => cb.checked)
        .map(cb => _pastasExpCache[Number(cb.dataset.idx)].caminho);
    try {
        const r = await fetch(`${API_BASE_URL}/api/collections/${_colecaoAtual.id}`, {
            method: 'PATCH', headers: fetchOptions.headers,
            body: JSON.stringify({ pastas_que_recebem: marcadas })
        });
        if (!r.ok) { toastErro(await _erroDaResposta(r, 'Não foi possível salvar.')); return; }

        const rf = await fetch(`${API_BASE_URL}/api/collections/${_colecaoAtual.id}/folders`);
        if (rf.ok) renderizarPastasExportadas(((await rf.json()).pastas || []).filter(p => p.existe));
        atualizarBotaoAbrirPasta(_colecaoAtual.id);

        if (marcadas.length === 0)      toastInfo('As novas fotos não serão enviadas para nenhuma pasta.');
        else if (marcadas.length === 1) toastOk('As novas fotos vão para 1 pasta.');
        else                            toastOk(`As novas fotos vão para ${marcadas.length} pastas.`);
    } catch (e) { console.error(e); toastErro('Erro de conexão.'); }
}

function fecharPastasExportadas() {
    document.getElementById('pastasExportadasModal').style.display = 'none';
}

// Trocar o complemento do nome da pasta. O prefixo é o nome da coleção e não
// entra na conversa — é o que liga a pasta à coleção no Explorer.
async function renomearSufixoDaPasta(p) {
    const prefixo = _colecaoAtual.nome;
    const atual = p.nome.startsWith(prefixo + '_') ? p.nome.slice(prefixo.length + 1) : '';

    const novo = await pedirTexto(
        'Complemento do nome',
        `A pasta vai se chamar "${prefixo}_<o que você escrever>". ` +
        `Deixe em branco para ficar só "${prefixo}".`,
        atual);
    if (novo === null) return;                    // cancelou
    if (novo.trim() === atual) return;            // nada mudou

    try {
        const r = await fetch(`${API_BASE_URL}/api/collections/${_colecaoAtual.id}/folders`, {
            method: 'PATCH', headers: fetchOptions.headers,
            body: JSON.stringify({ caminho: p.caminho, sufixo: novo.trim() })
        });
        if (!r.ok) { toastErro(await _erroDaResposta(r, 'Não foi possível renomear a pasta.')); return; }
        const d = await r.json();
        toastOk(`Pasta renomeada para "${d.nome}".`);

        const rf = await fetch(`${API_BASE_URL}/api/collections/${_colecaoAtual.id}/folders`);
        if (rf.ok) renderizarPastasExportadas(((await rf.json()).pastas || []).filter(x => x.existe));
        atualizarBotaoAbrirPasta(_colecaoAtual.id);
    } catch (e) { console.error(e); toastErro('Erro de conexão.'); }
}

// Define o conjunto de pastas que recebem. Aceita um caminho (trocar o
// destino) ou uma lista (espelhar em várias).
async function definirPastaQueRecebe(caminhos, nome) {
    const lista = Array.isArray(caminhos) ? caminhos : [caminhos];
    try {
        const r = await fetch(`${API_BASE_URL}/api/collections/${_colecaoAtual.id}`, {
            method: 'PATCH', headers: fetchOptions.headers,
            body: JSON.stringify({ pastas_que_recebem: lista })
        });
        if (!r.ok) { toastErro(await _erroDaResposta(r, 'Não foi possível trocar a pasta.')); return; }
        toastOk(lista.length > 1
            ? `As novas fotos desta coleção vão para ${lista.length} pastas.`
            : `As novas fotos desta coleção passam a ir para "${nome}".`);

        const rf = await fetch(`${API_BASE_URL}/api/collections/${_colecaoAtual.id}/folders`);
        if (rf.ok) renderizarPastasExportadas(((await rf.json()).pastas || []).filter(p => p.existe));
        atualizarBotaoAbrirPasta(_colecaoAtual.id);
    } catch (e) { console.error(e); toastErro('Erro de conexão.'); }
}

let _colecaoAtual = { id: null, nome: '' };

async function verColecao(id, nome) {
    // Preserva a capa já conhecida ao recarregar a mesma coleção; ao trocar de
    // coleção, ela é redescoberta abaixo.
    const capaConhecida = (_colecaoAtual && _colecaoAtual.id === id)
        ? _colecaoAtual.capa_file_id : undefined;
    _colecaoAtual = { id, nome, capa_file_id: capaConhecida };
    document.getElementById('colecoesTitulo').innerText = nome;
    const btnRen = document.getElementById('btnRenomearColecao');
    if (btnRen) btnRen.style.display = 'inline-block';
    document.getElementById('colecoesLista').style.display = 'none';
    document.getElementById('colecoesCriar').style.display = 'none';
    // Dentro de uma coleção não há lista de coleções para ordenar.
    document.getElementById('colecoesOrdem').style.display = 'none';
    document.getElementById('colecaoConteudo').style.display = 'block';
    atualizarBotaoAbrirPasta(id);
    const grid = document.getElementById('colecaoItens');
    grid.innerHTML = '<p style="color:var(--text-secondary);">Carregando...</p>';
    try {
        // A capa vem da listagem, que é quem a conhece. Sem isto, entrar
        // direto numa coleção (pelo desfazer, por exemplo) mostraria a estrela
        // vazia em todas as imagens, mesmo havendo capa escolhida.
        if (_colecaoAtual.capa_file_id === undefined) {
            try {
                const lista = await (await fetch(`${API_BASE_URL}/api/collections`)).json();
                const dela = (lista.colecoes || []).find(c => c.id === id);
                _colecaoAtual.capa_file_id = dela ? dela.capa_file_id : null;
            } catch (e) { _colecaoAtual.capa_file_id = null; }
        }

        const res = await fetch(`${API_BASE_URL}/api/collections/${id}`);
        const d = await res.json();
        const itens = d.resultados || [];
        if (itens.length === 0) {
            grid.innerHTML = '<p style="color:var(--text-secondary);">Coleção vazia.</p>';
            return;
        }
        // Reaproveita os itens como resultadosAtuais pra reusar o painel lateral
        window.resultadosAtuais = itens;
        grid.innerHTML = '';
        itens.forEach((r, idx) => {
            const card = document.createElement('div');
            card.className = 'recent-card';
            card.style.position = 'relative';
            card.onclick = () => { fecharColecoes(); abrirPainelLateral(idx); };
            const ext = (r.tipo || '').toLowerCase();
            if (extensoesImagem.includes(ext)) {
                const img = document.createElement('img');
                img.src = formatImagePath(r.caminho);
                img.alt = textoAlternativo(r);
                img.style.cssText = 'width:100%; height:110px; object-fit:cover; border-radius:8px;';
                card.appendChild(img);
            }
            const nm = document.createElement('div');
            nm.style.cssText = 'font-size:0.8rem; margin-top:6px; color:var(--text-primary); word-break:break-all;';
            nm.textContent = r.nome;
            card.appendChild(nm);

            // Botão de remover este item da coleção (flutuante no canto)
            const rem = document.createElement('button');
            rem.className = 'colecao-item-remover';
            rem.textContent = '×';
            rem.title = 'Remover desta coleção';
            rem.onclick = (e) => { e.stopPropagation(); removerDaColecao(r.id, r.nome); };
            card.appendChild(rem);

            // Definir como capa. Só faz sentido em imagem: um PDF não tem o
            // que mostrar na capa.
            if (extensoesImagem.includes(ext)) {
                const eCapa = _colecaoAtual && _colecaoAtual.capa_file_id === r.id;
                const capaBtn = document.createElement('button');
                capaBtn.className = 'colecao-item-capa' + (eCapa ? ' e-capa' : '');
                capaBtn.replaceChildren(icone('estrela', eCapa ? 'ic--cheio' : ''));
                capaBtn.title = eCapa
                    ? 'Esta é a capa. Clique para voltar ao mosaico automático.'
                    : 'Usar como capa da coleção';
                capaBtn.setAttribute('aria-pressed', eCapa ? 'true' : 'false');
                capaBtn.setAttribute('aria-label', capaBtn.title);
                capaBtn.onclick = (e) => {
                    e.stopPropagation();
                    definirCapaDaColecao(eCapa ? null : r.id);
                };
                card.appendChild(capaBtn);
            }

            grid.appendChild(card);
        });
    } catch (e) {
        console.error(e);
        grid.innerHTML = '<p style="color:#f87171;">Erro ao carregar.</p>';
    }
}

// Escolher a capa da coleção. `null` volta ao mosaico automático — a coleção
// tem uma foto que a representa na cabeça de quem a montou, e o mosaico das 4
// mais recentes raramente é essa foto.
async function definirCapaDaColecao(fileId) {
    if (!_colecaoAtual) return;
    try {
        const r = await fetch(`${API_BASE_URL}/api/collections/${_colecaoAtual.id}`, {
            method: 'PATCH', headers: fetchOptions.headers,
            body: JSON.stringify({ capa_file_id: fileId }),
        });
        if (!r.ok) {
            toastErro(await _erroDaResposta(r, 'Não foi possível definir a capa'));
            return;
        }
        _colecaoAtual.capa_file_id = fileId;
        toastOk(fileId ? 'Capa da coleção atualizada.'
                       : 'A capa voltou ao mosaico automático.');
        verColecao(_colecaoAtual.id, _colecaoAtual.nome);
    } catch (e) {
        toastErro('Não foi possível definir a capa. O servidor respondeu?');
    }
}

// Remove um arquivo da coleção aberta (usa o endpoint DELETE que já existe)
async function removerDaColecao(fileId, nomeArquivo) {
    if (!_colecaoAtual.id) return;
    try {
        const res = await fetch(`${API_BASE_URL}/api/collections/${_colecaoAtual.id}/files`, {
            method: 'DELETE', headers: fetchOptions.headers,
            body: JSON.stringify({ file_id: fileId })
        });
        if (res.ok) {
            const d = await res.json().catch(() => ({}));
            const col = _colecaoAtual;
            if (d.lixeira_id) {
                // O desfazer devolve a imagem à coleção. A cópia na pasta
                // espelho, se foi apagada logo abaixo, não volta — apagar
                // arquivo do disco é do usuário, e o app não desfaz isso.
                toastComDesfazer(`"${nomeArquivo}" removido da coleção.`,
                    () => desfazerExclusao(d.lixeira_id,
                                           () => verColecao(col.id, col.nome)));
            } else {
                toastInfo(`"${nomeArquivo}" removido da coleção.`);
            }
            verColecao(_colecaoAtual.id, _colecaoAtual.nome);  // recarrega a coleção
            // Espelhar é nos dois sentidos: se a coleção manda na pasta, sair
            // da coleção também tira da pasta.
            await removerDasPastasSePreciso(d);
        } else {
            toastErro("Não foi possível remover.");
        }
    } catch (e) { console.error(e); toastErro("Erro de conexão."); }
}

// Aplica a remoção nas pastas espelho conforme o modo salvo na coleção.
// Só apaga a CÓPIA — o original nas pastas monitoradas nunca é tocado.
async function removerDasPastasSePreciso(d) {
    const nomes = d.nomes_removidos || [];
    const pastas = d.pastas_que_recebem || [];
    const modo = d.modo_sync || 'manual';
    if (modo === 'manual' || nomes.length === 0 || pastas.length === 0) return;

    if (modo === 'perguntar') {
        const n = nomes.length;
        const ok = await confirmarAcao(
            'Apagar também da pasta?',
            `${n === 1 ? 'A cópia' : `As ${n} cópias`} em ` +
            `${pastas.length === 1 ? `"${_nomeDaPasta(pastas[0])}"` : `${pastas.length} pastas`} ` +
            `${n === 1 ? 'será apagada' : 'serão apagadas'}. ` +
            `${n === 1 ? 'O arquivo original' : 'Os arquivos originais'} não ` +
            `${n === 1 ? 'é afetado' : 'são afetados'}.`,
            'Apagar da pasta', 'Manter na pasta');
        if (!ok) return;
    }

    try {
        const r = await fetch(`${API_BASE_URL}/api/collections/${_colecaoAtual.id}/sync`, {
            method: 'DELETE', headers: fetchOptions.headers,
            body: JSON.stringify({ nomes })
        });
        if (!r.ok) { toastErro(await _erroDaResposta(r, 'Não foi possível apagar da pasta.')); return; }
        const res = await r.json();
        if (res.apagados > 0) {
            toastOk(`${res.apagados} ${res.apagados === 1 ? 'cópia apagada' : 'cópias apagadas'} da pasta.`);
        }
        if ((res.falhas || []).length > 0) {
            toastAviso(`${res.falhas.length} não ${res.falhas.length === 1 ? 'pôde' : 'puderam'} ser apagada(s) da pasta.`);
        }
    } catch (e) { console.error(e); toastErro('Erro de conexão.'); }
}

// Adicionar o arquivo aberto no painel lateral a uma coleção.
// Abre um modal com a lista de coleções clicáveis (sem prompt nativo).
async function abrirSeletorColecao() {
    // Sem seleção múltipla ativa, opera sobre o arquivo aberto no painel.
    if (_selecionados.size === 0 && !_fileIdAtual) {
        toastAviso("Abra um arquivo ou selecione imagens primeiro.");
        return;
    }
    const lista = document.getElementById('escolherColecaoLista');
    lista.innerHTML = '<p style="color:var(--text-secondary);">Carregando...</p>';
    document.getElementById('escolherColecaoModal').style.display = 'flex';
    try {
        const res = await fetch(`${API_BASE_URL}/api/collections`);
        const d = await res.json();
        const cols = d.colecoes || [];

        if (cols.length === 0) {
            lista.innerHTML = '<p style="color:var(--text-secondary);">Você ainda não tem coleções. Crie uma abaixo.</p>';
            return;
        }
        lista.innerHTML = '';
        cols.forEach(c => {
            const btn = document.createElement('button');
            btn.className = 'escolher-colecao-item';
            const nm = document.createElement('span');
            nm.textContent = c.nome;
            const cnt = document.createElement('span');
            cnt.className = 'escolher-colecao-count';
            cnt.textContent = `${c.total} ${c.total === 1 ? 'item' : 'itens'}`;
            btn.append(nm, cnt);
            btn.onclick = async () => {
                fecharEscolherColecao();
                await adicionarAColecao(c.id, c.nome);
            };
            lista.appendChild(btn);
        });
    } catch (e) {
        console.error(e);
        lista.innerHTML = '<p style="color:#f87171;">Erro ao carregar coleções.</p>';
    }
}

function fecharEscolherColecao() {
    // Se havia um envio de favoritos esperando esta escolha, fechar cancela —
    // sem isto a promessa ficaria pendurada e o botão de criar coleção
    // continuaria preso ao fluxo dos favoritos.
    if (_resolverEscolhaColecao) {
        _encerrarEscolhaColecao(null);
        return;
    }
    document.getElementById('escolherColecaoModal').style.display = 'none';
}

// "+ Criar nova coleção" dentro do modal de escolha: pede o nome via
// modal de input (pedirTexto) e já adiciona o arquivo atual nela.
async function criarColecaoEAdicionar() {
    const nome = await pedirTexto("Nova coleção", "Nome da coleção:");
    if (!nome || !nome.trim()) return;
    try {
        const cr = await fetch(`${API_BASE_URL}/api/collections`, {
            method: 'POST', headers: fetchOptions.headers,
            body: JSON.stringify({ nome: nome.trim() })
        });
        const cd = await cr.json();
        if (cr.ok) {
            fecharEscolherColecao();
            // Adiciona primeiro, pergunta da pasta depois: assim a pergunta
            // vem com a coleção já povoada, e o vínculo copia tudo de uma vez.
            await adicionarAColecao(cd.id, nome.trim());
            await configurarPastaDaColecao(cd.id, nome.trim());
        } else {
            toastErro(cd.error || "Erro ao criar coleção.");
        }
    } catch (e) { console.error(e); toastErro("Erro de conexão."); }
}

async function adicionarAColecao(colId, nome) {
    // Lote quando há seleção; senão, o arquivo aberto no painel lateral.
    const ids = _selecionados.size > 0 ? [..._selecionados] : [_fileIdAtual];
    try {
        const res = await fetch(`${API_BASE_URL}/api/collections/${colId}/files`, {
            method: 'POST', headers: fetchOptions.headers,
            body: JSON.stringify({ file_ids: ids })
        });
        const d = await res.json().catch(() => ({}));
        if (!res.ok) { toastErro(d.error || "Não foi possível adicionar."); return; }

        const add = d.adicionados ?? ids.length;
        const ja  = d.ja_existiam ?? 0;
        if (add === 0)      toastInfo(`Já ${ja === 1 ? 'estava' : 'estavam'} na coleção "${nome}".`);
        else if (ja > 0)    toastOk(`${add} adicionada(s) a "${nome}" — ${ja} já ${ja === 1 ? 'estava' : 'estavam'} lá.`);
        else                toastOk(`${add === 1 ? 'Adicionado' : add + ' adicionadas'} à coleção "${nome}".`);

        if (_selecionados.size > 0) limparSelecao();

        // Sincronia com a pasta vinculada, se houver. A decisão foi tomada uma
        // vez, na criação da coleção — aqui só se obedece ao que ficou salvo.
        await sincronizarSePreciso({
            id: colId, nome,
            pasta: d.pasta_vinculada,
            modo: d.modo_sync || 'manual',
            ids: d.ids_adicionados || [],
        });
    } catch (e) { console.error(e); toastErro("Erro de conexão."); }
}

// ==========================================
// PASTA VINCULADA (coleção espelhada no disco)
// ==========================================
// O usuário decide UMA vez, ao criar a coleção, se ela tem uma pasta no
// computador e o que acontece quando novas imagens entram. Depois disso o app
// não pergunta mais nada — exceto no modo 'perguntar', que é escolha dele.

// Executa a sincronia conforme o modo salvo na coleção.
async function sincronizarSePreciso({ id, nome, pasta, modo, ids }) {
    if (!pasta || modo === 'manual') return;   // nada vinculado: fluxo segue igual
    if (!ids || ids.length === 0) return;      // nada novo entrou: nada a copiar

    if (modo === 'perguntar') {
        const n = ids.length;
        const ok = await confirmarAcao(
            'Enviar para a pasta?',
            `${n === 1 ? 'A imagem adicionada' : `As ${n} imagens adicionadas`} ` +
            `${n === 1 ? 'vai' : 'vão'} para "${_nomeDaPasta(pasta)}"?`,
            'Enviar agora', 'Agora não');
        if (!ok) return;
    }

    await enviarParaPastaVinculada(id, nome, ids);
}

function _nomeDaPasta(caminho) {
    return (caminho || '').split(/[\\/]/).filter(Boolean).pop() || caminho;
}

// Traduz uma resposta de erro em algo acionável.
//
// O caso que motivou isto: com o backend rodando de antes da feature, o PATCH
// devolvia 405 em HTML. O `.json()` falhava, o corpo virava {} e o usuário via
// "Não foi possível criar a pasta" — mensagem que manda procurar permissão de
// disco quando o problema era um servidor desatualizado.
async function _erroDaResposta(r, padrao) {
    if (r.status === 405 || r.status === 404) {
        return 'O servidor está desatualizado e não conhece esta função. ' +
               'Feche a janela do servidor e rode o rodar.bat de novo.';
    }
    let d = {};
    try { d = await r.json(); } catch (e) { /* resposta não-JSON: usa o padrão */ }
    if (d && d.error) return d.error;
    return `${padrao} (erro ${r.status})`;
}

// Chama /sync e traduz o resultado numa frase. Sem barra de progresso: a
// sincronia é de poucos arquivos e termina antes de valer a pena mostrar uma.
async function enviarParaPastaVinculada(colId, nome, ids) {
    try {
        const r = await fetch(`${API_BASE_URL}/api/collections/${colId}/sync`, {
            method: 'POST', headers: fetchOptions.headers,
            body: JSON.stringify(ids ? { file_ids: ids } : {})
        });
        const d = await r.json().catch(() => ({}));

        if (r.status === 409) {
            // A pasta sumiu do disco. Não insiste nem desvincula sozinho —
            // o usuário decide se quer apontar para outro lugar.
            toastErro(d.error || 'A pasta desta coleção não está mais no lugar.');
            return;
        }
        if (!r.ok) { toastErro(await _erroDaResposta(r, 'Não foi possível enviar para a pasta.')); return; }

        const falhas = (d.falhas || []).length;
        const alvo = _nomeDaPasta(d.pasta);
        if (d.copiados > 0 && falhas === 0) {
            toastOk(`${d.copiados} ${d.copiados === 1 ? 'imagem enviada' : 'imagens enviadas'} para "${alvo}".`);
        } else if (d.copiados > 0) {
            toastAviso(`${d.copiados} ${d.copiados === 1 ? 'enviada' : 'enviadas'} para "${alvo}" — ${falhas} não ${falhas === 1 ? 'pôde' : 'puderam'} ser copiada(s).`);
        } else if (falhas > 0) {
            toastErro(`Nenhuma imagem foi enviada para "${alvo}": ${falhas} ${falhas === 1 ? 'falhou' : 'falharam'}.`);
        } else if (d.ja_existiam > 0) {
            toastInfo(`Já ${d.ja_existiam === 1 ? 'estava' : 'estavam'} na pasta "${alvo}".`);
        }
    } catch (e) { console.error(e); toastErro('Erro de conexão ao enviar para a pasta.'); }
}

// ── Modal de vínculo (mostrado UMA vez, ao criar a coleção) ─────────────────
let _vinculoResolver = null;

function perguntarVinculoDePasta(nomeColecao) {
    return new Promise((resolve) => {
        _vinculoResolver = resolve;
        document.getElementById('vincularTexto').textContent =
            `A coleção "${nomeColecao}" pode ter uma pasta no seu computador. ` +
            `As imagens que você adicionar a ela são copiadas para lá — os ` +
            `originais continuam onde estão.`;
        document.getElementById('vincularPastaModal').style.display = 'flex';
    });
}

function responderVinculo(modo) {
    document.getElementById('vincularPastaModal').style.display = 'none';
    const resolver = _vinculoResolver;
    _vinculoResolver = null;
    if (resolver) resolver(modo);
}

function fecharVincularPasta() {
    // Fechar sem escolher equivale a "não vincular" — nunca deixa a promise pendurada.
    if (_vinculoResolver) responderVinculo('manual');
    else document.getElementById('vincularPastaModal').style.display = 'none';
}

// Fluxo completo do vínculo, chamado logo após criar uma coleção.
// É o ÚNICO momento em que o app pergunta sobre pasta.
async function configurarPastaDaColecao(colId, nome) {
    const modo = await perguntarVinculoDePasta(nome);
    if (modo === 'manual') return 'manual';

    let destino;
    try {
        const r = await fetch(`${API_BASE_URL}/api/choose_folder`);
        const d = await r.json();
        if (d.status === 'cancelado') return 'manual';   // desistiu: sem pasta
        if (d.status !== 'sucesso' || !d.pasta) {
            toastErro('Não foi possível abrir o seletor de pastas.');
            return 'manual';
        }
        destino = d.pasta;
    } catch (e) { console.error(e); toastErro('Erro de conexão.'); return 'manual'; }

    // Cria a pasta E grava o vínculo numa chamada só. O backend reaproveita a
    // sanitização e a resolução de colisão da exportação — uma lógica só.
    let pastaCriada;
    try {
        const r = await fetch(`${API_BASE_URL}/api/collections/${colId}`, {
            method: 'PATCH', headers: fetchOptions.headers,
            body: JSON.stringify({ criar_pasta_em: destino, modo_sync: modo })
        });
        if (!r.ok) {
            toastErro(await _erroDaResposta(r, 'Não foi possível criar a pasta.'));
            return 'manual';
        }
        const d = await r.json();
        pastaCriada = d.pasta_vinculada;
    } catch (e) { console.error(e); toastErro('Erro de conexão.'); return 'manual'; }

    // Coleção que já tenha itens (o caso de vincular depois) sai daqui com a
    // pasta em dia; a recém-criada está vazia e este passo não faz nada.
    await enviarParaPastaVinculada(colId, nome, null);

    toastOk(modo === 'auto'
        ? `"${nome}" vai salvar em "${_nomeDaPasta(pastaCriada)}". Novas imagens vão sozinhas.`
        : `"${nome}" vai salvar em "${_nomeDaPasta(pastaCriada)}".`);
    return modo;
}

// ==========================================
// EXPORTAR COLEÇÃO PARA UMA PASTA LOCAL
// ==========================================
// Exportar aqui é copiar arquivo local → pasta local. O backend roda na
// máquina do usuário, então quem cria a pasta e copia é o Python.

let _exportJobId = null;
let _exportTimer = null;

// As opções da exportação, perguntadas antes de escolher a pasta.
//
// Vêm ANTES do seletor de pastas de propósito: o diálogo do Windows é modal e
// bloqueia a tela, e voltar dele para responder um formulário faria a pessoa
// perder o fio do que estava fazendo.
let _resolverOpcoesExport = null;

function perguntarOpcoesDeExportacao() {
    return new Promise((resolve) => {
        _resolverOpcoesExport = resolve;
        document.getElementById('opcoesExportModal').style.display = 'flex';
    });
}

function fecharOpcoesExport() {
    document.getElementById('opcoesExportModal').style.display = 'none';
    const resolver = _resolverOpcoesExport;
    _resolverOpcoesExport = null;
    if (resolver) resolver(null);          // fechar cancela a exportação
}

function confirmarOpcoesExport() {
    const opcoes = {
        tipos: document.getElementById('expTipos').value,
        padrao_nome: document.getElementById('expPadrao').value.trim(),
        largura_max: document.getElementById('expLargura').value || null,
        subpastas_por_data: document.getElementById('expSubpastas').checked,
    };
    document.getElementById('opcoesExportModal').style.display = 'none';
    const resolver = _resolverOpcoesExport;
    _resolverOpcoesExport = null;
    if (resolver) resolver(opcoes);
}

async function exportarColecao() {
    if (!_colecaoAtual.id) return;

    const opcoes = await perguntarOpcoesDeExportacao();
    if (!opcoes) return;                   // desistiu

    // Já exportada antes? Então esta é uma SEGUNDA pasta, e há duas decisões
    // que só o usuário pode tomar: como chamar a nova, e qual das pastas passa
    // a receber as fotos. Exportar em silêncio criaria pastas soltas e mudaria
    // o destino sem ele perceber.
    let existentes = [];
    try {
        const r = await fetch(`${API_BASE_URL}/api/collections/${_colecaoAtual.id}/folders`);
        if (r.ok) existentes = ((await r.json()).pastas || []).filter(p => p.existe);
    } catch (e) { console.error(e); }

    let sufixo = '';
    if (existentes.length > 0) {
        sufixo = await perguntarNomeDaNovaPasta(existentes);
        if (sufixo === null) return;             // desistiu
    }

    // Escolher o destino pelo diálogo nativo do Windows
    let destino;
    try {
        const r = await fetch(`${API_BASE_URL}/api/choose_folder`);
        const d = await r.json();
        if (d.status === 'cancelado') return;          // desistiu: sem erro
        if (d.status !== 'sucesso' || !d.pasta) {
            toastErro("Não foi possível abrir o seletor de pastas.");
            return;
        }
        destino = d.pasta;
    } catch (e) { console.error(e); toastErro("Erro de conexão."); return; }

    // Iniciar o job. Numa re-exportação, `vincular: false` mantém o destino
    // atual — a troca é perguntada depois, quando a pasta já existe.
    let pastaNova;
    try {
        const corpo = { destino, ...opcoes };
        if (existentes.length > 0) { corpo.sufixo = sufixo; corpo.vincular = false; }
        const r = await fetch(`${API_BASE_URL}/api/collections/${_colecaoAtual.id}/export`, {
            method: 'POST', headers: fetchOptions.headers,
            body: JSON.stringify(corpo)
        });
        if (!r.ok) { toastErro(await _erroDaResposta(r, 'Não foi possível exportar.')); return; }
        const d = await r.json();
        pastaNova = d.pasta;

        _exportJobId = d.job_id;
        abrirModalExportacao(d.total);
        _exportTimer = setInterval(consultarExportacao, 400);
    } catch (e) { console.error(e); toastErro("Erro de conexão."); return; }

    if (existentes.length > 0) _pendenteEscolherDestino = { pastaNova, existentes };
}

// ── Segunda exportação: nome da pasta nova ─────────────────────────────────
let _expNovoCtx = null;
let _pendenteEscolherDestino = null;

function perguntarNomeDaNovaPasta(existentes) {
    return new Promise((resolve) => {
        const base = _colecaoAtual.nome;
        _expNovoCtx = { resolve, base, existentes };

        document.getElementById('expNovoTexto').textContent =
            `"${base}" já foi salva em ${existentes.length === 1 ? 'uma pasta' : `${existentes.length} pastas`}. ` +
            `Uma nova pasta será criada — o nome da coleção é mantido no começo, ` +
            `para você reconhecer de onde ela veio.`;

        document.getElementById('expNovoAutoDesc').textContent =
            `A pasta vai se chamar "${base}_${existentes.length + 1}".`;
        document.getElementById('expNovoCustomDesc').textContent =
            `Ex.: "${base}_backup" ou "${base}_praia".`;
        document.getElementById('expNovoPrefixo').textContent = `${base}_`;
        document.getElementById('expNovoSufixo').value = '';

        document.getElementById('expNovoEtapaNome').style.display = 'block';
        document.getElementById('expNovoEtapaDestino').style.display = 'none';
        document.getElementById('expNovoCampo').style.display = 'none';
        document.getElementById('exportarDeNovoModal').style.display = 'flex';
    });
}

function escolherNomeNovaPasta(tipo) {
    if (!_expNovoCtx) return;
    if (tipo === 'auto') {
        _fecharExpNovo('');                 // sufixo vazio: backend numera
        return;
    }
    document.getElementById('expNovoCampo').style.display = 'block';
    setTimeout(() => document.getElementById('expNovoSufixo').focus(), 50);
}

function confirmarNomeNovaPasta() {
    const v = document.getElementById('expNovoSufixo').value.trim();
    if (!v) { toastAviso('Escreva um complemento ou escolha numerar automaticamente.'); return; }
    _fecharExpNovo(v);
}

function _fecharExpNovo(valor) {
    document.getElementById('exportarDeNovoModal').style.display = 'none';
    const ctx = _expNovoCtx;
    _expNovoCtx = null;
    if (ctx) ctx.resolve(valor);
}

function fecharExportarDeNovo() {
    if (_expNovoCtx) _fecharExpNovo(null);   // null = desistiu
    else document.getElementById('exportarDeNovoModal').style.display = 'none';
}

// ── Depois da segunda exportação: qual pasta recebe as próximas fotos ──────
function perguntarQualPastaRecebe({ pastaNova, existentes }) {
    const nomeNova = _nomeDaPasta(pastaNova);
    document.getElementById('expNovoTexto').textContent =
        `A pasta "${nomeNova}" foi criada. Agora escolha para onde vão as fotos ` +
        `que você adicionar a esta coleção daqui em diante.`;
    document.getElementById('expNovoEtapaNome').style.display = 'none';
    document.getElementById('expNovoEtapaDestino').style.display = 'block';

    const box = document.getElementById('expNovoDestinos');
    box.innerHTML = '';
    const opcoes = [{ caminho: pastaNova, nome: nomeNova, nova: true },
                    ...existentes.map(p => ({ caminho: p.caminho, nome: p.nome, atual: p.recebe }))];

    // Atalhos para os dois casos comuns, e depois a marcação livre. Sem eles,
    // "só a nova" — o caso mais frequente — custaria desmarcar as outras.
    const atalho = (rotulo, desc, lista) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'vincular-opcao';
        const t = document.createElement('span');
        t.className = 'vincular-opcao-titulo';
        t.textContent = rotulo;
        const d = document.createElement('span');
        d.className = 'vincular-opcao-desc';
        d.textContent = desc;
        btn.append(t, d);
        btn.onclick = async () => {
            document.getElementById('exportarDeNovoModal').style.display = 'none';
            await definirPastaQueRecebe(lista, nomeNova);
        };
        box.appendChild(btn);
    };

    atalho(`Só "${nomeNova}"`, 'As próximas fotos vão apenas para a pasta nova.',
           [pastaNova]);
    atalho('Todas as pastas', `As próximas fotos vão para as ${opcoes.length} pastas ao mesmo tempo.`,
           opcoes.map(o => o.caminho));
    atalho('Nenhuma por enquanto', 'As pastas ficam salvas, mas nada é enviado automaticamente.',
           []);

    // Marcação livre, para combinações que os atalhos não cobrem
    const sep = document.createElement('p');
    sep.className = 'exp-novo-rotulo';
    sep.style.marginTop = '14px';
    sep.textContent = 'Ou escolha exatamente quais:';
    box.appendChild(sep);

    opcoes.forEach(o => {
        const item = document.createElement('label');
        item.className = 'pasta-item';
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.checked = !!(o.nova || o.atual);
        cb.dataset.caminho = o.caminho;
        cb.setAttribute('aria-label', `Enviar as novas fotos para ${o.nome}`);
        const info = document.createElement('div');
        info.className = 'pasta-item-info';
        const nm = document.createElement('span');
        nm.className = 'pasta-item-nome';
        nm.textContent = o.nome + (o.nova ? '  (a que você acabou de criar)' : o.atual ? '  (recebe hoje)' : '');
        const cm = document.createElement('span');
        cm.className = 'pasta-item-caminho';
        cm.textContent = o.caminho;
        info.append(nm, cm);
        item.append(cb, info);
        box.appendChild(item);
    });

    const confirmar = document.createElement('button');
    confirmar.className = 'action-btn gradient-btn';
    confirmar.style.cssText = 'margin-top:14px; align-self:flex-end;';
    confirmar.textContent = 'Confirmar escolha';
    confirmar.onclick = async () => {
        const marcadas = [...box.querySelectorAll('input[type="checkbox"]:checked')]
            .map(cb => cb.dataset.caminho);
        document.getElementById('exportarDeNovoModal').style.display = 'none';
        await definirPastaQueRecebe(marcadas, nomeNova);
    };
    box.appendChild(confirmar);

    document.getElementById('exportarDeNovoModal').style.display = 'flex';
}

function abrirModalExportacao(total) {
    document.getElementById('exportModal').style.display = 'flex';
    document.getElementById('exportProgressoBox').style.display = 'block';
    document.getElementById('exportResultadoBox').style.display = 'none';
    document.getElementById('exportTitulo').textContent = `Exportando "${_colecaoAtual.nome}"...`;
    definirProgressoExport(0, total);
}

function definirProgressoExport(feitos, total) {
    const barra = document.getElementById('exportBarra');
    const txt   = document.getElementById('exportContagem');
    const pct   = total > 0 ? Math.round((feitos / total) * 100) : 0;
    barra.style.width = pct + '%';
    barra.setAttribute('aria-valuenow', String(feitos));
    barra.setAttribute('aria-valuemax', String(total));
    txt.textContent = `${feitos} de ${total} imagens`;
}

async function consultarExportacao() {
    if (!_exportJobId) return;
    try {
        const r = await fetch(`${API_BASE_URL}/api/collections/export/${_exportJobId}`);
        if (!r.ok) { pararPolling(); toastErro("Exportação não encontrada."); return; }
        const d = await r.json();

        definirProgressoExport(d.copiados, d.total);
        if (d.estado === 'executando') return;

        pararPolling();
        mostrarResultadoExportacao(d);
    } catch (e) {
        // Backend caiu no meio: para de girar e avisa (RNF-026)
        pararPolling();
        console.error(e);
        toastErro("A conexão com o Search+ foi perdida durante a exportação.");
    }
}

function pararPolling() {
    if (_exportTimer) { clearInterval(_exportTimer); _exportTimer = null; }
}

function mostrarResultadoExportacao(d) {
    document.getElementById('exportProgressoBox').style.display = 'none';
    const box = document.getElementById('exportResultadoBox');
    box.style.display = 'block';
    box.innerHTML = '';

    const titulo = document.getElementById('exportTitulo');
    const h = document.createElement('p');
    h.className = 'export-resumo';

    if (d.erro === 'disco_cheio') {
        titulo.textContent = 'Exportação interrompida';
        h.textContent = `O disco ficou sem espaço. ${d.copiados} imagens foram salvas antes de parar.`;
    } else if (d.estado === 'cancelado') {
        titulo.textContent = 'Exportação cancelada';
        h.textContent = `${d.copiados} de ${d.total} imagens foram copiadas antes do cancelamento e permanecem na pasta.`;
    } else if (d.falhas.length > 0) {
        titulo.textContent = 'Coleção salva — parcialmente';
        h.textContent = `${d.copiados} de ${d.total} imagens salvas em ${d.pasta}`;
    } else {
        rotularCom(titulo, 'check-circulo', 'Coleção salva');
        h.textContent = `${d.copiados} ${d.copiados === 1 ? 'imagem salva' : 'imagens salvas'} em ${d.pasta}`;
    }
    box.appendChild(h);

    // Lista nominal das falhas: um número solto não deixa o usuário
    // reconciliar a coleção com o disco (RF-053).
    if (d.falhas.length > 0) {
        const MOTIVOS = {
            nao_encontrado: 'não encontrada (movida ou apagada)',
            sem_permissao: 'sem permissão de leitura',
            fora_das_pastas: 'fora das pastas do computador',
            erro_leitura: 'falha ao ler o arquivo',
        };
        const t = document.createElement('p');
        t.className = 'export-falhas-titulo';
        t.textContent = `${d.falhas.length} não ${d.falhas.length === 1 ? 'pôde' : 'puderam'} ser copiada(s):`;
        box.appendChild(t);

        const ul = document.createElement('ul');
        ul.className = 'export-falhas';
        d.falhas.forEach(f => {
            const li = document.createElement('li');
            li.textContent = `${f.nome} — ${MOTIVOS[f.motivo] || f.motivo}`;
            ul.appendChild(li);
        });
        box.appendChild(ul);
    }

    const acoes = document.createElement('div');
    acoes.className = 'export-acoes';
    if (d.copiados > 0) {
        const abrir = document.createElement('button');
        abrir.className = 'action-btn gradient-btn';
        abrir.textContent = 'Abrir pasta';
        abrir.onclick = () => abrirPastaExportada(d.pasta);
        acoes.appendChild(abrir);
    }
    const fechar = document.createElement('button');
    fechar.className = 'action-btn';
    fechar.textContent = 'Fechar';
    fechar.onclick = fecharExportacao;
    acoes.appendChild(fechar);
    box.appendChild(acoes);
}

async function abrirPastaExportada(pasta) {
    try {
        const r = await fetch(`${API_BASE_URL}/api/open_folder?path=${encodeURIComponent(pasta)}`);
        if (!r.ok) toastErro("Não foi possível abrir a pasta.");
    } catch (e) { console.error(e); toastErro("Erro de conexão."); }
}

async function cancelarExportacao() {
    if (!_exportJobId) return;
    try {
        await fetch(`${API_BASE_URL}/api/collections/export/${_exportJobId}/cancel`, { method: 'POST' });
    } catch (e) { console.error(e); }
}

function fecharExportacao() {
    pararPolling();
    _exportJobId = null;
    document.getElementById('exportModal').style.display = 'none';
    atualizarBotaoAbrirPasta(_colecaoAtual.id);

    // Numa segunda exportação, a escolha de destino vem AGORA — depois do
    // resultado, para não competir com a barra de progresso na tela.
    if (_pendenteEscolherDestino) {
        const ctx = _pendenteEscolherDestino;
        _pendenteEscolherDestino = null;
        perguntarQualPastaRecebe(ctx);
    }
}

// ==========================================
// BUSCA POR IMAGEM (similaridade visual via CLIP)
// ==========================================
let _imagemBuscaDataUrl = null;

function abrirBuscaImagem() {
    document.getElementById('buscaImagemModal').style.display = 'flex';
    _imagemBuscaDataUrl = null;
    document.getElementById('dropZonePreview').style.display = 'none';
    document.getElementById('dropZonePlaceholder').style.display = 'flex';
    document.getElementById('btnBuscarParecidas').style.display = 'none';
}
function fecharBuscaImagem() {
    document.getElementById('buscaImagemModal').style.display = 'none';
}

// Lê um File em data URL e prepara o preview
function _carregarArquivoImagem(file) {
    if (!file || !file.type.startsWith('image/')) {
        toastAviso("Escolha um arquivo de imagem.");
        return;
    }
    const reader = new FileReader();
    reader.onload = (e) => {
        _imagemBuscaDataUrl = e.target.result;
        const prev = document.getElementById('dropZonePreview');
        prev.src = _imagemBuscaDataUrl;
        prev.style.display = 'block';
        document.getElementById('dropZonePlaceholder').style.display = 'none';
        document.getElementById('btnBuscarParecidas').style.display = 'block';
    };
    reader.readAsDataURL(file);
}

async function executarBuscaPorImagem() {
    if (!_imagemBuscaDataUrl) { toastAviso("Escolha uma imagem primeiro."); return; }
    fecharBuscaImagem();
    await _renderBuscaVisual({ data_url: _imagemBuscaDataUrl });
}

// Busca "achar parecidas" a partir do arquivo aberto no painel lateral
async function acharParecidas() {
    if (!_fileIdAtual) { toastAviso("Abra um arquivo primeiro."); return; }
    fecharPainelLateral();
    await _renderBuscaVisual({ file_id: _fileIdAtual });
}

// Faz o POST e renderiza os resultados reusando o fluxo de busca textual
async function _renderBuscaVisual(corpo) {
    const loadingScreen = document.getElementById('iaLoadingScreen');
    if (loadingScreen) loadingScreen.style.display = 'flex';
    try {
        const res = await fetch(`${API_BASE_URL}/api/search_by_image`, {
            method: 'POST', headers: fetchOptions.headers,
            body: JSON.stringify(corpo)
        });
        const d = await res.json();
        if (d.erro) { toastErro(d.erro); return; }

        window.resultadosAtuais = d.resultados || [];

        // Garante que a view de resultados está visível (caso venha do dashboard)
            const wrapper = document.getElementById('mainAppWrapper');
        wrapper.classList.remove('layout-centered');
        wrapper.classList.add('layout-top');
        document.getElementById('dashboardView').style.display = 'none';
        document.getElementById('filterBarContainer').style.display = 'flex';
        document.getElementById('filterBarContainer').style.opacity = '1';
        document.getElementById('searchResultsView').style.display = 'block';
        document.getElementById('searchResultsView').classList.remove('fade-out');
        document.getElementById('searchResultsView').style.opacity = '1';

        renderizarResultados();

        if (window.resultadosAtuais.length === 0) {
            toastInfo("Nenhuma imagem parecida encontrada no acervo.");
        } else {
            toastOk(`${window.resultadosAtuais.length} imagem(ns) parecida(s).`);
        }
    } catch (e) {
        console.error(e);
        toastErro("Erro ao buscar por imagem.");
    } finally {
        if (loadingScreen) loadingScreen.style.display = 'none';
    }
}

// Liga os handlers da drop zone uma vez que o DOM existe
document.addEventListener('DOMContentLoaded', () => {
    const zona = document.getElementById('dropZone');
    const input = document.getElementById('dropZoneInput');
    if (!zona || !input) return;

    zona.addEventListener('click', () => input.click());
    input.addEventListener('change', (e) => {
        if (e.target.files && e.target.files[0]) _carregarArquivoImagem(e.target.files[0]);
    });
    zona.addEventListener('dragover', (e) => {
        e.preventDefault();
        zona.classList.add('drop-zone-ativo');
    });
    zona.addEventListener('dragleave', () => zona.classList.remove('drop-zone-ativo'));
    zona.addEventListener('drop', (e) => {
        e.preventDefault();
        zona.classList.remove('drop-zone-ativo');
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            _carregarArquivoImagem(e.dataTransfer.files[0]);
        }
    });
});
