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

fecha_hoy = datetime.now().strftime("%Y_%m_%d")
GPS_FILE = f"gps_datos_{fecha_hoy}.txt"
CHAT_FILE = "gps_mensajes.txt"
ESTADO_FILE = "gps_estado_actual.txt" 

file_lock = threading.Lock()
lat_casa, lon_casa = -37.7843311149627, -58.848557034507394

if "limite_velocidad" not in st.session_state: st.session_state.limite_velocidad = 110.0

def guardar_estado_compartido(lat, lon, sats, vel, alt, hora, msg):
    try:
        with file_lock:
            with open(ESTADO_FILE, "w", encoding="utf-8") as f:
                f.write(f"{lat}|{lon}|{sats}|{vel}|{alt}|{hora}|{msg}\n")
    except: pass

def leer_estado_compartido():
    if os.path.exists(ESTADO_FILE):
        try:
            with file_lock:
                with open(ESTADO_FILE, "r", encoding="utf-8") as f:
                    linea = f.read().strip()
            partes = linea.split("|")
            if len(partes) == 7:
                return float(partes[0]), float(partes[1]), partes[2], partes[3], partes[4], partes[5], partes[6]
        except: pass
    return lat_casa, lon_casa, "0", "0.0 km/h", "0 m", "--:--:--", "Sincronizando satélites..."

v_lat, v_lon, v_sats, v_vel, v_alt, v_hora, v_msg = leer_estado_compartido()

v_ultimo_chat = "Sin mensajes nuevos"
if os.path.exists(CHAT_FILE):
    try:
        with file_lock:
            with open(CHAT_FILE, "r", encoding="utf-8") as f:
                lineas = f.readlines()
        if lineas:
            v_ultimo_chat = lineas[-1].strip()
    except: pass

def procesar_cadena_entrante(payload, topico_origen):
    if "ACK" in payload or "PC_VIA_WEB" in payload:
        return
    payload_saneado = payload.replace("\r", "").replace("\n", "").strip()

    if topico_origen == "qsolink/auto/coordenadas":
        cadena_limpia = payload_saneado.replace("GPS:", "").strip()
        partes = [p.strip() for p in cadena_limpia.split(",")]
        try:
            p_lat = float(partes[0])
            p_lon = float(partes[1])
            if -90 <= p_lat <= 90 and -180 <= p_lon <= 180:
                p_sats = partes[4] if len(partes) >= 5 else "0"
                p_vel = f"{partes[5]} km/h" if len(partes) >= 6 else "0.0 km/h"
                p_alt = f"{partes[6]} msnm" if len(partes) >= 7 else "0 m"
                p_hora = datetime.now().strftime("%H:%M:%S") + " (Local)"
                
                guardar_estado_compartido(p_lat, p_lon, p_sats, p_vel, p_alt, p_hora, "📡 Central Sincronizada OK")
                
                with file_lock:
                    with open(GPS_FILE, "a", encoding="utf-8") as f:
                        f.write(f"{p_lat},{p_lon}\n")
        except: pass

    if topico_origen == "qsolink/auto/chat":
        msg_limpio = payload_saneado.replace("LU3DJA:", "").strip()
        ahora_str = datetime.now().strftime("%H:%M:%S")
        with file_lock:
            with open(CHAT_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{ahora_str}] Móvil: {msg_limpio}\n")

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        client.subscribe("qsolink/auto/coordenadas")    
        client.subscribe("qsolink/auto/chat")    

def on_message(client, userdata, message):
    try:
        payload = message.payload.decode("utf-8").strip()
        procesar_cadena_entrante(payload, message.topic)
    except: pass

@st.cache_resource
def iniciar_conexion_mqtt():
    try:
        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        client.on_connect = on_connect
        client.on_message = on_message
        client.connect("broker.emqx.io", 1883, keepalive=60)
        client.loop_start()
        for thread in threading.enumerate():
            if thread.name.startswith("paho-mqtt-client"):
                add_script_run_ctx(thread)
        return client
    except: return None

client_activo = iniciar_conexion_mqtt()
st_autorefresh(interval=3000, key="global_refresh")

archivos_en_carpeta = os.listdir(".")
archivos_viajes = sorted([f for f in archivos_en_carpeta if f.startswith("gps_datos_") and f.endswith(".txt")])
st.sidebar.header("📂 Historial de Viajes")
archivo_seleccionado = st.sidebar.selectbox("Seleccionar Fecha de Ruta:", archivos_viajes, index=archivos_viajes.index(GPS_FILE) if GPS_FILE in archivos_viajes else 0)

st.sidebar.markdown("---")
st.sidebar.header("⚡ Alertas de Control")
limite_ingresado = st.sidebar.number_input("Límite de velocidad (km/h):", min_value=20, max_value=200, value=int(st.session_state.limite_velocidad), step=5)

