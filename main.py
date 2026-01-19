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
# Librerías de MLB
from pybaseball import team_batting, team_pitching

# --- 1. SERVIDOR FALSO (KEEP ALIVE) ---
app = Flask('')

@app.route('/')
def home():
    return "🤖 SUPER-BOT (Liga MX + MLB) Activo."

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

# URLs y Mapas
URL_LIGAMX = "https://www.football-data.co.uk/new/MEX.csv"
URL_CALENDARIO_LIGAMX = "https://www.espn.com.mx/futbol/calendario/_/liga/mex.1"
URL_CALENDARIO_MLB = "https://www.espn.com.mx/beisbol/mlb/calendario"

EQUIPOS_MX = {
    "america": "Club America", "guadalajara": "Guadalajara", "chivas": "Guadalajara",
    "cruz azul": "Cruz Azul", "pumas": "Unam Pumas", "tigres": "Tigres",
    "monterrey": "Monterrey", "toluca": "Toluca", "pachuca": "Pachuca", "leon": "Leon",
    "santos": "Santos Laguna", "atlas": "Atlas", "puebla": "Puebla", "san luis": "San Luis",
    "juarez": "Juarez", "mazatlan": "Mazatlan FC", "necaxa": "Necaxa", "queretaro": "Queretaro",
    "tijuana": "Tijuana", "xolos": "Tijuana"
}

# Diccionario de MLB (Nombres ESPN vs Pybaseball)
EQUIPOS_MLB = {
    "ny yankees": "NYY", "yankees": "NYY", "boston": "BOS", "red sox": "BOS",
    "baltimore": "BAL", "orioles": "BAL", "toronto": "TOR", "blue jays": "TOR",
    "tampa bay": "TB", "rays": "TB", "cleveland": "CLE", "guardians": "CLE",
    "detroit": "DET", "tigers": "DET", "minnesota": "MIN", "twins": "MIN",
    "chicago sox": "CWS", "white sox": "CWS", "kansas city": "KC", "royals": "KC",
    "houston": "HOU", "astros": "HOU", "seattle": "SEA", "mariners": "SEA",
    "texas": "TEX", "rangers": "TEX", "oakland": "OAK", "athletics": "OAK",
    "la angels": "LAA", "angels": "LAA", "ny mets": "NYM", "mets": "NYM",
    "atlanta": "ATL", "braves": "ATL", "philadelphia": "PHI", "phillies": "PHI",
    "miami": "MIA", "marlins": "MIA", "washington": "WSH", "nationals": "WSH",
    "chicago cubs": "CHC", "cubs": "CHC", "cincinnati": "CIN", "reds": "CIN",
    "milwaukee": "MIL", "brewers": "MIL", "pittsburgh": "PIT", "pirates": "PIT",
    "st. louis": "STL", "cardinals": "STL", "la dodgers": "LAD", "dodgers": "LAD",
    "arizona": "ARI", "diamondbacks": "ARI", "san francisco": "SF", "giants": "SF",
    "san diego": "SD", "padres": "SD", "colorado": "COL", "rockies": "COL"
}

# ==========================================
# 🧠 CEREBRO 1: LIGA MX (GOD MODE v6)
# ==========================================

def get_mx_data():
    try:
        df = pd.read_csv(URL_LIGAMX, on_bad_lines='skip')
        df['Date'] = pd.to_datetime(df['Date'], dayfirst=True)
        return df.sort_values('Date', ascending=True)
    except: return None

def clean_mx_name(raw, targets):
    clean = str(raw).lower().replace("fc", "").strip()
    for k, v in EQUIPOS_MX.items():
        if k in clean:
            matches = get_close_matches(v, targets, n=1, cutoff=0.6)
            if matches: return matches[0]
    m = get_close_matches(clean, targets, n=1, cutoff=0.4)
    return m[0] if m else None

def monte_carlo_mx(xg_l, xg_v, sims=5000):
    l_sim = np.random.poisson(xg_l, sims)
    v_sim = np.random.poisson(xg_v, sims)
    return {
        "local": np.sum(l_sim > v_sim)/sims*100,
        "empate": np.sum(l_sim == v_sim)/sims*100,
        "visita": np.sum(l_sim < v_sim)/sims*100,
        "over": np.sum((l_sim+v_sim) > 2.5)/sims*100
    }

