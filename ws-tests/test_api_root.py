#!/usr/bin/env python
import sys

from opentreetesting import test_http_json_method, config

DOMAIN = config('host', 'apihost')
SUBMIT_URI = '{d}/v4/'.format(d=DOMAIN)
if test_http_json_method(SUBMIT_URI, 'GET', expected_status=200):
    sys.exit(0)
sys.exit(1)
