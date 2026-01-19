import os
import telebot
import pandas as pd
import numpy as np
import schedule
import time
from datetime import datetime
import pytz
from flask import Flask
from threading import Thread
from difflib import get_close_matches

# Librerías de MLB
try:
    from pybaseball import team_batting, team_pitching
except ImportError:
    print("⚠️ Advertencia: pybaseball no instalado o falló.")

# --- 1. SERVIDOR FALSO (KEEP ALIVE PARA RENDER) ---
app = Flask('')

@app.route('/')
def home():
    return "🤖 SUPER-BOT (Liga MX + MLB) ESTÁ VIVO."

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

# URLs
URL_LIGAMX = "https://www.football-data.co.uk/new/MEX.csv"
URL_CALENDARIO_LIGAMX = "https://www.espn.com.mx/futbol/calendario/_/liga/mex.1"
URL_CALENDARIO_MLB = "https://www.espn.com.mx/beisbol/mlb/calendario"

# Mapas de Nombres
EQUIPOS_MX = {
    "america": "Club America", "guadalajara": "Guadalajara", "chivas": "Guadalajara",
    "cruz azul": "Cruz Azul", "pumas": "Unam Pumas", "unam": "Unam Pumas", "tigres": "Tigres",
    "monterrey": "Monterrey", "toluca": "Toluca", "pachuca": "Pachuca", "leon": "Leon",
    "santos": "Santos Laguna", "atlas": "Atlas", "puebla": "Puebla", "san luis": "San Luis",
    "juarez": "Juarez", "mazatlan": "Mazatlan FC", "necaxa": "Necaxa", "queretaro": "Queretaro",
    "tijuana": "Tijuana", "xolos": "Tijuana"
}

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
# 🧠 CEREBRO 1: LIGA MX (GOD MODE)
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

    # Pitágoras (Detector de Suerte)
    def pyth(t):
        p = df[(df['Home']==t)|(df['Away']==t)].tail(10)
        gf = p[p['Home']==t]['HG'].sum() + p[p['Away']==t]['AG'].sum()
        gc = p[p['Home']==t]['AG'].sum() + p[p['Away']==t]['HG'].sum()
        return (gf**2)/(gf**2 + gc**2) if (gf+gc)>0 else 0.5

    # xG para Monte Carlo
    def get_xg(t, is_h):
        p = df[df['Home' if is_h else 'Away']==t].tail(6)
        if len(p)==0: return 1.2
        return p['HG' if is_h else 'AG'].mean()

    xg_l = get_xg(local, True) * 1.15 # Factor Localía
    xg_v = get_xg(visita, False)
    
    mc = monte_carlo_mx(xg_l, xg_v)
    
    return {
        "local": local, "visita": visita,
        "probs": mc, "pyth_l": pyth(local), "pyth_v": pyth(visita)
    }

# ==========================================
# 🧠 CEREBRO 2: MLB (PYBASEBALL)
# ==========================================

def get_mlb_stats():
    try:
        y = datetime.now().year
        bat = team_batting(y)
        pit = team_pitching(y)
        if bat.empty or pit.empty: # Si es pretemporada, usar año anterior
            bat = team_batting(y-1)
            pit = team_pitching(y-1)
        return bat, pit
    except: return None, None

def clean_mlb_name(raw):
    clean = str(raw).lower()
    for k, v in EQUIPOS_MLB.items():
        if k in clean: return v
    return None

def analyze_mlb(local_raw, visita_raw, bat_df, pit_df):
    l_code = clean_mlb_name(local_raw)
    v_code = clean_mlb_name(visita_raw)
    if not l_code or not v_code: return None
    
    try:
        # Bateo (OPS)
        bat_l = bat_df[bat_df['Team'] == l_code]['OPS'].values[0]
        bat_v = bat_df[bat_df['Team'] == v_code]['OPS'].values[0]
        # Pitcheo (WHIP)
        pit_l = pit_df[pit_df['Team'] == l_code]['WHIP'].values[0]
        pit_v = pit_df[pit_df['Team'] == v_code]['WHIP'].values[0]
        
        # Algoritmo de Poder
        score_l = (bat_l * 1000) - (pit_v * 200)
        score_v = (bat_v * 1000) - (pit_l * 200)
        total = score_l + score_v
        
        # Tendencias
        trend = "Neutro"
        if (pit_l + pit_v) > 2.8: trend = "🔥 Alta Probable (Pitcheo Débil)"
        if (pit_l + pit_v) < 2.3: trend = "💎 Duelo de Pitcheo (Bajas/NRFI)"
        
        return {
            "local": l_code, "visita": v_code,
            "prob_l": (score_l/total)*100, "prob_v": (score_v/total)*100,
            "pit_l": pit_l, "pit_v": pit_v, "trend": trend
        }
    except: return None

# ==========================================
# 🕵️ SCRAPER CON FECHA EXACTA
# ==========================================

