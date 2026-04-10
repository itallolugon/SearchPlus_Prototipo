import os
import time
import json
import threading
import sqlite3
import numpy as np
import traceback
from datetime import datetime

# ==========================================
# CONFIGURAÇÕES E PASTAS
# ==========================================
CONFIG_FILE = 'config.json'
DB_FILE = 'metadados.db'
FAISS_FILE = 'indice_faiss.bin'

# Tentativa de carregar bibliotecas de IA
try:
    import faiss
    from sentence_transformers import SentenceTransformer
    from PIL import Image
    import easyocr
    from transformers import BlipProcessor, BlipForConditionalGeneration, MarianMTModel, MarianTokenizer
    import torch
    IA_DISPONIVEL = True
except ImportError:
    IA_DISPONIVEL = False

# Telemetria para o Front-end
status_sistema = {
    "status": "Inativo",
    "arquivos_pendentes": 0,
    "arquivos_processados_sessao": 0,
    "ultimo_tempo": 0,
    "pastas_monitoradas": 0
}

stop_event = threading.Event()
modelo_clip = None
leitor_ocr = None
blip_processor = None
blip_model = None
tradutor_en_pt = None
tok_en_pt = None
tradutor_pt_en = None
tok_pt_en = None

def traduzir_en_pt(texto):
    if not texto or not tradutor_en_pt: return ""
    tokens = tok_en_pt(texto, return_tensors="pt", padding=True)
    out = tradutor_en_pt.generate(**tokens)
    return tok_en_pt.decode(out[0], skip_special_tokens=True)

def traduzir_pt_en(texto):
    if not texto or not tradutor_pt_en: return ""
    tokens = tok_pt_en(texto, return_tensors="pt", padding=True)
    out = tradutor_pt_en.generate(**tokens)
    return tok_pt_en.decode(out[0], skip_special_tokens=True)

# ==========================================
# INICIALIZAÇÃO DO MOTOR
# ==========================================
def carregar_modelos():
    global modelo_clip, leitor_ocr
    global blip_processor, blip_model
    global tradutor_en_pt, tok_en_pt, tradutor_pt_en, tok_pt_en

    if IA_DISPONIVEL and modelo_clip is None:
        try:
            print("[...] Carregando Modelos Neurais (pode demorar na primeira vez)...")
            modelo_clip = SentenceTransformer('clip-ViT-B-32')
            leitor_ocr = easyocr.Reader(['pt', 'en'], gpu=False)
            
            print("[...] Carregando modelo BLIP de Descricao de Imagens...")
            blip_processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
            blip_model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base")
            
            print("[...] Carregando Tradutores Offline (MarianMT)...")
            tok_en_pt = MarianTokenizer.from_pretrained("Helsinki-NLP/opus-mt-tc-big-en-pt")
            tradutor_en_pt = MarianMTModel.from_pretrained("Helsinki-NLP/opus-mt-tc-big-en-pt")
            
            tok_pt_en = MarianTokenizer.from_pretrained("Helsinki-NLP/opus-mt-pt-en")
            tradutor_pt_en = MarianMTModel.from_pretrained("Helsinki-NLP/opus-mt-pt-en")
            
            print("[OK] Modelos Neurais Prontos!")
        except Exception as e:
            print(f"[ERRO] Erro ao carregar modelos: {e}")

