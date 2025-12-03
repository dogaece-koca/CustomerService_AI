from flask import Flask, request, jsonify, render_template
import os
import sqlite3
from google.cloud import dialogflow_v2 as dialogflow
import uuid

app = Flask(__name__)


DB_FILE = os.path.join(os.path.dirname(__file__), 'sirket_veritabani.db')

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/home/dogaecekoca/CustomerService_AI/google_key.json"

PROJECT_ID = "yardimci-musteri-jdch"


def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


# --- VERİTABANI FONKSİYONLARI ---
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


# --- YAPAY ZEKA ENTEGRASYONU ---
def detect_intent_texts(project_id, session_id, text, language_code):
    """Dialogflow API'ye metin gönderip cevabı alır."""
    session_client = dialogflow.SessionsClient()
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

    # Her kullanıcı için rastgele bir oturum ID (Basitlik için)
    # Gerçek uygulamada cookie veya localstorage'dan gelir
    session_id = str(uuid.uuid4())

    try:
        # 1. Dialogflow'a Sor (YAPAY ZEKA ADIMI)
        ai_result = detect_intent_texts(PROJECT_ID, session_id, user_message, "tr")

        intent_name = ai_result.intent.display_name
        bot_reply = ai_result.fulfillment_text  # Dialogflow'un statik cevabı
        params = ai_result.parameters

        # 2. Eğer veritabanı gerekiyorsa Python devreye girer
        if intent_name == "Siparis_Sorgulama":
            no = params.fields.get('siparis_no').string_value  # veya .number_value
            # Parametre boşsa Dialogflow zaten "Numaranız nedir?" diye sormuştur (slot filling)
            # Eğer parametre geldiyse veritabanına soruyoruz:
            if no:
                bot_reply = kargo_bilgisi_getir(str(int(float(no)))) if no.replace('.', '',
                                                                                   1).isdigit() else kargo_bilgisi_getir(
                    no)

        elif intent_name == "Fiyat_Sorgulama":
            desi = params.fields.get('desi').number_value
            sehir = params.fields.get('sehir').string_value

            # Parametreler tamamsa hesapla
            if desi and sehir:
                bot_reply = fiyat_hesapla(desi, sehir)

        # 3. Sonucu Dön
        return jsonify({"response": bot_reply})

    except Exception as e:
        print(f"Hata: {e}")
        return jsonify({"response": "Yapay zeka bağlantısında bir sorun oluştu."})


if __name__ == '__main__':
    app.run(debug=True)