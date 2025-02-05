# logger.py
import streamlit as st

class Logger:
    def __init__(self):
        # Initialize log text in session state if not already set.
        if 'log_text' not in st.session_state:
            st.session_state.log_text = ""
        self.log_text = st.session_state.log_text

    def log(self, msg: str) -> None:
        self.log_text += msg + "\n"
        st.session_state.log_text = self.log_text

    def get_log(self) -> str:
        return self.log_text
