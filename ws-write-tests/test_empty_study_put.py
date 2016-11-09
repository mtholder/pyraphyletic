#!/usr/bin/env python
import sys
from opentreetesting import test_http_json_method, writable_api_host_and_oauth_or_exit

DOMAIN, auth_token = writable_api_host_and_oauth_or_exit(__file__)
PUT_URI = DOMAIN + '/v4/study'
data = { 'auth_token': auth_token}
if not test_http_json_method(PUT_URI,
                             'PUT',
                             data,
                             expected_status=404):
    sys.exit(1)

SL_URI = DOMAIN + '/v3/study_list'
r = test_http_json_method(SL_URI,
                          'GET',
                          expected_status=200,
                          return_bool_data=True)
if not r[0]:
    sys.exit(1)

study_id = r[1][0]
PUT_URI = PUT_URI + '/' + study_id
if not test_http_json_method(PUT_URI,
                             'PUT',
                             data,
                             expected_status=400):
    sys.exit(1)
