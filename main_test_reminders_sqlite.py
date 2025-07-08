import os
import pygame
import json # <--- ¡Añade esta importación para leer JSON!
import sys # <--- Añade esta importación para sys.exit() si es necesario en el futuro

# Asegúrate de que estas importaciones son correctas según tus archivos
from mqtt_utils_A import setup_mqtt, publish_lights_state, last_two_temperatures, fall_detected_flag
from voice_recognition import setup_vosk
from audio_processing import setup_pyaudio, escuchar_comando, grabar_mensaje_voz, convertir_a_ogg_opus
from gemini_utils import consultar_gemini # Esta función ahora asume que genai.configure ya fue llamado
import time
import datetime
import threading
import requests
import asyncio
from telegram import Bot
from telegram.error import TelegramError
import pywhatkit
import subprocess
import re
import sqlite3
import google.generativeai as genai # <--- ¡Añade esta importación para configurar Gemini aquí!

# --- CARGAR CONFIGURACIÓN DESDE ARCHIVO JSON ---
CONFIG_FILE = "config.json"
config = {}

try:
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        config = json.load(f)
    print(f"Configuración cargada desde {CONFIG_FILE}")
except FileNotFoundError:
    print(f"Error: El archivo de configuración '{CONFIG_FILE}' no se encontró. Usando valores predeterminados o vacíos.")
    # Puedes definir valores por defecto aquí si el archivo no existe
    # o salir si la configuración es crítica.
    # Para este caso, definimos valores predeterminados vacíos para evitar errores.
    config = {
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID": "",
        "WHATSAPP_CAREGIVER_NUMBER": "",
        "GEMINI_API_KEY": "",
        "CUSTOM_COMMANDS": {},
        "SYSTEM_STARTUP_SCRIPT": "Inicio.bat"
    }
except json.JSONDecodeError as e:
    print(f"Error al parsear el archivo de configuración JSON: {e}")
    sys.exit("Error de configuración. Verifique config.json.") # Salir si el JSON está mal formateado

# --- CONFIGURACIÓN DE RUTAS (ahora algunas se obtienen de config) ---
RESPONSES_DIR = "Respuestas"
TEMP_AUDIO_DIR = "TempAudio"
SYSTEM_STARTUP_SCRIPT = config.get("SYSTEM_STARTUP_SCRIPT", "Inicio.bat") # Obtener de config, con fallback

if not os.path.exists(RESPONSES_DIR):
    os.makedirs(RESPONSES_DIR)
if not os.path.exists(TEMP_AUDIO_DIR):
    os.makedirs(TEMP_AUDIO_DIR)

current_state = "OFF"

# --- CONFIGURACIÓN DE TELEGRAM (ahora usando valores de config) ---
TELEGRAM_BOT_TOKEN = config.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = config.get("TELEGRAM_CHAT_ID")
# Inicializa el bot solo si el token está presente
telegram_bot = Bot(token=TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None
if not telegram_bot:
    print("Advertencia: TELEGRAM_BOT_TOKEN no configurado. Las funciones de Telegram no estarán disponibles.")

# --- CONFIGURACIÓN DE WHATSAPP (ahora usando valores de config) ---
WHATSAPP_CAREGIVER_NUMBER = config.get("WHATSAPP_CAREGIVER_NUMBER") 
if not WHATSAPP_CAREGIVER_NUMBER:
    print("Advertencia: WHATSAPP_CAREGIVER_NUMBER no configurado. Las funciones de WhatsApp no estarán disponibles.")

# --- CONFIGURACIÓN DE GEMINI (¡AHORA AQUÍ!) ---
GEMINI_API_KEY = config.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    print("API de Gemini configurada exitosamente.")
else:
    print("Advertencia: GEMINI_API_KEY no configurada en config.json. Las funciones de Gemini no funcionarán.")

# --- CONFIGURACIÓN DE BASE DE DATOS SQLite ---
DB_NAME = "reminders.db"

# --- FUNCIONES DE ASISTENTE ---

def responder_con_voz(texto):
    """Convierte texto a voz y lo reproduce usando gTTS y pygame."""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    archivo_respuesta = os.path.join(RESPONSES_DIR, f"respuesta_{timestamp}.mp3")

    try:
        from gtts import gTTS
        tts = gTTS(text=texto, lang='es')
        tts.save(archivo_respuesta)

        if not pygame.mixer.get_init():
            pygame.mixer.init()
            
        pygame.mixer.music.load(archivo_respuesta)
        pygame.mixer.music.play()

        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)

    except Exception as e:
        print(f"Error al reproducir el sonido: {e}")

    finally:
        if pygame.mixer.get_init() and pygame.mixer.music.get_busy() == False:
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
            time.sleep(0.1)

        try:
            if os.path.exists(archivo_respuesta):
                os.remove(archivo_respuesta)
        except Exception as e:
            print(f"Error al eliminar el archivo de audio: {e}")

