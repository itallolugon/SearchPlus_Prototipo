const API_BASE_URL = 'http://127.0.0.1:5000';
let currentConfig = {};
let tempConfig = {}; 

let cropper; 
let targetCropInput = ''; 
let searchHistoryExists = false;

window.resultadosAtuais = [];
window.ultimoTempoBusca = 0;
let filtroAtual = 'all';

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
            if(document.getElementById('searchResultsView').style.display === 'block') {
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
    } catch(e) { console.error("Erro ao selecionar imagem:", e); }
}

function abrirEditorCorte(imgSrc, inputId) {
    const cropImg = document.getElementById('cropperImage');
    cropImg.crossOrigin = "use-credentials";
    cropImg.src = imgSrc;
    document.getElementById('cropperModal').style.display = 'flex';
    
    cropImg.onload = () => {
        if(cropper) { cropper.destroy(); cropper = null; }
        
        let ratio = NaN; 
        
        if (inputId.toLowerCase().includes('banner')) ratio = 16/9;
        else if (inputId.toLowerCase().includes('avatar')) ratio = 1/1;
        
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
    if(cropper) { cropper.destroy(); cropper = null; }
}

function salvarCropper() {
    if(!cropper) return;
    
    // COMPRESSÃO E LIMITES DE RESOLUÇÃO (Avatar = Quadrado Menor; Banner/Fundo = Alta Definição)
    const isHighRes = targetCropInput.toLowerCase().includes('banner') || targetCropInput === 'bgUrl';
    const canvas = cropper.getCroppedCanvas({ 
        maxWidth: isHighRes ? 1920 : 600, 
        maxHeight: isHighRes ? 1080 : 600 
    });
    
    if(!canvas) { alert("Erro ao processar imagem."); return; }
    
    const croppedDataUrl = canvas.toDataURL('image/jpeg', isHighRes ? 0.8 : 0.6);
    document.getElementById(targetCropInput).value = croppedDataUrl;
    
    aplicarCorteNoPreview(targetCropInput, croppedDataUrl);
    fecharCropper();
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
        tempConfig.bg_url = base64Img;
        aplicarLivePreviewUX(); 
    }
}

function removerImagemOnboarding(inputId) {
    document.getElementById(inputId).value = "";
    if(inputId === 'obAvatar') {
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
            if(lembrar) localStorage.setItem('searchplus_user', user); 
            else localStorage.removeItem('searchplus_user');
            loginBemSucedido(user);
        } else { const data = await res.json(); alert(data.mensagem); }
    } catch(e) { 
        console.error(e);
        alert("🚨 Erro fatal de conexão. Verifique se o servidor Python está rodando e recarregue a página."); 
    }
}

async function fazerCadastro() {
    const user = document.getElementById('regUser').value.trim();
    const pass = document.getElementById('regPass').value.trim();
    if (!user || !pass) { alert("Preencha usuário e senha."); return; }

    try {
        const res = await fetch(`${API_BASE_URL}/api/register`, { method: 'POST', headers: fetchOptions.headers, body: JSON.stringify({ username: user, password: pass }) });
        if (res.ok) { document.getElementById('loginUser').value = user; document.getElementById('loginPass').value = pass; fazerLogin(); }
        else {
            let msg = `Erro HTTP ${res.status}`;
            try { const data = await res.json(); msg = data.mensagem || msg; } catch(_) { msg += ' (resposta não-JSON — veja o terminal do servidor)'; }
            alert(msg);
        }
    } catch(e) { alert("Erro de rede: " + e.message); }
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
            await fetch(`${API_BASE_URL}/api/folders`, { method: 'POST', headers: fetchOptions.headers, body: JSON.stringify({ pasta: data.pasta }) });
            currentConfig.historico_pastas = true; 
            atualizarListaPastasOnboarding();
        }
    } catch(e){}
}

async function atualizarListaPastasOnboarding() {
    const res = await fetch(`${API_BASE_URL}/api/folders`);
    const config = await res.json();
    const list = document.getElementById('onboardingFoldersList');
    if(config.pastas && config.pastas.length > 0) {
        list.innerHTML = config.pastas.map(p => `<div style="color:var(--telemetry); padding: 5px 0; text-align:center;">✔️ ${p}</div>`).join('');
    } else {
        list.innerHTML = `<p style="color: var(--text-secondary); font-size: 0.9rem; text-align:center;">Nenhuma pasta selecionada ainda.</p>`;
    }
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
    
    if(!document.getElementById('obAvatar').value) {
        const url = formatImagePath(currentConfig.perfil_avatar);
        document.getElementById('obPreviewAvatar').src = url || placeholderPreto;
    }
    if(!document.getElementById('obBanner').value) {
        const bannerUrl = formatImagePath(currentConfig.perfil_banner);
        if(bannerUrl) document.getElementById('obPreviewBanner').style.backgroundImage = `url('${bannerUrl}')`;
        else document.getElementById('obPreviewBanner').style.backgroundImage = 'none';
    }
}

