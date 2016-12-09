import unittest
import os

from pyramid import testing
from phylesystem_api.utility import fill_app_settings


def get_app_settings_for_testing(settings):
    from peyotl.utility.imports import SafeConfigParser
    cfg = SafeConfigParser()
    devini_path = os.path.abspath(os.path.join('..', 'development.ini'))
    if not os.path.isfile(devini_path):
        raise RuntimeError('Expecting a INI file at "{}" to run tests'.format(devini_path))
    cfg.read(devini_path)
    settings['repo_parent'] = cfg.get('app:main', 'repo_parent')
    fill_app_settings(settings=settings)


def gen_versioned_dummy_request():
    req = testing.DummyRequest()
    get_app_settings_for_testing(req.registry.settings)
    req.matchdict['api_version'] = 'v3'
    return req


def check_index_response(test_case, response):
    for k in ['documentation_url', 'description', 'source_url']:
        test_case.assertIn(k, response)


def check_render_markdown_response(test_case, response):
    expected = '<p>hi from <a href="http://phylo.bio.ku.edu" target="_blank">' \
               'http://phylo.bio.ku.edu</a> and  ' \
               '<a href="https://github.com/orgs/OpenTreeOfLife/dashboard" target="_blank">' \
               'https://github.com/orgs/OpenTreeOfLife/dashboard</a></p>'
    test_case.assertEquals(response.body, expected)


def check_study_list_and_config_response(test_case,
                                         sl_response,
                                         config_response,
                                         from_generic_config):
    nsis = sum([i['number of documents'] for i in config_response['shards']])
    test_case.assertEquals(nsis, len(sl_response))
    test_case.assertEquals(from_generic_config, config_response)


def check_unmerged_response(test_case, ub):
    test_case.assertTrue('master' not in ub)

def check_config_response(test_case, cfg):
    test_case.assertSetEqual(set(cfg.keys()), {"initialization", "shards", "number_of_shards"})

render_test_input = 'hi from <a href="http://phylo.bio.ku.edu" target="new">' \
                    'http://phylo.bio.ku.edu</a> and  ' \
                    'https://github.com/orgs/OpenTreeOfLife/dashboard'


class ViewTests(unittest.TestCase):
    def setUp(self):
        self.config = testing.setUp()

    def tearDown(self):
        testing.tearDown()

    def test_index(self):
        request = gen_versioned_dummy_request()
        from phylesystem_api.views import index
        check_index_response(self, index(request))

    def test_render_markdown(self):
        request = testing.DummyRequest(post={'src': render_test_input})
        from phylesystem_api.views import render_markdown
        check_render_markdown_response(self, render_markdown(request))

    def test_study_list_and_config(self):
        request = gen_versioned_dummy_request()
        from phylesystem_api.views import study_list
        sl = study_list(request)
        request = gen_versioned_dummy_request()
        from phylesystem_api.views import phylesystem_config
        x = phylesystem_config(request)
        request = gen_versioned_dummy_request()
        request.matchdict['resource_type'] = 'study'
        from phylesystem_api.views import generic_config
        y = generic_config(request)
        check_study_list_and_config_response(self, sl, x, y)

    def test_unmerged(self):
        request = gen_versioned_dummy_request()
        request.matchdict['resource_type'] = 'study'
        from phylesystem_api.views import unmerged_branches
        check_unmerged_response(self, unmerged_branches(request))

    def test_config(self):
        request = gen_versioned_dummy_request()
        from phylesystem_api.views import phylesystem_config
        r2 = phylesystem_config(request)
        check_config_response(self, r2)
        request.matchdict['resource_type'] = 'study'
        from phylesystem_api.views import generic_config
        r = generic_config(request)
        check_config_response(self, r)
        self.assertDictEqual(r, r2)

if __name__ == '__main__':
    unittest.main()
