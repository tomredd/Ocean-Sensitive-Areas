import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
import h3
import numpy as np
from odp.client import OdpClient

st.title("AIS Data Analyzer")

# Authentication
CLIENT_ID = st.sidebar.text_input("Client ID", "tom.redd@oceandata.earth:OSA")
CLIENT_SECRET = st.sidebar.text_input("Client Secret", "qwerty12345!", type="password")

AUTH_URL = "https://id.barentswatch.no/connect/token"

auth_data = {
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "grant_type": "client_credentials",
    "scope": "ais"
}

@st.cache_data
def get_access_token():
    response = requests.post(AUTH_URL, data=auth_data)
    if response.status_code == 200:
        return response.json()["access_token"]
    else:
        st.error(f"Authentication Error: {response.status_code} - {response.text}")
        return None

token = get_access_token()

if token:
    # User input for MMSI numbers
    mmsi_input = st.text_area("Enter MMSI numbers (one per line):")
    mmsi_list = [int(mmsi.strip()) for mmsi in mmsi_input.split("\n") if mmsi.strip()]

    if st.button("Generate Reports"):
        for mmsi in mmsi_list:
            st.subheader(f"Report for MMSI: {mmsi}")

            now = datetime.utcnow()
            seven_days_ago = now - timedelta(days=7)
            from_date = seven_days_ago.strftime("%Y-%m-%dT%H:%M:%SZ")
            to_date = now.strftime("%Y-%m-%dT%H:%M:%SZ")

            API_URL = f"https://historic.ais.barentswatch.no/v1/historic/tracks/{mmsi}/{from_date}/{to_date}"
            headers = {"Authorization": f"Bearer {token}"}

            response = requests.get(API_URL, headers=headers)

            if response.status_code == 200:
                ais_data = response.json()
                df = pd.json_normalize(ais_data)

                st.write(f"Number of data points: {len(df)}")

                if not df.empty:
                    st.write("Latest position:")
                    latest = df.iloc[0]
                    st.write(f"Latitude: {latest['latitude']}, Longitude: {latest['longitude']}")
                    st.write(f"Time: {latest['msgtime']}")
                    st.write(f"Speed: {latest['speedOverGround']} knots")
                    st.write(f"Course: {latest['courseOverGround']}°")

                    st.write("Movement summary:")
                    total_distance = df['speedOverGround'].sum() * 1852 / 3600  # Convert knots to meters
                    st.write(f"Total distance traveled: {total_distance:.2f} meters")
                    
                    avg_speed = df['speedOverGround'].mean()
                    st.write(f"Average speed: {avg_speed:.2f} knots")

                    st.write("Position plot:")
                    st.map(df[['latitude', 'longitude']])
                else:
                    st.write("No data available for this MMSI in the given time range.")
            else:
                st.error(f"Error fetching data: {response.status_code} - {response.text}")

    st.sidebar.info("This app fetches AIS data for the past 7 days for each MMSI number provided.")
else:
    st.error("Please provide valid authentication credentials.")

