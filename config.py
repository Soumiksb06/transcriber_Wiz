# config.py
import os
import streamlit as st

def setup_fal_api() -> str:
    """
    Set up FAL API key from Streamlit secrets if available, otherwise prompt the user.
    """
    if 'FAL_KEY' in st.secrets and st.secrets['FAL_KEY']:
        fal_key = st.secrets['FAL_KEY']
        os.environ['FAL_KEY'] = fal_key
    else:
        fal_key = st.text_input("Enter your FAL API key:", type="password")
        if fal_key:
            os.environ['FAL_KEY'] = fal_key
        else:
            st.error("FAL API key is required to proceed.")
            st.stop()
    return fal_key
