import faiss
import sqlite3
from sentence_transformers import SentenceTransformer

modelo = SentenceTransformer('clip-ViT-B-32')
idx = faiss.read_index('indice_faiss.bin')

conn = sqlite3.connect('metadados.db')
c = conn.cursor()
c.execute('SELECT id, nome FROM arquivos')
files = dict(c.fetchall())

print('--- Test: cat ---')
q1 = modelo.encode(['cat']).astype('float32')
D, I = idx.search(q1, 5)
for dist, i in zip(D[0], I[0]):
    print(f'  {files.get(int(i), "")}: {dist}')

print('--- Test: gato ---')
q2 = modelo.encode(['gato']).astype('float32')
D, I = idx.search(q2, 5)
for dist, i in zip(D[0], I[0]):
    print(f'  {files.get(int(i), "")}: {dist}')
