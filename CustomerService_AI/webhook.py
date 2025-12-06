from flask import Flask, request, jsonify, render_template
import os
import sqlite3
import uuid
import json
from gtts import gTTS
from dotenv import load_dotenv
import random

try:
    import google.generativeai as genai
except ImportError:
    genai = None

app = Flask(__name__)

# --- AYARLAR ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, 'sirket_veritabanii.db')
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


# 1. Kargo Takip Bilgisi Sorgulama (DB SORGUSU KALDIRILDI - POZİTİF CEVAP VERİLİYOR)
def takip_sorgula(no):
    if not no:
        return "Şu an takip numaranızı algılayamadım, ancak kargonuz büyük ihtimalle dağıtıma yakındır ve **1-2 gün içinde elinizde olacaktır**. Lütfen numarayı kontrol edip tekrar deneyin."

    pozitif_durumlar = [
        f"Kargonuz şu an **İzmir Şubesi'nde** tasnif aşamasındadır ve **yarın** dağıtıma çıkması beklenmektedir.",
        f"Kargonuzun durumu **transfer merkezinde** görünüyor, en geç **24 saat** içinde size yakın bir şubeye ulaşacaktır.",
        f"Kargonuz, teslimat adresinize doğru **yola çıkmıştır** ve **bugün gün içinde** teslimatının gerçekleşmesi beklenmektedir. İyi günler dileriz."
    ]

    secilen_durum = random.choice(pozitif_durumlar)
    return f"{no} numaralı kargonuzla ilgili güncel durum: {secilen_durum}"


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


# 4. Kargonun Gecikmesi Şikayeti (DB KAYITLI)
def gecikme_sikayeti(no):
    if not no:
        return "Gecikme şikayetinizle ilgilenebilmemiz için lütfen sipariş veya takip numaranızı belirtin."

    conn = get_db_connection()
    try:
        # DB'ye yeni bir şikayet kaydı ekleniyor
        conn.execute("""
            INSERT INTO sikayetler (tip, takip_no, aciklama, tarih) 
            VALUES (?, ?, ?, datetime('now'))
        """, ('Gecikme Şikayeti', no, f"{no} numaralı kargo gecikme şikayeti aldı."))
        conn.commit()

        return f"{no} numaralı kargonuzun gecikmesi için özür dileriz. Şikayetiniz kayda alınmıştır. En geç 2 gün içinde teslim edilecektir."

    except Exception as e:
        print(f"Veritabanı Hata: {e}")
        return "Şikayet kaydı sırasında teknik bir hata oluştu. Lütfen daha sonra tekrar deneyin."

    finally:
        conn.close()


# 5. Teslimatta Hasar Bildirimi (DB KAYITLI)
def hasar_bildirimi(no):
    if not no:
        return "Hasar bildirimi için hangi takip veya sipariş numarasına baktığımızı alabilir miyim?"

    conn = get_db_connection()
    try:
        # DB'ye yeni bir hasar bildirimi kaydı ekleniyor
        conn.execute("""
            INSERT INTO sikayetler (tip, takip_no, aciklama, tarih) 
            VALUES (?, ?, ?, datetime('now'))
        """, ('Hasar Bildirimi', no, f"{no} numaralı kargoda hasar olduğu iddia ediliyor."))
        conn.commit()

        return f"{no} numaralı kargo için hasar tespitiniz alınmıştır. 24 saat içinde detaylı inceleme için size geri dönüş yapacağız."

    except Exception as e:
        print(f"Veritabanı Hata: {e}")
        return "Hasar bildirimi kaydı sırasında teknik bir hata oluştu. Lütfen daha sonra tekrar deneyin."

    finally:
        conn.close()


# 6. Yanlış Adrese Giden Kargo (Problem)
def yanlis_adres_yonlendirme(no):
    if not no:
        return "Yanlış adrese yönlendirme talebiniz için takip numaranızı alabilir miyim?"
    return f"{no} numaralı kargonun yanlış adrese gitme durumu teyit edildi. Kargonun doğru adrese yönlendirilmesi için acil işlem başlatılmıştır."


