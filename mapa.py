import streamlit as st
import folium
from streamlit_folium import st_folium
import os
import paho.mqtt.client as mqtt
from datetime import datetime
import threading
from streamlit.runtime.scriptrunner import add_script_run_ctx
# ⏰ EL ANCLA HORARIA: Para obligar al servidor de internet a dar la hora de Argentina
from zoneinfo import ZoneInfo

st.set_page_config(page_title="Rastreador Satelital QSO LINK", layout="wide")

# --- ESTILOS DE PANTALLA ---
st.markdown("""
    <style>
        .block-container { padding-top: 1rem !important; padding-bottom: 0rem !important; padding-left: 2rem !important; padding-right: 2rem !important; }
        .stElementContainer iframe { touch-action: none !important; -webkit-user-select: none !important; user-select: none !important; }
        @media (max-width: 800px) { .stRemoteComponent { min-height: 450px !important; } }
    </style>
""", unsafe_allow_html=True)

# Clava la fecha del archivo según el huso horario real
fecha_hoy = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).strftime("%Y_%m_%d")
GPS_FILE = f"gps_datos_{fecha_hoy}.txt"
CHAT_FILE = "gps_mensajes.txt"
ESTADO_FILE = "gps_estado_actual.txt" 

file_lock = threading.Lock()
lat_casa, lon_casa = -37.784331, -58.848557 # Coordenadas en San Manuel

if "limite_velocidad" not in st.session_state: st.session_state.limite_velocidad = 110.0
if "map_zoom" not in st.session_state: st.session_state.map_zoom = 14
if "map_center" not in st.session_state: st.session_state.map_center = [lat_casa, lon_casa]

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

def procesar_cadena_entrante(payload, topico_origen):
    if "ACK" in payload or "PC_VIA_WEB" in payload: return
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
                p_alt = f"{partes[6]} m" if len(partes) >= 7 else "0 m"
                
                # 🟢 REPARACIÓN EXTENSA: Sincroniza la hora al reloj de Buenos Aires de prepo
                p_hora = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).strftime("%H:%M:%S")
                
                guardar_estado_compartido(p_lat, p_lon, p_sats, p_vel, p_alt, p_hora, "📡 Central Sincronizada OK")
                
                with file_lock:
                    with open(GPS_FILE, "a", encoding="utf-8") as f:
                        f.write(f"{p_lat},{p_lon}\n")
        except: pass

    if topico_origen == "qsolink/auto/chat":
        msg_limpio = payload_saneado.replace("LU3DJA:", "").strip()
        ahora_str = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).strftime("%H:%M:%S")
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

# --- INTERFAZ GRÁFICA ---
st.title("📡 Central de Monitoreo Satelital - LU3DJA")

archivos_en_carpeta = os.listdir(".")
archivos_viajes = sorted([f for f in archivos_en_carpeta if f.startswith("gps_datos_") and f.endswith(".txt")])
st.sidebar.header("📂 Historial de Viajes")
archivo_seleccionado = st.sidebar.selectbox("Seleccionar Fecha de Ruta:", archivos_viajes, index=archivos_viajes.index(GPS_FILE) if GPS_FILE in archivos_viajes else 0)

if st.sidebar.button("🎯 Centrar en el Móvil", use_container_width=True):
    v_lat_c, v_lon_c, _, _, _, _, _ = leer_estado_compartido()
    st.session_state.map_center = [v_lat_c, v_lon_c]
    st.session_state.map_zoom = 15
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.header("⚡ Alertas de Control")
limite_ingresado = st.sidebar.number_input("Límite de velocidad (km/h):", min_value=20, max_value=200, value=int(st.session_state.limite_velocidad), step=5)

if st.sidebar.button("💾 Aplicar Límite en Móvil", use_container_width=True):
    st.session_state.limite_velocidad = limite_ingresado
    if client_activo is not None:
        client_activo.publish("qsolink/pc/comandos", f"VEL_LIMIT:{limite_ingresado} PC_VIA_WEB")
        st.sidebar.success(f"¡Límite {limite_ingresado} km/h enviado!")

# --- DISEÑO EN DOS COLUMNAS LIMPIAS ---
col_izquierda, col_derecha = st.columns(2)

