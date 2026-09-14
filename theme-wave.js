/* ==========================================================================
   SEARCH+ / FUNDO DE ONDA
   --------------------------------------------------------------------------
   Não altera nada do script.js. Faz três coisas:
     1. injeta o canvas do shader dentro do #appBackground que já existe
     2. marca html.wv-auth enquanto a tela de entrada está aberta, pra o CSS
        esconder o app atrás (o overlay é transparente pra onda aparecer)
     3. escreve --wv-mx / --wv-my nos painéis (brilho que segue o cursor) e
        oferece os botões de paleta e modo leve

   O fundo é um porte do GrainGradient de @paper-design/shaders, shape "wave"
   — o mesmo componente que o midu.design embute por iframe. A equação da
   onda é literal do shader original; os trechos vêm marcados com ORIGINAL.
   ========================================================================== */
(function () {
    "use strict";

    var root = document.documentElement;
    var LS_PERF = "sp-wave-perf";

    function readLS(k, def) {
        try {
            var v = localStorage.getItem(k);
            return v === null ? def : v === "1";
        } catch (e) { return def; }
    }
    function writeLS(k, v) {
        try { localStorage.setItem(k, v ? "1" : "0"); } catch (e) { }
    }
    function readTxt(k, def) {
        try { return localStorage.getItem(k) || def; } catch (e) { return def; }
    }
    function writeTxt(k, v) {
        try { localStorage.setItem(k, v); } catch (e) { }
    }

    /* ======================================================================
       PALETAS
       ====================================================================== */
    var PALETTES = [
        /* A primeira e a do proprio app: sai das cores escolhidas em
           Personalizacao. Trocou a paleta la, a onda acompanha. */
        { name: "do app", back: "#0B0F19", colors: ["#1A1140", "#6F87A8", "#FF2DAF", "#FFC2E8"] },
        { name: "Vivo",    back: "#050505", colors: ["#3B0A6B", "#6F87A8", "#FF2DAF", "#FF9BE0"] },
        { name: "midu",    back: "#050505", colors: ["#151515", "#FF0300", "#FF0022", "#FF7D4E"] },
        { name: "Ciano",   back: "#04060B", colors: ["#12103A", "#6F87A8", "#A2B5CB", "#4FD1C5"] }
    ];

    /* Mistura dois hex: t=0 devolve a, t=1 devolve b. */
    function mistura(a, b, t) {
        var x = hex(a), y = hex(b), r = [];
        for (var i = 0; i < 3; i++) {
            r.push(Math.round((x[i] + (y[i] - x[i]) * t) * 255));
        }
        return "#" + r.map(function (v) {
            return ("0" + Math.max(0, Math.min(255, v)).toString(16)).slice(-2);
        }).join("");
    }

    /* Le as cores do app; null se ainda nao forem hex simples. */
    function paletaDoApp() {
        var cs = getComputedStyle(root);
        var p = (cs.getPropertyValue("--accent-primary") || "").trim();
        var d = (cs.getPropertyValue("--accent-secondary") || "").trim();
        if (!/^#[0-9a-fA-F]{6}$/.test(p) || !/^#[0-9a-fA-F]{6}$/.test(d)) return null;
        return {
            name: "do app",
            back: "#0B0F19",
            colors: [mistura(p, "#080A12", .74), p, d, mistura(d, "#FFFFFF", .5)]
        };
    }

    function hex(h) {
        return [
            parseInt(h.slice(1, 3), 16) / 255,
            parseInt(h.slice(3, 5), 16) / 255,
            parseInt(h.slice(5, 7), 16) / 255
        ];
    }

    /* ======================================================================
       SHADERS
       ====================================================================== */
    var VS = [
        "#version 300 es",
        "layout(location=0) in vec2 a_pos;",
        "void main(){ gl_Position=vec4(a_pos,0.,1.); }"
    ].join("\n");

    var FS_ONDA = [
        "#version 300 es",
        "precision highp float;",
        "uniform vec2 u_resolution; uniform float u_time;",
        "uniform vec4 u_colors[5]; uniform float u_colorsCount; uniform vec4 u_colorBack;",
        "uniform float u_softness,u_intensity,u_noise,u_scale,u_bandY;",
        "out vec4 fragColor;",
        "vec2 rot(vec2 v,float a){float s=sin(a),c=cos(a);return mat2(c,-s,s,c)*v;}",
        "float randomR(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453123);}",
        "vec3 permute(vec3 x){return mod(((x*34.)+1.)*x,289.);}",
        "float snoise(vec2 v){",
        " const vec4 C=vec4(.211324865405187,.366025403784439,-.577350269189626,.024390243902439);",
        " vec2 i=floor(v+dot(v,C.yy)); vec2 x0=v-i+dot(i,C.xx);",
        " vec2 i1=(x0.x>x0.y)?vec2(1.,0.):vec2(0.,1.);",
        " vec4 x12=x0.xyxy+C.xxzz; x12.xy-=i1; i=mod(i,289.);",
        " vec3 p=permute(permute(i.y+vec3(0.,i1.y,1.))+i.x+vec3(0.,i1.x,1.));",
        " vec3 m=max(.5-vec3(dot(x0,x0),dot(x12.xy,x12.xy),dot(x12.zw,x12.zw)),0.); m=m*m; m=m*m;",
        " vec3 x=2.*fract(p*C.www)-1.; vec3 h=abs(x)-.5; vec3 ox=floor(x+.5); vec3 a0=x-ox;",
        " m*=1.79284291400159-.85373472095314*(a0*a0+h*h);",
        " vec3 g; g.x=a0.x*x0.x+h.x*x0.y; g.yz=a0.yz*x12.xz+h.yz*x12.yw;",
        " return 130.*dot(m,g);}",
        /* ORIGINAL: valueNoiseR + fbmR, verbatim do shader do midu */
        "float valueNoiseR(vec2 st){",
        " vec2 i=floor(st),f=fract(st);",
        " float a=randomR(i),b=randomR(i+vec2(1,0)),c=randomR(i+vec2(0,1)),d=randomR(i+vec2(1,1));",
        " vec2 u=f*f*(3.-2.*f);",
        " return mix(mix(a,b,u.x),mix(c,d,u.x),u.y);}",
        "vec4 fbmR(vec2 n0,vec2 n1,vec2 n2,vec2 n3){",
        " float amp=.2; vec4 total=vec4(0.);",
        " for(int i=0;i<3;i++){",
        "  n0=rot(n0,.3); n1=rot(n1,.3); n2=rot(n2,.3); n3=rot(n3,.3);",
        "  total.x+=valueNoiseR(n0)*amp; total.y+=valueNoiseR(n1)*amp;",
        "  total.z+=valueNoiseR(n2)*amp; total.z+=valueNoiseR(n3)*amp;",
        "  n0*=1.99; n1*=1.99; n2*=1.99; n3*=1.99; amp*=.6;}",
        " return total;}",
        "void main(){",
        " vec2 uv=(gl_FragCoord.xy-.5*u_resolution)/u_resolution.y; uv.y=-uv.y;",
        " vec2 suv=uv*u_scale;",
        " vec2 guv=uv*u_resolution.y*1.6;",
        /* ORIGINAL: firstFrameOffset e o passo de tempo */
        " const float firstFrameOffset=7.;",
        " float t=.1*(u_time+firstFrameOffset);",
        /* ================= ORIGINAL: Sine wave ================= */
        " float wave=cos(.5*suv.x-4.*t)*sin(1.5*suv.x+2.*t)*(.75+.25*cos(6.*t));",
        " float shape=1.-smoothstep(-1.,1.,suv.y+wave+u_bandY);",
        /* ======================================================= */
        " float bn=snoise(guv*.5);",
        " vec4 fv=fbmR(.002*guv+10.,.003*guv,.001*guv,rot(.4*guv,2.));",
        " float grainDist=bn*snoise(guv*.2)-fv.x-fv.y;",
        " float rawNoise=.75*bn-fv.w-fv.z;",
        " shape+=u_intensity*2./u_colorsCount*(grainDist+.5);",
        " shape+=u_noise*10./u_colorsCount*clamp(rawNoise,0.,1.);",
        /* ORIGINAL: rampa de cor com anti-alias por fwidth */
        " float aa=fwidth(shape);",
        " shape=clamp(shape-.5/u_colorsCount,0.,1.);",
        " float totalShape=smoothstep(0.,u_softness+2.*aa,clamp(shape*u_colorsCount,0.,1.));",
        " float mixer=shape*(u_colorsCount-1.);",
        " int cnt=int(u_colorsCount)-1;",
        " vec4 grad=u_colors[0]; grad.rgb*=grad.a;",
        " for(int i=1;i<5;i++){",
        "  if(i>cnt) break;",
        "  float lt=clamp(mixer-float(i-1),0.,1.);",
        "  lt=smoothstep(.5-.5*u_softness-aa,.5+.5*u_softness+aa,lt);",
        "  vec4 c=u_colors[i]; c.rgb*=c.a; grad=mix(grad,c,lt);}",
        " vec3 color=grad.rgb*totalShape;",
        " float opacity=grad.a*totalShape;",
        " color=color+u_colorBack.rgb*(1.-opacity);",
        " fragColor=vec4(color,1.);}"
    ].join("\n");


    /* ======================================================================
       SOL
       Ceu quente, disco alto na esquerda, raios que giram devagar e um
       calor subindo do rodape. Sem barulho: e a cena mais calma das tres.
       ====================================================================== */
    var FS_SOL = [
        "#version 300 es",
        "precision highp float;",
        "uniform vec2 u_resolution; uniform float u_time;",
        "out vec4 fragColor;",

        "float h21(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7)))*43758.545); }",
        "float ruido(vec2 p){",
        "  vec2 i = floor(p), f = fract(p);",
        "  float a=h21(i), b=h21(i+vec2(1,0)), c=h21(i+vec2(0,1)), d=h21(i+vec2(1,1));",
        "  vec2 u = f*f*(3.-2.*f);",
        "  return mix(mix(a,b,u.x), mix(c,d,u.x), u.y);}",

        "void main(){",
        "  vec2 uv = (gl_FragCoord.xy - .5*u_resolution)/u_resolution.y;",
        "  float t = u_time*.06;",
        "  vec2 sol = vec2(-.42, .30);",
        "  float d = length((uv - sol) * vec2(1., 1.05));",

        /* ceu: quente em cima e na direcao do sol, frio no rodape */
        "  vec3 alto  = vec3(.82,.62,.38);",
        "  vec3 baixo = vec3(.09,.11,.21);",
        "  vec3 cor = mix(baixo, alto, clamp(uv.y*.85 + .62, 0., 1.));",

        /* halo do sol */
        "  cor += vec3(1.0,.72,.36) * pow(clamp(1.-d*.85, 0., 1.), 6.5) * .78;",
        "  cor += vec3(1.0,.92,.72) * smoothstep(.13, .02, d) * .85;",

        /* raios: leque em torno do sol, modulado por ruido lento */
        "  float ang = atan(uv.y - sol.y, uv.x - sol.x);",
        "  float raios = .5 + .5*sin(ang*7. + t*3.2 + ruido(vec2(ang*2.2, t*4.))*5.5);",
        "  raios *= smoothstep(1.35, .12, d);",
        "  cor += vec3(1.0,.84,.58) * raios * .12;",

        /* calor subindo do rodape */
        "  float calor = smoothstep(-.65, -.05, uv.y) * (.5 + .5*ruido(vec2(uv.x*3., t*6.)));",
        "  cor = mix(cor, cor*vec3(1.05,.98,.92), calor*.35);",

        /* vinheta discreta */
        "  cor *= 1.0 - .38*smoothstep(.25, 1.15, length(uv*vec2(.85,1.)));",
        "  cor *= .92;",
        "  fragColor = vec4(cor, 1.);}"
    ].join("\n");


    /* ======================================================================
       PAISAGENS
       Quatro cenas saem do MESMO shader. O que muda entre elas cabe em duas
       peças de texto: as constantes (céu, luz, se tem água) e as camadas de
       serra. Quatro shaders quase iguais divergem no primeiro conserto —
       assim um ajuste no relevo vale pras quatro de uma vez.
       ====================================================================== */
    var TERRENO = [
        "#version 300 es",
        "precision highp float;",
        "uniform vec2 u_resolution; uniform float u_time;",
        "out vec4 fragColor;",

        "/*CONST*/",

        /* Hash de multiplicação, não de sin(): nas cenas com água o cenário
           roda duas vezes por pixel, então cada sin() poupado vale por dois. */
        "float h11(float x){ float p = fract(x*.1031); p *= p + 33.33; p *= p + p; return fract(p); }",
        "float h21(vec2 v){ vec3 p = fract(v.xyx*.1031); p += dot(p, p.yzx + 33.33);",
        "  return fract((p.x + p.y) * p.z); }",

        "float ruido1(float x){ float i = floor(x), f = fract(x); f = f*f*(3.-2.*f);",
        "  return mix(h11(i), h11(i+1.), f); }",
        "float fbm1(float x){ float a = .5, s = 0.;",
        "  for(int i=0;i<3;i++){ s += a*ruido1(x); x *= 2.07; a *= .5; } return s; }",

        "float ruido2(vec2 p){ vec2 i = floor(p), f = fract(p); f = f*f*(3.-2.*f);",
        "  return mix(mix(h21(i), h21(i+vec2(1,0)), f.x),",
        "             mix(h21(i+vec2(0,1)), h21(i+vec2(1,1)), f.x), f.y); }",
        "float fbm2(vec2 p){ float a = .5, s = 0.;",
        "  for(int i=0;i<3;i++){ s += a*ruido2(p); p = p*2.03 + vec2(1.7,9.2); a *= .5; } return s; }",

        /* Ruído puro faz colina. Dobrado no meio, faz pico. */
        "float serra(float x, float esc, float des){",
        "  float n = fbm1(x*esc + des);",
        "  float c = 1. - abs(2.*n - 1.);",
        "  return c*c*.55 + c*.30 + n*.15; }",

        /* 'cova' afunda a camada no centro: é o que abre o vale. */
        "float crista(float x, float esc, float alt, float base, float des, float cova){",
        "  return base + alt*serra(x, esc, des) - cova*exp(-x*x*3.4); }",

        "vec3 camada(vec3 c, vec2 p, float esc, float alt, float base, float des,",
        "            float cova, vec3 cor, vec3 neb, float brilho, float suave){",
        "  float h = crista(p.x, esc, alt, base, des, cova);",
        /* A borda é a distância: perto corta, longe dissolve. */
        "  float m = smoothstep(h + suave, h - suave, p.y);",
        "  if (m <= .002) return c;",                    /* céu: sai antes de gastar */
        /* Inclinação por diferença: a encosta virada pra luz acende. */
        "  float incl = (crista(p.x+.02, esc, alt, base, des, cova) - h) * 50.;",
        "  float lado = clamp((LUZ.x - p.x)*5., -1., 1.);",
        "  float face = clamp(incl*lado*.9 + .10, 0., 1.);",
        "  float tex = ruido2(vec2(p.x*esc*2.4, p.y*9.))*.6",
        "            + ruido2(vec2(p.x*esc*7.0, p.y*22.))*.4;",
        "  vec3 cc = cor * (.82 + .34*tex);",
        "  float aresta = smoothstep(h-.055, h-.004, p.y);",
        "  cc += LUZ_COR * 1.5 * aresta * face * brilho;",
        /* O pé da serra se dissolve no ar entre ela e a próxima. */
        "  float prof = clamp((h - p.y)/(alt + .28), 0., 1.);",
        "  cc = mix(cc, neb, prof * (.42 + suave*7.0));",
        "  return mix(c, cc, m); }",

        "vec3 ceu(vec2 p, float t){",
        "  float g = clamp(p.y*.95 + .30, 0., 1.);",
        "  vec3 c = mix(CEU_BAIXO, CEU_ALTO, g*g*.75 + g*.25);",
        /* Duas camadas de nuvem andando em velocidades diferentes. */
        "  vec2 cp = vec2(p.x, p.y*2.3) + vec2(t*.010, 0.);",
        "  float nu = fbm2(cp*2.1)*.72 + fbm2(cp*4.6 + vec2(t*.021, 0.))*.34;",
        "  float cob = smoothstep(.38, .86, nu) * smoothstep(-.10, .30, p.y);",
        "  float d = length((p - LUZ)*vec2(.80,1.20));",
        "  c = mix(c, mix(NUVEM_ESC, NUVEM_CLA, exp(-d*1.9)), cob*NUVEM);",
        /* O claro atravessa a nuvem em vez de ficar por baixo dela. */
        "  c += LUZ_COR * pow(max(0., 1.-d), 3.4) * LUZ_FORCA;",
        "  c += LUZ_COR * .55 * exp(-d*1.5) * .30;",
        "  return c; }",

        /* A paisagem inteira. Nas cenas com água ela roda duas vezes. */
        "vec3 cenario(vec2 p, float t){",
        "  vec3 c = ceu(p, t);",
        "/*CAMADAS*/",
        "  return c; }",

        "void main(){",
        "  vec2 uv = (gl_FragCoord.xy - .5*u_resolution)/u_resolution.y;",
        "  float t = u_time;",
        "  vec3 cor;",

        "#if TEM_AGUA",
        "  if (uv.y > AGUA) {",
        "    cor = cenario(uv, t);",
        "  } else {",
        /* Reflexo 1:1 só vale com a câmera na altura da água. Comprimido em
           .60, a serra reflete perto da margem e o resto vira água escura. */
        "    float d = AGUA - uv.y;",
        "    float ond = sin(uv.x* 8.5 + d*24. - t*1.10)*.50",
        "              + sin(uv.x*17.0 - d*39. + t*1.65)*.28",
        "              + (ruido2(vec2(uv.x*5.5, d*13. - t*.55)) - .5)*.90;",
        "    float amp = .0035 + d*.055;",
        "    vec2 rp = vec2(uv.x + ond*amp*.85, AGUA + (AGUA - uv.y)*.60 + ond*amp*.55);",
        "    vec3 refl = cenario(rp, t);",
        "    float fres = exp(-d*2.6);",
        "    cor = mix(AGUA_FUNDO, refl*vec3(.56,.66,.82), .14 + .58*fres);",
        /* Brilho no plano (x/d, 1/d): abre sozinho vindo pra frente. */
        "    vec2 sp = vec2(uv.x, .17)/max(d, .006);",
        "    float g = ruido2(vec2(sp.x*2.2, sp.y*4.0) + vec2(t*.30, 0.));",
        "    float glint = smoothstep(.74, .97, g) * smoothstep(.0, .055, d);",
        "    cor += vec3(.30,.35,.44) * glint * (.05 + .16*fres);",
        "    float trilha = exp(-pow((uv.x - LUZ.x)*2.2, 2.));",
        "    cor += LUZ_COR * glint * trilha * (.20 + .50*fres);",
        "  }",
        "  cor += vec3(.30,.34,.42) * (1. - smoothstep(.0, .022, abs(uv.y - AGUA)))",
        "       * (.14 + .22*ruido2(vec2(uv.x*3.2 + t*.06, 7.)));",
        "  float nev = 1. - smoothstep(.0, .10, abs(uv.y - AGUA - .012",
        "            - ruido2(vec2(uv.x*1.6 + t*.05, 3.))*.03));",
        "  cor = mix(cor, NEVOA_COR, nev*.28);",
        /* A margem de cá, escura, só pra dar um degrau de profundidade. */
        "  float hf = -.400 + .030*serra(uv.x, 4., 90.) - .015*exp(-uv.x*uv.x*2.);",
        "  float mf = smoothstep(hf+.003, hf-.003, uv.y);",
        "  cor = mix(cor, vec3(.014,.020,.030), mf);",
        "  cor += vec3(.20,.24,.32) * smoothstep(hf-.010, hf-.001, uv.y) * mf * .28;",
        "#else",
        "  cor = cenario(uv, t);",
        "#endif",

        /* Feixes lidos pela direção, não pelo ângulo — assim não há costura. */
        "  vec2 dv = uv - LUZ; float dl = length(dv); dv /= max(dl, .001);",
        "  float feixe = smoothstep(.45, .85, fbm2(dv*3.5 + vec2(t*.04, 0.)));",
        /* Só onde já existe claridade: névoa espalha luz, não acende serra
           escura. E o núcleo fica de fora, senão o feixe vira estrela. */
        "  float claro = smoothstep(.05, .22, dot(cor, vec3(.3333)));",
        "  cor += LUZ_COR * feixe * exp(-dl*1.6) * smoothstep(.0, .20, dl) * claro * .20;",

        "  cor *= 1. - .40*smoothstep(.30, 1.15, length(uv*vec2(.80,1.)));",
        "  vec3 sc = clamp(cor, 0., 1.);",
        "  cor = mix(cor, sc*sc*(3.-2.*sc), .28);",
        "  cor += (h21(gl_FragCoord.xy) - .5) * .013;",   /* grão anti-banding */
        "  fragColor = vec4(max(cor, 0.), 1.);}"
    ].join("\n");

    function paisagem(consts, camadas) {
        return TERRENO
            .replace("/*CONST*/", consts.join("\n"))
            .replace("/*CAMADAS*/", camadas.join("\n"));
    }

    /* -------- Vale: lago parado, serras se afastando na neblina ---------- */
    var FS_VALE = paisagem([
        "#define TEM_AGUA 1",
        "const float AGUA = -.145;",
        "const vec2  LUZ  = vec2(.10, .18);",
        "const vec3  CEU_BAIXO  = vec3(.315,.345,.395);",
        "const vec3  CEU_ALTO   = vec3(.045,.062,.115);",
        "const vec3  NUVEM_ESC  = vec3(.115,.135,.185);",
        "const vec3  NUVEM_CLA  = vec3(.620,.580,.550);",
        "const vec3  LUZ_COR    = vec3(.600,.500,.360);",
        "const float LUZ_FORCA  = .85;",
        "const vec3  AGUA_FUNDO = vec3(.030,.046,.072);",
        "const vec3  NEVOA_COR  = vec3(.260,.300,.370);",
        "const float NUVEM = .88;"
    ], [
        "  c = camada(c, p, 1.6, .26,  .075, 11., .00, vec3(.255,.300,.375), vec3(.300,.340,.400), .30, .030);",
        "  c = camada(c, p, 2.4, .23,  .015, 41., .09, vec3(.150,.190,.255), vec3(.235,.275,.335), .38, .017);",
        "  float b1 = smoothstep(.115, .0, abs(p.y - .012 - fbm1(p.x*2.2 + t*.05)*.05));",
        "  c = mix(c, vec3(.275,.315,.375), b1*.42);",
        "  c = camada(c, p, 3.4, .20, -.050, 77., .15, vec3(.080,.105,.148), vec3(.180,.215,.270), .26, .009);",
        "  float b2 = smoothstep(.085, .0, abs(p.y + .072 - fbm1(p.x*1.7 - t*.07)*.04));",
        "  c = mix(c, vec3(.205,.240,.300), b2*.40);",
        "  c = camada(c, p, 4.6, .17, -.105,  5., .20, vec3(.038,.052,.076), vec3(.115,.145,.195), .16, .0045);"
    ]);

    /* ---- Cordilheira: sem água, picos altos, luz baixa por trás ---------- */
    var FS_SERRA = paisagem([
        "#define TEM_AGUA 0",
        "const float AGUA = -1.;",
        "const vec2  LUZ  = vec2(-.24, .12);",
        "const vec3  CEU_BAIXO  = vec3(.380,.400,.440);",
        "const vec3  CEU_ALTO   = vec3(.055,.070,.115);",
        "const vec3  NUVEM_ESC  = vec3(.100,.120,.170);",
        "const vec3  NUVEM_CLA  = vec3(.560,.545,.545);",
        "const vec3  LUZ_COR    = vec3(.660,.560,.420);",
        "const float LUZ_FORCA  = .85;",
        "const vec3  AGUA_FUNDO = vec3(0.);",
        "const vec3  NEVOA_COR  = vec3(0.);",
        "const float NUVEM = .72;"
    ], [
        "  c = camada(c, p, 1.3, .34,  .060, 21., .00, vec3(.265,.305,.372), vec3(.320,.350,.400), .34, .030);",
        "  c = camada(c, p, 2.1, .30, -.030, 53., .03, vec3(.160,.195,.252), vec3(.240,.275,.330), .40, .017);",
        "  float b1 = smoothstep(.110, .0, abs(p.y + .045 - fbm1(p.x*2.0 + t*.05)*.05));",
        "  c = mix(c, vec3(.250,.285,.345), b1*.40);",
        "  c = camada(c, p, 3.2, .26, -.140, 89., .06, vec3(.085,.108,.148), vec3(.175,.205,.258), .30, .009);",
        "  c = camada(c, p, 5.0, .22, -.265, 13., .08, vec3(.030,.040,.060), vec3(.100,.125,.170), .18, .0045);"
    ]);

    /* -------- Névoa: colinas redondas afogadas em bruma, quase sem cor --- */
    var FS_NEVOA = paisagem([
        "#define TEM_AGUA 0",
        "const float AGUA = -1.;",
        "const vec2  LUZ  = vec2(.06, .30);",
        "const vec3  CEU_BAIXO  = vec3(.500,.530,.575);",
        "const vec3  CEU_ALTO   = vec3(.130,.160,.220);",
        "const vec3  NUVEM_ESC  = vec3(.300,.330,.380);",
        "const vec3  NUVEM_CLA  = vec3(.720,.740,.765);",
        "const vec3  LUZ_COR    = vec3(.520,.545,.580);",
        "const float LUZ_FORCA  = .30;",
        "const vec3  AGUA_FUNDO = vec3(0.);",
        "const vec3  NEVOA_COR  = vec3(0.);",
        "const float NUVEM = .55;"
    ], [
        "  c = camada(c, p, 1.1, .20,  .030, 31., .00, vec3(.400,.430,.470), vec3(.440,.465,.500), .18, .030);",
        "  float b1 = smoothstep(.130, .0, abs(p.y - .010 - fbm1(p.x*1.9 + t*.04)*.05));",
        "  c = mix(c, vec3(.470,.495,.535), b1*.55);",
        "  c = camada(c, p, 1.7, .18, -.060, 67., .02, vec3(.290,.320,.365), vec3(.360,.385,.425), .20, .017);",
        "  float b2 = smoothstep(.120, .0, abs(p.y + .110 - fbm1(p.x*1.5 - t*.06)*.04));",
        "  c = mix(c, vec3(.390,.415,.455), b2*.52);",
        "  c = camada(c, p, 2.6, .16, -.160, 97., .04, vec3(.185,.210,.252), vec3(.265,.290,.330), .18, .009);",
        "  float b3 = smoothstep(.100, .0, abs(p.y + .225 - fbm1(p.x*1.3 + t*.05)*.04));",
        "  c = mix(c, vec3(.300,.325,.365), b3*.48);",
        "  c = camada(c, p, 3.8, .14, -.270,  7., .05, vec3(.095,.112,.145), vec3(.170,.190,.230), .14, .0045);"
    ]);

    /* -------- Fiorde: paredes íngremes, fenda funda, luz fria ------------ */
    var FS_FIORDE = paisagem([
        "#define TEM_AGUA 1",
        "const float AGUA = -.100;",
        "const vec2  LUZ  = vec2(.02, .13);",
        "const vec3  CEU_BAIXO  = vec3(.265,.310,.380);",
        "const vec3  CEU_ALTO   = vec3(.030,.048,.090);",
        "const vec3  NUVEM_ESC  = vec3(.085,.105,.150);",
        "const vec3  NUVEM_CLA  = vec3(.480,.520,.560);",
        "const vec3  LUZ_COR    = vec3(.430,.520,.620);",
        "const float LUZ_FORCA  = .70;",
        "const vec3  AGUA_FUNDO = vec3(.018,.030,.050);",
        "const vec3  NEVOA_COR  = vec3(.200,.245,.310);",
        "const float NUVEM = .82;"
    ], [
        "  c = camada(c, p, 1.4, .30,  .085, 71., .02, vec3(.210,.250,.310), vec3(.255,.290,.345), .26, .030);",
        "  c = camada(c, p, 2.0, .28,  .020, 29., .16, vec3(.115,.145,.195), vec3(.190,.225,.275), .30, .017);",
        "  float b1 = smoothstep(.095, .0, abs(p.y + .030 - fbm1(p.x*2.4 + t*.06)*.04));",
        "  c = mix(c, vec3(.215,.255,.315), b1*.38);",
        "  c = camada(c, p, 2.8, .26, -.045, 61., .26, vec3(.058,.078,.112), vec3(.135,.165,.212), .22, .009);",
        "  c = camada(c, p, 3.6, .24, -.090, 17., .34, vec3(.022,.032,.052), vec3(.085,.110,.150), .14, .0045);"
    ]);

    var CENAS = {
        onda:       { nome: "Onda",        fs: FS_ONDA },
        sol:        { nome: "Sol",         fs: FS_SOL },
        vale:       { nome: "Vale",        fs: FS_VALE },
        serra:      { nome: "Cordilheira", fs: FS_SERRA },
        nevoa:      { nome: "Névoa",       fs: FS_NEVOA },
        fiorde:     { nome: "Fiorde",      fs: FS_FIORDE }
    };

    /* ======================================================================
       ESTADO
       ====================================================================== */
    var LS_CENA = "sp-wave-cena";
    var state = {
        cena: "onda",
        pal: 0, intensity: .45, softness: .6, noise: .18,
        scale: 3.2, bandY: 1.0
    };
    var gl = null, U = {}, canvas = null, glOK = false;
    var programas = {};
    var usarCena = function () { };
    var dirty = true, lastPerf = null, start = performance.now();
    var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    /* ======================================================================
       MONTAGEM
       ====================================================================== */
    function mount() {
        var bg = document.getElementById("appBackground");
        if (!bg || document.getElementById("wvCanvas")) return;

        canvas = document.createElement("canvas");
        canvas.id = "wvCanvas";
        canvas.setAttribute("aria-hidden", "true");
        bg.appendChild(canvas);

        /* Ordem importa: canvas, grão, contorno. */
        ["wvGrain", "wvScrim"].forEach(function (id) {
            if (document.getElementById(id)) return;
            var d = document.createElement("div");
            d.id = id;
            d.setAttribute("aria-hidden", "true");
            bg.appendChild(d);
        });

        gl = canvas.getContext("webgl2", { antialias: false, alpha: false });
        if (!gl) return;   /* sem WebGL2 o gradiente do #appBackground vale */

        function compile(type, src) {
            var s = gl.createShader(type);
            gl.shaderSource(s, src);
            gl.compileShader(s);
            if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
                console.warn("[wave] shader:", gl.getShaderInfoLog(s));
                return null;
            }
            return s;
        }

        var buf = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, buf);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
        gl.enableVertexAttribArray(0);
        gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);

        /* Um programa por cena, compilado quando a cena e usada pela primeira
           vez. Trocar de fundo depois disso e so trocar de programa. */
        function programa(id) {
            if (programas[id]) return programas[id];
            var vs = compile(gl.VERTEX_SHADER, VS);
            var fs = compile(gl.FRAGMENT_SHADER, CENAS[id].fs);
            if (!vs || !fs) return null;
            var pr = gl.createProgram();
            gl.attachShader(pr, vs);
            gl.attachShader(pr, fs);
            gl.linkProgram(pr);
            if (!gl.getProgramParameter(pr, gl.LINK_STATUS)) {
                console.warn("[fundo] link:", gl.getProgramInfoLog(pr));
                return null;
            }
            programas[id] = pr;
            return pr;
        }

        usarCena = function (id) {
            if (!CENAS[id]) id = "onda";
            var pr = programa(id);
            if (!pr) return;
            state.cena = id;
            gl.useProgram(pr);
            U = {};
            ["u_resolution", "u_time", "u_colorsCount", "u_colorBack", "u_softness",
                "u_intensity", "u_noise", "u_scale", "u_bandY"].forEach(function (nome) {
                    U[nome] = gl.getUniformLocation(pr, nome);
                });
            U.colors = gl.getUniformLocation(pr, "u_colors");
            root.dataset.fundo = id;
            dirty = true;
            resize();
            applyPalette();
        };

        glOK = true;
        usarCena(state.cena);
        window.addEventListener("resize", resize);
        requestAnimationFrame(frame);
    }

    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    function resize() {
        if (!glOK) return;
        var w = Math.floor(window.innerWidth * dpr);
        var h = Math.floor(window.innerHeight * dpr);
        if (canvas.width !== w || canvas.height !== h) {
            canvas.width = w; canvas.height = h;
            gl.viewport(0, 0, w, h);
            dirty = true;
        }
        gl.uniform2f(U.u_resolution, w, h);
    }

    function applyPalette() {
        var p = (state.pal === 0 && paletaDoApp()) || PALETTES[state.pal];
        dirty = true;
        if (!glOK || state.cena !== "onda") return;
        var flat = [];
        p.colors.forEach(function (c) { var r = hex(c); flat.push(r[0], r[1], r[2], 1); });
        gl.uniform4fv(U.colors, new Float32Array(flat));
        gl.uniform1f(U.u_colorsCount, p.colors.length);
        var b = hex(p.back);
        gl.uniform4f(U.u_colorBack, b[0], b[1], b[2], 1);
    }

    function draw(now, frozen) {
        gl.uniform1f(U.u_time, (reduced || frozen) ? 7 : (now - start) / 1000);
        /* Chuva e sol nao usam os uniformes da onda; setar um location nulo
           e no-op no WebGL, entao nao precisa de if por cena. */
        gl.uniform1f(U.u_softness, state.softness);
        gl.uniform1f(U.u_intensity, state.intensity);
        gl.uniform1f(U.u_noise, state.noise);
        gl.uniform1f(U.u_scale, state.scale);
        gl.uniform1f(U.u_bandY, state.bandY);
        gl.drawArrays(gl.TRIANGLES, 0, 3);
    }

    function frame(now) {
        if (glOK) {
            var perf = root.classList.contains("wv-perf");
            if (perf !== lastPerf) { lastPerf = perf; dirty = true; }

            if (!perf) {
                draw(now, false);
            } else if (dirty) {
                /* Modo leve: onda congelada em t=7. Só redesenha quando a
                   paleta ou o tamanho muda — alguns frames, não 60 por
                   segundo. O rAF continua, mas sem drawArrays não há custo
                   de GPU. */
                draw(now, true);
                dirty = false;
            }
        }
        requestAnimationFrame(frame);
    }

    /* ======================================================================
       A ONDA SEGUE A PALETA DO APP
       O script.js escreve --accent-* no <html> quando o usuario mexe nas
       cores. Em vez de dar hook nele, observamos o atributo.
       ====================================================================== */
    function seguirPaleta() {
        var pendente = null;
        new MutationObserver(function () {
            if (state.pal !== 0) return;
            clearTimeout(pendente);
            pendente = setTimeout(applyPalette, 40);
        }).observe(root, { attributes: true, attributeFilter: ["style"] });
    }

    /* ======================================================================
       BRILHO QUE SEGUE O CURSOR
       ====================================================================== */
    document.addEventListener("pointermove", function (e) {
        if (root.classList.contains("wv-perf")) return;
        if (!e.target || !e.target.closest) return;
        var g = e.target.closest(".settings-group, .modal-content, .dock-btn, .stat-tile, .acao-ficha, .poster");
        if (!g) return;
        var r = g.getBoundingClientRect();
        g.style.setProperty("--wv-mx", ((e.clientX - r.left) / r.width * 100).toFixed(1) + "%");
        g.style.setProperty("--wv-my", ((e.clientY - r.top) / r.height * 100).toFixed(1) + "%");
    }, { passive: true });

    /* ======================================================================
       TELA DE ENTRADA
       O overlay é transparente pra onda aparecer atrás. Sem isso o app
       inteiro (top-bar, busca, avatar) fica visível por baixo do login.
       Observa em vez de dar hook no script.js, pra não tocar nele.
       ====================================================================== */
    function watchAuth() {
        var ov = document.getElementById("authOverlay");
        var ob = document.getElementById("onboardingOverlay");
        if (!ov) return;

        function visible(el) {
            if (!el) return false;
            var cs = getComputedStyle(el);
            return cs.display !== "none" && cs.visibility !== "hidden";
        }
        function sync() {
            root.classList.toggle("wv-auth", visible(ov) || visible(ob));
        }

        var mo = new MutationObserver(sync);
        mo.observe(ov, { attributes: true, attributeFilter: ["style", "class"] });
        if (ob) mo.observe(ob, { attributes: true, attributeFilter: ["style", "class"] });
        sync();
    }

    /* ======================================================================
       CONTROLES
       Escolher o fundo e aparencia: mora em Personalizacao. Modo leve e
       desempenho: mora em Ajustes > Desempenho. Cada um no seu lugar.
       ====================================================================== */
    function buildFundo() {
        var corpo = document.querySelector("#sidebarConfig .sidebar-body");
        if (!corpo || document.getElementById("wvCenas")) return;

        var grupo = document.createElement("div");
        grupo.className = "settings-group";

        var titulo = document.createElement("h3");
        titulo.textContent = "Fundo animado";

        var hint = document.createElement("p");
        hint.textContent = "A onda usa as suas duas cores. As paisagens têm luz própria.";

        var caixa = document.createElement("div");
        caixa.id = "wvCenas";
        caixa.className = "tema-opts";

        Object.keys(CENAS).forEach(function (id) {
            var b = document.createElement("button");
            b.type = "button";
            b.className = "tema-opt fundo-" + id;
            b.dataset.cena = id;
            b.innerHTML = '<i></i>';
            b.appendChild(document.createTextNode(CENAS[id].nome));
            b.addEventListener("click", function () {
                state.cena = id;
                writeTxt(LS_CENA, id);
                usarCena(id);
                marcar();
            });
            caixa.appendChild(b);
        });

        function marcar() {
            caixa.querySelectorAll(".tema-opt").forEach(function (b) {
                var on = b.dataset.cena === state.cena;
                b.classList.toggle("on", on);
                b.setAttribute("aria-pressed", on ? "true" : "false");
            });
        }

        grupo.appendChild(titulo);
        grupo.appendChild(hint);
        grupo.appendChild(caixa);

        var presets = corpo.querySelector(".preset-tema-box");
        if (presets) corpo.insertBefore(grupo, presets); else corpo.appendChild(grupo);
        marcar();
    }

    function buildBar() {
        var host = document.getElementById("cgTabDesempenho");
        if (!host || document.getElementById("wvBar")) return;

        var grupo = document.createElement("div");
        grupo.className = "settings-group";

        var lbl = document.createElement("label");
        lbl.textContent = "Modo leve";

        var hint = document.createElement("p");
        hint.className = "wv-hint";
        hint.textContent = "Congela o fundo e desliga os desfoques. Ligue se o computador engasgar.";

        var bar = document.createElement("div");
        bar.id = "wvBar";

        var bPerf = document.createElement("button");
        bPerf.type = "button";

        function sync() {
            var perf = root.classList.contains("wv-perf");
            bPerf.textContent = perf ? "Ligado" : "Desligado";
            bPerf.classList.toggle("on", perf);
            bPerf.setAttribute("aria-pressed", perf ? "true" : "false");
        }

        bPerf.addEventListener("click", function () {
            var perf = !root.classList.contains("wv-perf");
            root.classList.toggle("wv-perf", perf);
            writeLS(LS_PERF, perf);
            sync();
        });

        bar.appendChild(bPerf);
        grupo.appendChild(lbl);
        grupo.appendChild(hint);
        grupo.appendChild(bar);
        host.appendChild(grupo);
        sync();
    }

    /* ======================================================================
       INÍCIO
       ====================================================================== */
    function init() {
        /* Modo leve liga sozinho quando o sistema pede menos movimento. */
        if (readLS(LS_PERF, false) || reduced) root.classList.add("wv-perf");

        var salva = readTxt(LS_CENA, "onda");
        if (CENAS[salva]) state.cena = salva;
        root.dataset.fundo = state.cena;

        mount();
        watchAuth();
        buildFundo();
        buildBar();
        seguirPaleta();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
