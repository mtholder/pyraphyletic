from pyramid.config import Configurator
from pyramid.request import Request
from pyramid.request import Response

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
    config = Configurator(settings=settings)
    config.include('pyramid_chameleon')
    config.set_request_factory(request_factory)
    config.add_static_view('static', 'static', cache_max_age=3600)
    config.add_route('get_sub', '/v1/study/{study_id}/{subresource}')
    config.add_route('get_sub_id', '/v1/study/{study_id}/{subresource}/{subresource_id}')
    config.add_route('get_study', '/v1/study/{study_id}')
    config.add_route('home', '/v1')
    config.add_route('study_list', '/v1/study_list')
    config.add_route('phylesystem_config', '/v1/phylesystem_config')
    config.add_route('unmerged_branches', '/v1/unmerged_branches')
    config.add_route('external_url', '/v1/external_url/{study_id}')
    config.add_route('repo_nexson_format', '/v1/repo_nexson_format')
    config.scan()
    return config.make_wsgi_app()
