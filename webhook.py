from flask import Flask, request, jsonify, render_template
import os
import sqlite3
import uuid
from gtts import gTTS

try:
    from google.cloud import dialogflow_v2 as dialogflow
    import vertexai
    from vertexai.generative_models import GenerativeModel
except ImportError:
    dialogflow = None
    vertexai = None
    print("UYARI: Google Cloud kütüphaneleri eksik.")

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, 'sirket_veritabani.db')
KEY_FILE = os.path.join(BASE_DIR, 'google_key.json')
AUDIO_FOLDER = os.path.join(BASE_DIR, 'static')

PROJECT_ID = "yardimci-musteri-jdch"
LOCATION = "us-central1"

if not os.path.exists(AUDIO_FOLDER): os.makedirs(AUDIO_FOLDER)
if os.path.exists(KEY_FILE):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = KEY_FILE
    if vertexai:
        vertexai.init(project=PROJECT_ID, location=LOCATION)


def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def ask_gemini(user_input, data=None):

    if not vertexai: return "Yapay zeka modülü aktif değil."

    model = GenerativeModel("gemini-1.5-flash-001")

    system_prompt = """
    GÖREV: Sen 'Hızlı Kargo' firmasının profesyonel, zeki ve duygusal zekası yüksek müşteri temsilcisisin.

    KURALLAR:
    1. Kullanıcının DUYGUSUNU ANALİZ ET. Eğer kullanıcı kızgınsa veya şikayet ediyorsa, önce empati kur ve özür dile. Eğer mutluysa sen de enerjik ol.
    2. Sana verilen 'Sistem Verisi'ni kullanarak net cevap ver.
    3. Asla yalan söyleme. Veri yoksa "Bilgim yok" de.
    4. Cevabın konuşma diline uygun, doğal ve Türkçe olsun.
    """

    if data:
        prompt = f"""
        {system_prompt}
        ----------------
        Kullanıcı Mesajı: "{user_input}"
        ----------------
        Sistemden Çekilen Veri (Gerçek Bilgi): {data}
        ----------------
        CEVAP (Müşteriye):
        """
    else:
        prompt = f"""
        {system_prompt}
        ----------------
        Kullanıcı Mesajı: "{user_input}"
        ----------------
        Veri Yok. Bu genel bir sohbet veya bilgi sorusu olabilir.
        Bir müşteri temsilcisi gibi doğal cevap ver.
        ----------------
        CEVAP:
        """

    try:
        response = model.generate_content(prompt)
        return response.text.replace('*', '')
    except Exception as e:
        print(f"Gemini Hatası: {e}")
        return "Şu an cevap veremiyorum, sistemsel bir durum var."


def metni_sese_cevir(text):
    filename = f"ses_{uuid.uuid4().hex}.mp3"
    filepath = os.path.join(AUDIO_FOLDER, filename)
    try:
        tts = gTTS(text=text, lang='tr')
        tts.save(filepath)
        return f"/static/{filename}"
    except:
        return None


def detect_intent_texts(project_id, session_id, text):
    if dialogflow is None: return None
    session_client = dialogflow.SessionsClient(transport="rest")
    session = session_client.session_path(project_id, session_id)
    text_input = dialogflow.types.TextInput(text=text, language_code="tr")
    query_input = dialogflow.types.QueryInput(text=text_input)
    return session_client.detect_intent(session=session, query_input=query_input).query_result


def kargo_bilgisi_getir(no):
    conn = get_db_connection()
    try:
        query = """
            SELECT k.takip_no, m.ad_soyad, hc.durum_adi, s.sube_adi 
            FROM kargo_takip k
            JOIN siparisler sip ON k.siparis_no = sip.siparis_no
            JOIN musteriler m ON sip.musteri_id = m.musteri_id
            LEFT JOIN hareket_cesitleri hc ON k.durum_id = hc.id
            LEFT JOIN subeler s ON k.su_anki_sube_id = s.sube_id
            WHERE k.takip_no = ? OR k.siparis_no = ?
        """
        row = conn.execute(query, (no, no)).fetchone()
        if not row: return None
        return f"Müşteri: {row['ad_soyad']}, Durum: {row['durum_adi']}, Konum: {row['sube_adi']}"
    except:
        return None
    finally:
        conn.close()


def fiyat_hesapla(desi, nereye):
    conn = get_db_connection()
    try:
        baz = 35.0
        tutar = baz + (float(desi) * 5.0)
        return f"Desi: {desi}, Bölge: {nereye}, Tahmini Tutar: {tutar} TL"
    except:
        return None
    finally:
        conn.close()

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
        intent_name = ai_result.intent.display_name
        params = ai_result.parameters

        db_data = None

        if intent_name == "Siparis_Sorgulama":
            no = None
            if params.fields.get('siparis_no'):
                val = params.fields['siparis_no']
                no = str(int(val.number_value)) if val.kind == 'number_value' else val.string_value

            if no:
                db_data = kargo_bilgisi_getir(no)
                if not db_data: db_data = "Sistemde bu numaraya ait kayıt bulunamadı."

        elif intent_name == "Fiyat_Sorgulama":
            desi = params.fields.get('desi').number_value if params.fields.get('desi') else 1
            sehir = params.fields.get('sehir').string_value if params.fields.get('sehir') else 'uzak'
            db_data = fiyat_hesapla(desi, sehir)

        final_response = ask_gemini(user_message, db_data)

        audio_url = metni_sese_cevir(final_response)

        return jsonify({"response": final_response, "audio": audio_url})

    except Exception as e:
        print(f"Hata: {e}")
        return jsonify({"response": "Bir hata oluştu.", "audio": None})


if __name__ == '__main__':
    app.run(debug=True)