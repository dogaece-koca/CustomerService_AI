from flask import Flask, request, jsonify, render_template
import os
import sqlite3
import uuid
from gtts import gTTS
from dotenv import load_dotenv

# --- GÜVENLİ IMPORTLAR ---
try:
    from google.cloud import dialogflow_v2 as dialogflow
    import google.generativeai as genai
except ImportError:
    dialogflow = None
    genai = None
    print("UYARI: Kütüphaneler eksik.")

app = Flask(__name__)

# --- AYARLAR ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, 'sirket_veritabani.db')
KEY_FILE = os.path.join(BASE_DIR, 'google_key.json')
AUDIO_FOLDER = os.path.join(BASE_DIR, 'static')
ENV_FILE = os.path.join(BASE_DIR, '.env')

load_dotenv(ENV_FILE)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

PROJECT_ID = "yardimci-musteri-jdch"
if os.path.exists(KEY_FILE): os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = KEY_FILE

if genai and GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"Gemini Config Hatası: {e}")

if not os.path.exists(AUDIO_FOLDER): os.makedirs(AUDIO_FOLDER)

# Hafıza (Hata Sayacı)
user_sessions = {}


def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


# --- 1. GEMINI AI ---
def ask_gemini(user_input, context_data=None, is_error=False):
    if not GEMINI_API_KEY or not genai: return "Sistemsel hata (AI Kapalı)."

    try:
        model = genai.GenerativeModel('gemini-2.5-flash')

        system_prompt = """
        GÖREV: Sen 'Hızlı Kargo' firmasının yardımsever, profesyonel müşteri temsilcisisin.
        KİMLİK: Sen bir SESLİ ASİSTANSIN. Kullanıcı seninle konuşarak iletişim kuruyor.
        TON: Nazik, çözüm odaklı ve doğal Türkçe konuş. Robotik olma.
        KURAL: Cevaplarında asla "yazın", "girin" gibi ifadeler kullanma. "Söyleyin", "Belirtin" de.
        """

        if is_error:
            prompt = f"""
            {system_prompt}
            DURUM: Kullanıcı işlem yapmaya çalıştı (Örn: Kargo sorgulama) ama verisi hatalıydı.
            SİSTEM UYARISI: {context_data}
            GÖREVİN: Kullanıcıya durumu nazikçe açıkla. "{user_input}" mesajını yok say.
            Ona numarasını kontrol edip tekrar SÖYLEMESİNİ rica et.
            """
        elif context_data:
            prompt = f"{system_prompt}\nKullanıcı Mesajı: \"{user_input}\"\nSistem Bilgisi: {context_data}\nCevap:"
        else:
            prompt = f"{system_prompt}\nKullanıcı: \"{user_input}\"\nGenel sohbet et."

        response = model.generate_content(prompt)
        return response.text.replace('*', '')
    except Exception as e:
        return f"Üzgünüm, şu an cevap üretemiyorum. ({str(e)})"


# --- 2. SES OLUŞTURMA ---
def metni_sese_cevir(text):
    filename = f"ses_{uuid.uuid4().hex}.mp3"
    filepath = os.path.join(AUDIO_FOLDER, filename)
    try:
        tts = gTTS(text=text, lang='tr')
        tts.save(filepath)
        return f"/static/{filename}"
    except:
        return None


# --- 3. DIALOGFLOW ---
def detect_intent_texts(project_id, session_id, text):
    if dialogflow is None: return None
    try:
        session_client = dialogflow.SessionsClient(transport="rest")
        session = session_client.session_path(project_id, session_id)
        text_input = dialogflow.types.TextInput(text=text, language_code="tr")
        query_input = dialogflow.types.QueryInput(text=text_input)
        return session_client.detect_intent(session=session, query_input=query_input).query_result
    except:
        return None


# --- 4. DB FONKSİYONLARI ---
def kargo_bilgisi_getir(no):
    # Gelen no içindeki boşlukları temizle (Örn: "1 2 3" -> "123")
    clean_no = str(no).replace(" ", "").strip()

    conn = get_db_connection()
    try:
        query = "SELECT durum_adi FROM kargo_takip JOIN hareket_cesitleri ON durum_id = id WHERE takip_no = ? OR siparis_no = ?"
        row = conn.execute(query, (clean_no, clean_no)).fetchone()
        return f"Kargo Durumu: {row['durum_adi']}" if row else None
    except:
        return None
    finally:
        conn.close()