def analyze_mx(local_raw, visita_raw, df):
    equipos = pd.concat([df['Home'], df['Away']]).unique()
    local = clean_mx_name(local_raw, equipos)
    visita = clean_mx_name(visita_raw, equipos)
    if not local or not visita: return None

    # Cálculo Pitagórico (Suerte)
    def pyth(t):
        p = df[(df['Home']==t)|(df['Away']==t)].tail(10)
        gf = p[p['Home']==t]['HG'].sum() + p[p['Away']==t]['AG'].sum()
        gc = p[p['Home']==t]['AG'].sum() + p[p['Away']==t]['HG'].sum()
        return (gf**2)/(gf**2 + gc**2) if (gf+gc)>0 else 0.5

    # xG Simplificado para Monte Carlo
    def get_xg(t, is_h):
        p = df[df['Home' if is_h else 'Away']==t].tail(6)
        if len(p)==0: return 1.2
        return p['HG' if is_h else 'AG'].mean()

    xg_l = get_xg(local, True) * 1.15 # Factor Localía
    xg_v = get_xg(visita, False)
    
    mc = monte_carlo_mx(xg_l, xg_v)
    
    return {
        "sport": "soccer", "local": local, "visita": visita,
        "probs": mc, "pyth_l": pyth(local), "pyth_v": pyth(visita)
    }

# ==========================================
# 🧠 CEREBRO 2: MLB (BÉISBOL PRO)
# ==========================================

def get_mlb_stats():
    # Descarga stats del año actual (o 2024/2025 si no ha empezado)
    try:
        # Intentamos año actual, si falla, año anterior
        y = datetime.now().year
        bat = team_batting(y)
        pit = team_pitching(y)
        if bat.empty or pit.empty:
            bat = team_batting(y-1)
            pit = team_pitching(y-1)
        return bat, pit
    except: return None, None

def clean_mlb_name(raw):
    # Convierte "New York Yankees" a "NYY"
    clean = str(raw).lower()
    for k, v in EQUIPOS_MLB.items():
        if k in clean: return v
    return None

def analyze_mlb(local_raw, visita_raw, bat_df, pit_df):
    l_code = clean_mlb_name(local_raw)
    v_code = clean_mlb_name(visita_raw)
    
    if not l_code or not v_code: return None
    
    # Obtener stats
    try:
        # Bateo (OPS es lo más importante)
        bat_l = bat_df[bat_df['Team'] == l_code]['OPS'].values[0]
        bat_v = bat_df[bat_df['Team'] == v_code]['OPS'].values[0]
        
        # Pitcheo (WHIP y ERA es clave)
        pit_l = pit_df[pit_df['Team'] == l_code]['WHIP'].values[0] # Pitcheo del Local
        pit_v = pit_df[pit_df['Team'] == v_code]['WHIP'].values[0] # Pitcheo del Visita
        
        # Lógica de Poder: Bateo Fuerte vs Pitcheo Débil
        # Score = Bateo Propio - Pitcheo Rival
        # WHIP promedio es 1.30. Menos es mejor.
        
        score_l = (bat_l * 1000) - (pit_v * 200) # Ajuste ponderado
        score_v = (bat_v * 1000) - (pit_l * 200)
        
        total_score = score_l + score_v
        prob_l = (score_l / total_score) * 100
        prob_v = (score_v / total_score) * 100
        
        # Lógica de Carreras (Over/Under)
        # Si ambos pitchers tienen WHIP alto (>1.35) -> Over
        # Si ambos tienen WHIP bajo (<1.15) -> NRFI (No Run First Inning) o Under
        total_whip = pit_l + pit_v
        trend = "Neutro"
        if total_whip > 2.8: trend = "🔥 Alta Probable (Pitcheo Débil)"
        if total_whip < 2.3: trend = "💎 Duelo de Pitcheo (Bajas/NRFI)"
        
        return {
            "sport": "baseball", "local": l_code, "visita": v_code,
            "prob_l": prob_l, "prob_v": prob_v,
            "bat_l": bat_l, "bat_v": bat_v,
            "pit_l": pit_l, "pit_v": pit_v,
            "trend": trend
        }
    except: return None

# ==========================================
# 🕵️ SCRAPER UNIFICADO (FILTRO DE FECHA)
# ==========================================

