from flask import request, jsonify
from services.ai_service import process_search

def handle_search():
    data = request.get_json()
    
    if not data or 'query' not in data:
        return jsonify({"erro": "Nenhum termo de busca fornecido."}), 400
    
    user_query = data['query']
    
    # Chama o serviço que faz a leitura dos arquivos
    resultados = process_search(user_query)
    
    return jsonify({
        "sucesso": True,
        "termo_buscado": user_query,
        "resultados": resultados
    }), 200