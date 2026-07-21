import streamlit as st
import folium
from streamlit_folium import st_folium
import os
import paho.mqtt.client as mqtt
from streamlit_autorefresh import st_autorefresh
from datetime import datetime
import threading
from streamlit.runtime.scriptrunner import add_script_run_ctx

st.set_page_config(page_title="Rastreador Satelital QSO LINK", layout="wide")

st.markdown("""
    <style>
        .block-container { padding-top: 1rem !important; padding-bottom: 0rem !important; padding-left: 2rem !important; padding-right: 2rem !important; }
    </style>
""", unsafe_allow_html=True)

# 🛠️ CORRECCIÓN PARA INTERNET: Guardamos los datos en la carpeta temporal del servidor web
GPS_FILE = "/tmp/gps_trayecto.txt" if os.name != "nt" else os.path.join(os.path.expanduser("~"), "Desktop", "gps_trayecto.txt")
CHAT_FILE = "/tmp/gps_mensajes.txt" if os.name != "nt" else os.path.join(os.path.expanduser("~"), "Desktop", "gps_mensajes.txt")

lat_casa, lon_casa = -37.7843311149627, -58.848557034507394

if "lat" not in st.session_state: st.session_state.lat = lat_casa
if "lon" not in st.session_state: st.session_state.lon = lon_casa
if "ultimo_msg" not in st.session_state: st.session_state.ultimo_msg = "Iniciando sistema..."
if "canal" not in st.session_state: st.session_state.canal = "Red 4G Móvil"
if "satelites" not in st.session_state: st.session_state.satelites = "0"
if "velocidad" not in st.session_state: st.session_state.velocidad = "0.0 km/h"
if "altitud" not in st.session_state: st.session_state.altitud = "0 m"
if "hora_sat" not in st.session_state: st.session_state.hora_sat = "--:--:--"
if "ultimo_crudo" not in st.session_state: st.session_state.ultimo_crudo = ""

def procesar_cadena_entrante(payload, topico_origen):
    if "ACK" in payload or "PC_VIA_WEB" in payload:
        return

    payload_saneado = payload.replace("\r", "").replace("\n", "").strip()

    if payload_saneado == st.session_state.ultimo_crudo:
        return
    st.session_state.ultimo_crudo = payload_saneado

    if payload_saneado.count("-37.") > 1:
        return

    cadena = payload_saneado.replace("GPS:", "").replace("TALLER|", "").strip()
    partes = [p.strip() for p in cadena.split(",")]
    
    es_coordenada = False
    try:
        p_lat = float(partes[0])
        p_lon = float(partes[1])
        if -90 <= p_lat <= 90 and -180 <= p_lon <= 180:
            es_coordenada = True
    except:
        es_coordenada = False

    if es_coordenada:
        p_lat = float(partes[0])
        p_lon = float(partes[1])
        
        debe_actualizar_mapa = (st.session_state.lat != p_lat or st.session_state.lon != p_lon)
        
        st.session_state.lat = p_lat
        st.session_state.lon = p_lon
        
        if len(partes) >= 5:
            st.session_state.satelites = "".join([c for c in partes[4] if c.isdigit()]) or "0"
        
        if len(partes) >= 6:
            st.session_state.velocidad = f"{partes[5]} km/h"
            
        if len(partes) >= 7:
            st.session_state.altitud = f"{partes[6]} msnm"
            
        if len(partes) >= 8:
            h_raw = partes[7]
            try:
                h_raw_padded = h_raw.zfill(8)
                hora_utc = int(h_raw_padded[0:2]) - 3
                if hora_utc < 0: hora_utc += 24
                st.session_state.hora_sat = f"{hora_utc:02d}:{h_raw_padded[2:4]}:{h_raw_padded[4:6]} (Local)"
            except:
                st.session_state.hora_sat = "--:--:--"

        st.session_state.ultimo_msg = "📡 Coordenada Recibida por Red 4G"
        st.session_state.canal = f"Internet: {topico_origen}"
        
        try:
            with open(GPS_FILE, "a", encoding="utf-8") as f:
                f.write(f"{p_lat},{p_lon}\n")
        except: pass
            
        if debe_actualizar_mapa:
            st.rerun()
        return

    msg_limpio = payload_saneado.replace("Msg PC:", "").replace("LU3DJA:", "").strip()
    if ", Bluetooth:" in msg_limpio:
        msg_limpio = msg_limpio.split(", Bluetooth:")[0].strip()

    st.session_state.ultimo_msg = msg_limpio
    st.session_state.canal = f"Celular Chat: {topico_origen}"
    
    ahora_str = datetime.now().strftime("%H:%M:%S")
    try:
        with open(CHAT_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ahora_str}] Móvil: {msg_limpio}\n")
    except: pass
    st.rerun()

