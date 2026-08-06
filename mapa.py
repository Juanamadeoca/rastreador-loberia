import streamlit as st
import folium
from streamlit_folium import st_folium
import os
from streamlit_autorefresh import st_autorefresh
from datetime import datetime
import threading
import socket
from streamlit.runtime.scriptrunner import add_script_run_ctx

st.set_page_config(page_title="Rastreador Satelital QSO LINK", layout="wide")

st.markdown("""
    <style>
        .block-container { padding-top: 1rem !important; padding-bottom: 0rem !important; padding-left: 2rem !important; padding-right: 2rem !important; }
    </style>
""", unsafe_allow_html=True)

GPS_FILE = "gps_trayecto.txt"
CHAT_FILE = "gps_mensajes.txt"

lat_casa, lon_casa = -37.7843311149627, -58.848557034507394

if "lat" not in st.session_state: st.session_state.lat = lat_casa
if "lon" not in st.session_state: st.session_state.lon = lon_casa
if "ultimo_msg" not in st.session_state: st.session_state.ultimo_msg = "Iniciando sistema..."
if "canal" not in st.session_state: st.session_state.canal = "Red Local Taller"
if "satelites" not in st.session_state: st.session_state.satelites = "0"
if "velocidad" not in st.session_state: st.session_state.velocidad = "0.0 km/h"
if "altitud" not in st.session_state: st.session_state.altitud = "0 m"
if "hora_sat" not in st.session_state: st.session_state.hora_sat = "--:--:--"
if "ultimo_crudo" not in st.session_state: st.session_state.ultimo_crudo = ""
if "solicitar_recarga" not in st.session_state: st.session_state.solicitar_recarga = False

def procesar_cadena_entrante(payload, fuente="Radio Local"):
    if "ACK" in payload or "PC_VIA_WEB" in payload:
        return

    payload_saneado = payload.replace("\r", "").replace("\n", "").strip()

    if payload_saneado == st.session_state.ultimo_crudo:
        return
    st.session_state.ultimo_crudo = payload_saneado

    if "GPS:" in payload_saneado or "-37." in payload_saneado or "-38." in payload_saneado:
        cadena_limpia = payload_saneado.replace("GPS:", "").strip()
        partes = [p.strip() for p in cadena_limpia.split(",")]
        
        try:
            p_lat = float(partes[0])
            p_lon = float(partes[1])
            
            if -90 <= p_lat <= 90 and -180 <= p_lon <= 180:
                st.session_state.lat = p_lat
                st.session_state.lon = p_lon
                
                st.session_state.satelites = "12"
                if len(partes) >= 5:
                    st.session_state.satelites = "".join([c for c in partes[4] if c.isdigit()]) or "12"
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

                st.session_state.ultimo_msg = "📡 Central Sincronizada por Torre"
                st.session_state.canal = fuente
                
                with open(GPS_FILE, "a", encoding="utf-8") as f:
                    f.write(f"{p_lat},{p_lon}\n")
                    
                st.session_state.solicitar_recarga = True
        except:
            pass
        return

    if "LU3DJA:" in payload_saneado or "Móvil:" in payload_saneado:
        msg_limpio = payload_saneado.replace("LU3DJA:", "").strip()
        st.session_state.ultimo_msg = msg_limpio
        st.session_state.canal = "Radio Chat"
        
        ahora_str = datetime.now().strftime("%H:%M:%S")
        with open(CHAT_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ahora_str}] Móvil: {msg_limpio}\n")
        st.session_state.solicitar_recarga = True

def escuchar_torre_local_udp():
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            if hasattr(socket, "SIO_UDP_CONNRESET"):
                sock.ioctl(socket.SIO_UDP_CONNRESET, False)
            sock.bind(("0.0.0.0", 5005))
            while True:
                data, addr = sock.recvfrom(1024)
                if data:
                    payload = data.decode("utf-8", errors="ignore").strip()
                    procesar_cadena_entrante(payload, fuente=f"Torre Local ({addr[0]})")
        except:
            pass

@st.cache_resource
def iniciar_servicios_segundo_plano():
    t_udp = threading.Thread(target=escuchar_torre_local_udp, daemon=True)
    add_script_run_ctx(t_udp)
    t_udp.start()

iniciar_servicios_segundo_plano()

if st.session_state.solicitar_recarga:
    st.session_state.solicitar_recarga = False
    st.rerun()

st_autorefresh(interval=3000, key="global_refresh")

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
    
    mensaje_a_enviar = st.text_input("Enviar Mensaje al Móvil:", placeholder="Escribe aquí...", key="input_msg")

    if st.button("📤 Transmitir Mensaje", use_container_width=True):
        if mensaje_a_enviar.strip():
            texto_enviar = mensaje_a_enviar.strip()
            sock_tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock_tx.sendto(f"PC_MSG:{texto_enviar}".encode("utf-8"), ("192.168.1.202", 5005))
            except:
                pass
            
            ahora_actual = datetime.now().strftime("%H:%M:%S")
            with open(CHAT_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{ahora_actual}] Yo (PC): {texto_enviar}\n")
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
    m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=15)
    if len(trayecto) > 1:
        folium.PolyLine(locations=trayecto, color="#0D47A1", width=5, opacity=0.8, tooltip="Trayecto QSO LINK").add_to(m)
    
    folium.Marker(
        location=[st.session_state.lat, st.session_state.lon],
        popup=f"Móvil LU3DJA\nVel: {st.session_state.velocidad}\nHora: {st.session_state.hora_sat}",
        tooltip="Posición Actual",
        icon=folium.Icon(color="blue", icon="signal", prefix="fa")
    ).add_to(m)
    st_folium(m, width="100%", height=600, key="mapa_principal")
