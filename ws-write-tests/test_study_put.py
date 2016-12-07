#!/usr/bin/env python

import datetime
import sys
from opentreetesting import test_http_json_method, writable_api_host_and_oauth_or_exit

DOMAIN, auth_token = writable_api_host_and_oauth_or_exit(__file__)
A_STUDY_URI = DOMAIN + '/v4/study'
data = {'auth_token': auth_token}
if not test_http_json_method(A_STUDY_URI,
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
A_STUDY_URI = A_STUDY_URI + '/' + study_id
# Put of empty data should result in 400
r = test_http_json_method(A_STUDY_URI,
                          'PUT',
                          data,
                          expected_status=400)
print(r)
if not r:
    sys.exit(1)

DOMAIN, auth_token = writable_api_host_and_oauth_or_exit(__file__)
data = {'output_nexml2json': '1.0.0'}
r = test_http_json_method(A_STUDY_URI, "GET", data=data, expected_status=200, return_bool_data=True)
if not r[0]:
    sys.exit(0)
resp = r[1]
starting_commit_SHA = resp['sha']
n = resp['data']
# refresh a timestamp so that the test generates a commit
m = n['nexml']['^bogus_timestamp'] = datetime.datetime.utcnow().isoformat()
data = {'nexson': n,
        'auth_token': auth_token,
        'starting_commit_SHA': starting_commit_SHA,
        }
r = test_http_json_method(A_STUDY_URI,
                          'PUT',
                          data=data,
                          expected_status=200,
                          return_bool_data=True)
if not r[0]:
    sys.exit(0)
print r[1]
