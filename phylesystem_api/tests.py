import unittest
import os

from pyramid import testing
from phylesystem_api.util import fill_app_settings

def get_app_settings_for_testing(settings):
    from peyotl.utility.imports import SafeConfigParser
    cfg = SafeConfigParser()
    devini_path = os.path.abspath(os.path.join('..', 'development.ini'))
    if not os.path.isfile(devini_path):
        raise RuntimeError('Expecting a INI file at "{}" to run tests'.format(devini_path))
    cfg.read(devini_path)
    settings['repo_parent'] = cfg.get('app:main', 'repo_parent')
    fill_app_settings(settings=settings)

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
        request = testing.DummyRequest(post={'src': inp})
        from phylesystem_api.views import render_markdown
        d = render_markdown(request)
        expected = '<p>hi from <a href="http://phylo.bio.ku.edu" target="_blank">http://phylo.bio.ku.edu</a> and  <a href="https://github.com/orgs/OpenTreeOfLife/dashboard" target="_blank">https://github.com/orgs/OpenTreeOfLife/dashboard</a></p>'
        self.assertEquals(d.body, expected)

    def test_study_list(self):
        request = testing.DummyRequest()
        get_app_settings_for_testing(request.registry.settings)
        from phylesystem_api.views import study_list
        x = study_list(request)


