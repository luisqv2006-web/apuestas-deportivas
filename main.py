import os
import telebot
import pandas as pd
import numpy as np
from scipy.stats import poisson
from difflib import get_close_matches
import schedule
import time
from datetime import datetime
import pytz

# --- CONFIGURACIÓN ---
TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID') # ¡OJO! Necesitas tu ID de usuario
bot = telebot.TeleBot(TOKEN)

# URL de datos históricos para el análisis
URL_DATOS_HISTORICOS = "https://www.football-data.co.uk/new/MEX.csv"
# URL para ver qué partidos hay HOY (Calendario ESPN MX)
URL_CALENDARIO = "https://www.espn.com.mx/futbol/calendario/_/liga/mex.1"

# Mapa de equipos (Tus correcciones manuales para que coincidan las fuentes)
EQUIPOS_MAPA = {
    "america": "Club America", "club america": "Club America",
    "guadalajara": "Guadalajara", "chivas": "Guadalajara",
    "cruz azul": "Cruz Azul", "unam": "Unam Pumas", "pumas": "Unam Pumas",
    "tigres": "Tigres", "tigres uanl": "Tigres",
    "monterrey": "Monterrey", "rayados": "Monterrey",
    "toluca": "Toluca", "pachuca": "Pachuca", "leon": "Leon",
    "santos": "Santos Laguna", "santos laguna": "Santos Laguna",
    "atlas": "Atlas", "puebla": "Puebla",
    "san luis": "San Luis", "atletico san luis": "San Luis",
    "juarez": "Juarez", "fc juarez": "Juarez",
    "mazatlan": "Mazatlan FC", "mazatlan fc": "Mazatlan FC",
    "necaxa": "Necaxa", "queretaro": "Queretaro",
    "tijuana": "Tijuana", "xolos": "Tijuana"
}

# --- 1. MOTOR DE ANÁLISIS (EL CEREBRO) ---
def obtener_datos_historicos():
    try:
        df = pd.read_csv(URL_DATOS_HISTORICOS, on_bad_lines='skip')
        df['Date'] = pd.to_datetime(df['Date'], dayfirst=True)
        return df.sort_values('Date', ascending=False)
    except:
        return None

def normalizar_nombre(nombre_raw, lista_objetivo):
    # Limpieza básica
    nombre_clean = str(nombre_raw).lower().replace("fc", "").strip()
    
    # 1. Búsqueda directa en diccionario
    for k, v in EQUIPOS_MAPA.items():
        if k in nombre_clean:
            # Validar que el valor del mapa exista en la lista objetivo (CSV)
            matches = get_close_matches(v, lista_objetivo, n=1, cutoff=0.6)
            if matches: return matches[0]

    # 2. Búsqueda difusa (Fuzzy matching)
    matches = get_close_matches(nombre_clean, lista_objetivo, n=1, cutoff=0.4)
    if matches: return matches[0]
    return None

def analizar_partido(local_raw, visita_raw, df_hist):
    equipos_csv = pd.concat([df_hist['Home'], df_hist['Away']]).unique()
    
    local = normalizar_nombre(local_raw, equipos_csv)
    visita = normalizar_nombre(visita_raw, equipos_csv)
    
    if not local or not visita:
        return None # No se pudieron identificar los equipos

    # Lógica de Poisson Ponderada
    def get_stats(team, is_home):
        if is_home:
            partidos = df_hist[df_hist['Home'] == team].head(5)
            g = partidos['HG'].values; c = partidos['AG'].values
        else:
            partidos = df_hist[df_hist['Away'] == team].head(5)
            g = partidos['AG'].values; c = partidos['HG'].values
        
        if len(g) == 0: return 1.0, 1.0
        pesos = np.arange(len(g), 0, -1)
        return max(0.1, np.average(g, weights=pesos)), max(0.1, np.average(c, weights=pesos))

    atq_l, def_l = get_stats(local, True)
    atq_v, def_v = get_stats(visita, False)
    
    FACTOR_LOCALIA = 1.20
    xg_l = (atq_l * def_v) * FACTOR_LOCALIA
    xg_v = (atq_v * def_l)
    
    prob_l, prob_e, prob_v = 0, 0, 0
    for i in range(6):
        for j in range(6):
            p = poisson.pmf(i, xg_l) * poisson.pmf(j, xg_v)
            if i > j: prob_l += p
            elif i == j: prob_e += p
            else: prob_v += p
            
    return {
        "local": local, "visita": visita,
        "prob_local": prob_l * 100,
        "prob_empate": prob_e * 100,
        "prob_visita": prob_v * 100,
        "xg_local": xg_l, "xg_visita": xg_v
    }

