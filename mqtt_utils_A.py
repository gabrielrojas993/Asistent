# mqtt_utils_A.py
import paho.mqtt.client as mqtt
import threading
import time # Asegúrate de importar time para usar time.sleep

BROKER_ADDRESS = "192.168.1.12"  # ¡Mantén esta IP!
TOPIC_LUCES = "robot/luces"
TOPIC_TEMPERATURA = "robot/temperatura"
TOPIC_CAIDA_DETECTADA = "hogar/emergencia/caida/detectada"

client = mqtt.Client()

last_two_temperatures = []
fall_detected_flag = False
fall_flag_lock = threading.Lock() 

def on_connect(client, userdata, flags, rc):
    """Callback cuando el cliente MQTT se conecta al broker."""
    if rc == 0:
        print("Conexión exitosa al broker MQTT.")
        client.subscribe(TOPIC_TEMPERATURA)
        client.subscribe(TOPIC_CAIDA_DETECTADA)
        print(f"Suscrito a tópico: {TOPIC_TEMPERATURA}")
        print(f"Suscrito a tópico: {TOPIC_CAIDA_DETECTADA}")
    else:
        print(f"Error al conectar al broker MQTT, código: {rc} - {mqtt.connack_string(rc)}")
        # Aquí puedes añadir más lógica de depuración si rc indica un problema específico.
        # Por ejemplo, si rc=5, es un error de autenticación/autorización.

def on_message(client, userdata, msg):
    """Callback para manejar los mensajes recibidos desde el broker MQTT."""
    global last_two_temperatures 
    global fall_detected_flag
    
    if msg.topic == TOPIC_TEMPERATURA:
        try:
            temperature = float(msg.payload.decode()) 
            print(f"Temperatura recibida: {temperature}")

            last_two_temperatures.append(temperature)
            if len(last_two_temperatures) > 2:
                last_two_temperatures.pop(0)
            print(f"Últimas temperaturas: {last_two_temperatures}")
        except ValueError:
            print(f"Mensaje de temperatura inválido: {msg.payload.decode()}")
        except Exception as e:
            print(f"Error procesando mensaje de temperatura: {e}")
    
    elif msg.topic == TOPIC_CAIDA_DETECTADA:
        with fall_flag_lock:
            fall_detected_flag = True
        print(f"¡Mensaje de ALERTA DE CAÍDA recibido!: {msg.payload.decode()}")

def setup_mqtt():
    """Configura y conecta el cliente MQTT con reintentos."""
    client.on_connect = on_connect
    client.on_message = on_message
    
    max_retries = 10  # Aumenta los intentos
    retry_delay_seconds = 3 # Espera más entre reintentos
    
    for i in range(max_retries):
        try:
            print(f"Intento {i+1}/{max_retries}: Conectando a broker MQTT en: {BROKER_ADDRESS}:{1883}...")
            # Usar 'port' en lugar de 'mqtt_port' para consistencia con la sintaxis de paho-mqtt
            client.connect(BROKER_ADDRESS, port=1883, keepalive=60) 
            client.loop_start() # Inicia el loop de red en un hilo separado
            print("Cliente MQTT: Loop de red iniciado exitosamente.")
            return # Conexión exitosa, salir de la función
        except ConnectionRefusedError: # Específico para cuando el broker no está escuchando
            print(f"Conexión rechazada por el broker. Asegúrate de que Mosquitto está corriendo y escuchando en {BROKER_ADDRESS}:1883.")
        except Exception as e:
            print(f"Error general al conectar con el broker MQTT (Intento {i+1}): {e}")
        
        if i < max_retries - 1:
            print(f"Reintentando conexión en {retry_delay_seconds} segundos...")
            time.sleep(retry_delay_seconds)
        else:
            print("Máximo de reintentos de conexión MQTT alcanzado. El cliente no pudo conectar.")
            # Puedes considerar aquí una notificación de fallo grave si la conexión MQTT es indispensable.

def publish_lights_state(state):
    """Publica el estado de las luces en el broker MQTT."""
    if client.is_connected():
        client.publish(TOPIC_LUCES, state, qos=1)
        print(f"Publicado en {TOPIC_LUCES}: {state}")
    else:
        print("Error: Cliente MQTT no conectado. No se pudo publicar el estado de las luces. (Desde publish_lights_state)")