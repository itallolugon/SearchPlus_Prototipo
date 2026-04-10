import os
import atexit
import signal
import json
import psycopg2
import mimetypes
import tkinter as tk
from tkinter import filedialog
from psycopg2.extras import RealDictCursor
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, request, jsonify, send_from_directory, session
from flask_cors import CORS
from flaskwebgui import FlaskUI

mimetypes.add_type('text/css', '.css')
mimetypes.add_type('application/javascript', '.js')

from services.ai_service import process_search, iniciar_worker_background, parar_worker, get_system_status
app = Flask(__name__)
CORS(app, supports_credentials=True)
app.secret_key = 'chave_super_secreta_do_search_plus' 
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024 

DB_CONFIG = {
    'dbname': 'searchplus',
    'user': 'postgres',
    'password': '123456', 
    'host': 'localhost',
    'port': '5432'
}

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)

def init_postgres():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        conn.commit()
        cursor.close()
        conn.close()
        print("[OK] Banco PostgreSQL inicializado.")
    except Exception as e:
        print(f"[ERRO] Erro PostgreSQL: {e}")

def load_config():
    default_config = {
        "pastas": [], 
        "historico_pastas": False,
        "tema": "dark",
        "idioma": "pt-BR",
        "cor_primaria": "#A855F7",
        "cor_secundaria": "#E879F9",
        "cor_texto_botao": "#FFFFFF",
        "bg_url": "",
        "bg_blur": 15,
        "perfil_nome": "Visitante",
        "perfil_handle": "", 
        "perfil_cargo": "Pesquisador",
        "perfil_local": "Brasil",
        "perfil_bio": "Explorando os dados do Search+.",
        "perfil_avatar": "https://api.dicebear.com/7.x/avataaars/svg?seed=Felix",
        "perfil_banner": "https://images.unsplash.com/photo-1550684848-fac1c5b4e853?q=80&w=1200&auto=format&fit=crop"
    }
    
    config_path = 'config.json'
    if os.path.exists(config_path):
        try:
            if os.path.getsize(config_path) > 5 * 1024 * 1024:
                os.remove(config_path)
                return default_config

            with open(config_path, 'r', encoding='utf-8') as f:
                content = f.read()
                if not content.strip(): return default_config
                data = json.loads(content)
                for key, value in default_config.items():
                    if key not in data or data[key] == "":
                        data[key] = value
                return data
        except Exception:
            return default_config 
            
    return default_config

def save_config(config_data):
    try:
        with open('config.json', 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=4)
    except Exception as e:
        print(f"Erro ao salvar config: {e}")

@app.route('/api/register', methods=['POST'])
def register():
    dados = request.get_json()
    username = dados.get('username')
    password = dados.get('password')

    if not username or not password: 
        return jsonify({"status": "erro", "mensagem": "Usuário e senha são obrigatórios."}), 400

    hashed_pw = generate_password_hash(password)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO usuarios (username, password_hash) VALUES (%s, %s)', (username, hashed_pw))
        conn.commit()
        cursor.close()
        conn.close()
        
        config = load_config()
        config['perfil_nome'] = username
        save_config(config)
        
        return jsonify({"status": "sucesso", "mensagem": "Usuário criado com sucesso!"})
    except psycopg2.errors.UniqueViolation:
        return jsonify({"status": "erro", "mensagem": "Este nome de usuário já existe."}), 409
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

@app.route('/api/login', methods=['POST'])
def login():
    dados = request.get_json()
    username = dados.get('username')
    password = dados.get('password')

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM usuarios WHERE username = %s', (username,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            return jsonify({"status": "sucesso", "mensagem": "Login efetuado!"})
        else:
            return jsonify({"status": "erro", "mensagem": "Usuário ou senha incorretos."}), 401
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": f"Erro no banco: {e}"}), 500

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"status": "sucesso"})

@app.route('/api/check_session', methods=['GET'])
def check_session():
    if 'user_id' in session: 
        return jsonify({"logado": True, "username": session['username']})
    return jsonify({"logado": False}), 401

@app.route('/api/search', methods=['POST', 'OPTIONS'])
def search():
    if request.method == 'OPTIONS': return '', 200
    if 'user_id' not in session: return jsonify({"erro": "Acesso negado"}), 401
    dados = request.get_json()
    query = dados.get('query', '')
    resultados = process_search(query)
    return jsonify(resultados)

@app.route('/api/status', methods=['GET'])
def status():
    try:
        return jsonify(get_system_status())
    except:
        return jsonify({"status": "Offline", "arquivos_pendentes": 0, "arquivos_processados_sessao": 0})

@app.route('/api/config', methods=['GET', 'POST'])
def config():
    if 'user_id' not in session: return jsonify({"erro": "Acesso negado"}), 401
    if request.method == 'GET':
        return jsonify(load_config())
    if request.method == 'POST':
        novas_configs = request.get_json()
        save_config(novas_configs)
        return jsonify({"status": "sucesso"})

@app.route('/api/folders', methods=['GET'])
def get_folders():
    if 'user_id' not in session: return jsonify({"erro": "Acesso negado"}), 401
    return jsonify(load_config())

