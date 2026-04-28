import urllib.request
import json
import sys
import time

model_name = "llava"
print(f"==================================================")
print(f" Baixando IA Visual ({model_name}) do Ollama... ")
print(f"==================================================")
print("Isso pode levar de 5 a 20 minutos dependendo da sua internet (Aprox 4.7 GB).\n")

data = json.dumps({"name": model_name}).encode('utf-8')
req = urllib.request.Request("http://localhost:11434/api/pull", data=data, method="POST")

try:
    with urllib.request.urlopen(req) as response:
        for line in response:
            if line:
                try:
                    d = json.loads(line.decode('utf-8'))
                    status = d.get('status', '')
                    if 'completed' in d and 'total' in d:
                        pct = (d['completed'] / d['total']) * 100
                        print(f"\rProgresso: [{status}] {pct:.1f}% ({d['completed']//1024//1024} MB / {d['total']//1024//1024} MB)", end="")
                    else:
                        print(f"\rStatus: {status}".ljust(60), end="")
                except:
                    pass
    print("\n\n✅ Download do LLaVA concluído com sucesso!")
    print("O motor de IA agora está 100% pronto para uso no Search+.")
except Exception as e:
    print(f"\n\n❌ Erro ao baixar o modelo: {e}")
    print("Certifique-se de que o Ollama está rodando no seu computador.")

print("\nPode fechar esta janela.")
