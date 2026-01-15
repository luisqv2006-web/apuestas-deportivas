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

# --- 1. SERVIDOR FALSO ---
app = Flask('')

@app.route('/')
def home():
    return "🤖 Bot Liga MX v6.0 (GOD MODE - Monte Carlo): ONLINE."

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.start()

# --- 2. CONFIGURACIÓN ---
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
    "necaxa": "Necaxa", "queretaro": "Queretaro", "gallos": "Queretaro",
    "tijuana": "Tijuana", "xolos": "Tijuana"
}

# --- 3. MOTOR MATEMÁTICO NIVEL DIOS ---

def obtener_datos():
    try:
        df = pd.read_csv(URL_DATOS_HISTORICOS, on_bad_lines='skip')
        df['Date'] = pd.to_datetime(df['Date'], dayfirst=True)
        return df.sort_values('Date', ascending=True)
    except: return None

def normalizar_nombre(nombre_raw, lista_objetivo):
    nombre_clean = str(nombre_raw).lower().replace("fc", "").strip()
    for k, v in EQUIPOS_MAPA.items():
        if k in nombre_clean:
            matches = get_close_matches(v, lista_objetivo, n=1, cutoff=0.6)
            if matches: return matches[0]
    matches = get_close_matches(nombre_clean, lista_objetivo, n=1, cutoff=0.4)
    if matches: return matches[0]
    return None

# --- A. EXPECTATIVA PITAGÓRICA (Detectar Suerte) ---
def calcular_pitagoras(df, equipo):
    # Fórmula: GolesFavor^2 / (GolesFavor^2 + GolesContra^2)
    # Esto predice el % de victorias "real" sin el factor suerte
    partidos = df[(df['Home'] == equipo) | (df['Away'] == equipo)].tail(10)
    gf = 0
    gc = 0
    
    for _, row in partidos.iterrows():
        if row['Home'] == equipo:
            gf += row['HG']; gc += row['AG']
        else:
            gf += row['AG']; gc += row['HG']
            
    if gf == 0 and gc == 0: return 0.50
    
    exp_pyth = (gf**2) / ((gf**2) + (gc**2))
    return exp_pyth # Retorna valor entre 0 y 1

# --- B. VOLATILIDAD (Detectar Caos) ---
def calcular_volatilidad(df, equipo):
    # Calcula la Desviación Estándar de los goles
    # Si es alta, el equipo es impredecible.
    local = df[df['Home'] == equipo]['HG']
    visita = df[df['Away'] == equipo]['AG']
    todos_goles = pd.concat([local, visita]).tail(10)
    
    if len(todos_goles) < 2: return 0
    return todos_goles.std()

# --- C. SIMULACIÓN MONTE CARLO (El Cerebro) ---
def simulacion_monte_carlo(xg_l, xg_v, n_simulaciones=10000):
    # Simulamos el partido 10,000 veces usando numpy (muy rápido)
    goles_local_sim = np.random.poisson(xg_l, n_simulaciones)
    goles_visita_sim = np.random.poisson(xg_v, n_simulaciones)
    
    victorias_l = np.sum(goles_local_sim > goles_visita_sim)
    empates = np.sum(goles_local_sim == goles_visita_sim)
    victorias_v = np.sum(goles_local_sim < goles_visita_sim)
    
    # Probabilidad de Over 2.5 en la simulación
    total_goles = goles_local_sim + goles_visita_sim
    over_2_5 = np.sum(total_goles > 2.5)
    
    return {
        "local": (victorias_l / n_simulaciones) * 100,
        "empate": (empates / n_simulaciones) * 100,
        "visita": (victorias_v / n_simulaciones) * 100,
        "over": (over_2_5 / n_simulaciones) * 100
    }