def vaciar_carpeta_respuestas():
    """Elimina todos los archivos en la carpeta 'Respuestas' cada 5 minutos."""
    while True:
        time.sleep(300)
        for archivo in os.listdir(RESPONSES_DIR):
            archivo_path = os.path.join(RESPONSES_DIR, archivo)
            try:
                if os.path.isfile(archivo_path):
                    os.remove(archivo_path)
                    print(f"Archivo eliminado: {archivo_path}")
            except Exception as e:
                print(f"Error al eliminar el archivo {archivo_path}: {e}")

async def enviar_mensaje_voz_telegram(chat_id, audio_filepath, caption="Mensaje de voz del sistema de asistencia."):
    """
    Envía un archivo de audio como mensaje de voz a un chat de Telegram.
    Ideal para mensajes de emergencia donde el tono es importante.
    """
    if not telegram_bot:
        print("Error: Bot de Telegram no inicializado. No se pudo enviar mensaje de voz.")
        return False
    try:
        with open(audio_filepath, 'rb') as audio_file:
            await telegram_bot.send_voice(chat_id=chat_id, voice=audio_file, caption=caption)
        print(f"Mensaje de voz enviado a Telegram a chat_id: {chat_id}")
        return True
    except TelegramError as e:
        print(f"Error de Telegram al enviar mensaje de voz: {e}")
        return False
    except FileNotFoundError:
        print(f"Error: Archivo de audio no encontrado en {audio_filepath}")
        return False
    except Exception as e:
        print(f"Error inesperado al enviar mensaje de voz a Telegram: {e}")
        return False

def enviar_alerta_whatsapp(phone_number, message_text):
    """
    Envía un mensaje de texto por WhatsApp usando pywhatkit.
    Nota: Esto abrirá una ventana del navegador. No recomendado para sistemas headless.
    """
    if not phone_number:
        print("Error: Número de cuidador de WhatsApp no configurado. No se pudo enviar mensaje.")
        return False
    try:
        pywhatkit.sendwhatmsg_instantly(phone_number, message_text, wait_time=15, tab_close=True)
        print(f"Mensaje de texto de alerta enviado a WhatsApp a {phone_number}")
        return True
    except Exception as e:
        print(f"Error al enviar mensaje de texto de alerta por WhatsApp: {e}")
        return False