async function finalizarOnboarding() {
    const btn = document.getElementById('btnConcluirOnboarding');
    btn.innerText = "Salvando..."; btn.disabled = true;

    const foldersRes = await fetch(`${API_BASE_URL}/api/folders`);
    const foldersData = await foldersRes.json();
    if(!foldersData.pastas || foldersData.pastas.length === 0) {
        alert("Por favor, adicione pelo menos uma pasta para a IA monitorar antes de concluir.");
        voltarParaOnboardingStep1();
        btn.innerText = "Concluir ✔️"; btn.disabled = false;
        return;
    }

    currentConfig.perfil_nome = document.getElementById('obNome').value.trim() || currentConfig.perfil_nome;
    currentConfig.perfil_handle = document.getElementById('obHandle').value.trim() || currentConfig.perfil_handle;
    currentConfig.perfil_cargo = document.getElementById('obCargo').value.trim() || currentConfig.perfil_cargo;
    currentConfig.perfil_bio = document.getElementById('obBio').value.trim();
    
    if(document.getElementById('obAvatar').value) currentConfig.perfil_avatar = document.getElementById('obAvatar').value;
    if(document.getElementById('obBanner').value) currentConfig.perfil_banner = document.getElementById('obBanner').value;

    await fetch(`${API_BASE_URL}/api/config`, { method: 'POST', headers: fetchOptions.headers, body: JSON.stringify(currentConfig) });
    await carregarConfiguracoesUX(); 
    document.getElementById('onboardingOverlay').style.display = 'none';
    
    btn.innerText = "Concluir ✔️"; btn.disabled = false;
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
        
        document.getElementById('navAvatar').src = formatImagePath(currentConfig.perfil_avatar) || placeholderPreto;
        document.getElementById('dropAvatar').src = formatImagePath(currentConfig.perfil_avatar) || placeholderPreto;
        document.getElementById('dropName').innerText = currentConfig.perfil_nome;
        document.getElementById('dropHandle').innerText = '@' + currentConfig.perfil_handle;
        
        document.getElementById('viewAvatar').src = formatImagePath(currentConfig.perfil_avatar) || placeholderPreto;
        const bannerUrl = formatImagePath(currentConfig.perfil_banner);
        if(bannerUrl) document.getElementById('viewBanner').style.backgroundImage = `url('${bannerUrl}')`;
        else document.getElementById('viewBanner').style.backgroundImage = 'none';
        
        document.getElementById('viewProfileName').innerText = currentConfig.perfil_nome;
        document.getElementById('viewProfileHandle').innerText = '@' + currentConfig.perfil_handle;
        document.getElementById('viewProfileCargo').innerText = currentConfig.perfil_cargo || "Cargo não definido";
        document.getElementById('viewProfileLocal').innerText = "📍 " + (currentConfig.perfil_local || "Localização não definida");
        document.getElementById('viewProfileBio').innerText = currentConfig.perfil_bio;

        document.getElementById('editNome').value = currentConfig.perfil_nome;
        document.getElementById('editHandle').value = currentConfig.perfil_handle;
        document.getElementById('editCargo').value = currentConfig.perfil_cargo || "";
        document.getElementById('editLocal').value = currentConfig.perfil_local || "";
        document.getElementById('editBio').value = currentConfig.perfil_bio;
        
        document.getElementById('previewAvatar').src = formatImagePath(currentConfig.perfil_avatar) || placeholderPreto;
        document.getElementById('previewBanner').src = formatImagePath(currentConfig.perfil_banner) || placeholderPreto;
        document.getElementById('editAvatar').value = "";
        document.getElementById('editBanner').value = "";
        
        if (currentConfig.idioma) document.getElementById('idiomaSelect').value = currentConfig.idioma;

    } catch (e) { console.error("Erro ao carregar UX:", e); }
}

function aplicarLivePreviewUX() { aplicarTemaNoDOM(tempConfig); }
function setLiveTema(tema) { tempConfig.tema = tema; aplicarLivePreviewUX(); }

