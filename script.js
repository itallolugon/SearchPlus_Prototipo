const API_BASE_URL = 'http://127.0.0.1:5000';
let currentConfig = {};
let tempConfig = {};

let cropper;
let targetCropInput = '';
let searchHistoryExists = false;

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

// Atalhos semânticos
const toastOk   = (m) => mostrarToast(m, 'sucesso');
const toastErro = (m) => mostrarToast(m, 'erro', 6000);
const toastInfo = (m) => mostrarToast(m, 'info');
const toastAviso = (m) => mostrarToast(m, 'aviso', 5500);

const dicasUX = [
    "A IA faz buscas semânticas. Descreva o arquivo com linguagem natural.",
    "O motor lê textos dentro de Imagens e PDFs automaticamente.",
    "Pesquise algo como: 'Planilha financeira do ano passado'.",
    "Personalize o aplicativo usando o menu do seu perfil."
];
let tipInterval;

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
    await carregarConfiguracoesUX();
    document.getElementById('onboardingOverlay').style.display = 'none';

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
    if (!confirm("Tem certeza que deseja limpar todo o histórico de busca?")) return;
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
    if (!confirm("ATENÇÃO: Isto vai apagar todas as descrições e vetores da IA gerados até agora. O motor precisará reanalisar todos os arquivos do zero. Deseja continuar?")) return;
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
    document.getElementById('searchInput').value = query;
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
        if (btn) {
            btn.innerText = `✅ ${data.reenfileirados} arquivo(s) na fila!`;
            setTimeout(() => { btn.innerText = 'Re-analisar Arquivos com Descrição Ruim'; btn.disabled = false; }, 3000);
        } else {
            toastOk(`${data.reenfileirados} arquivo(s) na fila de reanálise.`);
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
    document.getElementById('searchInput').value = '';
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

        if (searchHistoryExists) {
            document.getElementById('dashboardView').style.display = 'block';
            carregarFavoritosDash();
            carregarGaleria();
            setTimeout(() => {
                document.getElementById('dashboardView').classList.remove('fade-out');
                document.getElementById('dashboardView').style.opacity = '1';
            }, 50);
        }
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

    searchHistoryExists = true;

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
            rGridImg.innerHTML += `<div class="recent-card" onclick="abrirPainelPeloNome('${r.nome}')"><div class="recent-img"><img src="${formatImagePath(r.caminho)}"></div><p>${r.nome}</p></div>`;
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
                <button class="btn-config-folder" onclick="abrirConfigPasta(${fId}, '${escapedPath}')">Config</button>
                <button class="btn-remover" onclick="removerPasta('${escapedPath}')">Excluir</button>
            </div>
        </div>`;
    });
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
    }
    btn.innerText = "+ Importar Nova Pasta";
}

async function removerPasta(p) {
    if (!confirm("Remover pasta monitorada? A IA não buscará mais nela.")) return;
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

function renderizarResultados() {
    const mGrid = document.getElementById('melhoresGrid'); const oGrid = document.getElementById('outrasGrid');
    mGrid.innerHTML = ''; oGrid.innerHTML = '';

    const filtrados = window.resultadosAtuais.filter(r => {
        const ext = r.tipo.toLowerCase();
        if (filtroAtual === 'all') return true;
        if (filtroAtual === 'imagem') return extensoesImagem.includes(ext);
        if (filtroAtual === 'midia') return extensoesAudio.includes(ext) || extensoesVideo.includes(ext);
        return !extensoesImagem.includes(ext) && !extensoesAudio.includes(ext) && !extensoesVideo.includes(ext);
    });

    if (filtrados.length > 0) {
        document.getElementById('tituloMelhores').style.display = 'block'; document.getElementById('tituloSemantica').style.display = 'block';
    } else {
        document.getElementById('tituloMelhores').style.display = 'none'; document.getElementById('tituloSemantica').style.display = 'none';
        mGrid.innerHTML = '<p style="text-align:center; width:100%; color:var(--text-secondary);">Nada encontrado.</p>'; return;
    }

    const melhores = filtrados.filter(r => r.score >= 0.60); const outras = filtrados.filter(r => r.score < 0.60);

    const buildCard = (r) => {
        const ext = r.tipo.toLowerCase(); const link = formatImagePath(r.caminho);
        let midia = `<div class="document-icon-wrapper"><svg viewBox='0 0 24 24'><path d='M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2h12c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z'/></svg></div>`;
        if (extensoesVideo.includes(ext)) midia = `<video controls><source src="${link}"></video>`;
        else if (extensoesAudio.includes(ext)) midia = `<audio controls><source src="${link}"></audio>`;
        else if (extensoesImagem.includes(ext)) midia = `<img src="${link}">`;

        const idx = window.resultadosAtuais.indexOf(r);
        let trecho = r.trecho && r.trecho !== "Nenhum conteúdo..." ? `<div class="trecho-preview">"${r.trecho}"</div>` : '';

        const favClass = r.favorito ? 'is-fav' : '';
        const favIcon = r.favorito ? '' : '🤍';
        const favBtn = `<div class="btn-fav-abs ${favClass}" onclick="toggleFavorito(event, ${r.id}, this)">${favIcon}</div>`;

        return `<div class="card" data-idx="${idx}" onclick="abrirPainelLateral(${idx})" onmouseenter="mostrarHoverPreview(event, ${idx})" onmousemove="moverHoverPreview(event)" onmouseleave="esconderHoverPreview()">${favBtn}<div class="media-container">${midia}</div><div class="card-content"><h3>${r.nome}</h3><div class="tags"><span class="badge type">${ext.toUpperCase()}</span><span class="badge score">SCORE: ${Math.round(r.score * 100)}%</span></div>${trecho}</div></div>`;
    };

    melhores.forEach(r => mGrid.innerHTML += buildCard(r));
    outras.forEach(r => oGrid.innerHTML += buildCard(r));
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
    document.getElementById('sideBadgeScore').innerText = `SCORE: ${Math.round(res.score * 100)}%`;
    document.getElementById('sideDownloadBtn').href = formatImagePath(res.caminho);

    const ext = res.tipo.toLowerCase(); const link = formatImagePath(res.caminho);
    const mediaBox = document.getElementById('sideMediaPreview');
    if (extensoesVideo.includes(ext)) mediaBox.innerHTML = `<video controls autoplay><source src="${link}"></video>`;
    else if (extensoesAudio.includes(ext)) mediaBox.innerHTML = `<audio controls autoplay><source src="${link}"></audio>`;
    else if (extensoesImagem.includes(ext)) mediaBox.innerHTML = `<img src="${link}">`;
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
                    thumbHtml = `<img src="${formatImagePath(r.caminho)}" class="fav-thumb">`;
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
                        <button class="btn-fav-icon" onclick="toggleFavorito(event, ${r.id}, null, true)"></button>
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

            if (btnElement) {
                if (isFav) {
                    btnElement.classList.add('is-fav');
                    btnElement.innerText = '';
                } else {
                    btnElement.classList.remove('is-fav');
                    btnElement.innerText = '🤍';
                }
            }

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
                    midia = `<div class="recent-img"><img src="${formatImagePath(r.caminho)}"></div>`;
                }

                const cardBox = `<div class="recent-card" onclick="abrirFavoritos()" id="favDash_${r.id}">
                    <div style="position:relative; width:100%; height:100%; pointer-events: none;">
                        ${midia}
                    </div>
                    <p style="pointer-events: auto;">${r.nome}</p>
                    <button class="btn-fav-abs is-fav" onclick="event.stopPropagation(); toggleFavorito(event, ${r.id}, this, true)" style="top:5px; right:5px; width:30px; height:30px; pointer-events: auto;"></button>
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

// Função placeholder para limpar busca (usada no logout)
function limparBusca() {
    document.getElementById('searchInput').value = '';
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
            toastOk("Análise concluída! Os arquivos já podem ser buscados.");
        }
        _ultimaFila = pend;

        // Monta o texto do status
        let texto;
        if (pend > 0) {
            texto = `🔍 Analisando arquivos — ${pend} na fila`;
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
// COLEÇÕES (playlists de arquivos)
// ==========================================
let _fileIdAtual = null;

async function abrirColecoes() {
    document.getElementById('colecoesModal').style.display = 'flex';
    document.getElementById('colecoesTitulo').innerText = 'Minhas Coleções';
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
            carregarColecoes();
        } else {
            toastErro(d.error || "Não foi possível criar a coleção.");
        }
    } catch (e) { console.error(e); toastErro("Erro de conexão."); }
}

