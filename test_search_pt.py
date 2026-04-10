import faiss
import sqlite3
from sentence_transformers import SentenceTransformer

modelo = SentenceTransformer('clip-ViT-B-32')
idx = faiss.read_index('indice_faiss.bin')

conn = sqlite3.connect('metadados.db')
c = conn.cursor()
c.execute('SELECT id, nome FROM arquivos')
files = dict(c.fetchall())

def test_query(text):
    print(f'\n--- Test: {text} ---')
    q = modelo.encode([text]).astype('float32')
    faiss.normalize_L2(q)
    D, I = idx.search(q, 3)
    for dist, i in zip(D[0], I[0]):
        cos_sim = 1.0 - (dist / 2.0)
        print(f'  {files.get(int(i), "")}: {cos_sim:.2f} ({cos_sim*100:.0f}%)')

test_query('cat')
test_query('gato')
test_query('woman')
test_query('mulher')