document.getElementById('corPrimaria').addEventListener('input', function() { tempConfig.cor_primaria = this.value; aplicarLivePreviewUX(); });
document.getElementById('corSecundaria').addEventListener('input', function() { tempConfig.cor_secundaria = this.value; aplicarLivePreviewUX(); });
document.getElementById('corTextoBotao').addEventListener('input', function() { tempConfig.cor_texto_botao = this.value; aplicarLivePreviewUX(); });
document.getElementById('idiomaSelect').addEventListener('change', function() { tempConfig.idioma = this.value; });
document.getElementById('bgBlur').addEventListener('input', function() { 
    document.getElementById('blurValue').innerText = this.value; 
    tempConfig.bg_blur = parseInt(this.value); 
    aplicarLivePreviewUX(); 
});

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

    const appBg = document.getElementById('appBackground');
    const realImg = document.getElementById('realBgImage');
    
    // Gradientes base continuam existindo
    appBg.style.backgroundImage = `radial-gradient(circle at 0% 100%, ${config.cor_primaria}26 0%, transparent 50%), radial-gradient(circle at 100% 0%, ${config.cor_secundaria}26 0%, transparent 40%)`; 
    
    if (config.bg_url && config.bg_url.trim() !== "") { 
        if(realImg) {
            realImg.src = formatImagePath(config.bg_url);
            realImg.style.display = 'block';
            realImg.style.filter = `blur(${config.bg_blur || 0}px)`;
            realImg.style.transition = 'filter 0.3s ease';
        }
    } 
    else { 
        if(realImg) realImg.style.display = 'none';
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
    
    document.getElementById('corPrimaria').value = tempConfig.cor_primaria;
    document.getElementById('corSecundaria').value = tempConfig.cor_secundaria;
    document.getElementById('corTextoBotao').value = tempConfig.cor_texto_botao;
    document.getElementById('bgUrl').value = tempConfig.bg_url;
    document.getElementById('previewBg').src = placeholderPreto; 
    document.getElementById('bgBlur').value = tempConfig.bg_blur;
    document.getElementById('blurValue').innerText = tempConfig.bg_blur;
    
    aplicarLivePreviewUX();
}

async function salvarConfiguracoesUX() {
    currentConfig = { ...tempConfig }; 
    await fetch(`${API_BASE_URL}/api/config`, { method: 'POST', headers: fetchOptions.headers, body: JSON.stringify(currentConfig) });
    fecharSidebarConfig();
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
    document.getElementById('corPrimaria').value = tempConfig.cor_primaria;
    document.getElementById('corSecundaria').value = tempConfig.cor_secundaria;
    document.getElementById('corTextoBotao').value = tempConfig.cor_texto_botao || '#FFFFFF';
    document.getElementById('bgUrl').value = tempConfig.bg_url;
    document.getElementById('previewBg').src = formatImagePath(tempConfig.bg_url) || placeholderPreto;
    document.getElementById('bgBlur').value = tempConfig.bg_blur;
    document.getElementById('blurValue').innerText = tempConfig.bg_blur;
    if(tempConfig.idioma) document.getElementById('idiomaSelect').value = tempConfig.idioma;

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
    if(newAvatar) currentConfig.perfil_avatar = newAvatar;
    if(newBanner) currentConfig.perfil_banner = newBanner;

    try {
        const res = await fetch(`${API_BASE_URL}/api/config`, { 
            method: 'POST', 
            headers: fetchOptions.headers, 
            body: JSON.stringify(currentConfig) 
        });
        
        if(res.ok) {
            await carregarConfiguracoesUX(); 
            fecharEditPerfil(); 
            abrirViewPerfil();
        } else {
            alert("Erro ao salvar perfil.");
        }
    } catch(e) {
        console.error("Erro de rede:", e);
        alert("Erro de conexão ao salvar perfil.");
    } finally {
        btn.innerText = "Salvar Alterações"; btn.disabled = false;
    }
}

// ==========================================
// BUSCA E DASHBOARD (SOFT TRANSITIONS GLOBAIS)
// ==========================================
function voltarParaHomeSmooth() {
    document.getElementById('searchInput').value = '';
    document.getElementById('searchResultsView').classList.add('fade-out');
    document.getElementById('searchResultsView').style.opacity = '0'; // Esconde na volta
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

// ==========================================
// HISTÓRICO DE BUSCAS
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
            <span onclick="usarHistorico('${q.replace(/'/g, "\\'")}')" style="flex:1; color:var(--text-primary); font-size:0.95rem;">🕐 ${q}</span>
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
    await fetch(`${API_BASE_URL}/api/search_history`, {
        method: 'POST',
        headers: fetchOptions.headers,
        body: JSON.stringify({ query })
    });
    _historicoCache = [query, ..._historicoCache.filter(q => q !== query)].slice(0, 10);
}

