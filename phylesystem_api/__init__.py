from pyramid.config import Configurator


def main(global_config, **settings):
    """ This function returns a Pyramid WSGI application.
    """
    config = Configurator(settings=settings)
    config.include('pyramid_chameleon')
    config.add_static_view('static', 'static', cache_max_age=3600)
    config.add_route('home', '/v1')
    config.add_route('study_list', '/v1/study_list')
    config.add_route('phylesystem_config', '/v1/phylesystem_config')
    config.add_route('unmerged_branches', '/v1/unmerged_branches')
    config.add_route('external_url', '/v1/external_url/{study_id}')
    config.scan()
    return config.make_wsgi_app()
