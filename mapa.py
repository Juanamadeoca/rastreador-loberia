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

file_lock = threading.Lock()

lat_casa, lon_casa = -37.7843311149627, -58.848557034507394

if "lat" not in st.session_state: st.session_state.lat = lat_casa
if "lon" not in st.session_state: st.session_state.lon = lon_casa
if "ultimo_msg" not in st.session_state: st.session_state.ultimo_msg = "Sincronizando satélites..."
if "ultimo_chat" not in st.session_state: st.session_state.ultimo_chat = "Sin mensajes nuevos"
if "canal" not in st.session_state: st.session_state.canal = "Red Internet"
if "satelites" not in st.session_state: st.session_state.satelites = "0"
if "velocidad" not in st.session_state: st.session_state.velocidad = "0.0 km/h"
if "altitud" not in st.session_state: st.session_state.altitud = "0 m"
if "hora_sat" not in st.session_state: st.session_state.hora_sat = "--:--:--"
if "ultimo_crudo" not in st.session_state: st.session_state.ultimo_crudo = ""
if "limite_velocidad" not in st.session_state: st.session_state.limite_velocidad = 110.0

def procesar_cadena_entrante(payload, topico_origen):
    if "ACK" in payload or "PC_VIA_WEB" in payload:
        return

    payload_saneado = payload.replace("\r", "").replace("\n", "").strip()

    if payload_saneado == st.session_state.ultimo_crudo:
        return
    st.session_state.ultimo_crudo = payload_saneado

    if topico_origen == "qsolink/auto/coordenadas":
        cadena_limpia = payload_saneado.replace("GPS:", "").strip()
        partes = [p.strip() for p in cadena_limpia.split(",")]
        
        try:
            p_lat = float(partes[0])
            p_lon = float(partes[1])
            
            if -90 <= p_lat <= 90 and -180 <= p_lon <= 180:
                posicion_cambio = (p_lat != st.session_state.lat) or (p_lon != st.session_state.lon)
                
                st.session_state.lat = p_lat
                st.session_state.lon = p_lon
                
                if len(partes) >= 5:
                    st.session_state.satelites = partes[4]
                if len(partes) >= 6:
                    st.session_state.velocidad = f"{partes[5]} km/h"
                if len(partes) >= 7:
                    st.session_state.altitud = f"{partes[6]} msnm"
                
                # ⏰ SOLUCIÓN RELOJ: Toma la hora de Windows al recibir el dato, infalible y exacta
                st.session_state.hora_sat = datetime.now().strftime("%H:%M:%S") + " (Local)"

                st.session_state.ultimo_msg = "📡 Central Sincronizada OK"
                
                if posicion_cambio:
                    with file_lock:
                        with open(GPS_FILE, "a", encoding="utf-8") as f:
                            f.write(f"{p_lat},{p_lon}\n")
        except:
            pass
        return

    if topico_origen == "qsolink/auto/chat":
        msg_limpio = payload_saneado.replace("LU3DJA:", "").strip()
        st.session_state.ultimo_chat = msg_limpio
        
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
    except:
        pass
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
    except:
        return None

client_activo = iniciar_conexion_mqtt()

st_autorefresh(interval=3000, key="global_refresh")

# Menú en barra lateral para ver viajes de días anteriores
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
    trayecto.append([st.session_state.lat, st.session_state.lon])

vel_numerica = 0.0
try:
    vel_numerica = float(st.session_state.velocidad.replace(" km/h", "").strip())
except: pass

exceso_velocidad = vel_numerica > st.session_state.limite_velocidad

col1, col2 = st.columns(2)

with col1:
    st.header("📡 Central de Monitoreo Familia")
    
    if exceso_velocidad:
        st.error(f"🚨 ¡ALERTA DE EXCESO DE VELOCIDAD! El auto va a {st.session_state.velocidad} (Límite: {st.session_state.limite_velocidad} km/h)")

    m_col1, m_col2 = st.columns(2)
    with m_col1:
        st.metric(label="🛰️ Satélites Activos", value=f"{st.session_state.satelites} Sats")
        st.metric(label="🏔️ Altitud", value=st.session_state.altitud)
    with m_col2:
        st.metric(label="⚡ Velocidad GPS", value=st.session_state.velocidad, delta=f"¡Exceso!" if exceso_velocidad else None, delta_color="inverse" if exceso_velocidad else "normal")
        st.metric(label="⏰ Sincronización", value=st.session_state.hora_sat)
        
    st.write(f"**📍 Coordenadas:** {st.session_state.lat:.6f} , {st.session_state.lon:.6f}")
    
    if "PANICO" in st.session_state.ultimo_msg.upper() or "PANICO" in st.session_state.ultimo_chat.upper():
        st.error(f"🚨 **ALERTA DE EMERGENCIA:** ¡BOTÓN DE PÁNICO PRESIONADO EN EL MÓVIL!")
    else:
        st.info(f"💬 **Último Evento GPS:** {st.session_state.ultimo_msg}")
    
    st.markdown("---")
    st.success(f"📱 **Último Chat desde el Auto:** {st.session_state.ultimo_chat}")
    
    mensaje_a_enviar = st.text_input("Enviar Mensaje al Móvil:", placeholder="Escribe aquí...", key="input_msg")

    if st.button("📤 Transmitir Mensaje", use_container_width=True):
        if mensaje_a_enviar.strip() and client_activo is not None:
            texto_enviar = mensaje_a_enviar.strip()
            payload_camuflado = f"{texto_enviar} PC_VIA_WEB"
            client_activo.publish("qsolink/pc/comandos", payload_camuflado)
            
            ahora_actual = datetime.now().strftime("%H:%M:%S")
            with file_lock:
                with open(CHAT_FILE, "a", encoding="utf-8") as f:
                    f.write(f"[{ahora_actual}] Yo (PC): {texto_enviar}\n")
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
        except: pass
        st.session_state.lat = lat_casa
        st.session_state.lon = lon_casa
        st.session_state.satelites = "0"
        st.session_state.velocidad = "0.0 km/h"
        st.session_state.altitud = "0 m"
        st.session_state.hora_sat = "--:--:--"
        st.session_state.ultimo_msg = "Mapa Vaciado con Éxito"
        st.rerun()
        
    if st.button("🗑️ Vaciar Historial de Chats", use_container_width=True):
        try:
            with file_lock:
                if os.path.exists(CHAT_FILE): os.remove(CHAT_FILE)
        except: pass
        st.session_state.ultimo_chat = "Historial de mensajes vaciado"
        st.rerun()

with col2:
    m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=14)
    
    folium.Marker(
        location=[lat_casa, lon_casa],
        popup="Taller / Casa Fija (San Manuel)",
        tooltip="Mi Taller",
        icon=folium.Icon(color="red", icon="home", prefix="fa")
    ).add_to(m)

    if len(trayecto) > 1:
        folium.PolyLine(locations=trayecto, color="#0D47A1", width=5).add_to(m)
    
    folium.Marker(
        location=[st.session_state.lat, st.session_state.lon],
        popup=f"Móvil LU3DJA\nVel: {st.session_state.velocidad}",
        tooltip="Posición Actual",
        icon=folium.Icon(color="blue", icon="car", prefix="fa")
    ).add_to(m)
    st_folium(m, width="100%", height=600, key="mapa_principal")
