from flask import Flask, request, jsonify

app = Flask(__name__)

# --- 1. DİNAMİK VERİ TABANI SİMÜLASYONU ---
# Bu sözlükler normalde veritabanı sorgularınızın yerini tutar.
SIPARIS_DURUMU = {
    '1234': 'bugün kargoya verilmiştir.',
    '55674': '2 gün önce teslim edilmiştir.',
    '9999': 'şu an hazırlanıyor.'
}
IADE_BILGISI = {
    'standart': 'Tüm ürünlerde iade süresi 15 gündür. Ücretsiz kargo kodu: IADE2025',
    'indirimli': 'İndirimli ürünlerde iade süresi 7 iş günüdür.'
}


# --- 2. NİYETE ÖZEL İŞLEYİCİ FONKSİYONLAR ---

def isleyici_siparis_sorgulama(parameters):
    """'Siparis_Sorgulama' niyeti için dinamik cevap üretir."""

    kargo_numarasi = parameters.get('kargo_numarasi')

    # 1. PARAMETRE KONTROLÜ
    if not kargo_numarasi:
        # Dialogflow parametreyi yakalayamazsa
        return "Lütfen sorgulamak istediğiniz 4 haneli sipariş numarasını belirtin."

    # 2. VERİ TABANI SORGULAMA (Simülasyon)
    if kargo_numarasi in SIPARIS_DURUMU:
        durum = SIPARIS_DURUMU[kargo_numarasi]
        return f"{kargo_numarasi} numaralı siparişiniz {durum}"
    else:
        return f"Üzgünüm, {kargo_numarasi} numarasına ait güncel bir sipariş bilgisi bulunamadı."


def isleyici_iade_sureci(parameters):
    """'Iade_Sureci' niyeti için dinamik/statik cevap üretir."""

    # Not: İade türü gibi başka bir parametre de çekilebilir, şimdilik statik cevap verelim.

    # 1. DİNAMİK/STATİK BİLGİ KOMBİNASYONU
    statik_bilgi = IADE_BILGISI['standart']
    dinamik_ek = " İhtiyaç duyarsanız, canlı desteğe bağlanmak için 'Canlı Destek' yazabilirsiniz."

    return statik_bilgi + dinamik_ek


# --- 3. NİYET EŞLEME SÖZLÜĞÜ (Dispatcher) ---

# Gelen niyet adını, işleyecek fonksiyona yönlendirir.
INTENT_HANDLERS = {
    'Siparis_Sorgulama': isleyici_siparis_sorgulama,
    'Iade_Sureci': isleyici_iade_sureci,
    # GELECEKTEKİ NİYETLERİNİZİ BURAYA EKLEYİN
    # 'Fatura_Talebi': isleyici_fatura_talebi,
}


# --- 4. ANA WEBHOOK GİRİŞ NOKTASI ---

@app.route('/webhook', methods=['POST'])
def webhook():
    req = request.get_json(silent=True, force=True)

    try:
        intent_name = req['queryResult']['intent']['displayName']
        parameters = req['queryResult']['parameters']

        # Eğer niyet sözlükte varsa, ilgili fonksiyonu çalıştır
        if intent_name in INTENT_HANDLERS:
            # Fonksiyonu parametrelerle çağır
            fulfillmentText = INTENT_HANDLERS[intent_name](parameters)
        else:
            # İşleyicisi tanımlanmamış niyetler için yedek
            fulfillmentText = "Üzgünüm, bu konuyu dinamik olarak işleyecek bir fonksiyon henüz tanımlanmadı."

    except Exception as e:
        # Hata durumunda kullanıcı dostu bir mesaj döndür
        print(f"Hata oluştu: {e}")
        fulfillmentText = "Sunucu tarafında bir hata oluştu. Lütfen daha sonra tekrar deneyin."

    # Dialogflow'a JSON cevabını geri gönder
    return jsonify({
        'fulfillmentText': fulfillmentText
    })


if __name__ == '__main__':
    # Production ortamına dağıtırken bu kısmı kullanmayız
    app.run(debug=True, port=5000)