/* ==========================================================================
   SEARCH+ / LABORATÓRIO
   --------------------------------------------------------------------------
   Propostas de interface que dá pra ligar e desligar ao vivo, pra
   comparar antes e depois sem trocar código. Ficam em
   Ajustes > Configurações gerais > Laboratório.

   Cada proposta é uma classe no <html> (lab-*). As que são só aparência
   moram no CSS; as que precisam mexer no conteúdo dos cartões têm um
   aplica()/desfaz() aqui — e nada disso toca no script.js.

   Gostou de alguma? É só deixar a classe ligada por padrão (ou colar o
   bloco de CSS correspondente sem o prefixo .lab-x).
   ========================================================================== */
(function () {
    "use strict";

    var root = document.documentElement;
    var LS = "sp-lab-";

    /* ======================================================================
       AS PROPOSTAS
       ====================================================================== */
    var PROPOSTAS = [
        {
            id: "skeleton",
            nome: "Buscar sem cobrir a tela",
            texto: "Troca o “PROCESSANDO...” em tela cheia por esqueletos de cartão no lugar " +
                   "dos resultados. Você continua vendo onde está.",
            aplica: function () { limpaEsqueleto(); },
            desfaz: limpaEsqueleto
        },
        {
            id: "densidade",
            nome: "Grade mais densa",
            texto: "Cartões menores: cabe quase o dobro de resultados sem rolar. " +
                   "Bom pra quem busca imagem, ruim pra quem lê descrição.",
        },
        {
            id: "vitrine",
            nome: "Vitrine cheia (exemplos)",
            texto: "O servidor de demonstração tem 1 ou 2 arquivos por categoria, e prateleira " +
                   "com dois itens não parece prateleira. Isto repete as capas que existem, " +
                   "marcadas com “exemplo”, só pra você ver a estante cheia. Não é acervo real.",
            aplica: encheVitrine,
            desfaz: limpaVitrine,
            // Sai de fábrica desligada: com foto de verdade nas capas, a
            // repeticao le como defeito, nao como estante cheia.
            padrao: false
        },
        {
            id: "atalhos",
            nome: "Atalhos à mostra",
            texto: "Mostra a tecla / no campo de busca e a legenda das teclas no histórico. " +
                   "Atalho que ninguém vê é atalho que ninguém usa."
        }
    ];

    function ligada(p) {
        try {
            var v = localStorage.getItem(LS + p.id);
            return v === null ? !!p.padrao : v === "1";
        } catch (e) { return !!p.padrao; }
    }
    function grava(id, v) {
        try { localStorage.setItem(LS + id, v ? "1" : "0"); } catch (e) { }
    }

    function aplicar(p, on) {
        root.classList.toggle("lab-" + p.id, on);
        grava(p.id, on);
        if (on && p.aplica) p.aplica();
        if (!on && p.desfaz) p.desfaz();
    }

    /* ======================================================================
       VITRINE
       Repete as capas que a galeria já trouxe até a faixa parecer uma
       estante. Cada cópia abre o arquivo de verdade e vem marcada.
       ====================================================================== */
    var MINIMO_VITRINE = 10;

    function encheFaixa(trilho, itens, aoClicar) {
        if (!itens || itens.length === 0) return;
        var i = 0;
        var guarda = 0;
        while (trilho.children.length < MINIMO_VITRINE && guarda++ < 60) {
            var r = itens[i % itens.length];
            var poster = window.montarPoster(r, aoClicar(r));
            poster.dataset.demo = "1";
            trilho.appendChild(poster);
            i++;
        }
    }

    function encheVitrine() {
        if (typeof window.montarPoster !== "function") return;
        var grupos = window._galeriaGrupos || {};

        document.querySelectorAll(".faixa[data-cat]").forEach(function (sec) {
            var cat = sec.dataset.cat;
            var trilho = sec.querySelector(".faixa-trilho");
            if (!trilho) return;
            encheFaixa(trilho, grupos[cat], function (r) {
                return function () { window.abrirPainelGaleria(cat, r.id); };
            });
        });

        var todos = [];
        Object.keys(grupos).forEach(function (cat) {
            grupos[cat].forEach(function (r) {
                if (!todos.some(function (x) { return x.id === r.id; })) todos.push(r);
            });
        });

        ["recentImgs", "recentFavsDash"].forEach(function (id) {
            var trilho = document.getElementById(id);
            if (!trilho || trilho.children.length === 0) return;
            encheFaixa(trilho, todos, function (r) {
                return function () {
                    var cat = Object.keys(grupos).find(function (c) {
                        return grupos[c].some(function (x) { return x.id === r.id; });
                    });
                    if (cat) window.abrirPainelGaleria(cat, r.id);
                };
            });
        });
    }

    function limpaVitrine() {
        document.querySelectorAll(".poster[data-demo]").forEach(function (p) { p.remove(); });
    }

    /* ======================================================================
       3. BUSCA SEM TELA CHEIA
       O CSS esconde o #iaLoadingScreen; aqui só entram os esqueletos no
       lugar dos resultados enquanto ele estaria aberto.
       ====================================================================== */
    function limpaEsqueleto() {
        document.querySelectorAll(".lab-skel").forEach(function (s) { s.remove(); });
    }

    function poeEsqueleto() {
        var grid = document.getElementById("melhoresGrid");
        if (!grid || grid.querySelector(".lab-skel")) return;
        for (var i = 0; i < 8; i++) {
            var s = document.createElement("div");
            s.className = "lab-skel";
            s.style.animationDelay = (i * 60) + "ms";
            grid.appendChild(s);
        }
    }

    function vigiaCarregamento() {
        var tela = document.getElementById("iaLoadingScreen");
        if (!tela) return;
        new MutationObserver(function () {
            if (!root.classList.contains("lab-skeleton")) return;
            var aberta = getComputedStyle(tela).display !== "none" || tela.style.display === "flex";
            if (aberta) poeEsqueleto(); else limpaEsqueleto();
        }).observe(tela, { attributes: true, attributeFilter: ["style"] });
    }

    /* ======================================================================
       Os resultados são redesenhados pelo script a cada busca ou filtro:
       quando o grid muda, as propostas que mexem no cartão entram de novo.
       ====================================================================== */
    function vigiaGaleria() {
        var alvo = document.getElementById("galeriaCategorias");
        if (!alvo) return;
        var pendente = null;
        new MutationObserver(function () {
            clearTimeout(pendente);
            pendente = setTimeout(function () {
                if (root.classList.contains("lab-vitrine")) encheVitrine();
            }, 60);
        }).observe(alvo, { childList: true });
    }

    /* ======================================================================
       A ABA
       ====================================================================== */
    function montaAba() {
        var abas = document.querySelector("#modalConfigGerais .sheet-tabs");
        var corpo = document.querySelector("#modalConfigGerais .modal-content");
        if (!abas || !corpo || document.getElementById("cgTabLab")) return;

        var btn = document.createElement("button");
        btn.className = "btn-tab-selector";
        btn.type = "button";
        btn.dataset.tab = "cg-lab";
        btn.textContent = "Laboratório";
        btn.onclick = function () { selecionarTabCg("cg-lab", btn); };
        abas.appendChild(btn);

        var painel = document.createElement("div");
        painel.id = "cgTabLab";
        painel.style.display = "none";

        var intro = document.createElement("p");
        intro.className = "lab-intro";
        intro.textContent = "Propostas ligadas e desligadas na hora, pra você comparar. " +
                            "Nada aqui é definitivo — é pra olhar e decidir.";
        painel.appendChild(intro);

        PROPOSTAS.forEach(function (p) {
            var linha = document.createElement("div");
            linha.className = "lab-item";

            var txt = document.createElement("div");
            var t = document.createElement("strong");
            t.textContent = p.nome;
            var d = document.createElement("p");
            d.textContent = p.texto;
            txt.appendChild(t);
            txt.appendChild(d);

            var sw = document.createElement("button");
            sw.className = "lab-sw";
            sw.type = "button";
            sw.setAttribute("role", "switch");
            sw.setAttribute("aria-label", p.nome);

            function pinta() {
                var on = root.classList.contains("lab-" + p.id);
                sw.classList.toggle("on", on);
                sw.setAttribute("aria-checked", on ? "true" : "false");
            }

            sw.onclick = function () {
                aplicar(p, !root.classList.contains("lab-" + p.id));
                pinta();
            };

            pinta();
            linha.appendChild(txt);
            linha.appendChild(sw);
            painel.appendChild(linha);
        });

        /* O painel entra antes da barra de botões do rodapé do modal. */
        var rodape = corpo.lastElementChild;
        corpo.insertBefore(painel, rodape);
    }

    /* ======================================================================
       INÍCIO
       ====================================================================== */
    function init() {
        PROPOSTAS.forEach(function (p) {
            if (ligada(p)) {
                root.classList.add("lab-" + p.id);
                if (p.aplica) p.aplica();
            }
        });
        montaAba();
        vigiaCarregamento();
        vigiaGaleria();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
