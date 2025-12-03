from flask import Flask, request, jsonify, render_template
import os
import sqlite3
import uuid

try:
    from google.cloud import dialogflow_v2 as dialogflow
    from google.protobuf.struct_pb2 import Struct
except ImportError:
    dialogflow = None
    print("UYARI: 'google-cloud-dialogflow' kütüphanesi bulunamadı.")

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, 'sirket_veritabani.db')
KEY_FILE = os.path.join(BASE_DIR, 'google_key.json')

if os.path.exists(KEY_FILE):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = KEY_FILE
else:
    print(f"KRİTİK UYARI: {KEY_FILE} dosyası bulunamadı!")

PROJECT_ID = "yardimci-musteri-jdch"

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


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

        return {
            "ad_soyad": row['ad_soyad'],
            "durum": row['durum_adi'],
            "sube": row['sube_adi'] if row['sube_adi'] else "Merkez",
            "kargo_no": str(row['takip_no'])
        }
    except:
        return None
    finally:
        conn.close()


def fiyat_hesapla(desi, nereye):
    conn = get_db_connection()
    try:
        # 1. Veritabanındaki parametreleri çek (baz_ucret, desi_birim_ucret, carpanlar)
        cursor = conn.execute("SELECT parametre_adi, deger FROM fiyat_parametreleri")
        # Gelen veriyi sözlüğe çevir: {'baz_ucret': 35.0, 'desi_birim_ucret': 8.5, ...}
        p = {row['parametre_adi']: row['deger'] for row in cursor.fetchall()}

        # Değerleri al (Veritabanında yoksa varsayılan 0 almasın diye güvenli get kullanıyoruz)
        baz_ucret = p.get('baz_ucret', 35.0)
        birim_ucret = p.get('desi_birim_ucret', 8.5)

        # 2. Çarpanı belirle (Kullanıcının girdiği şehre göre)
        nereye = nereye.lower()
        carpan = 1.0  # Varsayılan

        if 'istanbul' in nereye or 'içi' in nereye:
            carpan = p.get('carpan_sehir_ici', 1.0)
        elif 'ankara' in nereye or 'izmir' in nereye or 'yakın' in nereye:
            carpan = p.get('carpan_yakin_sehir', 1.5)
        else:
            # Diğer tüm şehirler uzak kabul edilir
            carpan = p.get('carpan_uzak_sehir', 2.2)

        # 3. Hesaplama İşlemi
        tutar = (baz_ucret + (float(desi) * birim_ucret)) * carpan

        return {
            "tutar": f"{tutar:.2f}",
            "desi": str(desi),
            "sehir": nereye
        }
    except Exception as e:
        print(f"Hesaplama Hatası: {e}")
        return None
    finally:
        conn.close()


def trigger_dialogflow_event(project_id, session_id, event_name, parameters):
    if dialogflow is None: return None

    session_client = dialogflow.SessionsClient(transport="rest")
    session = session_client.session_path(project_id, session_id)

    event_input = dialogflow.types.EventInput(name=event_name, parameters=parameters, language_code="tr")
    query_input = dialogflow.types.QueryInput(event=event_input)

    response = session_client.detect_intent(session=session, query_input=query_input)
    return response.query_result.fulfillment_text


def detect_intent_texts(project_id, session_id, text):
    if dialogflow is None: return None

    session_client = dialogflow.SessionsClient(transport="rest")
    session = session_client.session_path(project_id, session_id)

    text_input = dialogflow.types.TextInput(text=text, language_code="tr")
    query_input = dialogflow.types.QueryInput(text=text_input)

    response = session_client.detect_intent(session=session, query_input=query_input)
    return response.query_result


@app.route('/')
def ana_sayfa():
    return render_template('index.html')


@app.route('/api/chat', methods=['POST'])
def chat_api():
    data = request.get_json()
    user_message = data.get('message', '')

    if dialogflow is None:
        return jsonify({"response": "Hata: Kütüphane eksik."})

    session_id = str(uuid.uuid4())

    try:
        ai_result = detect_intent_texts(PROJECT_ID, session_id, user_message)

        if not ai_result:
            return jsonify({"response": "Yapay zeka servisine bağlanılamadı."})

        intent_name = ai_result.intent.display_name
        params = ai_result.parameters

        final_response = ai_result.fulfillment_text

        if intent_name == "Siparis_Sorgulama":
            no = None
            if params and 'siparis_no' in params.fields:
                val = params.fields['siparis_no']
                if val.kind == 'number_value':
                    no = str(int(val.number_value))
                elif val.kind == 'string_value':
                    no = val.string_value

            if no:
                db_data = kargo_bilgisi_getir(no)
                if db_data:
                    final_response = trigger_dialogflow_event(PROJECT_ID, session_id, "KARGO_BULUNDU", db_data)
                else:
                    final_response = trigger_dialogflow_event(PROJECT_ID, session_id, "KARGO_BULUNAMADI", {})

        elif intent_name == "Fiyat_Sorgulama":
            desi = 1
            sehir = 'uzak'

            if params and 'desi' in params.fields:
                val = params.fields['desi']
                if val.kind == 'number_value': desi = val.number_value

            if params and 'sehir' in params.fields:
                sehir = params.fields['sehir'].string_value

            db_data = fiyat_hesapla(desi, sehir)

            if db_data:
                final_response = trigger_dialogflow_event(PROJECT_ID, session_id, "FIYAT_HESAPLANDI", db_data)

        return jsonify({"response": final_response})

    except Exception as e:
        print(f"Hata: {e}")
        return jsonify({"response": "Bir hata oluştu."})


if __name__ == '__main__':
    app.run(debug=True)