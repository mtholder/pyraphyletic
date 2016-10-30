#!/usr/bin/env python
import unittest

from opentreetesting import test_http_json_method, config
from phylesystem_api.tests import check_study_list_and_config_response

DOMAIN = config('host', 'apihost')


class TestStudyListAndConfig(unittest.TestCase):
    def test_study_list_and_config(self):
        SL_SUBMIT_URI = DOMAIN + '/phylesystem/study_list'
        r = test_http_json_method(SL_SUBMIT_URI, 'GET', expected_status=200, return_bool_data=True)
        self.assertTrue(r[0])
        sl = r[1]
        DEP_SUBMIT_URI = DOMAIN + '/phylesystem/phylesystem_config'
        r = test_http_json_method(DEP_SUBMIT_URI, 'GET', expected_status=200, return_bool_data=True)
        self.assertTrue(r[0])
        full_config = r[1]
        GEN_SUBMIT_URI = DOMAIN + '/phylesystem/study/config'
        r = test_http_json_method(GEN_SUBMIT_URI, 'GET', expected_status=200, return_bool_data=True)
        self.assertTrue(r[0])
        gen_config = r[1]
        check_study_list_and_config_response(self, sl, full_config, gen_config)


if __name__ == '__main__':
    # TODO: argv hacking only necessary because of the funky invocation of the test from
    # germinator/ws-tests/run_tests.sh
    import sys
    sys.argv = sys.argv[:1]
    unittest.main()