def analizar_partido_god(local_raw, visita_raw, df):
    equipos_csv = pd.concat([df['Home'], df['Away']]).unique()
    local = normalizar_nombre(local_raw, equipos_csv)
    visita = normalizar_nombre(visita_raw, equipos_csv)
    
    if not local or not visita: return None

    # 1. Obtener xG Base
    def get_xg_base(team, is_home):
        p = df[df['Home' if is_home else 'Away'] == team].tail(8)
        if len(p) == 0: return 1.2
        return np.mean(p['HG' if is_home else 'AG'])
    
    xg_l_base = get_xg_base(local, True)
    xg_v_base = get_xg_base(visita, False)
    
    # Ajuste por defensa rival
    def get_def_weakness(team, is_home):
        # Que tantos goles permite el rival cuando juega fuera/casa
        p = df[df['Home' if not is_home else 'Away'] == team].tail(8)
        if len(p) == 0: return 1.0
        return np.mean(p['HG' if not is_home else 'AG'])

    def_l = get_def_weakness(local, True) # Qué tan malo es el local defendiendo
    def_v = get_def_weakness(visita, False) # Qué tan malo es el visita defendiendo
    
    # xG Final Ponderado
    xg_final_l = (xg_l_base + def_v) / 2 * 1.15 # 15% ventaja local
    xg_final_v = (xg_v_base + def_l) / 2

    # 2. Ejecutar Monte Carlo
    mc_results = simulacion_monte_carlo(xg_final_l, xg_final_v)
    
    # 3. Calcular Métricas "Pro"
    pyth_l = calcular_pitagoras(df, local)
    pyth_v = calcular_pitagoras(df, visita)
    vol_l = calcular_volatilidad(df, local)
    vol_v = calcular_volatilidad(df, visita)
    
    # Interpretación de Volatilidad
    riesgo = "Bajo"
    if vol_l > 1.5 or vol_v > 1.5: riesgo = "ALTO (Equipos Inestables)"
    elif vol_l > 1.2 or vol_v > 1.2: riesgo = "Medio"

    return {
        "local": local, "visita": visita,
        "mc": mc_results,
        "pyth_l": pyth_l, "pyth_v": pyth_v,
        "riesgo": riesgo,
        "xg_l": xg_final_l, "xg_v": xg_final_v
    }

def buscar_partidos_hoy():
    print("🔍 Buscando partidos...")
    try:
        tablas = pd.read_html(URL_CALENDARIO)
        partidos = []
        for t in tablas:
            if len(t.columns) >= 2:
                for _, r in t.iterrows():
                    try:
                        if isinstance(r[0], str) and len(r[0]) > 3: partidos.append((r[0], r[1]))
                    except: continue
        return partidos
    except: return []

def tarea_diaria():
    print("⚡ Iniciando GOD MODE v6.0...")
    partidos = buscar_partidos_hoy()
    if not partidos: return

    df = obtener_datos()
    if df is None: return

    reporte = "💎 **LIGA MX PREDICCIÓN ÉLITE (v6.0)** 💎\n"
    reporte += "_Simulación Monte Carlo (10,000 partidos)_\n\n"
    
    hay_datos = False

    for p in partidos:
        data = analizar_partido_god(p[0], p[1], df)
        if data:
            hay_datos = True
            mc = data['mc']
            
            # Decisión Inteligente
            pick = "No Tocar / Muy Cerrado"
            emoji = "😐"
            
            # Criterio Pitagórico (La prueba de la verdad)
            # Si Monte Carlo dice que gana Local, pero Pitágoras dice que Local juega mal... CUIDADO
            check_pyth = True
            if mc['local'] > 50 and data['pyth_l'] < 0.40: check_pyth = False # Falso favorito
            
            if mc['local'] > 55 and check_pyth:
                pick = f"Gana {data['local']}"
                emoji = "🏠💰"
            elif mc['visita'] > 50 and data['pyth_v'] > 0.45:
                pick = f"Gana {data['visita']}"
                emoji = "✈️💰"
            elif mc['over'] > 60:
                pick = "Alta de Goles (+2.5)"
                emoji = "⚽🔥"
            
            # Alerta de Riesgo
            alerta = ""
            if data['riesgo'] == "ALTO (Equipos Inestables)":
                alerta = "\n⚠️ **CUIDADO:** Partido de alto riesgo (Volátil)."

            reporte += (
                f"🆚 **{data['local']}** vs **{data['visita']}**\n"
                f"🎲 Probs: {mc['local']:.1f}% - {mc['empate']:.1f}% - {mc['visita']:.1f}%\n"
                f"📉 Pitágoras: {data['pyth_l']:.2f} vs {data['pyth_v']:.2f}\n"
                f"🎯 **PICK:** {emoji} {pick}\n"
                f"{alerta}\n"
                f"──────────────────\n"
            )

    if hay_datos and CHAT_ID:
        try:
            bot.send_message(CHAT_ID, reporte, parse_mode="Markdown")
            print("Reporte enviado.")
        except Exception as e: print(e)

# --- 4. ARRANQUE ---
keep_alive()

# Ajuste horario: 10:00 AM México (16:00 UTC)
schedule.every().day.at("16:00").do(tarea_diaria)

print("🤖 Bot GOD MODE v6.0 Listo.")

# Descomentar para probar YA
# tarea_diaria()

while True:
    schedule.run_pending()
    time.sleep(60)
