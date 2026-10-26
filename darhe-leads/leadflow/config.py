"""Reglas y listas configurables. Si cambian las reglas de negocio, se cambian AQUÍ."""

# --- Reglas de calificación (provisionales, dadas por DARHE) ---
SEGMENTOS_OBJETIVO = {"transportista", "restaurantero", "construccion", "empresario"}
MIN_EMPLEADOS = 20          # A requiere >= 20; menos de 20 => C
EMPLEADOS_ALTO_POTENCIAL = 100  # B con esta cifra o más se marca para revisión (podría ser A)

# --- Sinónimos de segmento (se comparan sin acentos y en minúsculas) ---
SEGMENTOS_ALIAS = {
    "transportista": ["transportista", "transporte", "fletes", "flete", "autotransporte"],
    "restaurantero": ["restaurantero", "restaurantera", "restaurant", "restaurante", "restaurantes"],
    "construccion": ["construccion", "constructora", "constructor"],
    "empresario": ["empresario", "empresaria", "empresarios", "empresa", "pyme"],
}

# Pistas para inferir segmento SOLO cuando viene vacío (siempre se marca para revisión)
SEGMENTO_PISTAS_EMPRESA = {
    "transportista": ["transportes", "fletes", "autotransporte", "logistica"],
    "restaurantero": ["restaurante", "restaurant", "taqueria", "gastronomic", "cocina"],
    "construccion": ["constructora", "construccion", "obras"],
}

# --- Competidores: se busca en empresa, nombre y dominio del correo (sin acentos) ---
# Agrega aquí nombres reales de competidores conocidos.
COMPETIDORES = ["competencia"]

# --- Spam ---
SPAM_PALABRAS = [
    r"gana\s*dinero", r"ganadinero", r"gana\s*\$", r"\$\$\$", r"haz\s*clic", r"click\s*here",
    r"casino", r"bitcoin", r"cripto", r"viagra", r"premio\s*gratis", r"prestamo\s*inmediato",
]
SPAM_DOMINIOS = ["spam", "mailinator", "tempmail", "10minutemail", "guerrillamail"]
SPAM_UMBRAL = 2  # puntos; 1 punto = sospechoso (va a revisión), 2+ = descartado

CORREOS_PERSONALES = {"gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "live.com", "icloud.com"}

# --- Señales en el mensaje (texto sin acentos, minúsculas) ---
PAT_COTIZACION = r"cotiz|presupuesto|propuesta|\bquote\b|quotation"
PAT_DEMO = r"\bdemo\b|demostracion|prueba gratis|\btrial\b"
PAT_PROBLEMA = (r"caos|problema|necesit|queremos dejar|dejar de|controlar|rotacion|desorden|"
                r"perdida|fraude|robo|no podemos|retraso|errores|automatiz|digitaliz")
PAT_PRECIO = r"cuanto cuesta|precio|costo|how much|price|comision"
PAT_URGENCIA = r"\burge\b|urgente|esta semana|lo antes posible|cuanto antes|asap|hoy mismo|inmediat"
PAT_CANAL = r"mis clientes|para mi cliente|mis cliente"   # posible revendedor / canal
PAT_INGLES = r"\b(the|do you|we have|we are|hi|hello|please|for|our)\b"
PAT_URL = r"https?://|www\."

# Cifras de personal que se pueden leer del mensaje ("90 operadores", "somos como 60")
PAT_EMPLEADOS_MSG = [
    r"(\d{1,5})\s*(?:empleados|trabajadores|operadores|colaboradores|personas|employees|workers|choferes|conductores|cuadrilleros|meseros)",
    r"somos\s+(?:como\s+|unos\s+|aprox\w*\s+)?(\d{1,5})",
]