if st.sidebar.button("💾 Aplicar Límite en Móvil", use_container_width=True):
    st.session_state.limite_velocidad = limite_ingresado
    if client_activo is not None:
        client_activo.publish("qsolink/pc/comandos", f"VEL_LIMIT:{limite_ingresado} PC_VIA_WEB")
        st.sidebar.success(f"¡Límite {limite_ingresado} km/h enviado!")

trayecto = []
archivo_a_cargar = archivo_seleccionado if archivo_seleccionado else GPS_FILE
if os.path.exists(archivo_a_cargar):
    try:
        with file_lock:
            with open(archivo_a_cargar, "r", encoding="utf-8") as f:
                for linea in f:
                    linea = linea.strip()
                    if not linea: continue
                    p_partes = linea.split(",")
                    if len(p_partes) == 2:
                        trayecto.append([float(p_partes[0]), float(p_partes[1])])
    except: pass

if not trayecto:
    trayecto.append([v_lat, v_lon])

try: vel_numerica = float(v_vel.replace(" km/h", "").strip())
except: vel_numerica = 0.0
exceso_velocidad = vel_numerica > st.session_state.limite_velocidad

col1, col2 = st.columns(2)

with col1:
    st.header("📡 Central de Monitoreo Familia")
    if exceso_velocidad:
        st.error(f"🚨 ¡ALERTA DE EXCESO DE VELOCIDAD! El auto va a {v_vel} (Límite: {st.session_state.limite_velocidad} km/h)")

    m_col1, m_col2 = st.columns(2)
    with m_col1:
        st.metric(label="🛰️ Satélites Activos", value=f"{v_sats} Sats")
        st.metric(label="🏔️ Altitud", value=v_alt)
    with m_col2:
        st.metric(label="⚡ Velocidad GPS", value=v_vel, delta="¡Exceso!" if exceso_velocidad else None, delta_color="inverse" if exceso_velocidad else "normal")
        st.metric(label="⏰ Sincronización", value=v_hora)
        
    st.write(f"**📍 Coordenadas:** {v_lat:.6f} , {v_lon:.6f}")
    
    if "PANICO" in v_msg.upper() or "PANICO" in v_ultimo_chat.upper():
        st.error("🚨 **ALERTA DE EMERGENCIA:** ¡BOTÓN DE PÁNICO PRESIONADO EN EL MÓVIL!")
    else:
        st.info(f"💬 **Último Evento GPS:** {v_msg}")
    
    st.markdown("---")
    st.success(f"📱 **Último Chat desde el Auto:** {v_ultimo_chat}")
    
    mensaje_a_enviar = st.text_input("Enviar Mensaje al Móvil:", placeholder="Escribe aquí...", key="input_msg")

    if st.button("📤 Transmitir Mensaje", use_container_width=True):
        if mensaje_a_enviar.strip() and client_activo is not None:
            texto_enviar = mensaje_a_enviar.strip()
            payload_camuflado = f"{texto_enviar} PC_VIA_WEB"
            client_activo.publish("qsolink/pc/comandos", payload_camuflado)
            
            ahora_actual = datetime.now().strftime("%H:%M:%S")
            try:
                with file_lock:
                    with open(CHAT_FILE, "a", encoding="utf-8") as f:
                        f.write(f"[{ahora_actual}] Yo (PC): {texto_enviar}\n")
            except: pass
            st.rerun()
            
    st.markdown("#### 📝 Historial Reciente de Mensajes")
    if os.path.exists(CHAT_FILE):
        try:
            with file_lock:
                with open(CHAT_FILE, "r", encoding="utf-8") as f:
                    lineas_chat = f.readlines()
            for l in reversed(lineas_chat[-6:]):
                st.text(l.strip())
        except: pass
            
    st.markdown("---")
    if st.button("🗑️ Vaciar Mapa de Hoy", use_container_width=True):
        try:
            with file_lock:
                if os.path.exists(GPS_FILE): os.remove(GPS_FILE)
                if os.path.exists(ESTADO_FILE): os.remove(ESTADO_FILE)
        except: pass
        st.rerun()
        
    # 🟢 BOTÓN AGREGADO: Vaciar Historial de Chats para toda la familia
    if st.button("🗑️ Vaciar Historial de Chats", use_container_width=True):
        try:
            with file_lock:
                if os.path.exists(CHAT_FILE): os.remove(CHAT_FILE)
        except: pass
        st.rerun()

with col2:
    m = folium.Map(location=[v_lat, v_lon], zoom_start=14)
    folium.Marker(location=[lat_casa, lon_casa], popup="Mi Taller", icon=folium.Icon(color="red", icon="home", prefix="fa")).add_to(m)
    if len(trayecto) > 1:
        folium.PolyLine(locations=trayecto, color="#0D47A1", width=5).add_to(m)
    folium.Marker(location=[v_lat, v_lon], popup=f"Móvil LU3DJA\nVel: {v_vel}", icon=folium.Icon(color="blue", icon="car", prefix="fa")).add_to(m)
    st_folium(m, width="100%", height=600, key="mapa_principal")
