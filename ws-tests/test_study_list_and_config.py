#!/usr/bin/env python
import unittest

from opentreetesting import test_http_json_method, config
from phylesystem_api.tests import (check_study_list_and_config_response,
                                   check_external_url_response)

DOMAIN = config('host', 'apihost')


class TestStudyListAndConfig(unittest.TestCase):
    def test_study_list_and_config(self):
        SL_SUBMIT_URI = DOMAIN + '/v3/study_list'
        r = test_http_json_method(SL_SUBMIT_URI, 'GET', expected_status=200, return_bool_data=True)
        self.assertTrue(r[0])
        sl = r[1]
        DEP_SUBMIT_URI = DOMAIN + '/v3/phylesystem_config'
        r = test_http_json_method(DEP_SUBMIT_URI, 'GET', expected_status=200, return_bool_data=True)
        self.assertTrue(r[0])
        full_config = r[1]
        GEN_SUBMIT_URI = DOMAIN + '/v4/study/config'
        r = test_http_json_method(GEN_SUBMIT_URI, 'GET', expected_status=200, return_bool_data=True)
        self.assertTrue(r[0])
        gen_config = r[1]
        check_study_list_and_config_response(self, sl, full_config, gen_config)
        if not sl:
            return
        doc_id = sl[0]
        EXT_SUBMIT_URI = DOMAIN + '/v4/study/external_url/{}'.format(doc_id)
        r = test_http_json_method(EXT_SUBMIT_URI, 'GET', expected_status=200, return_bool_data=True)
        self.assertTrue(r[0])
        e = r[1]
        check_external_url_response(self, doc_id, e)


if __name__ == '__main__':
    # TODO: argv hacking only necessary because of the funky invocation of the test from
    # germinator/ws-tests/run_tests.sh
    import sys
    sys.argv = sys.argv[:1]
    unittest.main()
