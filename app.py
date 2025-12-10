import streamlit as st
import pandas as pd
import plotly.express as px
from firebase_admin import credentials, db, initialize_app, get_app
from streamlit_option_menu import option_menu

# Firebase Configuration
FIREBASE_URL = 'https://smart-climate-monitoring-db-default-rtdb.firebaseio.com/'

# Streamlit Page Setup
st.set_page_config(layout="wide", page_title="Smart Climate Monitor", page_icon="🏠")


# --- INITIALIZATION FUNCTION ---
def init_firebase():
    """Initializes Firebase Admin SDK by reading individual secrets from st.secrets."""
    try:
        get_app()
    except ValueError:
        try:
            required_keys = [
                "firebase_type", "firebase_project_id", "firebase_private_key",
                "firebase_client_email", "firebase_token_uri", "firebase_auth_uri",
                "firebase_auth_provider_x509_cert_url", "firebase_client_x509_cert_url",
                "firebase_client_id"
            ]

            if all(key in st.secrets for key in required_keys):
                key_dict = {
                    "type": st.secrets["firebase_type"],
                    "project_id": st.secrets["firebase_project_id"],
                    "private_key": st.secrets["firebase_private_key"],
                    "client_email": st.secrets["firebase_client_email"],
                    "token_uri": st.secrets["firebase_token_uri"],
                    "auth_uri": st.secrets["firebase_auth_uri"],
                    "auth_provider_x509_cert_url": st.secrets["firebase_auth_provider_x509_cert_url"],
                    "client_x509_cert_url": st.secrets["firebase_client_x509_cert_url"],
                    "client_id": st.secrets["firebase_client_id"]
                }
                cred = credentials.Certificate(key_dict)
            else:
                st.error("Missing one or more required Firebase secrets. Please check the Streamlit Secrets dashboard.")
                st.stop()

            initialize_app(cred, {'databaseURL': FIREBASE_URL})
            st.success("Firebase connected successfully!")
        except Exception as e:
            st.error(f"Failed to initialize Firebase: {e}")
            st.stop()

    return db.reference('/')


# Initialize Firebase and get the root reference
root_ref = init_firebase()


# --- GET DATA HISTORY FUNCTION ---
@st.cache_data(ttl=60)
def get_data_history(limit=15):
    """
    Retrieves the latest 'limit' data entries using a direct Firebase query
    (limit_to_last), which ensures only the newest data is fetched.
    """
    try:
        logs_ref = root_ref.child('data_logs')
        logs = logs_ref.order_by_key().limit_to_last(limit).get()

        if not logs:
            return pd.DataFrame()

        data_list = []
        for key, log in logs.items():
            if log and 'sensor_logs' in log and 'actuator_logs' in log:
                timestamp_ms = log.get('timestamp', 0)

                if isinstance(timestamp_ms, str):
                    try:
                        timestamp_ms = int(timestamp_ms)
                    except ValueError:
                        timestamp_ms = 0

                record = {
                    'Timestamp (ms)': timestamp_ms,
                    'Temperature (°C)': log['sensor_logs'].get('temp'),
                    'Humidity (%)': log['sensor_logs'].get('humidity'),
                    'Light Level (Lux)': log['sensor_logs'].get('light_lvl'),
                    'Motion Detected': log['sensor_logs'].get('motion_state'),
                    'Relay State': log['actuator_logs'].get('relay_state'),
                    'Light State': log['actuator_logs'].get('light_state'),
                }
                data_list.append(record)

        df = pd.DataFrame(data_list)

        if not df.empty:
            # Conversion to datetime using 's' (Seconds) to fix 1970 date issue
            df['Timestamp'] = pd.to_datetime(df['Timestamp (ms)'], unit='s')
            df.set_index('Timestamp', inplace=True)
            df = df.sort_index()

        return df

    except Exception as e:
        st.error(f"Error reading data from Firebase: {e}")
        return pd.DataFrame()


