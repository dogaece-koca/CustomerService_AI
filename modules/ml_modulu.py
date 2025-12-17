from sklearn.linear_model import LinearRegression
import pandas as pd
import os
import re
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

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


EGITILMIS_MODEL = None

def metin_temizle(metin):
    if not isinstance(metin, str): return ""

    metin = re.sub(r'<.*?>', '', metin)
    metin = re.sub(r'[^a-zA-ZçÇğĞıİöÖşŞüÜ\s]', '', metin)
    metin = metin.lower()
    metin = re.sub(r'\s+', ' ', metin).strip()

    return metin

def modeli_egit():
    global EGITILMIS_MODEL

    CSV_DOSYA_ADI = 'duygu_analizi.csv'
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # Ana dizini bul
    csv_path = os.path.join(base_dir, CSV_DOSYA_ADI)

    if not os.path.exists(csv_path):
        print(f"UYARI: {csv_path} bulunamadı.")
        return None

    try:
        try:
            df = pd.read_csv(csv_path, encoding='utf-8')
        except:
            df = pd.read_csv(csv_path, encoding='utf-16')

        if 'text' not in df.columns or 'label' not in df.columns:
            print("CSV formatı hatalı. 'text' ve 'label' sütunları olmalı.")
            return None

        df = df.dropna()
        df['clean_text'] = df['text'].apply(metin_temizle)

        vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=5000)
        clf = LogisticRegression(max_iter=1000)
        model = make_pipeline(vectorizer, clf)

        model.fit(df['clean_text'], df['label'])

        EGITILMIS_MODEL = model
        print("Duygu Analizi Modeli Eğitildi (N-Grams & TF-IDF)")
        return model

    except Exception as e:
        print(f"Model Eğitme Hatası: {e}")
        return None


def duygu_analizi_yap(gelen_cumle):
    global EGITILMIS_MODEL

    if EGITILMIS_MODEL is None:
        EGITILMIS_MODEL = modeli_egit()
        if EGITILMIS_MODEL is None:
            return "NÖTR (Model Yok)", 0

    try:
        temiz_cumle = metin_temizle(gelen_cumle)

        if not temiz_cumle or len(temiz_cumle) < 3:
            return "NÖTR (Yetersiz Veri)", 0

        olasiliklar = EGITILMIS_MODEL.predict_proba([temiz_cumle])[0]
        siniflar = EGITILMIS_MODEL.classes_

        max_index = np.argmax(olasiliklar)
        tahmin = siniflar[max_index]
        guven_skoru = olasiliklar[max_index]

        if guven_skoru < 0.55:
            return "NÖTR (Düşük Güven)", 0

        if tahmin in ["Olumlu", "Pozitif", "1"]:
            return "MUTLU (POZİTİF)", 2
        elif tahmin in ["Olumsuz", "Negatif", "-1"]:
            return "KIZGIN (NEGATİF)", -2
        else:
            return "NÖTR", 0

    except Exception as e:
        print(f"Analiz Hatası: {e}")
        return "NÖTR", 0