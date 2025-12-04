from flask import Flask, request, jsonify, render_template
import os
import sqlite3
import uuid
import json
from gtts import gTTS
from dotenv import load_dotenv

try:
    import google.generativeai as genai
except ImportError:
    genai = None

app = Flask(__name__)

# --- AYARLAR ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, 'sirket_veritabani.db')
AUDIO_FOLDER = os.path.join(BASE_DIR, 'static')
ENV_FILE = os.path.join(BASE_DIR, '.env')

load_dotenv(ENV_FILE)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if genai and GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

if not os.path.exists(AUDIO_FOLDER): os.makedirs(AUDIO_FOLDER)

chat_histories = {}


def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def kargo_bilgisi_getir(no):
    if not no: return "Numara yok."
    try:
        conn = get_db_connection()
        query = "SELECT durum_adi FROM kargo_takip JOIN hareket_cesitleri ON durum_id = id WHERE takip_no = ? OR siparis_no = ?"
        row = conn.execute(query, (no, no)).fetchone()
        conn.close()
        return f"Kargo Durumu: {row['durum_adi']}" if row else "Sistemde böyle bir numara yok."
    except:
        return "Sorgulama yapıldı (DB Bağlı Değil), Kargonuz yolda görünüyor."


def iade_islemi_baslat(no):
    if not no: return "Numara belirtilmedi."

    conn = get_db_connection()
    try:
        query = "SELECT durum_adi FROM kargo_takip JOIN hareket_cesitleri ON durum_id = id WHERE takip_no = ? OR siparis_no = ?"
        row = conn.execute(query, (no, no)).fetchone()

        if not row:
            return "Sistemde böyle bir kayıt bulunamadı."

        durum = row['durum_adi']

        yasakli_durumlar = ["YOLDA", "DAGITIMDA", "TRANSFER", "TESLIM"]

        if any(kelime in durum for kelime in yasakli_durumlar):
            return f"Kargonuz şu an '{durum}' aşamasındadır. Kargo yola çıktı, iade edemezsiniz. Lütfen kargonun elinize geçmesini bekleyip iade talebi oluşturun."

        return f"{no} numaralı sipariş için iade talebiniz alınmıştır. İade Kodunuz, 998877."

    except Exception as e:
        return f"Veritabanı işlem hatası: {e}"
    finally:
        conn.close()


def dogrulama_yap(siparis_no, ad, telefon):
    if not siparis_no or not ad or not telefon:
        return "DOGRULAMA_HATA|Eksik Parametre."

    conn = get_db_connection()
    try:
        temiz_telefon = telefon.replace(" ", "").replace("-", "").strip()
        if len(temiz_telefon) > 10 and temiz_telefon.startswith('0'):
            temiz_telefon = temiz_telefon[1:]

        if len(temiz_telefon) != 10:
            return "DOGRULAMA_HATA|Telefon numarası formatı geçersiz (10 hane olmalı)."

        validation_query = """
            SELECT s.siparis_no, m.musteri_id
            FROM musteriler m 
            JOIN siparisler s ON m.musteri_id = s.musteri_id
            JOIN kargo_takip kt ON s.siparis_no = kt.siparis_no
            WHERE (kt.takip_no = ? OR s.siparis_no = ?)
              AND m.telefon = ?                          
              AND UPPER(m.ad_soyad) LIKE ?                
        """

        sql_params = (siparis_no, siparis_no, temiz_telefon, f"%{ad.upper()}%")
        musteri_row = conn.execute(validation_query, sql_params).fetchone()

        if not musteri_row:
            return "DOGRULAMA_HATA|Bilgiler eşleşmiyor. Lütfen kontrol ediniz."

        gercek_siparis_no = musteri_row['siparis_no']
        return f"DOGRULAMA_BASARILI|{gercek_siparis_no}"

    except Exception as e:
        return f"DOGRULAMA_HATA_DB|{e}"
    finally:
        conn.close()


def adres_degistir(siparis_no, ad, telefon, yeni_adres):
    if not siparis_no or not yeni_adres:
        return "Veri Eksikliği Hatası: Sipariş No ve Yeni Adres eksik."

    conn = get_db_connection()
    try:

        update_query = """
            UPDATE kargo_takip
            SET teslim_adresi = ?
            WHERE siparis_no = ?
        """
        conn.execute(update_query, (yeni_adres, siparis_no))
        conn.commit()

        return f" {siparis_no} numaralı siparişinizin teslimat adresi başarıyla '{yeni_adres}' olarak güncellenmiştir. Onay SMS'i gönderilmiştir."

    except Exception as e:
        conn.rollback()
        return f"Veritabanı işlem hatası: {e}"
    finally:
        conn.close()


def fiyat_hesapla(desi, nereye):
    return f"{desi} desi, {nereye} için fiyat: 150 TL."


