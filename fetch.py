#!/usr/bin/env python3

import requests
import json
import sys
import re
from pathlib import Path
from bs4 import BeautifulSoup

page_cache = {}


def debug(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr)


def fetch_cache(url, mode='lxml'):
    dest = Path('./page_cache/') / (url.replace('/', '_') + '.html')
    dest.parent.mkdir(exist_ok=True)

    if url + mode in page_cache:
        debug('using memory cache for', url)
        return page_cache[url + mode]

    try:
        with open(dest, 'r', encoding='utf-8') as infile:
            body = infile.read()
            debug('using cache for', url)
    except:
        debug('fetching', url)
        r = requests.get(url)
        body = r.text
        with open(dest, 'w', encoding='utf-8') as outfile:
            outfile.write(body)

    if mode == 'lxml':
        body = BeautifulSoup(body, 'lxml')
    elif mode == 'json':
        body = json.loads(body)

    page_cache[url + mode] = body
    return body


def fetch_cache_img(url, name):
    dest = Path('./img_cache/') / name
    dest.parent.mkdir(exist_ok=True)

    try:
        with open(dest, 'r', encoding='utf-8') as infile:
            debug('using cache for', url)
    except:
        debug('fetching', url)
        r = requests.get(url)
        with open(dest, 'wb') as outfile:
            outfile.write(r.content)

    return name


def parse_classes(classes):
    categories = {}

    for c in classes:
        if c == "academicTypeLocation":
            categories['academic'] = True
        elif c == "administrativeTypeLocation":
            categories['administrative'] = True
        elif c == "employeeHousingTypeLocation":
            categories['employee-housing'] = True
        elif c == "studentHousingTypeLocation":
            categories['student-housing'] = True

    return categories


def parse_location_attrs(locationAttributes):
    attrs = {
        'address': None,
        'accessibility-level': 'unknown',
        'floors': [],
        'offices': [],
        'departments': [],
        'description': None,
    }

    for i, thing in enumerate(locationAttributes):
        label = None
        if i is 0:
            label = 'address'
        elif i is 1:
            label = 'description'

        label_el = thing.select_one('.label')
        if label_el:
            label = label_el.get_text().lower().strip(':')

        value = None
        if label == 'address':
            bits = thing.select('.buildingAttributes li')
            if len(bits) >= 1:
                value = bits[0].get_text()
            if len(bits) == 2:
                access_level = 'unknown'
                text = bits[1].get_text()
                if text == 'Wheelchair Access':
                    access_level = 'wheelchair'
                elif text == 'No Handicap Access':
                    access_level = 'none'
                elif text == 'Unkown':
                    access_level = 'unknown'

                attrs['accessibility-level'] = access_level
        elif label == 'floors':
            floors = thing.select('.buildingFloors a')
            value = [{'href': f.attrs['href'], 'label': f.get_text()} for f in floors]
        elif label == 'offices':
            offices = thing.select('.buildingAttributes a')
            value = [{'href': o.attrs['href'], 'label': o.get_text()} for o in offices]
        elif label == 'departments':
            depts = thing.select('.buildingAttributes a')
            value = [{'href': d.attrs['href'], 'label': d.get_text()} for d in depts]
        elif label == 'description':
            description_bits = thing.select('.buildingAttributes p')
            value = [bit.get_text() for bit in description_bits]

        attrs[label] = value

    return attrs


def get_buildings():
    urls = [
        ['building', 'https://apps.carleton.edu/map/types/buildings/',],
        ['outdoors', 'https://apps.carleton.edu/map/types/outdoors/',],
        ['athletics', 'https://apps.carleton.edu/map/types/athletics/',],
        ['parking', 'https://apps.carleton.edu/map/types/parking/',],
    ]

    locations = {}

    house_regex = re.compile(r'\bHouse\b')
    hall_regex = re.compile(r'\bHall\b')

    for category, url in urls:
        listing_soup = fetch_cache(url, 'lxml')

        for location in listing_soup.select('.currentList .locationListing li'):
            ident = location.select_one('a').attrs['href'].split('/')[-2]

            if ident in locations:
                debug('already processed', ident)
                locations[ident]['categories'][category] = True
                continue

            classes = location.attrs.get('class', [])
            name = location.get_text()

            soup = fetch_cache(f'https://apps.carleton.edu/map/{ident}/', 'lxml')

            categories = parse_classes(classes)
            categories[category] = True
            if house_regex.search(name):
                categories['house'] = True
            elif hall_regex.search(name):
                categories['hall'] = True

            location_attrs = soup.select('.locationAttribute')
            attributes = parse_location_attrs(location_attrs)

            img = None
            img_el = soup.select_one('#locationRepresentativeImage')
            if img_el:
                link = img_el.select_one('img').attrs['src']
                link = link.replace('_tn', '')
                img = fetch_cache_img('https://apps.carleton.edu' + link, name=ident + '.jpg')

            json_detail = fetch_cache(
                f'https://apps.carleton.edu/map/api/static/?size=1x1&context=1&buildings={ident}&format=json',
                mode='json',
            )

            outline = []
            if not json_detail.get('error', False):
                outline = json_detail['all_building_coords']
                outline = [[p['lat'], p['lon']] for shape in outline for p in shape]
                centerpoint = [json_detail['center_lat'], json_detail['center_lon']]

            locations[ident] = {
                'id': ident,
                'name': name,
                'photo': img,
                'categories': categories,
                'outline': outline,
                'center': centerpoint,
                **attributes,
            }

    return locations


buildings = list(get_buildings().values())

with open('./data.json', 'w', encoding='utf-8') as outfile:
    json.dump(buildings, outfile, indent='\t', sort_keys=True)