# Multi-Page Navigation
with st.sidebar:
    selected = option_menu(
        menu_title="Main Menu",
        options=["Data History", "Control"],
        icons=["clock-history", "sliders"],
        menu_icon="cast",
        default_index=0,
    )

# 1. Data History Page
if selected == "Data History":
    st.title("📊 Data History & Visualization (Latest 15)")
    st.markdown("---")

    df_history = get_data_history(limit=15)

    if df_history.empty:
        st.info("No data available in the 'data_logs' path. Ensure your NodeMCU is pushing data.")
    else:
        static_key_suffix = "static_display"

        st.subheader("Time Series Data")
        col1, col2 = st.columns(2)

        with col1:
            fig_th = px.line(
                df_history,
                y=['Temperature (°C)', 'Humidity (%)'],
                title="Temperature & Humidity Over Time",
                height=400
            )
            st.plotly_chart(fig_th, use_container_width=True, key=f'temp_hum_chart_{static_key_suffix}')

        with col2:
            fig_light = px.line(
                df_history,
                y='Light Level (Lux)',
                title="Light Level Over Time",
                height=400
            )
            st.plotly_chart(fig_light, use_container_width=True, key=f'light_level_chart_{static_key_suffix}')

        st.subheader("Raw Data Table")
        latest_15_df_display = df_history.sort_index(ascending=False)
        st.dataframe(latest_15_df_display, use_container_width=True, key=f'data_table_{static_key_suffix}')

# 2. Control Page
elif selected == "Control":
    st.title("🕹️ Device Control Interface")
    st.markdown("---")

    control_ref = root_ref.child('controls')


    # Reads current status (Temp/Hum).
    # Reduced TTL to 5s so you see environmental changes quickly.
    @st.cache_data(ttl=5)
    def read_current_status():
        """Reads the current status from Firebase."""
        status = root_ref.child('current_status').get()
        if status:
            return status.get('temp', 'N/A'), status.get('humidity', 'N/A')
        return 'N/A', 'N/A'


    # Sets the override value in Firebase
    def set_override(device, value):
        """Pushes the boolean override command to Firebase."""
        try:
            control_ref.child(f'{device}_override').set(value)
            st.toast(f"{device.capitalize()} override set to {value}", icon='✅')
        except Exception as e:
            st.error(f"Failed to send command: {e}")


    # CRITICAL FIX: REMOVED @st.cache_data
    # This must fetch the LIVE state every time to prevent the toggle from
    # resetting to an old cached value.
    def get_current_control_state(device):
        """Reads the current override state for the toggle switch."""
        try:
            state = control_ref.child(f'{device}_override').get()
            return bool(state)
        except:
            return False


    # Live Status Display
    st.subheader("Current Climate Status")
    temp, humidity = read_current_status()

    col_status_1, col_status_2 = st.columns(2)
    with col_status_1:
        st.metric("Current Temperature", f"{temp}°C")
    with col_status_2:
        st.metric("Current Humidity", f"{humidity}%")

    # Control Widgets
    st.subheader("Light Control")
    # Fetch live state immediately before rendering the toggle
    current_light_state = get_current_control_state('light')

    light_toggle = st.toggle(
        "Light Override (Manual Control)",
        value=current_light_state,
        key='light_override_toggle',
        help="Turn ON to set LED to 255. Turn OFF to set LED to 0."
    )

    # Check if the user just flipped the switch
    if light_toggle != current_light_state:
        set_override('light', light_toggle)
        # We manually sleep briefly to allow Firebase to process, then rerun to confirm state
        import time

        time.sleep(0.5)
        st.rerun()

    st.markdown("---")

    st.subheader("Relay Control")
    current_relay_state = get_current_control_state('relay')

    relay_toggle = st.toggle(
        "Relay Override (Pump/Fan)",
        value=current_relay_state,
        key='relay_override_toggle',
        help="Turn ON to activate the relay. Turn OFF to deactivate."
    )

    if relay_toggle != current_relay_state:
        set_override('relay', relay_toggle)
        import time

        time.sleep(0.5)
        st.rerun()