def buscar_partidos(url, deporte):
    print(f"🔍 Buscando {deporte}...")
    try:
        dfs = pd.read_html(url)
        partidos = []
        
        zona_mx = pytz.timezone('America/Mexico_City')
        hoy = datetime.now(zona_mx)
        # Diccionarios de fecha
        meses = {1:"enero", 2:"febrero", 3:"marzo", 4:"abril", 5:"mayo", 6:"junio",
                 7:"julio", 8:"agosto", 9:"septiembre", 10:"octubre", 11:"noviembre", 12:"diciembre"}
        
        # Texto a buscar: "18 de enero" o "hoy"
        dia_txt = f"{hoy.day} de {meses[hoy.month]}"
        print(f"📅 Filtro: {dia_txt}")

        for df in dfs:
            txt = df.to_string().lower()
            if dia_txt in txt or "hoy" in txt:
                if len(df.columns) >= 2:
                    for _, row in df.iterrows():
                        try:
                            e1 = str(row[0])
                            e2 = str(row[1])
                            if len(e1)>3 and len(e2)>3:
                                if "enero" not in e1.lower(): # Evitar leer fechas como equipos
                                    partidos.append((e1, e2))
                        except: continue
        return list(set(partidos)) # Eliminar duplicados
    except: return []

# ==========================================
# 🚀 EJECUCIÓN MAESTRA
# ==========================================

def tarea_maestra():
    print("⚡ INICIANDO ANÁLISIS DEPORTIVO MUNDIAL...")
    reporte = "🌍 **REPORTE DIARIO DE SEÑALES** 🌍\n"
    
    # 1. ANALISIS LIGA MX
    juegos_mx = buscar_partidos(URL_CALENDARIO_LIGAMX, "Liga MX")
    if juegos_mx:
        df_mx = get_mx_data()
        if df_mx is not None:
            reporte += "\n⚽ **FÚTBOL (LIGA MX)**\n"
            for p in juegos_mx:
                data = analyze_mx(p[0], p[1], df_mx)
                if data:
                    probs = data['probs']
                    pick = "Cerrado 😐"
                    if probs['local'] > 55 and data['pyth_l'] > 0.45: pick = f"Gana {data['local']} 🏠"
                    elif probs['visita'] > 50 and data['pyth_v'] > 0.45: pick = f"Gana {data['visita']} ✈️"
                    elif probs['over'] > 60: pick = "Alta Goles (+2.5) ⚽🔥"
                    
                    reporte += (
                        f"🔹 {data['local']} vs {data['visita']}\n"
                        f"🎲 MC: {probs['local']:.0f}% - {probs['visita']:.0f}%\n"
                        f"🎯 PICK: {pick}\n\n"
                    )

    # 2. ANALISIS MLB
    juegos_mlb = buscar_partidos(URL_CALENDARIO_MLB, "MLB")
    if juegos_mlb:
        # Descargamos stats de pybaseball una sola vez
        bat_df, pit_df = get_mlb_stats()
        if bat_df is not None:
            reporte += "\n⚾ **BÉISBOL (MLB PRO)**\n"
            for p in juegos_mlb:
                data = analyze_mlb(p[0], p[1], bat_df, pit_df)
                if data:
                    pick_mlb = "Cerrado"
                    if data['prob_l'] > 58: pick_mlb = f"Gana {data['local']} 🏠"
                    elif data['prob_v'] > 58: pick_mlb = f"Gana {data['visita']} ✈️"
                    
                    reporte += (
                        f"🔹 {data['local']} vs {data['visita']}\n"
                        f"📊 Poder: {data['prob_l']:.0f}% vs {data['prob_v']:.0f}%\n"
                        f"🧤 WHIP: {data['pit_l']:.2f} vs {data['pit_v']:.2f}\n"
                        f"💡 Tendencia: {data['trend']}\n"
                        f"🎯 SEÑAL: {pick_mlb}\n\n"
                    )

    if "🔹" in reporte and CHAT_ID:
        try:
            bot.send_message(CHAT_ID, reporte, parse_mode="Markdown")
            print("✅ Reporte enviado.")
        except Exception as e: print(e)
    else:
        print("No hay partidos hoy o no se encontraron datos.")

# --- ARRANQUE ---
keep_alive()
schedule.every().day.at("16:00").do(tarea_maestra) # 10:00 AM México

# Descomenta para probar YA
# tarea_maestra()

print("🤖 Super-Bot Mundial Iniciado (Soccer + Baseball).")
while True:
    schedule.run_pending()
    time.sleep(60)
