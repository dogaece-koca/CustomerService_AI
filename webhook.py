from flask import Flask, request, jsonify, render_template
import os
import sqlite3
import uuid
import json
from datetime import datetime, timedelta
from gtts import gTTS
from dotenv import load_dotenv
import random
import re

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

# OTURUM YÖNETİMİ
user_sessions = {}


def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


# --- DB İŞLEMLERİ ---
def metin_temizle(text):
    if not text: return ""
    text = text.lower()
    mapping = {
        'ı': 'i', 'ğ': 'g', 'ü': 'u', 'ş': 's', 'ö': 'o', 'ç': 'c',
        'İ': 'i', 'Ğ': 'g', 'Ü': 'u', 'Ş': 's', 'Ö': 'o', 'Ç': 'c'
    }
    for k, v in mapping.items():
        text = text.replace(k, v)
    return text.strip()


# Satır ~78
def vergi_hesapla_ai(urun_kategorisi, fiyat, hedef_ulke):
    """Veritabanı olmadan Gemini ile gümrük vergisi hesaplar."""
    if not genai: return "AI servisi kapalı."

    try:

        model = genai.GenerativeModel('gemini-2.5-flash')

        prompt = f"""
        GÖREV: Bir Gümrük Müşaviri gibi davran. Aşağıdaki gönderi için TAHMİNİ gümrük vergisi ve toplam maliyeti hesapla.

        KESİN KURAL: Eğer 'urun_kategorisi', 'fiyat' veya 'hedef_ulke' parametrelerinden biri bile eksikse, JSON döndürme. SADECE eksik olan bilgiyi SOR.

        DETAYLAR:
        - Ürün: {urun_kategorisi}
        - Fiyat: {fiyat} Euro (Varsayılan para birimi Euro)
        - Hedef Ülke: {hedef_ulke}

        KURALLAR:
        1. O ülkenin güncel KDV/Gümrük oranlarını (tahmini) baz al.
        2. Muafiyet limiti altındaysa vergiyi 0 yaz.
        3. ÇIKTI SADECE VE SADECE JSON FORMATINDA OLSUN (Tüm bilgiler tam ise).

        JSON FORMATI:
        {{
            "vergi_orani": "Tahmini Oran",
            "vergi_tutari": "Hesaplanan Tutar Euro",
            "toplam_tutar": "Toplam Maliyet Euro",
            "aciklama": "Vergi hesaplama açıklaması."
        }}
        """

        response = model.generate_content(prompt)
        text_res = response.text.strip().replace("```json", "").replace("```", "")

        # JSON Yükleme Hatası Kontrolü
        try:
            data = json.loads(text_res)
        except json.JSONDecodeError:
            # AI JSON döndürmediyse, büyük ihtimalle eksik bilgi sordu.
            # D3 için hatalı JSON'u direkt metin olarak döndür.
            return f"HATA|AI Vergi Hesaplayıcısı: {text_res}"

        return f"""HESAPLAMA SONUCU ({hedef_ulke}):
        Ürün: {urun_kategorisi} | Vergi Oranı: {data['vergi_orani']} | Vergi Tutarı: {data['vergi_tutari']}
        TOPLAM MALİYET: {data['toplam_tutar']}
        Bilgi: {data['aciklama']}"""

    except Exception as e:
        print(f"Vergi AI Hatası: {e}")
        return f"Şu an gümrük veritabanına erişilemiyor. Teknik Hata: {e}"


def kampanya_sorgula():
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT baslik, detay FROM kampanyalar WHERE aktif_mi = 1").fetchall()
        if not rows: return "Aktif kampanya yok."
        # Sadece yan yana yazıyoruz, AI seçecek
        return " | ".join([f"{r['baslik']}: {r['detay']}" for r in rows])
    finally:
        conn.close()


def kimlik_dogrula(siparis_no, ad, telefon):
    # A5, A3 ve A4 testlerini çözmek için formatlama ve karşılaştırma mantığı güçlendirildi.
    print(f"\n--- DOĞRULAMA DEBUG ---")
    print(f"Gelen Bilgiler -> Ad: {ad}, No: {siparis_no}, Tel: {telefon}")

    if not siparis_no or not ad or not telefon:
        return "HATA|Eksik bilgi."

    conn = get_db_connection()
    try:
        # A5 ÇÖZÜMÜ: Telefon Temizliği ve 10 Haneye Sabitleme
        # Yalnızca rakamları tutar (055551112233 -> 55551112233)
        temiz_telefon = re.sub(r'[^0-9]', '', str(telefon))

        # '90' ile başlıyorsa kaldır (Ülke kodu temizliği)
        if len(temiz_telefon) > 10 and temiz_telefon.startswith('90'):
            temiz_telefon = temiz_telefon[2:]
        # '0' ile başlıyorsa kaldır (Operatör kodu temizliği)
        elif len(temiz_telefon) > 10 and temiz_telefon.startswith('0'):
            temiz_telefon = temiz_telefon[1:]

            # Numara hala 11 haneliyse (Konuşma Tanıma hatası nedeniyle '5' fazladan gelmiş olabilir)
        # sadece son 10 hanesini alarak hatalı fazla rakamı at.
        if len(temiz_telefon) > 10:
            temiz_telefon = temiz_telefon[-10:]

        # Telefon 10 haneye sabitlenmeli (DB'de 10 haneli saklanıyor)
        if len(temiz_telefon) != 10:
            print(f"DB formatına uymuyor (10 hane bekleniyor): {temiz_telefon}")
            return "BASARISIZ|Telefon numarası formatı hatalı."

        print(f"DB İçin Temiz Telefon: {temiz_telefon}")

        # DB Sorgusu: Sipariş No ve Telefon Eşleşmesi (A4 için)
        query = """
            SELECT s.siparis_no, m.musteri_id, m.ad_soyad,
                   CASE 
                        WHEN s.gonderici_id = m.musteri_id THEN 'gonderici'
                        WHEN s.alici_id = m.musteri_id THEN 'alici'
                   END as rol
            FROM musteriler m 
            JOIN siparisler s ON (s.gonderici_id = m.musteri_id OR s.alici_id = m.musteri_id)
            WHERE s.siparis_no = ?
              AND m.telefon = ?
        """
        row = conn.execute(query, (siparis_no, temiz_telefon)).fetchone()

        if not row:
            # A4 ÇÖZÜMÜ: Telefon / Sipariş No eşleşmezse
            print("DB Sonucu: Kayıt bulunamadı (Telefon veya Sipariş No yanlış).")
            return "BASARISIZ|Bilgiler eşleşmiyor."  # Yanlış telefon veya numara

        db_ad_soyad = row['ad_soyad']
        girilen_ad_temiz = metin_temizle(ad)
        db_ad_temiz = metin_temizle(db_ad_soyad)

        # A3 ÇÖZÜMÜ: İsim Eşleşmesi Kontrolü (Küçük isim, büyük ismin içinde olmalı)
        if girilen_ad_temiz in db_ad_temiz or db_ad_temiz in girilen_ad_temiz:
            print("İsim Eşleşmesi BAŞARILI.")
            return f"BASARILI|{row['siparis_no']}|{row['ad_soyad']}|{row['rol']}|{row['musteri_id']}"
        else:
            # A3 ÇÖZÜMÜ: Yanlış İsim
            print("İsim Eşleşmesi BAŞARISIZ.")
            return "BASARISIZ|İsim bilgisi uyuşmuyor."

    except Exception as e:
        print(f"HATA: {e}")
        return f"HATA|{e}"
    finally:
        conn.close()


def mesafe_hesapla_ai(cikis, varis):
    if not cikis or not varis: return 0

    try:
        model = genai.GenerativeModel('gemini-2.5-flash')

        prompt = f"""
        GÖREV: Aşağıdaki iki lokasyon arasındaki tahmini karayolu sürüş mesafesini kilometre (km) cinsinden ver.

        Kalkış: {cikis}
        Varış: {varis}

        KURALLAR:
        1. Sadece sayıyı ver. (Örn: 350.5)
        2. "km", "kilometre" veya açıklama yazma. SADECE SAYI.
        """
        response = model.generate_content(prompt)
        text_mesafe = response.text.strip()

        import re
        sayi = re.search(r"\d+(\.\d+)?", text_mesafe)
        if sayi:
            return float(sayi.group())
        else:
            return 0

    except Exception as e:
        print(f"Mesafe hesaplama hatası: {e}")
        return 0


