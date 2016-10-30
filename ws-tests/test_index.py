#!/usr/bin/env python
import unittest
import re
from opentreetesting import test_http_json_method, config
from phylesystem_api.tests import check_index_response

DOMAIN = config('host', 'apihost')
pre_v = re.compile(r'^(.+)/v[0-9]+')

class TestIndex(unittest.TestCase):
    def test_index(self):
        global DOMAIN
        m = pre_v.match(DOMAIN)
        if m:
            DOMAIN = m.group(1)
        I_SUBMIT_URI = DOMAIN + '/phylesystem/'
        r = test_http_json_method(I_SUBMIT_URI, 'GET', expected_status=200, return_bool_data=True)
        self.assertTrue(r[0])
        check_index_response(self, r[1])

if __name__ == '__main__':
    # TODO: argv hacking only necessary because of the funky invocation of the test from
    # germinator/ws-tests/run_tests.sh
    import sys
    sys.argv = sys.argv[:1]
    unittest.main()
