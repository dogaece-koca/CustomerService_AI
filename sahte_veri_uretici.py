import os
import random
import pandas as pd
from faker import Faker
from datetime import datetime, timedelta

# --- AYARLAR ---
MUSTERI_SAYISI = 100  # Ekstra kaç müşteri üretilsin?
SIPARIS_SAYISI = 500  # Kaç sipariş olsun?
SUBE_SAYISI = 20  # Kaç şube olsun?
KURYE_SAYISI = 50  # Kaç kurye olsun?

# Dosya Yolları
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FOLDER = os.path.join(BASE_DIR, 'veri_dosyalari')

if not os.path.exists(CSV_FOLDER):
    os.makedirs(CSV_FOLDER)

fake = Faker('tr_TR')


def telefon_uret():
    baslangic = random.choice(["530", "532", "535", "542", "544", "505", "506", "555"])
    kalan = "".join([str(random.randint(0, 9)) for _ in range(7)])
    return f"{baslangic}{kalan}" # Başında 0 olmadan, 10 hane, boşluksuz


def veri_uret():
    print("⏳ Simülasyon verileri hazırlanıyor...")

    # ==========================================
    # 1. ŞUBELER (subeler.csv)
    # ==========================================
    subeler = []
    # Senin sabit şubelerin (Testlerin bozulmaması için)
    subeler.append([1, 'Kadıköy Merkez', 'İstanbul', 'Kadıköy', 'Caferağa Mah. Moda Cad. No:10', '0216 333 44 55',
                    'Hafta içi: 09:00-18:00'])
    subeler.append(
        [2, 'Beşiktaş Şube', 'İstanbul', 'Beşiktaş', 'Çırağan Cad. No:25', '0212 222 11 00', 'Hafta içi: 09:00-18:00'])
    subeler.append(
        [3, 'Çankaya Şube', 'Ankara', 'Çankaya', 'Atatürk Bulvarı No:50', '0312 444 55 66', 'Hafta içi: 08:30-17:30'])
    subeler.append([4, 'Alsancak Şube', 'İzmir', 'Konak', 'Kıbrıs Şehitleri Cad. No:15', '0232 555 66 77',
                    'Hafta içi: 09:00-18:00'])

    iller = ["Bursa", "Antalya", "Adana", "Gaziantep", "Konya", "Muğla", "Trabzon"]

    # Rastgele Şubeler
    for i in range(5, SUBE_SAYISI + 1):
        il = random.choice(iller)
        ilce = fake.city()
        subeler.append([
            i,
            f"{il} {ilce} Şubesi",
            il,
            ilce,
            fake.address().replace("\n", " "),
            telefon_uret(),
            "Hafta içi 09:00-18:00"
        ])

    df_subeler = pd.DataFrame(subeler,
                              columns=['sube_id', 'sube_adi', 'il', 'ilce', 'adres', 'telefon', 'calisma_saatleri'])
    df_subeler.to_csv(os.path.join(CSV_FOLDER, 'subeler.csv'), index=False)
    print(f"🏢 Şubeler oluşturuldu: {len(df_subeler)}")

    # ==========================================
    # 2. KURYELER (kuryeler.csv)
    # ==========================================
    kuryeler = []
    # Sabit Kuryeler
    kuryeler.append([201, 'Ahmet Hızlı', 1, '0532 111 22 33', 4.8])
    kuryeler.append([202, 'Mehmet Çevik', 2, '0533 444 55 66', 4.5])

    # Rastgele Kuryeler
    for i in range(205, 205 + KURYE_SAYISI):
        sube_id = random.randint(1, len(df_subeler))  # Rastgele bir şubeye ata
        kuryeler.append([
            i,
            fake.name_male() if random.random() > 0.5 else fake.name_female(),
            sube_id,
            telefon_uret(),
            round(random.uniform(3.5, 5.0), 1)
        ])

    df_kuryeler = pd.DataFrame(kuryeler, columns=['kurye_id', 'ad_soyad', 'bagli_sube_id', 'telefon', 'puan'])
    df_kuryeler.to_csv(os.path.join(CSV_FOLDER, 'kuryeler.csv'), index=False)
    print(f"🛵 Kuryeler oluşturuldu: {len(df_kuryeler)}")

    # ==========================================
    # 3. MÜŞTERİLER (musteriler.csv)
    # ==========================================
    musteriler = []
    # Sabit Müşteriler (Senaryo için gerekli)
    musteriler.append([1001, 'Zeynep Yılmaz', '5051112233', 'zeynep@mail.com', 'SMS'])
    musteriler.append([1002, 'Can Demir', '5354445566', 'can@mail.com', 'SMS'])
    musteriler.append([1003, 'Elif Kaya', '5459998877', 'elif@mail.com', 'E-posta'])
    musteriler.append([1004, 'Doğa Ece Koca', '5415998046', 'doga@mail.com', 'SMS'])
    musteriler.append([9999, 'Misafir Kullanıcı', '1234567890', 'misafir@test.com', 'SMS'])

    # Rastgele Müşteriler
    for i in range(1005, 1005 + MUSTERI_SAYISI):
        ad = fake.name()
        mail = f"{ad.lower().replace(' ', '')}@mail.com"
        musteriler.append([
            i,
            ad,
            telefon_uret(),
            mail,
            random.choice(['SMS', 'E-posta', 'SMS'])
        ])

    df_musteriler = pd.DataFrame(musteriler, columns=['musteri_id', 'ad_soyad', 'telefon', 'email', 'bildirim_tercihi'])
    df_musteriler.to_csv(os.path.join(CSV_FOLDER, 'musteriler.csv'), index=False)
    print(f"👤 Müşteriler oluşturuldu: {len(df_musteriler)}")

    # ==========================================
    # 4. SİPARİŞLER ve KARGO TAKİP
    # ==========================================
    siparisler = []
    kargo_takip = []

    # Sabit Siparişler
    bugun = datetime.now().strftime('%Y-%m-%d')
    siparisler.append(['123456', 1001, 1002, 'Kitap Kolisi'])
    kargo_takip.append(['123456', '123456', 3, bugun, 'Moda Cad. No:10 Kadıköy/İSTANBUL', 201])

    siparisler.append(['999999', 1003, 1001, 'Mobilya'])
    kargo_takip.append(['999999', '999999', 4, bugun, 'Pınar Mah. No:5 Sarıyer/İSTANBUL', 202])

    urunler = ["Elektronik", "Giyim", "Kitap", "Kozmetik", "Evrak", "Yedek Parça"]

    # Rastgele Siparişler
    for _ in range(SIPARIS_SAYISI):
        siparis_no = str(fake.unique.random_number(digits=6))
        gonderici = random.choice(df_musteriler['musteri_id'].tolist())
        alici = random.choice(df_musteriler['musteri_id'].tolist())
        while alici == gonderici: alici = random.choice(df_musteriler['musteri_id'].tolist())

        siparisler.append([siparis_no, gonderici, alici, random.choice(urunler)])

        # Rastgele Durum (1:Hazırlanıyor, 3:Dağıtımda, 4:Teslim, 8:İptal)
        durum_id = random.choices([1, 2, 3, 4, 8], weights=[15, 20, 25, 35, 5], k=1)[0]
        kurye = random.choice(df_kuryeler['kurye_id'].tolist())

        tarih = fake.date_between(start_date='-10d', end_date='+5d')

        kargo_takip.append([
            siparis_no,  # Takip no = Sipariş no
            siparis_no,
            durum_id,
            tarih,
            fake.address().replace("\n", " "),
            kurye
        ])

    df_siparisler = pd.DataFrame(siparisler, columns=['siparis_no', 'gonderici_id', 'alici_id', 'urun_tanimi'])
    df_siparisler.to_csv(os.path.join(CSV_FOLDER, 'siparisler.csv'), index=False)

    df_takip = pd.DataFrame(kargo_takip,
                            columns=['takip_no', 'siparis_no', 'durum_id', 'tahmini_teslim', 'teslim_adresi',
                                     'kurye_id'])
    df_takip.to_csv(os.path.join(CSV_FOLDER, 'kargo_takip.csv'), index=False)
    print(f"📦 Sipariş ve Takipler oluşturuldu: {len(df_siparisler)}")

    # ==========================================
    # 5. DİĞER SABİT TABLOLAR
    # ==========================================

    # Hareket Çeşitleri
    hareketler = [
        [1, 'HAZIRLANIYOR'], [2, 'TRANSFER'], [3, 'DAGITIMDA'], [4, 'TESLIM_EDILDI'], [8, 'IPTAL EDILDI']
    ]
    pd.DataFrame(hareketler, columns=['id', 'durum_adi']).to_csv(os.path.join(CSV_FOLDER, 'hareket_cesitleri.csv'),
                                                                 index=False)

    # Kampanyalar
    kampanyalar = [
        ['Bahar Fırsatı', 'Bahar aylarına özel tüm kargolarda %15 indirim var.', 1],
        ['Öğrenci İndirimi', 'Öğrenci kimliğiyle gelenlere %50 indirim uyguluyoruz.', 1],
        ['Yılbaşı Kampanyası', '3 Gönder 2 Öde kampanyası.', 0]
    ]
    pd.DataFrame(kampanyalar, columns=['baslik', 'detay', 'aktif_mi']).to_csv(
        os.path.join(CSV_FOLDER, 'kampanyalar.csv'), index=False)

    # Tarife
    tarife = [[1, 5, 10, 100, 5, 20, 30, 200]]
    pd.DataFrame(tarife, columns=['id', 'kisa_mesafe_km_ucret', 'uzak_mesafe_km_ucret', 'taban_desi_ucreti',
                                  'taban_desi_limiti', 'kisa_mesafe_ek_desi_ucret', 'uzak_mesafe_ek_desi_ucret',
                                  'mesafe_siniri_km']).to_csv(os.path.join(CSV_FOLDER, 'ucretlendirme_tarife.csv'),
                                                              index=False)

    # Müşteri Faturalar (Sabit Veriler)
    faturalar = [
        [1001, '123456', 150.0, 4.0, 'Kadıköy Şube', 'Gebze Depo', 5350.0, bugun],
        [1003, '999999', 600.0, 10.0, 'İstanbul Merkez', 'Ankara Şube', 30250.0, bugun]
    ]
    pd.DataFrame(faturalar, columns=['musteri_id', 'siparis_no', 'mesafe_km', 'desi', 'cikis_adresi', 'varis_adresi',
                                     'toplam_fiyat', 'hesaplama_tarihi']).to_csv(
        os.path.join(CSV_FOLDER, 'musteri_faturalar.csv'), index=False)

    # Kargo Hareketleri (Detaylı Geçmiş - Sabit Örnek)
    detayli_hareketler = [
        ['123456', '2025-12-08 09:00', 'Kadıköy Şube', 'Kabul', 'Kargo şubeden kabul edildi.', 4],
        ['123456', '2025-12-08 14:30', 'Kadıköy Şube', 'Transfer', 'Transfer aracına yüklendi.', 4],
        ['123456', '2025-12-08 17:00', 'Tuzla Aktarma Merkezi', 'Giriş', 'Aktarma merkezine ulaştı.', 4],
        ['123456', '2025-12-09 08:30', 'Tuzla Aktarma Merkezi', 'Çıkış', 'İzmir aracına yüklendi.', 4],
        ['123456', '2025-12-09 14:00', 'Manisa Aktarma', 'Giriş', 'Bölge aktarmaya ulaştı.', 4],
        ['123456', '2025-12-10 09:00', 'Alsancak Şube', 'Varış', 'Varış şubesine ulaştı.', 4]
    ]
    pd.DataFrame(detayli_hareketler,
                 columns=['takip_no', 'islem_tarihi', 'islem_yeri', 'islem_tipi', 'aciklama', 'hedef_sube_id']).to_csv(
        os.path.join(CSV_FOLDER, 'kargo_hareketleri.csv'), index=False)

    print("\n✅ TÜM CSV DOSYALARI OLUŞTURULDU! Şimdi 'db_simulasyon_kurulum.py' çalıştırın.")


if __name__ == "__main__":
    veri_uret()