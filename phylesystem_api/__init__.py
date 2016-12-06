# from phylesystem_api.util import get_phylesystem
from pyramid.config import Configurator
from pyramid.request import Request
from pyramid.request import Response
from phylesystem_api.views import fill_app_settings
import logging

_LOG = logging.getLogger(__name__)


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
    _LOG.debug('main running from "{}" and called with "{}"'.format(global_config['here'],
                                                                    global_config['__file__']))
    from phylesystem_api.views import get_resource_type_to_umbrella_name_copy
    fill_app_settings(settings)
    config = Configurator(settings=settings)
    config.include('pyramid_chameleon')
    config.set_request_factory(request_factory)
    config.add_static_view('static', 'static', cache_max_age=3600)
    config.add_route('home', '/')
    # Some routes need to have a API version prefix.
    # Some need a resource_type  like study, amendment, collection
    # And other need version/resource_type
    # So we compose these prefixes here
    v_prefix = '{api_version:v1|v2|v3|v4}'
    rt_keys = get_resource_type_to_umbrella_name_copy().keys()
    joined_rt_keys = '|'.join(rt_keys)
    rt_prefix = '{resource_type:' + joined_rt_keys + '}'
    v_rt_prefix = v_prefix + '/' + rt_prefix

    # The doc IDs have different regex patterns, so we build a url frag to match each type
    # these can be used in URLs that are specific to one resource type.
    phylesystem = settings['phylesystem']
    taxon_amendments = settings['taxon_amendments']
    tree_collections = settings['tree_collections']
    study_id_frag = "{doc_id:" + phylesystem.id_regex.pattern + "}"
    study_id_ext_frag = "{doc_id:" + phylesystem.id_regex.pattern + "[.][a-z]+}"
    amendment_id_frag = "{doc_id:" + taxon_amendments.id_regex.pattern + "}"
    collection_id_frag = "{coll_user_id:[a-zA-Z0-9-]+}/{coll_id:[a-zA-Z0-9-]+}"
    # Set up the routes that we anticipate using in v4 and above:
    config.add_route('versioned_home',
                     v_prefix + '/',
                     request_method='GET')
    config.add_route('render_markdown',
                     v_prefix + '/render_markdown',
                     request_method='POST')
    config.add_route('generic_config',
                     v_rt_prefix + '/config',
                     request_method='GET')
    config.add_route('unmerged_branches',
                     v_rt_prefix + '/unmerged_branches',
                     request_method='GET')
    config.add_route('generic_list',
                     v_rt_prefix + '/list',
                     request_method='GET')
    config.add_route('generic_external_url',
                     v_rt_prefix + '/external_url/{doc_id}',
                     request_method='GET')
    config.add_route('generic_push',
                     v_rt_prefix + '/push',
                     request_method='GET')
    config.add_route('generic_push_failure',
                     v_rt_prefix + '/push_failure',
                     request_method='GET')
    # GET of entire resource
    config.add_route('get_study_via_id',
                     v_prefix + '/study/' + study_id_frag,
                     request_method='GET')
    config.add_route('get_taxon_amendment_via_id',
                     v_prefix + '/amendment/' + amendment_id_frag,
                     request_method='GET')
    config.add_route('get_tree_collection_via_id',
                     v_prefix + '/collection/' + collection_id_frag,
                     request_method='GET')
    # studies support subsetting the resource w/ a GET
    config.add_route('get_study_via_id_and_ext',
                     v_prefix + '/study/' + study_id_ext_frag,
                     request_method='GET')
    study_sub_frag = '/{subresource_type:meta|tree|subtree|otus|otu|otumap|file}'
    config.add_route('get_study_subresource_no_id',
                     v_prefix + '/study/' + study_id_frag + study_sub_frag,
                     request_method='GET')
    config.add_route('get_study_subresource_via_id',
                     v_prefix + '/study/' + study_id_frag + study_sub_frag + '/{subresource_id}',
                     request_method='GET')
    # PUT methods need the doc id
    config.add_route('put_study_via_id',
                     v_prefix + '/study/' + study_id_frag,
                     request_method='PUT')
    config.add_route('put_taxon_amendment_via_id',
                     v_prefix + '/amendment/' + amendment_id_frag,
                     request_method='PUT')
    config.add_route('put_tree_collection_via_id',
                     v_prefix + '/collection/' + collection_id_frag,
                     request_method='PUT')
    # POST methods don't need the doc id
    config.add_route('post_study',
                     v_prefix + '/study/',
                     request_method='POST')
    config.add_route('post_taxon_amendment',
                     v_prefix + '/amendment/',
                     request_method='POST')
    config.add_route('post_tree_collection',
                     v_prefix + '/collection/',
                     request_method='POST')
    config.add_route('options_study_id',
                     v_prefix + '/study/' + study_id_frag,
                     request_method='OPTIONS')
    config.add_route('options_taxon_amendment_id',
                     v_prefix + '/amendment/' + amendment_id_frag,
                     request_method='OPTIONS')
    config.add_route('options_tree_collection_id',
                     v_prefix + '/collection/' + collection_id_frag,
                     request_method='OPTIONS')
    config.add_route('options_generic',
                     v_rt_prefix + '/',
                     request_method='OPTIONS')
    # push methods need the doc id (oddly enough)
    config.add_route('push_study_via_id',
                     v_prefix + '/push/study/' + study_id_frag,
                     request_method='PUT')
    config.add_route('push_taxon_amendment_via_id',
                     v_prefix + '/push/amendment/' + amendment_id_frag,
                     request_method='PUT')
    config.add_route('push_tree_collection_via_id',
                     v_prefix + '/push/collection/' + collection_id_frag,
                     request_method='PUT')

    # Methods pertaining to the set of trees currently in synth
    config.add_route('trees_in_synth',
                     v_prefix + '/trees_in_synth',
                     request_method="GET")
    config.add_route('include_tree_in_synth',
                     v_prefix + '/include_tree_in_synth',
                     request_method="POST")
    config.add_route('exclude_tree_from_synth',
                     v_prefix + '/include_tree_in_synth',
                     request_method="POST")

    # TODO add routes to be deprecated once our tools rely only on the generic forms
    config.add_route('study_list', v_prefix + '/study_list')
    config.add_route('phylesystem_config', v_prefix + '/phylesystem_config')
    config.add_route('study_external_url', v_prefix + '/external_url/{study_id}')
    config.add_route('amendment_list', v_prefix + '/amendments/amendment_list')
    # The next 2 methods are really fetch all+last commit
    config.add_route('fetch_all_amendments', v_prefix + '/amendments/list_all')
    config.add_route('fetch_all_collections', v_prefix + '/collections/find_collections')


    skip = '''
        config.add_route('get_sub', vstr + 'study/{study_id}/{subresource}')
        config.add_route('get_sub_id', vstr + 'study/{study_id}/{subresource}/{subresource_id}')
        config.add_route('post_study_id', vstr + 'study/{study_id}')
        config.add_route('post_study', vstr + 'study')
        config.add_route('push_id', vstr + 'push/{study_id}')
        config.add_route('put_study_id', vstr + 'study/{study_id}')
        config.add_route('delete_study_id', vstr + 'study/{study_id}')
        config.add_route('options_study_id', vstr + 'study/{study_id}')
        config.add_route('search', vstr + 'search/{kind}/{property_name}/{search_term}')
        config.add_route('nudge_indexers', vstr + 'nudgeIndexOnUpdates')
        config.add_route('merge_id', vstr + 'merge')
        '''
    config.scan()
    return config.make_wsgi_app()
