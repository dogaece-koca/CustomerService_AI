import sqlite3
import os

DB_FILE = 'sirket_veritabani.db'

def verileri_doldur():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        print("Veritabanına bağlanıldı...")

        # 1. TEMİZLİK: Eski test verilerini temizleyelim
        cursor.execute("DELETE FROM kargo_takip WHERE takip_no = '112234'")
        cursor.execute("DELETE FROM siparisler WHERE siparis_no = '12345'") # Eski harfli olanı değil bunu siliyoruz artık
        cursor.execute("DELETE FROM musteriler WHERE musteri_id = 123")
        cursor.execute("DELETE FROM hareket_cesitleri WHERE id = 10")

        # 2. HAREKET DURUMU
        cursor.execute("INSERT OR IGNORE INTO hareket_cesitleri (id, durum_adi) VALUES (10, 'Dağıtıma Çıktı')")

        # 3. MÜŞTERİ EKLE (Telefon: '0', çünkü kullanmıyoruz)
        # Ad: Mehmet Öztürk
        cursor.execute("INSERT INTO musteriler (musteri_id, ad_soyad, telefon, email) VALUES (123, 'Berk Özbezen', '0000000000', 'mehmet@mail.com')")

        # 4. SİPARİŞ OLUŞTUR (Sadece Rakam: 55555)
        cursor.execute("INSERT INTO siparisler (siparis_no, musteri_id, urun_tanimi) VALUES ('12345', 123, 'klavye')")

        # 5. KARGOYU OLUŞTUR (Takip No: 112233)
        # Sipariş No olarak '55555' bağladık.
        cursor.execute("INSERT INTO kargo_takip (takip_no, siparis_no, durum_id, su_anki_sube_id, teslim_adresi) VALUES ('112234', '12345', 10, 1, 'Eski Adres bursa')")

        conn.commit()
        print("\n✅ TELEFONSUZ VE KOLAY SİPARİŞ NUMARALI VERİ YÜKLENDİ!")
        print("--- TEST SENARYOSU ---")
        print("1. 'Adresimi değiştirmek istiyorum' de.")
        print("2. İsim sorunca: 'Mehmet Öztürk' de.")
        print("3. Hangi sipariş sorunca: '55555' (Beş beş beş beş beş) de.")
        print("4. Bot telefon sormadan direkt 'Yeni adresiniz nedir?' demeli.")

    except Exception as e:
        print(f"❌ HATA: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    verileri_doldur()