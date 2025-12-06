import sqlite3
import os
from datetime import datetime, timedelta

DB_NAME = "sirket_veritabani.db"


def create_simulation_db():
    if os.path.exists(DB_NAME):
        os.remove(DB_NAME)
        print(f"Mevcut {DB_NAME} silindi, sıfırdan kuruluyor...")

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # ==========================================
    # 1. REFERANS TABLOLARI (SABİT VERİLER)
    # ==========================================

    cursor.execute('''
        CREATE TABLE hareket_cesitleri (
            id INTEGER PRIMARY KEY,
            durum_adi TEXT,
            aciklama TEXT
        )
    ''')

    hareketler = [
        (1, 'HAZIRLANIYOR', 'Sipariş hazırlanma aşamasında'),
        (2, 'TRANSFER', 'Transfer merkezine sevk edildi'),
        (3, 'SUBEDE', 'Teslimat şubesinde bekliyor'),
        (4, 'DAGITIMDA', 'Kurye dağıtıma çıkardı'),
        (5, 'TESLIM_EDILDI', 'Alıcıya teslim edildi'),
        (6, 'IADE_SURECINDE', 'İade işlemi başlatıldı'),
        (7, 'TESLIM_EDILEMEDI', 'Adreste bulunamadı/Teslim edilemedi')
    ]
    cursor.executemany('INSERT INTO hareket_cesitleri VALUES (?,?,?)', hareketler)

    # --- YENİ DİNAMİK FİYATLANDIRMA YAPISI ---

    # 1. TABLO: Temel Hesaplama Kuralları
    # Sabit listeler yerine matematiksel katsayılar tutuyoruz.
    cursor.execute('''
        CREATE TABLE fiyat_parametreleri (
            parametre_adi TEXT PRIMARY KEY, -- Örn: baz_ucret, desi_carpan_sehir_ici
            deger REAL,                     -- Örn: 30.0, 5.5
            aciklama TEXT
        )
    ''')

    fiyat_kurallari = [
        ('baz_ucret', 35.0, 'Kargo açılış ücreti'),
        ('desi_birim_ucret', 8.5, 'Her 1 desi için eklenen ücret'),
        ('carpan_sehir_ici', 1.0, 'Şehir içi gönderim çarpanı'),
        ('carpan_yakin_sehir', 1.5, '600km altı mesafe çarpanı'),
        ('carpan_uzak_sehir', 2.2, '600km üstü mesafe çarpanı')
    ]
    cursor.executemany('INSERT INTO fiyat_parametreleri VALUES (?,?,?)', fiyat_kurallari)

    # 2. TABLO: Ek Hizmetler (Opsiyonel Giderler)
    cursor.execute('''
        CREATE TABLE ek_hizmetler (
            id INTEGER PRIMARY KEY,
            hizmet_adi TEXT,
            ucret REAL
        )
    ''')

    ek_hizmetler = [
        (0, 'Yok', 0.0),
        (1, 'SMS Bilgilendirme', 2.50),
        (2, 'Sigorta (Kırılabilir)', 25.00),
        (3, 'Telefon İhbarlı Teslim', 5.00),
        (4, 'Hızlı Teslimat (VIP)', 50.00)
    ]
    cursor.executemany('INSERT INTO ek_hizmetler VALUES (?,?,?)', ek_hizmetler)

    # ==========================================
    # 2. ŞİRKET İÇ YAPISI
    # ==========================================

    cursor.execute('''
        CREATE TABLE subeler (
            sube_id INTEGER PRIMARY KEY,
            sube_adi TEXT,
            il TEXT,
            ilce TEXT,
            adres TEXT,
            telefon TEXT,
            koordinat_lat REAL,
            koordinat_long REAL
        )
    ''')

    cursor.execute('''
        CREATE TABLE kuryeler (
            kurye_id INTEGER PRIMARY KEY,
            ad_soyad TEXT,
            bagli_oldugu_sube_id INTEGER,
            puan REAL, 
            FOREIGN KEY(bagli_oldugu_sube_id) REFERENCES subeler(sube_id)
        )
    ''')

    # ==========================================
    # 3. MÜŞTERİ VE SİPARİŞLER
    # ==========================================

    cursor.execute('''
        CREATE TABLE musteriler (
            musteri_id INTEGER PRIMARY KEY,
            ad_soyad TEXT,
            telefon TEXT,
            email TEXT
        )
    ''')

    # Siparişler tablosunu dinamik fiyatlandırmaya uygun hale getiriyoruz
    cursor.execute('''
        CREATE TABLE siparisler (
            siparis_no TEXT PRIMARY KEY,
            musteri_id INTEGER,
            urun_tanimi TEXT,
            desi REAL,
            bolge_tipi TEXT,       -- 'sehir_ici', 'yakin_sehir', 'uzak_sehir' (Parametre tablosuyla eşleşir)
            ek_hizmet_id INTEGER,  -- Müşteri SMS veya Sigorta istemiş mi?
            gonderici_odeme INTEGER DEFAULT 1,
            FOREIGN KEY(musteri_id) REFERENCES musteriler(musteri_id),
            FOREIGN KEY(ek_hizmet_id) REFERENCES ek_hizmetler(id)
        )
    ''')

    # ==========================================
    # 4. OPERASYON (Hareketler)
    # ==========================================

    cursor.execute('''
        CREATE TABLE kargo_takip (
            takip_no TEXT PRIMARY KEY,
            siparis_no TEXT,
            durum_id INTEGER,    
            su_anki_sube_id INTEGER,
            atanan_kurye_id INTEGER,
            tahmini_teslim DATE,
            teslim_adresi TEXT,
            FOREIGN KEY(siparis_no) REFERENCES siparisler(siparis_no),
            FOREIGN KEY(su_anki_sube_id) REFERENCES subeler(sube_id),
            FOREIGN KEY(atanan_kurye_id) REFERENCES kuryeler(kurye_id),
            FOREIGN KEY(durum_id) REFERENCES hareket_cesitleri(id)
        )
    ''')

    # ==========================================
    # 5. VERİ GİRİŞİ (SİMÜLASYON)
    # ==========================================

    # --- A. ŞUBELER ---
    subeler = [
        (1, 'Kadıköy Merkez', 'İstanbul', 'Kadıköy', 'Caferağa Mah. Moda Cad. No:10', '0216 333 44 55', 40.9, 29.0),
        (2, 'Beşiktaş Şube', 'İstanbul', 'Beşiktaş', 'Çırağan Cad. No:25', '0212 222 11 00', 41.0, 29.0),
        (3, 'Çankaya Şube', 'Ankara', 'Çankaya', 'Atatürk Bulvarı No:50', '0312 444 55 66', 39.9, 32.8)
    ]
    cursor.executemany('INSERT INTO subeler VALUES (?,?,?,?,?,?,?,?)', subeler)

    # --- B. KURYELER ---
    kuryeler = [
        (101, 'Ali Hızlı', 1, 4.8),
        (102, 'Veli Yavaş', 1, 3.5),
        (201, 'Ayşe Seri', 2, 4.9),
        (301, 'Mehmet Güçlü', 3, 4.7)
    ]
    cursor.executemany('INSERT INTO kuryeler VALUES (?,?,?,?)', kuryeler)

    # --- C. MÜŞTERİLER ---
    musteriler = [
        (1001, 'Zeynep Yılmaz', '5551112233', 'zeynep@mail.com'),
        (1002, 'Can Demir', '5554445566', 'can@mail.com'),
        (1003, 'Elif Kaya', '5559998877', 'elif@mail.com')
    ]
    cursor.executemany('INSERT INTO musteriler VALUES (?,?,?,?)', musteriler)

    # --- D. SİPARİŞLER (Dinamik Parametrelerle) ---
    siparisler = [
        # Zeynep: Şehir içi, küçük paket, Ek hizmet yok
        ('KRG-2023001', 1001, 'Kitap Kolisi', 3.0, 'sehir_ici', 0, 1),

        # Can: Uzak şehir, çok küçük paket, SMS istiyor (ID: 1)
        ('KRG-2023002', 1002, 'Elektronik Eşya', 1.0, 'uzak_sehir', 1, 1),

        # Elif: Yakın şehir, büyük paket, Sigorta istiyor (ID: 2)
        ('KRG-2023003', 1003, 'Mobilya Aksesuar', 15.0, 'yakin_sehir', 2, 0)
    ]
    cursor.executemany('INSERT INTO siparisler VALUES (?,?,?,?,?,?,?)', siparisler)

    # --- E. KARGO HAREKETLERİ ---
    bugun = datetime.now()
    kargo_hareketleri = [
        ('123456', 'KRG-2023001', 4, 1, 101, bugun.strftime('%Y-%m-%d'), 'Moda, Kadıköy'),
        ('987654', 'KRG-2023002', 3, 2, None, (bugun + timedelta(days=1)).strftime('%Y-%m-%d'), 'Etiler, Beşiktaş'),
        ('555555', 'KRG-2023003', 2, None, None, (bugun + timedelta(days=2)).strftime('%Y-%m-%d'), 'İzmir')
    ]
    cursor.executemany('INSERT INTO kargo_takip VALUES (?,?,?,?,?,?,?)', kargo_hareketleri)

    conn.commit()
    conn.close()
    print("SİMÜLASYON VERİTABANI GÜNCELLENDİ!")
    print("Yeni Özellik: Dinamik Fiyatlandırma")
    print("Eklendi: 'fiyat_parametreleri' (Baz ücret, desi çarpanı)")
    print("Eklendi: 'ek_hizmetler' (SMS, Sigorta, VIP)")


if __name__ == "__main__":
    create_simulation_db()