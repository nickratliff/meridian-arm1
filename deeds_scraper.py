"""
Meridian — Fayette Deeds Scraper
Scrapes fayettedeeds.com for deed history, mortgages, liens, and tax bills.
No login required — fully public site.

Usage: python3 deeds_scraper.py "<address>" "<city>" "<zip>"
Returns: JSON to stdout
"""

import sys
import re
import json
import requests
from bs4 import BeautifulSoup

LAND_SEARCH_URL = 'https://fayettedeeds.com/landrecords/index.php'
TAX_SEARCH_URL  = 'https://fayettedeeds.com/delinquent/index.php'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Referer': 'https://fayettedeeds.com/index.php',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Origin': 'https://fayettedeeds.com',
}

STREET_TYPES = {
    'street': 'ST', 'st': 'ST',
    'avenue': 'AVE', 'ave': 'AVE',
    'boulevard': 'BLVD', 'blvd': 'BLVD',
    'drive': 'DR', 'dr': 'DR',
    'lane': 'LN', 'ln': 'LN',
    'court': 'CT', 'ct': 'CT',
    'circle': 'CIR', 'cir': 'CIR',
    'road': 'RD', 'rd': 'RD',
    'place': 'PL', 'pl': 'PL',
    'way': 'WAY',
    'terrace': 'TER', 'ter': 'TER',
    'trail': 'TRL', 'trl': 'TRL',
    'parkway': 'PKWY', 'pkwy': 'PKWY',
    'pike': 'PIKE',
    'run': 'RUN',
    'cove': 'CV', 'cv': 'CV',
}

DIRECTIONALS = {'N', 'S', 'E', 'W', 'NE', 'NW', 'SE', 'SW'}


def parse_address(address: str) -> dict:
    """
    Parse '3101 Sunningdale Ct' into components for the deeds search form.
    Confirmed field names: StreetNum, directional, streetName, type
    """
    parts = address.strip().split()
    result = {'StreetNum': '', 'directional': '', 'streetName': '', 'type': ''}

    if not parts:
        return result

    # Street number
    if parts[0].isdigit():
        result['StreetNum'] = parts[0]
        parts = parts[1:]

    # Directional prefix
    if parts and parts[0].upper() in DIRECTIONALS:
        result['directional'] = parts[0].upper()
        parts = parts[1:]

    # Street type suffix
    if len(parts) > 1 and parts[-1].lower() in STREET_TYPES:
        result['type'] = STREET_TYPES[parts[-1].lower()]
        parts = parts[:-1]

    # Remaining = street name
    result['streetName'] = ' '.join(parts).upper()

    return result


def build_land_payload(address: str) -> dict:
    """Build the POST form payload for a land records address search."""
    addr = parse_address(address)

    payload = {
        # Hidden fields (confirmed from form inspection)
        'searchType':     'davidson',
        'show_pick_list': 'off',
        'party_type':     '',
        'InstGroupSelect': 'DocType',

        # Address fields (confirmed field names)
        'StreetNum':   addr['StreetNum'],
        'directional': addr['directional'],
        'streetName':  addr['streetName'],
        'type':        addr['type'],

        # Instrument groups — select what matters for real estate
        'instType[DEEDS]':         'DEEDS',
        'instType[MORTGAGES]':     'MORTGAGES',
        'instType[LIENS]':         'LIENS',
        'instType[DELINQUENT TAX]':'DELINQUENT TAX',
        'instType[RELEASE]':       'RELEASE',
        'instType[LAND RECORDS]':  'LAND RECORDS',
    }

    return payload


def parse_results_table(html: str) -> list:
    """Parse the BIS Online results table into structured records."""
    soup = BeautifulSoup(html, 'html.parser')
    records = []

    # BIS Online results use a standard table layout
    for table in soup.find_all('table'):
        rows = table.find_all('tr')
        if len(rows) < 2:
            continue

        # Find header row
        headers = []
        header_row = rows[0]
        header_cells = header_row.find_all(['th', 'td'])
        if header_cells:
            headers = [c.get_text(strip=True).lower().replace(' ', '_').replace('/', '_')
                      for c in header_cells]

        # Skip tables without useful headers
        if not any(h in headers for h in ['instrument_type', 'type', 'grantor', 'grantee', 'recorded', 'date']):
            continue

        for row in rows[1:]:
            cells = row.find_all('td')
            if not cells or len(cells) < 2:
                continue

            record = {}
            for i, header in enumerate(headers):
                if i < len(cells):
                    record[header] = cells[i].get_text(strip=True)

            # Grab detail link if present
            link = row.find('a', href=True)
            if link:
                href = link['href']
                record['detail_url'] = (
                    href if href.startswith('http')
                    else 'https://fayettedeeds.com' + href
                )

            if record:
                records.append(record)

    return records


