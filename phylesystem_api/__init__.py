# from phylesystem_api.util import get_phylesystem
from pyramid.config import Configurator
from pyramid.request import Request
from pyramid.request import Response
from phylesystem_api.util import fill_app_settings


# Adapted from:
#   http://stackoverflow.com/questions/21107057/pyramid-cors-for-ajax-requests
# and our previous CORS headers (in the web2py version of the phylesystem-api)
def request_factory(environ):
    request = Request(environ)
    if request.is_xhr:
        request.response = Response()
        request.response.headerlist = []
        request.response.headerlist.extend(
            (
                ('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Credentials', 'true'),
                ('Access-Control-Max-Age', 86400),
                ('Content-Type', 'application/json')
            )
        )
    return request


def main(global_config, **settings):
    """ This function returns a Pyramid WSGI application.
    """
    fill_app_settings(settings)
    config = Configurator(settings=settings)
    config.include('pyramid_chameleon')
    config.set_request_factory(request_factory)
    config.add_static_view('static', 'static', cache_max_age=3600)
    config.add_route('home', '/')
    config.add_route('render_markdown', '/render_markdown')
    vstr = '{api_version:v1|v2|v3}'
    config.add_route('study_list', vstr + '/study_list')
    # Deprecate in phylesystem_config in favor of generic_config
    config.add_route('phylesystem_config', vstr + '/phylesystem_config')
    config.add_route('generic_config',  vstr + '/{resource_type}/config')
    # v3/unmerged_branches defaults to phylesystem
    config.add_route('unmerged_branches',  vstr + '/{resource_type}/unmerged_branches')

    config.add_route('study_external_url', vstr + '/external_url/{study_id}')
    #config.add_route('options_study', '{api_version}/study')
    #config.add_route('options_study_id', '{api_version}/study/{study_id}')
    #config.add_route('options_generic', '{api_version}/{resourt_type}')

    skip = '''
        config.add_route('get_sub', vstr + 'study/{study_id}/{subresource}')
        config.add_route('get_sub_id', vstr + 'study/{study_id}/{subresource}/{subresource_id}')
        config.add_route('get_study_id', vstr + 'study/{study_id}')
        config.add_route('post_study_id', vstr + 'study/{study_id}')
        config.add_route('post_study', vstr + 'study')
        config.add_route('push_id', vstr + 'push/{study_id}')
        config.add_route('put_study_id', vstr + 'study/{study_id}')
        config.add_route('delete_study_id', vstr + 'study/{study_id}')
        config.add_route('options_study_id', vstr + 'study/{study_id}')
        config.add_route('search', vstr + 'search/{kind}/{property_name}/{search_term}')
        config.add_route('nudge_indexers', vstr + 'nudgeIndexOnUpdates')
        config.add_route('merge_id', vstr + 'merge')
        config.add_route('push', vstr + 'push')
        config.add_route('unmerged_branches', vstr + 'unmerged_branches')
        '''
    config.scan()
    return config.make_wsgi_app()
