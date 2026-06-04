"""
Meridian — PVA Scraper (ScrapingBee edition)
Uses ScrapingBee with premium proxies to bypass Cloudflare on qPublic.
Fast, reliable, no headless browser needed on the server.

Usage: python3 pva_scraper.py "<address>" "<city>" "<zip>"
Returns: JSON to stdout

Required env var:
  SCRAPINGBEE_API_KEY — from scrapingbee.com (free tier = 1000 credits, ~100 lookups)

Optional (kept for fallback testing):
  PVA_SESSION, PVA_ZITOK, PVA_CF_CLEARANCE
"""

import syså
import os
import re
import json
import requests
from bs4 import BeautifulSoup

SCRAPINGBEE_URL = 'https://app.scrapingbee.com/api/v1/'

# Street type suffixes to strip for qPublic search
STREET_SUFFIXES = re.compile(
    r'\s+(st|ave|blvd|dr|ln|ct|cir|rd|pl|way|ter|trl|pkwy|hwy|pike|run|'
    r'street|avenue|boulevard|drive|lane|court|circle|road|place|'
    r'terrace|trail|parkway|highway)\.?$',
    re.IGNORECASE
)

# ─────────────────────────────────────────────
# County Routing Map
# ─────────────────────────────────────────────
COUNTY_MAP = {
    "405": {
        "name": "Fayette",
        "search_url": "https://qpublic.schneidercorp.com/Application.aspx?AppID=1019&LayerID=21504&PageTypeID=2",
        "base_url": "https://qpublic.schneidercorp.com"
    },
    "40324": {
        "name": "Scott",
        "search_url": "https://qpublic.schneidercorp.com/Application.aspx?AppID=948&LayerID=&PageTypeID=2",
        "base_url": "https://qpublic.schneidercorp.com"
    },
    "40356": {
        "name": "Jessamine",
        "search_url": "https://qpublic.schneidercorp.com/Application.aspx?AppID=864&LayerID=&PageTypeID=2",
        "base_url": "https://qpublic.schneidercorp.com"
    },
    "40391": {
        "name": "Clark",
        "search_url": "https://qpublic.schneidercorp.com/Application.aspx?App=ClarkCountyKY&LayerID=&PageTypeID=2",
        "base_url": "https://qpublic.schneidercorp.com"
    },
    "40361": {
        "name": "Bourbon",
        "search_url": "https://qpublic.schneidercorp.com/Application.aspx?App=BourbonCountyKY&LayerID=&PageTypeID=2",
        "base_url": "https://qpublic.schneidercorp.com"
    },
    "40403": {
        "name": "Madison",
        "search_url": "https://beacon.schneidercorp.com/Application.aspx?AppID=889&LayerID=&PageTypeID=2",
        "base_url": "https://beacon.schneidercorp.com"
    },
    "40475": {
        "name": "Madison",
        "search_url": "https://beacon.schneidercorp.com/Application.aspx?AppID=889&LayerID=&PageTypeID=2",
        "base_url": "https://beacon.schneidercorp.com"
    },
    "40353": {
        "name": "Montgomery",
        "search_url": "https://qpublic.schneidercorp.com/Application.aspx?App=MontgomeryCountyKY&LayerID=&PageTypeID=2",
        "base_url": "https://qpublic.schneidercorp.com"
    }
}


def detect_county(zip_code: str) -> dict | None:
    if zip_code in COUNTY_MAP:
        return COUNTY_MAP[zip_code]
    prefix = zip_code[:3]
    if prefix in COUNTY_MAP:
        return COUNTY_MAP[prefix]
    return None


def strip_suffix(address: str) -> str:
    """Remove street type suffix for qPublic search (e.g. '3101 Sunningdale Ct' → '3101 Sunningdale')."""
    return STREET_SUFFIXES.sub('', address).strip()


def bee_get(api_key: str, url: str) -> str:
    """Fetch a URL via ScrapingBee with Cloudflare bypass."""
    resp = requests.get(
        SCRAPINGBEE_URL,
        params={
            'api_key':       api_key,
            'url':           url,
            'render_js':     'false',
            'stealth_proxy': 'true',
            'country_code':  'us',
        },
        timeout=60
    )
    resp.raise_for_status()
    return resp.text


def bee_post(api_key: str, url: str, form_data: dict) -> str:
    """POST a form via ScrapingBee with Cloudflare bypass."""
    resp = requests.post(
        SCRAPINGBEE_URL,
        params={
            'api_key':       api_key,
            'url':           url,
            'render_js':     'false',
            'stealth_proxy': 'true',
            'country_code':  'us',
        },
        data=form_data,
        timeout=60
    )
    resp.raise_for_status()
    return resp.text


