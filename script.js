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
    } catch (e) { console.error("Servidor API offline."); }
};

// ==========================================
// SELETOR E CROPPER DE IMAGEM
// ==========================================
async function selecionarImagemExplorer(inputId) {
    try {
        const res = await fetch(`${API_BASE_URL}/api/choose_image`);
        const data = await res.json();

        if (data.status === "sucesso") {
            const imgPath = formatImagePath(data.caminho);
            targetCropInput = inputId;
            abrirEditorCorte(imgPath, inputId);
        }
    } catch (e) { console.error("Erro ao selecionar imagem:", e); }
}

function abrirEditorCorte(imgSrc, inputId) {
    const cropImg = document.getElementById('cropperImage');
    cropImg.crossOrigin = "use-credentials";
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

        if (!canvas) { alert("Erro: Não foi possível processar a área recortada."); return; }

        const croppedDataUrl = canvas.toDataURL('image/jpeg', isHighRes ? 0.8 : 0.6);
        const targetEl = document.getElementById(targetCropInput);
        if (targetEl) targetEl.value = croppedDataUrl;

        aplicarCorteNoPreview(targetCropInput, croppedDataUrl);
        fecharCropper();
    } catch (e) {
        console.error("Erro no Cropper:", e);
        alert("Erro de Segurança (CORS) ao processar imagem, ou imagem é inválida. Tente outra imagem.");
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

    if (!user || !pass) { alert("Preencha usuário e senha."); return; }

    try {
        const res = await fetch(`${API_BASE_URL}/api/login`, { method: 'POST', headers: fetchOptions.headers, body: JSON.stringify({ username: user, password: pass }) });
        if (res.ok) {
            if (lembrar) localStorage.setItem('searchplus_user', user);
            else localStorage.removeItem('searchplus_user');
            loginBemSucedido(user);
        } else { const data = await res.json(); alert(data.mensagem); }
    } catch (e) {
        console.error(e);
        alert("Erro fatal de conexão. Verifique se o servidor Python está rodando e recarregue a página.");
    }
}

async function fazerCadastro() {
    const user = document.getElementById('regUser').value.trim();
    const handle = document.getElementById('regHandle').value.trim();
    const pass = document.getElementById('regPass').value.trim();
    if (!user || !pass || !handle) { alert("Preencha usuário, handle e senha."); return; }

    try {
        const res = await fetch(`${API_BASE_URL}/api/register`, { method: 'POST', headers: fetchOptions.headers, body: JSON.stringify({ username: user, handle: handle, password: pass }) });
        if (res.ok) { document.getElementById('loginUser').value = user; document.getElementById('loginPass').value = pass; fazerLogin(); }
        else { const data = await res.json(); alert(data.mensagem); }
    } catch (e) { alert("Erro de conexão com o banco de dados."); }
}

async function loginBemSucedido(username) {
    await carregarConfiguracoesUX();
    await carregarHistorico();

    const handle = currentConfig.perfil_handle || username;

    document.getElementById('dropHandle').innerText = '@' + handle;
    document.getElementById('dashHandle').innerText = '@' + handle;

    document.getElementById('authOverlay').style.display = 'none';
    verificarOnboarding();
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
    } catch (e) { console.error("Erro ao remover pasta:", e); }
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
        alert("Por favor, adicione pelo menos uma pasta para a IA monitorar antes de concluir.");
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
        safeSetCheck('cgIniciarSistema', currentConfig.iniciar_sistema);
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

function abrirViewPerfil() {
    document.getElementById('statPastas').innerText = currentConfig.pastas ? currentConfig.pastas.length : 0;
    document.getElementById('statArquivos').innerText = window.resultadosAtuais.length > 0 ? "100+" : "0";

    document.getElementById('viewPerfilModal').style.display = 'flex';
    document.getElementById('profileDropdown').style.display = 'none';
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
    currentConfig.notificacoes = document.getElementById('cgNotificacoes').checked;
    currentConfig.atalho_busca = document.getElementById('cgAtalho').value.trim();
    currentConfig.iniciar_sistema = document.getElementById('cgIniciarSistema').checked;
    currentConfig.modo_privado = document.getElementById('cgModoPrivado').checked;
    currentConfig.pastas_ignoradas = document.getElementById('cgPastasIgnoradas').value.trim();
    currentConfig.modo_desempenho = document.getElementById('cgModoDesempenho').value;

    await fetch(`${API_BASE_URL}/api/config`, { 
        method: 'POST', 
        headers: fetchOptions.headers, 
        body: JSON.stringify(currentConfig) 
    });
    fecharModalConfigGerais();
}

async function limparHistoricoBusca() {
    if (confirm("Tem certeza que deseja limpar todo o histórico de busca?")) {
        await fetch(`${API_BASE_URL}/api/clear_history`, { method: 'POST' });
        window.searchHistoryExists = false;
        document.getElementById('searchHistoryList').innerHTML = "";
        alert("Histórico de busca limpo com sucesso!");
    }
}