def buscar_partidos(url):
    print(f"🔍 Buscando partidos en {url}...")
    try:
        dfs = pd.read_html(url)
        partidos = []
        
        # Obtener fecha de HOY en México
        zona_mx = pytz.timezone('America/Mexico_City')
        hoy = datetime.now(zona_mx)
        
        meses = {1:"enero", 2:"febrero", 3:"marzo", 4:"abril", 5:"mayo", 6:"junio",
                 7:"julio", 8:"agosto", 9:"septiembre", 10:"octubre", 11:"noviembre", 12:"diciembre"}
        
        # Texto a buscar: Ejemplo "18 de enero"
        dia_txt = f"{hoy.day} de {meses[hoy.month]}"
        print(f"📅 Filtro de Fecha: {dia_txt}")

        for df in dfs:
            txt = df.to_string().lower()
            # Solo procesar tablas que contengan la fecha de HOY
            if dia_txt in txt or "hoy" in txt:
                if len(df.columns) >= 2:
                    for _, row in df.iterrows():
                        try:
                            e1 = str(row[0])
                            e2 = str(row[1])
                            # Filtro básico de texto
                            if len(e1) > 3 and len(e2) > 3:
                                # Evitar que la fecha sea leída como equipo
                                if "enero" not in e1.lower() and "febrero" not in e1.lower():
                                    partidos.append((e1, e2))
                        except: continue
        
        # Eliminar duplicados
        return list(set(partidos))
    except Exception as e:
        print(f"❌ Error scraping: {e}")
        return []

# ==========================================
# 🚀 TAREA MAESTRA (EJECUCIÓN)
# ==========================================

def tarea_maestra():
    print("⚡ INICIANDO ANÁLISIS DEPORTIVO...")
    reporte = "🌍 **REPORTE DIARIO: BOMBPICKS PREMIUM** 🌍\n"
    hay_info = False
    
    # 1. LIGA MX
    juegos_mx = buscar_partidos(URL_CALENDARIO_LIGAMX)
    if juegos_mx:
        df_mx = get_mx_data()
        if df_mx is not None:
            encabezado_mx = False
            for p in juegos_mx:
                data = analyze_mx(p[0], p[1], df_mx)
                if data:
                    if not encabezado_mx:
                        reporte += "\n⚽ **FÚTBOL (LIGA MX)**\n"
                        encabezado_mx = True
                        hay_info = True
                    
                    probs = data['probs']
                    pick = "Cerrado 😐"
                    
                    # Lógica de Picks
                    if probs['local'] > 55 and data['pyth_l'] > 0.45:
                        pick = f"Gana {data['local']} 🏠"
                    elif probs['visita'] > 50 and data['pyth_v'] > 0.45:
                        pick = f"Gana {data['visita']} ✈️"
                    elif probs['over'] > 60:
                        pick = "Alta Goles (+2.5) ⚽🔥"
                        
                    reporte += (
                        f"🔹 {data['local']} vs {data['visita']}\n"
                        f"🎲 MC: {probs['local']:.1f}% - {probs['visita']:.1f}%\n"
                        f"📉 Pyth: {data['pyth_l']:.2f} vs {data['pyth_v']:.2f}\n"
                        f"🎯 PICK: {pick}\n\n"
                    )

    # 2. MLB
    juegos_mlb = buscar_partidos(URL_CALENDARIO_MLB)
    if juegos_mlb:
        bat, pit = get_mlb_stats()
        if bat is not None:
            encabezado_mlb = False
            for p in juegos_mlb:
                data = analyze_mlb(p[0], p[1], bat, pit)
                if data:
                    if not encabezado_mlb:
                        reporte += "\n⚾ **BÉISBOL (MLB PRO)**\n"
                        encabezado_mlb = True
                        hay_info = True
                        
                    pick_mlb = "Cerrado"
                    if data['prob_l'] > 58: pick_mlb = f"Gana {data['local']} 🏠"
                    elif data['prob_v'] > 58: pick_mlb = f"Gana {data['visita']} ✈️"
                    
                    reporte += (
                        f"🔹 {data['local']} vs {data['visita']}\n"
                        f"📊 Poder: {data['prob_l']:.0f}% vs {data['prob_v']:.0f}%\n"
                        f"💡 Tendencia: {data['trend']}\n"
                        f"🎯 SEÑAL: {pick_mlb}\n\n"
                    )

    # ENVÍO
    if hay_info and CHAT_ID:
        try:
            bot.send_message(CHAT_ID, reporte, parse_mode="Markdown")
            print("✅ Reporte enviado al Canal.")
        except Exception as e:
            print(f"❌ Error enviando a Telegram: {e}")
    else:
        print("⚠️ No hay partidos HOY o no encontré datos.")

# --- ARRANQUE ---

# 1. Iniciar Web Server (Para que Render no se duerma)
keep_alive()

# 2. Programar horario (10:00 AM México = 16:00 UTC)
schedule.every().day.at("16:00").do(tarea_maestra)

print("🤖 BOT INICIADO.")

# 🔥 EJECUCIÓN INMEDIATA (PARA PROBAR YA)
# Esta línea obliga al bot a analizar apenas arranque, sin esperar la hora.
tarea_maestra()

# 3. Bucle eterno
while True:
    schedule.run_pending()
    time.sleep(60)