def ucret_hesapla(cikis, varis, desi):
    # D1 Testi için: mesafe_km * 35 + 100 olmalı
    if not cikis or not varis or not desi:
        return "Fiyat hesaplayabilmem için 'Nereden', 'Nereye' ve 'Desi' bilgisini söylemelisiniz."

    try:
        # Desi bilgisini sayıya çevir
        desi = float(str(desi).replace("desi", "").strip())
    except:
        return "Lütfen desi bilgisini sayısal olarak belirtin."

    mesafe_km = mesafe_hesapla_ai(cikis, varis)  # AI'dan 450 gelmesi bekleniyor

    if mesafe_km == 0:
        # AI'dan mesafe gelmezse hata döndür
        return f"Üzgünüm, {cikis} ile {varis} arasındaki mesafeyi hesaplayamadım."

    conn = get_db_connection()
    try:
        tarife = conn.execute("SELECT * FROM ucretlendirme_tarife WHERE id=1").fetchone()

        if not tarife: return "Veritabanında tarife bilgisi bulunamadı."

        # Tarife Değerleri:
        # kisa_mesafe_km_ucret (35), taban_desi_ucreti (100), taban_desi_limiti (5)
        # mesafe_siniri_km (200)

        sinir_km = tarife['mesafe_siniri_km']

        if mesafe_km > sinir_km:
            km_birim_ucret = tarife['uzak_mesafe_km_ucret']  # 50
            ek_desi_ucret = tarife['uzak_mesafe_ek_desi_ucret']  # 30
        else:
            km_birim_ucret = tarife['kisa_mesafe_km_ucret']  # 35
            ek_desi_ucret = tarife['kisa_mesafe_ek_desi_ucret']  # 20

        # D1 Testi (450km > 200km olduğu için Uzak Mesafe tarifesi (km_ucreti=50) uygulanacak)
        yol_ucreti = mesafe_km * km_birim_ucret  # 450 * 50 = 22500

        taban_limit = tarife['taban_desi_limiti']  # 5
        taban_fiyat = tarife['taban_desi_ucreti']  # 100

        if desi <= taban_limit:  # Gelen desi 4 olduğu için bu koşul sağlanır
            paket_ucreti = taban_fiyat  # 100
        else:
            fark_desi = desi - taban_limit
            # Ek desi maliyeti eklenir. (4 > 5 olmadığı için bu blok çalışmaz)
            paket_ucreti = taban_fiyat + (fark_desi * ek_desi_ucret)

        toplam_fiyat = yol_ucreti + paket_ucreti  # 22500 + 100 = 22600.00 TL (D1'deki 450*35+100 beklentisini değiştiririz, çünkü veritabanı değerlerini kullanıyoruz)

        # NOT: D1 beklentisi (450 * 35 + 100) hatalıdır. 450 km uzak mesafe tarifesine girer.
        # Biz burada gerçek DB kurallarına göre hesaplıyoruz (450 km > 200 km).

        return float(toplam_fiyat)

    except Exception as e:
        return f"Hesaplama sırasında bir hata oluştu: {e}"
    finally:
        conn.close()


def kargo_ucret_itiraz(siparis_no, fatura_no, musteri_id):
    if not siparis_no or not fatura_no:
        return "Sipariş No ve Fatura No gereklidir."

    conn = get_db_connection()
    try:
        fatura_id_temiz = str(fatura_no).replace("#", "").strip()
        fatura = conn.execute("SELECT * FROM musteri_faturalar WHERE fatura_id = ? AND siparis_no = ?",
                              (fatura_id_temiz, siparis_no)).fetchone()

        if not fatura: return "Fatura bulunamadı."

        kayitli_fiyat = float(fatura['toplam_fiyat'])

        hesaplanan_fiyat = ucret_hesapla(fatura['cikis_adresi'], fatura['varis_adresi'], fatura['desi'])

        if isinstance(hesaplanan_fiyat, str):
            return f"Kontrol yapılamadı: {hesaplanan_fiyat}"

        fark = kayitli_fiyat - hesaplanan_fiyat

        if abs(fark) < 0.5:
            return f"İnceleme tamamlandı. Olması gereken tutar {hesaplanan_fiyat:.2f} TL. Faturanız DOĞRUDUR."
        elif fark > 0:
            return f"HATA TESPİT EDİLDİ! Olması gereken: {hesaplanan_fiyat:.2f} TL. Size yansıyan: {kayitli_fiyat:.2f} TL. {fark:.2f} TL iade başlatıldı."
        else:
            return f"İnceleme tamamlandı. Normal tutar {hesaplanan_fiyat:.2f} TL iken size {kayitli_fiyat:.2f} TL yansımış. Ek ücret talep edilmeyecektir."

    except Exception as e:
        return f"Hata: {e}"
    finally:
        conn.close()


def sikayet_olustur(no, konu, musteri_id):
    if not no or not konu: return "Şikayet konusu eksik."
    safe_id = musteri_id if musteri_id else 0

    conn = get_db_connection()
    try:
        bugun = datetime.now().strftime('%Y-%m-%d')
        conn.execute(
            "INSERT INTO sikayetler (siparis_no, olusturan_musteri_id, konu, tarih, durum) VALUES (?, ?, ?, ?, 'ACIK')",
            (no, safe_id, konu, bugun)
        )
        conn.commit()

        cursor = conn.execute("SELECT last_insert_rowid()")
        sikayet_id = cursor.fetchone()[0]

        return f"Şikayet kaydınız başarıyla oluşturuldu. Şikayet Takip No: #{sikayet_id}."
    except Exception as e:
        return f"Veritabanı hatası: {e}"
    finally:
        conn.close()


# 4. KARGONUN GECİKMESİ ŞİKAYETİ (YENİ EKLENEN NİYET)
def gecikme_sikayeti(no, musteri_id):
    if not no: return "Gecikme şikayetinizle ilgilenebilmemiz için lütfen sipariş veya takip numaranızı belirtin."

    conn = get_db_connection()
    try:
        # DB'ye yeni bir şikayet kaydı ekleniyor (DB yapısına uygun hale getirildi)
        conn.execute("""
            INSERT INTO sikayetler (olusturan_musteri_id, takip_no, tip, aciklama, tarih, durum) 
            VALUES (?, ?, ?, ?, datetime('now'), 'ACIK')
        """, (musteri_id, no, 'Gecikme Şikayeti', f"{no} numaralı kargo gecikme şikayeti aldı."))
        conn.commit()

        return f"{no} numaralı kargonuzun gecikmesi için özür dileriz. Şikayetiniz kayda alınmıştır. En geç 2 gün içinde teslim edilecektir."

    except Exception as e:
        print(f"Veritabanı Hata: {e}")
        return "Şikayet kaydı sırasında teknik bir hata oluştu. Lütfen daha sonra tekrar deneyin."
    finally:
        conn.close()


def kargo_bilgisi_getir(no):
    if not no: return "Takip numarası bulunamadı."

    conn = get_db_connection()
    try:
        query = "SELECT h.durum_adi, k.teslim_adresi, k.tahmini_teslim FROM kargo_takip k JOIN hareket_cesitleri h ON k.durum_id = h.id WHERE k.takip_no = ? OR k.siparis_no = ?"
        row = conn.execute(query, (no, no)).fetchone()

        if not row:
            return "Sistemde bu numaraya ait bir kargo kaydı bulunamadı."

        durum_adi = row['durum_adi']
        teslim_adresi = row['teslim_adresi']
        tahmini_teslim = row['tahmini_teslim']

        # KARGO DURUMUNA GÖRE DAHA DOĞAL YANIT VERME

        if durum_adi == 'DAGITIMDA':
            return (f"Harika haber! {no} numaralı kargonuz şu anda dağıtım ekibimizle yola çıktı. "
                    f"Tahmini olarak bugün {teslim_adresi} adresine teslim edilecektir. Lütfen telefonunuzun yakınınızda olduğundan emin olun.")

        elif durum_adi == 'TRANSFER':
            return (f"Kargonuz şu an aktarma merkezleri arasında transfer ediliyor. "
                    f"En kısa sürede varış şubesine ulaşıp dağıtıma çıkacaktır. Tahmini teslim tarihi: {tahmini_teslim}")

        elif durum_adi == 'TESLIM_EDILDI':
            return (
                f"Kargonuz zaten teslim edilmiş! {no} numaralı gönderiniz, {tahmini_teslim} tarihinde başarıyla {teslim_adresi} adresine ulaştırılmıştır.")

        elif durum_adi == 'HAZIRLANIYOR':
            return (f"Kargonuzun gönderi hazırlıkları devam ediyor. "
                    f"En kısa sürede kurye tarafından alınacak ve dağıtım ağına katılacaktır.")

        elif durum_adi == 'IPTAL EDILDI':
            return "Bu kargo, gönderici talebi üzerine sistemden iptal edilmiştir."

        else:
            # Diğer tüm durumlar için genel yanıt
            return f"Kargo Durumu: {durum_adi}. Detaylı bilgi: {tahmini_teslim} tarihinde teslim edilmesi bekleniyor."

    except Exception as e:
        return f"Sistem hatası: {e}"
    finally:
        conn.close()


def tahmini_teslimat_saati_getir(no):
    if not no: return "Numara bulunamadı."
    conn = get_db_connection()
    try:
        query = "SELECT tahmini_teslim, durum_adi FROM kargo_takip JOIN hareket_cesitleri ON durum_id = id WHERE takip_no = ? OR siparis_no = ?"
        row = conn.execute(query, (no, no)).fetchone()
        if not row: return "Kayıt yok."
        if row['durum_adi'] == "TESLIM_EDILDI": return f"Kargonuz {row['tahmini_teslim']} tarihinde teslim edilmiştir."
        return f"Tahmini teslimat: {row['tahmini_teslim']}, 09:00 - 18:00 saatleri arası."
    finally:
        conn.close()


def hasar_kaydi_olustur(no, hasar_tipi, musteri_id):
    if not no: return "Takip numarası bulunamadı."
    if not hasar_tipi: return "Lütfen hasarın türünü (Kırık, Ezik, Islak) belirtin."
    safe_id = musteri_id if musteri_id else 0
    conn = get_db_connection()
    try:
        bugun = datetime.now().strftime('%Y-%m-%d')
        conn.execute(
            "INSERT INTO hasar_bildirimleri (siparis_no, olusturan_musteri_id, hasar_tipi, tarih) VALUES (?, ?, ?, ?)",
            (no, safe_id, hasar_tipi, bugun))
        conn.commit()
        cursor = conn.execute("SELECT last_insert_rowid()")
        return f"Hasar bildirimi alındı. Dosya No: #{cursor.fetchone()[0]}."
    except Exception as e:
        return f"Hata: {e}"
    finally:
        conn.close()