def find_property_url(api_key: str, county: dict, address: str) -> str | None:
    """Search qPublic for the address and return the property detail page URL."""
    search_address = strip_suffix(address)

    # Step 1 — Load search page to get ASP.NET form tokens
    search_html = bee_get(api_key, county['search_url'])
    soup = BeautifulSoup(search_html, 'html.parser')

    viewstate     = soup.find('input', {'name': '__VIEWSTATE'})
    viewstate_gen = soup.find('input', {'name': '__VIEWSTATEGENERATOR'})
    event_val     = soup.find('input', {'name': '__EVENTVALIDATION'})

    address_input = (
        soup.find('input', {'id': 'txtAddress'}) or
        soup.find('input', attrs={'placeholder': lambda x: x and 'address' in x.lower()}) or
        soup.find('input', attrs={'name': lambda x: x and 'address' in x.lower()})
    )

    if not address_input:
        return None

    # Step 2 — Submit address search
    form_data = {
        '__VIEWSTATE':          viewstate['value']     if viewstate     else '',
        '__VIEWSTATEGENERATOR': viewstate_gen['value'] if viewstate_gen else '',
        '__EVENTVALIDATION':    event_val['value']     if event_val     else '',
        address_input.get('name', 'txtAddress'): search_address,
        'btnSearch': 'Search',
    }

    results_html = bee_post(api_key, county['search_url'], form_data)
    results_soup = BeautifulSoup(results_html, 'html.parser')

    # Step 3 — Find property detail link in results
    link = results_soup.find('a', href=lambda h: h and ('PageTypeID=4' in h or 'KeyValue' in h))
    if not link:
        return None

    href = link['href']
    return href if href.startswith('http') else county['base_url'] + href


def extract_property_data(api_key: str, property_url: str) -> dict:
    """Fetch property detail page and extract all fields."""
    html = bee_get(api_key, property_url)
    soup = BeautifulSoup(html, 'html.parser')
    data = {}

    # Table-based layout (most qPublic pages)
    for row in soup.find_all('tr'):
        cells = row.find_all(['td', 'th'])
        if len(cells) >= 2:
            label = cells[0].get_text(strip=True).rstrip(':').lower()
            value = cells[1].get_text(strip=True)
            if label and value:
                key = re.sub(r'[^a-z0-9]+', '_', label).strip('_')
                data[key] = value

    # Normalize to standard field names
    key_map = {
        'parcel_id':        ['parcel_id', 'parcel_number', 'account_number', 'map_number'],
        'owner_name':       ['owner_name', 'owner'],
        'property_address': ['property_address', 'location_address', 'site_address'],
        'legal_description':['legal_description', 'legal_desc'],
        'year_built':       ['year_built', 'yr_built'],
        'total_sqft':       ['deeded_sq_ft', 'total_sq_ft', 'total_living_area', 'gross_building_area', 'heated_sq_ft'],
        'bedrooms':         ['bedrooms', 'bed', 'beds'],
        'bathrooms':        ['bathrooms', 'bath', 'baths', 'full_baths'],
        'assessed_value':   ['assessed_value', 'total_assessed', 'total_value', 'appraised_value'],
        'land_value':       ['land_value', 'land_assessed'],
        'building_value':   ['building_value', 'improvement_value'],
        'last_sale_date':   ['last_sale_date', 'sale_date', 'deed_date'],
        'last_sale_price':  ['last_sale_price', 'sale_price', 'deed_amount'],
        'lot_size':         ['acres', 'lot_size', 'land_area', 'acreage'],
        'subdivision':      ['subdivision', 'sub_division', 'pva_neighborhood'],
        'tax_amount':       ['tax_amount', 'total_tax', 'annual_tax'],
        'zoning':           ['lfucg_zoning', 'zoning', 'zone'],
    }

    normalized = {}
    for norm_key, candidates in key_map.items():
        for c in candidates:
            if c in data:
                normalized[norm_key] = data[c]
                break

    normalized['_raw'] = data
    return normalized


def scrape_pva(address: str, city: str, zip_code: str) -> dict:
    api_key = os.environ.get('SCRAPINGBEE_API_KEY', '')

    if not api_key:
        return {
            'error': 'SCRAPINGBEE_API_KEY not set. Sign up at scrapingbee.com and add the key to Railway environment variables.',
            'address': address
        }

    county = detect_county(zip_code)
    if not county:
        return {
            'error': f'No county mapping found for zip {zip_code}',
            'address': address
        }

    try:
        property_url = find_property_url(api_key, county, address)
        if not property_url:
            # Retry without house number if full address fails
            street_only = re.sub(r'^\d+\s+', '', strip_suffix(address))
            property_url = find_property_url(api_key, county, street_only)

        if not property_url:
            return {
                'error': f'Property not found for: {address}. Try adjusting the address format.',
                'county': county['name'],
                'address': address
            }

        property_data = extract_property_data(api_key, property_url)
        property_data['county']           = county['name']
        property_data['source']           = 'PVA via qPublic + ScrapingBee'
        property_data['address_searched'] = f'{address}, {city}, KY {zip_code}'
        property_data['property_url']     = property_url
        return property_data

    except requests.HTTPError as e:
        return {'error': f'HTTP error: {e}', 'county': county['name'], 'address': address}
    except Exception as e:
        return {'error': str(e), 'county': county['name'], 'address': address}


def main():
    if len(sys.argv) < 4:
        print(json.dumps({'error': 'Usage: pva_scraper.py <address> <city> <zip>'}))
        sys.exit(1)

    result = scrape_pva(sys.argv[1], sys.argv[2], sys.argv[3])
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
