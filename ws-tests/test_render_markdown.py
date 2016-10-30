#!/usr/bin/env python
import unittest

from opentreetesting import get_response_from_http, config
from phylesystem_api.tests import check_render_markdown_response, render_test_input

DOMAIN = config('host', 'apihost')


class TestRenderMarkdown(unittest.TestCase):
    def test_render_markdown(self):
        RM_SUBMIT_URI = DOMAIN + '/phylesystem/render_markdown'
        r = get_response_from_http(RM_SUBMIT_URI, 'POST', data={'src': render_test_input})
        r.body = r.text
        check_render_markdown_response(self, r)


if __name__ == '__main__':
    # TODO: argv hacking only necessary because of the funky invocation of the test from
    # germinator/ws-tests/run_tests.sh
    import sys
    sys.argv = sys.argv[:1]
    unittest.main()