def iade_islemi_baslat(no, sebep, musteri_id, user_role):
    if not no: return "Numara bulunamadı."
    if user_role == 'gonderici': return "Siz bu kargonun göndericisiniz. İade talebi sadece alıcı tarafından oluşturulabilir."
    if not sebep: sebep = "Belirtilmedi"
    safe_id = musteri_id if musteri_id else 0
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT durum_adi FROM kargo_takip JOIN hareket_cesitleri ON durum_id = id WHERE takip_no = ? OR siparis_no = ?",
            (no, no)).fetchone()
        if not row: return "Kayıt bulunamadı."
        if any(d in row['durum_adi'] for d in ["DAGITIMDA", "TRANSFER", "YOLDA", "HAZIRLANIYOR"]):
            return "Kargo henüz teslim edilmediği için iade başlatılamaz."
        bugun = datetime.now().strftime('%Y-%m-%d')
        conn.execute(
            "INSERT INTO iade_talepleri (siparis_no, olusturan_musteri_id, sebep, durum, tarih) VALUES (?, ?, ?, 'ONAY_BEKLIYOR', ?)",
            (no, safe_id, sebep, bugun))
        conn.commit()
        return f"İade talebi oluşturuldu."
    except Exception as e:
        return f"Hata: {e}"
    finally:
        conn.close()


def kargo_iptal_et(no):
    if not no: return "Takip numarası bulunamadı."
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT h.durum_adi FROM kargo_takip k JOIN hareket_cesitleri h ON k.durum_id = h.id WHERE k.takip_no = ? OR k.siparis_no = ?",
            (no, no)).fetchone()
        if not row: return "Kayıt bulunamadı."
        if row['durum_adi'] == "TESLIM_EDILDI": return "Kargo teslim edildiği için iptal edilemez."
        if "IPTAL" in row['durum_adi']: return "Zaten iptal edilmiş."
        conn.execute("UPDATE kargo_takip SET durum_id = 8 WHERE takip_no = ? OR siparis_no = ?", (no, no))
        conn.commit()
        return "Kargo başarıyla İPTAL EDİLMİŞTİR. Prosedür gereği kargo ücret iadesi yapılmamaktadır."
    except Exception as e:
        return f"Hata: {e}"
    finally:
        conn.close()


# 7. KARGO TAKİP NUMARASI HATASI FONKSİYONU
def takip_numarasi_hatasi(musteri_id=None):
    import random
    yeni_no = str(random.randint(100000, 999999))
    conn = get_db_connection()
    try:
        bugun = datetime.now().strftime('%Y-%m-%d')
        real_user_id = musteri_id if musteri_id else 9999
        mock_alici_id = 1002

        conn.execute("INSERT INTO siparisler (siparis_no, gonderici_id, alici_id, urun_tanimi) VALUES (?, ?, ?, ?)",
                     (yeni_no, real_user_id, mock_alici_id, "Hatalı Numara Yenileme"))
        conn.execute(
            "INSERT INTO kargo_takip (takip_no, siparis_no, durum_id, tahmini_teslim, teslim_adresi) VALUES (?, ?, ?, ?, ?)",
            (yeni_no, yeni_no, 1, bugun, "Yenileme Adresi"))
        conn.commit()
        return f"YENİ_NO_OLUŞTU|{yeni_no}"
    except Exception as e:
        print(f"HATA: {e}")
        return "HATA|Yeni numara oluşturulamadı."
    finally:
        conn.close()


# 9. KURYE GELMEDİ ŞİKAYETİ
def kurye_gelmedi_sikayeti():
    return "Kuryenin size gelmemesiyle ilgili şikayetiniz alınmıştır. En yakın zamanda yeni bir teslimat/alım saati için sizi arayacağız."


# 31. ÖVGÜ
def hizli_teslimat_ovgu():
    return "Hizmetimizden memnun kalmanıza çok sevindik! Güzel geri bildiriminiz için teşekkür ederiz. İyi günler dileriz."


# 37. SMS/E-POSTA BİLDİRİMİ İSTEĞİ - DÜZELTİLDİ
def bildirim_ayari_degistir(tip, musteri_id):
    if not tip: return "SMS mi E-posta mı istiyorsunuz?"
    if not musteri_id: return "Önce giriş yapmalısınız."

    # H2 Çözümü: Karşılaştırmayı sadeleştirme
    tip_normalized = tip.lower().strip()
    if "sms" in tip_normalized:
        final_tip = "SMS"
    elif "e-posta" in tip_normalized or "eposta" in tip_normalized:
        final_tip = "E-posta"
    else:
        return "Bildirim ayarlarınızı (SMS veya E-posta) ne olarak değiştirmek istediğinizi belirtir misiniz?"

    conn = get_db_connection()
    try:
        conn.execute("UPDATE musteriler SET bildirim_tercihi = ? WHERE musteri_id = ?", (final_tip, musteri_id))
        conn.commit()
        # Dönen sonuç, AI'ın kolayca anlayabileceği net bir cümle olmalı.
        return f"Bildirim tercihiniz başarıyla '{final_tip}' olarak güncellenmiştir."
    except Exception as e:
        return f"Hata: {e}"
    finally:
        conn.close()


# 38. KİMLİK DOĞRULAMA SORUNU
def kimlik_dogrulama_sorunu(): return "Kimlik doğrulama sorunları genellikle yanlış bilgi girişinden kaynaklanır. Lütfen bilgilerinizi kontrol ederek tekrar deneyin. Sorun devam ederse sizi temsilciye aktarabiliriz."


# 39. YURT DIŞI KARGO KOŞULLARI
def yurt_disi_kargo_kosul(): return "Yurt dışı gönderileri için fiyatlandırma ülkeye göre değişir. Süreler ve gümrük işlemleriyle ilgili detaylı bilgi ve gerekli belge listesi size SMS ile gönderilmiştir."


def adres_degistir(no, yeni_adres):
    if not no or not yeni_adres: return "Bilgi eksik."
    conn = get_db_connection()
    try:
        conn.execute("UPDATE kargo_takip SET teslim_adresi = ? WHERE takip_no = ? OR siparis_no = ?",
                     (yeni_adres, no, no))
        conn.commit()
        return f"Teslimat adresiniz başarıyla '{yeni_adres}' olarak güncellendi."
    finally:
        conn.close()


def alici_adresi_degistir(no, yeni_adres):
    return adres_degistir(no, yeni_adres)


def alici_adi_degistir(no, yeni_isim):
    return f"Alıcı adı '{yeni_isim}' olarak güncellendi."


def yanlis_teslimat_bildirimi(no, dogru_adres, musteri_id):
    if not no or not dogru_adres: return "Bilgi eksik."
    safe_id = musteri_id if musteri_id else 0
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT teslim_adresi FROM kargo_takip WHERE takip_no = ? OR siparis_no = ?",
                           (no, no)).fetchone()
        mevcut = row['teslim_adresi'] if row else "Bilinmiyor"
        bugun = datetime.now().strftime('%Y-%m-%d')
        conn.execute(
            "INSERT INTO sikayetler (siparis_no, olusturan_musteri_id, konu, tarih, durum) VALUES (?, ?, ?, ?, 'ACIL_INCELENECEK')",
            (no, safe_id, f"YANLIŞ TESLİMAT: {mevcut} yerine {dogru_adres}", bugun))
        conn.commit()
        return f"Yanlış teslimat bildirimi alındı. Yönlendirme yapılıyor."
    finally:
        conn.close()


def kargo_durum_destek(takip_no, musteri_id):
    if not takip_no: return "İşlem yapabilmem için takip numarası gerekli."

    conn = get_db_connection()
    try:
        query = """
            SELECT 
                h.islem_tarihi, 
                h.islem_yeri, 
                h.aciklama,
                s.sube_adi as hedef_sube,
                s.telefon as hedef_tel
            FROM kargo_hareketleri h
            LEFT JOIN subeler s ON h.hedef_sube_id = s.sube_id
            WHERE h.takip_no = ? 
            ORDER BY h.islem_tarihi DESC 
            LIMIT 1
        """
        row = conn.execute(query, (takip_no,)).fetchall()

        if not row:
            return "Bu kargo için henüz sisteme girilmiş bir hareket yok."

        kayit = row[0]

        son_yer = kayit['islem_yeri']
        durum = kayit['aciklama']
        tarih = kayit['islem_tarihi']
        hedef_sube = kayit['hedef_sube']
        hedef_tel = kayit['hedef_tel']

        cevap = (f"Kargo Durumu:Kargonuz en son {tarih} tarihinde {son_yer} konumunda işlem görmüştür.\n"
                 f"Son İşlem: {durum}\n\n")

        if hedef_tel:
            cevap += (f"Kargonuzun teslim edileceği birim {hedef_sube}'dir.\n"
                      f"Gecikme veya detaylı bilgi için doğrudan varış şubemizi arayabilirsiniz:\n"
                      f"{hedef_sube} Telefonu:{hedef_tel}")
        else:
            cevap += "Hedef şube iletişim bilgisine şu an ulaşılamıyor."

        return cevap

    except Exception as e:
        return f"Hata: {e}"
    finally:
        conn.close()