def fiyat_hesapla(desi, nereye):
    return f"{desi} desi, {nereye} için fiyat hesaplandı."


# --- ROUTES ---
@app.route('/')
def ana_sayfa():
    return render_template('index.html')


@app.route('/api/chat', methods=['POST'])
def chat_api():
    data = request.get_json()
    user_message = data.get('message', '').strip()
    session_id = data.get('session_id', str(uuid.uuid4()))

    # Hafıza başlat
    if session_id not in user_sessions:
        user_sessions[session_id] = {'fail_count': 0, 'last_siparis_no': None}

    try:
        # --- YENİ EKLENEN TEMİZLİK MANTIĞI ---
        # Kullanıcı "1 2 3" dediyse bunu "123" yapıp sayı mı diye bakalım.
        cleaned_message = user_message.replace(" ", "")

        # --- STRATEJİ 1: DİREKT SAYI KONTROLÜ (Boşluksuz Haliyle) ---
        if cleaned_message.isdigit():
            no = cleaned_message  # Temizlenmiş (boşluksuz) halini kullan
            db_data = kargo_bilgisi_getir(no)

            # Hafızaya da temiz halini at
            user_sessions[session_id]['last_siparis_no'] = no

            if db_data:
                final_response = ask_gemini(user_message, db_data, is_error=False)
                user_sessions[session_id]['fail_count'] = 0
            else:
                hata_mesaji = f"'{no}' numaralı bir sipariş kaydı bulunamadı."
                final_response = ask_gemini(user_message, hata_mesaji, is_error=True)

            audio_url = metni_sese_cevir(final_response)
            return jsonify({"response": final_response, "audio": audio_url})

        # --- STRATEJİ 2: SOHBET KONTROLÜ (Dialogflow) ---
        ai_result = detect_intent_texts(PROJECT_ID, session_id, user_message)

        intent_name = None
        params = None
        dialogflow_answer = None

        if ai_result:
            intent_name = ai_result.intent.display_name
            params = ai_result.parameters
            dialogflow_answer = ai_result.fulfillment_text

        db_data = None
        gemini_note = None

        if intent_name == "Siparis_Sorgulama":
            no = None
            if params and 'siparis_no' in params.fields:
                val = params.fields['siparis_no']
                if val.kind == 'number_value':
                    no = str(int(val.number_value))
                elif val.kind == 'string_value' and val.string_value:
                    # Gelen string'in boşluklarını sil
                    no = val.string_value.replace(" ", "")

            # Mesajda yoksa HAFIZADAN çek
            if not no:
                no = user_sessions[session_id].get('last_siparis_no')

            if no:
                user_sessions[session_id]['last_siparis_no'] = no
                db_data = kargo_bilgisi_getir(no)

                if db_data:
                    user_sessions[session_id]['fail_count'] = 0
                else:
                    current_fails = user_sessions[session_id]['fail_count'] + 1
                    user_sessions[session_id]['fail_count'] = current_fails
                    if current_fails >= 3:
                        gemini_note = "Kullanıcı 3 kez hatalı girdi. SMS/E-posta kontrol etmesini söyle."
                        user_sessions[session_id]['fail_count'] = 0
                    else:
                        gemini_note = f"Kullanıcı '{no}' numarasını sordu ama veritabanında yok."

        elif intent_name == "Fiyat_Sorgulama":
            desi = params.fields.get('desi').number_value if params and params.fields.get('desi') else 1
            sehir = params.fields.get('sehir').string_value if params and params.fields.get('sehir') else 'uzak'
            db_data = fiyat_hesapla(desi, sehir)

        # --- CEVAP OLUŞTURMA ---
        if gemini_note:
            final_response = ask_gemini(user_message, gemini_note, is_error=True)
        elif db_data:
            final_response = ask_gemini(user_message, db_data, is_error=False)
        elif dialogflow_answer:
            final_response = dialogflow_answer
        else:
            final_response = ask_gemini(user_message, None, is_error=False)

        audio_url = metni_sese_cevir(final_response)

        return jsonify({"response": final_response, "audio": audio_url})

    except Exception as e:
        print(f"Hata: {e}")
        return jsonify({"response": "Bir hata oluştu.", "audio": None})


if __name__ == '__main__':
    app.run(debug=True)