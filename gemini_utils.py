# gemini_utils.py
import google.generativeai as genai
# No necesitamos 'import os' aquí ya que no leeremos variables de entorno ni manejaremos rutas de archivos.

# ¡Importante! 'genai.configure(api_key=YOUR_API_KEY)'
# AHORA SE LLAMARÁ EN main_test_reminders_sqlite.py
# después de cargar la clave desde config.json.
# Por lo tanto, no se configura aquí directamente.

# Crear la instancia del modelo (fuera de la función para mantener la sesión)
# El modelo se inicializa una vez que la API ha sido configurada globalmente.
# Si genai.configure no se ha llamado aún, esto podría fallar.
# Para asegurar que la inicialización del modelo es segura, la moveremos
# para que se haga después de que la API esté configurada en main_test_reminders_sqlite.py,
# o asegurarnos de que `model` y `chat_session` se manejen de una forma que permita la re-configuración.

# Una forma más robusta es inicializar el modelo y la sesión de chat dentro
# de una función de inicialización que reciba la clave API, o que confíe
# en que genai.configure() ya ha sido llamado.

# Vamos a mantener la inicialización aquí, asumiendo que main_test_reminders_sqlite.py
# configurará genai *antes* de que este módulo sea realmente usado (es decir, antes de llamar a consultar_gemini).
# Si hay problemas, podríamos necesitar una función 'init_gemini' aquí.
model = genai.GenerativeModel("gemini-1.5-flash")
chat_session = model.start_chat(history=[])


def consultar_gemini(pregunta):
    """
    Envía una pregunta a la API de Gemini y devuelve la respuesta.
    Mantiene el contexto del chat.
    Asume que genai.configure() ya ha sido llamado en el script principal
    con la clave API correcta.
    """
    try:
        # Prefijo para indicar que la respuesta debe ser en español y amable
        prefijo = "Responde en español y con un tono amable y de cuidado a personas adultas, tambien se algo breve con las respuestas: "
        pregunta_modificada = prefijo + pregunta
        
        # Enviar el mensaje y obtener la respuesta
        respuesta = chat_session.send_message(pregunta_modificada)
        
        if hasattr(respuesta, 'text'):
            return respuesta.text 
        else:
            return "Lo siento, no pude obtener una respuesta clara de Gemini."

    except Exception as e:
        print(f"Error al consultar Gemini: {e}")
        return "Lo siento, hubo un problema al consultar Gemini."