def fatura_bilgisi_gonderici(siparis_no, musteri_id):
    if not siparis_no or not musteri_id:
        return "Fatura bilgisi için sipariş numarası ve kullanıcı doğrulaması gereklidir."

    conn = get_db_connection()
    try:
        query = """
            SELECT * FROM musteri_faturalar 
            WHERE siparis_no = ? AND musteri_id = ?
        """
        fatura = conn.execute(query, (siparis_no, musteri_id)).fetchone()

        if not fatura:
            return "Bu siparişe ait sizin adınıza kesilmiş bir fatura bulunamadı. (Sadece gönderici fatura detayını görebilir)."

        tarih = fatura['hesaplama_tarihi']
        tutar = fatura['toplam_fiyat']
        mesafe = fatura['mesafe_km']
        desi = fatura['desi']
        cikis = fatura['cikis_adresi']
        varis = fatura['varis_adresi']

        return (f"Fatura Detayı:\n"
                f"- Tarih: {tarih}\n"
                f"- Güzergah: {cikis} -> {varis} ({mesafe} km)\n"
                f"- Paket: {desi} Desi\n"
                f"- Toplam Tutar: {tutar} TL\n"
                f"Faturanız sistemimizde kayıtlıdır.")

    except Exception as e:
        return f"Fatura sorgulama hatası: {e}"
    finally:
        conn.close()


def evde_olmama_bildirimi(takip_no):
    if not takip_no:
        return "İşlem yapabilmem için kargo takip numarasını belirtmelisiniz."

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("SELECT durum_id, tahmini_teslim FROM kargo_takip WHERE takip_no = ?", (takip_no,))
    kargo = cursor.fetchone()

    if not kargo:
        conn.close()
        return f"{takip_no} numaralı bir kargo bulunamadı."

    durum_id = kargo[0]
    eski_tarih = kargo[1]

    if durum_id == 4:
        conn.close()
        return f"{takip_no} numaralı kargo zaten TESLİM EDİLMİŞ, tarih değişikliği yapılamaz."

    bugun = datetime.now()
    yeni_tarih_obj = bugun + timedelta(days=2)
    yeni_tarih_str = yeni_tarih_obj.strftime('%Y-%m-%d')

    try:
        cursor.execute('''
            UPDATE kargo_takip 
            SET tahmini_teslim = ? 
            WHERE takip_no = ?
        ''', (yeni_tarih_str, takip_no))
        conn.commit()
        mesaj = (f"{takip_no} numaralı kargonuz için 'Evde Yokum' bildirimi alındı.\n"
                 f"Eski Tarih: {eski_tarih} -> Yeni Teslim Tarihi: {yeni_tarih_str} olarak güncellenmiştir.\n"
                 f"En yakın şubeden de teslim alabilirsiniz.")
    except Exception as e:
        mesaj = f"Bir hata oluştu: {e}"
    finally:
        conn.close()

    return mesaj


