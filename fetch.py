#!/usr/bin/env python3

import requests
import argparse
import yaml
import json
import sys
import re
from pathlib import Path
from bs4 import BeautifulSoup

page_cache = {}


def debug(*args, **kwargs):
    print(*args, **kwargs, file=sys.stderr)


def fetch_cache(url, *, mode, force=False, cache_dir: Path):
    if mode == 'lxml':
        dest = cache_dir / 'html' / (url.replace('/', '_') + '.html')
    elif mode == 'json':
        dest = cache_dir / 'json' / (url.replace('/', '_') + '.json')
    dest.parent.mkdir(exist_ok=True)

    if url + mode in page_cache:
        debug('using memory cache for', url)
        return page_cache[url + mode]

    try:
        if force:
            raise Exception('trigger catch')
        with open(dest, 'r', encoding='utf-8') as infile:
            body = infile.read()
            debug('using cache for', url)
    except:
        debug('fetching', url)
        r = requests.get(url)
        body = r.text
        if mode == 'lxml':
            soup = BeautifulSoup(body, 'lxml')
            [t.decompose() for t in soup.find_all('script')]
            [t.decompose() for t in soup.find_all('style')]
            [t.decompose() for t in soup.find_all('link')]
            [t.decompose() for t in soup.find_all('img') if t.attrs['src'].startswith('data:')]
            [t.decompose() for t in soup.find_all('input')]
            [t.decompose() for t in soup.select('#mapData')]
            [t.decompose() for t in soup.select('#footer')]
            [t.decompose() for t in soup.select('#carletonBanner')]
            body = soup.prettify()
        with open(dest, 'w', encoding='utf-8') as outfile:
            outfile.write(body)

    if mode == 'lxml':
        body = BeautifulSoup(body, 'lxml')
    elif mode == 'json':
        body = json.loads(body)

    page_cache[url + mode] = body
    return body


def fetch_cache_img(url, *, name, force=False, cache_dir: Path):
    dest = cache_dir / 'img' / name
    dest.parent.mkdir(exist_ok=True)

    try:
        if force:
            raise Exception('trigger catch')
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
        'accessibility': 'unknown',
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
            label = label_el.get_text().strip().lower().strip(':')

        value = None
        if label == 'address':
            bits = thing.select('.buildingAttributes li')
            if len(bits) >= 1:
                value = bits[0].get_text().strip()
            if len(bits) == 2:
                access_level = 'unknown'
                text = bits[1].get_text().strip()
                if text == 'Wheelchair Access':
                    access_level = 'wheelchair'
                elif text == 'No Handicap Access':
                    access_level = 'none'
                elif text == 'Unkown':
                    access_level = 'unknown'

                attrs['accessibility'] = access_level
        elif label == 'floors':
            floors = thing.select('.buildingFloors a')
            value = [{'href': f.attrs['href'], 'label': f.get_text().strip()} for f in floors]
        elif label == 'offices':
            offices = thing.select('.buildingAttributes a')
            value = [{'href': o.attrs['href'], 'label': o.get_text().strip()} for o in offices]
        elif label == 'departments':
            depts = thing.select('.buildingAttributes a')
            value = [{'href': d.attrs['href'], 'label': d.get_text().strip()} for d in depts]
        elif label == 'description':
            description_bits = thing.select('.buildingAttributes p')
            value = [bit.get_text().strip() for bit in description_bits]

        attrs[label] = value

    return attrs


def get_buildings(*, force=False, cache_dir: Path, overrides={}):
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
        listing_soup = fetch_cache(url, mode='lxml', force=force, cache_dir=cache_dir)

        for location in listing_soup.select('.currentList .locationListing li'):
            ident = location.select_one('a').attrs['href'].split('/')[-2]

            if ident in locations:
                debug('already processed', ident)
                locations[ident]['categories'][category] = True
                continue

            classes = location.attrs.get('class', [])
            name = location.get_text().strip()

            soup = fetch_cache(f'https://apps.carleton.edu/map/{ident}/', force=force, mode='lxml', cache_dir=cache_dir)

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
                img = fetch_cache_img('https://apps.carleton.edu' + link, force=force, name=ident + '.jpg', cache_dir=cache_dir)

            json_detail = fetch_cache(
                f'https://apps.carleton.edu/map/api/static/?size=1x1&context=1&buildings={ident}&format=json',
                mode='json',
                force=force,
                cache_dir=cache_dir,
            )

            outline = []
            centerpoint = None
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true',
                        help='Force a re-download of all files')
    parser.add_argument('--root-dir', action='store', default='./', metavar='DIR',
                        help='Where to cache the downloaded files')
    args = parser.parse_args()

    cache_dir = Path(args.root_dir) / 'cache'
    overrides_file = Path(args.root_dir) / 'overrides.yaml'
    with open(overrides_file, 'r', encoding='utf-8') as infile:
        overrides = yaml.safe_load(infile)

    buildings = get_buildings(force=args.force, cache_dir=cache_dir, overrides=overrides)
    building_list = list(buildings.values())
    dump = json.dumps(building_list, indent='\t', sort_keys=True)
    print(dump)


if __name__ == '__main__':
    main()