# ⏱️ EL MARCAPASOS EXCLUSIVO DE DATOS PARA LA WEB DEL TELÉFONO
with col_izquierda:
    @st.fragment(run_every=2)
    def renderizar_datos_dinamicos():
        lat_act, lon_act, sats_act, vel_act, alt_act, hora_act, msg_act = leer_estado_compartido()
        
        ultimo_chat_act = "Sin mensajes nuevos del móvil"
        if os.path.exists(CHAT_FILE):
            try:
                with file_lock:
                    with open(CHAT_FILE, "r", encoding="utf-8") as f:
                        lineas = f.readlines()
                for linea in reversed(lineas):
                    if "Móvil:" in linea:
                        ultimo_chat_act = linea.strip()
                        break
            except: pass

        try: vel_num = float(vel_act.replace(" km/h", "").strip())
        except: vel_num = 0.0
        exceso_vel = vel_num > st.session_state.limite_velocidad

        if exceso_vel:
            st.error(f"🚨 ¡ALERTA DE EXCESO DE VELOCIDAD! El auto va a {vel_act}")

        m_col1, m_col2 = st.columns(2)
        with m_col1:
            st.metric(label="🛰️ Satélites Activos", value=f"{sats_act} Sats")
            st.metric(label="🏔️ Altitud", value=alt_act)
        with m_col2:
            st.metric(label="⚡ Velocidad GPS", value=vel_act, delta="¡Exceso!" if exceso_vel else None, delta_color="inverse" if exceso_vel else "normal")
            st.metric(label="⏰ Sincronización", value=hora_act)
            
        st.write(f"**📍 Coordenadas Actuales:** {lat_act:.6f} , {lon_act:.6f}")
        
        if "PANICO" in msg_act.upper() or "PANICO" in ultimo_chat_act.upper():
            st.error("🚨 **ALERTA DE EMERGENCIA:** ¡BOTÓN DE PÁNICO PRESIONADO!")
        else:
            st.info(f"💬 **Último Evento GPS:** {msg_act}")
            
        st.success(f"📱 **Último Chat desde el Auto:** {ultimo_chat_act}")
        
        mensaje_enviar = st.text_input("Enviar Mensaje al Móvil:", placeholder="Escribe aquí...", key="input_msg")

        if st.button("📤 Transmitir Mensaje", use_container_width=True):
            if mensaje_enviar.strip() and client_activo is not None:
                texto_enviar = mensaje_enviar.strip()
                client_activo.publish("qsolink/pc/comandos", f"{texto_enviar} PC_VIA_WEB")
                ahora_actual = datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).strftime("%H:%M:%S")
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
                for l in reversed(lineas_chat[-5:]): st.text(l.strip())
            except: pass

    renderizar_datos_dinamicos()

# 🗺️ LA COLUMNA DEL MAPA FIJO PARA LA WEB (Dibuja la ruta sin parpadear)
with col_derecha:
    trayecto = []
    archivo_cargar = archivo_seleccionado if archivo_seleccionado else GPS_FILE
    if os.path.exists(archivo_cargar):
        try:
            with file_lock:
                with open(archivo_cargar, "r", encoding="utf-8") as f:
                    for linea in f:
                        linea = linea.strip()
                        if not linea: continue
                        p_partes = linea.split(",")
                        if len(p_partes) == 2:
                            trayecto.append([float(p_partes), float(p_partes)])
        except: pass

    if not trayecto: trayecto.append([v_lat, v_lon])

    m = folium.Map(location=st.session_state.map_center, zoom_start=st.session_state.map_zoom)
    folium.Marker(location=[lat_casa, lon_casa], popup="Mi Taller", icon=folium.Icon(color="red", icon="home", prefix="fa")).add_to(m)
    
    if len(trayecto) > 1:
        folium.PolyLine(locations=trayecto, color="#0D47A1", width=5).add_to(m)
        
    folium.Marker(location=[v_lat, v_lon], popup=f"Móvil LU3DJA\nVel: {v_vel}", icon=folium.Icon(color="blue", icon="car", prefix="fa")).add_to(m)
    
    map_data = st_folium(m, width="100%", height=500, key="mapa_principal", returned_objects=["zoom", "center"])
    
    if map_data is not None:
        if map_data.get("zoom") is not None: st.session_state.map_zoom = map_data["zoom"]
        if map_data.get("center") is not None: st.session_state.map_center = [map_data["center"]["lat"], map_data["center"]["lng"]]

    st.markdown("---")
    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        if st.button("🗑️ Vaciar Mapa de Hoy", use_container_width=True):
            try:
                with file_lock:
                    if os.path.exists(GPS_FILE): os.remove(GPS_FILE)
                    if os.path.exists(ESTADO_FILE): os.remove(ESTADO_FILE)
                st.rerun()
            except: pass
            
    with btn_col2:
        if st.button("🗑️ Vaciar Historial de Chats", use_container_width=True):
            try:
                with file_lock:
                    if os.path.exists(CHAT_FILE): os.remove(CHAT_FILE)
                st.rerun()
            except: pass