def on_message(client, userdata, message):
    try:
        payload = message.payload.decode("utf-8").strip()
        procesar_cadena_entrante(payload, message.topic)
    except:
        pass

@st.cache_resource
def iniciar_conexion_mqtt():
    try:
        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        client.on_message = on_message
        client.connect("broker.emqx.io", 1883, keepalive=60)
        client.subscribe("auto/gps/loberia")    
        client.loop_start()
        for thread in threading.enumerate():
            if thread.name.startswith("paho-mqtt-client"):
                add_script_run_ctx(thread)
        return client
    except:
        return None

client_activo = iniciar_conexion_mqtt()

trayecto = []
if os.path.exists(GPS_FILE):
    try:
        with open(GPS_FILE, "r", encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if not linea: continue
                p_partes = linea.split(",")
                if len(p_partes) == 2:
                    trayecto.append([float(p_partes[0]), float(p_partes[1])])
    except: pass

if not trayecto:
    trayecto.append([st.session_state.lat, st.session_state.lon])

col1, col2 = st.columns(2)

with col1:
    @st.fragment
    def renderizar_datos_consola():
        st_autorefresh(interval=3000, key="texto_refresh")
        st.header("📡 Central de Monitoreo Familia")
        
        m_col1, m_col2 = st.columns(2)
        with m_col1:
            st.metric(label="🛰️ Satélites Activos", value=f"{st.session_state.satelites} Sats")
            st.metric(label="🏔️ Altitud", value=st.session_state.altitud)
        with m_col2:
            st.metric(label="⚡ Velocidad GPS", value=st.session_state.velocidad)
            st.metric(label="⏰ Sincronización", value=st.session_state.hora_sat)
            
        st.write(f"**📍 Coordenadas:** {st.session_state.lat:.6f} , {st.session_state.lon:.6f}")
        st.info(f"💬 **Último Evento:** {st.session_state.ultimo_msg}")
        
    renderizar_datos_consola()
    
    mensaje_a_enviar = st.text_input("Enviar Mensaje al Móvil:", placeholder="Escribe aquí...", key="input_msg")

    if st.button("📤 Transmitir Mensaje", use_container_width=True):
        if mensaje_a_enviar.strip() and client_activo is not None:
            texto_enviar = mensaje_a_enviar.strip()
            payload_camuflado = f"{texto_enviar} PC_VIA_WEB"
            client_activo.publish("auto/gps/torre_tx", payload_camuflado)
            
            ahora_actual = datetime.now().strftime("%H:%M:%S")
            try:
                with open(CHAT_FILE, "a", encoding="utf-8") as f:
                    f.write(f"[{ahora_actual}] Yo (PC): {texto_enviar}\n")
            except: pass
            st.rerun()
            
    st.markdown("#### 📝 Historial Reciente")
    if os.path.exists(CHAT_FILE):
        try:
            with open(CHAT_FILE, "r", encoding="utf-8") as f:
                lineas_chat = f.readlines()
            for l in reversed(lineas_chat[-6:]):
                st.text(l.strip())
        except: pass
            
    if st.button("🗑️ Reiniciar Historial de Ruta", use_container_width=True):
        try:
            if os.path.exists(GPS_FILE): os.remove(GPS_FILE)
            if os.path.exists(CHAT_FILE): os.remove(CHAT_FILE)
        except: pass
        st.session_state.lat = lat_casa
        st.session_state.lon = lon_casa
        st.session_state.satelites = "0"
        st.session_state.velocidad = "0.0 km/h"
        st.session_state.altitud = "0 m"
        st.session_state.hora_sat = "--:--:--"
        st.session_state.ultimo_msg = "Historial Vaciado con Éxito"
        st.rerun()

with col2:
    m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=16)
    if len(trayecto) > 1:
        folium.PolyLine(trayecto, color="blue", weight=6, opacity=0.85).add_to(m)
    folium.Marker([st.session_state.lat, st.session_state.lon], popup="Camioneta", icon=folium.Icon(color="red", icon="car", prefix="fa")).add_to(m)
    
    map_key = f"mapa_live_{st.session_state.lat}_{st.session_state.lon}_{len(trayecto)}"
    st_folium(m, width="100%", height=580, key=map_key)
