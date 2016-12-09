#!/usr/bin/env python
import unittest

from opentreetesting import test_http_json_method, config
from phylesystem_api.tests import check_push_failure_response

DOMAIN = config('host', 'apihost')


class TestStudyListAndConfig(unittest.TestCase):
    def test_study_list_and_config(self):
        UB_SUBMIT_URI = DOMAIN + '/v4/study/push_failure'
        r = test_http_json_method(UB_SUBMIT_URI, 'GET', expected_status=200, return_bool_data=True)
        self.assertTrue(r[0])
        check_push_failure_response(self, r[1])


if __name__ == '__main__':
    # TODO: argv hacking only necessary because of the funky invocation of the test from
    # germinator/ws-tests/run_tests.sh
    import sys

    sys.argv = sys.argv[:1]
    unittest.main()