def iniciar_banco():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS arquivos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT,
            caminho TEXT UNIQUE,
            tipo TEXT,
            texto_extraido TEXT,
            data_processamento TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            favorito INTEGER DEFAULT 0
        )
    ''')
    try:
        cursor.execute("ALTER TABLE arquivos ADD COLUMN favorito INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass # Coluna já existe
    conn.commit()
    conn.close()

def load_folders():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get("pastas", [])
        except:
            return []
    return []

def get_system_status():
    status_sistema["pastas_monitoradas"] = len(load_folders())
    return status_sistema

# ==========================================
# BUSCA VETORIAL (FAISS)
# ==========================================
def process_search(query):
    query = query.lower().strip()
    start_time = time.time()
    resultados = []

    if not IA_DISPONIVEL or not os.path.exists(FAISS_FILE) or not query:
        return {"resultados": [], "tempo_busca": 0}

    try:
        # Traduz a busca para bater com o CLIP e BLIP (inglês)
        query_en = traduzir_pt_en(query)
        if not query_en: query_en = query

        # Busca real usando o modelo CLIP
        query_embedding = modelo_clip.encode([query_en]).astype('float32')
        faiss.normalize_L2(query_embedding)
        index = faiss.read_index(FAISS_FILE)
        distancias, indices = index.search(query_embedding, 20)

        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        for dist, doc_id in zip(distancias[0], indices[0]):
            if doc_id == -1: continue
            cursor.execute("SELECT * FROM arquivos WHERE id = ?", (int(doc_id),))
            row = cursor.fetchone()

            if row and os.path.exists(row['caminho']):
                # Conversão L2 Normalizada para Cosine Similarity (0 a 1)
                cos_sim = max(0.01, float(1.0 - (dist / 2.0)))
                # Ajuste Visual: CLIP raramente passa de 0.3 na similaridade texto-imagem. Multiplicamos por 3.5 para parecer 0-100% amigável.
                score_calc = min(1.0, cos_sim * 3.5)

                
                resultados.append({
                    "id": row['id'],
                    "nome": row['nome'],
                    "caminho": row['caminho'],
                    "tipo": row['tipo'],
                    "score": score_calc,
                    "favorito": bool(row['favorito']),
                    "data": row['data_processamento'],
                    "trecho": row['texto_extraido'][:120] + "..." if row['texto_extraido'] else "Match visual detectado.",
                    "conteudo": row['texto_extraido'] or "Arquivo visual."
                })
        conn.close()
    except Exception:
        import traceback
        print(f"[ERRO] Erro na busca vetorial:\n{traceback.format_exc()}")

    resultados = sorted(resultados, key=lambda x: x['score'], reverse=True)
    status_sistema["ultimo_tempo"] = round(time.time() - start_time, 2)
    return {"resultados": resultados, "tempo_busca": status_sistema["ultimo_tempo"]}
# ==========================================
# WORKER LOOP (PROCESSAMENTO EM BACKGROUND)
# ==========================================
def worker_loop():
    iniciar_banco()
    carregar_modelos()
    
    arquivos_ja_processados = set()
    dimensao_vetor = 512 # Padrão do CLIP
    
    status_sistema["status"] = "Monitorando Pastas"

    while not stop_event.is_set():
        pastas = load_folders()
        if not pastas or not IA_DISPONIVEL:
            time.sleep(5)
            continue

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Sincroniza memória com o que já está no banco de dados
        cursor.execute("SELECT caminho FROM arquivos")
        for row in cursor.fetchall():
            arquivos_ja_processados.add(row[0])

        arquivos_para_processar = []
        for pasta in pastas:
            if os.path.exists(pasta):
                for root, _, files in os.walk(pasta):
                    for f in files:
                        if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                            caminho = os.path.join(root, f)
                            if caminho not in arquivos_ja_processados:
                                arquivos_para_processar.append(caminho)

        status_sistema["arquivos_pendentes"] = len(arquivos_para_processar)
        
        if arquivos_para_processar:
            status_sistema["status"] = "Processando IA..."
            
            # Carrega ou cria índice FAISS
            if os.path.exists(FAISS_FILE):
                index = faiss.read_index(FAISS_FILE)
            else:
                index = faiss.IndexIDMap(faiss.IndexFlatL2(dimensao_vetor))

            for caminho in arquivos_para_processar:
                if stop_event.is_set(): break
                
                try:
                    nome_arq = os.path.basename(caminho)
                    tipo_arq = nome_arq.split('.')[-1].lower()

                    # 1. CLIP Embedding
                    img = Image.open(caminho).convert('RGB')
                    vetor = modelo_clip.encode([img]).astype('float32')
                    faiss.normalize_L2(vetor)

                    # BLIP Legenda Visual
                    caption_pt = ""
                    try:
                        inputs = blip_processor(img, return_tensors="pt")
                        out = blip_model.generate(**inputs, max_new_tokens=40)
                        caption_en = blip_processor.decode(out[0], skip_special_tokens=True)
                        caption_pt = "Análise da IA: " + traduzir_en_pt(caption_en)
                    except: pass

                    # 2. OCR
                    texto_extraido = ""
                    try:
                        res_ocr = leitor_ocr.readtext(caminho, detail=0)
                        if res_ocr:
                            texto_extraido = " | Texto na Imagem: " + " ".join(res_ocr)
                    except: pass
                    
                    texto_completo = caption_pt + texto_extraido

                    # 3. Salva no Banco e FAISS
                    cursor.execute("INSERT INTO arquivos (nome, caminho, tipo, texto_extraido) VALUES (?, ?, ?, ?)",
                                 (nome_arq, caminho, tipo_arq, texto_completo))
                    doc_id = cursor.lastrowid
                    conn.commit()

                    index.add_with_ids(vetor, np.array([doc_id]))
                    faiss.write_index(index, FAISS_FILE)

                    arquivos_ja_processados.add(caminho)
                    status_sistema["arquivos_processados_sessao"] += 1
                    
                except Exception:
                    print(f"[ERRO] Erro ao ler imagem {caminho}:\n{traceback.format_exc()}")
                
                status_sistema["arquivos_pendentes"] -= 1
            
            status_sistema["status"] = "Monitorando Pastas"
        
        conn.close()
        time.sleep(5)

# ==========================================
# CONTROLE DO PROCESSO
# ==========================================
def iniciar_worker_background():
    stop_event.clear()
    t = threading.Thread(target=worker_loop, daemon=True)
    t.start()

def parar_worker():
    stop_event.set()
    status_sistema["status"] = "Inativo"