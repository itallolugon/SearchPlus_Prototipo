from flask import Blueprint
from controllers.search_controller import handle_search

search_bp = Blueprint('search_routes', __name__)

# Rota POST para receber a busca
search_bp.route('/search', methods=['POST'])(handle_search)