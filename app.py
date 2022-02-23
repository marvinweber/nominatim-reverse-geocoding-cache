import hashlib
import logging
from datetime import datetime
import time
from flask import Flask, request as flask_req
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
NOMINATIM_REQ_TIMEOUT = 3  # 5 seconds

CACHE_QUERY_FIELDS = ['lat', 'lon', 'format', 'json_callback', 'addressdetails', 'extratags', 'namedetails', 'accept-language',
                      'zoom', 'polygon_geojson', 'polygon_kml', 'polygon_svg', 'polygon_text', 'polygon_threshold']


@app.route("/")
def home():
    return 'ok'


@app.route("/reverse")
def reverse():
    full_path = flask_req.full_path
    headers = flask_req.headers
    args = flask_req.args.copy()

    # ensure the "accept-language" query param is always set
    args.setdefault('accept-language', 'en-us')
    # filter args that should be used for creating cache key and sort them
    cache_args = sorted([(key, value) for (key, value)
                        in args.items() if key in CACHE_QUERY_FIELDS])
    cache_key = 'nominatim_req__' + hashlib.md5(('__'.join(
        [f'{key}={value}' for (key, value) in cache_args])).encode('utf-8')).hexdigest()

    response_data = r.get(cache_key)
    if not response_data:
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
        r.set(LAST_NOMINATIM_REQUEST_KEY, datetime.now().timestamp())
        r.set(cache_key, response_data)
    else:
        logger.debug('Serving cached request...')

    return response_data
