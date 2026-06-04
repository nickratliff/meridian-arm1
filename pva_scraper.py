"""
Meridian — PVA Scraper (Cookie-based, no browser)
Uses a real browser session cookie to bypass Cloudflare entirely.
Fast, reliable, no Playwright needed for authentication.

Usage: python3 pva_scraper.py "<address>" "<city>" "<zip>"
Returns: JSON to stdout

Required env vars:
  PVA_SESSION  — value of ASP.NET_SessionId cookie from qpublic.schneidercorp.com
  PVA_ZITOK   — value of _zitok cookie from qpublic.schneidercorp.com
"""

import sys
import os
import json
import requests
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────
# County Routing Map
# ─────────────────────────────────────────────
COUNTY_MAP = {
    "405": {
        "name": "Fayette",
        "app_id": "1019",
        "search_url": "https://qpublic.schneidercorp.com/Application.aspx?AppID=1019&LayerID=21504&PageTypeID=2",
        "base_url": "https://qpublic.schneidercorp.com"
    },
    "40324": {
        "name": "Scott",
        "app_id": "948",
        "search_url": "https://qpublic.schneidercorp.com/Application.aspx?AppID=948&LayerID=&PageTypeID=2",
        "base_url": "https://qpublic.schneidercorp.com"
    },
    "40356": {
        "name": "Jessamine",
        "app_id": "864",
        "search_url": "https://qpublic.schneidercorp.com/Application.aspx?AppID=864&LayerID=&PageTypeID=2",
        "base_url": "https://qpublic.schneidercorp.com"
    },
    "40391": {
        "name": "Clark",
        "app_id": "ClarkCountyKY",
        "search_url": "https://qpublic.schneidercorp.com/Application.aspx?App=ClarkCountyKY&LayerID=&PageTypeID=2",
        "base_url": "https://qpublic.schneidercorp.com"
    },
    "40361": {
        "name": "Bourbon",
        "app_id": "BourbonCountyKY",
        "search_url": "https://qpublic.schneidercorp.com/Application.aspx?App=BourbonCountyKY&LayerID=&PageTypeID=2",
        "base_url": "https://qpublic.schneidercorp.com"
    },
    "40403": {
        "name": "Madison",
        "app_id": "889",
        "search_url": "https://beacon.schneidercorp.com/Application.aspx?AppID=889&LayerID=&PageTypeID=2",
        "base_url": "https://beacon.schneidercorp.com"
    },
    "40475": {
        "name": "Madison",
        "app_id": "889",
        "search_url": "https://beacon.schneidercorp.com/Application.aspx?AppID=889&LayerID=&PageTypeID=2",
        "base_url": "https://beacon.schneidercorp.com"
    },
    "40353": {
        "name": "Montgomery",
        "app_id": "MontgomeryCountyKY",
        "search_url": "https://qpublic.schneidercorp.com/Application.aspx?App=MontgomeryCountyKY&LayerID=&PageTypeID=2",
        "base_url": "https://qpublic.schneidercorp.com"
    }
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://qpublic.schneidercorp.com/',
}


def detect_county(zip_code: str) -> dict | None:
    if zip_code in COUNTY_MAP:
        return COUNTY_MAP[zip_code]
    prefix = zip_code[:3]
    if prefix in COUNTY_MAP:
        return COUNTY_MAP[prefix]
    return None


def build_session(session_cookie: str, zitok: str, cf_clearance: str) -> requests.Session:
    """Build a requests session with the real browser cookies including Cloudflare clearance."""
    session = requests.Session()
    session.headers.update(HEADERS)
    session.cookies.set('ASP.NET_SessionId', session_cookie, domain='qpublic.schneidercorp.com')
    session.cookies.set('_zitok', zitok, domain='.schneidercorp.com')
    if cf_clearance:
        session.cookies.set('cf_clearance', cf_clearance, domain='.schneidercorp.com')
    return session


