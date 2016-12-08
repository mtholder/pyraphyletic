#!/usr/bin/env python
import sys, os
from opentreetesting import test_http_json_method, config
DOMAIN = config('host', 'apihost')
SUBMIT_URI = DOMAIN + '/v3/trees_in_synth'
r = test_http_json_method(SUBMIT_URI,
                          'GET',
                          expected_status=200,
                          return_bool_data=True)
if not r[0]:
    sys.stderr.write("Note that the test trees_in_synth.py will fail if your test collections repo does not have " \
                     "collections that have the same IDs as the collections currently used in synthesis.\n")
    sys.exit(1)
