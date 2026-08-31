// Deriva a URL da API da própria página, em vez de fixar uma porta: o mesmo
// arquivo serve tanto o backend real (5000) quanto o servidor mock (5001), sem
// editar nada. Só cai no valor fixo quando a página é aberta pelo file://,
// onde não há origem HTTP para herdar.
const API_BASE_URL =
    window.location.protocol.startsWith("http")
        ? window.location.origin
        : "http://127.0.0.1:5000";
let currentConfig = {};
let tempConfig = {};

let cropper;
let targetCropInput = '';

window.resultadosAtuais = [];
window.ultimoTempoBusca = 0;
let filtroAtual = 'all';

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
    document.querySelectorAll('.filter-tag').forEach(btn => {
        btn.addEventListener('click', (e) => {
            document.querySelectorAll('.filter-tag').forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            filtroAtual = e.target.getAttribute('data-filter');
            if (document.getElementById('searchResultsView').style.display === 'block') {
                renderizarResultados();
            }
        });
    });
});

// ==========================================
// SISTEMA DE TOAST (notificações ao usuário)
// ==========================================
// Substitui alert() nativo e os console.error silenciosos.
// Tipos: 'sucesso' | 'erro' | 'info' | 'aviso'
function mostrarToast(mensagem, tipo = 'info', duracaoMs = 4500) {
    const container = document.getElementById('toastContainer');
    if (!container) { console.log(`[${tipo}] ${mensagem}`); return; }

    const icones = { sucesso: '✓', erro: '✕', info: 'ℹ', aviso: '⚠' };
    const toast = document.createElement('div');
    toast.className = `toast toast-${tipo}`;
    toast.innerHTML = `
        <span class="toast-icone">${icones[tipo] || 'ℹ'}</span>
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
    toast.setAttribute('role', 'status');
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
            'Nenhuma indexação foi concluída ainda. Depois de analisar suas ' +
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
        `${t.indexados || 0} ${t.indexados === 1 ? 'arquivo indexado' : 'arquivos indexados'}` +
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
    linha.appendChild(parte(pasta.indexados || 0, 'indexados',
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

        currentConfig.cor_primaria = currentConfig.cor_primaria || "#A855F7";
        currentConfig.cor_secundaria = currentConfig.cor_secundaria || "#E879F9";
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
    tempConfig.cor_primaria = "#A855F7";
    tempConfig.cor_secundaria = "#E879F9";
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

// Rótulos e ícones amigáveis por categoria
const _CATEGORIA_LABEL = {
    pessoas:  { icone: '👥', nome: 'Pessoas' },
    animais:  { icone: '🐾', nome: 'Animais' },
    comida:   { icone: '🍽️', nome: 'Comida' },
    natureza: { icone: '🌳', nome: 'Natureza' },
    urbano:   { icone: '🏙️', nome: 'Urbano' },
    desenhos: { icone: '🎨', nome: 'Desenhos e Arte' },
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
            const meta = _CATEGORIA_LABEL[c.categoria] || { icone: '📦', nome: c.categoria };
            const pct = maxVal > 0 ? Math.round((c.total / maxVal) * 100) : 0;
            const row = document.createElement('div');
            row.style.cssText = 'display:flex; align-items:center; gap:10px; font-size:0.85rem;';
            // Estrutura: ícone+nome | barra | contagem (tudo via DOM, sem innerHTML de dado externo)
            const label = document.createElement('span');
            label.style.cssText = 'width:90px; color:var(--text-primary);';
            label.textContent = `${meta.icone} ${meta.nome}`;
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
        lupa.textContent = '🔍';

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
    if (btn) { btn.innerText = '⏳ Enfileirando...'; btn.disabled = true; }
    else { toastInfo('Reanalisando arquivos com descrição ruim...'); }
    try {
        const res = await fetch(`${API_BASE_URL}/api/reanalyze`, { method: 'POST' });
        const data = await res.json();
        // Imagens com descrição em formato antigo não vão pra fila: elas são
        // redescritas sozinhas na próxima busca em que aparecerem.
        const limpas = data.descricoes_limpas || 0;
        const extra = limpas ? ` + ${limpas} imagem(ns) marcada(s) pra redescrever` : '';
        if (btn) {
            btn.innerText = `✅ ${data.reenfileirados} arquivo(s) na fila!`;
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
    return av;
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

function popularDashboard(resultados) {
    const rGridImg = document.getElementById('recentImgs');
    const rGridDoc = document.getElementById('recentDocs');
    rGridImg.innerHTML = ''; rGridDoc.innerHTML = '';

    let imgs = 0, docs = 0;
    resultados.forEach(r => {
        const ext = r.tipo.toLowerCase();
        if (extensoesImagem.includes(ext) && imgs < 4) {
            rGridImg.innerHTML += `<div class="recent-card" onclick="abrirPainelPeloNome('${r.nome}')"><div class="recent-img"><img src="${formatImagePath(r.caminho)}" alt="${_attr(textoAlternativo(r))}"></div><p>${r.nome}</p></div>`;
            imgs++;
        } else if (!extensoesImagem.includes(ext) && docs < 4) {
            rGridDoc.innerHTML += `<div class="recent-card" onclick="abrirPainelPeloNome('${r.nome}')"><div class="recent-img doc-icon">${ext.toUpperCase()}</div><p>${r.nome}</p></div>`;
            docs++;
        }
    });
}

function abrirPainelPeloNome(nome) {
    const idx = window.resultadosAtuais.findIndex(r => r.nome === nome);
    if (idx !== -1) abrirPainelLateral(idx);
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
        list.innerHTML = '<p style="color:var(--text-secondary);">Nenhuma pasta monitorada.</p>';
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
    const btn = document.getElementById('btnAdicionarPasta'); btn.innerText = "⏳ Abrindo Windows...";
    const res = await fetch(`${API_BASE_URL}/api/choose_folder`); const data = await res.json();
    if (data.status === "sucesso") {
        btn.innerText = "⏳ Salvando...";
        const updateRes = await fetch(`${API_BASE_URL}/api/folders`, {
            method: 'POST', headers: fetchOptions.headers,
            body: JSON.stringify({ pasta: data.pasta, prioridades: ['tudo'], perfil_analise: 'fast', janela_processamento: 'always' })
        });
        const config = await updateRes.json();
        atualizarListaModalPastas(config.pastas);
        toastInfo("Pasta adicionada. Clique em \"Analisar Pastas\" quando quiser iniciar a IA.");
    }
    btn.innerText = "+ Importar Nova Pasta";
}

async function removerPasta(p) {
    if (!await confirmarAcao("Remover pasta", "Remover pasta monitorada? A IA não buscará mais nela.", "Remover")) return;
    const res = await fetch(`${API_BASE_URL}/api/folders`, { method: 'DELETE', headers: fetchOptions.headers, body: JSON.stringify({ pasta: p }) });
    const config = await res.json();
    atualizarListaModalPastas(config.pastas);
}

async function forcarAnalise() {
    const btn = document.getElementById('btnAnalisarPastas');
    const textoOriginal = btn.innerHTML;
    btn.innerHTML = "⏳ Atualizando embeddings...";
    btn.disabled = true;
    try {
        // 1. Re-gera embeddings dos arquivos já processados (rápido, sem LLaVA)
        await fetch(`${API_BASE_URL}/api/reembed`, { method: 'POST', headers: fetchOptions.headers });
        btn.innerHTML = "⏳ Sincronizando com a IA...";
        // 2. Escaneia pastas em busca de arquivos novos
        await fetch(`${API_BASE_URL}/api/analyze_folders`, { method: 'POST', headers: fetchOptions.headers });
        btn.innerHTML = "✅ Análise Iniciada!";
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
            `onclick="toggleFavorito(event, ${r.id}, this)">${r.favorito ? ICONE_FAV.sim : ICONE_FAV.nao}</button>`;

        // Seleção ≠ favorito: caixa quadrada à esquerda, coração à direita.
        // O estado vem do Set em memória, não do DOM — o grid é reconstruído
        // inteiro a cada troca de filtro e levaria a marcação junto.
        const sel = _selecionados.has(r.id);
        const selBtn = `<button type="button" class="btn-sel-abs${sel ? ' is-sel' : ''}" role="checkbox" aria-checked="${sel}" aria-label="Selecionar para coleção" title="Selecionar para coleção" onclick="alternarSelecao(event, ${r.id}, this)">${sel ? '✓' : ''}</button>`;

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
        titulo.textContent = 'Nenhum arquivo indexado ainda';
        motivo.textContent =
            'O Search+ só encontra o que já analisou. Adicione uma pasta do seu ' +
            'computador para ele começar a indexar as imagens e documentos.';
        box.appendChild(_botaoVazio('Gerenciar pastas', () => {
            if (typeof abrirModalPastas === 'function') abrirModalPastas();
        }));
        return;
    }

    // Causa 3 — há acervo, a frase é que não casou. Sugere o que EXISTE:
    // categorias com conteúdo levam a resultado garantido, ao contrário de um
    // "você quis dizer" adivinhado que também não acharia nada.
    motivo.textContent = indexados
        ? `Há ${indexados} ${indexados === 1 ? 'arquivo indexado' : 'arquivos indexados'}, ` +
          'mas nenhum corresponde a essa descrição. Tente palavras mais gerais — ' +
          'a busca entende o significado, não o nome do arquivo.'
        : 'Tente palavras mais gerais — a busca entende o significado da imagem, ' +
          'não o nome do arquivo.';

    if (categorias.length > 0) {
        box.appendChild(_secaoSugestoes(
            'Talvez você queira dizer:',
            categorias.slice(0, 6).map(c => {
                const meta = _CAT_GALERIA[c.categoria] || { icone: '📁', nome: c.categoria };
                return { rotulo: `${meta.icone} ${meta.nome}`, badge: c.total, termo: meta.nome };
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
        chip.textContent = it.rotulo;
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

        if (dados.resultados && dados.resultados.length > 0) {
            list.innerHTML = '';
            dados.resultados.forEach(r => {
                const ext = r.tipo.toLowerCase();
                let iconText = "";
                if (extensoesVideo.includes(ext)) iconText = "🎥";
                else if (extensoesAudio.includes(ext)) iconText = "🎵";
                else if (extensoesImagem.includes(ext)) iconText = "";

                let thumbHtml = `<div class="fav-thumb" style="display:flex; align-items:center; justify-content:center; font-size:1.5rem;">${iconText}</div>`;
                if (extensoesImagem.includes(ext)) {
                    thumbHtml = `<img src="${formatImagePath(r.caminho)}" class="fav-thumb" alt="${_attr(textoAlternativo(r))}">`;
                }

                const dataAdd = r.data ? new Date(r.data).toLocaleDateString('pt-BR') : "Desconhecido";

                const card = `
                <div class="fav-card" id="favCard_${r.id}">
                    ${thumbHtml}
                    <div class="fav-info">
                        <strong>${r.nome}</strong>
                        <span>${ext.toUpperCase()}</span>
                        <span>Adicionado: ${dataAdd}</span>
                    </div>
                    <div class="fav-actions">
                        <button type="button" class="btn-fav-icon" aria-label="Remover dos favoritos" title="Remover dos favoritos" onclick="toggleFavorito(event, ${r.id}, null, true)">${ICONE_FAV.sim}</button>
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

// Coração vazado x preenchido. São glifos de TEXTO, não emoji: o emoji 🤍 vem
// com cor própria e ignora `color`, então a regra `.is-fav` não conseguia
// pintá-lo. O favoritado chegava a renderizar string vazia — um círculo em
// branco, sem indicação nenhuma de que estava favoritado.
const ICONE_FAV = { sim: '♥', nao: '♡' };

function aplicarEstadoFavorito(btn, isFav) {
    if (!btn) return;
    btn.classList.toggle('is-fav', !!isFav);
    btn.textContent = isFav ? ICONE_FAV.sim : ICONE_FAV.nao;
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

            if (btnElement) aplicarEstadoFavorito(btnElement, isFav);

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
                if (extensoesVideo.includes(ext)) iconText = "🎥";
                else if (extensoesAudio.includes(ext)) iconText = "🎵";
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
                    <button type="button" class="btn-fav-abs is-fav" aria-pressed="true" aria-label="Remover dos favoritos" title="Remover dos favoritos" onclick="event.stopPropagation(); toggleFavorito(event, ${r.id}, this, true)" style="top:5px; right:5px; width:30px; height:30px; pointer-events: auto;">${ICONE_FAV.sim}</button>
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
    pessoas:  { icone: '👥', nome: 'Pessoas' },
    animais:  { icone: '🐾', nome: 'Animais' },
    comida:   { icone: '🍽️', nome: 'Comida' },
    natureza: { icone: '🌳', nome: 'Natureza' },
    urbano:   { icone: '🏙️', nome: 'Urbano' },
    desenhos: { icone: '🎨', nome: 'Desenhos e Arte' },
    outras:   { icone: '📦', nome: 'Outras' },
};

async function carregarGaleria() {
    const container = document.getElementById('galeriaCategorias');
    if (!container) return;
    try {
        const res = await fetch(`${API_BASE_URL}/api/gallery`, { headers: fetchOptions.headers });
        const d = await res.json();
        const grupos = d.grupos || [];
        container.innerHTML = '';
        if (grupos.length === 0) return;

        grupos.forEach(g => {
            const meta = _CAT_GALERIA[g.categoria] || { icone: '📁', nome: g.categoria };

            const secao = document.createElement('div');
            secao.style.cssText = 'margin-bottom: 32px;';

            const titulo = document.createElement('h3');
            titulo.style.cssText = 'color: var(--text-primary); margin: 0 0 14px 0; display:flex; align-items:center; gap:8px; justify-content:center;';
            titulo.textContent = `${meta.icone} ${meta.nome}`;
            const cont = document.createElement('span');
            cont.style.cssText = 'font-size:0.8rem; color:var(--text-secondary); font-weight:normal;';
            cont.textContent = `(${g.total})`;
            titulo.appendChild(cont);
            secao.appendChild(titulo);

            const grid = document.createElement('div');
            grid.className = 'recent-grid';

            // Guarda os itens do grupo numa janela global pra reusar o painel lateral
            g.itens.forEach(r => {
                const card = document.createElement('div');
                card.className = 'recent-card';
                card.onclick = () => abrirPainelGaleria(g.categoria, r.id);

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
    } catch (e) { console.error(e); }
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

async function buscarStatus() {
    const b = document.getElementById('statusBar');
    try {
        const res = await fetch(`${API_BASE_URL}/api/status`);
        const s = await res.json();
        const pend = s.arquivos_pendentes || 0;

        // Detecta transição fila>0 -> fila=0: análise terminou.
        // Só notifica se as notificações estiverem ativadas nas configs.
        if (_ultimaFila > 0 && pend === 0 && currentConfig.notificacoes !== false) {
            // Com o resumo a um clique: é o momento em que a pessoa está
            // olhando e a pergunta "entrou tudo?" está viva. Depois ela ainda
            // encontra o mesmo resumo nas Configurações.
            toastComAcao('Indexação concluída! Os arquivos já podem ser buscados.',
                         'Ver resumo', abrirResumoIndexacao);
        }
        _ultimaFila = pend;

        // Monta o texto do status
        let texto;
        if (pend > 0) {
            // "N na fila" não responde à pergunta que a pessoa tem: dá tempo
            // de almoçar? O tempo restante vem calibrado pelo ritmo que a
            // indexação está de fato conseguindo nesta máquina, e só aparece
            // quando o servidor tem medição suficiente para arriscar um número.
            const resta = s.restante_texto ? ` · ${s.restante_texto}` : '';
            texto = `🔍 Indexando arquivos — ${pend} na fila${resta}`;
        } else if (s.status && s.status.startsWith('Aguardando janela')) {
            texto = `🕐 ${s.status}`;
        } else if (s.status && s.status.startsWith('Escaneando')) {
            texto = `📂 ${s.status}`;
        } else {
            texto = "Motor pronto";
        }

        // Reconstrói a barra: texto (textContent, anti-XSS) + botão cancelar
        b.innerHTML = '';
        const span = document.createElement('span');
        span.textContent = texto;
        b.appendChild(span);

        if (pend > 0) {
            const btn = document.createElement('button');
            btn.textContent = '✕ Cancelar análise';
            btn.className = 'status-cancelar';
            btn.onclick = cancelarAnalise;
            b.appendChild(btn);
        }
        b.style.color = "var(--telemetry)";
    } catch (e) {
        b.textContent = "⚠ Servidor desconectado — verifique se o backend está rodando.";
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
// ATALHOS DE TECLADO
// ==========================================
// "/" foca a busca · "Esc" fecha janelas abertas
document.addEventListener('keydown', (e) => {
    // Esc: fecha o modal/painel aberto mais relevante
    if (e.key === 'Escape') {
        // Menu lateral aberto? fecha ele primeiro
        const ml = document.getElementById('menuLateral');
        if (ml && ml.classList.contains('aberto')) { fecharMenuLateral(); return; }
        const fechaveis = [
            ['statusPastaModal', () => { if (typeof fecharStatusPasta === 'function') fecharStatusPasta(); }],
            ['configColecaoModal', () => { if (typeof fecharConfigColecao === 'function') fecharConfigColecao(); }],
            ['exportarDeNovoModal', () => { if (typeof fecharExportarDeNovo === 'function') fecharExportarDeNovo(); }],
            ['pastasExportadasModal', () => { if (typeof fecharPastasExportadas === 'function') fecharPastasExportadas(); }],
            ['pastasColecaoModal', () => { if (typeof fecharPastasColecao === 'function') fecharPastasColecao(); }],
            ['vincularPastaModal', () => { if (typeof fecharVincularPasta === 'function') fecharVincularPasta(); }],
            ['exportModal', () => { if (typeof fecharExportacao === 'function') fecharExportacao(); }],
            ['escolherColecaoModal', () => { if (typeof fecharEscolherColecao === 'function') fecharEscolherColecao(); }],
            ['ajudaModal', fecharAjuda],
            ['cropperModal', () => { if (typeof fecharCropper === 'function') fecharCropper(); }],
            ['modalFavoritos', () => { if (typeof fecharFavoritos === 'function') fecharFavoritos(); }],
            ['foldersModal', () => { if (typeof fecharModalPastas === 'function') fecharModalPastas(); }],
            ['editPerfilModal', () => { if (typeof fecharEditPerfil === 'function') fecharEditPerfil(); }],
            ['viewPerfilModal', () => { if (typeof fecharViewPerfil === 'function') fecharViewPerfil(); }],
        ];
        for (const [id, fechar] of fechaveis) {
            const el = document.getElementById(id);
            if (el && getComputedStyle(el).display !== 'none') {
                fechar();
                return;
            }
        }
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

function alternarSelecao(event, fileId, btn) {
    event.stopPropagation();     // não abre o painel lateral
    const card = btn.closest('.card');

    if (_selecionados.has(fileId)) {
        _selecionados.delete(fileId);
        btn.classList.remove('is-sel');
        btn.textContent = '';
        btn.setAttribute('aria-checked', 'false');
        if (card) card.classList.remove('card-selecionado');
    } else {
        _selecionados.add(fileId);
        btn.classList.add('is-sel');
        btn.textContent = '✓';
        btn.setAttribute('aria-checked', 'true');
        if (card) card.classList.add('card-selecionado');
    }
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
        btn.textContent = sel ? '✓' : '';
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
    btn.textContent = todos ? '☒ Desmarcar tudo' : '☑ Selecionar tudo';
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
    await carregarColecoes();
}
function fecharColecoes() {
    document.getElementById('colecoesModal').style.display = 'none';
}

async function carregarColecoes() {
    const lista = document.getElementById('colecoesLista');
    lista.innerHTML = '<p style="color:var(--text-secondary);">Carregando...</p>';
    try {
        const res = await fetch(`${API_BASE_URL}/api/collections`);
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
            if (caps.length === 0) {
                capa.classList.add('colecao-capa-vazia');
                capa.textContent = '📁';
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
            delBtn.textContent = '🗑';
            delBtn.title = 'Excluir coleção';
            delBtn.onclick = (e) => { e.stopPropagation(); excluirColecao(c.id, c.nome); };

            info.append(titulo, meta);

            // Selo da pasta vinculada: o usuário precisa ver que a coleção
            // espelha algo no disco, e em que modo.
            if (c.pasta_vinculada) {
                const auto = c.modo_sync === 'auto';
                const selo = document.createElement('div');
                selo.className = 'colecao-vinculo' + (auto ? ' colecao-vinculo-auto' : '');
                selo.textContent = auto ? `↳ envia para ${_nomeDaPasta(c.pasta_vinculada)}`
                                        : `↳ pasta: ${_nomeDaPasta(c.pasta_vinculada)}`;
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
            `Lixeira. Os originais nas pastas monitoradas não são tocados. ` +
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
        btn.textContent = pastas.length > 1
            ? `📂 Abrir pasta exportada (${pastas.length})`
            : '📂 Abrir pasta exportada';
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
        toastAviso('Esta coleção ainda não tem pasta no computador. Use "Exportar coleção".');
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
        renomear.textContent = '✎';
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
                `com o nome anterior da coleção. Use o lápis em "Abrir pasta exportada" ` +
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
        p.textContent = 'Esta coleção ainda não tem pasta no computador. Use "Exportar coleção" para criar uma.';
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
      desc: 'Nada é copiado nem apagado sozinho. Use "Exportar coleção" e ' +
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
            'Use "Exportar coleção" para criar uma — só então o envio automático tem destino.';
    } else {
        const recebendo = pastas.filter(p => p.recebe);
        rodape.textContent = recebendo.length === 0
            ? `${pastas.length} ${pastas.length === 1 ? 'pasta criada' : 'pastas criadas'}, mas nenhuma marcada para receber. ` +
              'Escolha em "Abrir pasta exportada".'
            : `Destino: ${recebendo.map(p => p.nome).join(', ')}. ` +
              'Para mudar, use "Abrir pasta exportada".';
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
    btn.textContent = caixas.some(cb => !cb.checked)
        ? '☑ Enviar para todas as pastas'
        : '☐ Não enviar para nenhuma';
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
    _colecaoAtual = { id, nome };
    document.getElementById('colecoesTitulo').innerText = nome;
    const btnRen = document.getElementById('btnRenomearColecao');
    if (btnRen) btnRen.style.display = 'inline-block';
    document.getElementById('colecoesLista').style.display = 'none';
    document.getElementById('colecoesCriar').style.display = 'none';
    document.getElementById('colecaoConteudo').style.display = 'block';
    atualizarBotaoAbrirPasta(id);
    const grid = document.getElementById('colecaoItens');
    grid.innerHTML = '<p style="color:var(--text-secondary);">Carregando...</p>';
    try {
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

            grid.appendChild(card);
        });
    } catch (e) {
        console.error(e);
        grid.innerHTML = '<p style="color:#f87171;">Erro ao carregar.</p>';
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
            toastErro(d.error || 'A pasta vinculada não está mais no lugar.');
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
        ? `"${nome}" está vinculada a "${_nomeDaPasta(pastaCriada)}". Novas imagens vão sozinhas.`
        : `"${nome}" está vinculada a "${_nomeDaPasta(pastaCriada)}".`);
    return modo;
}

// ==========================================
// EXPORTAR COLEÇÃO PARA UMA PASTA LOCAL
// ==========================================
// Exportar aqui é copiar arquivo local → pasta local. O backend roda na
// máquina do usuário, então quem cria a pasta e copia é o Python.

let _exportJobId = null;
let _exportTimer = null;

async function exportarColecao() {
    if (!_colecaoAtual.id) return;

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
        const corpo = { destino };
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
            `"${base}" já foi exportada para ${existentes.length === 1 ? 'uma pasta' : `${existentes.length} pastas`}. ` +
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
        titulo.textContent = 'Coleção exportada — parcialmente';
        h.textContent = `${d.copiados} de ${d.total} imagens salvas em ${d.pasta}`;
    } else {
        titulo.textContent = '✓ Coleção exportada';
        h.textContent = `${d.copiados} ${d.copiados === 1 ? 'imagem salva' : 'imagens salvas'} em ${d.pasta}`;
    }
    box.appendChild(h);

    // Lista nominal das falhas: um número solto não deixa o usuário
    // reconciliar a coleção com o disco (RF-053).
    if (d.falhas.length > 0) {
        const MOTIVOS = {
            nao_encontrado: 'não encontrada (movida ou apagada)',
            sem_permissao: 'sem permissão de leitura',
            fora_das_pastas: 'fora das pastas monitoradas',
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
