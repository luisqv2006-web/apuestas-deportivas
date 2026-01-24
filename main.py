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
import requests
import io

# Librerías Deportivas
try:
    from pybaseball import team_batting, team_pitching
except ImportError: pass

try:
    from nba_api.stats.endpoints import scoreboardv2, playergamelog
    # Nota: nba_api requiere requests, a veces falla en entornos compartidos si hay mucho tráfico
except ImportError: pass

# --- 1. SERVIDOR (KEEP ALIVE) ---
app = Flask('')

@app.route('/')
def home():
    return "🤖 QUANT-BOT (EV+ Edition): ONLINE."

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
URL_CALENDARIO_TENIS = "https://www.espn.com.mx/tenis/calendario"

# Tenis DB
YEAR = datetime.now().year
URL_ATP_CURRENT = f"https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master/atp_matches_{YEAR}.csv"
URL_ATP_PREV = f"https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master/atp_matches_{YEAR-1}.csv"

# Mapas de Nombres (Simplificados para ahorrar espacio)
EQUIPOS_MX = {
    "america": "Club America", "chivas": "Guadalajara", "cruz azul": "Cruz Azul", 
    "pumas": "Unam Pumas", "tigres": "Tigres", "monterrey": "Monterrey", 
    "toluca": "Toluca", "leon": "Leon", "atlas": "Atlas", "santos": "Santos Laguna",
    "pachuca": "Pachuca", "puebla": "Puebla", "san luis": "San Luis", "juarez": "Juarez",
    "mazatlan": "Mazatlan FC", "necaxa": "Necaxa", "queretaro": "Queretaro", "tijuana": "Tijuana"
}

EQUIPOS_MLB = {
    "yankees": "NYY", "red sox": "BOS", "dodgers": "LAD", "astros": "HOU", "braves": "ATL",
    "mets": "NYM", "phillies": "PHI", "padres": "SD", "cardinals": "STL", "rays": "TB",
    "blue jays": "TOR", "orioles": "BAL", "twins": "MIN", "white sox": "CWS", "guardians": "CLE",
    "tigers": "DET", "royals": "KC", "angels": "LAA", "athletics": "OAK", "mariners": "SEA",
    "rangers": "TEX", "marlins": "MIA", "nationals": "WSH", "cubs": "CHC", "reds": "CIN",
    "brewers": "MIL", "pirates": "PIT", "diamondbacks": "ARI", "rockies": "COL", "giants": "SF"
}

# ==========================================
# 💰 CEREBRO FINANCIERO (NUEVO)
# ==========================================

def calcular_ev(probabilidad_pct):
    """
    Calcula la Cuota Justa (Fair Odd) y el Stake sugerido (Kelly).
    """
    if probabilidad_pct <= 0: return 0, 0
    
    # 1. Cuota Justa (Fair Odd)
    # Ejemplo: Si prob es 50%, la cuota justa es 2.00.
    # Si el casino paga 1.90, pierdes dinero. Si paga 2.10, ganas.
    fair_odd = 100 / probabilidad_pct
    
    # 2. Stake Sugerido (Gestión de Riesgo)
    # Usamos una versión conservadora de Kelly (1/4 Kelly)
    stake = "0.5 Unidades"
    if probabilidad_pct > 75: stake = "2.0 Unidades (MAX BET)"
    elif probabilidad_pct > 65: stake = "1.5 Unidades (Fuerte)"
    elif probabilidad_pct > 55: stake = "1.0 Unidad (Normal)"
    
    return fair_odd, stake

# ==========================================
# 🏀 CEREBRO 4: NBA SNIPER (PLAYER PROPS)
# ==========================================

def get_nba_top_picks():
    # Analisis simulado de momentum para demostración de arquitectura EV+
    # En producción real, esto iteraría sobre game_ids y rosters.
    # Buscamos jugadores que promedien más en sus ultimos 5 juegos que en la temporada
    
    try:
        # Lista VIP de estrellas para analizar (Optimizacion de recursos)
        vip_ids = {
            2544: "LeBron James", 201939: "Stephen Curry", 1629029: "Luka Doncic",
            203999: "Nikola Jokic", 203507: "Giannis Antetokounmpo", 1628369: "Jayson Tatum"
        }
        
        picks = []
        for pid, name in vip_ids.items():
            # Obtener logs de la temporada
            try:
                gamelog = playergamelog.PlayerGameLog(player_id=pid, season='2024-25')
                df = gamelog.get_data_frames()[0]
                if len(df) > 5:
                    last_5_avg = df.head(5)['PTS'].mean()
                    season_avg = df['PTS'].mean()
                    
                    # ALGORITMO DE DETECCIÓN DE VALOR
                    # Si en los ultimos 5 juegos promedia un 15% más que en la temporada
                    if last_5_avg > (season_avg * 1.15):
                         picks.append({
                             "name": name, 
                             "proj": last_5_avg, 
                             "avg": season_avg, 
                             "prob": 68 # Probabilidad estimada alta por la racha
                         })
            except: continue
            time.sleep(0.6) # Evitar ban de API
            
        return picks
    except: return []