@app.route('/api/folders', methods=['POST'])
def add_folder():
    if 'user_id' not in session: return jsonify({"erro": "Acesso negado"}), 401
    dados = request.get_json()
    nova_pasta = dados.get('pasta')
    config = load_config()
    
    if nova_pasta:
        if nova_pasta not in config["pastas"]:
            config["pastas"].append(nova_pasta)
            config["historico_pastas"] = True
            save_config(config)
            
    return jsonify(config)

@app.route('/api/favorites/toggle', methods=['POST'])
def api_toggle_favorite():
    if 'user_id' not in session: return jsonify({"erro": "Acesso negado"}), 401
    dados = request.get_json()
    id_arquivo = dados.get('id')
    import sqlite3
    try:
        conn = sqlite3.connect('metadados.db')
        cursor = conn.cursor()
        cursor.execute("SELECT favorito FROM arquivos WHERE id = ?", (id_arquivo,))
        row = cursor.fetchone()
        if row:
            novo_status = 0 if row[0] == 1 else 1
            cursor.execute("UPDATE arquivos SET favorito = ? WHERE id = ?", (novo_status, id_arquivo))
            conn.commit()
            return jsonify({"status": "sucesso", "favorito": bool(novo_status)})
        return jsonify({"erro": "Arquivo nao encontrado"}), 404
    except Exception as e:
        return jsonify({"erro": str(e)}), 500
    finally:
        if 'conn' in locals(): conn.close()

@app.route('/api/favorites', methods=['GET'])
def api_get_favorites():
    if 'user_id' not in session: return jsonify({"erro": "Acesso negado"}), 401
    import sqlite3
    try:
        conn = sqlite3.connect('metadados.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM arquivos WHERE favorito = 1 ORDER BY id DESC")
        rows = cursor.fetchall()
        resultados = []
        for row in rows:
            resultados.append({
                "id": row['id'],
                "nome": row['nome'],
                "caminho": row['caminho'],
                "tipo": row['tipo'],
                "data": dict(row).get('data_processamento', ''),
                "favorito": True
            })
        return jsonify({"resultados": resultados})
    except Exception as e:
        return jsonify({"erro": str(e)}), 500
    finally:
        if 'conn' in locals(): conn.close()

@app.route('/api/folders', methods=['DELETE'])
def remove_folder():
    if 'user_id' not in session: return jsonify({"erro": "Acesso negado"}), 401
    dados = request.get_json()
    pasta_remover = dados.get('pasta')
    config = load_config()
    
    if "pastas" in config and pasta_remover in config["pastas"]:
        config["pastas"].remove(pasta_remover)
        save_config(config)
        
    return jsonify(config)

@app.route('/api/choose_folder', methods=['GET'])
def choose_folder():
    if 'user_id' not in session: return jsonify({"erro": "Acesso negado"}), 401
    root = tk.Tk()
    root.attributes("-topmost", True)
    root.withdraw()
    folder_path = filedialog.askdirectory(title="Selecione a Pasta para Importar")
    root.destroy()
    if folder_path:
        folder_path = os.path.normpath(folder_path)
        return jsonify({"status": "sucesso", "pasta": folder_path})
    return jsonify({"status": "cancelado"})

@app.route('/api/choose_image', methods=['GET'])
def choose_image():
    if 'user_id' not in session: return jsonify({"erro": "Acesso negado"}), 401
    root = tk.Tk()
    root.attributes("-topmost", True)
    root.withdraw()
    file_path = filedialog.askopenfilename(
        title="Selecione uma Imagem",
        filetypes=[("Imagens", "*.png;*.jpg;*.jpeg;*.gif;*.webp")]
    )
    root.destroy()
    if file_path:
        file_path = os.path.normpath(file_path)
        return jsonify({"status": "sucesso", "caminho": file_path})
    return jsonify({"status": "cancelado"})

@app.route('/fonts/<path:filename>')
def serve_fonts(filename):
    return send_from_directory('fonts', filename)

@app.route('/api/file/<path:filename>')
def serve_file(filename):
    if 'user_id' not in session: return jsonify({"erro": "Acesso negado"}), 401
    try:
        if os.path.isabs(filename):
            directory = os.path.dirname(filename)
            file = os.path.basename(filename)
            return send_from_directory(directory, file)
        return "Caminho inválido", 404
    except Exception:
        return "Arquivo não encontrado", 404

@app.route('/')
def index(): 
    return send_from_directory('.', 'index.html')

@app.route('/<path:filename>')
def serve_static(filename): 
    return send_from_directory('.', filename)

def desligamento_seguro(signum=None, frame=None): 
    parar_worker()

if __name__ == '__main__':
    atexit.register(desligamento_seguro)
    signal.signal(signal.SIGINT, desligamento_seguro)
    signal.signal(signal.SIGTERM, desligamento_seguro)

    init_postgres() 
    iniciar_worker_background()
    FlaskUI(app=app, server="flask", port=5000, width=1200, height=800).run()