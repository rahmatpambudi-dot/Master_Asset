"""
Update asset_downtime.csv dari Google Sheets MASTER (2 tab: Data Verifikasi & Downtime).
Dijalankan otomatis oleh GitHub Actions (lihat .github/workflows/update-csv.yml).

Logic join:
  - Downtime.Periode dinormalisasi ke format "Mon-YY" (sama seperti Master.Bulan)
  - Downtime di-agregasi per (Nopol, Periode) -> total Potongan sewa
  - Di-join ke Master via (NOPOL, Bulan)
  - DPP Net = DPP - Downtime (0 kalau tidak ada catatan downtime)
"""

import gspread
import pandas as pd
import json
import os
import re
from google.oauth2.service_account import Credentials

# ============================================================
# CONFIG — ganti 3 nilai ini
# ============================================================
SPREADSHEET_ID = '1R30vW1JD94RPjVhmGeyvu2uOmR9xomAfd8SfczzN7qA'
GID_MASTER = 0            # tab "Data Verifikasi dan Tagihan"
GID_DOWNTIME = 1232255908 # tab "Downtime"
OUTPUT_PATH = 'data/asset_downtime.csv'
# ============================================================

MONTH_MAP = {
    'jan': 'Jan', 'januari': 'Jan',
    'feb': 'Feb', 'februari': 'Feb',
    'mar': 'Mar', 'maret': 'Mar',
    'apr': 'Apr', 'april': 'Apr',
    'mei': 'May', 'may': 'May',
    'jun': 'Jun', 'juni': 'Jun',
    'jul': 'Jul', 'juli': 'Jul',
    'agu': 'Aug', 'agustus': 'Aug', 'aug': 'Aug',
    'sep': 'Sep', 'sept': 'Sep', 'september': 'Sep',
    'okt': 'Oct', 'oktober': 'Oct', 'oct': 'Oct',
    'nov': 'Nov', 'november': 'Nov',
    'des': 'Dec', 'desember': 'Dec', 'dec': 'Dec',
}


def normalize_periode(p):
    """'Januari 25' / 'Jan-26' / 'Sept 25' -> 'Jan-25' (format Bulan di master)"""
    if not p:
        return None
    p = str(p).strip()
    parts = re.split(r'[\s-]+', p)
    if len(parts) != 2:
        return None
    mon, yr = parts
    mon_std = MONTH_MAP.get(mon.lower())
    if not mon_std:
        return None
    if len(yr) == 4:
        yr = yr[-2:]
    return f'{mon_std}-{yr}'


def to_num(v):
    if v is None:
        return 0.0
    s = str(v).strip().replace(',', '').replace(' ', '')
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def main():
    creds_json = os.environ['GOOGLE_CREDENTIALS']
    creds_dict = json.loads(creds_json)
    scopes = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)

    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    ws_master = spreadsheet.get_worksheet_by_id(GID_MASTER)
    ws_downtime = spreadsheet.get_worksheet_by_id(GID_DOWNTIME)

    master_records = ws_master.get_all_records()
    downtime_records = ws_downtime.get_all_records()

    # --- Master: buang baris kosong (tanpa Bulan) ---
    master = [r for r in master_records if str(r.get('Bulan', '')).strip()]

    # --- Downtime: agregasi Potongan sewa per (NOPOL upper, Periode ternormalisasi) ---
    downtime_agg = {}
    for r in downtime_records:
        nopol = str(r.get('Nopol', '')).strip().upper()
        if not nopol:
            continue
        bln = normalize_periode(r.get('Periode', ''))
        potongan = to_num(r.get('Potongan sewa', 0))
        key = (nopol, bln)
        downtime_agg[key] = downtime_agg.get(key, 0.0) + potongan

    # --- Join ke master ---
    out_rows = []
    for r in master:
        nopol = str(r.get('NOPOL', '')).strip().upper()
        bln = str(r.get('Bulan', '')).strip()
        dpp = to_num(r.get('DPP\n ( Nilai Yg ditagihkan )', r.get('DPP', 0)))
        downtime_val = downtime_agg.get((nopol, bln), 0.0)
        dpp_net = dpp - downtime_val
        out_rows.append({
            'Bulan': bln,
            'NOPOL': str(r.get('NOPOL', '')).strip(),
            'Kategori Site': str(r.get('Kategori Site', '')).strip(),
            'Site Name': str(r.get('Site Name', '')).strip(),
            'BU Site': str(r.get('BU Site', '')).strip(),
            'Type Armada': str(r.get('Type Armada', '')).strip(),
            'Klasifikasi Kendaraan': str(r.get('JENIS', '')).strip(),
            'Usia (Year)': r.get('Usia (Year)', ''),
            'Owner': str(r.get('OWNER', '')).strip(),
            'DPP': dpp,
            'Nominal Downtime': downtime_val,
            'DPP Net (setelah downtime)': dpp_net,
        })

    df = pd.DataFrame(out_rows)
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)
    print(f'OK -> {OUTPUT_PATH} ({len(df)} baris, {df["NOPOL"].nunique()} unit unik)')

    # --- Laporan baris downtime yang gagal nyambung ke master (untuk dicek manual) ---
    master_keys = {(str(r.get('NOPOL', '')).strip().upper(), str(r.get('Bulan', '')).strip()) for r in master}
    gagal = []
    for r in downtime_records:
        nopol = str(r.get('Nopol', '')).strip().upper()
        bln = normalize_periode(r.get('Periode', ''))
        if not nopol or to_num(r.get('Potongan sewa', 0)) == 0:
            continue
        if (nopol, bln) not in master_keys:
            gagal.append((nopol, r.get('Periode', '')))
    if gagal:
        print(f'Peringatan: {len(gagal)} baris downtime tidak nyambung ke master:')
        for nopol, periode in gagal:
            print(f'  - {nopol} / {periode}')
    print('Selesai.')


if __name__ == '__main__':
    main()
