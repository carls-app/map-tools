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
    categories = set()

    for c in classes:
        if c == "academicTypeLocation":
            categories.add('academic')
        elif c == "administrativeTypeLocation":
            categories.add('administrative')
        elif c == "employeeHousingTypeLocation":
            categories.add('employee-housing')
        elif c == "studentHousingTypeLocation":
            categories.add('student-housing')

    return categories


def parse_location_attrs(locationAttributes):
    attrs = {
        'address': None,
        'accessibility': 'unknown',
        'floors': [],
        'offices': [],
        'departments': [],
        'description': '',
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
            value = [f'{v["label"]} <{v["href"]}>' for v in value]
        elif label == 'offices':
            offices = thing.select('.buildingAttributes a')
            value = [{'href': o.attrs['href'], 'label': o.get_text().strip()} for o in offices]
            value = [f'{v["label"]} <{v["href"]}>' for v in value]
        elif label == 'departments':
            depts = thing.select('.buildingAttributes a')
            value = [{'href': d.attrs['href'], 'label': d.get_text().strip()} for d in depts]
            value = [f'{v["label"]} <{v["href"]}>' for v in value]
        elif label == 'description':
            description_bits = thing.select('p')
            value = "\n\n".join([bit.get_text().strip() for bit in description_bits])

        attrs[label] = value

    if not attrs['address'] and not attrs['description']:
        description_bits = [thing.select('p') for thing in locationAttributes]
        value = "\n\n".join([bit.get_text().strip() for thing in description_bits for bit in thing])
        attrs['description'] = value

    return attrs


def get_features(*, force=False, cache_dir: Path, overrides={}):
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
                locations[ident]['properties']['categories'].add(category)
                continue

            # grab the override, if it exists
            override = next((x for x in overrides['changes'] if x['id'] == ident), None)

            classes = location.attrs.get('class', [])
            name = location.get_text().strip()

            if override and override.get('name', ''):
                name = override['name']

            soup = fetch_cache(f'https://apps.carleton.edu/map/{ident}/', force=force, mode='lxml', cache_dir=cache_dir)

            categories = parse_classes(classes)
            categories.add(category)
            if house_regex.search(name):
                categories.add('house')
            elif hall_regex.search(name):
                categories.add('hall')

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
                outline = [[[p['lon'], p['lat']] for shape in outline for p in shape]]
                centerpoint = [json_detail['center_lon'], json_detail['center_lat']]

            feature = {
                'type': 'Feature',
                'id': ident,
                'properties': {
                    'name': name,
                    'categories': categories,
                    **attributes,
                },
                'geometry': {
                    'type': 'GeometryCollection',
                    'geometries': []
                }
            }

            if img:
                feature['properties']['photos'] = [img]

            if override and override.get('outline', []):
                outline = override['outline']

            if len(outline):
                # the first and last positions of at ring of coordinates
                # must be the same
                for ring in outline:
                    if ring[0] != ring[-1]:
                        debug(f'editing ring for {ident}')
                        ring.append(ring[0])
                feature['geometry']['geometries'].append({
                    'type': 'Polygon',
                    'coordinates': outline,
                })
            if centerpoint:
                feature['geometry']['geometries'].append({
                    'type': 'Point',
                    'coordinates': centerpoint,
                })
            if not centerpoint and not len(outline):
                debug(f'warning: {ident} has no geometry!')
                del feature['geometry']

            locations[ident] = feature

    for location in locations.values():
        location['properties']['categories'] = sorted(list(location['properties']['categories']))

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

    features = get_features(force=args.force, cache_dir=cache_dir, overrides=overrides)
    feature_collection = {
        'type': 'FeatureCollection',
        'features': list(features.values()),
    }
    dump = json.dumps(feature_collection, indent='\t', sort_keys=True, ensure_ascii=False)
    print(dump)


if __name__ == '__main__':
    main()
