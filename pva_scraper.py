"""
Meridian — PVA Scraper
Supports all 7 central KY counties via Schneider Corp qPublic / Beacon platforms.
Usage: python3 pva_scraper.py "<address>" "<city>" "<zip>"
Returns: JSON to stdout
"""

import sys
import os
import json
import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# ─────────────────────────────────────────────
# County Routing Map
# ─────────────────────────────────────────────
COUNTY_MAP = {
    # ZIP prefix → county config
    "405": {  # Fayette (Lexington)
        "name": "Fayette",
        "platform": "qpublic",
        "url": "https://qpublic.schneidercorp.com/Application.aspx?AppID=1019&LayerID=21504&PageTypeID=4",
        "search_url": "https://qpublic.schneidercorp.com/Application.aspx?AppID=1019&LayerID=21504&PageTypeID=2"
    },
    "40324": {
        "name": "Scott",
        "platform": "qpublic",
        "url": "https://qpublic.schneidercorp.com/Application.aspx?AppID=948",
        "search_url": "https://qpublic.schneidercorp.com/Application.aspx?AppID=948&LayerID=&PageTypeID=2"
    },
    "40356": {
        "name": "Jessamine",
        "platform": "qpublic",
        "url": "https://qpublic.schneidercorp.com/Application.aspx?AppID=864",
        "search_url": "https://qpublic.schneidercorp.com/Application.aspx?AppID=864&LayerID=&PageTypeID=2"
    },
    "40391": {
        "name": "Clark",
        "platform": "qpublic",
        "url": "https://qpublic.schneidercorp.com/Application.aspx?App=ClarkCountyKY",
        "search_url": "https://qpublic.schneidercorp.com/Application.aspx?App=ClarkCountyKY&LayerID=&PageTypeID=2"
    },
    "40361": {
        "name": "Bourbon",
        "platform": "qpublic",
        "url": "https://qpublic.schneidercorp.com/Application.aspx?App=BourbonCountyKY",
        "search_url": "https://qpublic.schneidercorp.com/Application.aspx?App=BourbonCountyKY&LayerID=&PageTypeID=2"
    },
    "40403": {
        "name": "Madison",
        "platform": "beacon",
        "url": "https://beacon.schneidercorp.com/Application.aspx?AppID=889",
        "search_url": "https://beacon.schneidercorp.com/Application.aspx?AppID=889&LayerID=&PageTypeID=2"
    },
    "40475": {
        "name": "Madison",
        "platform": "beacon",
        "url": "https://beacon.schneidercorp.com/Application.aspx?AppID=889",
        "search_url": "https://beacon.schneidercorp.com/Application.aspx?AppID=889&LayerID=&PageTypeID=2"
    },
    "40353": {
        "name": "Montgomery",
        "platform": "qpublic",
        "url": "https://qpublic.schneidercorp.com/Application.aspx?App=MontgomeryCountyKY",
        "search_url": "https://qpublic.schneidercorp.com/Application.aspx?App=MontgomeryCountyKY&LayerID=&PageTypeID=2"
    }
}

def detect_county(zip_code: str) -> dict | None:
    """Route to correct county config based on zip code."""
    # Try exact match first
    if zip_code in COUNTY_MAP:
        return COUNTY_MAP[zip_code]
    # Try 3-digit prefix (covers all Fayette 405xx zips)
    prefix = zip_code[:3]
    if prefix in COUNTY_MAP:
        return COUNTY_MAP[prefix]
    return None


async def login_qpublic(page, login: str, password: str):
    """Handle qPublic login modal."""
    try:
        # Click login link if visible
        login_link = page.locator('a:has-text("Log In"), a:has-text("Login"), #login-link')
        if await login_link.count() > 0:
            await login_link.first.click()
            await page.wait_for_timeout(1000)

        # Fill credentials
        await page.fill('input[name="username"], input[id*="user"], input[placeholder*="user" i]', login)
        await page.fill('input[name="password"], input[type="password"]', password)

        # Submit
        submit = page.locator('button[type="submit"], input[type="submit"], button:has-text("Sign In"), button:has-text("Log In")')
        await submit.first.click()
        await page.wait_for_load_state('networkidle', timeout=15000)

    except PlaywrightTimeout:
        raise Exception("Login timed out — check PVA credentials or site availability")


async def search_property(page, address: str, county_config: dict):
    """Navigate to search and find the property."""
    await page.goto(county_config['search_url'], wait_until='domcontentloaded', timeout=30000)
    await page.wait_for_timeout(2000)

    # Try address search field
    search_selectors = [
        'input[placeholder*="address" i]',
        'input[id*="address" i]',
        'input[name*="address" i]',
        '#txtAddress',
        '.search-input'
    ]

    for sel in search_selectors:
        try:
            field = page.locator(sel)
            if await field.count() > 0:
                await field.first.fill(address)
                # Press enter or click search
                await field.first.press('Enter')
                await page.wait_for_load_state('networkidle', timeout=15000)
                break
        except Exception:
            continue