// ==========================================
// RE-ANÁLISE SELETIVA
// ==========================================
async function reAnalizarArquivos() {
    const btn = document.getElementById('btnReanalizar');
    btn.innerText = '⏳ Enfileirando...'; btn.disabled = true;
    try {
        const res = await fetch(`${API_BASE_URL}/api/reanalyze`, { method: 'POST' });
        const data = await res.json();
        btn.innerText = `✅ ${data.reenfileirados} arquivo(s) na fila!`;
        setTimeout(() => { btn.innerText = '⚡ Re-analisar Arquivos com Descrição Ruim'; btn.disabled = false; }, 3000);
    } catch(e) {
        btn.innerText = '⚡ Re-analisar Arquivos com Descrição Ruim'; btn.disabled = false;
    }
}

// ==========================================
// ABRIR LOCAL NO EXPLORER
// ==========================================
let _caminhoArquivoAtual = '';

async function abrirLocalDoArquivo() {
    if (!_caminhoArquivoAtual) return;
    try {
        await fetch(`${API_BASE_URL}/api/open_location?path=${encodeURIComponent(_caminhoArquivoAtual)}`);
    } catch(e) { console.error('Erro ao abrir local:', e); }
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
            
            const hora = new Date().toLocaleTimeString('pt-BR', {hour: '2-digit', minute:'2-digit'});
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
    if(idx !== -1) abrirPainelLateral(idx);
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
    if(!pastas || pastas.length === 0) { list.innerHTML = '<p style="color:var(--text-secondary);">Nenhuma pasta monitorada.</p>'; return; }
    list.innerHTML = '';
    pastas.forEach(p => {
        list.innerHTML += `<div class="folder-item"><span class="folder-path">${p}</span><button class="btn-remover" onclick="removerPasta('${p.replace(/\\/g, '\\\\')}')">Excluir</button></div>`;
    });
}

async function adicionarPasta() {
    const btn = document.getElementById('btnAdicionarPasta'); btn.innerText = "⏳ Abrindo Windows...";
    const res = await fetch(`${API_BASE_URL}/api/choose_folder`); const data = await res.json();
    if (data.status === "sucesso") {
        btn.innerText = "⏳ Salvando...";
        const updateRes = await fetch(`${API_BASE_URL}/api/folders`, { method: 'POST', headers: fetchOptions.headers, body: JSON.stringify({ pasta: data.pasta }) });
        const config = await updateRes.json();
        atualizarListaModalPastas(config.pastas);
    }
    btn.innerText = "+ Importar Nova Pasta";
}

