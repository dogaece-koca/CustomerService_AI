from modules.database import kimlik_dogrula, ucret_hesapla, kampanya_sorgula, kargo_ucret_itiraz, \
    yanlis_teslimat_bildirimi, sube_saat_sorgula, sube_sorgula, en_yakin_sube_bul, sube_telefon_sorgula, \
    sikayet_olustur, hasar_kaydi_olustur, kargo_bilgisi_getir, tahmini_teslimat_saati_getir, iade_islemi_baslat, \
    kargo_iptal_et, adres_degistir, alici_adresi_degistir, kargo_durum_destek, fatura_bilgisi_gonderici, \
    evde_olmama_bildirimi, supervizor_talebi, bildirim_ayari_degistir, takip_numarasi_hatasi, gecikme_sikayeti, \
    kurye_gelmedi_sikayeti, hizli_teslimat_ovgu, kimlik_dogrulama_sorunu, yurt_disi_kargo_kosul, \
    alici_bilgisi_guncelle
from modules.ml_modulu import duygu_analizi_yap, teslimat_suresi_hesapla
from dotenv import load_dotenv
from datetime import datetime
import math
import json
import os
import re

try:
    import google.generativeai as genai
except ImportError:
    genai = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_FOLDER = os.path.join(BASE_DIR, 'static')
ENV_FILE = os.path.join(BASE_DIR, '.env')

load_dotenv(ENV_FILE)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if genai and GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)


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
        sayi = re.search(r"\d+(\.\d+)?", text_mesafe)
        if sayi:
            return float(sayi.group())
        else:
            return 0

    except Exception as e:
        print(f"Mesafe hesaplama hatası: {e}")
        return 0


def vergi_hesapla_ai(urun_kategorisi, fiyat, hedef_ulke):
    print(f"DEBUG: vergi_hesapla_ai çalıştı -> {urun_kategorisi}, {fiyat}, {hedef_ulke}")

    if 'genai' not in globals():
        return "Üzgünüm, şu an yapay zeka servisine erişemiyorum."

    try:
        model = genai.GenerativeModel('gemini-2.5-flash')

        prompt = f"""
        GÖREV: Bir gümrük danışmanı gibi davran ve müşteriye yanıt ver.

        GİRDİLER:
        - Ürün: {urun_kategorisi}
        - Fiyat: {fiyat}
        - Hedef Ülke: {hedef_ulke}
        

        KURALLAR:
        1. Hedef ülkenin para birimini ($, €, £) tespit et ve hesaplamayı o birimle yap.
        2. Tahmini bir gümrük vergisi hesapla.
        3. ÇIKTI FORMATI: Sadece müşteriye söylenecek tek ve net bir cümle kur.
        4. EĞER BİLGİ EKSİKSE: (Örn: Fiyat yoksa) Kibarca eksik bilgiyi sor.
        5. ASLA JSON veya kod bloğu kullanma. Sadece düz yazı yaz.

        ÖRNEK CEVAP TİPİ:
        "{hedef_ulke} gönderiniz için tahmini 25 € gümrük vergisi çıkıyor."
        """

        response = model.generate_content(prompt)
        text_res = response.text.strip()

        text_res = text_res.replace("**", "").replace("```", "")

        return text_res

    except Exception as e:
        print(f"AI Hatası: {e}")
        return "Vergi hesaplama servisinde geçici bir yoğunluk var, lütfen daha sonra tekrar deneyin."

