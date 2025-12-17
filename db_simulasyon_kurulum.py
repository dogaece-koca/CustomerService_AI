import sqlite3
import pandas as pd
import os

# --- AYARLAR ---s
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, 'sirket_veritabani.db')
CSV_FOLDER = os.path.join(BASE_DIR, 'veri_dosyalari')


def veritabani_kur():
    # 1. TEMİZLİK: Eski veritabanını sil (Temiz kurulum için)
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
        print(f"♻Eski veritabanı temizlendi: {DB_FILE}")

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    print("Veritabanı bağlantısı kuruldu.")

    # ---------------------------------------------------------
    # 2. TABLO ŞEMALARINI OLUŞTUR
    # ---------------------------------------------------------

    # A. ŞUBELER
    cursor.execute('''CREATE TABLE IF NOT EXISTS subeler (
        sube_id INTEGER PRIMARY KEY,
        sube_adi TEXT,
        il TEXT,
        ilce TEXT,
        adres TEXT,
        telefon TEXT,
        calisma_saatleri TEXT
    )''')

    # B. KURYELER
    cursor.execute('''CREATE TABLE IF NOT EXISTS kuryeler (
        kurye_id INTEGER PRIMARY KEY,
        ad_soyad TEXT,
        bagli_sube_id INTEGER,
        telefon TEXT,
        puan REAL,
        FOREIGN KEY(bagli_sube_id) REFERENCES subeler(sube_id)
    )''')

    # C. MÜŞTERİLER
    cursor.execute('''CREATE TABLE IF NOT EXISTS musteriler (
        musteri_id INTEGER PRIMARY KEY,
        ad_soyad TEXT,
        telefon TEXT,
        email TEXT,
        bildirim_tercihi TEXT DEFAULT 'SMS'
    )''')

    # D. HAREKET ÇEŞİTLERİ (DURUMLAR)
    cursor.execute('''CREATE TABLE IF NOT EXISTS hareket_cesitleri (
        id INTEGER PRIMARY KEY,
        durum_adi TEXT
    )''')

    # E. SİPARİŞLER
    cursor.execute('''CREATE TABLE IF NOT EXISTS siparisler (
        siparis_no TEXT PRIMARY KEY,
        gonderici_id INTEGER,
        alici_id INTEGER,
        urun_tanimi TEXT,
        FOREIGN KEY(gonderici_id) REFERENCES musteriler(musteri_id),
        FOREIGN KEY(alici_id) REFERENCES musteriler(musteri_id)
    )''')

    # F. KARGO TAKİP (ANA TABLO)
    cursor.execute('''CREATE TABLE IF NOT EXISTS kargo_takip (
            takip_no TEXT PRIMARY KEY,
            siparis_no TEXT,
            durum_id INTEGER,
            tahmini_teslim DATE,
            teslim_adresi TEXT,
            kurye_id INTEGER,
            oncelik_puani INTEGER DEFAULT 0, -- Yeni eklenen kolon (0: Normal, 3: Kritik)
            FOREIGN KEY(siparis_no) REFERENCES siparisler(siparis_no),
            FOREIGN KEY(kurye_id) REFERENCES kuryeler(kurye_id)
        )''')

    # G. KARGO HAREKETLERİ (GEÇMİŞ)
    cursor.execute('''CREATE TABLE IF NOT EXISTS kargo_hareketleri (
        hareket_id INTEGER PRIMARY KEY AUTOINCREMENT,
        takip_no TEXT,
        islem_tarihi DATETIME,
        islem_yeri TEXT,
        islem_tipi TEXT,
        aciklama TEXT,
        hedef_sube_id INTEGER, 
        FOREIGN KEY(takip_no) REFERENCES kargo_takip(takip_no),
        FOREIGN KEY(hedef_sube_id) REFERENCES subeler(sube_id)
    )''')

    # H. MÜŞTERİ FATURALAR
    cursor.execute('''CREATE TABLE IF NOT EXISTS musteri_faturalar (
        fatura_id INTEGER PRIMARY KEY AUTOINCREMENT,
        musteri_id INTEGER,
        siparis_no TEXT,
        mesafe_km REAL,
        desi REAL,
        cikis_adresi TEXT,
        varis_adresi TEXT,
        toplam_fiyat REAL,
        hesaplama_tarihi DATE,
        FOREIGN KEY(musteri_id) REFERENCES musteriler(musteri_id),
        FOREIGN KEY(siparis_no) REFERENCES siparisler(siparis_no)
    )''')

    # I. KAMPANYALAR
    cursor.execute('''CREATE TABLE IF NOT EXISTS kampanyalar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        baslik TEXT, 
        detay TEXT, 
        aktif_mi INTEGER
    )''')

    # J. TARİFE
    cursor.execute('''CREATE TABLE IF NOT EXISTS ucretlendirme_tarife (
        id INTEGER PRIMARY KEY,
        kisa_mesafe_km_ucret REAL,
        uzak_mesafe_km_ucret REAL,
        taban_desi_ucreti REAL,
        taban_desi_limiti INTEGER,
        kisa_mesafe_ek_desi_ucret REAL,
        uzak_mesafe_ek_desi_ucret REAL,
        mesafe_siniri_km INTEGER
    )''')

    # K. BOŞ TABLOLAR (Süreç içinde dolacaklar)
    cursor.execute('''CREATE TABLE IF NOT EXISTS sikayetler (
        sikayet_id INTEGER PRIMARY KEY AUTOINCREMENT,
        siparis_no TEXT,
        olusturan_musteri_id INTEGER,
        konu TEXT,
        durum TEXT DEFAULT 'ACIK',
        tarih DATE,
        tip TEXT,
        takip_no TEXT,
        aciklama TEXT
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS iade_talepleri (
        iade_id INTEGER PRIMARY KEY AUTOINCREMENT,
        siparis_no TEXT,
        olusturan_musteri_id INTEGER,
        sebep TEXT,
        durum TEXT DEFAULT 'ONAY_BEKLIYOR',
        tarih DATE
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS hasar_bildirimleri (
        hasar_id INTEGER PRIMARY KEY AUTOINCREMENT,
        siparis_no TEXT,
        olusturan_musteri_id INTEGER,
        hasar_tipi TEXT,
        tazminat_durumu TEXT DEFAULT 'INCELEMEDE',
        tarih DATE
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS supervisor_gorusmeleri (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        musteri_id INTEGER,
        girilen_ad TEXT,
        girilen_telefon TEXT,
        talep_tarihi DATETIME,
        durum TEXT DEFAULT 'BEKLIYOR'
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS kargo_oncelik (
            id INTEGER PRIMARY KEY,
            oncelik_adi TEXT,
            aciklama TEXT,
            renk_kodu TEXT DEFAULT '#FFFFFF'
        )''')

    conn.commit()
    print("Tablo yapıları oluşturuldu.")

    # ---------------------------------------------------------
    # 3. CSV DOSYALARINDAN VERİ AKTARIMI
    # ---------------------------------------------------------

    def csv_yukle(dosya_adi, tablo_adi):
        dosya_yolu = os.path.join(CSV_FOLDER, dosya_adi)
        if not os.path.exists(dosya_yolu):
            print(f"UYARI: '{dosya_adi}' bulunamadı, '{tablo_adi}' tablosu boş kalacak.")
            return

        try:
            # Pandas ile oku (dtype=str önemli: Telefon numaralarının başındaki 0 gitmesin)
            df = pd.read_csv(dosya_yolu, dtype=str)

            # Veritabanına "append" moduyla ekle
            df.to_sql(tablo_adi, conn, if_exists='append', index=False)
            print(f"{dosya_adi} --> '{tablo_adi}' tablosuna {len(df)} kayıt yüklendi.")

        except Exception as e:
            print(f"HATA ({dosya_adi}): {e}")

    print("\n--- Veriler Yükleniyor ---")
    csv_yukle('subeler.csv', 'subeler')
    csv_yukle('kuryeler.csv', 'kuryeler')
    csv_yukle('musteriler.csv', 'musteriler')
    csv_yukle('hareket_cesitleri.csv', 'hareket_cesitleri')
    csv_yukle('siparisler.csv', 'siparisler')
    csv_yukle('kargo_takip.csv', 'kargo_takip')
    csv_yukle('kargo_hareketleri.csv', 'kargo_hareketleri')
    csv_yukle('musteri_faturalar.csv', 'musteri_faturalar')
    csv_yukle('kampanyalar.csv', 'kampanyalar')
    csv_yukle('ucretlendirme_tarife.csv', 'ucretlendirme_tarife')
    csv_yukle('kargo_oncelik.csv', 'kargo_oncelik')

    conn.close()
    print("\nVERİTABANI KURULUMU TAMAMLANDI!")


if __name__ == "__main__":
    if not os.path.exists(CSV_FOLDER):
        os.makedirs(CSV_FOLDER)
        print(f"HATA: '{CSV_FOLDER}' klasörü bulunamadı. Lütfen önce 'sahte_veri_uretici.py' dosyasını çalıştırın.")
    else:
        veritabani_kur()