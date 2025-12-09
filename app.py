import streamlit as st
import pandas as pd
import plotly.express as px
from firebase_admin import credentials, db, initialize_app, get_app
from streamlit_option_menu import option_menu
from datetime import datetime
import json
import time

# Firebase Configuration
FIREBASE_URL = 'https://smart-climate-monitoring-db-default-rtdb.firebaseio.com/'

# Initialization Function
def init_firebase():
    """Initializes Firebase Admin SDK if it hasn't been initialized already."""
    try:
        get_app()
    except ValueError:
        try:
            # 1. Check if credentials are in st.secrets
            if "firebase_credentials" in st.secrets:
                # Load the clean JSON string from Streamlit secrets
                key_dict = json.loads(st.secrets["firebase_credentials"])
                cred = credentials.Certificate(key_dict)
            else:
                # Stop if secret is not found (necessary for deployment)
                st.error("Firebase credentials not found in Streamlit secrets. Please configure the 'firebase_credentials' secret.")
                st.stop()

            initialize_app(cred, {'databaseURL': FIREBASE_URL})
            st.success("Firebase connected successfully!")
        except Exception as e:
            st.error(f"Failed to initialize Firebase: {e}")
            st.stop()
    return db.reference('/')

# Streamlit Page Setup
st.set_page_config(layout="wide", page_title="Smart Climate Monitor", page_icon="🏠")

# Initialize Firebase and get the root reference
root_ref = init_firebase()

@st.cache_data(ttl=5)
def get_data_history():
    """Reads and formats data from the /data_logs path."""
    try:
        logs = root_ref.child('data_logs').get()

        if not logs:
            return pd.DataFrame()

        data_list = []
        for key, log in logs.items():
            if log and 'sensor_logs' in log and 'actuator_logs' in log:
                timestamp_ms = log.get('timestamp', 0)

                # Ensure timestamp is treated as a long integer
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

        # Conversion to datetime
        if not df.empty:
            df['Timestamp'] = pd.to_datetime(df['Timestamp (ms)'], unit='ms')
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
    st.title("📊 Data History & Visualization")
    st.markdown("---")

    charts_placeholder = st.empty()
    table_placeholder = st.empty()

    # Real-Time Update Loop for Data History
    while True:
        df_history = get_data_history()

        if df_history.empty:
            st.info("No data available in the 'data_logs' path. Ensure your NodeMCU is pushing data.")
            time.sleep(5)
            continue

        # GENERATE A DYNAMIC KEY based on the current time
        dynamic_key_suffix = str(time.time())

        # Update Charts
        with charts_placeholder.container():
            st.subheader("Time Series Data")
            col1, col2 = st.columns(2)

            with col1:
                fig_th = px.line(
                    df_history,
                    y=['Temperature (°C)', 'Humidity (%)'],
                    title="Temperature & Humidity Over Time",
                    height=400
                )
                st.plotly_chart(fig_th, use_container_width=True, key=f'temp_hum_chart_{dynamic_key_suffix}')

            with col2:
                fig_light = px.line(
                    df_history,
                    y='Light Level (Lux)',
                    title="Light Level Over Time",
                    height=400
                )
                st.plotly_chart(fig_light, use_container_width=True, key=f'light_level_chart_{dynamic_key_suffix}')

        # 2. Update Table
        with table_placeholder.container():
            st.subheader("Raw Data Table (Latest 10)")
            latest_10_df = df_history.tail(10).sort_index(ascending=False)
            st.dataframe(latest_10_df, use_container_width=True, key=f'data_table_{dynamic_key_suffix}')

        time.sleep(5)

# 2. Control Page
elif selected == "Control":
    st.title("🕹️ Device Control Interface")
    st.markdown("---")

    control_ref = root_ref.child('controls')


    # Read the current status for display
    def read_current_status():
        """Reads the current status from Firebase."""
        status = root_ref.child('current_status').get()
        if status:
            return status.get('temp', 'N/A'), status.get('humidity', 'N/A')
        return 'N/A', 'N/A'


    # Live Status Display
    st.subheader("Current Climate Status")
    status_placeholder = st.empty()


    # Control Logic Functions
    def set_override(device, value):
        """Pushes the boolean override command to Firebase."""
        try:
            control_ref.child(f'{device}_override').set(value)
            st.toast(f"{device.capitalize()} override set to {value}", icon='✅')
        except Exception as e:
            st.error(f"Failed to send command: {e}")


    def get_current_control_state(device):
        """Reads the current override state for the toggle switch."""
        try:
            state = control_ref.child(f'{device}_override').get()
            return bool(state)
        except:
            return False


    # Control Widgets
    st.subheader("Light Control")
    current_light_state = get_current_control_state('light')

    light_toggle = st.toggle(
        "Light Override (Manual Control)",
        value=current_light_state,
        key='light_override_toggle',
        help="Turn ON to set LED to 255. Turn OFF to set LED to 0."
    )

    if light_toggle != current_light_state:
        set_override('light', light_toggle)
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
        st.rerun()

    # Real-Time Update Loop
    while True:
        temp, humidity = read_current_status()

        with status_placeholder.container():
            col_status_1, col_status_2 = st.columns(2)
            with col_status_1:
                st.metric("Current Temperature", f"{temp}°C")
            with col_status_2:
                st.metric("Current Humidity", f"{humidity}%")

        time.sleep(5)