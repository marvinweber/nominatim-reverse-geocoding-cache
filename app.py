import hashlib
import json
import logging
from datetime import datetime
import time
from flask import Flask, request as flask_req, make_response
import redis
import requests
import os


logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s :: %(levelname)s :: %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
redis_host = os.environ.get('REDIS_HOST', 'localhost')
logger.info(f'Connecting to redis: {redis_host}')
r = redis.Redis(host=redis_host, port=6379, db=0)

NOMINATIM_SERVER = 'https://nominatim.openstreetmap.org'
LAST_NOMINATIM_REQUEST_KEY = 'LAST_NOMINATIM_REQUEST'
NOMINATIM_REQ_TIMEOUT = 2  # 2 seconds

DATA_TTL = 60 * 60 * 24 * 365 * 2  # 2 years

REQ_COUNTER_CACHE_KEY = 'request_counter'
NOMINATIM_REQ_COUNTER_CACHE_KEY = 'nominatim_request_counter'

CACHE_QUERY_FIELDS = ['lat', 'lon', 'format', 'json_callback', 'addressdetails', 'extratags', 'namedetails', 'accept-language',
                      'zoom', 'polygon_geojson', 'polygon_kml', 'polygon_svg', 'polygon_text', 'polygon_threshold']


@app.route("/")
def home():
    return 'ok'


@app.route("/reverse")
def reverse():
    r.incr(REQ_COUNTER_CACHE_KEY)
    full_path = flask_req.full_path
    headers = flask_req.headers
    args = flask_req.args.copy()
    resp = make_response()

    # ensure the "accept-language" query param is always set
    args.setdefault('accept-language', 'en-us')
    # filter args that should be used for creating cache key and sort them
    cache_args = sorted([(key, value) for (key, value)
                        in args.items() if key in CACHE_QUERY_FIELDS])
    cache_key_hash = hashlib.md5(
        ('__'.join([f'{key}={value}' for (key, value) in cache_args])).encode('utf-8')).hexdigest()
    cache_key_data = f'nr__{cache_key_hash}__data'
    cache_key_info = f'nr__{cache_key_hash}__info'  # cache for status code and headers

    response_data = r.get(cache_key_data)
    response_info = r.get(cache_key_info)
    if not response_data or not response_info:
        r.incr(NOMINATIM_REQ_COUNTER_CACHE_KEY)
        logger.info('Request not cached! Requesting from nominatim...')

        # ensure requests are throttled to nomatim api
        # note: this is not yet multi-thread safe!
        last_nominatim_request = float(r.get(LAST_NOMINATIM_REQUEST_KEY) or 0)
        timeout_wait = last_nominatim_request - datetime.now().timestamp() + \
            NOMINATIM_REQ_TIMEOUT
        if timeout_wait > 0:
            logger.info(
                f'Waiting {timeout_wait}s before sending request to nominatim')
            time.sleep(timeout_wait)

        # request info from nominatim
        nominatim_response = requests.get(f'{NOMINATIM_SERVER}{full_path}', headers=headers)
        response_data = nominatim_response.content
        response_info = {
            'status_code': nominatim_response.status_code,
            'headers': {
                'Content-Type': nominatim_response.headers['Content-Type']
            },
            'timestamp': datetime.now().timestamp(),
        }

        r.set(LAST_NOMINATIM_REQUEST_KEY, datetime.now().timestamp())
        
        # cache request data
        r.set(cache_key_data, response_data, DATA_TTL)
        r.set(cache_key_info, json.dumps(response_info), DATA_TTL)
    else:
        logger.debug('Serving cached request...')
        response_info = json.loads(response_info)
        resp.headers['X-Cached-Response'] = 'True'
        resp.headers['X-Cache-Timestamp'] = response_info['timestamp']

    resp.data = response_data
    resp.status_code = response_info['status_code']
    resp.headers.update(response_info['headers'])
    return resp
