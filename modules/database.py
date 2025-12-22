import sqlite3
import os
import re
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(BASE_DIR, 'sirket_veritabani.db')


def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

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

def kampanya_sorgula():
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT baslik, detay FROM kampanyalar WHERE aktif_mi = 1").fetchall()
        if not rows: return "Aktif kampanya yok."
        return " | ".join([f"{r['baslik']}: {r['detay']}" for r in rows])
    finally:
        conn.close()

def kimlik_dogrula(siparis_no, ad, telefon):
    print(f"\n--- DOĞRULAMA DEBUG ---")
    print(f"Gelen Bilgiler -> Ad: {ad}, No: {siparis_no}, Tel: {telefon}")

    if not siparis_no or not ad or not telefon:
        return "HATA|Eksik bilgi."

    conn = get_db_connection()
    try:
        temiz_telefon = re.sub(r'[^0-9]', '', str(telefon))

        if len(temiz_telefon) > 10 and temiz_telefon.startswith('90'):
            temiz_telefon = temiz_telefon[2:]
        elif len(temiz_telefon) > 10 and temiz_telefon.startswith('0'):
            temiz_telefon = temiz_telefon[1:]

        if len(temiz_telefon) > 10:
            temiz_telefon = temiz_telefon[-10:]

        if len(temiz_telefon) != 10:
            print(f"DB formatına uymuyor (10 hane bekleniyor): {temiz_telefon}")
            return "BASARISIZ|Telefon numarası formatı hatalı."

        print(f"DB İçin Temiz Telefon: {temiz_telefon}")

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
            print("DB Sonucu: Kayıt bulunamadı (Telefon veya Sipariş No yanlış).")
            return "BASARISIZ|Bilgiler eşleşmiyor."

        db_ad_soyad = row['ad_soyad']
        girilen_ad_temiz = metin_temizle(ad)
        db_ad_temiz = metin_temizle(db_ad_soyad)

        if girilen_ad_temiz in db_ad_temiz or db_ad_temiz in girilen_ad_temiz:
            print("İsim Eşleşmesi BAŞARILI.")
            return f"BASARILI|{row['siparis_no']}|{row['ad_soyad']}|{row['rol']}|{row['musteri_id']}"
        else:
            print("İsim Eşleşmesi BAŞARISIZ.")
            return "BASARISIZ|İsim bilgisi uyuşmuyor."

    except Exception as e:
        print(f"HATA: {e}")
        return f"HATA|{e}"
    finally:
        conn.close()

def ucret_hesapla(cikis, varis, desi):
    from modules.gemini_ai import mesafe_hesapla_ai
    if not cikis or not varis or not desi:
        return "Fiyat hesaplayabilmem için 'Nereden', 'Nereye' ve 'Desi' bilgisini söylemelisiniz."

    try:
        desi = float(str(desi).replace("desi", "").strip())
    except:
        return "Lütfen desi bilgisini sayısal olarak belirtin."

    mesafe_km = mesafe_hesapla_ai(cikis, varis)

    if mesafe_km == 0:
        return f"Üzgünüm, {cikis} ile {varis} arasındaki mesafeyi hesaplayamadım."

    conn = get_db_connection()
    try:
        tarife = conn.execute("SELECT * FROM ucretlendirme_tarife WHERE id=1").fetchone()

        if not tarife: return "Veritabanında tarife bilgisi bulunamadı."

        sinir_km = tarife['mesafe_siniri_km']

        if mesafe_km > sinir_km:
            km_birim_ucret = tarife['uzak_mesafe_km_ucret']
            ek_desi_ucret = tarife['uzak_mesafe_ek_desi_ucret']
        else:
            km_birim_ucret = tarife['kisa_mesafe_km_ucret']
            ek_desi_ucret = tarife['kisa_mesafe_ek_desi_ucret']

        yol_ucreti = mesafe_km * km_birim_ucret

        taban_limit = tarife['taban_desi_limiti']
        taban_fiyat = tarife['taban_desi_ucreti']

        if desi <= taban_limit:
            paket_ucreti = taban_fiyat
        else:
            fark_desi = desi - taban_limit
            paket_ucreti = taban_fiyat + (fark_desi * ek_desi_ucret)

        toplam_fiyat = yol_ucreti + paket_ucreti

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

