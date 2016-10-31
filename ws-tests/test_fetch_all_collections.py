#!/usr/bin/env python
import sys, os
from opentreetesting import test_http_json_method, config
DOMAIN = config('host', 'apihost')
# backwards compat, support "list_all"
SUBMIT_URI = DOMAIN + '/v3/collections/find_collections'
r = test_http_json_method(SUBMIT_URI,
                          'GET',
                          expected_status=200,
                          return_bool_data=True)
if not r[0]:
    sys.exit(1)
full_objs = r[1]
full_objs_by_id = {i['id']: i for i in full_objs}
SUBMIT_URI = DOMAIN + '/v4/collections/list'
r = test_http_json_method(SUBMIT_URI,
                          'GET',
                          expected_status=200,
                          return_bool_data=True)
if not r[0]:
    sys.exit(1)

fo_ids = set(full_objs_by_id.keys())
list_ids = set(r[1])
print fo_ids
print list_ids
if set(full_objs_by_id.keys()) != set(r[1]):
    sys.exit('.../find_collections and .../list returned different responses.')