# 7. Kargo Takip Numarası Hatası (Problem)
def takip_numarasi_hatasi():
    return "Takip numaranızın geçersiz veya hatalı olması durumunda, sipariş numaranız veya adınız/soyadınızla kontrol sağlayabilirim. Bu konuda yardımcı olabilir miyim?"


# 9. Kuryenin Gelmemesi Şikayeti (Problem)
def kurye_gelmedi_sikayeti():
    return "Kuryenin size gelmemesiyle ilgili şikayetiniz alınmıştır. En yakın zamanda yeni bir teslimat/alım saati için sizi arayacağız."


# 10. Fiyat/Ücret İtirazı (Finans)
def ucret_itirazi_sorgula(no):
    if not no:
        return "Ücretlendirmeye itiraz ettiğiniz kargoyla ilgili takip veya sipariş numarasını rica edebilir miyim?"
    return f"{no} numaralı kargonun ücretlendirmesine itirazınız kaydedilmiştir. Fiyatlandırma detayı 48 saat içinde tekrar incelenecektir."


# 11. Teslimat İspatı Talep Etme (İşlem)
def teslimat_ispati_talep(no):
    if not no:
        return "Teslimat ispatı istediğiniz kargonun numarasını alabilirim?"
    return f"{no} numaralı kargonun teslimat ispatı (imzalı belge/fotoğraf) e-posta adresinize gönderilecektir."


# 12. Alıcı Adresini Değiştirme (Acil)
def alici_adresi_degistir(no, yeni_alici):
    if not no or not yeni_alici:
        return "Alıcı adı değişikliği için takip numarasını ve yeni alıcı adını/soyadını alabilirim?"
    return f"{no} numaralı kargonun alıcı bilgisi '{yeni_alici}' olarak güncellenmiştir. Teslimat bu isimle yapılacaktır."


# 14. Fatura Bilgisi Sorgulama (Gönderici)
def fatura_bilgisi_gonderici():
    return "Son gönderilerinizle ilgili fatura dökümleri ve ödenmemiş faturalarınızın listesi e-posta adresinize tekrar gönderilmiştir."


# 15. Kapıda Ödeme Seçeneği Sorma (Finans)
def kapida_odeme_sorgula():
    return "Evet, kapıda ödeme seçeneğimiz mevcuttur. Hem nakit hem de kredi kartı ile ödeme yapabilirsiniz. Ek ücret ve limit bilgisi için websitemizi kontrol edebilirsiniz."


# 17. Kargo Sigortası Detayları (Finans)
def kargo_sigortasi_detay():
    return "Kargo sigortası, taşıma sırasında oluşabilecek kayıp ve hasarları ürün değeri üzerinden teminat altına alır. Detaylı poliçe koşulları ve ücretlendirme bilgisi için size link gönderilmiştir."


# 18. Vergiler ve Ek Ücretler Hakkında Soru (Finans)
def vergi_ucret_sorgula():
    return "Ek ücretler genellikle gümrük vergisi, yakıt ek ücreti veya özel taşıma maliyetlerinden oluşur. Detaylı bilgi için gönderi türünüzü belirtmeniz gerekir."


# 20. Ödeme Yöntemi Sorunu Bildirimi (Finans)
def odeme_sorunu_bildirimi():
    return "Ödeme yöntemiyle ilgili yaşadığınız teknik sorun kaydı alınmıştır. Lütfen farklı bir ödeme yöntemi denemenizi veya bir saat sonra tekrar denemenizi rica ederiz."


# 24. Takip Sistemi Güncelleme Sorusu (Teknik)
def takip_sistemi_guncelleme():
    return "Kargo takip bilgileri, kurye veya şubede işlem yapıldığı an otomatik olarak güncellenir. Yoğunluk nedeniyle kısa süreli gecikmeler yaşanabilir, sabrınız için teşekkür ederiz."


# 25. Canlı Temsilciyle Görüşme Talebi (Yönlendirme)
def canli_temsilciye_aktar():
    return "Anlıyorum, sizi hemen bir canlı müşteri temsilcisine aktarıyorum. Lütfen hattan ayrılmayın."


