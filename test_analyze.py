import sys
import os
import glob
sys.path.insert(0, "backend")

from app import _analyze_image, OLLAMA_OK

print("OLLAMA_OK is", OLLAMA_OK)
files = glob.glob(r"C:\Users\Teste\Pictures\Screenshots\*.png")
if not files:
    print("Nenhuma imagem encontrada.")
    sys.exit(0)
    
test_file = files[0]
print("Testing file:", test_file)

try:
    res = _analyze_image(test_file, perfil="fast")
    print("RESULT:", res)
except Exception as e:
    print("FATAL ERROR:", e)
