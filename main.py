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
from flask import Flask
from threading import Thread

# --- 1. SERVIDOR FALSO PARA RENDER (KEEP ALIVE) ---
app = Flask('')

@app.route('/')
def home():
    return "🤖 El Bot de Liga MX está VIVO y trabajando."

def run_web_server():
    # Render asigna un puerto dinámico, lo leemos aquí
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.start()

# --- 2. CONFIGURACIÓN DEL BOT ---
TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
bot = telebot.TeleBot(TOKEN)

URL_DATOS_HISTORICOS = "https://www.football-data.co.uk/new/MEX.csv"
URL_CALENDARIO = "https://www.espn.com.mx/futbol/calendario/_/liga/mex.1"

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

# --- 3. LÓGICA DE ANÁLISIS ---
def obtener_datos_historicos():
    try:
        df = pd.read_csv(URL_DATOS_HISTORICOS, on_bad_lines='skip')
        df['Date'] = pd.to_datetime(df['Date'], dayfirst=True)
        return df.sort_values('Date', ascending=False)
    except:
        return None

def normalizar_nombre(nombre_raw, lista_objetivo):
    nombre_clean = str(nombre_raw).lower().replace("fc", "").strip()
    for k, v in EQUIPOS_MAPA.items():
        if k in nombre_clean:
            matches = get_close_matches(v, lista_objetivo, n=1, cutoff=0.6)
            if matches: return matches[0]
    matches = get_close_matches(nombre_clean, lista_objetivo, n=1, cutoff=0.4)
    if matches: return matches[0]
    return None

def analizar_partido(local_raw, visita_raw, df_hist):
    equipos_csv = pd.concat([df_hist['Home'], df_hist['Away']]).unique()
    local = normalizar_nombre(local_raw, equipos_csv)
    visita = normalizar_nombre(visita_raw, equipos_csv)
    
    if not local or not visita: return None

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
        "prob_visita": prob_v * 100
    }

def buscar_partidos_hoy():
    print("🔍 Buscando partidos en ESPN...")
    try:
        tablas = pd.read_html(URL_CALENDARIO)
        partidos_hoy = []
        for tabla in tablas:
            if len(tabla.columns) >= 2:
                for index, row in tabla.iterrows():
                    try:
                        equipo1 = row[0]
                        equipo2 = row[1] 
                        if isinstance(equipo1, str) and isinstance(equipo2, str):
                            if len(equipo1) > 3 and len(equipo2) > 3:
                                partidos_hoy.append((equipo1, equipo2))
                    except: continue
        return partidos_hoy
    except Exception as e:
        print(f"Error scraping: {e}")
        return []

def tarea_diaria():
    print("⏰ Ejecutando tarea diaria...")
    partidos = buscar_partidos_hoy()
    if not partidos:
        print("No encontré partidos claros hoy.")
        return

    df_hist = obtener_datos_historicos()
    if df_hist is None: return

    reporte = "🤖 **REPORTE LIGA MX** 🤖\n\n"
    hay_predicciones = False

    for p in partidos:
        local_raw, visita_raw = p
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
                f"L: {p_l:.1f}% | E: {analisis['prob_empate']:.1f}% | V: {p_v:.1f}%\n"
                f"Predicción: {icono}\n"
                f"---\n"
            )

    if hay_predicciones and CHAT_ID:
        try:
            bot.send_message(CHAT_ID, reporte, parse_mode="Markdown")
            print("Mensaje enviado.")
        except Exception as e:
            print(f"Error enviando mensaje: {e}")

# --- 4. EJECUCIÓN PRINCIPAL ---

# Arrancamos el servidor web falso en un hilo separado
keep_alive()

# Programamos la tarea (Ajusta la hora según necesites)
schedule.every().day.at("10:00").do(tarea_diaria)
# schedule.every(10).minutes.do(tarea_diaria) # Descomenta esto para probar rápido (cada 10 mins)

print("🤖 Bot iniciado con Servidor Web Falso. Esperando...")

while True:
    schedule.run_pending()
    time.sleep(60)
