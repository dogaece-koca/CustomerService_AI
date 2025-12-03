from flask import Flask, request, jsonify, render_template
import os
import sqlite3
import uuid

# --- GÜVENLİ IMPORT ---
try:
    from google.cloud import dialogflow_v2 as dialogflow
except ImportError:
    dialogflow = None
    print("UYARI: 'google-cloud-dialogflow' kütüphanesi bulunamadı.")

app = Flask(__name__)

# --- AYARLAR ---
# Veritabanı ve Anahtar Yolları
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, 'sirket_veritabani.db')
KEY_FILE = os.path.join(BASE_DIR, 'google_key.json')

# Google Cloud Kimlik Doğrulama
if os.path.exists(KEY_FILE):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = KEY_FILE
else:
    print(f"KRİTİK UYARI: {KEY_FILE} dosyası bulunamadı!")

# *** PROJE ID (Testte çalışan ID buraya) ***
PROJECT_ID = "yardimci-musteri-jdch"


# --- VERİTABANI YARDIMCISI ---
def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


# --- İŞ MANTIĞI (Kargo & Fiyat) ---
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
        if not row: return "Bu numaraya ait sipariş bulamadım."

        cevap = f"Sayın {row['ad_soyad']}, kargonuz: {row['durum_adi']}."
        if row['sube_adi']: cevap += f" ({row['sube_adi']})"
        return cevap
    except:
        return "Veritabanı hatası."
    finally:
        conn.close()


def fiyat_hesapla(desi, nereye):
    conn = get_db_connection()
    try:
        params = conn.execute("SELECT parametre_adi, deger FROM fiyat_parametreleri").fetchall()
        p = {row['parametre_adi']: row['deger'] for row in params}

        baz = p.get('baz_ucret', 30.0)
        birim = p.get('desi_birim_ucret', 5.0)
        carpan = 1.0

        if 'istanbul' in nereye.lower():
            carpan = p.get('carpan_sehir_ici', 1.0)
        elif 'ankara' in nereye.lower():
            carpan = p.get('carpan_yakin_sehir', 1.5)
        else:
            carpan = p.get('carpan_uzak_sehir', 2.2)

        tutar = (baz + (float(desi) * birim)) * carpan
        return f"{desi} desi, {nereye} için tutar: {tutar:.2f} TL"
    except:
        return "Fiyat hesabı için desi giriniz."
    finally:
        conn.close()


# --- YAPAY ZEKA (REST MODU İLE) ---
def detect_intent_texts(project_id, session_id, text, language_code):
    """Dialogflow API'ye bağlanır (REST transport kullanarak donmayı engeller)."""
    if dialogflow is None: return None

    # !!! KRİTİK AYAR: transport="rest" !!!
    # PythonAnywhere ücretsiz sürümünde bu olmadan kod DONAR.
    session_client = dialogflow.SessionsClient(transport="rest")

    session = session_client.session_path(project_id, session_id)
    text_input = dialogflow.types.TextInput(text=text, language_code=language_code)
    query_input = dialogflow.types.QueryInput(text=text_input)

    response = session_client.detect_intent(session=session, query_input=query_input)
    return response.query_result


# --- ROUTES ---

@app.route('/')
def ana_sayfa():
    return render_template('index.html')


@app.route('/api/chat', methods=['POST'])
def chat_api():
    data = request.get_json()
    user_message = data.get('message', '')

    # Kütüphane kontrolü
    if dialogflow is None:
        return jsonify({"response": "Hata: google-cloud-dialogflow yüklü değil."})

    # Her kullanıcıya unique session ID
    session_id = str(uuid.uuid4())

    try:
        # 1. Dialogflow'a Sor
        ai_result = detect_intent_texts(PROJECT_ID, session_id, user_message, "tr")

        if not ai_result:
            return jsonify({"response": "Yapay zeka servisine bağlanılamadı."})

        intent_name = ai_result.intent.display_name
        bot_reply = ai_result.fulfillment_text
        params = ai_result.parameters

        # 2. Veritabanı İşlemleri (Fulfillment)
        if intent_name == "Siparis_Sorgulama":
            # Parametreleri güvenli şekilde al
            no = None
            if params and 'siparis_no' in params.fields:
                val = params.fields['siparis_no']
                # Dialogflow bazen number bazen string döner, ikisini de kontrol et
                if val.kind == 'number_value':
                    no = str(int(val.number_value))
                elif val.kind == 'string_value':
                    no = val.string_value

            if no:
                bot_reply = kargo_bilgisi_getir(no)

        elif intent_name == "Fiyat_Sorgulama":
            desi = 1
            sehir = 'uzak'

            if params and 'desi' in params.fields:
                val = params.fields['desi']
                if val.kind == 'number_value': desi = val.number_value

            if params and 'sehir' in params.fields:
                sehir = params.fields['sehir'].string_value

            bot_reply = fiyat_hesapla(desi, sehir)

        return jsonify({"response": bot_reply})

    except Exception as e:
        print(f"Hata Detayı: {e}")
        return jsonify({"response": f"Bir hata oluştu. Lütfen tekrar deneyin."})


if __name__ == '__main__':
    app.run(debug=True)