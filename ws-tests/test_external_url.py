#!/usr/bin/env python
import sys

from opentreetesting import test_http_json_method, config

DOMAIN = config('host', 'apihost')
SUBMIT_URI = DOMAIN + '/v4/study/list'
# sys.stderr.write('Calling "{}"...\n'.format(SUBMIT_URI))
r = test_http_json_method(SUBMIT_URI,
                          'GET',
                          expected_status=200,
                          return_bool_data=True)
if not r[0]:
    sys.exit(1)
study_id = r[1][0]
SUBMIT_URI = DOMAIN + '/v3/external_url/{}'.format(study_id)
r = test_http_json_method(SUBMIT_URI,
                          'GET',
                          expected_status=200,
                          return_bool_data=True)
if not r[0]:
    sys.exit(1)
from_old = r[1]
SUBMIT_URI = DOMAIN + '/v4/study/external_url/{}'.format(study_id)
r = test_http_json_method(SUBMIT_URI,
                          'GET',
                          expected_status=200,
                          return_bool_data=True)
if not r[0]:
    sys.exit(1)
from_new = r[1]
if (from_new['url'] != from_old['url']) or (from_new['doc_id'] != from_old['study_id']):
    sys.exit('URLs from old ({}) and new ({}) invocations differ.'.format(from_old, from_new))