def enviar_mensaje_telegram_texto(mensaje):
    """
    Envía un mensaje de texto plano a un chat de Telegram usando la API de requests.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Error: Token o Chat ID de Telegram no configurados. No se pudo enviar mensaje de texto.")
        return {"ok": False, "description": "Configuración de Telegram incompleta."}
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje}
    response = requests.post(url, data=data)
    return response.json()

def is_mosquitto_running():
    """
    Verifica si el proceso de Mosquitto está en ejecución en Windows.
    Retorna True si está corriendo, False en caso contrario.
    """
    try:
        result = subprocess.run(['tasklist', '/NH', '/FI', 'IMAGENAME eq mosquitto.exe'], 
                                 capture_output=True, text=True, check=False)
        
        if "mosquitto.exe" in result.stdout:
            return True
        return False
    except Exception as e:
        print(f"Error al verificar el estado de Mosquitto: {e}")
        return False

# MODIFICACIÓN CLAVE: Esta función ahora también intenta conectar el cliente MQTT
def iniciar_servidor_mqtt_y_sistema():
    """
    Ejecuta el script batch para iniciar el servidor MQTT.
    Luego intenta conectar el cliente MQTT y verifica el estado de Mosquitto.
    Retorna True si la conexión MQTT es exitosa, False en caso contrario.
    """
    script_name = SYSTEM_STARTUP_SCRIPT 
    base_dir = os.path.dirname(os.path.abspath(__file__))
    full_script_path = os.path.join(base_dir, script_name)

    if not os.path.exists(full_script_path):
        print(f"Error: El script de inicio del sistema no se encuentra en: {full_script_path}")
        responder_con_voz("Lo siento, no pude encontrar el script para encender el sistema. Por favor, verifique la instalación.")
        return False
    
    print(f"Intentando ejecutar '{full_script_path}' para iniciar el servidor de comunicación (Mosquitto)...")
    responder_con_voz("Intentando encender el servidor de comunicación. Esto puede tardar unos segundos.")
    
    try:
        # Ejecutar el script en segundo plano
        subprocess.Popen([full_script_path], shell=True, cwd=base_dir)
        print(f"'{full_script_path}' ejecutado correctamente (comando enviado).")
        
        # Dar tiempo a Mosquitto para que se inicie completamente
        time.sleep(7) # Aumentado a 7 segundos para mayor robustez

        if is_mosquitto_running():
            print("Servidor Mosquitto detectado en ejecución. Intentando conectar el cliente MQTT.")
            responder_con_voz("El servidor de comunicación está activo. Conectando al sistema.")
            
            try:
                # Intentar configurar el cliente MQTT (desde mqtt_utils_A)
                setup_mqtt() 
                print("Cliente MQTT conectado.")
                return True # Éxito en el inicio y conexión
            except Exception as e:
                print(f"Error al conectar el cliente MQTT después de iniciar Mosquitto: {e}")
                responder_con_voz("El servidor de comunicación está activo, pero no pude conectar con el sistema. Revise los errores.")
                return False
        else:
            responder_con_voz("El servidor de comunicación no se pudo iniciar. Por favor, reintente o revise los errores.")
            print("Error: Mosquitto no se detectó en ejecución después del intento de inicio.")
            return False 
    except Exception as e:
        print(f"Error al ejecutar el script '{full_script_path}': {e}")
        responder_con_voz("Lo siento, hubo un problema al ejecutar el script de inicio del sistema.")
        return False

async def handle_emergency_alert(stream, recognizer, source=""):
    """
    Función para manejar las acciones a tomar en caso de una emergencia (caída o botón de pánico).
    """
    print(f"--- ¡EMERGENCIA DETECTADA! Fuente: {source} ---")
    responder_con_voz("¡Alerta! Se ha detectado una emergencia. Activando protocolo de seguridad.")
    
    current_time_str = datetime.datetime.now().strftime("%I:%M %p del %d/%m/%Y")
    emergency_text = f"🚨 ALERTA DE EMERGENCIA 🚨\nSe ha detectado una emergencia ({source}) en el hogar a las {current_time_str}. Por favor, verifique."
    
    # Solo intentar enviar si la configuración de Telegram está presente
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        enviar_mensaje_telegram_texto(emergency_text)
    else:
        print("Advertencia: No se pudo enviar alerta de Telegram, configuración incompleta.")

    # Solo intentar enviar si la configuración de WhatsApp está presente
    if WHATSAPP_CAREGIVER_NUMBER:
        enviar_alerta_whatsapp(WHATSAPP_CAREGIVER_NUMBER, emergency_text)
    else:
        print("Advertencia: No se pudo enviar alerta de WhatsApp, número de cuidador no configurado.")

    publish_lights_state("ON") 

    responder_con_voz("¿Puedes decirme algo más sobre lo que pasó? Si quieres, puedes grabar un mensaje de voz para el cuidador.")
    responder_con_voz("Di 'grabar mensaje' para empezar, o 'cancelar' para continuar sin mensaje de voz.")
    
    decision = escuchar_comando(stream, recognizer, timeout=7)

    if "grabar mensaje" in decision:
        responder_con_voz("Por favor, di tu mensaje de voz después de la señal. Tienes 15 segundos.")
        time.sleep(1)
        
        recorded_file = grabar_mensaje_voz(stream, duration=15, filename_suffix="emergency_voice_message")
        
        if recorded_file and os.path.exists(recorded_file):
            converted_file = convertir_a_ogg_opus(recorded_file, output_ogg_file_suffix="emergency_voice_message_converted")
            if converted_file and os.path.exists(converted_file):
                if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
                    await enviar_mensaje_voz_telegram(TELEGRAM_CHAT_ID, converted_file, caption=f"¡MENSAJE DE VOZ DE EMERGENCIA desde el sistema ({source})!")
                    responder_con_voz("Mensaje de voz adicional enviado al cuidador.")
                else:
                    responder_con_voz("No pude enviar el mensaje de voz adicional. Se envió una alerta de texto.")
            else:
                responder_con_voz("No pude enviar el mensaje de voz adicional. Se envió una alerta de texto.")
        else:
            responder_con_voz("No pude grabar tu mensaje. Ya se envió una alerta de texto.")
    else:
        responder_con_voz("Entendido. Se ha enviado la alerta de emergencia principal. Permaneceré atento.")

    global fall_detected_flag
    fall_detected_flag = False
    print("--- Protocolo de emergencia finalizado ---")

# --- FUNCIONES DE BASE DE DATOS SQLite PARA RECORDATORIOS ---

def init_db():
    """Inicializa la base de datos de recordatorios y crea la tabla si no existe."""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                time_hour INTEGER NOT NULL,
                time_minute INTEGER NOT NULL,
                message TEXT NOT NULL,
                last_triggered_date TEXT -- Formato YYYY-MM-DD
            )
        """)
        conn.commit()
        conn.close()
        print(f"Base de datos {DB_NAME} inicializada correctamente.")
    except Exception as e:
        print(f"Error al inicializar la base de datos: {e}")