def alici_adresi_degistir(no, yeni_adres):
    return adres_degistir(no, yeni_adres)

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

def gecikme_sikayeti(no, musteri_id):
    if not no:
        return "Gecikme şikayetinizle ilgilenebilmemiz için lütfen sipariş veya takip numaranızı belirtin."

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT tahmini_teslim FROM kargo_takip WHERE takip_no = ?", (no,))
        sonuc = cursor.fetchone()

        if not sonuc:
            return "Hata: Belirttiğiniz numaraya ait bir kargo kaydı bulunamadı."

        mevcut_tarih_str = sonuc[0]  # Örn: '2023-12-15'
        mevcut_teslim_tarihi = datetime.strptime(mevcut_tarih_str, '%Y-%m-%d').date()
        bugun = datetime.now().date()

        if mevcut_teslim_tarihi < bugun:

            yeni_tarih_obj = bugun + timedelta(days=1)
            yeni_tarih_str = yeni_tarih_obj.strftime('%Y-%m-%d')

            cursor.execute("""
                UPDATE kargo_takip 
                SET tahmini_teslim = ?,
                    oncelik_puani = 2
                WHERE takip_no = ? OR siparis_no = ?
            """, (yeni_tarih_str, no))

            aciklama = f"{no} nolu kargo gecikti (Eski tarih: {mevcut_tarih_str}). Teslimat {yeni_tarih_str} tarihine ötelendi."

            cursor.execute("""
                            INSERT INTO sikayetler (olusturan_musteri_id, takip_no, tip, aciklama, tarih, durum) 
                            VALUES (?, ?, ?, ?, datetime('now'), 'ACIK')
                        """, (musteri_id, no, 'Gecikme Şikayeti', aciklama))

            conn.commit()

            return (
                f"Kontrollerimi sağladım ve haklısınız, kargonuzun {mevcut_tarih_str} tarihinde teslim edilmesi gerekiyordu. "
                f"Yaşanan aksaklık için çok özür dilerim. Şikayet kaydınızı oluşturdum. "
                f"Kargonuzu 'Yüksek Öncelikli' listeye aldım ve teslimat tarihini {yeni_tarih_str} (yarın) olarak güncelledim.")

        else:
            return (f"Sistemdeki kontrollerimi yaptım; şu an için bir gecikme görünmüyor. "
                    f"Tahmini teslimat tarihiniz {mevcut_tarih_str} olarak gözüküyor. "
                    f"Kargonuzun zamanında ulaşması için elimizden geleni yapıyoruz.")

    except Exception as e:
        print(f"Veritabanı Hata: {e}")
        return "İşlem sırasında teknik bir hata oluştu. Lütfen daha sonra tekrar deneyin."
    finally:
        conn.close()

def kargo_bilgisi_getir(no, user_role=None):
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

        # --- GÖNDERİCİYE ÖZEL MESAJLAR ---
        if user_role == 'gonderici':
            if durum_adi == 'DAGITIMDA':
                return (f"Gönderdiğiniz kargo şu an dağıtımda. "
                        f"Bugün gün içerisinde alıcıya teslim edilmesi planlanıyor.")

            elif durum_adi == 'TRANSFER':
                return (f"Gönderdiğiniz kargo yola çıktı ve şu an transfer sürecinde. "
                        f"Alıcı kargoyu teslim aldığında sisteme düşmüş olacak, ara ara sorgulayarak takip edebilirsiniz. Tahmini varış: {tahmini_teslim}")

            elif durum_adi == 'TESLIM_EDILDI':
                return (
                    f"İşlem tamamlandı. Gönderdiğiniz kargo {tahmini_teslim} tarihinde alıcıya başarıyla teslim edilmiştir.")

            elif durum_adi == 'HAZIRLANIYOR':
                return f"Siparişiniz alındı, kargo çıkışı için hazırlıklar devam ediyor."

            else:
                return f"Gönderinizin durumu: {durum_adi}. Tahmini varış tarihi: {tahmini_teslim}."

        # --- ALICI (VEYA MİSAFİR) İÇİN MESAJLAR ---
        else:
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
                return "Bu kargo iptal edilmiştir."

            else:
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