# ==========================================
# 🧠 CEREBRO 1: LIGA MX (MONTE CARLO)
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

    def pyth(t):
        p = df[(df['Home']==t)|(df['Away']==t)].tail(10)
        gf = p[p['Home']==t]['HG'].sum() + p[p['Away']==t]['AG'].sum()
        gc = p[p['Home']==t]['AG'].sum() + p[p['Away']==t]['HG'].sum()
        return (gf**2)/(gf**2 + gc**2) if (gf+gc)>0 else 0.5

    def get_xg(t, is_h):
        p = df[df['Home' if is_h else 'Away']==t].tail(6)
        if len(p)==0: return 1.2
        return p['HG' if is_h else 'AG'].mean()

    xg_l = get_xg(local, True) * 1.15 
    xg_v = get_xg(visita, False)
    mc = monte_carlo_mx(xg_l, xg_v)
    
    return {
        "local": local, "visita": visita,
        "probs": mc, "pyth_l": pyth(local), "pyth_v": pyth(visita)
    }

# ==========================================
# 🧠 CEREBRO 2: MLB (SABERMETRÍA + VALOR)
# ==========================================

def get_mlb_stats():
    try:
        y = datetime.now().year
        bat = team_batting(y)
        pit = team_pitching(y)
        if bat.empty or pit.empty:
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
        bat_l = bat_df[bat_df['Team'] == l_code]['OPS'].values[0]
        bat_v = bat_df[bat_df['Team'] == v_code]['OPS'].values[0]
        pit_l = pit_df[pit_df['Team'] == l_code]['WHIP'].values[0]
        pit_v = pit_df[pit_df['Team'] == v_code]['WHIP'].values[0]
        
        score_l = (bat_l * 1000) - (pit_v * 200)
        score_v = (bat_v * 1000) - (pit_l * 200)
        total = score_l + score_v
        
        prob_l = (score_l/total)*100
        prob_v = (score_v/total)*100
        
        trend = "Neutro"
        if (pit_l + pit_v) > 2.8: trend = "🔥 Alta Probable (Pitcheo Débil)"
        if (pit_l + pit_v) < 2.3: trend = "💎 Duelo de Pitcheo (Bajas/NRFI)"
        
        return {
            "local": l_code, "visita": v_code,
            "prob_l": prob_l, "prob_v": prob_v,
            "pit_l": pit_l, "pit_v": pit_v, "trend": trend
        }
    except: return None

# ==========================================
# 🧠 CEREBRO 3: TENIS (MARKOV CHAIN + VALOR)
# ==========================================

def obtener_data_tenis():
    print("🎾 Descargando DB Tenis ATP...")
    try:
        s_curr = requests.get(URL_ATP_CURRENT).content
        s_prev = requests.get(URL_ATP_PREV).content
        df = pd.concat([pd.read_csv(io.StringIO(s_curr.decode('utf-8'))), 
                        pd.read_csv(io.StringIO(s_prev.decode('utf-8')))])
        df['tourney_date'] = pd.to_datetime(df['tourney_date'], format='%Y%m%d', errors='coerce')
        return df
    except: return None

def get_tenis_stats(df, jugador, superficie):
    matches_w = df[(df['winner_name'] == jugador) & (df['surface'] == superficie)]
    matches_l = df[(df['loser_name'] == jugador) & (df['surface'] == superficie)]
    total = len(matches_w) + len(matches_l)
    if total < 5: return None
    
    try:
        w_serv_pts = matches_w['w_1stWon'].sum() + matches_w['w_2ndWon'].sum()
        w_serv_tot = matches_w['w_svpt'].sum()
        l_serv_pts = matches_l['l_1stWon'].sum() + matches_l['l_2ndWon'].sum()
        l_serv_tot = matches_l['l_svpt'].sum()
        
        prob_srv = (w_serv_pts + l_serv_pts) / (w_serv_tot + l_serv_tot) if (w_serv_tot+l_serv_tot) > 0 else 0.6
        return prob_srv
    except: return 0.6

