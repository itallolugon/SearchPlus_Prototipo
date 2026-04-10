import os
from transformers import BlipProcessor, BlipForConditionalGeneration, MarianMTModel, MarianTokenizer
from sentence_transformers import SentenceTransformer
import whisper

LOCAL_MODELS_DIR = "local_models"

def baixar_tudo():
    os.makedirs(LOCAL_MODELS_DIR, exist_ok=True)
    print("======================================================")
    print("🚀 INICIANDO O DOWNLOAD SEGURO DAS IAs (MODO SAFETENSORS)")
    print("======================================================")
    print("Aguarde... As barras de progresso vão aparecer abaixo.\n")

    print("1/4 - Baixando IA Visual (BLIP - ~1GB)...")
    p = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-base")
    m = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-base", use_safetensors=True)
    p.save_pretrained(os.path.join(LOCAL_MODELS_DIR, "blip-base"))
    m.save_pretrained(os.path.join(LOCAL_MODELS_DIR, "blip-base"))
    print("✅ IA Visual concluída!\n")

    print("2/4 - Baixando IA Semântica (MiniLM - ~400MB)...")
    m = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    m.save(os.path.join(LOCAL_MODELS_DIR, "minilm"))
    print("✅ IA Semântica concluída!\n")

    print("3/4 - Baixando IA de Tradução (~300MB)...")
    t = MarianTokenizer.from_pretrained("Helsinki-NLP/opus-mt-tc-big-en-pt")
    m = MarianMTModel.from_pretrained("Helsinki-NLP/opus-mt-tc-big-en-pt", use_safetensors=True)
    t.save_pretrained(os.path.join(LOCAL_MODELS_DIR, "tradutor"))
    m.save_pretrained(os.path.join(LOCAL_MODELS_DIR, "tradutor"))
    print("✅ IA de Tradução concluída!\n")

    print("4/4 - Baixando IA de Áudio/Vídeo (Whisper - ~460MB)...")
    whisper.load_model("small", download_root=os.path.join(LOCAL_MODELS_DIR, "whisper"))
    print("✅ IA de Áudio/Vídeo concluída!\n")

    print("======================================================")
    print("🎉 SUCESSO ABSOLUTO! Todas as IAs foram baixadas.")
    print("Seu software agora escuta, lê, vê e traduz 100% OFFLINE.")
    print("======================================================")

if __name__ == "__main__":
    baixar_tudo()