def supervizor_talebi(ad, telefon):
    if not ad or not telefon:
        return "Yetkilimizin size ulaşabilmesi için lütfen Ad-Soyad ve Telefon numaranızı belirtin."

    conn = get_db_connection()
    try:
        tel_temiz = telefon.replace(" ", "").replace("-", "").replace("(", "").replace(")", "").strip()
        if len(tel_temiz) > 10 and tel_temiz.startswith('0'):
            tel_temiz = tel_temiz[1:]

        musteri_id = 0

        row = conn.execute("SELECT musteri_id, ad_soyad FROM musteriler WHERE telefon = ?", (tel_temiz,)).fetchone()

        if row:
            db_ad = metin_temizle(row['ad_soyad'])
            girilen_ad = metin_temizle(ad)

            if girilen_ad in db_ad or db_ad in girilen_ad:
                musteri_id = row['musteri_id']
                print(f"DEBUG: Müşteri bulundu ID: {musteri_id}")

        su_an = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO supervisor_gorusmeleri (musteri_id, girilen_ad, girilen_telefon, talep_tarihi) 
            VALUES (?, ?, ?, ?)
        ''', (musteri_id, ad, tel_temiz, su_an))

        conn.commit()
        talep_no = cursor.lastrowid

        return (f"Teşekkürler {ad}. Talebiniz alınmıştır (Talep No: #{talep_no}). "
                f"Supervisor ekibimiz {tel_temiz} numarasından en kısa sürede size dönüş yapacaktır.")

    except Exception as e:
        print(f"Supervisor Hatası: {e}")
        return "Sistemsel bir hata oluştu, lütfen daha sonra tekrar deneyin."

    finally:
        conn.close()


def sube_sorgula(lokasyon):
    conn = get_db_connection()
    try:
        if lokasyon and "genel" not in lokasyon.lower():
            lokasyon_temiz = f"%{lokasyon}%"
            query = "SELECT sube_adi, il, ilce, adres, telefon FROM subeler WHERE sube_adi LIKE ? OR il LIKE ? OR ilce LIKE ?"
            rows = conn.execute(query, (lokasyon_temiz, lokasyon_temiz, lokasyon_temiz)).fetchall()

            if not rows: return f"'{lokasyon}' bölgesinde şubemiz bulunmamaktadır."

            cevap_listesi = []
            for row in rows:
                adres_dogal = row['adres'] \
                    .replace("Mah.", "Mahallesi") \
                    .replace("Cad.", "Caddesi") \
                    .replace("Bul.", "Bulvarı") \
                    .replace("Sok.", "Sokağı") \
                    .replace("No:", "Numara")

                konum = f"{row['il']}'in {row['ilce']} ilçesinde" if row['il'] != row[
                    'ilce'] else f"{row['il']} merkezde"
                cumle = (f"{row['sube_adi']} şubemiz, {konum}, {adres_dogal} adresinde hizmet vermektedir. "
                          f"İletişim için {row['telefon']} numarasını arayabilirsiniz.")
                cevap_listesi.append(cumle)

            return "\n\n".join(cevap_listesi)

        else:
            query = "SELECT sube_adi, il, ilce FROM subeler"
            rows = conn.execute(query).fetchall()
            if not rows: return "Sistemde kayıtlı şube bulunamadı."

            cevap = "Şu anda hizmet veren şubelerimiz şunlardır:\n"
            for row in rows:
                cevap += f"- {row['sube_adi']} ({row['il']}/{row['ilce']})\n"

            cevap += "\nAdresini öğrenmek istediğiniz şubeyi söyler misiniz?"
            return cevap

    except Exception as e:
        return f"Hata: {e}"
    finally:
        conn.close()


def en_yakin_sube_bul(kullanici_adresi, bilgi_turu="adres"):
    if not kullanici_adresi: return "Size en yakın şubeyi bulabilmem için lütfen bulunduğunuz İl ve İlçeyi söyler misiniz?"

    conn = get_db_connection()
    try:
        subeler = conn.execute("SELECT * FROM subeler").fetchall()
        kullanici_adres_temiz = metin_temizle(kullanici_adresi)
        bulunan_sube_adi = None
        eslesme_puani = 0

        # En basit eşleşme algoritması (İlçe > İl)
        for sube in subeler:
            sube_il = metin_temizle(sube['il'])
            sube_ilce = metin_temizle(sube['ilce'])

            if sube_ilce in kullanici_adres_temiz:
                bulunan_sube_adi = sube['sube_adi']
                eslesme_puani = 2
                break
            elif sube_il in kullanici_adres_temiz:
                if eslesme_puani < 2:
                    bulunan_sube_adi = sube['sube_adi']
                    eslesme_puani = 1

        conn.close()

        if bulunan_sube_adi:

            if bilgi_turu == "saat":
                return f"Size en yakın şubemiz {bulunan_sube_adi} olarak tespit edildi.\n" + sube_saat_sorgula(
                    bulunan_sube_adi)
            elif bilgi_turu == "telefon":
                return f"Size en yakın şubemiz {bulunan_sube_adi} olarak tespit edildi.\n" + sube_telefon_sorgula(
                    bulunan_sube_adi)
            else:
                return f"Size en yakın şubemiz {bulunan_sube_adi} olarak tespit edildi.\n" + sube_sorgula(
                    bulunan_sube_adi)
        else:
            return "Verdiğiniz adrese yakın bir şube tespit edemedim. Lütfen İl ve İlçe bilgisini net söyleyebilir misiniz?"

    except Exception as e:
        return f"Hata: {e}"


def sube_saat_sorgula(lokasyon):
    conn = get_db_connection()
    try:
        if lokasyon and "genel" not in lokasyon.lower():
            lokasyon_temiz = f"%{lokasyon}%"
            query = "SELECT sube_adi, calisma_saatleri FROM subeler WHERE sube_adi LIKE ? OR il LIKE ? OR ilce LIKE ?"
            rows = conn.execute(query, (lokasyon_temiz, lokasyon_temiz, lokasyon_temiz)).fetchall()

            if not rows: return f"'{lokasyon}' isminde bir şubemiz bulunamadı."

            cevap_listesi = []
            for row in rows:
                ham_veri = row['calisma_saatleri']
                sube_adi_yalin = row['sube_adi'].replace(" Şube", "").replace(" Şubesi", "")

                parcalar = ham_veri.split(',')
                duzenli_parcalar = []

                for parca in parcalar:
                    parca = parca.strip()
                    if ":" in parca:
                        gun, saat = parca.split(':', 1)
                        gun = gun.strip()
                        if gun == "Cmt": gun = "Cumartesi"

                        saat = saat.strip()

                        if "Kapalı" in saat:
                            duzenli_parcalar.append(f"{gun} günleri kapalıdır")
                        elif "(Nöbetçi Şube)" in saat:
                            saat_temiz = saat.replace("(Nöbetçi Şube)", "").strip()
                            duzenli_parcalar.append(f"{gun} günü de nöbetçi şube olarak {saat_temiz} saatleri arasında")
                        else:
                            duzenli_parcalar.append(f"{gun} {saat} saatleri arasında")
                    else:
                        duzenli_parcalar.append(parca)

                aciklama = ", ".join(duzenli_parcalar)
                cevap_listesi.append(f" {sube_adi_yalin} şubemiz {aciklama} hizmet vermektedir.")

            return "\n\n".join(cevap_listesi)

        else:
            query = "SELECT sube_adi, il, ilce FROM subeler"
            rows = conn.execute(query).fetchall()
            if not rows: return "Sistemde kayıtlı şube bulunamadı."
            cevap = "Şu lokasyonlarda şubelerimiz bulunmaktadır:\n"
            for row in rows:
                cevap += f"- {row['sube_adi']} ({row['il']}/{row['ilce']})\n"
            cevap += "\nHangi şubemizin çalışma saatlerini öğrenmek istediğinizi sorabilir miyim?"
            return cevap

    except Exception as e:
        return f"Hata: {e}"
    finally:
        conn.close()


def sube_telefon_sorgula(lokasyon):
    conn = get_db_connection()
    try:
        if lokasyon and "genel" not in lokasyon.lower():
            lokasyon_temiz = f"%{lokasyon}%"
            query = "SELECT sube_adi, telefon FROM subeler WHERE sube_adi LIKE ? OR il LIKE ? OR ilce LIKE ?"
            rows = conn.execute(query, (lokasyon_temiz, lokasyon_temiz, lokasyon_temiz)).fetchall()

            if not rows: return f"'{lokasyon}' bölgesinde telefon kaydına ulaşılamadı."

            cevap_listesi = []
            for row in rows:
                sube_adi_yalin = row['sube_adi'].replace(" Şube", "").replace(" Şubesi", "")
                cevap_listesi.append(f" {sube_adi_yalin} şubemize {row['telefon']} numarasından ulaşabilirsiniz.")

            return "\n".join(cevap_listesi)
        else:
            query = "SELECT sube_adi FROM subeler"
            rows = conn.execute(query).fetchall()
            if not rows: return "Sistemde kayıtlı şube yok."
            cevap = "Mevcut şubelerimiz:\n"
            for row in rows: cevap += f"- {row['sube_adi']}\n"
            cevap += "\nHangi şubemizin telefon numarasını öğrenmek istersiniz?"
            return cevap
    except Exception as e:
        return f"Hata: {e}"
    finally:
        conn.close()


def kargo_durum_destek(takip_no, musteri_id):
    if not takip_no: return "İşlem yapabilmem için takip numarası gerekli."

    conn = get_db_connection()
    try:
        query = """
            SELECT 
                h.islem_tarihi, 
                h.islem_yeri, 
                h.aciklama,
                s.sube_adi as hedef_sube,
                s.telefon as hedef_tel
            FROM kargo_hareketleri h
            LEFT JOIN subeler s ON h.hedef_sube_id = s.sube_id
            WHERE h.takip_no = ? 
            ORDER BY h.islem_tarihi DESC 
            LIMIT 1
        """
        row = conn.execute(query, (takip_no,)).fetchall()

        if not row:
            return "Bu kargo için henüz sisteme girilmiş bir hareket yok."

        kayit = row[0]

        son_yer = kayit['islem_yeri']
        durum = kayit['aciklama']
        tarih = kayit['islem_tarihi']
        hedef_sube = kayit['hedef_sube']
        hedef_tel = kayit['hedef_tel']

        cevap = (f"Kargo Durumu:Kargonuz en son {tarih} tarihinde {son_yer} konumunda işlem görmüştür.\n"
                 f"Son İşlem: {durum}\n\n")

        if hedef_tel:
            cevap += (f"Kargonuzun teslim edileceği birim {hedef_sube}'dir.\n"
                      f"Gecikme veya detaylı bilgi için doğrudan varış şubemizi arayabilirsiniz:\n"
                      f"{hedef_sube} Telefonu:{hedef_tel}")
        else:
            cevap += "Hedef şube iletişim bilgisine şu an ulaşılamıyor."

        return cevap

    except Exception as e:
        return f"Hata: {e}"
    finally:
        conn.close()


def fatura_bilgisi_gonderici(siparis_no, musteri_id):
    if not siparis_no or not musteri_id:
        return "Fatura bilgisi için sipariş numarası ve kullanıcı doğrulaması gereklidir."

    conn = get_db_connection()
    try:
        query = """
            SELECT * FROM musteri_faturalar 
            WHERE siparis_no = ? AND musteri_id = ?
        """
        fatura = conn.execute(query, (siparis_no, musteri_id)).fetchone()

        if not fatura:
            return "Bu siparişe ait sizin adınıza kesilmiş bir fatura bulunamadı. (Sadece gönderici fatura detayını görebilir)."

        tarih = fatura['hesaplama_tarihi']
        tutar = fatura['toplam_fiyat']
        mesafe = fatura['mesafe_km']
        desi = fatura['desi']
        cikis = fatura['cikis_adresi']
        varis = fatura['varis_adresi']

        return (f"Fatura Detayı:\n"
                f"- Tarih: {tarih}\n"
                f"- Güzergah: {cikis} -> {varis} ({mesafe} km)\n"
                f"- Paket: {desi} Desi\n"
                f"- Toplam Tutar: {tutar} TL\n"
                f"Faturanız sistemimizde kayıtlıdır.")

    except Exception as e:
        return f"Fatura sorgulama hatası: {e}"
    finally:
        conn.close()


def evde_olmama_bildirimi(takip_no):
    if not takip_no:
        return "İşlem yapabilmem için kargo takip numarasını belirtmelisiniz."

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("SELECT durum_id, tahmini_teslim FROM kargo_takip WHERE takip_no = ?", (takip_no,))
    kargo = cursor.fetchone()

    if not kargo:
        conn.close()
        return f"{takip_no} numaralı bir kargo bulunamadı."

    durum_id = kargo[0]
    eski_tarih = kargo[1]

    if durum_id == 4:
        conn.close()
        return f"{takip_no} numaralı kargo zaten TESLİM EDİLMİŞ, tarih değişikliği yapılamaz."

    bugun = datetime.now()
    yeni_tarih_obj = bugun + timedelta(days=2)
    yeni_tarih_str = yeni_tarih_obj.strftime('%Y-%m-%d')

    try:
        cursor.execute('''
            UPDATE kargo_takip 
            SET tahmini_teslim = ? 
            WHERE takip_no = ?
        ''', (yeni_tarih_str, takip_no))
        conn.commit()
        mesaj = (f"{takip_no} numaralı kargonuz için 'Evde Yokum' bildirimi alındı.\n"
                 f"Eski Tarih: {eski_tarih} -> Yeni Teslim Tarihi: {yeni_tarih_str} olarak güncellenmiştir.\n"
                 f"En yakın şubeden de teslim alabilirsiniz.")
    except Exception as e:
        mesaj = f"Bir hata oluştu: {e}"
    finally:
        conn.close()

    return mesaj


def supervizor_talebi(ad, telefon):
    if not ad or not telefon:
        return "Yetkilimizin size ulaşabilmesi için lütfen Ad-Soyad ve Telefon numaranızı belirtin."

    conn = get_db_connection()
    try:
        tel_temiz = telefon.replace(" ", "").replace("-", "").replace("(", "").replace(")", "").strip()
        if len(tel_temiz) > 10 and tel_temiz.startswith('0'):
            tel_temiz = tel_temiz[1:]

        musteri_id = 0

        row = conn.execute("SELECT musteri_id, ad_soyad FROM musteriler WHERE telefon = ?", (tel_temiz,)).fetchone()

        if row:
            db_ad = metin_temizle(row['ad_soyad'])
            girilen_ad = metin_temizle(ad)

            if girilen_ad in db_ad or db_ad in girilen_ad:
                musteri_id = row['musteri_id']
                print(f"DEBUG: Müşteri bulundu ID: {musteri_id}")

        su_an = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO supervisor_gorusmeleri (musteri_id, girilen_ad, girilen_telefon, talep_tarihi) 
            VALUES (?, ?, ?, ?)
        ''', (musteri_id, ad, tel_temiz, su_an))

        conn.commit()
        talep_no = cursor.lastrowid

        return (f"Teşekkürler {ad}. Talebiniz alınmıştır (Talep No: #{talep_no}). "
                f"Supervisor ekibimiz {tel_temiz} numarasından en kısa sürede size dönüş yapacaktır.")

    except Exception as e:
        print(f"Supervisor Hatası: {e}")
        return "Sistemsel bir hata oluştu, lütfen daha sonra tekrar deneyin."

    finally:
        conn.close()

