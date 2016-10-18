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

    def test_render_markdown(self):
        inp = 'hi from <a href="http://phylo.bio.ku.edu" target="new">http://phylo.bio.ku.edu</a> and  https://github.com/orgs/OpenTreeOfLife/dashboard'
        request = testing.DummyRequest(post=inp)
        from phylesystem_api.views import render_markdown
        d = render_markdown(request)
        expected = '<p>hi from <a href="http://phylo.bio.ku.edu" target="_blank">http://phylo.bio.ku.edu</a> and  <a href="https://github.com/orgs/OpenTreeOfLife/dashboard" target="_blank">https://github.com/orgs/OpenTreeOfLife/dashboard</a></p>'
        self.assertEquals(d.body, expected)