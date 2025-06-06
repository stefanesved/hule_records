from flask import Flask, request, jsonify
import os
import requests
import firebase_admin
from firebase_admin import credentials, db
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from collections import defaultdict

app = Flask(__name__)

# Firebase setup
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://hule-records-default-rtdb.firebaseio.com'
})

# Google Sheets setup
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
gs_creds = ServiceAccountCredentials.from_json_keyfile_name("serviceAccountKey.json", scope)
gs_client = gspread.authorize(gs_creds)
sheet = gs_client.open("VinylInventory").sheet1

DISCOGS_TOKEN = "HaugEnfScUsKKaiktXamoqIsMJSXXiRBVTWhnUUG"


HTML_PAGE = """
<!doctype html>
<html>
<head>
  <title>Vinyl Scanner</title>
  <link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css' rel='stylesheet'>
  <script src='https://cdnjs.cloudflare.com/ajax/libs/quagga/0.12.1/quagga.min.js'></script>
  <style>
    #scanner video {
      width: 100% !important;
      height: auto !important;
      border-radius: 12px;
      object-fit: cover;
      max-height: 220px;
    }
    #scanner {
      height: 220px;
      position: relative;
      overflow: hidden;
    }
</style>
</head>
<body class='bg-dark text-white'>
  <div class='container py-5'>
    <h2 class='text-center mb-4'>🎵 Hule Vinyl Scanner</h2>
    <div class='mb-4 text-center'>
      <a href='/inventory' class='btn btn-outline-light'>View Inventory</a>
    </div>
    <div id='scanner' class='border rounded p-3 mb-3'></div>
    <p id='status' class='text-center'>Initializing camera...</p>
    <div id='album-info' class='text-center'></div>

    <div class='text-center mt-3'>
      <p>Having trouble? Enter barcode manually:</p>
      <input id='manual-barcode' class='form-control w-50 mx-auto' placeholder='Enter barcode'>
      <button class='btn btn-primary mt-2' onclick='lookupManual()'>Look up</button>
      <small class='text-muted d-block mt-2'>Tip: Hold the vinyl 6–12 inches away in good lighting. Tap to focus if supported.</small>
    </div>
  </div>

  <script>
    function initQuagga() {
      const isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);
      const facingMode = isMobile ? { ideal: "environment" } : { ideal: "user" };

      Quagga.init({
        inputStream: {
          name: "Live",
          type: "LiveStream",
          target: document.querySelector('#scanner'),
          constraints: {
            facingMode: facingMode,
            aspectRatio: { ideal: 1.33 },
            width: { ideal: 1280 },
            height: { ideal: 720 }
          }
        },
        decoder: {
          readers: ["ean_reader"]
        },
        locate: true
      }, function(err) {
        if (err) {
          console.error('Quagga init error:', err);
          document.getElementById('status').textContent = 'Camera access failed. Check browser permissions.';
          return;
        }
        Quagga.start();
        document.getElementById('status').textContent = 'Scanning...';
      });

      Quagga.onDetected(function(data) {
        Quagga.stop();
        Quagga.CameraAccess.release();
        let code = data.codeResult.code;
        document.getElementById('status').textContent = 'Barcode: ' + code;
        fetch('/lookup', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ barcode: code })
        })
        .then(res => res.json())
        .then(renderAlbumInfo);
      });
    }

    function lookupManual() {
      const code = document.getElementById("manual-barcode").value;
      fetch('/lookup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ barcode: code })
      })
      .then(res => res.json())
      .then(renderAlbumInfo);
    }

    function renderAlbumInfo(data) {
      if (data.error) {
        document.getElementById('album-info').innerHTML = '<p>' + data.error + '</p>';
      } else {
        let content = `<h3>${data.title}</h3><p>Artist: ${data.artist} <br> Year: ${data.year}</p>`;
        if (data.thumb) {
          content += `<img src="${data.thumb}" class="img-thumbnail my-2" width="150" /><br>`;
        }
        if (data.exists) {
          content += `<p>Price: $${data.price}</p>
                      <button class="btn btn-danger" onclick="sellAlbum('${data.barcode}')">Mark as Sold</button>`;
        } else {
          content += `<input type="number" class="form-control w-50 mx-auto" id="price" placeholder="Price" />
                      <button class="btn btn-success mt-2" onclick="saveAlbum('${data.barcode}', '${data.title}', '${data.artist}', '${data.year}')">Save to Inventory</button>`;
        }
        document.getElementById('album-info').innerHTML = content;
      }
    }

    function saveAlbum(barcode, title, artist, year) {
      const price = document.getElementById('price').value;
      const thumb = document.querySelector('#album-info img')?.src || null;
      fetch('/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ barcode, title, artist, year, price, thumb })
      }).then(res => res.json()).then(data => {
        alert(data.message);
        location.reload();
      });
    }

    function sellAlbum(barcode) {
      fetch('/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ barcode })
      }).then(res => res.json()).then(data => {
        alert(data.message);
        location.reload();
      });
    }

    window.addEventListener('DOMContentLoaded', initQuagga);
  </script>
</body>
</html>
"""

