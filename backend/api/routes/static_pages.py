import os
from flask import Blueprint, send_from_directory

bp = Blueprint('static_pages', __name__)

FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../frontend'))
PUBLIC_DIR = os.path.join(FRONTEND_DIR, 'public')

@bp.route('/')
def index():
    return send_from_directory(PUBLIC_DIR, 'index.html')

@bp.route('/<path:path>')
def serve_static(path):
    public_path = os.path.join(PUBLIC_DIR, path)
    if os.path.exists(public_path) and not os.path.isdir(public_path):
        return send_from_directory(PUBLIC_DIR, path)
    frontend_path = os.path.join(FRONTEND_DIR, path)
    if os.path.exists(frontend_path) and not os.path.isdir(frontend_path):
        return send_from_directory(FRONTEND_DIR, path)
    return "Not Found", 404