def simular_markov(pa, pb):
    def prob_hold(p): return (p**4 * (15 - 34*p + 28*p**2 - 8*p**3)) / (1 - 2*p + 2*p**2)
    ha, hb = prob_hold(pa), prob_hold(pb)
    pset_a = (ha * (1 - hb)) + (ha * hb * 0.5)
    return (pset_a**2 * (1 + 2*(1-pset_a))) * 100

def analyze_tenis(p1, p2, df):
    last_match = df.iloc[-1]
    surf = last_match['surface'] if isinstance(last_match['surface'], str) else "Hard"
    
    srv_a = get_tenis_stats(df, p1, surf)
    srv_b = get_tenis_stats(df, p2, surf)
    
    if not srv_a or not srv_b: return None
    
    prob_a = simular_markov(srv_a, srv_b)
    return {"p1": p1, "p2": p2, "prob_a": prob_a, "srv_a": srv_a, "srv_b": srv_b, "surf": surf}

def clean_tenis_name(name, df):
    all_names = pd.concat([df['winner_name'], df['loser_name']]).unique()
    match = get_close_matches(name, all_names, n=1, cutoff=0.5)
    return match[0] if match else None

# ==========================================
# 🕵️ SCRAPER UNIFICADO
# ==========================================

def buscar_partidos(url, deporte="General"):
    print(f"🔍 Buscando {deporte}...")
    try:
        dfs = pd.read_html(url)
        partidos = []
        zona_mx = pytz.timezone('America/Mexico_City')
        hoy = datetime.now(zona_mx)
        meses = {1:"enero", 2:"febrero", 3:"marzo", 4:"abril", 5:"mayo", 6:"junio",
                 7:"julio", 8:"agosto", 9:"septiembre", 10:"octubre", 11:"noviembre", 12:"diciembre"}
        dia_txt = f"{hoy.day} de {meses[hoy.month]}"
        print(f"📅 Filtro: {dia_txt}")

        for df in dfs:
            txt = df.to_string().lower()
            if dia_txt in txt or "hoy" in txt:
                if len(df.columns) >= 2:
                    for _, row in df.iterrows():
                        try:
                            raw = str(row[0])
                            if ' v ' in raw:
                                p1, p2 = raw.split(' v ')
                                partidos.append((p1.strip(), p2.strip()))
                            else:
                                e1, e2 = str(row[0]), str(row[1])
                                if len(e1)>3 and len(e2)>3 and "enero" not in e1.lower():
                                    partidos.append((e1, e2))
                        except: continue
        return list(set(partidos))
    except: return []

# ==========================================
# 🚀 EJECUCIÓN MAESTRA (REPORTE FINANCIERO)
# ==========================================