async function removerPasta(p) {
    if(!confirm("Remover pasta monitorada? A IA não buscará mais nela.")) return;
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
        if(filtroAtual==='all') return true;
        if(filtroAtual==='imagem') return extensoesImagem.includes(ext);
        if(filtroAtual==='midia') return extensoesAudio.includes(ext) || extensoesVideo.includes(ext);
        return !extensoesImagem.includes(ext) && !extensoesAudio.includes(ext) && !extensoesVideo.includes(ext);
    });
    
    if(filtrados.length>0){
        document.getElementById('tituloMelhores').style.display='block'; document.getElementById('tituloSemantica').style.display='block';
    } else {
        document.getElementById('tituloMelhores').style.display='none'; document.getElementById('tituloSemantica').style.display='none';
        mGrid.innerHTML = '<p style="text-align:center; width:100%; color:var(--text-secondary);">Nada encontrado.</p>'; return;
    }
    
    const melhores = filtrados.filter(r => r.score >= 0.60); const outras = filtrados.filter(r => r.score < 0.60);
    
    const buildCard = (r) => {
        const ext = r.tipo.toLowerCase(); const link = formatImagePath(r.caminho);
        let midia = `<div class="document-icon-wrapper"><svg viewBox='0 0 24 24'><path d='M14 2H6c-1.1 0-1.99.9-1.99 2L4 20c0 1.1.89 2 1.99 2h12c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z'/></svg></div>`;
        if(extensoesVideo.includes(ext)) midia = `<video controls><source src="${link}"></video>`;
        else if(extensoesAudio.includes(ext)) midia = `<audio controls><source src="${link}"></audio>`;
        else if(extensoesImagem.includes(ext)) midia = `<img src="${link}">`;
        
        const idx = window.resultadosAtuais.indexOf(r);
        let trecho = r.trecho && r.trecho !== "Nenhum conteúdo..." ? `<div class="trecho-preview">"${r.trecho}"</div>` : '';
        
        const favClass = r.favorito ? 'is-fav' : '';
        const favIcon = r.favorito ? '💖' : '🤍';
        const favBtn = `<div class="btn-fav-abs ${favClass}" onclick="toggleFavorito(event, ${r.id}, this)">${favIcon}</div>`;
        
        return `<div class="card" onclick="abrirPainelLateral(${idx})">${favBtn}<div class="media-container">${midia}</div><div class="card-content"><h3>${r.nome}</h3><div class="tags"><span class="badge type">${ext.toUpperCase()}</span><span class="badge score">SCORE: ${Math.round(r.score*100)}%</span></div>${trecho}</div></div>`;
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
    document.getElementById('sideBadgeScore').innerText = `SCORE: ${Math.round(res.score*100)}%`;
    document.getElementById('sideDownloadBtn').href = formatImagePath(res.caminho);
    
    const ext = res.tipo.toLowerCase(); const link = formatImagePath(res.caminho);
    const mediaBox = document.getElementById('sideMediaPreview');
    if(extensoesVideo.includes(ext)) mediaBox.innerHTML = `<video controls autoplay><source src="${link}"></video>`;
    else if(extensoesAudio.includes(ext)) mediaBox.innerHTML = `<audio controls autoplay><source src="${link}"></audio>`;
    else if(extensoesImagem.includes(ext)) mediaBox.innerHTML = `<img src="${link}">`;
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

window.onclick = function(e) {
    if(e.target.closest('.modal') && !e.target.closest('.modal-content') && !e.target.closest('.fav-modal-content')) {
        e.target.closest('.modal').style.display = 'none';
        if(cropper) { cropper.destroy(); cropper = null; } 
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
                let iconText = "📄";
                if(extensoesVideo.includes(ext)) iconText = "🎥";
                else if(extensoesAudio.includes(ext)) iconText = "🎵";
                else if(extensoesImagem.includes(ext)) iconText = "🖼️";
                
                let thumbHtml = `<div class="fav-thumb" style="display:flex; align-items:center; justify-content:center; font-size:1.5rem;">${iconText}</div>`;
                if(extensoesImagem.includes(ext)) {
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
                        <button class="btn-fav-icon" onclick="toggleFavorito(event, ${r.id}, null, true)">💖</button>
                    </div>
                </div>`;
                list.innerHTML += card;
            });
        } else {
            list.innerHTML = '<p style="text-align:center; color: var(--text-secondary);">Nenhum favorito ainda.</p>';
        }
    } catch(e) {
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
        
        if(dados.status === 'sucesso') {
            const isFav = dados.favorito;
            
            // Atualiza global state para a renderização saber disso depois
            if(window.resultadosAtuais) {
                window.resultadosAtuais.forEach(r => {
                    if(r.id === id) r.favorito = isFav;
                });
            }
            
            if(btnElement) {
                if(isFav) {
                    btnElement.classList.add('is-fav');
                    btnElement.innerText = '💖';
                } else {
                    btnElement.classList.remove('is-fav');
                    btnElement.innerText = '🤍';
                }
            }
            
            // Se desfavoritou pelo Modal ou Dashboard, removemos o card
            if(fromModal && !isFav) {
                const card = document.getElementById(`favCard_${id}`);
                if(card) card.remove();
                
                const list = document.getElementById('favoritosList');
                if(list && !list.innerHTML.trim().includes('fav-card')) {
                    list.innerHTML = '<p style="text-align:center; color: var(--text-secondary);">Nenhum favorito ainda.</p>';
                }
                
                carregarFavoritosDash(); // Sincroniza o painel principal se estiver aberto
            }
            
            // E atualizamos a tela de pesquisa de fundo DE QUALQUER FORMA pra refletir os cliques.
            if(document.getElementById('searchResultsView').style.display === 'block') {
                renderizarResultados();
            }
        }
    } catch(e) {
        console.error("Erro ao favoritar", e);
    }
}

async function carregarFavoritosDash() {
    try {
        const res = await fetch(`${API_BASE_URL}/api/favorites`, { headers: fetchOptions.headers });
        const dados = await res.json();
        
        const grid = document.getElementById('recentFavsDash');
        const title = document.getElementById('favDashTitle');
        if(!grid) return;
        
        grid.innerHTML = '';
        
        if (dados.resultados && dados.resultados.length > 0) {
            title.style.display = 'block';
            
            // Exibir ate os top 8 mais recentes na horizontal/grid
            const topFavs = dados.resultados.slice(0, 8);
            
            topFavs.forEach(r => {
                const ext = r.tipo.toLowerCase();
                let iconText = "📄";
                if(extensoesVideo.includes(ext)) iconText = "🎥";
                else if(extensoesAudio.includes(ext)) iconText = "🎵";
                else if(extensoesImagem.includes(ext)) iconText = "🖼️";
                
                let midia = `<div class="recent-img" style="font-size:3rem; background:transparent;">${iconText}</div>`;
                if(extensoesImagem.includes(ext)) {
                    midia = `<div class="recent-img"><img src="${formatImagePath(r.caminho)}"></div>`;
                }

                const cardBox = `<div class="recent-card" onclick="alert('Inspecionado nos favoritos!')" id="favDash_${r.id}">
                    <div style="position:relative; width:100%; height:100%; pointer-events: none;">
                        ${midia}
                    </div>
                    <p style="pointer-events: auto;">${r.nome}</p>
                    <button class="btn-fav-abs is-fav" onclick="event.stopPropagation(); toggleFavorito(event, ${r.id}, this, true)" style="top:5px; right:5px; width:30px; height:30px; pointer-events: auto;">💖</button>
                </div>`;
                
                grid.innerHTML += cardBox;
            });
        } else {
            title.style.display = 'none';
        }
    } catch(e) {}
}

// Restaura a função de apertar Enter no teclado para buscar
function verificarEnter(e) { 
    if (e.key === "Enter") realizarBusca(); 
}

// 2. STATUS BAR COM FEEDBACK DE CONCLUSÃO
async function buscarStatus() {
    try {
        const res = await fetch(`${API_BASE_URL}/api/status`); 
        const s = await res.json();
        const b = document.getElementById('statusBar'); 
        
        let statusTexto = s.status;
        
        // Se a fila zerou, avisa visualmente que a verificação terminou!
        if(s.arquivos_pendentes === 0 && s.arquivos_processados_sessao > 0) {
            statusTexto = "✅ Verificação Concluída";
        }
        
        let m = `⚙️ Motor: ${statusTexto}`;
        if(s.arquivos_pendentes > 0) m += ` | ⏳ Fila: ${s.arquivos_pendentes}`;
        m += ` | 📦 Processados: ${s.arquivos_processados_sessao}`;
        
        b.innerText = m; 
        b.style.color = "var(--telemetry)";
    } catch(e) { 
        document.getElementById('statusBar').innerText = "🔌 API Desconectada."; 
        document.getElementById('statusBar').style.color = "#ef4444"; 
    }
}
setInterval(buscarStatus, 2000);

// Restaura a função de apertar Enter no teclado para buscar
function verificarEnter(e) { 
    if (e.key === "Enter") realizarBusca(); 
}

// SEARCH+ PRO: GLOBAL IMAGE DISPATCHER
function aplicarCorteNoPreview(targetId, base64Data) {
    const isAvatar = targetId.toLowerCase().includes('avatar');
    const isBanner = targetId.toLowerCase().includes('banner');

    // 1. Persistência no Objeto de Configuração
    if (isAvatar) currentConfig.perfil_avatar = base64Data;
    if (isBanner) currentConfig.perfil_banner = base64Data;

    // 2. DOM Sync (Atualiza todos os espelhos da imagem na UI)
    const selectors = {
        avatar: ['#navAvatar', '#dropAvatar', '#viewAvatar', '#previewAvatar', '#obPreviewAvatar'],
        banner: ['#viewBanner', '#obPreviewBanner', '#previewBanner']
    };

    if (isAvatar) {
        selectors.avatar.forEach(sel => {
            const el = document.querySelector(sel);
            if (el) el.src = base64Data;
        });
    }

    if (isBanner) {
        selectors.banner.forEach(sel => {
            const el = document.querySelector(sel);
            if (!el) return;
            if (el.tagName === 'IMG') el.src = base64Data;
            else el.style.backgroundImage = `url('${base64Data}')`;
        });
    }

    // 3. Silently save to server (Pro-active save)
    fetch(`${API_BASE_URL}/api/config`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(currentConfig)
    }).catch(err => console.error("Sync Error:", err));
}