async function limparCacheIA() {
    if (confirm("ATENÇÃO: Isto irá apagar todas as descrições e vetores da IA gerados até agora. O motor precisará reanalisar todos os arquivos nas pastas configuradas do zero. Deseja continuar?")) {
        await fetch(`${API_BASE_URL}/api/clear_cache`, { method: 'POST' });
        alert("Banco de dados da IA foi limpo! A análise recomeçará em breve.");
    }
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
            alert("Erro ao salvar perfil.");
        }
    } catch (e) {
        console.error("Erro de rede:", e);
        alert("Erro de conexão ao salvar perfil.");
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

function mostrarHistorico() {
    if (_historicoCache.length === 0) return;
    const dropdown = document.getElementById('searchHistoryDropdown');
    const list = document.getElementById('searchHistoryList');
    list.innerHTML = _historicoCache.map((q, i) => `
        <div style="display:flex; align-items:center; justify-content:space-between; padding:10px 16px; cursor:pointer; border-bottom:1px solid var(--border-light); transition:background 0.15s;"
             onmouseenter="this.style.background='rgba(168,85,247,0.1)'" onmouseleave="this.style.background='transparent'">
            <span onclick="usarHistorico('${q.replace(/'/g, "\\'")}')" style="flex:1; color:var(--text-primary); font-size:0.95rem;">${q}</span>
            <span onclick="removerHistorico(${i})" style="color:var(--text-secondary); font-size:1.2rem; padding:0 4px; line-height:1;">&times;</span>
        </div>`).join('');
    dropdown.style.display = 'block';
}

function esconderHistorico() {
    document.getElementById('searchHistoryDropdown').style.display = 'none';
}

function usarHistorico(query) {
    document.getElementById('searchInput').value = query;
    esconderHistorico();
    realizarBusca();
}

async function removerHistorico(index) {
    await fetch(`${API_BASE_URL}/api/search_history/${index}`, { method: 'DELETE' });
    await carregarHistorico();
    mostrarHistorico();
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
    const btn = document.getElementById('btnReanalizar');
    btn.innerText = '⏳ Enfileirando...'; btn.disabled = true;
    try {
        const res = await fetch(`${API_BASE_URL}/api/reanalyze`, { method: 'POST' });
        const data = await res.json();
        btn.innerText = `✅ ${data.reenfileirados} arquivo(s) na fila!`;
        setTimeout(() => { btn.innerText = 'Re-analisar Arquivos com Descrição Ruim'; btn.disabled = false; }, 3000);
    } catch(e) {
        btn.innerText = 'Re-analisar Arquivos com Descrição Ruim'; btn.disabled = false;
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
            setTimeout(() => {
                document.getElementById('dashboardView').classList.remove('fade-out');
                document.getElementById('dashboardView').style.opacity = '1';
            }, 50);
        }
    }, 400);
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
        const res = await fetch(`${API_BASE_URL}/api/search`, { method: 'POST', headers: fetchOptions.headers, body: JSON.stringify({ query: query, filtro: filtroAtual }) });
        const dados = await res.json();
        window.resultadosAtuais = Array.isArray(dados) ? dados : (dados.resultados || []);
        salvarBuscaNoHistorico(query.trim());

    } catch (e) { console.error("Erro na busca."); } finally {
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

        return `<div class="card" onclick="abrirPainelLateral(${idx})">${favBtn}<div class="media-container">${midia}</div><div class="card-content"><h3>${r.nome}</h3><div class="tags"><span class="badge type">${ext.toUpperCase()}</span><span class="badge score">SCORE: ${Math.round(r.score * 100)}%</span></div>${trecho}</div></div>`;
    };

    melhores.forEach(r => mGrid.innerHTML += buildCard(r));
    outras.forEach(r => oGrid.innerHTML += buildCard(r));
}

function abrirPainelLateral(id) {
    const res = window.resultadosAtuais[id];
    const q = document.getElementById('searchInput').value.trim().toLowerCase();

    _caminhoArquivoAtual = res.caminho;

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
        console.error("Erro ao favoritar", e);
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

                const cardBox = `<div class="recent-card" onclick="alert('Inspecionado nos favoritos!')" id="favDash_${r.id}">
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
async function buscarStatus() {
    try {
        const res = await fetch(`${API_BASE_URL}/api/status`);
        const s = await res.json();
        const b = document.getElementById('statusBar');

        let statusTexto = s.status;

        if (s.arquivos_pendentes === 0 && s.arquivos_processados_sessao > 0) {
            statusTexto = "✅ Verificação Concluída";
        }

        let m = `Motor: ${statusTexto}`;
        if (s.arquivos_pendentes > 0) m += ` | ⏳ Fila: ${s.arquivos_pendentes}`;
        m += ` | 📦 Processados: ${s.arquivos_processados_sessao}`;

        b.innerText = m;
        b.style.color = "var(--telemetry)";
    } catch (e) {
        document.getElementById('statusBar').innerText = "API Desconectada.";
        document.getElementById('statusBar').style.color = "#ef4444";
    }
}
setInterval(buscarStatus, 2000);