async function excluirColecao(id, nome) {
    if (!confirm(`Excluir a coleção "${nome}"? Os arquivos não são apagados, só a coleção.`)) return;
    try {
        await fetch(`${API_BASE_URL}/api/collections/${id}`, { method: 'DELETE' });
        toastInfo(`Coleção "${nome}" excluída.`);
        carregarColecoes();
    } catch (e) { console.error(e); toastErro("Não foi possível excluir."); }
}

let _colecaoAtual = { id: null, nome: '' };

async function verColecao(id, nome) {
    _colecaoAtual = { id, nome };
    document.getElementById('colecoesTitulo').innerText = nome;
    document.getElementById('colecoesLista').style.display = 'none';
    document.getElementById('colecoesCriar').style.display = 'none';
    document.getElementById('colecaoConteudo').style.display = 'block';
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
            toastInfo(`"${nomeArquivo}" removido da coleção.`);
            verColecao(_colecaoAtual.id, _colecaoAtual.nome);  // recarrega a coleção
        } else {
            toastErro("Não foi possível remover.");
        }
    } catch (e) { console.error(e); toastErro("Erro de conexão."); }
}

// Adicionar o arquivo aberto no painel lateral a uma coleção
async function abrirSeletorColecao() {
    if (!_fileIdAtual) { toastAviso("Abra um arquivo primeiro."); return; }
    try {
        const res = await fetch(`${API_BASE_URL}/api/collections`);
        const d = await res.json();
        const cols = d.colecoes || [];
        if (cols.length === 0) {
            const nome = prompt("Você ainda não tem coleções. Nome da nova coleção:");
            if (!nome || !nome.trim()) return;
            const cr = await fetch(`${API_BASE_URL}/api/collections`, {
                method: 'POST', headers: fetchOptions.headers,
                body: JSON.stringify({ nome: nome.trim() })
            });
            const cd = await cr.json();
            if (cr.ok) await adicionarAColecao(cd.id, nome.trim());
            else toastErro(cd.error || "Erro ao criar coleção.");
            return;
        }
        const nomes = cols.map((c, i) => `${i + 1}. ${c.nome} (${c.total})`).join('\n');
        const escolha = prompt(`Adicionar a qual coleção?\n\n${nomes}\n\nDigite o número:`);
        const idx = parseInt(escolha, 10) - 1;
        if (isNaN(idx) || idx < 0 || idx >= cols.length) return;
        await adicionarAColecao(cols[idx].id, cols[idx].nome);
    } catch (e) { console.error(e); toastErro("Erro de conexão."); }
}

async function adicionarAColecao(colId, nome) {
    try {
        const res = await fetch(`${API_BASE_URL}/api/collections/${colId}/files`, {
            method: 'POST', headers: fetchOptions.headers,
            body: JSON.stringify({ file_id: _fileIdAtual })
        });
        if (res.ok) toastOk(`Adicionado à coleção "${nome}".`);
        else toastErro("Não foi possível adicionar.");
    } catch (e) { console.error(e); toastErro("Erro de conexão."); }
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
        searchHistoryExists = true;
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