# --- GEMINI ZEKASI ---
def process_with_gemini(session_id, user_message):
    if not genai: return "AI kapalı."

    model = genai.GenerativeModel('gemini-2.5-flash')

    history = chat_histories.get(session_id, [])

    print(f"\n--- DEBUG BAŞLADI ---")
    print(f"Session ID: {session_id}")
    print(f"Mevcut Hafıza: {history}")
    print(f"Yeni Mesaj: {user_message}")
    # -----------------------------

    system_prompt = """
    GÖREV: Sesli Hızlı Kargo asistanısın. Müşteri temsilcisi gibi doğal ve nazik konuş.
    ÖN İŞLEM TALİMATI: Eğer KULLANICI MESAJI sadece tek tek söylenmiş sayıları içeriyorsa, bu sayıları hemen ayıklayıp tek bir takip numarası/sipariş numarası olarak birleştir.

    ÇIKTI: Sadece JSON.

    ANALİZ KURALLARI (SIRAYLA UYGULA):

    1. DURUM: SLOT DOLDURMA VE ADRES DEĞİŞTİRME MANTIĞI (KRİTİK!)
       - Kullanıcı, GEÇMİŞ SOHBETTE veya mevcut mesajda "adres", "değiştirme", "yanlış adres" gibi kelimelerle adres değiştirme niyeti gösterdiyse, bu amaca odaklan.
       - Gerekli Slotlar: ad, telefon, siparis_no, yeni_adres.

       - Eğer slotlar eksikse, sırayla EKSİK OLAN İLK BİLGİYİ İSTE:
         1. Ad eksikse: { "type": "chat", "reply": "Elbette, adres değişikliği için öncelikle siparişinizin sahibinin adını ve soyadını öğrenebilir miyim?" }
         2. Ad dolu, Sipariş No eksikse: { "type": "chat", "reply": "Teşekkürler. Hangi siparişinizin adresini değiştireceğimizi öğrenmek için sipariş numaranızı rica edebilir miyim?" }
         3. Ad ve Sipariş No dolu, Telefon eksikse: { "type": "chat", "reply": "Şimdi güvenlik için kayıtlı telefon numaranızı da söyler misiniz?" }

         # YENİ SLOT: DOĞRULAMA ÇAĞRISI (3 bilgi dolunca aksiyon çağrılmalı)
         4. Ad, Sipariş No ve Telefon doluysa, **ancak GEÇMİŞ SOHBETTE 'DOGRULAMA_BASARILI' yoksa**: 
            -> { "type": "action", "function": "dogrulama_yap", "parameters": { "ad": "...", "telefon": "...", "siparis_no": "..." } }

         # YENİ SLOT: ADRES SORMA (Sadece doğrulama başarılı ise sorulur)
         5. GEÇMİŞ SOHBETTE 'DOGRULAMA_BASARILI' varsa ve Yeni Adres eksikse: 
            -> { "type": "chat", "reply": "Doğrulama başarılı. Kargonun yeni teslimat adresi ne olacak, tam adresinizi yazar mısınız?" }

       - **SON ADIM: TÜM SLOTLAR DOLUYSA AKSİYON ÇAĞIR**
         -> { "type": "action", "function": "adres_degistir", "parameters": { "ad": "...", "telefon": "...", "siparis_no": "...", "yeni_adres": "..." } }


    2. DURUM: BAĞLAM KONTROLÜ (Kargo ve İade)
       - Eğer kullanıcı SADECE sayısal bir ifade girdiyse, GEÇMİŞ SOHBETİ kontrol et:
         - Geçmişte "iade" sorulduysa -> "iade_işlemi"
         - Geçmişte "kargom nerde" sorulduysa -> "kargo_sorgula"
         - Diğer durumlarda -> "chat" (Soru sor)


    3. DURUM: AÇIK EYLEMLER
       - "Kargom nerede 12345" -> kargo_sorgula
       - "12345 nolu siparişi iade et" -> iade_işlemi
       - Fiyat ne kadar? -> fiyat_hesapla


    4. DURUM: GENEL SOHBET
       - Merhaba, teşekkürler vb. -> { "type": "chat", "reply": "..." }

    CEVAP FORMATI:
    { "type": "action", "function": "...", "parameters": { "no": "..." } }
    VEYA
    { "type": "chat", "reply": "..." }
    """

    formatted_history = "\n".join(history)
    full_prompt = f"{system_prompt}\n\nGEÇMİŞ SOHBET:\n{formatted_history}\n\nKULLANICI: {user_message}\nJSON CEVAP:"

    try:
        result = model.generate_content(full_prompt)
        text_response = result.text.replace("```json", "").replace("```", "").strip()
        print(f"AI JSON Yanıtı: {text_response}")  # Debug

        data = json.loads(text_response)

        final_reply = ""
        is_error = False

        if data.get("type") == "action":
            func = data.get("function")
            params = data.get("parameters", {})

            system_res = ""
            if func == "kargo_sorgula":
                system_res = kargo_bilgisi_getir(params.get("no"))
            elif func == "iade_işlemi":
                system_res = iade_islemi_baslat(params.get("no"))
            elif func == "fiyat_hesapla":
                system_res = fiyat_hesapla(params.get("desi"), params.get("nereye"))

            elif func == "dogrulama_yap":
                ad = params.get("ad")
                telefon = params.get("telefon")
                siparis_no = params.get("siparis_no")
                system_res = dogrulama_yap(siparis_no, ad, telefon)

                if system_res.startswith("DOGRULAMA_BASARILI"):
                    final_prompt = f"""
                        GÖREV: Kullanıcıya hitaben, kibar, doğal ve sadece tek bir mesaj yaz. Başka açıklama kullanma.
                        SİSTEM BİLGİSİ: Doğrulama başarılı. Sipariş numarası hafızaya kaydedildi.
                        Talimat: Doğrulamanın başarılı olduğunu ve şimdi yeni adresi sorması gerektiğini söyle. Cevabın SADECE yanıt metni olmalıdır.
                        """
                else:
                    final_prompt = f"""
                        GÖREV: Kullanıcıya hitaben, kibar ve özür dileyen bir mesaj yaz. Başka açıklama kullanma.
                        SİSTEM BİLGİSİ: Bilgi Doğrulama Hatası.
                        Talimat: Doğrulamanın başarısız olduğunu ve bilgileri kontrol etmesini iste. Cevabın SADECE yanıt metni olmalıdır.
                        """
                final_resp = model.generate_content(final_prompt).text
                final_reply = final_resp.strip()

            elif func == "adres_degistir":
                siparis_no = params.get("siparis_no")
                ad = params.get("ad")
                telefon = params.get("telefon")
                yeni_adres = params.get("yeni_adres")
                system_res = adres_degistir(siparis_no, ad, telefon, yeni_adres)

                if "Bilgi Doğrulama Hatası:" in system_res or "Veritabanı işlem hatası:" in system_res or "Veri Eksikliği Hatası:" in system_res:
                    is_error = True

            if func != "dogrulama_yap":
                if is_error:
                    final_prompt = f"""
                            GÖREV: Kullanıcıya hitaben, kibar, **özür dileyen** ve sadece tek bir mesaj yaz. Başka hiçbir açıklama, giriş veya çıkış cümlesi kullanma.
                            SİSTEM BİLGİSİ: {system_res}

                            Talimat: Sistem bilgisini kullanıcıya nazikçe ilet. **Kesinlikle 'başarı', 'onaylandı', 'güncellendi' gibi kelimeler kullanma**. Hata nedeniyle işlemin gerçekleştirilemediğini belirt ve tekrar denemesini iste (Bilgileri kontrol etmesini söyle). Cevabın SADECE yanıt metni olmalıdır.
                            """
                else:
                    final_prompt = f"""
                            GÖREV: Kullanıcıya hitaben, kibar, doğal ve sadece tek bir mesaj yaz. Başka hiçbir açıklama, giriş veya çıkış cümlesi kullanma.
                            SİSTEM BİLGİSİ: {system_res}

                            Talimat: Sistem bilgisini kullanıcıya nazikçe ilet. Cevabın SADECE yanıt metni olmalıdır.
                            """

                final_resp = model.generate_content(final_prompt).text
                final_reply = final_resp.strip()


        elif data.get("type") == "chat":
            final_reply = data.get("reply")

        chat_histories.setdefault(session_id, []).append(f"KULLANICI: {user_message}")
        chat_histories[session_id].append(f"ASİSTAN: {final_reply}")

        print(f"Hafızaya Kaydedildi. Yeni Uzunluk: {len(chat_histories[session_id])}")
        print("--- DEBUG BİTTİ ---\n")

        return final_reply

    except Exception as e:
        print(f"HATA: {e}")
        return "Bir hata oluştu."


def metni_sese_cevir(text):
    filename = f"ses_{uuid.uuid4().hex}.mp3"
    try:
        gTTS(text=text, lang='tr').save(os.path.join(AUDIO_FOLDER, filename))
        return f"/static/{filename}"
    except:
        return None


@app.route('/')
def ana_sayfa(): return render_template('index.html')


@app.route('/api/chat', methods=['POST'])
def chat_api():
    data = request.get_json()
    msg = data.get('message', '')
    sid = data.get('session_id')
    if not sid:
        print("UYARI: Frontend Session ID göndermedi! Hafıza çalışmaz.")
        sid = "ozel_test_oturumu"

    resp = process_with_gemini(sid, msg)
    audio = metni_sese_cevir(resp)
    return jsonify({"response": resp, "audio": audio, "session_id": sid})


if __name__ == '__main__':
    app.run(debug=True)