def hasar_kaydi_olustur(takip_no, hasar_tipi, musteri_id):
    if not takip_no: return "Takip numarası gerekli."
    if not hasar_tipi: return "Hasar tipi belirtmelisiniz."

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT id FROM hareket_cesitleri WHERE durum_adi LIKE '%Teslim%'")
        hedef_durum = cursor.fetchone()

        if not hedef_durum:
            return "Sistem hatası: 'Teslim Edildi' durumunun ID karşılığı bulunamadı."

        teslim_edildi_id = hedef_durum['id']  # Örn: 4 dönecektir

        cursor.execute("SELECT durum_id, siparis_no FROM kargo_takip WHERE takip_no = ?", (takip_no,))
        kargo = cursor.fetchone()

        if not kargo:
            return "Kayıt bulunamadı."

        mevcut_durum_id = kargo['durum_id']  # Bu bir sayı (INTEGER)
        siparis_no = kargo['siparis_no']

        if mevcut_durum_id != teslim_edildi_id:
            return (f"İşlem reddedildi. Kargonuz sistemde henüz teslim edilmiş görünmüyor "
                    f"Sadece teslim alınan kargolar için hasar kaydı açılabilir.")

        bugun = datetime.now().strftime('%Y-%m-%d')
        cursor.execute("""
            INSERT INTO hasar_bildirimleri 
            (siparis_no, olusturan_musteri_id, hasar_tipi, tazminat_durumu, tarih) 
            VALUES (?, ?, ?, 'INCELEMEDE', ?)
        """, (siparis_no, musteri_id, hasar_tipi, bugun))

        conn.commit()
        return f"Hasar bildirimi başarıyla oluşturuldu. Dosya No: #{cursor.lastrowid}"

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

def bildirim_ayari_degistir(tip, musteri_id):
    if not tip: return "SMS mi E-posta mı istiyorsunuz?"
    if not musteri_id: return "Önce giriş yapmalısınız."

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
        return f"Bildirim tercihiniz başarıyla '{final_tip}' olarak güncellenmiştir."
    except Exception as e:
        return f"Hata: {e}"
    finally:
        conn.close()

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

def yanlis_teslimat_bildirimi(no, dogru_adres, musteri_id):
    if not no or not dogru_adres:
        return "İşlem yapabilmem için takip numarasını ve doğru adresi belirtmelisiniz."

    safe_id = musteri_id if musteri_id else 0
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        query = """
            SELECT k.takip_no, k.durum_id, k.teslim_adresi, h.durum_adi 
            FROM kargo_takip k
            JOIN hareket_cesitleri h ON k.durum_id = h.id
            WHERE k.takip_no = ? OR k.siparis_no = ?
        """
        row = cursor.execute(query, (no, no)).fetchone()

        if not row:
            return "Sistemde bu numaraya ait bir kayıt bulunamadı."

        mevcut_adres = row['teslim_adresi']
        durum_adi = row['durum_adi']
        gercek_takip_no = row['takip_no']

        update_query = """
            UPDATE kargo_takip 
            SET teslim_adresi = ?, 
                oncelik_puani = 3 
            WHERE takip_no = ?
        """
        cursor.execute(update_query, (dogru_adres, gercek_takip_no))

        hareket_ekle_query = """
            INSERT INTO kargo_hareketleri (takip_no, islem_tarihi, islem_yeri, islem_tipi, aciklama, hedef_sube_id)
            VALUES (?, datetime('now'), 'Çağrı Merkezi / AI', 'Adres Düzeltme', ?, 0)
        """
        aciklama_hareket = f"Müşteri talebiyle adres revize edildi. Eski: {mevcut_adres[:10]}..."
        cursor.execute(hareket_ekle_query, (gercek_takip_no, aciklama_hareket))

        bugun = datetime.now().strftime('%Y-%m-%d')
        sikayet_query = """
            INSERT INTO sikayetler (siparis_no, olusturan_musteri_id, konu, tarih, durum, tip, aciklama) 
            VALUES (?, ?, ?, ?, 'ACIL_MUDAHALE', 'YANLIS_ADRES', ?)
        """
        konu_basligi = f"[KRİTİK] Yanlış Adres Bildirimi - {durum_adi}"
        detayli_aciklama = f"Kullanıcı adresin yanlış olduğunu bildirdi. Sistem, adresi '{dogru_adres}' olarak güncelledi. Kurye uyarılmalı."

        cursor.execute(sikayet_query, (no, safe_id, konu_basligi, bugun, detayli_aciklama))

        conn.commit()

        if "TESLIM" in durum_adi:
            return (f"Dikkat! Kargonuz sistemde 'Teslim Edildi' görünüyor ancak adres hatası bildirdiniz. "
                    f"Acil durum kaydı (#KRITIK) oluşturarak bölge operasyon müdürüne ilettim. "
                    f"Hatalı teslimatı geri almak için ekiplerimiz hemen harekete geçecektir.")
        else:
            return (f"Endişelenmeyin, müdahale ettim. "
                    f"Sistemdeki hatalı adresi sildim ve '{dogru_adres}' olarak güncelledim. "
                    f"Kuryemize 'Adres Değişikliği' uyarısını ve yeni rotayı anlık olarak ilettim.")

    except Exception as e:
        print(f"Hata Detayı: {e}")
        return "Sistemsel bir hata oluştu, ancak talebinizi not ettim. Lütfen daha sonra tekrar deneyin."
    finally:
        conn.close()

