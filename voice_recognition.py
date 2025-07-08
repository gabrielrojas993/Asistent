# voice_recognition.py
from vosk import Model, KaldiRecognizer
import json
import os
import sys # <--- ¡Añade esta línea!

def setup_vosk():
    """Configura el modelo de reconocimiento de voz Vosk."""
    # La ruta del modelo Vosk debe ser relativa a la ubicación de donde se ejecuta main_A.py
    # Si main_A.py está en la raíz del proyecto, y el modelo está en Audio/vosk-model-small-es-0.42
    # CORRECCIÓN DE RUTA: Asumiendo que la carpeta vosk-model-small-es-0.42 está en el mismo nivel que tu ejecutable
    model_path = "vosk-model-small-es-0.42" # <--- ¡Cambia esta línea!
    
    if not os.path.exists(model_path):
        print(f"Error: El modelo Vosk no se encuentra en la ruta: {model_path}")
        print("Asegúrate de haber descargado y descomprimido el modelo allí.")
        sys.exit(1) # <--- ¡Cambia 'exit()' por 'sys.exit(1)'!

    model = Model(model_path)
    recognizer = KaldiRecognizer(model, 16000) 
    return recognizer

def reconocer_comando(recognizer, data):
    """
    Convierte el audio en texto usando el reconocimiento de voz de Vosk.
    Esta función es utilizada internamente por `audio_processing.escuchar_comando`.
    """
    if recognizer.AcceptWaveform(data):
        result = json.loads(recognizer.Result())
        return result.get("text", "")
    return ""