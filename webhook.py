from flask import Flask, request, jsonify, render_template
import os
import sqlite3
import uuid
from gtts import gTTS

try:
    from google.cloud import dialogflow_v2 as dialogflow
except ImportError:
    dialogflow = None

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, 'sirket_veritabani.db')
KEY_FILE = os.path.join(BASE_DIR, 'google_key.json')
AUDIO_FOLDER = os.path.join(BASE_DIR, 'static')

if not os.path.exists(AUDIO_FOLDER): os.makedirs(AUDIO_FOLDER)
if os.path.exists(KEY_FILE): os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = KEY_FILE

PROJECT_ID = "yardimci-musteri-jdch"

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def metni_sese_cevir(text):
    try:
        tts = gTTS(text=text, lang='tr')
        filename = f"ses_{uuid.uuid4().hex}.mp3"
        filepath = os.path.join(AUDIO_FOLDER, filename)
        tts.save(filepath)
        return f"/static/{filename}"
    except:
        return None


def detect_intent_texts(project_id, session_id, text):
    if dialogflow is None: return None
    session_client = dialogflow.SessionsClient(transport="rest")  # REST ÖNEMLİ
    session = session_client.session_path(project_id, session_id)
    text_input = dialogflow.types.TextInput(text=text, language_code="tr")
    query_input = dialogflow.types.QueryInput(text=text_input)
    return session_client.detect_intent(session=session, query_input=query_input).query_result


@app.route('/')
def ana_sayfa():
    return render_template('index.html')


@app.route('/api/chat', methods=['POST'])
def chat_api():
    data = request.get_json()
    user_message = data.get('message', '')
    session_id = str(uuid.uuid4())

    try:
        ai_result = detect_intent_texts(PROJECT_ID, session_id, user_message)
        bot_reply = ai_result.fulfillment_text

        # (Burada veritabanı işlemleri - if intent == siparis vs. - olmalı)

        audio_url = metni_sese_cevir(bot_reply)

        return jsonify({"response": bot_reply, "audio": audio_url})

    except Exception as e:
        return jsonify({"response": "Hata oluştu.", "audio": None})


if __name__ == '__main__':
    app.run(debug=True)