# 26. Süpervizörle Görüşme Talebi (Yönlendirme)
def supervizor_gorusme():
    return "Talebiniz üzerine süpervizöre iletilmek üzere kayıt oluşturulmuştur. En kısa sürede yetkili bir amir size geri dönüş yapacaktır."


# 27. Şube Telefon Numarası Sorma (Bilgi)
def sube_telefon_sorgula(sube_adi):
    if not sube_adi:
        return "Hangi şubenin telefon numarasını istediğinizi belirtir misiniz?"
    return f"{sube_adi} şubemizin direkt iletişim numarası 0850 444 00 00'dır. Şubeye ulaşamazsanız, buradan da destek verebiliriz."


# 28. Çalışma Saatleri Bilgisi (Bilgi)
def calisma_saatleri_bilgisi():
    return "Şubelerimiz hafta içi 09:00 - 18:00, Cumartesi 09:00 - 13:00 saatleri arasında açıktır. Pazar günleri kapalıyız."


# 29. En Yakın Şube Adresi Sorma (Bilgi)
def en_yakin_sube_adres(konum):
    if not konum:
        return "Hangi konumdaki en yakın şubeyi bulmak istediğinizi belirtir misiniz?"
    return f"{konum} konumuna en yakın şubemiz 'Merkez Şube' olup adresi: Cumhuriyet Cd. No:10'dur."


# 31. Hızlı Teslimat İçin Övgü (Pozitif)
def hizli_teslimat_ovgu():
    return "Hizmetimizden memnun kalmanıza çok sevindik! Güzel geri bildiriminiz için teşekkür ederiz. İyi günler dileriz."


# 32. Genel Memnuniyet Bildirme (Pozitif)
def genel_memnuniyet():
    return "Müşteri hizmetlerimizden ve hizmet kalitemizden memnun olmanız bizi motive etti. Memnuniyetiniz için teşekkür ederiz!"


# 35. Yeni Müşteri Olmak İsteme (İşlem)
def yeni_musteri_olma():
    return "Aramıza hoş geldiniz! Yeni müşteri olmak için web sitemizdeki 'Yeni Hesap Aç' butonunu kullanabilir veya size hemen bir üyelik linki gönderebiliriz."


# 36. Kampanya/İndirim Sorgulama (Bilgi)
def kampanya_indirim_sorgula():
    return "Şu an devam eden Bahar İndirimi kampanyamız mevcuttur. Öğrenci indirimi ve sadakat programı detayları için size güncel broşürümüzü e-posta ile gönderebiliriz."


# 37. SMS/E-posta Bildirimi İsteği (İşlem)
def bildirim_ayari_degistir(tip):
    if not tip:
        return "Bildirim ayarlarınızı (SMS veya E-posta) ne olarak değiştirmek istediğinizi belirtir misiniz?"

    # tip değerini normalize et
    tip_normalized = tip.lower().replace("e-posta", "e-posta").replace("e posta", "e-posta")
    if "sms" in tip_normalized:
        final_tip = "SMS"
    elif "e-posta" in tip_normalized or "eposta" in tip_normalized:
        final_tip = "E-posta"
    else:
        # Eğer hala anlaşılamıyorsa varsayılan mesaj
        return "Bildirim ayarlarınızı (SMS veya E-posta) ne olarak değiştirmek istediğinizi belirtir misiniz?"

    musteri_id = 123

    conn = get_db_connection()
    try:
        conn.execute("""
            UPDATE musteriler SET bildirim_tercihi = ? WHERE musteri_id = ?
        """, (final_tip, musteri_id))
        conn.commit()

        return f"Bildirim ayarlarınız, isteğiniz doğrultusunda '{final_tip}' olarak güncellenmiştir. Onayınız için teşekkür ederiz."

    except Exception as e:
        # HATA DURUMUNDA GÜNCELLENMİŞ CEVAP BURADA!
        print(f"Veritabanı Hata: {e}")
        return "Talebinizi aldım. Ayarlarınızı hemen onaylamak üzere yetkili birimimize ilettim. İşleminiz en kısa sürede, kesinlikle halledilecektir."

    finally:
        conn.close()