async def extract_property_data(page) -> dict:
    """Extract property details from the result page."""
    data = {}

    # Helper: grab text by label
    async def get_field(label_text: str) -> str:
        try:
            # Try table-based layout (most qPublic pages)
            cell = page.locator(f'td:has-text("{label_text}") + td, th:has-text("{label_text}") + td')
            if await cell.count() > 0:
                return (await cell.first.inner_text()).strip()
            # Try label/value div layout
            label = page.locator(f'.label:has-text("{label_text}"), .field-label:has-text("{label_text}")')
            if await label.count() > 0:
                parent = label.first.locator('..')
                value = parent.locator('.value, .field-value')
                if await value.count() > 0:
                    return (await value.first.inner_text()).strip()
        except Exception:
            pass
        return ''

    # Standard PVA fields
    field_map = {
        'parcel_id':       ['Parcel ID', 'Parcel Number', 'Account Number'],
        'owner_name':      ['Owner Name', 'Owner'],
        'mailing_address': ['Mailing Address', 'Owner Address'],
        'property_address':['Property Address', 'Location Address', 'Site Address'],
        'legal_description':['Legal Description', 'Legal Desc'],
        'land_use':        ['Land Use', 'Property Class', 'Property Use'],
        'lot_size':        ['Lot Size', 'Land Area', 'Acreage'],
        'year_built':      ['Year Built', 'Yr Built'],
        'total_sqft':      ['Total Sq Ft', 'Total Living Area', 'Gross Building Area'],
        'bedrooms':        ['Bedrooms', 'Bed'],
        'bathrooms':       ['Bathrooms', 'Bath', 'Full Baths'],
        'assessed_value':  ['Assessed Value', 'Total Assessed', 'Total Value'],
        'land_value':      ['Land Value', 'Land Assessed'],
        'building_value':  ['Building Value', 'Improvement Value'],
        'tax_amount':      ['Tax Amount', 'Total Tax', 'Annual Tax'],
        'last_sale_date':  ['Last Sale Date', 'Sale Date', 'Deed Date'],
        'last_sale_price': ['Last Sale Price', 'Sale Price', 'Deed Amount'],
        'subdivision':     ['Subdivision', 'Sub Division', 'Plat'],
        'zoning':          ['Zoning', 'Zone'],
        'school_district': ['School District', 'District'],
    }

    for key, labels in field_map.items():
        for label in labels:
            val = await get_field(label)
            if val:
                data[key] = val
                break

    # Fallback: grab full page text for manual parsing
    if not data:
        data['raw_text'] = await page.inner_text('body')

    return data


async def scrape_pva(address: str, city: str, zip_code: str) -> dict:
    login = os.environ.get('PVA_LOGIN', '')
    password = os.environ.get('PVA_PASSWORD', '')

    if not login or not password:
        return {
            'error': 'PVA credentials not set in environment variables',
            'address': address
        }

    county = detect_county(zip_code)
    if not county:
        return {
            'error': f'No county mapping found for zip {zip_code}',
            'address': address,
            'supported_zips': list(COUNTY_MAP.keys())
        }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36'
        )
        page = await context.new_page()

        try:
            # Navigate to the county site
            await page.goto(county['url'], wait_until='domcontentloaded', timeout=30000)
            await page.wait_for_timeout(2000)

            # Login
            await login_qpublic(page, login, password)

            # Search for property
            await search_property(page, address, county)

            # Check for no results
            no_results = await page.locator('text="No results", text="no records found", text="0 records"').count()
            if no_results > 0:
                return {
                    'error': 'No property found for this address',
                    'county': county['name'],
                    'address': address
                }

            # Extract data
            property_data = await extract_property_data(page)
            property_data['county'] = county['name']
            property_data['source'] = 'qPVA via qPublic/Beacon'
            property_data['address_searched'] = f'{address}, {city}, KY {zip_code}'

            return property_data

        except Exception as e:
            return {
                'error': str(e),
                'county': county.get('name', 'unknown'),
                'address': address
            }
        finally:
            await browser.close()


def main():
    if len(sys.argv) < 4:
        print(json.dumps({'error': 'Usage: pva_scraper.py <address> <city> <zip>'}))
        sys.exit(1)

    address = sys.argv[1]
    city = sys.argv[2]
    zip_code = sys.argv[3]

    result = asyncio.run(scrape_pva(address, city, zip_code))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
