import pandas as pd
import os
from sklearn.linear_model import LinearRegression
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.naive_bayes import MultinomialNB

def teslimat_suresi_hesapla(mesafe, agirlik):
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        base_dir = os.path.dirname(current_dir)

        csv_path = os.path.join(base_dir, 'teslimat_verisi.csv')

        print(f"🔍 ML Modülü CSV Arıyor: {csv_path}")

        if not os.path.exists(csv_path):
            return "HATA: 'teslimat_verisi.csv' dosyası bulunamadı."

        df = pd.read_csv(csv_path)

        df = df[df['Status'].isin(['Delivered', 'Delayed'])]

        df = df.dropna(subset=['Distance_miles', 'Weight_kg', 'Transit_Days'])

        X = df[['Distance_miles', 'Weight_kg']]
        y = df['Transit_Days']

        model = LinearRegression()
        model.fit(X, y)

        yeni_veri = pd.DataFrame({
            'Distance_miles': [float(mesafe)],
            'Weight_kg': [float(agirlik)]
        })

        tahmin = model.predict(yeni_veri)[0]

        if tahmin < 1.0: tahmin = 1.0

        return round(tahmin, 1)

    except Exception as e:
        return f"Model Hatası: {e}"


def duygu_analizi_yap(gelen_cumle):
    try:
        CSV_DOSYA_ADI = 'duygu_analizi.csv'
        SUTUN_YORUM = 'text'
        SUTUN_ETIKET = 'label'

        current_dir = os.path.dirname(os.path.abspath(__file__))
        base_dir = os.path.dirname(current_dir)
        csv_path = os.path.join(base_dir, CSV_DOSYA_ADI)

        if not os.path.exists(csv_path):
            return "NÖTR (Dosya Yok)", 0

        try:
            df = pd.read_csv(csv_path, encoding='utf-8')
        except:
            df = pd.read_csv(csv_path, encoding='utf-16')

        df = df.dropna(subset=[SUTUN_YORUM, SUTUN_ETIKET])
        df[SUTUN_YORUM] = df[SUTUN_YORUM].astype(str)

        # Vectorizer ayarları (Küçük harf duyarlılığı vs.)
        vectorizer = CountVectorizer()
        X = vectorizer.fit_transform(df[SUTUN_YORUM])
        y = df[SUTUN_ETIKET]

        clf = MultinomialNB()
        clf.fit(X, y)

        # --- DÜZELTME BAŞLANGICI ---

        # 1. ADIM: Gelen cümleyi vektöre çevir
        gelen_vektor = vectorizer.transform([gelen_cumle])

        # KONTROL 1: HİÇBİR KELİME EŞLEŞTİ Mİ?
        # Eğer kullanıcının yazdığı kelimelerin hiçbiri veri setinde yoksa (nnz = number of non-zero elements)
        # Modelin rastgele (veya çoğunluk sınıfına göre) atmasina izin verme, NÖTR dön.
        if gelen_vektor.nnz == 0:
            return "NÖTR (Tanımsız Kelime)", 0

        # 2. ADIM: Sadece tahmin değil, olasılıkları da al
        # classes_ modelin tanıdığı sınıfları (örn: ['Negatif', 'Olumlu', 'Tarafsız']) tutar
        olasiliklar = clf.predict_proba(gelen_vektor)[0]
        max_olasilik = np.max(olasiliklar)  # En yüksek güven skoru (örn: 0.45 veya 0.90)
        tahmin_index = np.argmax(olasiliklar)
        tahmin = clf.classes_[tahmin_index]

        sonuc_str = str(tahmin)

        # KONTROL 2: GÜVEN EŞİĞİ (THRESHOLD)
        # Eğer model %60'tan az eminse, risk alma NÖTR de.
        if max_olasilik < 0.60:
            return "NÖTR (Düşük Güven)", 0

        # --- DÜZELTME BİTİŞİ ---

        if sonuc_str in ["Olumlu", "Pozitif", "1", "positive", "iyi"]:
            return "MUTLU (POZİTİF)", 2
        elif sonuc_str in ["Olumsuz", "Negatif", "-1", "negative", "kötü"]:
            return "KIZGIN (NEGATİF)", -2
        else:
            return "NÖTR", 0

    except Exception as e:
        print(f"ML Hatası: {e}")
        return "NÖTR", 0