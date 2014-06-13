from phylesystem_api.util import get_phylesystem
from pyramid.httpexceptions import HTTPNotFound
from pyramid.view import view_config
import logging
_LOG = logging.getLogger(__name__)

@view_config(route_name='home', renderer='json')
def index(request):
    return {
        "description": "The Open Tree API",
        "source_url": "https://github.com/OpenTreeOfLife/phylesystem-api/",
        "documentation_url": "https://github.com/OpenTreeOfLife/phylesystem-api/tree/master/docs"
    }

@view_config(route_name='study_list', renderer='json')
def study_list(request):
    phylesystem = get_phylesystem(request.registry.settings)
    return phylesystem.get_study_ids()

@view_config(route_name='phylesystem_config', renderer='json')
def phylesystem_config(request):
    phylesystem = get_phylesystem(request.registry.settings)
    return phylesystem.get_configuration_dict()

@view_config(route_name='unmerged_branches', renderer='json')
def unmerged_branches(request):
    phylesystem = get_phylesystem(request.registry.settings)
    bl = phylesystem.get_branch_list()
    bl.sort()
    return bl

@view_config(route_name='external_url', renderer='json')
def external_url(request):
    phylesystem = get_phylesystem(request.registry.settings)
    study_id = request.matchdict['study_id']
    try:
        u = phylesystem.get_public_url(study_id)
        return {'url': u, 'study_id': study_id}
    except:
        msg = 'study {} not found in external_url'.format(study_id)
        _LOG.exception(msg)
        raise HTTPNotFound(body=msg)
 