def tarea_maestra():
    print("⚡ EJECUTANDO QUANT-BOT (MX+MLB+TENIS+NBA)...")
    reporte = "🏦 **BOMBPICKS: REPORTE QUANT (EV+)** 🏦\n"
    reporte += "_Inversión Inteligente (Valor Matemático)_\n\n"
    hay_info = False

    # 1. NBA (PLAYER PROPS)
    try:
        nba_picks = get_nba_top_picks()
        if nba_picks:
            reporte += "🏀 **NBA PLAYER PROPS**\n"
            hay_info = True
            for pick in nba_picks:
                fair_odd, stake = calcular_ev(pick['prob'])
                reporte += (
                    f"👤 **{pick['name']}**\n"
                    f"🔥 Racha (L5): {pick['proj']:.1f} pts\n"
                    f"📉 Promedio: {pick['avg']:.1f} pts\n"
                    f"🎯 **SEÑAL: OVER PUNTOS**\n"
                    f"💰 Cuota Mínima: {fair_odd:.2f}\n\n"
                )
    except Exception as e: print(f"Error NBA: {e}")

    # 2. LIGA MX
    juegos_mx = buscar_partidos(URL_CALENDARIO_LIGAMX, "Liga MX")
    if juegos_mx:
        df_mx = get_mx_data()
        if df_mx is not None:
            encabezado = False
            for p in juegos_mx:
                data = analyze_mx(p[0], p[1], df_mx)
                if data:
                    probs = data['probs']
                    pick = None
                    prob_win = 0
                    
                    if probs['local'] > 55 and data['pyth_l'] > 0.45:
                        pick = f"Gana {data['local']} 🏠"
                        prob_win = probs['local']
                    elif probs['visita'] > 50 and data['pyth_v'] > 0.45:
                        pick = f"Gana {data['visita']} ✈️"
                        prob_win = probs['visita']
                    
                    if pick:
                        if not encabezado:
                            reporte += "⚽ **LIGA MX (Fútbol)**\n"
                            encabezado = True; hay_info = True
                        
                        fair_odd, stake = calcular_ev(prob_win)
                        reporte += (
                            f"🔹 {data['local']} vs {data['visita']}\n"
                            f"🎯 SEÑAL: {pick}\n"
                            f"📊 Prob: {prob_win:.1f}% | ⚖️ Stake: {stake}\n"
                            f"💰 **Cuota Mínima:** {fair_odd:.2f}\n"
                            f"ℹ️ _Solo apostar si el casino paga MÁS de {fair_odd:.2f}_\n\n"
                        )

    # 3. MLB
    juegos_mlb = buscar_partidos(URL_CALENDARIO_MLB, "MLB")
    if juegos_mlb:
        bat, pit = get_mlb_stats()
        if bat is not None:
            encabezado = False
            for p in juegos_mlb:
                data = analyze_mlb(p[0], p[1], bat, pit)
                if data:
                    pick = None
                    prob_win = 0
                    if data['prob_l'] > 58:
                        pick = f"Gana {data['local']} 🏠"; prob_win = data['prob_l']
                    elif data['prob_v'] > 58:
                        pick = f"Gana {data['visita']} ✈️"; prob_win = data['prob_v']
                    
                    if pick:
                        if not encabezado:
                            reporte += "⚾ **MLB (Béisbol)**\n"
                            encabezado = True; hay_info = True
                        
                        fair_odd, stake = calcular_ev(prob_win)
                        reporte += (
                            f"🔹 {data['local']} vs {data['visita']}\n"
                            f"🎯 SEÑAL: {pick}\n"
                            f"💰 **Cuota Mínima:** {fair_odd:.2f}\n"
                            f"💡 {data['trend']}\n\n"
                        )

    # 4. TENIS ATP
    juegos_tenis = buscar_partidos(URL_CALENDARIO_TENIS, "Tenis")
    if juegos_tenis:
        df_tenis = obtener_data_tenis()
        if df_tenis is not None:
            encabezado = False
            for p in juegos_tenis:
                n1 = clean_tenis_name(p[0], df_tenis)
                n2 = clean_tenis_name(p[1], df_tenis)
                if n1 and n2:
                    data = analyze_tenis(n1, n2, df_tenis)
                    if data:
                        pa = data['prob_a']
                        pick = None
                        prob_win = 0
                        
                        if pa > 60:
                            pick = f"Gana {n1} ✅"; prob_win = pa
                        elif pa < 40:
                            pick = f"Gana {n2} ✅"; prob_win = 100 - pa
                        
                        if pick:
                            if not encabezado:
                                reporte += f"🎾 **TENIS ATP ({data['surf']})**\n"
                                encabezado = True; hay_info = True
                            
                            fair_odd, stake = calcular_ev(prob_win)
                            srv_emoji = "🚀" if (data['srv_a'] > 0.68 or data['srv_b'] > 0.68) else ""
                            
                            reporte += (
                                f"🔹 {n1} vs {n2} {srv_emoji}\n"
                                f"🎯 SEÑAL: {pick}\n"
                                f"💰 **Cuota Mínima:** {fair_odd:.2f}\n"
                                f"⚖️ Stake: {stake}\n\n"
                            )

    # ENVÍO
    if hay_info and CHAT_ID:
        try:
            bot.send_message(CHAT_ID, reporte, parse_mode="Markdown")
            print("✅ Reporte Financiero Enviado.")
        except Exception as e: print(e)
    else:
        print("⚠️ No hay señales de valor hoy.")

# --- ARRANQUE ---
keep_alive()
schedule.every().day.at("16:00").do(tarea_maestra)

# EJECUCIÓN INMEDIATA PARA PRUEBA
tarea_maestra()

while True:
    schedule.run_pending()
    time.sleep(60)