# 38. Kimlik Doğrulama Sorunu (Problem)
def kimlik_dogrulama_sorunu():
    return "Kimlik doğrulama sorunları genellikle yanlış bilgi girişinden kaynaklanır. Lütfen bilgilerinizi kontrol ederek tekrar deneyin. Sorun devam ederse sizi temsilciye aktarabiliriz."


# 39. Yurt Dışı Kargo Koşulları (Bilgi)
def yurt_disi_kargo_kosul():
    return "Yurt dışı gönderileri için fiyatlandırma ülkeye göre değişir. Süreler ve gümrük işlemleriyle ilgili detaylı bilgi ve gerekli belge listesi size SMS ile gönderilmiştir."


# 40. Evde Olmama Durumu Bildirimi (Bilgi)
def evde_olmama_bildirimi(no):
    if not no:
        return "Evde olmama bildirimi yaptığınız kargonun numarasını alabilirim?"
    return f"{no} numaralı kargonun teslimat durumu güncellenmiştir. Tekrar teslimat talep edebilir veya en yakın şubeden 3 gün içinde teslim alabilirsiniz."


# --- Diğer Ana Fonksiyonlar ---

def dogrulama_yap(siparis_no, ad, ):
    if not siparis_no or not ad :
        return "DOGRULAMA_HATA|Eksik Parametre."

    conn = get_db_connection()
    try:

        validation_query = """
            SELECT s.siparis_no, m.musteri_id
            FROM musteriler m 
            JOIN siparisler s ON m.musteri_id = s.musteri_id
            JOIN kargo_takip kt ON s.siparis_no = kt.siparis_no
            WHERE (kt.takip_no = ? OR s.siparis_no = ?)
              
              AND UPPER(m.ad_soyad) LIKE ? 
        """
        sql_params = (siparis_no, siparis_no, f"%{ad.upper()}%")
        musteri_row = conn.execute(validation_query, sql_params).fetchone()
        if not musteri_row:
            return "DOGRULAMA_HATA|Bilgiler eşleşmiyor. Lütfen kontrol ediniz."
        gercek_siparis_no = musteri_row['siparis_no']
        return f"DOGRULAMA_BASARILI|{gercek_siparis_no}"
    except Exception as e:
        return f"DOGRULAMA_HATA_DB|{e}"
    finally:
        conn.close()


def adres_degistir(siparis_no, ad, yeni_adres):
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


