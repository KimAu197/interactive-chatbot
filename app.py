import logging
import os
import streamlit as st
from dotenv import load_dotenv
import agent

load_dotenv()

# Configure logging once at startup (Streamlit reruns the script, so guard with the root logger's handlers)
_root_logger = logging.getLogger()
if not _root_logger.handlers:
    _fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    _file_handler = logging.FileHandler("app.log", encoding="utf-8")
    _file_handler.setLevel(logging.DEBUG)
    _file_handler.setFormatter(_fmt)
    _console_handler = logging.StreamHandler()
    _console_handler.setLevel(logging.INFO)
    _console_handler.setFormatter(_fmt)
    _root_logger.setLevel(logging.DEBUG)
    _root_logger.addHandler(_file_handler)
    _root_logger.addHandler(_console_handler)

st.set_page_config(
    page_title="Cal.com Scheduling Assistant",
    page_icon="📅",
    layout="centered",
)

st.title("Cal.com Scheduling Assistant")
st.caption("Book, view, cancel, or reschedule meetings via natural language.")

OPENAI_KEY_SET = bool(os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_API_KEY") != "your_openai_api_key_here")
if not OPENAI_KEY_SET:
    st.error("OpenAI API key is not configured. Please set OPENAI_API_KEY in your .env file.")
    st.stop()

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if not st.session_state.messages:
    with st.chat_message("assistant"):
        welcome = (
            "Hello! I'm your scheduling assistant. I can help you:\n\n"
            "- **Book** a new meeting (15 or 30 minutes)\n"
            "- **View** your scheduled meetings\n"
            "- **Cancel** a meeting\n"
            "- **Reschedule** a meeting\n\n"
            "What would you like to do?"
        )
        st.markdown(welcome)

if prompt := st.chat_input("Type your message..."):
    with st.chat_message("user"):
        st.markdown(prompt)

    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                reply, updated_messages = agent.run_agent(list(st.session_state.messages))
                st.session_state.messages = updated_messages
                st.markdown(reply)
            except Exception as e:
                error_msg = f"An error occurred: {e}"
                st.error(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})
