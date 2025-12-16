import pandas as pd
import os
from sklearn.linear_model import LinearRegression
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.naive_bayes import MultinomialNB

def teslimat_suresi_hesapla(mesafe, agirlik):
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        csv_path = os.path.join(base_dir, 'teslimat_verisi.csv')

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
        base_dir = os.path.dirname(os.path.abspath(__file__))
        csv_path = os.path.join(base_dir, 'duygu_analizi.csv')

        if not os.path.exists(csv_path):
            return "NÖTR (Veri Yok)", 0

        df = pd.read_csv(csv_path)

        vectorizer = CountVectorizer()
        X = vectorizer.fit_transform(df['text'])
        y = df['label']

        clf = MultinomialNB()
        clf.fit(X, y)

        tahmin = clf.predict(vectorizer.transform([gelen_cumle]))[0]

        skor = 0
        durum_mesaji = "NÖTR"

        if tahmin == "Olumlu":
            skor = 2
            durum_mesaji = "MUTLU"
        elif tahmin == "Olumsuz":
            skor = -2
            durum_mesaji = "KIZGIN"
        else:  # Tarafsız
            skor = 0
            durum_mesaji = "NÖTR"

        return durum_mesaji, skor

    except Exception as e:
        print(f"ML Hatası: {e}")
        return "NÖTR", 0