# --- 2. BUSCADOR DE PARTIDOS (EL OJO) ---
def buscar_partidos_hoy():
    print("🔍 Buscando partidos en ESPN...")
    try:
        # Pandas lee las tablas de la web de ESPN automáticamente
        tablas = pd.read_html(URL_CALENDARIO)
        
        partidos_hoy = []
        fecha_hoy = datetime.now(pytz.timezone('America/Mexico_City')).strftime("%d de %b") # Formato ESPN aprox
        
        # Como ESPN cambia formatos, una estrategia simple es traer TODO lo que encuentre
        # y filtrar lo que parezca un partido de hoy.
        # NOTA: Para este ejemplo simple, asumiremos que si la tabla tiene datos, son los proximos partidos.
        
        for tabla in tablas:
            # Intentamos limpiar la tabla
            if len(tabla.columns) >= 2:
                for index, row in tabla.iterrows():
                    # Estructura usual ESPN: Local, Resultado/Hora, Visitante
                    try:
                        equipo1 = row[0]
                        equipo2 = row[1] 
                        # Validación muy básica de texto
                        if isinstance(equipo1, str) and isinstance(equipo2, str):
                            if len(equipo1) > 3 and len(equipo2) > 3:
                                partidos_hoy.append((equipo1, equipo2))
                    except:
                        continue
                        
        return partidos_hoy
    except Exception as e:
        print(f"Error scraping calendario: {e}")
        return []

# --- 3. TAREA AUTOMATICA ---
def tarea_diaria():
    print("⏰ Ejecutando tarea diaria...")
    partidos = buscar_partidos_hoy()
    
    if not partidos:
        print("No encontré partidos claros para hoy.")
        return

    df_hist = obtener_datos_historicos()
    if df_hist is None: return

    reporte = "🤖 **REPORTE DIARIO LIGA MX** 🤖\n\n"
    hay_predicciones = False

    for p in partidos:
        local_raw, visita_raw = p
        # Limpieza extra de nombres de ESPN que suelen venir con hora
        # Ejemplo: "América 21:00" -> quitamos la hora si podemos, o confiamos en el normalizador
        
        analisis = analizar_partido(local_raw, visita_raw, df_hist)
        
        if analisis:
            hay_predicciones = True
            p_l = analisis['prob_local']
            p_v = analisis['prob_visita']
            
            icono = "⚖️"
            if p_l > 55: icono = "🔥 LOCAL"
            elif p_v > 55: icono = "🔥 VISITA"
            
            reporte += (
                f"⚽ **{analisis['local']} vs {analisis['visita']}**\n"
                f"Probabilidades: {p_l:.1f}% - {analisis['prob_empate']:.1f}% - {p_v:.1f}%\n"
                f"Predicción: {icono}\n"
                f"-----------------------------\n"
            )

    if hay_predicciones and CHAT_ID:
        bot.send_message(CHAT_ID, reporte, parse_mode="Markdown")
        print("Mensaje enviado a Telegram.")
    else:
        print("Se encontraron partidos pero no se pudieron emparejar con la base de datos histórica.")

# --- 4. CONFIGURACIÓN DEL SERVIDOR (RENDER) ---
# Programar la tarea todos los días a las 10:00 AM hora México
schedule.every().day.at("10:00").do(tarea_diaria)

# Endpoint falso para que Render sepa que estamos vivos (opcional si usas worker)
# Pero como usaremos script simple:
print("🤖 Bot iniciado. Esperando hora programada...")

# Si quieres probarlo INMEDIATAMENTE al subir, descomenta la siguiente línea:
# tarea_diaria()

while True:
    schedule.run_pending()
    time.sleep(60) # Revisar cada minuto