def categorize_records(records: list) -> dict:
    """Group records into deed/mortgage/lien/release categories."""
    out = {'deeds': [], 'mortgages': [], 'liens': [], 'releases': [], 'other': []}

    for rec in records:
        # Try various field names the BIS table might use
        inst = (
            rec.get('instrument_type') or rec.get('type') or
            rec.get('inst_type') or rec.get('instrument') or ''
        ).upper()

        if any(x in inst for x in ['DEED', 'LAND CONTRACT']):
            out['deeds'].append(rec)
        elif any(x in inst for x in ['MORTGAGE', 'MTG']):
            out['mortgages'].append(rec)
        elif any(x in inst for x in ['LIEN', 'LIS PENDENS', 'DELINQUENT']):
            out['liens'].append(rec)
        elif any(x in inst for x in ['RELEASE', 'REL']):
            out['releases'].append(rec)
        else:
            out['other'].append(rec)

    return out


def search_tax_bills(session: requests.Session, address: str) -> list:
    """Search delinquent tax bills. Field names likely same pattern."""
    addr = parse_address(address)

    resp = session.get(TAX_SEARCH_URL, timeout=15)
    resp.raise_for_status()

    payload = {
        'StreetNum':  addr['StreetNum'],
        'streetName': addr['streetName'],
        'type':       addr['type'],
    }

    results_resp = session.post(TAX_SEARCH_URL, data=payload, timeout=20)
    results_resp.raise_for_status()
    return parse_results_table(results_resp.text)


def scrape_deeds(address: str, city: str, zip_code: str) -> dict:
    session = requests.Session()
    session.headers.update(HEADERS)

    result = {
        'source':           'Fayette County Deed Records',
        'source_url':       'https://fayettedeeds.com',
        'address_searched': f'{address}, {city}, KY {zip_code}',
        'land_records':     [],
        'tax_bills':        [],
        'categorized':      {},
        'summary':          {},
    }

    # ── Land records ─────────────────────────────────────────────────────────
    try:
        payload = build_land_payload(address)
        resp = session.post(LAND_SEARCH_URL, data=payload, timeout=20)
        resp.raise_for_status()

        records = parse_results_table(resp.text)
        result['land_records'] = records
        result['categorized']  = categorize_records(records)

        cat = result['categorized']
        result['summary'] = {
            'total_instruments': len(records),
            'deed_count':        len(cat['deeds']),
            'mortgage_count':    len(cat['mortgages']),
            'lien_count':        len(cat['liens']),
            'release_count':     len(cat['releases']),
        }

        if cat['deeds']:
            result['summary']['most_recent_deed'] = cat['deeds'][0]
        if cat['mortgages']:
            result['summary']['most_recent_mortgage'] = cat['mortgages'][0]

        active_liens = [l for l in cat['liens']
                        if 'RELEASE' not in (l.get('instrument_type', '') or '').upper()]
        result['summary']['active_liens']       = len(active_liens)
        result['summary']['active_lien_detail'] = active_liens if active_liens else []

    except Exception as e:
        result['land_records_error'] = str(e)

    # ── Tax bills ─────────────────────────────────────────────────────────────
    try:
        tax_bills = search_tax_bills(session, address)
        result['tax_bills'] = tax_bills
        result['summary']['delinquent_tax_count'] = len(tax_bills)
    except Exception as e:
        result['tax_bills_error'] = str(e)

    return result


def main():
    if len(sys.argv) < 4:
        print(json.dumps({'error': 'Usage: deeds_scraper.py <address> <city> <zip>'}))
        sys.exit(1)

    result = scrape_deeds(sys.argv[1], sys.argv[2], sys.argv[3])
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
