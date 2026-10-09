
from flask import Flask, jsonify, request, render_template_string
import gpiod
import time
import statistics
import threading
import json
import os

app = Flask(__name__)

GPIO_CHIP = "gpiochip1"
DT_PIN = 73
SCK_PIN = 228

AYAR_DOSYASI = os.path.expanduser(
    "~/hx711-proje/tarti_ayar.json"
)

kilit = threading.Lock()
durum = {
    "gram": None,
    "ham": None,
    "sifir": None,
    "katsayi": None,
    "hata": None,
    "son_okuma": None
}

chip = None
dt = None
sck = None

def ayar_yukle():
    if os.path.exists(AYAR_DOSYASI):
        with open(AYAR_DOSYASI, "r") as f:
            ayar = json.load(f)
        durum["sifir"] = ayar["sifir"]
        durum["katsayi"] = ayar["katsayi"]

def ayar_kaydet():
    gecici = AYAR_DOSYASI + ".tmp"
    with open(gecici, "w") as f:
        json.dump({
            "sifir": durum["sifir"],
            "katsayi": durum["katsayi"]
        }, f)
    os.replace(gecici, AYAR_DOSYASI)

def ham_oku():
    baslangic = time.monotonic()

    while dt.get_value() == 1:
        if time.monotonic() - baslangic > 3:
            raise TimeoutError("HX711 veri vermiyor")
        time.sleep(0.001)

    veri = 0

    for _ in range(24):
        sck.set_value(1)
        bit = dt.get_value()
        sck.set_value(0)
        veri = (veri << 1) | bit

    sck.set_value(1)
    sck.set_value(0)

    if veri & 0x800000:
        veri -= 0x1000000

    if veri == -1:
        raise ValueError("HX711 gecersiz okuma: -1")

    return veri

def medyan_oku(adet=15):
    degerler = []
    deneme = 0
    maksimum_deneme = adet * 4

    while len(degerler) < adet:
        deneme += 1

        if deneme > maksimum_deneme:
            raise RuntimeError(
                "Yeterli sayida gecerli HX711 okumasi alinamadi"
            )

        try:
            ham = ham_oku()
            degerler.append(ham)
        except ValueError:
            print("Gecersiz HX711 okumasi atlandi")

        time.sleep(0.1)

    return statistics.median(degerler)

def sensor_dongusu():
    while True:
        try:
            with kilit:
                ham = medyan_oku(5)
                durum["ham"] = ham

                if durum["katsayi"] is not None:
                    durum["gram"] = (
                        ham - durum["sifir"]
                    ) / durum["katsayi"]
                else:
                    durum["gram"] = None

                durum["son_okuma"] = time.time()
                durum["hata"] = None
        except Exception as e:
            with kilit:
                durum["gram"] = None
                durum["hata"] = str(e)

        time.sleep(0.3)

