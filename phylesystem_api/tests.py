import unittest

from pyramid import testing


class ViewTests(unittest.TestCase):
    def setUp(self):
        self.config = testing.setUp()

    def tearDown(self):
        testing.tearDown()

    def test_index(self):
        request = testing.DummyRequest()
        from phylesystem_api.views import index
        d = index(request)
        for k in ['documentation_url', 'description', 'source_url']:
            self.assertIn(k, d)
