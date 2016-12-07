#!/usr/bin/env python
import sys

from opentreetesting import test_http_json_method, config

DOMAIN = config('host', 'apihost')
# backwards compat, support "list_all"
SUBMIT_URI = DOMAIN + '/v3/amendments/amendment_list'
r = test_http_json_method(SUBMIT_URI,
                          'GET',
                          expected_status=200,
                          return_bool_data=True)
if not r[0]:
    sys.exit(1)
la = r[1]
SUBMIT_URI = DOMAIN + '/v4/amendments/list'
r = test_http_json_method(SUBMIT_URI,
                          'GET',
                          expected_status=200,
                          return_bool_data=True)
if not r[0]:
    sys.exit(1)
if la != r[1]:
    sys.exit('.../list_all and .../list returned different responses.')