def add_reminder_to_db(hour, minute, message):
    """Añade un nuevo recordatorio a la base de datos."""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO reminders (time_hour, time_minute, message, last_triggered_date) VALUES (?, ?, ?, ?)",
                       (hour, minute, message, None)) # last_triggered_date comienza como NULL
        new_id = cursor.lastrowid
        conn.commit()
        conn.close()
        print(f"Recordatorio añadido a la DB con ID: {new_id}")
        return new_id
    except Exception as e:
        print(f"Error al añadir recordatorio a la DB: {e}")
        return None

def get_all_reminders_from_db():
    """Obtiene todos los recordatorios de la base de datos."""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT id, time_hour, time_minute, message, last_triggered_date FROM reminders")
        rows = cursor.fetchall()
        conn.close()
        
        loaded_reminders = []
        for row in rows:
            r_id, r_hour, r_minute, r_message, r_last_date_str = row
            try:
                time_obj = datetime.time(r_hour, r_minute)
                last_triggered_date = datetime.datetime.strptime(r_last_date_str, '%Y-%m-%d').date() if r_last_date_str else None
                loaded_reminders.append({
                    'id': r_id,
                    'time_obj': time_obj,
                    'message': r_message,
                    'last_triggered_date': last_triggered_date
                })
            except Exception as e:
                print(f"Error al procesar recordatorio de la DB (ID: {r_id}): {e}")
        return loaded_reminders
    except Exception as e:
        print(f"Error al obtener recordatorios de la DB: {e}")
        return []

def update_reminder_triggered_date_in_db(reminder_id, new_date_str):
    """Actualiza la fecha de la última vez que se activó un recordatorio."""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("UPDATE reminders SET last_triggered_date = ? WHERE id = ?", (new_date_str, reminder_id))
        conn.commit()
        conn.close()
        print(f"Recordatorio ID {reminder_id} actualizado a fecha: {new_date_str}")
    except Exception as e:
        print(f"Error al actualizar la fecha del recordatorio ID {reminder_id}: {e}")

def delete_reminder_from_db_by_id(reminder_id):
    """Elimina un recordatorio de la base de datos por su ID."""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        conn.commit()
        conn.close()
        print(f"Recordatorio ID {reminder_id} eliminado de la DB.")
        return cursor.rowcount > 0 
    except Exception as e:
        print(f"Error al eliminar recordatorio ID {reminder_id} de la DB: {e}")
        return False

def delete_reminders_from_db_by_message_part(message_part):
    """Elimina recordatorios de la base de datos por una parte de su mensaje."""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM reminders WHERE message LIKE ?", ('%' + message_part + '%',))
        conn.commit()
        conn.close()
        rows_deleted = cursor.rowcount
        print(f"{rows_deleted} recordatorios eliminados de la DB con mensaje '{message_part}'.")
        return rows_deleted
    except Exception as e:
        print(f"Error al eliminar recordatorios por mensaje de la DB: {e}")
        return 0