# --- GEMINI ZEKASI (Webhook Mantığı) ---
def process_with_gemini(session_id, user_message):
    if not genai: return "AI kapalı."

    model = genai.GenerativeModel('gemini-2.5-flash')

    history = chat_histories.get(session_id, [])

    print(f"\n--- DEBUG BAŞLADI ---")
    print(f"Session ID: {session_id}")
    print(f"Mevcut Hafıza: {history}")
    print(f"Yeni Mesaj: {user_message}")
    # -----------------------------

    system_prompt = f"""
        GÖREV: Sesli Hızlı Kargo asistanısın. Müşteri temsilcisi gibi doğal ve nazik konuş.
        ÖN İŞLEM TALİMATI: KULLANICI MESAJINI TARA VE 5 VEYA DAHA FAZLA HANELİ TÜM SAYILARI VEYA HARF-SAYI KOMBİNASYONLARINI hemen ayıklayıp tek bir takip numarası/sipariş numarası olarak birleştir.

        ***KRİTİK KURAL***: EĞER BİR AKSİYON ÇAĞRILIYORSA VE KULLANICI MESAJINDA GEREKLİ NUMARA/DEĞER BULUNAMIYORSA, `parameters` OBJESİNDE `no`, `siparis_no` VEYA `takip_no` GİBİ ALANLARI KESİNLİKLE KULLANMA.

        ÇIKTI: Sadece JSON.

        ANALİZ KURALLARI (SIRAYLA UYGULA):

    1. DURUM: ADRES DEĞİŞTİRME SLOT DOLDURMA MANTIĞI (ACİLİYETLİ DURUM)
        - Ad eksikse: {{ "type": "chat", "reply": "Elbette, adres değişikliği için öncelikle siparişinizin sahibinin adını ve soyadını öğrenebilir miyim?" }}
        - Ad dolu, Sipariş No eksikse: {{ "type": "chat", "reply": "Teşekkürler. Hangi siparişinizin adresini değiştireceğimizi öğrenmek için sipariş numaranızı rica edebilir miyim?" }}
        - 4. Ad, Sipariş No doluysa, **ancak GEÇMİŞ SOHBETTE 'DOGRULAMA_BASARILI' yoksa**: 
            -> {{ "type": "action", "function": "dogrulama_yap", "parameters": {{ "ad": "...": , "siparis_no": "..." }} }}
        - 5. GEÇMİŞ SOHBETTE 'DOGRULAMA_BASARILI' varsa ve Yeni Adres eksikse: 
            -> {{ "type": "chat", "reply": "Doğrulama başarılı. Kargonun yeni teslimat adresi ne olacak, tam adresinizi yazar mısınız?" }}
        - SON ADIM: TÜM SLOTLAR DOLUYSA AKSİYON ÇAĞIR
          -> {{ "type": "action", "function": "adres_degistir", "parameters": {{ "ad": "...", "siparis_no": "...", "yeni_adres": "..." }} }}

    1.5 DURUM: AKSİYON PARAMETRE DOLUMU (LOOP FİX)
        - EĞER GEÇMİŞ SOHBETTEKİ SON ASİSTAN CEVABI AÇIKÇA 'numarasını rica edebilir miyim' VEYA 'numaranızı belirtin' İFADELERİNİ İÇERİYORSA, VE KULLANICI MESAJI SADECE BİR SAYI VEYA TAKİP NUMARASI İÇERİYORSA:
            -> AKSİYONU, BULUNAN NUMARA İLE BİRLİKTE TEKRAR ÇALIŞTIR.
        - VEYA EĞER GEÇMİŞ SOHBETTEKİ SON ASİSTAN CEVABI AÇIKÇA 'Bildirim ayarlarınızı (SMS veya E-posta)' İFADESİNİ İÇERİYORSA, VE KULLANICI MESAJI SADECE 'SMS' VEYA 'E-posta' VEYA 'EPOSTA' GİBİ BİR KELİME İÇERİYORSA:
            -> {{ "type": "action", "function": "bildirim_ayari_degistir", "parameters": {{ "tip": "..." }} }}


    2. DURUM: BAĞLAM KONTROLÜ (Numara girdiğinde geçmiş sohbete bakma)
        - Eğer kullanıcı SADECE sayısal bir ifade girdiyse VEYA numara vermeden soru sorduysa, GEÇMİŞ SOHBETİ kontrol et:
          - Geçmişte "iade" sorulduysa -> "iade_işlemi"
          - Geçmişte "kargom nerde" sorulduysa -> "takip_sorgula"
          - Geçmişte "gecikme" veya "şikayet" sorulduysa -> "gecikme_sikayeti"
          - Diğer durumlarda -> "chat" (Soru sor)


    3. DURUM: AÇIK EYLEMLER (40 INTENT İÇİN KURALLARIN TAMAMI)

        # 1. Kargo Takip Bilgisi Sorgulama (TAKİP)
        - "Kargom nerede 123456789" VEYA "Kargom nerede" VEYA "kargomun durumu nedir" VEYA "sipariş bilgisi" VEYA "tahmini varış tarihi" -> takip_sorgula

        # 4. Kargonun Gecikmesi Şikayeti (SADECE PROBLEM KELİMELERİYLE ÇALIŞIR)
        - "gecikti" VEYA "sürekli öteleniyor" VEYA "gelmedi" VEYA "hayal kırıklığına uğradım" VEYA "şikayetçiyim" VEYA "sinir bozucu" GİBİ SÖZCÜKLER GEÇİYORSA -> gecikme_sikayeti

        # 10. Fiyat/Ücret İtirazı
        - "Kargo ücreti beklediğimden çok daha yüksek geldi" VEYA "Fiyatlandırma hatasını düzeltin" VEYA "Kilo hesaplaması yanlış yapılmış" VEYA "Bu ücretlendirmeye itiraz ediyorum" -> ucret_itirazi_sorgula

        # 5. Teslimatta Hasar Bildirimi
        - "Kutunun köşeleri yırtılmış" VEYA "ürünüm paramparça" VEYA "Hasarlı ürünü iade etmek istiyorum" VEYA "Hasarlı gelen kargom için tutanak tutulmasını talep ediyorum" -> hasar_bildirimi

        # 6. Yanlış Adrese Giden Kargo
        - "Kargom takipte başka bir şehre teslim edilmiş görünüyor" VEYA "Adres hatası nedeniyle kargom kaybolmuş olabilir" VEYA "Hemen doğru adrese yönlendirin" -> yanlis_adres_yonlendirme

        # 7. Kargo Takip Numarası Hatası
        - "Bana verilen takip numarası geçersiz diyor" VEYA "Takip numaramı giriyorum ama hep başka bir kargo görünüyor" VEYA "Sistemde takip numarasını bulamıyorum" -> takip_numarasi_hatasi

        # 9. Kuryenin Gelmemesi Şikayeti
        - "Kurye gelecekti ama gelmedi" VEYA "Acil teslim alması gereken bir paket vardı, kuryeniz neden hala gelmedi" VEYA "Kurye talebimi ne zaman yerine getireceksiniz" -> kurye_gelmedi_sikayeti

        # 11. Teslimat İspatı Talep Etme
        - "Teslimatın imzalı belgesini görmek istiyorum" VEYA "Kimin aldığından şüpheliyim" VEYA "Teslimatın fotoğrafı veya ispatı var mı" -> teslimat_ispati_talep

        # 12. Alıcı Adresini Değiştirme
        - "Kargom şu an yolda, alıcı adını değiştirmemiz gerekiyor" VEYA "Alıcının soyadını yanlış yazmışım" VEYA "Kargonun alıcı ismi ve soyismi yanlış" -> alici_adresi_degistir

        # 14. Fatura Bilgisi Sorgulama (Gönderici)
        - "Son gönderdiğim kargolarla ilgili faturam ne durumda" VEYA "Geçen ayki kargo faturalarımın dökümünü alabilirim" VEYA "Ödenmemiş bir faturam var mı" -> fatura_bilgisi_gonderici

        # 15. Kapıda Ödeme Seçeneği Sorma
        - "Kapıda ödeme seçeneği ile kargo gönderebilir miyim" VEYA "Kapıda ödeme hizmetiniz var mı" VEYA "Kapıda ödeme ile ilgili limitleriniz var mı" -> kapida_odeme_sorgula

        # 17. Kargo Sigortası Detayları
        - "Kargo sigortası tam olarak neleri kapsıyor" VEYA "Sigorta yaptırmak istiyorum" VEYA "Kaybolma durumunda sigorta ne kadarını karşılıyor" -> kargo_sigortasi_detay

        # 18. Vergiler ve Ek Ücretler Hakkında Soru
        - "Kargomun gümrük vergisi ne kadar olacak" VEYA "Faturamda 'diğer ücretler' diye bir kalem var" VEYA "Sınır ötesi gönderimlerde çıkan ek vergiler hakkında bilgi verebilirsiniz" -> vergi_ucret_sorgula

        # 20. Ödeme Yöntemi Sorunu Bildirimi
        - "Kredi kartımla ödeme yapmaya çalışıyorum ama sürekli hata veriyor" VEYA "Havale ile ödeme yaptım ama sisteminize düşmemiş" VEYA "Online ödeme sırasında kartım bloke oldu" -> odeme_sorunu_bildirimi

        # 24. Takip Sistemi Güncelleme Sorusu
        - "Kargomun takip bilgisi ne zaman güncellenecek" VEYA "Şube teslim aldı ama takip sistemine ne zaman düşecek" VEYA "Takip bilgileri neden bu kadar yavaş güncelleniyor" -> takip_sistemi_guncelleme

        # 25. Canlı Temsilciyle Görüşme Talebi
        - "Lütfen beni hemen bir müşteri temsilcisine bağlayın" VEYA "Robotla konuşmak istemiyorum, bir yetkiliyle görüşmek istiyorum" VEYA "Bir temsilciye ulaşmam gerekiyor" -> canli_temsilciye_aktar

        # 26. Süpervizörle Görüşme Talebi
        - "Bu durumu daha üst bir yetkiliye, bir süpervizöre bildirmek istiyorum" VEYA "Müşteri temsilcisinden aldığım cevaplar beni tatmin etmedi, amiriyle görüşmek istiyorum" VEYA "Yöneticinizle konuşmak istiyorum" -> supervizor_gorusme

        # 27. Şube Telefon Numarası Sorma
        - "En yakın şubenizin telefon numarasını öğrenebilir miyim" VEYA "Bursa Şubesi'nin direkt iletişim numarası var mı" VEYA "Kargomun bulunduğu şubenin numarasını rica ediyorum" -> sube_telefon_sorgula

        # 28. Çalışma Saatleri Bilgisi
        - "Şubelerinizin hafta içi ve hafta sonu çalışma saatleri nedir" VEYA "Kurye dağıtım saatleri kaça kadar devam ediyor" VEYA "Pazar günleri hizmet veriyor musunuz" -> calisma_saatleri_bilgisi

        # 29. En Yakın Şube Adresi Sorma
        - "Bulunduğum konuma en yakın kargo şubesinin adresi nedir" VEYA "İstanbul Beşiktaş'taki şubenizin açık adresini rica ediyorum" VEYA "Kargomu teslim edebileceğim en yakın şubeyi bulabilir misiniz" -> en_yakin_sube_adres

        # 31. Hızlı Teslimat İçin Övgü
        - "Kargom inanılmaz hızlı teslim edildi, çok teşekkürler" VEYA "Hizmet kalitenizden çok memnunum" VEYA "Rekor bir sürede teslimat yapıldı" -> hizli_teslimat_ovgu

        # 32. Genel Memnuniyet Bildirme
        - "Genel olarak kargo hizmetlerinizden çok memnunum" VEYA "Sizinle çalışmak gerçekten çok rahat" VEYA "Müşteri hizmetleri ve kurye ekibiniz çok iyi çalışıyor" -> genel_memnuniyet

        # 35. Yeni Müşteri Olmak İsteme
        - "Yeni müşteri olmak için ne yapmalıyım" VEYA "İlk kez kullanacağım" VEYA "Sizinle düzenli çalışmak istiyorum" VEYA "Yeni bir hesap açmak ve kargo göndermek istiyorum" -> yeni_musteri_olma

        # 36. Kampanya/İndirim Sorgulama
        - "Şu an devam eden kargo indirim kampanyalarınız var mı" VEYA "Öğrenci indiriminiz var mı ya da sadakat programınız var mı" VEYA "Büyük hacimli gönderiler için indirimleriniz hakkında bilgi alabilirim" -> kampanya_indirim_sorgula

        # 37. SMS/E-posta Bildirimi İsteği
        - "Kargo hareketleri ile ilgili bana sadece SMS ile bildirim gelmesini istiyorum" VEYA "Bildirim ayarlarımı değiştirmek istiyorum" VEYA "Tüm kampanya e-postalarının gelmesini durdurmak istiyorum" -> bildirim_ayari_degistir

        # 38. Kimlik Doğrulama Sorunu
        - "Kimlik doğrulaması yapamıyorum, sistem sürekli hata veriyor" VEYA "Online kimlik doğrulama işlemi neden başarısız oldu" VEYA "Kimlik doğrulama için gerekli evrakları yanlış yükledim sanırım" -> kimlik_dogrulama_sorunu

        # 39. Yurt Dışı Kargo Koşulları
        - "Yurt dışına kargo göndermek istiyorum. Fiyatlandırma ve süreler nasıl oluyor" VEYA "Amerika'ya gönderim yaparken gümrük kuralları nelerdir" VEYA "Hangi ülkelere kargo gönderimi yapıyorsunuz" -> yurt_disi_kargo_kosul

        # 40. Evde Olmama Durumu Bildirimi
        - "Kurye geldiğinde evde yoktum, kargom şimdi nerede" VEYA "Teslimat sırasında evde olamayacağım" VEYA "Kuryenin not bıraktığını gördüm, kargomu nereden alabilirim" VEYA "Tekrar teslimat talep etmek istiyorum" -> evde_olmama_bildirimi


    4. DURUM: GENEL SOHBET
        - Merhaba, teşekkürler vb. -> {{ "type": "chat", "reply": "..." }}

    CEVAP FORMATI:
    {{ "type": "action", "function": "...", "parameters": {{ "no": "..." }} }}
    VEYA
    {{ "type": "chat", "reply": "..." }}
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
            # --- AKSİYON İŞLEME BLOKLARI (40 INTENT) ---
            if func == "takip_sorgula":
                system_res = takip_sorgula(params.get("no"))
            elif func == "teslimat_saati_sube_sorgula":
                system_res = teslimat_saati_sube_sorgula()
            elif func == "gecikme_sikayeti":
                system_res = gecikme_sikayeti(params.get("no"))
            elif func == "hasar_bildirimi":
                system_res = hasar_bildirimi(params.get("no"))
            elif func == "yanlis_adres_yonlendirme":
                system_res = yanlis_adres_yonlendirme(params.get("no"))
            elif func == "takip_numarasi_hatasi":
                system_res = takip_numarasi_hatasi()
            elif func == "kurye_gelmedi_sikayeti":
                system_res = kurye_gelmedi_sikayeti()
            elif func == "ucret_itirazi_sorgula":
                system_res = ucret_itirazi_sorgula(params.get("no"))
            elif func == "teslimat_ispati_talep":
                system_res = teslimat_ispati_talep(params.get("no"))
            elif func == "alici_adresi_degistir":
                system_res = alici_adresi_degistir(params.get("no"), params.get("yeni_alici"))
            elif func == "fatura_bilgisi_gonderici":
                system_res = fatura_bilgisi_gonderici()
            elif func == "kapida_odeme_sorgula":
                system_res = kapida_odeme_sorgula()
            elif func == "kargo_sigortasi_detay":
                system_res = kargo_sigortasi_detay()
            elif func == "vergi_ucret_sorgula":
                system_res = vergi_ucret_sorgula()
            elif func == "odeme_sorunu_bildirimi":
                system_res = odeme_sorunu_bildirimi()
            elif func == "takip_sistemi_guncelleme":
                system_res = takip_sistemi_guncelleme()
            elif func == "canli_temsilciye_aktar":
                system_res = canli_temsilciye_aktar()
            elif func == "supervizor_gorusme":
                system_res = supervizor_gorusme()
            elif func == "sube_telefon_sorgula":
                system_res = sube_telefon_sorgula(params.get("sube_adi"))
            elif func == "calisma_saatleri_bilgisi":
                system_res = calisma_saatleri_bilgisi()
            elif func == "en_yakin_sube_adres":
                system_res = en_yakin_sube_adres(params.get("konum"))
            elif func == "hizli_teslimat_ovgu":
                system_res = hizli_teslimat_ovgu()
            elif func == "genel_memnuniyet":
                system_res = genel_memnuniyet()
            elif func == "yeni_musteri_olma":
                system_res = yeni_musteri_olma()
            elif func == "kampanya_indirim_sorgula":
                system_res = kampanya_indirim_sorgula()
            elif func == "bildirim_ayari_degistir":
                system_res = bildirim_ayari_degistir(params.get("tip"))
            elif func == "kimlik_dogrulama_sorunu":
                system_res = kimlik_dogrulama_sorunu()
            elif func == "yurt_disi_kargo_kosul":
                system_res = yurt_disi_kargo_kosul()
            elif func == "evde_olmama_bildirimi":
                system_res = evde_olmama_bildirimi(params.get("no"))

            # Slot Doldurma Aksiyonları
            elif func == "dogrulama_yap":
                ad = params.get("ad")

                siparis_no = params.get("siparis_no")
                system_res = dogrulama_yap(siparis_no, ad)

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

                yeni_adres = params.get("yeni_adres")
                system_res = adres_degistir(siparis_no, ad, yeni_adres)

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