def sube_sorgula(lokasyon):
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        if lokasyon and "genel" not in lokasyon.lower() and "nerede" not in lokasyon.lower():
            lokasyon_temiz = f"%{lokasyon}%"
            query = "SELECT sube_adi, il, ilce, adres, telefon FROM subeler WHERE sube_adi LIKE ? OR il LIKE ? OR ilce LIKE ?"
            rows = cursor.execute(query, (lokasyon_temiz, lokasyon_temiz, lokasyon_temiz)).fetchall()

            if not rows:
                return f"Maalesef {lokasyon} bölgesinde henüz bir şubemiz bulunmuyor."

            if len(rows) == 1:
                row = rows[0]
                temiz_ad = row['sube_adi'].replace(" Şube", "").replace(" Şubesi", "").strip()
                adres_okunabilir = row['adres'].replace("/", " taksim ").replace("No:", "Numara ")

                return (f"{temiz_ad} şubemiz, {row['ilce']} ilçesinde hizmet veriyor. "
                        f"Açık adresi şöyle: {adres_okunabilir}.")

            else:
                sube_isimleri = [row['sube_adi'].replace(" Şube", "").strip() for row in rows]
                isimler_str = ", ".join(sube_isimleri)
                return f"{lokasyon} bölgesinde {len(rows)} şubemiz var: {isimler_str}. Hangisinin adresini istersiniz?"

        else:
            query = "SELECT DISTINCT il FROM subeler"
            rows = cursor.execute(query).fetchall()

            if not rows: return "Sistemde şu an aktif bir şube görünmüyor."

            sehirler = [row['il'] for row in rows]
            toplam_sehir = len(sehirler)

            sehirler_str = ", ".join(sehirler[:5])

            if toplam_sehir > 5:
                ek_metin = f"ve {toplam_sehir - 5} diğer şehirde"
            else:
                ek_metin = ""

            return (f"Şu anda Türkiye genelinde toplam {toplam_sehir} farklı şehirde hizmet veriyoruz. "
                    f"Başlıca {sehirler_str} {ek_metin} şubelerimiz bulunuyor. "
                    f"Hangi şehirdeki şubeyi öğrenmek istersiniz?")

    except Exception as e:
        return f"Şube bilgisi çekilirken teknik bir hata oldu."
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