# Flask endpoints below (unchanged)
@app.route('/')
def home():
    return HTML_PAGE

@app.route('/inventory')
def inventory():
    ref = db.reference('inventory')
    inventory = ref.get() or {}

    # Count units from Firebase
    count_map = defaultdict(int)
    for barcode in inventory.keys():
        count_map[barcode] += 1

    rows = "".join([
        f"<tr><td>{k}</td><td>{v.get('title')}</td><td>{v.get('artist')}</td><td>{v.get('year')}</td><td>${v.get('price')}</td><td>{count_map.get(k, 0)}</td></tr>"
        for k, v in inventory.items()
    ])
    table_html = f"""
    <!doctype html>
    <html>
    <head>
      <title>Inventory</title>
      <link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css' rel='stylesheet'>
    </head>
    <body class="bg-light">
      <div class="container py-5">
        <h2 class="mb-4">📦 Current Vinyl Inventory</h2>
        <a href="/" class="btn btn-secondary mb-3">Back to Scanner</a>
        <div class="table-responsive">
          <table class="table table-bordered table-striped">
            <thead class="table-dark">
              <tr><th>Barcode</th><th>Title</th><th>Artist</th><th>Year</th><th>Price</th><th>Units</th></tr>
            </thead>
            <tbody>
              {rows}
            </tbody>
          </table>
        </div>
      </div>
    </body>
    </html>
    """
    return table_html

@app.route('/lookup', methods=['POST'])
def lookup():
    data = request.get_json()
    barcode = data.get('barcode')

    inventory_ref = db.reference('inventory')
    item = inventory_ref.child(barcode).get()
    if item:
        # Fetch thumb from Discogs even if item exists
        discogs_thumb = None
        try:
            r = requests.get("https://api.discogs.com/database/search", params={
                'barcode': barcode,
                'token': DISCOGS_TOKEN
            })
            results = r.json().get('results')
            if results:
                discogs_thumb = results[0].get('thumb')
        except:
            pass

        item['barcode'] = barcode
        item['exists'] = True
        item['thumb'] = discogs_thumb
        return jsonify(item)

    r = requests.get("https://api.discogs.com/database/search", params={
        'barcode': barcode,
        'token': DISCOGS_TOKEN
    })
    results = r.json().get('results')
    if results:
        item = results[0]
        return jsonify({
            'exists': False,
            'barcode': barcode,
        'title': item.get('title'),
        'artist': item.get('title').split(' - ')[0],
            'year': item.get('year', 'Unknown'),
            'thumb': item.get('thumb')
        })
    return jsonify({ 'error': 'Album not found.' })

@app.route('/save', methods=['POST'])
def save():
    data = request.get_json()

    ref = db.reference('inventory')
    ref.child(data['barcode']).set({
        'title': data['title'],
        'artist': data['artist'],
        'year': data['year'],
        'price': float(data['price']),
        'thumb': data.get('thumb')
    })

    try:
        sheet.append_row([
            data['barcode'],
            data['title'],
            data['artist'],
            data['year'],
            float(data['price'])
        ])
    except Exception as e:
        print(f"Google Sheets backup failed: {e}")

    return jsonify({ 'message': 'Album saved to cloud inventory!' })

@app.route('/delete', methods=['POST'])
def delete():
    data = request.get_json()
    barcode = data.get('barcode')

    db.reference('inventory').child(barcode).delete()

    try:
        sheet_data = sheet.get_all_values()
        for i, row in enumerate(sheet_data):
            if row and row[0] == barcode:
                sheet.delete_row(i + 1)
                break
    except Exception as e:
        print(f"Google Sheets delete failed: {e}")

    return jsonify({'message': 'Album marked as sold and removed.'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0',port=5001)