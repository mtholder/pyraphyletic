#!/usr/bin/env python
from celery import Celery
from peyotl import get_logger
import requests
import traceback
import json

celery = Celery()
celery.config_from_object('celeryconfig')


# noinspection PyBroadException
@celery.task
def call_http_json(url,
                   verb='GET',
                   data=None,
                   headers=None):
    _LOG = get_logger(__name__)
    if headers is None:
        headers = {'content-type': 'application/json', 'accept': 'application/json', }
    _LOG.debug('url = {}  verb = {}  data = {}'.format(url, verb, data))
    resp = None
    try:
        if data:
            resp = requests.request(verb, url, headers=headers, data=json.dumps(data), allow_redirects=True)
        else:
            resp = requests.request(verb, url, headers=headers, allow_redirects=True)
        resp.raise_for_status()
        return resp.status_code, resp.json()
    except:
        _LOG.exception('call_http_json E1')
        try:
            x = resp.status_code
        except:
            _LOG.exception('call_http_json E2')
            x = -1
        try:
            return x, 'Error response with JSON = ' + json.dumps(resp.json())
        except:
            _LOG.exception('call_http_json E3')
            try:
                return x, 'Error: response with text = ' + resp.text
            except:
                m = 'Unknown error: ' + traceback.format_exc()
                _LOG.exception('call_http_json E4')
                return x, m