def search_address(session: requests.Session, county: dict, address: str) -> str | None:
    """Submit address search and return the URL of the property detail page."""
    # Load search page to get form tokens
    resp = session.get(county['search_url'], timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')

    # Get ASP.NET form fields
    viewstate = soup.find('input', {'name': '__VIEWSTATE'})
    viewstate_gen = soup.find('input', {'name': '__VIEWSTATEGENERATOR'})
    event_validation = soup.find('input', {'name': '__EVENTVALIDATION'})

    # Find address search input
    address_input = (
        soup.find('input', {'id': 'txtAddress'}) or
        soup.find('input', {'placeholder': lambda x: x and 'address' in x.lower()}) or
        soup.find('input', {'name': lambda x: x and 'address' in x.lower()})
    )

    if not address_input:
        return None

    # Build POST payload
    payload = {
        '__VIEWSTATE': viewstate['value'] if viewstate else '',
        '__VIEWSTATEGENERATOR': viewstate_gen['value'] if viewstate_gen else '',
        '__EVENTVALIDATION': event_validation['value'] if event_validation else '',
        address_input.get('name', 'txtAddress'): address,
        'btnSearch': 'Search',
    }

    # Submit search
    resp = session.post(county['search_url'], data=payload, timeout=20)
    resp.raise_for_status()

    # If redirected to a property page, return that URL
    if 'PageTypeID=4' in resp.url or 'ParcelID' in resp.url:
        return resp.url

    # Otherwise look for a result link in the response
    soup = BeautifulSoup(resp.text, 'html.parser')
    result_link = soup.find('a', href=lambda h: h and ('PageTypeID=4' in h or 'ParcelID' in h))
    if result_link:
        href = result_link['href']
        if href.startswith('http'):
            return href
        return county['base_url'] + href

    return None


def extract_property_data(session: requests.Session, property_url: str) -> dict:
    """Scrape property detail page and extract all fields."""
    resp = session.get(property_url, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, 'html.parser')

    data = {}

    # Extract from table rows (label in one cell, value in next)
    for row in soup.find_all('tr'):
        cells = row.find_all(['td', 'th'])
        if len(cells) >= 2:
            label = cells[0].get_text(strip=True).rstrip(':').lower()
            value = cells[1].get_text(strip=True)
            if label and value:
                key = label.replace(' ', '_').replace('.', '').replace('/', '_')
                data[key] = value

    # Also try labeled div/span patterns
    for el in soup.find_all(class_=lambda c: c and ('label' in c.lower() or 'field' in c.lower())):
        label = el.get_text(strip=True).rstrip(':').lower()
        sibling = el.find_next_sibling()
        if sibling:
            value = sibling.get_text(strip=True)
            if label and value:
                key = label.replace(' ', '_').replace('.', '')
                data[key] = value

    # Normalize common field names
    normalized = {}
    key_map = {
        'owner_name': ['owner_name', 'owner', 'property_owner'],
        'property_address': ['property_address', 'location_address', 'site_address', 'address'],
        'parcel_id': ['parcel_id', 'parcel_number', 'account_number', 'map_number'],
        'year_built': ['year_built', 'yr_built', 'year_build'],
        'total_sqft': ['total_sq_ft', 'total_living_area', 'gross_building_area', 'heated_sq_ft'],
        'bedrooms': ['bedrooms', 'bed', 'beds'],
        'bathrooms': ['bathrooms', 'bath', 'baths', 'full_baths'],
        'assessed_value': ['assessed_value', 'total_assessed', 'total_value', 'appraised_value'],
        'land_value': ['land_value', 'land_assessed'],
        'building_value': ['building_value', 'improvement_value'],
        'last_sale_date': ['last_sale_date', 'sale_date', 'deed_date'],
        'last_sale_price': ['last_sale_price', 'sale_price', 'deed_amount'],
        'lot_size': ['lot_size', 'land_area', 'acreage', 'lot_area'],
        'subdivision': ['subdivision', 'sub_division', 'plat'],
        'legal_description': ['legal_description', 'legal_desc'],
        'tax_amount': ['tax_amount', 'total_tax', 'annual_tax'],
        'zoning': ['zoning', 'zone'],
    }

    for normalized_key, possible_keys in key_map.items():
        for pk in possible_keys:
            if pk in data:
                normalized[normalized_key] = data[pk]
                break

    # Include all raw data too for debugging
    normalized['_raw'] = data
    return normalized


def scrape_pva(address: str, city: str, zip_code: str) -> dict:
    session_cookie = os.environ.get('PVA_SESSION', '')
    zitok = os.environ.get('PVA_ZITOK', '')
    cf_clearance = os.environ.get('PVA_CF_CLEARANCE', '')

    if not session_cookie:
        return {
            'error': 'PVA_SESSION cookie not set. Log into qpublic.schneidercorp.com, copy ASP.NET_SessionId cookie value, and add it to Railway environment variables.',
            'address': address
        }

    county = detect_county(zip_code)
    if not county:
        return {
            'error': f'No county mapping found for zip {zip_code}',
            'address': address
        }

    try:
        session = build_session(session_cookie, zitok, cf_clearance)

        # Test authentication by hitting the search page
        test_resp = session.get(county['search_url'], timeout=15)
        if 'login' in test_resp.url.lower() or 'account/login' in test_resp.url.lower():
            return {
                'error': 'Session cookie expired. Please log into qpublic.schneidercorp.com again, copy the new ASP.NET_SessionId value, and update the PVA_SESSION variable in Railway.',
                'address': address
            }

        # Search for the property
        property_url = search_address(session, county, address)
        if not property_url:
            return {
                'error': f'Property not found: {address}. Try a different address format (e.g. "3101 Sunningdale" without "Ct").',
                'county': county['name'],
                'address': address
            }

        # Extract property data
        property_data = extract_property_data(session, property_url)
        property_data['county'] = county['name']
        property_data['source'] = 'PVA via qPublic'
        property_data['address_searched'] = f'{address}, {city}, KY {zip_code}'
        property_data['property_url'] = property_url
        return property_data

    except requests.RequestException as e:
        return {'error': f'Network error: {str(e)}', 'county': county.get('name', ''), 'address': address}
    except Exception as e:
        return {'error': str(e), 'county': county.get('name', ''), 'address': address}


def main():
    if len(sys.argv) < 4:
        print(json.dumps({'error': 'Usage: pva_scraper.py <address> <city> <zip>'}))
        sys.exit(1)

    address = sys.argv[1]
    city = sys.argv[2]
    zip_code = sys.argv[3]

    result = scrape_pva(address, city, zip_code)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