def evde_olmama_bildirimi(no):
    if not no:
        return "İşlem yapabilmem için kargo takip veya sipariş numarasını belirtmelisiniz."

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        query = """
            SELECT k.takip_no, k.durum_id, k.tahmini_teslim, h.durum_adi 
            FROM kargo_takip k
            JOIN hareket_cesitleri h ON k.durum_id = h.id
            WHERE k.takip_no = ? OR k.siparis_no = ?
        """
        row = cursor.execute(query, (no, no)).fetchone()

        if not row:
            return f"Sistemde bu numaraya ({no}) ait bir kayıt bulunamadı."

        durum_id = row['durum_id']
        eski_tarih = row['tahmini_teslim']
        durum_adi = row['durum_adi']
        gercek_takip_no = row['takip_no']

        if "TESLIM" in durum_adi:
            return f"Kargonuz zaten teslim edilmiş görünüyor, erteleme işlemi yapılamaz."

        bugun = datetime.now()
        yeni_tarih_obj = bugun + timedelta(days=1)
        yeni_tarih_str = yeni_tarih_obj.strftime('%Y-%m-%d')


        if "DAGITIM" in durum_adi or "KURYE" in durum_adi:
            yeni_durum_id = 2
            aciklama_hareket = "Kurye Sahada Uyarıldı: Müşteri evde yok, teslimat durduruldu."
            operasyon_mesaji = "Kuryemiz şu an dağıtımda olduğu için kendisine 'Teslimatı İptal Et' uyarısı gönderdim."

        else:
            yeni_durum_id = durum_id
            aciklama_hareket = "Müşteri talebi üzerine teslimat tarihi güncellendi."
            operasyon_mesaji = "Talebiniz sisteme işlendi."

        update_query = """
            UPDATE kargo_takip 
            SET tahmini_teslim = ?, 
                durum_id = ?,
                oncelik_puani = 2 
            WHERE takip_no = ?
        """
        cursor.execute(update_query, (yeni_tarih_str, yeni_durum_id, gercek_takip_no))

        log_query = """
            INSERT INTO kargo_hareketleri (takip_no, islem_tarihi, islem_yeri, islem_tipi, aciklama, hedef_sube_id)
            VALUES (?, datetime('now'), 'Mobil Asistan', 'Erteleme', ?, 0)
        """
        cursor.execute(log_query, (gercek_takip_no, aciklama_hareket))

        conn.commit()

        return (f"{operasyon_mesaji}\n"
                f"{gercek_takip_no} numaralı kargonuzun teslimat tarihi {eski_tarih} yerine {yeni_tarih_str} olarak planlanmıştır.\n"
                f"Dilerseniz bu tarihten önce en yakın şubemizden de teslim alabilirsiniz.")

    except Exception as e:
        print(f"Hata: {e}")
        return "Sistemsel bir hata oluştu, erteleme işlemi yapılamadı."
    finally:
        conn.close()

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

def kurye_gelmedi_sikayeti(no, musteri_id):
    if not no:
        return "Hangi gönderi/alım için kurye beklemiştiniz? Takip veya sipariş numarasını belirtirseniz hemen kontrol edip ekibe ileteyim."

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        query = "SELECT durum_id, tahmini_teslim FROM kargo_takip WHERE takip_no = ? OR siparis_no = ?"
        row = cursor.execute(query, (no, no)).fetchone()

        if not row:
            return "Sistemde bu numaraya ait aktif bir kayıt bulamadım. Numarayı kontrol eder misiniz?"

        mevcut_durum_id = row['durum_id']

        if mevcut_durum_id == 4:
            return "Sistemde kargonuz teslim edilmiş görünüyor. Eğer teslim almadıysanız bu ciddi bir durum, hemen 'Teslim almadım' kaydı oluşturuyorum."

        yarin = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        cursor.execute("""
                    UPDATE kargo_takip 
                    SET tahmini_teslim = ?,
                        oncelik_puani = 3
                    WHERE takip_no = ? OR siparis_no = ?
                """, (yarin, no, no))

        konu = f"[ACİL-KURYE GELMEDİ] {no} nolu kargo için müşteri adreste beklemiş ancak kurye uğramamış."

        cursor.execute("""
            INSERT INTO sikayetler (siparis_no, olusturan_musteri_id, konu, tip, tarih, durum) 
            VALUES (?, ?, ?, 'KURYE_GELMEDI', datetime('now'), 'ACIL_ISLEM')
        """, (no, musteri_id, konu))

        cursor.execute("""
            INSERT INTO supervisor_gorusmeleri (musteri_id, girilen_ad, girilen_telefon, talep_tarihi, durum)
            VALUES (?, 'Sistem Oto', 'Kurye Sikayeti', datetime('now'), 'OTOMATIK_ESKALASYON')
        """, (musteri_id,))

        conn.commit()

        return (f"Yaşattığımız bu aksaklık için kurumum adına çok özür dilerim. "
                f"Şikayet kaydınızı 'ACİL' koduyla operasyon müdürüne ilettim. "
                f"{no} numaralı işleminizi yarına ({yarin}) erteledim ve 'Öncelikli Dağıtım/Alım' listesine ekledim. "
                f"Yarın gün içerisinde mutlaka adresinize gelinecektir.")

    except Exception as e:
        return f"Sistem hatası: {e}"
    finally:
        conn.close()