HTML = """
<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Orange Pi Akilli Tarti</title>
<style>
body {
    margin: 0;
    background: #101827;
    color: white;
    font-family: Arial, sans-serif;
    text-align: center;
}
.container {
    max-width: 700px;
    margin: 50px auto;
    padding: 20px;
}
.card {
    background: #1e293b;
    border-radius: 20px;
    padding: 40px 15px;
    margin: 20px 0;
}
.weight {
    font-size: clamp(50px, 12vw, 90px);
    font-weight: bold;
}
.unit {
    font-size: 28px;
    color: #94a3b8;
}
button {
    background: #2563eb;
    color: white;
    border: none;
    padding: 15px 24px;
    margin: 8px;
    border-radius: 10px;
    font-size: 16px;
    cursor: pointer;
}
input {
    padding: 13px;
    border-radius: 8px;
    border: none;
    width: 130px;
    font-size: 16px;
}
#status {
    color: #94a3b8;
    margin-top: 15px;
}
</style>
</head>
<body>
<div class="container">
    <h1>Orange Pi Akilli Tarti</h1>
    <div class="card">
        <div>CANLI AGIRLIK</div>
        <div class="weight" id="weight">--</div>
        <div class="unit">gram</div>
        <div id="status">Baglaniyor...</div>
    </div>

    <button onclick="dara()">Dara Al</button>

    <div class="card">
        <h3>Kalibrasyon</h3>
        <p>Once teraziyi bosaltip dara alin.</p>
        <p>Sonra bilinen agirligi koyun.</p>
        <input type="number" id="referans"
               placeholder="Gram" step="any" min="0.01">
        <button onclick="kalibre()">Kalibre Et</button>
    </div>
</div>

<script>
async function guncelle() {
    try {
        const r = await fetch("/api/weight");
        const d = await r.json();

        document.getElementById("weight").textContent =
            d.gram === null ? "--" : d.gram.toFixed(2);

        document.getElementById("status").textContent =
            d.hata || (
                d.gram === null
                ? "Kalibrasyon gerekli"
                : "Sensor aktif"
            );
    } catch (e) {
        document.getElementById("status").textContent =
            "Sunucu baglantisi yok";
    }
}

async function dara() {
    if (!confirm("Terazi bos mu? Dara alinsin mi?")) return;
    try {
        const r = await fetch("/api/tare", {method:"POST"});
        const d = await r.json();
        alert(d.mesaj || d.hata);
    } catch(e) {
        alert("Baglanti hatasi");
    }
}

async function kalibre() {
    const gram = Number(
        document.getElementById("referans").value
    );
    if (!Number.isFinite(gram) || gram <= 0) {
        alert("Gecerli bir gram degeri girin");
        return;
    }
    if (!confirm("Referans agirlik terazide mi?")) return;

    try {
        const r = await fetch("/api/calibrate", {
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify({gram:gram})
        });
        const d = await r.json();
        alert(d.mesaj || d.hata);
    } catch(e) {
        alert("Baglanti hatasi");
    }
}

setInterval(guncelle, 1000);
guncelle();
</script>
</body>
</html>
"""

@app.route("/")
def ana_sayfa():
    return render_template_string(HTML)

@app.route("/api/weight")
def agirlik_api():
    with kilit:
        return jsonify({
            "gram": durum["gram"],
            "ham": durum["ham"],
            "hata": durum["hata"],
            "son_okuma": durum["son_okuma"]
        })

@app.route("/api/tare", methods=["POST"])
def dara_api():
    try:
        with kilit:
            sifir = medyan_oku(15)
            durum["sifir"] = sifir
            durum["gram"] = None
            if durum["katsayi"] is not None:
                ayar_kaydet()
        return jsonify({"mesaj": "Dara alindi"})
    except Exception as e:
        return jsonify({"hata": str(e)}), 500

@app.route("/api/calibrate", methods=["POST"])
def kalibrasyon_api():
    try:
        veri = request.get_json(silent=True) or {}
        agirlik = float(veri.get("gram", 0))

        if not (0 < agirlik <= 1000):
            return jsonify({
                "hata": "Agirlik 0-1000 gram araliginda olmali"
            }), 400

        with kilit:
            if durum["sifir"] is None:
                return jsonify({
                    "hata": "Once dara alin"
                }), 400

            yuklu = medyan_oku(15)
            katsayi = (
                yuklu - durum["sifir"]
            ) / agirlik

            if abs(katsayi) < 0.000001:
                raise ValueError("Kalibrasyon basarisiz")

            durum["katsayi"] = katsayi
            durum["gram"] = None
            ayar_kaydet()

        return jsonify({
            "mesaj": "Kalibrasyon tamamlandi",
            "katsayi": katsayi
        })
    except Exception as e:
        return jsonify({"hata": str(e)}), 500

if __name__ == "__main__":
    try:
        ayar_yukle()

        chip = gpiod.Chip(GPIO_CHIP)
        dt = chip.get_line(DT_PIN)
        sck = chip.get_line(SCK_PIN)

        dt.request(
            consumer="hx711_dt",
            type=gpiod.LINE_REQ_DIR_IN
        )
        sck.request(
            consumer="hx711_sck",
            type=gpiod.LINE_REQ_DIR_OUT,
            default_vals=[0]
        )

        threading.Thread(
            target=sensor_dongusu,
            daemon=True
        ).start()

        app.run(
            host="0.0.0.0",
            port=5000,
            debug=False,
            use_reloader=False,
            threaded=True
        )

    finally:
        if sck is not None:
            try:
                sck.release()
            except Exception:
                pass
        if dt is not None:
            try:
                dt.release()
            except Exception:
                pass
        if chip is not None:
            chip.close()