# --- FUNCIONES DE LÓGICA DE RECORDATORIOS ---

def parse_time_from_text(text):
    """
    Intenta extraer una hora (HH:MM) del texto en lenguaje natural.
    Soporta formatos como "a las ocho", "a las tres y cuarto de la tarde", "a las diez y treinta de la noche".
    Retorna un objeto datetime.time o None si no puede parsear.
    """
    time_map_hour = {
        'una': 1, 'dos': 2, 'tres': 3, 'cuatro': 4, 'cinco': 5, 'seis': 6, 'siete': 7,
        'ocho': 8, 'nueve': 9, 'diez': 10, 'once': 11, 'doce': 12
    }
    time_map_minute = {
        'cuarto': 15, 'media': 30, 'treinta': 30, 'quince': 15, 'cero': 0, 'y cuarto': 15, 'y media': 30
    }

    # Normalizar texto: reemplazar números en palabras por dígitos
    for word, num in time_map_hour.items():
        text = text.replace(word, str(num))
    for word, num in time_map_minute.items():
        text = text.replace(word, str(num))
    
    # Regex para encontrar patrones de tiempo: "a las HH [y MM] [de la MAÑANA/TARDE/NOCHE]"
    match = re.search(r'a las (\d+)(?: y (\d+))? (?:de la (mañana|tarde|noche))?', text)

    if match:
        hour_str = match.group(1)
        minute_str = match.group(2)
        period = match.group(3)

        try:
            hour = int(hour_str)
            minute = int(minute_str) if minute_str else 0

            # Ajustar la hora según el período (mañana/tarde/noche)
            if period == 'tarde' and hour < 12:
                hour += 12
            elif period == 'noche': 
                if hour >= 1 and hour < 12: 
                    hour += 12
                elif hour == 12: # 12 de la noche (medianoche)
                    hour = 0
            elif period == 'mañana' and hour == 12: # 12 de la mañana (mediodía)
                hour = 12 

            # Validar rangos de hora y minuto
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                return None
            
            return datetime.time(hour, minute)
        except ValueError:
            return None 
    return None 

def check_reminders_thread_func():
    """
    Hilo en segundo plano para verificar y activar recordatorios desde la base de datos.
    """
    print("Iniciando hilo de verificación de recordatorios...")
    while True:
        now = datetime.datetime.now()
        current_date = now.date()
        current_time = now.time()

        # Cargar recordatorios frescos de la DB en cada ciclo
        reminders_from_db = get_all_reminders_from_db() 
        
        for reminder in reminders_from_db: 
            if reminder['time_obj'].hour == current_time.hour and \
               reminder['time_obj'].minute == current_time.minute and \
               (reminder['last_triggered_date'] is None or reminder['last_triggered_date'] != current_date):
                
                print(f"Activando recordatorio: {reminder['message']} a las {current_time.strftime('%H:%M')}")
                responder_con_voz(f"¡Recordatorio! {reminder['message']}")
                
                # Actualizar la fecha de última activación en la base de datos
                update_reminder_triggered_date_in_db(reminder['id'], current_date.strftime('%Y-%m-%d'))
        
        # Dormir hasta el inicio del siguiente minuto para una verificación precisa
        time.sleep(60 - now.second if now.second != 0 else 60) 

# --- FUNCIÓN PRINCIPAL ASÍNCRONA ---