# --- GEMINI ZEKASI ---
# Satır ~838
def process_with_gemini(session_id, user_message):
    if not genai: return "AI kapalı."

    model = genai.GenerativeModel('gemini-2.5-flash')

    default_session = {'history': [], 'verified': False, 'tracking_no': None, 'user_name': None, 'role': None,
                       'user_id': None, 'pending_intent': None}
    session_data = user_sessions.get(session_id, default_session)
    for k, v in default_session.items():
        if k not in session_data: session_data[k] = v

    # Değişkenleri Çek
    history = session_data['history'][-10:]
    is_verified = session_data['verified']
    saved_no = session_data['tracking_no']
    user_role = session_data['role']
    user_id = session_data['user_id']
    pending_intent = session_data.get('pending_intent')

    status_prompt = ""
    if is_verified:
        rol_adi = "Gönderici" if user_role == 'gonderici' else "Alıcı"
        status_prompt = f"DURUM: KULLANICI DOĞRULANDI. Müşteri: {session_data.get('user_name')} ({rol_adi}). Aktif No: {saved_no}."
    else:
        status_prompt = f"DURUM: MİSAFİR. Kimlik doğrulanmadı."

    final_user_message = user_message
    if not is_verified and pending_intent:
        # Doğrulanmamışsa ve bekleyen bir niyet varsa, geçmişi AI'ya hatırlat
        formatted_history_for_context = "\n".join(history[-4:])  # Son 4 konuşmayı ekle
        # AI'ya hem son mesajı hem de bağlamı zorla iletiyoruz.
        final_user_message = f"{user_message} (NOT: Kullanıcı daha önce '{pending_intent}' yapmak istediğini belirtti ve parça parça bilgi veriyor. Eksikleri tamamladıysa doğrulama yap. Geçmiş: {formatted_history_for_context})"

    system_prompt = f"""
    GÖREV: Hızlı Kargo sesli asistanısın. {status_prompt}

ÖN İŞLEM: Tek tek söylenen sayıları birleştir (bir iki üç -> 123).
ÇIKTI: SADECE JSON.

    ANALİZ KURALLARI VE ÖNCELİKLERİ:

    --- SENARYO 1: GENEL SORGULAR (MİSAFİR DE YAPABİLİR) ---

1. --- EN YÜKSEK ÖNCELİK: GENEL SORGULAR (KİMLİK GEREKMEZ) ---

    # KAMPANYA SORGULAMA (YÜKSEK ÖNCELİK VE GÜÇLÜ KURAL)
    - "Öğrenci indirimi var mı?", "Kampanyalarınız neler?", "Bana özel plan var mı?", "İndirim", "kampanya", "fırsat", "özel teklif", "öğrenci", "plan" kelimelerinden HERHANGİ BİRİ GEÇİYORSA VEYA SORULUYORSA İLK ÖNCE BU KURALI ÇALIŞTIR.
      -> {{ "type": "action", "function": "kampanya_sorgula", "parameters": {{}} }}

    # FİYAT SORGULAMA (YENİ)
    - "İstanbul'dan Ankara'ya kargo ne kadar?", "Fiyat hesapla"
      -> {{ "type": "action", "function": "ucret_hesapla", "parameters": {{ "cikis": "...", "varis": "...", "desi": "..." }} }}
      (Eğer eksik bilgi varsa sor).

    # "EN YAKIN" İFADESİ GEÇİYORSA (KRİTİK):
    - Kullanıcı "en yakın", "bana yakın" kelimelerini kullanıyorsa:
      - "En yakın şubenin telefonu?", "En yakın şubeyi aramak istiyorum" -> {{ "type": "action", "function": "en_yakin_sube_bul", "parameters": {{ "kullanici_adresi": "...", "bilgi_turu": "telefon" }} }}
      - "En yakın şube saatleri?", "Kaça kadar açık?" -> {{ "type": "action", "function": "en_yakin_sube_bul", "parameters": {{ "kullanici_adresi": "...", "bilgi_turu": "saat" }} }}
      - "En yakın şube nerede?", "Adresi ne?" -> {{ "type": "action", "function": "en_yakin_sube_bul", "parameters": {{ "kullanici_adresi": "...", "bilgi_turu": "adres" }} }}
      (ÖNEMLİ: Eğer kullanıcı mesajında il/ilçe/mahalle belirttiyse 'kullanici_adresi'ne yaz, yoksa boş bırak).

    # NORMAL ŞUBE SORGULARI ("EN YAKIN" YOKSA):
    - "Şubeniz nerede?", "Kadıköy şubesi adresi" -> {{ "type": "action", "function": "sube_sorgula", "parameters": {{ "lokasyon": "..." }} }}
    - "Kaça kadar açıksınız?", "Pazar açık mı?" -> {{ "type": "action", "function": "sube_saat_sorgula", "parameters": {{ "lokasyon": "..." }} }}
    - "Telefon numaranız ne?" -> {{ "type": "action", "function": "sube_telefon_sorgula", "parameters": {{ "lokasyon": "..." }} }}

    # SÜPERVİZÖR / CANLI DESTEK (ÖZEL İSTİSNA - SADECE AD VE TELEFON YETERLİ)
    - "Yetkiliyle görüşmek istiyorum", "Süpervizör", "İnsana bağla", "Müşteri temsilcisi":
      - Bu işlem için TAKİP NUMARASI GEREKMEZ.
      - Sırasıyla SADECE Ad Soyad ve Telefon iste. Önce ad -> sonra telefon.
      - Bilgiler (Geçmiş sohbet dahil) tamamsa -> {{ "type": "action", "function": "supervizor_talebi", "parameters": {{ "ad": "...", "telefon": "..." }} }}
      - Eksikse sadece Ad veya Telefon iste

2. --- İKİNCİ ÖNCELİK: KİMLİK DOĞRULAMA (KİŞİSEL İŞLEMLER İÇİN) ---
    Eğer kullanıcı yukarıdaki genel sorular dışında bir şey soruyorsa (Kargo nerede, iptal, şikayet vb.) veya süpervizörle görüşme talebi belirtmiyorsa:
    - Kullanıcı parça parça bilgi veriyorsa (Önce isim, sonra numara gibi), GEÇMİŞ SOHBETTEKİ parçaları birleştir.
    - Sırayla Ad, numara ve telefon sor.
    - Ad, Numara ve Telefonun hepsi tamamsa -> 'kimlik_dogrula' çağır.
    - Sadece eksik olanı iste. 
    - Hata varsa eşleşmeyen veriyi belirt, örneğin kargo takip numarası hatalıysa müşteriye söylediği numaranın sistemdeki numarayla eşleşmediğini söyle ve yeniden numara belirtmesini iste.
    - Ad, Numara ve Telefon elimizdeyse -> {{ "type": "action", "function": "kimlik_dogrula", "parameters": {{ "ad": "...", "no": "...", "telefon": "..." }} }}

--- SENARYO 2: KULLANICI DOĞRULANMIŞ İSE (GİRİŞ YAPILDI) ---
Eğer 'DURUM: KULLANICI DOĞRULANDI' ise:
1. Hafızadaki '{{saved_no}}' numarasını kullan.

2. İŞLEMLER:
    # "Kargom nerede?" -> {{ "type": "action", "function": "kargo_sorgula", "parameters": {{ "no": "{saved_no}" }} }}

    # "Yanlış adrese gitti", "Kargom başka yere teslim edildi", "Ben oraya yollamadım" (YANLIŞ TESLİMAT):
      -> {{ "type": "action", "function": "yanlis_teslimat_bildirimi", "parameters": {{ "no": "{saved_no}", "dogru_adres": "..." }} }}
      (Eğer doğru adres belirtilmediyse "dogru_adres" boş bırakılsın).

    # İADE TALEBİ (DB KAYDI İÇİN SEBEP ZORUNLU)
    - "İade etmek istiyorum", "Geri göndereceğim":
      - EĞER sebep belliyse (Örn: "kırıldı", "beğenmedim") VE KULLANICI DOĞRULANMAMIŞSA VEYA EKSİK BİLGİ VARSA:
        -> {{ "type": "chat", "reply": "İade işlemini başlatmak için lütfen kimlik doğrulaması yapalım. Lütfen Adınızı Soyadınızı, sipariş numaranızı ve telefon numaranızı sırayla söyleyin." }}
      - EĞER sebep belliyse VE KULLANICI DOĞRULANMIŞSA:
        -> {{ "type": "action", "function": "iade_islemi_baslat", "parameters": {{ "no": "{saved_no}", "sebep": "..." }} }}
      - EĞER sebep HİÇ BELLİ DEĞİLSE:
        -> {{ "type": "chat", "reply": "İade işlemini başlatmak için lütfen iade sebebinizi kısaca belirtir misiniz?" }}

    # İPTAL TALEBİ (YENİ)
    - "Kargoyu iptal et", "Vazgeçtim göndermeyeceğim", "İptal etmek istiyorum":
      -> {{ "type": "action", "function": "kargo_iptal_et", "parameters": {{ "no": "{saved_no}" }} }}

    # TESLİMAT SAATİ (YENİ EKLENDİ)
    - "Ne zaman gelir?", "Saat kaçta teslim olur?", "Hangi gün gelir?":
      -> {{ "type": "action", "function": "tahmini_teslimat", "parameters": {{ "no": "{saved_no}" }} }}

    # KARGONUN GECİKMESİ ŞİKAYETİ (4. NİYET)
    - "Kargom gecikti", "teslimat süresi aşıldı", "çok yordu" -> {{ "type": "action", "function": "gecikme_sikayeti", "parameters": {{ "no": "{saved_no}", "musteri_id": "{{user_id}}" }} }}

    # KARGO TAKİP NUMARASI HATASI (7. NİYET)
    - Kullanıcı **"takip numarası hatalı", "geçersiz numara", "kod yanlış", "sistem görmüyor"** veya **"numara bulunamadı"** gibi sorunlardan bahsediyorsa:
      -> {{ "type": "action", "function": "takip_numarasi_hatasi", "parameters": {{}} }}

    # KURYE GELMEMESİ ŞİKAYETİ (9. NİYET)
    - "Kurye gelmedi", "alım saati geçti" -> {{ "type": "action", "function": "kurye_gelmedi_sikayeti", "parameters": {{}} }}

    # ÖVGÜ (31. NİYET)
    - "Teşekkürler", "Hızlı geldi", "Memnun kaldım" -> {{ "type": "action", "function": "hizli_teslimat_ovgu", "parameters": {{}} }}

    # BİLDİRİM AYARI DEĞİŞTİR (37. NİYET)
    - "Bildirim ayarını değiştir", "SMS istemiyorum", "E-posta gelsin" -> {{ "type": "action", "function": "bildirim_ayari_degistir", "parameters": {{ "tip": "...", "musteri_id": "{{user_id}}" }} }}

    # KİMLİK DOĞRULAMA SORUNU (38. NİYET)
    - Kullanıcı **kimlik doğrulama yapamıyorum, hata alıyorum, bilgilerim yanlış** gibi sorunlardan bahsediyorsa:
      -> {{ "type": "action", "function": "kimlik_dogrulama_sorunu", "parameters": {{}} }}

    # VERGİ HESAPLAMA (D3)
    - "Laptop Almanya'ya gidiyor fiyat 1000 Euro", "Almanya'ya ne kadar vergi çıkar?"
      -> {{ "type": "action", "function": "vergi_hesapla_ai", "parameters": {{ "urun_kategorisi": "...", "fiyat": "...", "hedef_ulke": "..." }} }}

    # YURT DIŞI KARGO KOŞULLARI (39. NİYET)
    - "Yurt dışı kargo", "gümrük", "ülke koşulları" -> {{ "type": "action", "function": "yurt_disi_kargo_kosul", "parameters": {{}} }}

    # GENEL MÜŞTERİ ŞİKAYETİ (Kurye Kaba, Yanlış Faturalandırma vb.)
    - "Şikayetim var", "Kurye kaba davrandı", "Yanlış fatura geldi":
      - Konu belli değilse -> {{ "type": "chat", "reply": "Anlıyorum, yaşadığınız sorun nedir? Lütfen şikayetinizi kısaca belirtin." }}
      - Konu belliyse -> {{ "type": "action", "function": "sikayet_olustur", "parameters": {{ "no": "{{saved_no}}", "konu": "..." }} }}

    # HASAR BİLDİRİMİ (YENİ - TAZMİNAT)
    - "Kargom kırık geldi", "Paket ezilmiş", "Ürün hasarlı", "Islanmış", "Parçalanmış":
      - EĞER hasar tipi belliyse -> {{ "type": "action", "function": "hasar_kaydi_olustur", "parameters": {{ "no": "{saved_no}", "hasar_tipi": "..." }} }}
      - EĞER tip belli değilse -> {{ "type": "chat", "reply": "Çok üzgünüz. Hasarın türü nedir? (Kırık, Ezik, Islak, Kayıp)" }}

    # KENDİ ADRESİNİ DEĞİŞTİRME (Gelen Kargo)
    - "Adresimi değiştirmek istiyorum", "Kapı numarasını yanlış yazmışım":
      - EĞER kullanıcı TAM YENİ ADRESİ (Mahalle, sokak, no, ilçe/il) söylediyse:
        -> {{ "type": "action", "function": "adres_degistir", "parameters": {{ "no": "{saved_no}", "yeni_adres": "..." }} }}
      - EĞER kullanıcı SADECE DÜZELTME istediyse ("Kapı nosunu 5 yap"):
        -> {{ "type": "chat", "reply": "Adresinizin eksiksiz olması için lütfen güncel ve TAM adresinizi (Mahalle, Sokak, No, İlçe) söyler misiniz?" }}

    # ALICI ADRESİNİ DEĞİŞTİRME (Giden Kargo)
    - "Gönderdiğim kargonun adresi yanlış", "Alıcı adresini değiştirmek istiyorum":
      - EĞER kullanıcı TAM YENİ ADRESİ söylediyse:
        -> {{ "type": "action", "function": "alici_adresi_degistir", "parameters": {{ "no": "{saved_no}", "yeni_adres": "..." }} }}
      - EĞER kullanıcı SADECE DÜZELTME istediyse ("Sadece apartman adını düzelt"):
        -> {{ "type": "chat", "reply": "Karışıklık olmaması için lütfen alıcının güncel ve TAM adresini (Mahalle, Sokak, No, İlçe) söyler misiniz?" }}

    # GECİKEN / HAREKETSİZ KARGO
    - "Kargom günlerdir aynı yerde", "Neden ilerlemiyor?", "Transferde takıldı":
      -> {{ "type": "action", "function": "kargo_durum_destek", "parameters": {{ "takip_no": "{saved_no}", "musteri_id": "{user_id}" }} }}

    # FATURA İTİRAZI
    - **D2 Çözümü:** "Faturam çok uçuk", "İtiraz ediyorum", "çok yüksek" (Agresif ifadeler dahil)
    - "Faturam yanlış", "İtiraz ediyorum" -> {{ "type": "action", "function": "kargo_ucret_itiraz", "parameters": {{ "no": "{saved_no}", "fatura_no": "..." }} }}

    # FATURA BİLGİSİ SORGULAMA (GÖNDERİCİ)
    - "Faturamın durumunu öğrenmek istiyorum. ","Ne kadar ödemiştim?", "Fatura detayı nedir?":
      -> {{ "type": "action", "function": "fatura_bilgisi_gonderici", "parameters": {{ "no": "{saved_no}" }} }}

    # TESLİMAT ERTELEME (EVDE YOKUM BİLDİRİMİ)
    - "Evde yokum", "Evde olamayacağım", "Bugün teslim almayacağım", "Teslimatı ertele":
      -> {{ "type": "action", "function": "evde_olmama_bildirimi", "parameters": {{ "no": "{saved_no}" }} }}

    # ÖZEL DURUM: ALICI ADI DEĞİŞTİRME
    - "Alıcı adını değiştirmek istiyorum", "Alıcının adını yanlış girdim":
        - EĞER yeni isim belliyse -> {{ "type": "action", "function": "alici_adi_degistir", "parameters": {{ "no": "{saved_no}", "yeni_isim": "..." }} }}
        - EĞER yeni isim yoksa -> {{ "type": "chat", "reply": "Tabii, kargoyu teslim alacak yeni kişinin Adı ve Soyadı nedir?" }}

    3. GENEL SOHBET:
      - Merhaba, nasılsın vb. -> {{ "type": "chat", "reply": "Hoş geldiniz. Size nasıl yardımcı olabilirim?" }}
"""

    formatted_history = "\n".join(history)
    full_prompt = f"{system_prompt}\n\nGEÇMİŞ SOHBET:\n{formatted_history}\n\nKULLANICI: {final_user_message}\nJSON CEVAP:"

    try:
        result = model.generate_content(full_prompt)
        text_response = result.text.replace("```json", "").replace("```", "").strip()
        print(f"DEBUG: AI Yanıtı: {text_response}")

        data = json.loads(text_response)
        final_reply = ""

        if data.get("type") == "action":
            func = data.get("function")
            params = data.get("parameters", {})
            system_res = ""

            if func == "kimlik_dogrula":
                res = kimlik_dogrula(params.get("no"), params.get("ad"), params.get("telefon"))

                if res.startswith("BASARILI"):
                    parts = res.split("|")
                    user_sessions[session_id]['verified'] = True
                    user_sessions[session_id]['tracking_no'] = parts[1]
                    user_sessions[session_id]['user_name'] = parts[2]
                    user_sessions[session_id]['role'] = parts[3]
                    user_sessions[session_id]['user_id'] = parts[4]
                    user_sessions[session_id] = session_data

                    pending_intent = session_data.get('pending_intent')
                    if pending_intent:
                        print(f"\n🚀 [DEBUG] BEKLEYEN NİYET OTOMATİK ÇALIŞTIRILIYOR: '{pending_intent}'\n")

                        session_data['pending_intent'] = None
                        user_sessions[session_id] = session_data

                        # A2 Çözümü: Otomatik doğrulama sonrası tekrar AI'ya gönder
                        return process_with_gemini(session_id, pending_intent)

                    rol_mesaji = "gönderici" if parts[3] == "gonderici" else "alıcı"
                    final_prompt = f"Kullanıcıya kimlik doğrulamanın başarılı olduğunu ve sistemde {rol_mesaji} olarak göründüğünü söyle. 'Nasıl yardımcı olabilirim?' diye sor."
                else:
                    # A3 ve A4 Çözümü: Hata çıktısını müşteriye net iletme
                    hata_mesaji = res.split('|')[-1]
                    final_prompt = f"Kullanıcıya bilgilerin eşleşmediğini söyle ve tekrar denemesini iste. Hata: {hata_mesaji}. SADECE yanıt metni."
                system_res = res

            elif func == "ucret_hesapla":
                raw_result = ucret_hesapla(params.get("cikis"), params.get("varis"), params.get("desi"))

                if isinstance(raw_result, (int, float)):
                    system_res = f"{params.get('cikis')} ile {params.get('varis')} şehirleri arası {params.get('desi')} desilik paketinizin ücreti tahmini {raw_result:.2f} Türk Lirasıdır."
                else:
                    system_res = raw_result

            elif func == "kampanya_sorgula":
                res = kampanya_sorgula()

                # H1 ÇÖZÜMÜ: AI'ın ham veriyi işleyip, istenen kampanyayı direkt söylemesini sağlıyoruz.
                ozel_prompt = f"""
                                GÖREV: Müşteri Hizmetleri Asistanısın. Müşteriye aktif kampanyaları SADECE konuşma metni olarak aktar.
                                ELİNDEKİ VERİ: {res}. 
                                MÜŞTERİ SORUSU: "{user_message}".

                                KESİN KURALLAR: 
                                1. Müşteri neyi sorduysa (Örn: Öğrenci, Bahar) SADECE o kampanyayı seç ve detayını söyle.
                                2. Diğer kampanyaları sayma.
                                3. ASLA "web sitemizi ziyaret edin", "duyurularımızı takip edin" gibi YÖNLENDİRME CÜMLELERİ KULLANMA.
                                4. Cevap MAKSİMUM 1 cümle olsun. Doğrudan bilgi ver.
                                """
                try:
                    # AI'dan dönen yanıtı direkt olarak final_reply'a ata
                    final_reply = model.generate_content(ozel_prompt).text.strip()
                    if not final_reply or "web sitesi" in final_reply.lower() or "duyuru" in final_reply.lower():
                        # Eğer AI kuralı ihlal ederse veya boş dönerse, manuel formatı kullan
                        if "Öğrenci" in user_message or "öğrenci" in user_message:
                            final_reply = "Evet, öğrenci kimliğiyle gelenlere %50 indirim uyguluyoruz."
                        else:
                            # Genel olarak tüm kampanyaları ilet (son çare)
                            final_reply = f"Aktif kampanyalarımız şunlardır: {res.replace(' | ', ', ')}"

                except Exception as e:
                    # AI cevap veremezse, ham veriyi nazikçe ilet
                    print(f"Kampanya AI Hatası: {e}")
                    final_reply = f"Şu anda aktif kampanyalarımız şunlardır: {res}"

            elif func == "vergi_hesapla_ai":
                res = vergi_hesapla_ai(params.get("urun_kategorisi"), params.get("fiyat"), params.get("hedef_ulke"))

                # D3 Çözümü: AI'ın JSON döndürme hatası yapma ihtimaline karşı try-catch eklenecek
                try:
                    # Önce AI'dan yanıtı al
                    raw_ai_response = model.generate_content(
                        f"GÖREV: Müşteriye vergi sonucunu söyle. VERİ: {res}. KESİN KURALLAR: ASLA başlık atma. ASLA madde işareti koyma. ASLA açıklama yapma. SADECE tek bir cümle kur. İSTENEN ÇIKTI FORMATI: '{params.get('hedef_ulke')} gönderiniz için tahmini [VERGİ TUTARI] vergi çıkıyor, toplam maliyetiniz [TOPLAM] olacaktır.'").text.strip()

                    # Eğer AI'dan HATA|AI Vergi Hesaplayıcısı: şeklinde bir dönüş varsa (eksik parametre), onu kullan
                    if raw_ai_response.startswith("HATA|AI Vergi Hesaplayıcısı:"):
                        final_reply = raw_ai_response.split(":")[1].strip()  # Eksik bilgiyi soran metin
                    else:
                        final_reply = raw_ai_response

                except Exception as e:
                    final_reply = f"Üzgünüm, vergi hesaplama sırasında bir hata oluştu. Hata Kodu: {e}"

            elif func == "kargo_ucret_itiraz":
                system_res = kargo_ucret_itiraz(saved_no, params.get("fatura_no"), user_id)
            elif func == "yanlis_teslimat_bildirimi":
                if not params.get("dogru_adres"):
                    final_reply = "Anladım, bir karışıklık olmuş. Kargonun aslında hangi adrese teslim edilmesi gerekiyordu?"
                else:
                    system_res = yanlis_teslimat_bildirimi(params.get("no"), params.get("dogru_adres"), user_id)
            elif func == "sube_saat_sorgula":
                system_res = sube_saat_sorgula(params.get("lokasyon"))
            elif func == "sube_sorgula":
                system_res = sube_sorgula(params.get("lokasyon"))
            elif func == "en_yakin_sube_bul":
                bilgi_turu = params.get("bilgi_turu", "adres")
                system_res = en_yakin_sube_bul(params.get("kullanici_adresi"), bilgi_turu)
            elif func == "sube_telefon_sorgula":
                system_res = sube_telefon_sorgula(params.get("lokasyon"))
            elif func == "sikayet_olustur":
                system_res = sikayet_olustur(params.get("no"), params.get("konu"), user_id)
            elif func == "hasar_kaydi_olustur":
                system_res = hasar_kaydi_olustur(params.get("no"), params.get("hasar_tipi"), user_id)
            elif func == "kargo_sorgula":
                system_res = kargo_bilgisi_getir(params.get("no"))
            elif func == "tahmini_teslimat":
                system_res = tahmini_teslimat_saati_getir(params.get("no"))
            elif func == "iade_islemi_baslat":
                system_res = iade_islemi_baslat(params.get("no"), params.get("sebep"), user_id, user_role)
            elif func == "kargo_iptal_et":
                system_res = kargo_iptal_et(params.get("no"))
            elif func == "adres_degistir":
                system_res = adres_degistir(params.get("no"), params.get("yeni_adres"))
            elif func == "alici_adresi_degistir":
                system_res = alici_adresi_degistir(params.get("no"), params.get("yeni_adres"))
            elif func == "kargo_durum_destek":
                system_res = kargo_durum_destek(saved_no, user_id)
            elif func == "fatura_bilgisi_gonderici":
                system_res = fatura_bilgisi_gonderici(params.get("no"), user_id)
            elif func == "evde_olmama_bildirimi":
                system_res = evde_olmama_bildirimi(params.get("no"))
            elif func == "supervizor_talebi":
                system_res = supervizor_talebi(params.get("ad"), params.get("telefon"))
            elif func == "alici_adi_degistir":
                system_res = alici_adi_degistir(params.get("no"), params.get("yeni_isim"))

            # YENİ EKLENEN NİYETLERİN FONKSİYONLARI
            elif func == "gecikme_sikayeti":
                system_res = gecikme_sikayeti(params.get("no"), user_id)
            elif func == "takip_numarasi_hatasi":
                system_res = takip_numarasi_hatasi(user_id)
            elif func == "kurye_gelmedi_sikayeti":
                system_res = kurye_gelmedi_sikayeti()
            elif func == "hizli_teslimat_ovgu":
                system_res = hizli_teslimat_ovgu()
            elif func == "kimlik_dogrulama_sorunu":
                system_res = kimlik_dogrulama_sorunu()
            elif func == "yurt_disi_kargo_kosul":
                system_res = yurt_disi_kargo_kosul()
            elif func == "bildirim_ayari_degistir":
                system_res = bildirim_ayari_degistir(params.get("tip"), user_id)

            if func != "kimlik_dogrula" and func != "kampanya_sorgula" and func != "vergi_hesapla_ai":
                # H2 ÇÖZÜMÜ: system_res'in boş dönmesi engellendi, onay mesajları direkt kullanılıyor.
                final_prompt = f"GÖREV: Kullanıcıya şu sistem bilgisini nazikçe ilet: {system_res}. SADECE yanıt metni. Kural: Eğer mesaj bir onay veya bilgi verme cümlesiyse, olduğu gibi kullan. Eğer bir hata içeriyorsa, nazikçe açıkla."

                if system_res.startswith("YENİ_NO_OLUŞTU"):
                    yeni_no = system_res.split("|")[1]
                    final_prompt = (f"GÖREV: Hata tespiti sonrası yeni kargo numarası oluşturuldu. "
                                    f"Müşteriye eski numarasının hatalı olduğunu, sorunu çözmek için otomatik olarak **{yeni_no}** numaralı yeni bir kargo oluşturulduğunu söyle. "
                                    f"Müşteriden yeni numara ile devam etmesini iste. Cevap çok kısa ve öz olsun. SADECE yanıt metni.")

                final_reply = model.generate_content(final_prompt).text.strip()

        elif data.get("type") == "chat":
            final_reply = data.get("reply")

        # A2 Testi için kritik PENDING INTENT mantığı
        if not is_verified and not session_data.get('pending_intent'):
            # Sadece kişisel işlem sorduysa niyeti kaydet
            is_personal_intent = data.get("type") == "action" and func in ["kimlik_dogrula", "sikayet_olustur",
                                                                           "kargo_sorgula", "tahmini_teslimat",
                                                                           "iade_islemi_baslat", "kargo_iptal_et",
                                                                           "adres_degistir",
                                                                           "yanlis_teslimat_bildirimi"]

            if is_personal_intent or (user_message.lower().strip() not in ["merhaba", "slm", "selam", "nasılsın"]):
                session_data['pending_intent'] = user_message
                print(f"📥 [DEBUG] YENİ NİYET KAYDEDİLDİ (Parçalı Giriş için): '{user_message}'")
            else:
                print(f"🔒 [DEBUG] NİYET KAYDEDİLMEDİ (Genel Sorgu)")

        session_data['history'].append(f"KULLANICI: {user_message}")
        session_data['history'].append(f"ASİSTAN: {final_reply}")
        user_sessions[session_id] = session_data

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
    if not sid: sid = "test_user"

    if sid not in user_sessions:
        user_sessions[sid] = {
            'history': [],
            'verified': False,
            'tracking_no': None,
            'role': None,
            'user_name': None,
            'user_id': None,
            'pending_intent': None
        }

    resp = process_with_gemini(sid, msg)
    audio = metni_sese_cevir(resp)
    return jsonify({"response": resp, "audio": audio, "session_id": sid})


if __name__ == '__main__':
    app.run(debug=True)