def process_with_gemini(session_id, user_message, user_sessions):
    if not genai: return "AI kapalı."

    model = genai.GenerativeModel('gemini-2.5-flash')


    simdi = datetime.now()
    tarih_str = simdi.strftime("%d.%m.%Y")
    gun_str = simdi.strftime("%A")
    saat_str = simdi.strftime("%H:%M")

    zaman_bilgisi = f"BUGÜNÜN TARİHİ: {tarih_str} ({gun_str}) - SAAT: {saat_str}"


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
        formatted_history_for_context = "\n".join(history[-4:])
        final_user_message = f"{user_message} (NOT: Kullanıcı daha önce '{pending_intent}' yapmak istediğini belirtti ve parça parça bilgi veriyor. Eksikleri tamamladıysa doğrulama yap. Geçmiş: {formatted_history_for_context})"

    duygu_durumu, duygu_skoru = duygu_analizi_yap(user_message)
    print(f"[NLP ANALİZİ] Müşteri Duygusu: {duygu_durumu} (Skor: {duygu_skoru})")

    duygu_notu = ""
    if "KIZGIN (NEGATİF)" in duygu_durumu:
        duygu_notu = "DİKKAT: Müşteri şu an ÖFKELİ görünüyor. Cevabında mutlaka alttan al, çok nazik ol, özür dile ve çözüm odaklı konuş. Asla tartışmaya girme."
    elif "MUTLU (POZİTİF)" in duygu_durumu:
        duygu_notu = "İPUCU: Müşteri MEMNUN görünüyor. Enerjik ve samimi bir dille teşekkür et."

    system_prompt = f"""
    GÖREV: Hızlı Kargo sesli asistanısın. {status_prompt}
    
    SİSTEM ZAMANI: {zaman_bilgisi}
    (Tüm tarih hesaplamalarını, 'bugün', 'yarın', '2 gün sonra' gibi ifadeleri yukarıdaki SİSTEM ZAMANI'na göre yap.)

    !!! KRİTİK DUYGU DURUMU ANALİZİ !!!
    {duygu_notu}

    ÖN İŞLEM: Tek tek söylenen sayıları birleştir (bir iki üç -> 123).
    ÇIKTI: SADECE JSON.

    !!! KESİN VE DEĞİŞMEZ KURAL !!!
    - CEVAPLARDA ASLA EMOJİ KULLANMA (Örn: 😊, 👋, 📦 YASAK). 
    - SADECE DÜZ METİN VE NOKTALAMA İŞARETLERİ KULLAN.
    
    # TUTARLILIK KURALI
    - TARİH TUTARLILIĞI: Eğer veritabanından gelen bir "Tahmini Teslim Tarihi" varsa, müşteri ne kadar kızgın olursa olsun ASLA bu tarihi değiştirme.
       - YANLIŞ: "Özür dileriz, şikayet oluşturdum, kargonuz 2 gün içinde gelir." (Veri uydurma!)
       - DOĞRU: "Yaşanan aksaklık için çok özür dilerim, şikayet kaydınızı oluşturdum. Sistemlerimize göre kargonuz BUGÜN teslim edilecek görünüyor, süreci hızlandırmaları için şubeyi uyarıyorum."

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

    # TESLİMAT SÜRESİ TAHMİNİ
    - "Kargo kaç günde gider?", "İzmir İstanbul arası ne kadar sürer?", "Tahmini varış süresi hesapla", "Teslimat kaç gün sürer?":
      -> {{ "type": "action", "function": "teslimat_suresi_hesapla_ai", "parameters": {{ "cikis": "...", "varis": "...", "desi": "..." }} }}
      (Not: Eğer kullanıcı desi belirtmediyse varsayılan olarak '5' kabul et).

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
    - Ad, numara ve telefonu bir anda SORMA. SIRAYLA sor.
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

    # KARGONUN GECİKMESİ ŞİKAYETİ 
    - "Kargom gecikti", "teslimat süresi aşıldı", "çok yordu" -> {{ "type": "action", "function": "gecikme_sikayeti", "parameters": {{ "no": "{saved_no}", "musteri_id": "{{user_id}}" }} }}

    # KARGO TAKİP NUMARASI HATASI 
    - Kullanıcı **"takip numarası hatalı", "geçersiz numara", "kod yanlış", "sistem görmüyor"** veya **"numara bulunamadı"** gibi sorunlardan bahsediyorsa:
      -> {{ "type": "action", "function": "takip_numarasi_hatasi", "parameters": {{}} }}

    # KURYE GELMEMESİ ŞİKAYETİ 
    - "Kurye gelmedi", "alım saati geçti" -> {{ "type": "action", "function": "kurye_gelmedi_sikayeti", "parameters": {{}} }}

    # ÖVGÜ 
    - "Teşekkürler", "Hızlı geldi", "Memnun kaldım" -> {{ "type": "action", "function": "hizli_teslimat_ovgu", "parameters": {{}} }}

    # BİLDİRİM AYARI DEĞİŞTİR 
    - "Bildirim ayarını değiştir", "SMS istemiyorum", "E-posta gelsin" -> {{ "type": "action", "function": "bildirim_ayari_degistir", "parameters": {{ "tip": "...", "musteri_id": "{{user_id}}" }} }}

    # KİMLİK DOĞRULAMA SORUNU 
    - Kullanıcı **kimlik doğrulama yapamıyorum, hata alıyorum, bilgilerim yanlış** gibi sorunlardan bahsediyorsa:
      -> {{ "type": "action", "function": "kimlik_dogrulama_sorunu", "parameters": {{}} }}

    # VERGİ HESAPLAMA 
    - "Laptop Almanya'ya gidiyor fiyat 1000 Euro", "Almanya'ya ne kadar vergi çıkar?"
      -> {{ "type": "action", "function": "vergi_hesapla_ai", "parameters": {{ "urun_kategorisi": "...", "fiyat": "...", "hedef_ulke": "..." }} }}

    # YURT DIŞI KARGO KOŞULLARI 
    - "Yurt dışı kargo", "gümrük", "ülke koşulları" -> {{ "type": "action", "function": "yurt_disi_kargo_kosul", "parameters": {{}} }}

    # GENEL MÜŞTERİ ŞİKAYETİ (Kurye Kaba, Yanlış Faturalandırma vb.)
    - "Şikayetim var", "Kurye kaba davrandı", "Yanlış fatura geldi":
      - Konu belli değilse -> {{ "type": "chat", "reply": "Anlıyorum, yaşadığınız sorun nedir? Lütfen şikayetinizi kısaca belirtin." }}
      - Konu belliyse -> {{ "type": "action", "function": "sikayet_olustur", "parameters": {{ "no": "{{saved_no}}", "konu": "..." }} }}

    # HASAR BİLDİRİMİ (TAZMİNAT)
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
    - "Faturam çok uçuk", "İtiraz ediyorum", "çok yüksek", "Faturam yanlış" (Agresif ifadeler dahil):
    - -> {{ "type": "action", "function": "kargo_ucret_itiraz", "parameters": {{ "no": "{saved_no}", "fatura_no": "..." }} }}

    # FATURA BİLGİSİ SORGULAMA (GÖNDERİCİ)
    - "Faturamın durumunu öğrenmek istiyorum. ","Ne kadar ödemiştim?", "Fatura detayı nedir?":
      -> {{ "type": "action", "function": "fatura_bilgisi_gonderici", "parameters": {{ "no": "{saved_no}" }} }}

    # TESLİMAT ERTELEME (EVDE YOKUM BİLDİRİMİ)
    - "Evde yokum", "Evde olamayacağım", "Bugün teslim almayacağım", "Teslimatı ertele":
      -> {{ "type": "action", "function": "evde_olmama_bildirimi", "parameters": {{ "no": "{saved_no}" }} }}

    # ALICI ADI VEYA TELEFONU DEĞİŞTİRME
    - "Alıcının adını yanlış yazmışım Ahmet Yılmaz olacak", "Alıcı telefonunu güncellemek istiyorum 5551234567":
    - EĞER isim değişecekse -> {{ "type": "action", "function": "alici_bilgisi_guncelle", "parameters": {{ "no": "{saved_no}", "yeni_veri": "Ahmet Yılmaz", "bilgi_turu": "isim" }} }}
    - EĞER telefon değişecekse -> {{ "type": "action", "function": "alici_bilgisi_guncelle", "parameters": {{ "no": "{saved_no}", "yeni_veri": "5551234567", "bilgi_turu": "telefon" }} }}
 
    3. GENEL SOHBET:
      - Merhaba, nasılsın vb. -> {{ "type": "chat", "reply": "Hoş geldiniz. Size nasıl yardımcı olabilirim?" }}
"""

    formatted_history = "\n".join(history)
    full_prompt = f"{system_prompt}\n\nGEÇMİŞ SOHBET:\n{formatted_history}\n\nKULLANICI: {final_user_message}\nJSON CEVAP:"

    try:
        result = model.generate_content(full_prompt)
        text_response = result.text.replace("```json", "").replace("```", "").strip()
        # --- DEBUG NOKTASI---
        print(f"\n[DEBUG] AI HAM CEVAP: {text_response}")
        # --------------------------------------

        data = json.loads(text_response)
        final_reply = ""
        func = None

        if data.get("type") == "action":
            func = data.get("function")
            params = data.get("parameters", {})

            # --- DEBUG NOKTASI  ---
            print(f"✅ [DEBUG] SEÇİLEN FONKSİYON: {func}")
            print(f"🔍 [DEBUG] PARAMETRELER: {params}")
            # -------------------------------------------------
            system_res = ""

            if func == "kimlik_dogrula":
                print("[DEBUG] kimlik_dogrula ÇAĞRILIYOR...")

                db_sonuc = kimlik_dogrula(params.get("no"), params.get("ad"), params.get("telefon"))
                print(f"[DEBUG] DB DÖNÜŞÜ: {db_sonuc}")

                if db_sonuc.startswith("BASARILI"):
                    parts = db_sonuc.split("|")
                    user_sessions[session_id]['verified'] = True
                    user_sessions[session_id]['tracking_no'] = parts[1]
                    user_sessions[session_id]['user_name'] = parts[2]
                    user_sessions[session_id]['role'] = parts[3]
                    user_sessions[session_id]['user_id'] = parts[4]
                    user_sessions[session_id]['durum'] = "SERBEST"
                    user_sessions[session_id] = session_data

                    pending_intent = session_data.get('pending_intent')
                    if pending_intent:
                        print(f"\n[DEBUG] BEKLEYEN NİYET OTOMATİK ÇALIŞTIRILIYOR: '{pending_intent}'\n")
                        session_data['pending_intent'] = None
                        user_sessions[session_id] = session_data
                        return process_with_gemini(session_id, pending_intent, user_sessions)

                    rol = "Gönderici" if parts[3] == "gonderici" else "Alıcı"

                    success_prompt = f"""
                                        GÖREV: Sesli asistan olarak yanıt ver.
                                        DURUM: Kimlik doğrulama başarılı. Kullanıcı: {parts[2]} ({rol}).
                                        TALİMAT: Kullanıcıya ismiyle hitap et, doğrulamanın yapıldığını söyle ve 'Size nasıl yardımcı olabilirim?' diye sor.
                                        """
                    final_reply = model.generate_content(success_prompt).text.strip()

                else:
                    hata_detayi = db_sonuc.split('|')[-1] if '|' in db_sonuc else "Bilgiler eşleşmedi."

                    hata_prompt = f"""
                                GÖREV: Bir kargo şirketi sesli asistanısın.
                                DURUM: Kullanıcı kimlik doğrulaması yapamadı.
                                SİSTEM HATASI: {hata_detayi} (Bunu kullanıcıya teknik terimle söyleme!)
                                YAPILACAKLAR:
                                1. Kullanıcıya nazikçe bilgilerin sistemdekiyle eşleşmediğini söyle.
                                2. "{hata_detayi}" bilgisine göre ipucu ver. 
                                    - Eğer sorun isimdeyse: "Sistemdeki kayıtla söylediğiniz isim eşleşmedi, rica etsem isminizi tekrar söyler misiniz?" de.
                                    - Eğer sorun numaradaysa: "Bu numaraya ait bir kayıt bulamadım, takip numaranızı kontrol edip tekrar okur musunuz?" de.
                                3. Tekrar denemesini iste.
                                4. ASLA teknik hata kodlarını (BASARISIZ|...) kullanıcıya okuma.
                                5. Kısa tut (Sesli okunacak).
                                """
                    final_reply = model.generate_content(hata_prompt).text.strip()
                    system_res = f"Doğrulama Hatası: {hata_detayi}"

            elif func == "ucret_hesapla":
                raw_result = ucret_hesapla(params.get("cikis"), params.get("varis"), params.get("desi"))

                if isinstance(raw_result, (int, float)):
                    system_res = f"{params.get('cikis')} ile {params.get('varis')} şehirleri arası {params.get('desi')} desilik paketinizin ücreti tahmini {raw_result:.2f} Türk Lirasıdır."
                else:
                    system_res = raw_result

            elif func == "kampanya_sorgula":
                res = kampanya_sorgula()

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
                    final_reply = model.generate_content(ozel_prompt).text.strip()
                    if not final_reply or "web sitesi" in final_reply.lower() or "duyuru" in final_reply.lower():
                        if "Öğrenci" in user_message or "öğrenci" in user_message:
                            final_reply = "Evet, öğrenci kimliğiyle gelenlere %50 indirim uyguluyoruz."
                        else:
                            final_reply = f"Aktif kampanyalarımız şunlardır: {res.replace(' | ', ', ')}"

                except Exception as e:
                    print(f"Kampanya AI Hatası: {e}")
                    final_reply = f"Şu anda aktif kampanyalarımız şunlardır: {res}"
            elif func == "vergi_hesapla_ai":
                system_res = vergi_hesapla_ai(
                    params.get("urun_kategorisi"),
                    params.get("fiyat"),
                    params.get("hedef_ulke")
                )
                final_reply = system_res
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
                aktif_rol = session_data.get('role')
                system_res = kargo_bilgisi_getir(params.get("no"), user_role=aktif_rol)
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
            elif func == "alici_bilgisi_guncelle":
                aktif_rol = session_data.get('role')
                aktif_no = session_data.get('tracking_no') or params.get("no")
                system_res = alici_bilgisi_guncelle(
                    aktif_no,
                    params.get("yeni_veri"),
                    aktif_rol,
                    params.get("bilgi_turu")
                )
            elif func == "gecikme_sikayeti":
                system_res = gecikme_sikayeti(params.get("no"), user_id)
            elif func == "takip_numarasi_hatasi":
                system_res = takip_numarasi_hatasi(user_id)
            elif func == "kurye_gelmedi_sikayeti":
                aktif_no = session_data.get('tracking_no') or params.get("takip_no")
                system_res = kurye_gelmedi_sikayeti(aktif_no, user_id)
                final_reply = system_res
            elif func == "hizli_teslimat_ovgu":
                system_res = hizli_teslimat_ovgu()
            elif func == "kimlik_dogrulama_sorunu":
                system_res = kimlik_dogrulama_sorunu()
            elif func == "yurt_disi_kargo_kosul":
                system_res = yurt_disi_kargo_kosul()
            elif func == "bildirim_ayari_degistir":
                system_res = bildirim_ayari_degistir(params.get("tip"), user_id)
            elif func == "teslimat_suresi_hesapla_ai":
                cikis = params.get("cikis")
                varis = params.get("varis")
                desi = params.get("desi", 5)

                if not cikis or not varis:
                    system_res = "Teslimat süresi hesaplayabilmem için lütfen Çıkış ve Varış şehirlerini belirtin."
                else:
                    mesafe = mesafe_hesapla_ai(cikis, varis)

                    if mesafe > 0:
                        ham_sure = teslimat_suresi_hesapla(mesafe, desi)

                        sure = math.ceil(ham_sure)

                        system_res = (f"Geçmiş taşıma verilerimize dayanarak yaptığım analize göre, "
                                      f"{cikis} ile {varis} arasındaki gönderimlerin ortalama {sure} gün süreceğini öngörüyorum. "
                                      f"Mesafe yaklaşık {int(mesafe)} kilometre.")
                    else:
                        system_res = "Şehirler arası mesafe hesaplanamadı, lütfen tekrar deneyin."

            if func != "kimlik_dogrula" and func != "kampanya_sorgula" and func != "vergi_hesapla_ai":
                final_prompt = f"GÖREV: Kullanıcıya şu sistem bilgisini nazikçe ilet: {system_res}. SADECE yanıt metni. Kural: Eğer mesaj bir onay veya bilgi verme cümlesiyse, olduğu gibi kullan. Eğer bir hata içeriyorsa, nazikçe açıkla."

                if system_res.startswith("YENİ_NO_OLUŞTU"):
                    yeni_no = system_res.split("|")[1]
                    final_prompt = (f"GÖREV: Hata tespiti sonrası yeni kargo numarası oluşturuldu. "
                                    f"Müşteriye eski numarasının hatalı olduğunu, sorunu çözmek için otomatik olarak **{yeni_no}** numaralı yeni bir kargo oluşturulduğunu söyle. "
                                    f"Müşteriden yeni numara ile devam etmesini iste. Cevap çok kısa ve öz olsun. SADECE yanıt metni.")

                final_reply = model.generate_content(final_prompt).text.strip()

        elif data.get("type") == "chat":
            final_reply = data.get("reply")
        if not is_verified and not session_data.get('pending_intent'):
            is_personal_intent = data.get("type") == "action" and func in ["kimlik_dogrula", "sikayet_olustur",
                                                                           "kargo_sorgula", "tahmini_teslimat",
                                                                           "iade_islemi_baslat", "kargo_iptal_et",
                                                                           "adres_degistir",
                                                                           "yanlis_teslimat_bildirimi"]

            if is_personal_intent or (user_message.lower().strip() not in ["merhaba", "slm", "selam", "nasılsın"]):
                session_data['pending_intent'] = user_message
                print(f"[DEBUG] YENİ NİYET KAYDEDİLDİ (Parçalı Giriş için): '{user_message}'")
            else:
                print(f"[DEBUG] NİYET KAYDEDİLMEDİ (Genel Sorgu)")

        session_data['history'].append(f"KULLANICI: {user_message}")
        session_data['history'].append(f"ASİSTAN: {final_reply}")
        user_sessions[session_id] = session_data

        return final_reply

    except Exception as e:
        print(f"HATA: {e}")
        return "Bir hata oluştu."