async def main_async():
    global current_state
    
    # 1. Configurar audio y reconocimiento de voz primero
    recognizer = setup_vosk()
    p, stream = setup_pyaudio()

    # 2. Intentar iniciar el sistema (servidor MQTT y cliente) automáticamente al inicio
    system_started_successfully = iniciar_servidor_mqtt_y_sistema()
    
    if system_started_successfully:
        responder_con_voz("Sistema de asistencia iniciado y listo para recibir comandos.")
    else:
        responder_con_voz("Sistema de asistencia iniciado, pero con problemas de comunicación. Algunas funciones podrían no estar disponibles.")

    # Iniciar hilos de tareas en segundo plano
    threading.Thread(target=vaciar_carpeta_respuestas, daemon=True).start()
    threading.Thread(target=check_reminders_thread_func, daemon=True).start() 

    # --- DICIONARIO DE COMANDOS (ahora fusionando con CUSTOM_COMMANDS de config) ---
    # Primero define tus comandos base/fijos
    comandos = {
        "encender luces": ["enciende las luces", "prender luces", "luces encendidas", "encender luces"],
        "apagar luces": ["apaga luces","apaga las luces", "luces apagadas", "apagar luces"],
        "temperatura": ["cuál es la temperatura", "consulta temperatura", "dime la temperatura"],
        "mensaje cuidador": ["mensaje al cuidador", "avisar cuidador", "llamar cuidador", "aviso cuidador", "enviar mensaje", "Auxilio", "emergencia"], # Mantener para re-intento manual
        "gemini": ["gemini", "pregunta a gemini", "una consulta", "una pregunta"], # Mantener para re-intento manual
        "hora" : ["qué hora es", "dime la hora", "hora actual", "cuál es la hora"],
        "encender sistema": ["enciende el sistema", "iniciar sistema", "prende el sistema"], # Mantener para re-intento manual
        "fecha y dia": ["qué día es hoy", "cuál es la fecha", "dime el día", "dime la fecha de hoy"],
        "añadir recordatorio": ["pon un recordatorio", "recuérdame", "añadir recordatorio de pastillas", "programar recordatorio"],
        "listar recordatorios": ["qué recordatorios tengo", "mis recordatorios", "dime mis recordatorios"],
        "eliminar recordatorio": ["borrar recordatorio", "quitar recordatorio", "eliminar recordatorio"],
    }
    
    # Fusionar los comandos personalizados del archivo de configuración
    for key, value in config.get("CUSTOM_COMMANDS", {}).items():
        if key in comandos:
            comandos[key].extend(value) # Añadir variantes a comandos existentes
        else:
            comandos[key] = value # Añadir nuevos comandos

    try:
        while True:
            global fall_detected_flag
            if fall_detected_flag:
                print("¡Caída detectada! Activando manejo de emergencia.")
                await handle_emergency_alert(stream, recognizer, source="detección de caída")
                continue 

            comando = escuchar_comando(stream, recognizer) 
            print(f"Comando detectado: {comando}")

            if any(variant in comando for variant in comandos["encender luces"]):
                publish_lights_state("ON")
                current_state = "ON"
                respuesta = "Luces encendidas."
                print(respuesta)
                responder_con_voz(respuesta)

            elif any(variant in comando for variant in comandos["apagar luces"]):
                publish_lights_state("OFF")
                current_state = "OFF"
                respuesta = "Luces apagadas."
                print(respuesta)
                responder_con_voz(respuesta)

            elif any(variant in comando for variant in comandos["temperatura"]):
                print("Consultando temperatura...")
                responder_con_voz("Consultando temperatura")
                if last_two_temperatures:
                    respuesta = f"La temperatura actual es de {last_two_temperatures[-1]} grados Celsius."
                    time.sleep(1)
                    print(respuesta)
                    responder_con_voz(respuesta)
                else:
                    respuesta = "Lo siento, aún no tengo datos de temperatura recientes."
                    print(respuesta)
                    responder_con_voz(respuesta)

            elif any(variant in comando for variant in comandos["gemini"]):
                print("Comando Gemini detectado.")
                if not GEMINI_API_KEY:
                    responder_con_voz("Lo siento, la clave de la API de Gemini no está configurada. No puedo responder preguntas.")
                    print("Error: Clave API de Gemini no configurada.")
                    continue

                responder_con_voz("De acuerdo, ¿cuál es tu pregunta?")
                time.sleep(1.0)
                pregunta_a_gemini = escuchar_comando(stream, recognizer, timeout=12)
                
                if not pregunta_a_gemini:
                    responder_con_voz("Lo siento, no he capturado tu pregunta. Por favor, inténtalo de nuevo.")
                    print("No se capturó ninguna pregunta para Gemini.")
                    continue 

                print(f"Pregunta a Gemini: '{pregunta_a_gemini}'")
                try:
                    # Llamada a consultar_gemini, que ahora no necesita la API_KEY como argumento
                    respuesta_gemini = consultar_gemini(pregunta_a_gemini)
                    if respuesta_gemini:
                        print(f"Gemini respondió: {respuesta_gemini}")
                        responder_con_voz(respuesta_gemini)
                    else:
                        responder_con_voz("Lo siento, no pude obtener una respuesta clara de Gemini.")
                except Exception as e:
                    print(f"Error al consultar Gemini: {e}")
                    responder_con_voz("Lo siento, hubo un problema al consultar a Gemini. Por favor, inténtalo de nuevo más tarde.")

            elif any(variant in comando for variant in comandos["hora"]): 
                hora_actual = datetime.datetime.now().strftime("%I:%M %p")
                respuesta = f"La hora actual es {hora_actual}."
                print(respuesta)
                responder_con_voz(respuesta)
            
            elif any(variant in comando for variant in comandos["mensaje cuidador"]): 
                print("Comando 'mensaje cuidador' detectado.")
                if not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID) and not WHATSAPP_CAREGIVER_NUMBER:
                    responder_con_voz("Lo siento, no tengo configurado ningún método para enviar mensajes al cuidador.")
                    print("Error: Métodos de envío de mensajes al cuidador no configurados.")
                    continue

                responder_con_voz("De acuerdo. ¿Qué mensaje quieres enviar al cuidador? Por favor, di tu mensaje ahora.")
                time.sleep(2.0)
                mensaje_para_cuidador = escuchar_comando(stream, recognizer, timeout=25)
                print(f"Mensaje para cuidador capturado: '{mensaje_para_cuidador}'")

                if mensaje_para_cuidador:
                    responder_con_voz("Voy a enviar el siguiente mensaje al cuidador:")
                    time.sleep(0.5)
                    responder_con_voz(mensaje_para_cuidador)
                    
                    time.sleep(2.0)
                    responder_con_voz("¿Quieres enviar este mensaje? Di 'sí' o 'no' en los próximos 7 segundos.")
                    confirmacion = escuchar_comando(stream, recognizer, timeout=7)
                    
                    if "sí" in confirmacion.lower() or "si" in confirmacion.lower():
                        try:
                            if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
                                respuesta_telegram = enviar_mensaje_telegram_texto(f"Mensaje del usuario: {mensaje_para_cuidador}")
                                if respuesta_telegram.get("ok"):
                                    responder_con_voz("¡Mensaje enviado correctamente a Telegram!")
                                else:
                                    responder_con_voz("Hubo un error al enviar el mensaje a Telegram.")
                            else:
                                print("Advertencia: No se pudo enviar mensaje de Telegram, configuración incompleta.")
                                responder_con_voz("No pude enviar el mensaje a Telegram porque no está configurado.")
                            
                            if WHATSAPP_CAREGIVER_NUMBER:
                                enviar_alerta_whatsapp(WHATSAPP_CAREGIVER_NUMBER, f"Mensaje del usuario: {mensaje_para_cuidador}")
                            else:
                                print("Advertencia: No se pudo enviar mensaje de WhatsApp, número de cuidador no configurado.")
                                responder_con_voz("No pude enviar el mensaje a WhatsApp porque no está configurado.")

                        except Exception as e:
                            print(f"Error de conexión o envío: {e}")
                            responder_con_voz("No pude enviar el mensaje al cuidador.")
                    else:
                        responder_con_voz("Envío de mensaje cancelado.")
                        print("Envío de mensaje cancelado.")
                else:
                    responder_con_voz("No he capturado ningún mensaje. Intenta de nuevo.")

            elif any(variant in comando for variant in comandos["fecha y dia"]):
                print("Comando de fecha y día detectado.")
                current_date = datetime.datetime.now()
                
                dias_semana = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
                meses_anyo = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
                
                dia_semana_str = dias_semana[current_date.weekday()]
                dia_mes = current_date.day
                mes_str = meses_anyo[current_date.month - 1]
                anyo = current_date.year

                respuesta_fecha = f"Hoy es {dia_semana_str}, {dia_mes} de {mes_str} de {anyo}."
                
                print(f"Fecha y día: {respuesta_fecha}")
                responder_con_voz(respuesta_fecha)

            # --- LÓGICA PARA AÑADIR RECORDATORIO ---
            elif any(variant in comando for variant in comandos["añadir recordatorio"]):
                print("Comando para añadir recordatorio detectado.")
                responder_con_voz("De acuerdo. ¿Qué te debo recordar y a qué hora? Por ejemplo, 'recordar tomar pastillas a las ocho de la noche'.")
                time.sleep(1.0)
                recordatorio_str = escuchar_comando(stream, recognizer, timeout=15)

                if recordatorio_str:
                    time_obj = parse_time_from_text(recordatorio_str)
                    
                    if time_obj:
                        message_raw = re.sub(r'(?:a las \d+(?: y \d+)? (?:de la (?:mañana|tarde|noche))?)|(?:recuerdame\s?)', '', recordatorio_str, flags=re.IGNORECASE).strip()
                        message = message_raw if message_raw else "un evento"

                        new_id = add_reminder_to_db(time_obj.hour, time_obj.minute, message.strip())
                        if new_id:
                            responder_con_voz(f"Recordatorio de '{message.strip()}' con ID {new_id} programado para las {time_obj.strftime('%I:%M %p').replace('AM', 'de la mañana').replace('PM', 'de la tarde')}.")
                        else:
                            responder_con_voz("Lo siento, no pude guardar el recordatorio en la base de datos.")
                    else:
                        responder_con_voz("No pude entender la hora del recordatorio. Por favor, intenta de nuevo diciendo la hora claramente.")
                else:
                    responder_con_voz("No he capturado el recordatorio. Por favor, inténtalo de nuevo.")

            # --- LÓGICA PARA LISTAR RECORDATORIOS ---
            elif any(variant in comando for variant in comandos["listar recordatorios"]):
                print("Comando para listar recordatorios detectado.")
                all_reminders = get_all_reminders_from_db()
                if all_reminders:
                    response_text = "Tienes los siguientes recordatorios:"
                    for r in all_reminders:
                        time_str = r['time_obj'].strftime('%I:%M %p').replace('AM', 'de la mañana').replace('PM', 'de la tarde')
                        response_text += f" Recordatorio número {r['id']}: '{r['message']}' a las {time_str}."
                    print(response_text)
                    responder_con_voz(response_text)
                else:
                    responder_con_voz("No tienes ningún recordatorio programado.")
            
            # --- LÓGICA PARA ELIMINAR RECORDATORIO ---
            elif any(variant in comando for variant in comandos["eliminar recordatorio"]):
                print("Comando para eliminar recordatorio detectado.")
                responder_con_voz("De acuerdo. ¿Qué recordatorio quieres eliminar? Di el número o una palabra clave del mensaje.")
                time.sleep(1.0)
                eliminar_str = escuchar_comando(stream, recognizer, timeout=10)

                if eliminar_str:
                    rows_deleted = 0
                    try:
                        eliminar_id = int(eliminar_str.strip())
                        if delete_reminder_from_db_by_id(eliminar_id):
                            rows_deleted = 1
                    except ValueError:
                        rows_deleted = delete_reminders_from_db_by_message_part(eliminar_str.strip())
                    
                    if rows_deleted > 0:
                        if rows_deleted == 1:
                            responder_con_voz("Recordatorio eliminado.")
                        else:
                            responder_con_voz(f"{rows_deleted} recordatorios eliminados.")
                    else:
                        responder_con_voz("No encontré ningún recordatorio con esa descripción o número para eliminar.")
                else:
                    responder_con_voz("No he capturado la descripción del recordatorio a eliminar. Por favor, inténtalo de nuevo.")

            # --- LÓGICA PRINCIPAL DEL COMANDO: ENCENDER SISTEMA ---
            # Este comando ahora re-intenta la secuencia de inicio
            elif any(variant in comando for variant in comandos["encender sistema"]):
                print("Comando 'encender sistema' detectado. Re-iniciando el proceso de activación.")
                iniciar_servidor_mqtt_y_sistema()
            
    except KeyboardInterrupt:
        print("Cerrando programa por interrupción del teclado...")
        responder_con_voz("Cerrando programa.")
        stream.stop_stream()
        stream.close()
        p.terminate()
    except Exception as e:
        print(f"Se ha producido un error inesperado en el bucle principal: {e}")
        responder_con_voz("Lo siento, se ha producido un error inesperado y necesito reiniciar.")

if __name__ == "__main__":
    init_db() # Inicializar la base de datos al inicio
    pygame.mixer.init() 
    asyncio.run(main_async())