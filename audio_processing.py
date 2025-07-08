# Audio/audio_processing.py
import pyaudio
import json
import time
import wavio 
from pydub import AudioSegment 
import numpy as np 
import os # Importar os para la ruta de archivos temporales

# Asegúrate de tener FFmpeg instalado y en tu PATH para que pydub funcione con OGG/Opus

# Importa el directorio temporal desde main_A.py o defínelo aquí si lo prefieres local
# Para este ejemplo, lo haré localmente para que este módulo sea autocontenido,
# pero en tu setup, lo ideal es que main_A.py lo defina y lo pase o lo importe si es global.
TEMP_AUDIO_DIR_LOCAL = "TempAudio" 
if not os.path.exists(TEMP_AUDIO_DIR_LOCAL):
    os.makedirs(TEMP_AUDIO_DIR_LOCAL)


def setup_pyaudio():
    """Configura el flujo de audio con PyAudio."""
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=8000)
    stream.start_stream()
    return p, stream

def escuchar_comando(stream, recognizer, timeout=5):
    """
    Escucha un comando de voz, lo transcribe usando Vosk y lo retorna.
    Tiene un tiempo máximo de escucha.
    """
    print("Escuchando comando...")
    
    start_time = time.time()
    
    # Resetear el reconocedor para asegurar que no haya resultados parciales anteriores
    recognizer.Reset()

    while True:
        data = stream.read(4096, exception_on_overflow=False) # Usar un chunk más pequeño para procesamiento más rápido
        if recognizer.AcceptWaveform(data):
            result = recognizer.Result()
            texto = json.loads(result)["text"]
            if texto:
                return texto
        
        if time.time() - start_time > timeout:
            print("Tiempo máximo de escucha de comando alcanzado.")
            # Obtener el resultado final incluso si no hubo una pausa clara
            final_result = json.loads(recognizer.FinalResult())["text"]
            return final_result


def grabar_mensaje_voz(stream, duration=10, filename_suffix="voice_message"):
    """
    Graba audio del micrófono por una duración específica y lo guarda en un archivo WAV temporal.
    
    Args:
        stream: El objeto stream de PyAudio para la captura.
        duration (int): Duración máxima de la grabación en segundos.
        filename_suffix (str): Sufijo para el nombre del archivo (ej. "emergency_voice_message").
    
    Returns:
        str: La ruta del archivo grabado si la grabación fue exitosa, None en caso contrario.
    """
    fs = 16000 
    frames = []
    print(f"Grabando mensaje de voz por hasta {duration} segundos. Habla ahora...")
    
    start_time = time.time()
    
    # Generar un nombre de archivo único para evitar colisiones
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(TEMP_AUDIO_DIR_LOCAL, f"{filename_suffix}_{timestamp}.wav")

    try:
        while True:
            data = stream.read(8000, exception_on_overflow=False) 
            frames.append(data)
            
            if time.time() - start_time > duration:
                break
        
        print(f"Grabación finalizada. Guardando como {filename}")
        
        audio_data = np.frombuffer(b''.join(frames), dtype=np.int16)
        wavio.write(filename, audio_data, fs, sampwidth=2) 
        
        return filename
    except Exception as e:
        print(f"Error durante la grabación del mensaje de voz: {e}")
        return None
    
def convertir_a_ogg_opus(input_wav_file, output_ogg_file_suffix="voice_message_converted"):
    """
    Convierte un archivo WAV a OGG (Opus codec), ideal para mensajes de voz de Telegram.
    Requiere FFmpeg.
    
    Args:
        input_wav_file (str): Ruta al archivo WAV de entrada.
        output_ogg_file_suffix (str): Sufijo para el nombre del archivo OGG de salida.
        
    Returns:
        str: La ruta del archivo OGG convertido si fue exitoso, None en caso contrario.
    """
    # Generar un nombre de archivo único para la salida OGG
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_ogg_file = os.path.join(TEMP_AUDIO_DIR_LOCAL, f"{output_ogg_file_suffix}_{timestamp}.ogg")

    try:
        audio = AudioSegment.from_wav(input_wav_file)
        audio.export(output_ogg_file, format="ogg", codec="libopus")
        print(f"Archivo convertido a OGG Opus: {output_ogg_file}")
        return output_ogg_file
    except FileNotFoundError:
        print("Error: FFmpeg no encontrado. Asegúrate de tenerlo instalado y en tu PATH.")
        return None
    except Exception as e:
        print(f"Error al convertir a OGG Opus: {e}")
        return None