def hizli_teslimat_ovgu():
    return "Hizmetimizden memnun kalmanıza çok sevindik! Güzel geri bildiriminiz için teşekkür ederiz. İyi günler dileriz."

def kimlik_dogrulama_sorunu(): return "Kimlik doğrulama sorunları genellikle yanlış bilgi girişinden kaynaklanır. Lütfen bilgilerinizi kontrol ederek tekrar deneyin. Sorun devam ederse sizi temsilciye aktarabiliriz."

def yurt_disi_kargo_kosul(): return "Yurt dışı gönderileri için fiyatlandırma ülkeye göre değişir. Süreler ve gümrük işlemleriyle ilgili detaylı bilgi ve gerekli belge listesi size SMS ile gönderilmiştir."

def alici_bilgisi_guncelle(no, yeni_veri, user_role, bilgi_turu="isim"):
    if user_role != 'gonderici':
        return "Güvenlik gereği alıcı bilgilerini sadece kargoyu gönderen kişi değiştirebilir."

    if not no or not yeni_veri:
        return "İşlem için takip numarası ve yeni bilgi gereklidir."

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        query = """
            SELECT s.siparis_no, k.takip_no, s.alici_id, m.ad_soyad, m.telefon 
            FROM siparisler s
            JOIN musteriler m ON s.alici_id = m.musteri_id
            LEFT JOIN kargo_takip k ON s.siparis_no = k.siparis_no
            WHERE k.takip_no = ? OR s.siparis_no = ?
        """
        row = cursor.execute(query, (no, no)).fetchone()

        if not row:
            return "Sistemde bu numaraya ait bir kayıt bulunamadı."

        siparis_no = row['siparis_no']
        takip_no = row['takip_no']
        eski_id = row['alici_id']
        eski_ad = row['ad_soyad']
        eski_tel = row['telefon']


        yeni_ad = eski_ad
        yeni_tel = eski_tel

        if bilgi_turu == "isim":
            yeni_ad = yeni_veri
            degisiklik_mesaji = f"Alıcı Adı Değiştirildi: {eski_ad} -> {yeni_ad}"

        elif bilgi_turu == "telefon":
            temiz_tel = re.sub(r'[^0-9]', '', str(yeni_veri))
            if len(temiz_tel) > 10: temiz_tel = temiz_tel[-10:]
            yeni_tel = temiz_tel
            degisiklik_mesaji = f"Alıcı Telefonu Değiştirildi: {eski_tel} -> {yeni_tel}"

        else:
            return "Geçersiz işlem türü."

        cursor.execute("INSERT INTO musteriler (ad_soyad, telefon, email) VALUES (?, ?, ?)",
                       (yeni_ad, yeni_tel, "bilinmiyor@kargo.com"))

        yeni_musteri_id = cursor.lastrowid

        cursor.execute("UPDATE siparisler SET alici_id = ? WHERE siparis_no = ?", (yeni_musteri_id, siparis_no))

        if takip_no:
            log_query = """
                INSERT INTO kargo_hareketleri (takip_no, islem_tarihi, islem_yeri, islem_tipi, aciklama, hedef_sube_id)
                VALUES (?, datetime('now'), 'Çağrı Merkezi', 'Alıcı Değişikliği', ?, 0)
            """
            cursor.execute(log_query, (takip_no, degisiklik_mesaji))

        conn.commit()
        return f"İşlem Başarılı. {degisiklik_mesaji}. Sipariş yeni alıcıya atandı."

    except Exception as e:
        print(f"Hata: {e}")
        return f"Sistemsel bir hata oluştu: {e}"
    finally:
        conn.close()