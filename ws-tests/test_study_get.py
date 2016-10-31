#!/usr/bin/env python
import sys, os
from opentreetesting import test_http_json_method, config
DOMAIN = config('host', 'apihost')
SUBMIT_URI = DOMAIN + '/v4/study/list'
#sys.stderr.write('Calling "{}"...\n'.format(SUBMIT_URI))
r = test_http_json_method(SUBMIT_URI,
                          'GET',
                          expected_status=200,
                          return_bool_data=True)
if not r[0]:
    sys.exit(1)
study_id = r[1][0]

SUBMIT_URI = DOMAIN + '/v1/study/{}'.format(study_id)
data = {'output_nexml2json':'1.2'}
if test_http_json_method(SUBMIT_URI, 'GET', data=data, expected_status=200):
    sys.exit(0)
sys.exit(1)
