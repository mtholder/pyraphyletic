from peyotl import get_logger
from pyramid.view import view_config
from pyramid.response import Response
from pyramid.httpexceptions import exception_response
import markdown
import bleach

_LOG = get_logger(__name__)

_API_VERSIONS = frozenset(['v1', 'v2', 'v3'])
_RESOURCE_TYPE_2_SETTINGS_UMBRELLA_KEY = {'phylesystem': 'phylesystem',
                                          'study': 'phylesystem',
                                          'studies': 'phylesystem',
                                          'taxon_amendments': 'taxon_amendments',
                                          'amendments': 'taxon_amendments',
                                          'amendment': 'taxon_amendments',
                                          'tree_collections': 'tree_collections',
                                          'collections': 'tree_collections',
                                          'collection': 'tree_collections',
                                          }


def check_api_version(request):
    vstr = request.matchdict.get('api_version')
    if vstr not in _API_VERSIONS:
        raise exception_response(404, explanation='API version "{}" is not supported'.format(vstr))
    return vstr


def generic_umbrella(view_fn):
    """This decorator is used to match requests that contain a resource_type
    in the matchdict. If that string in not in the _RESOURCE_TYPE_2_SETTINGS_UMBRELLA_KEY
    dict, then a 404 is raised. Otherwise the appropriate "umbrella" is located
    in the global settings, and the view function is called with the
    request and the umbrella object as the first 2 arguments"""

    def check_resource_type(request, *args, **kwargs):
        rtstr = request.matchdict.get('resource_type')
        key_name = _RESOURCE_TYPE_2_SETTINGS_UMBRELLA_KEY.get(rtstr)
        if key_name is None:
            raise exception_response(404, explanation='Resource type "{}" is not supported'.format(rtstr))
        umbrella = request.registry.settings[key_name]
        return view_fn(request, umbrella, *args, **kwargs)
    return check_resource_type


@view_config(route_name='home', renderer='json')
def index(request):
    check_api_version(request)
    return {
        "description": "The Open Tree API",
        "source_url": "https://github.com/mtholder/pyraphyletic",
        "documentation_url": "https://github.com/OpenTreeOfLife/phylesystem-api/tree/master/docs"
    }


@view_config(route_name='render_markdown')
def render_markdown(request):
    check_api_version(request)
    try:
        src = request.POST['src']
    except KeyError:
        raise exception_response(400, explanation='"src" parameter not found in POST')

    def add_blank_target(attrs, new=False):
        attrs['target'] = '_blank'
        return attrs

    h = markdown.markdown(src)
    h = bleach.clean(h, tags=['p', 'a', 'hr', 'i', 'em', 'b', 'div', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4'])
    h = bleach.linkify(h, callbacks=[add_blank_target])
    return Response(h)


@view_config(route_name='study_list', renderer='json')
def study_list(request):
    return request.registry.settings['phylesystem'].get_study_ids()


@view_config(route_name='phylesystem_config', renderer='json')
def phylesystem_config(request):
    return request.registry.settings['phylesystem'].get_configuration_dict()

@view_config(route_name='generic_config', renderer='json')
@generic_umbrella
def generic_config(request, umbrella):
    return umbrella.get_configuration_dict()


@view_config(route_name='unmerged_branches', renderer='json')
@generic_umbrella
def unmerged_branches(request, umbrella):
    """Returns the non-master branches for a resource_type.
    Default is request.matchdict['resource_type'] is 'phylesystem'.
    """
    bs = set(umbrella.get_branch_list())
    bl = [i for i in bs if i != 'master']
    bl.sort()
    return bl


@view_config(route_name='study_external_url', renderer='json')
def external_url(request):
    phylesystem = request.registry.settings['phylesystem']
    study_id = request.matchdict['study_id']
    return external_url_generic(phylesystem, study_id, 'study_id')

def external_url_generic(umbrella, doc_id, doc_id_key):
    try:
        u = umbrella.get_public_url(doc_id)
        return {'url': u, doc_id_key: doc_id}
    except:
        msg = 'document {} not found'.format(doc_id)
        _LOG.exception(msg)
        raise HTTPNotFound(body=anyjson.dumps({'error': 1, 'description': msg}))

'''
@view_config(route_name='options_study_id', renderer='json', request_method='OPTIONS')
@view_config(route_name='options_study', renderer='json', request_method='OPTIONS')
@view_config(route_name='options_generic', renderer='json', request_method='OPTIONS')
@api_versioned
@generic_umbrella
def study_options(request, *valist):
    """A simple method for approving CORS preflight request"""
    if request.env.http_access_control_request_method:
        response.headers['Access-Control-Allow-Methods'] = 'POST,GET,DELETE,PUT,OPTIONS'
    if request.env.http_access_control_request_headers:
        response.headers['Access-Control-Allow-Headers'] = 'Origin, Content-Type, Accept, Authorization'
    response.status_code = 200
    return response
'''
'''
import traceback
import urllib2

import anyjson
from peyotl.nexson_syntax import get_empty_nexson, \
    PhyloSchema, \
    BY_ID_HONEY_BADGERFISH
from peyotl.phylesystem.git_workflows import GitWorkflowError, \
    merge_from_master
from pyramid.httpexceptions import HTTPNotFound, HTTPBadRequest, HTTPConflict
from pyramid.url import route_url
from pyramid.view import view_config


from phylesystem_api.util import err_body, \
    raise_http_error_from_msg, \
    authenticate, \
    new_nexson_with_crossref_metadata, \
    OTISearch



@view_config(route_name='get_sub', renderer='json', request_method='GET')
@view_config(route_name='get_sub_id', renderer='json', request_method='GET')
@view_config(route_name='get_study_id', renderer='json', request_method='GET')
def get_study(request):
    """OpenTree API methods relating to reading"""
    valid_resources = ('study',)
    params = dict(request.params)
    params.update(dict(request.matchdict))
    study_id = request.matchdict['study_id']
    valid_subresources = ('tree', 'meta', 'otus', 'otu', 'otumap')
    returning_full_study = False
    returning_tree = False
    content_id = None
    version_history = None
    # infer file type from extension
    type_ext = None
    last_word_dot_split = request.path.split('/')[-1].split('.')
    if len(last_word_dot_split) > 1:
        type_ext = '.' + last_word_dot_split[-1]

    params['type_ext'] = type_ext
    subresource = params.get('subresource')
    subresource_id = params.get('subresource_id')
    if subresource_id and ('.' in subresource_id):
        subresource_id = subresource_id.split('.')[0]  # could crop ID...
    if subresource is None:
        returning_full_study = True
        if '.' in study_id:
            study_id = study_id.split('.')[0]
        _LOG.debug('GET v1/study/{}'.format(study_id))
        return_type = 'study'
    elif subresource == 'tree':
        return_type = 'tree'
        returning_tree = True
        content_id = subresource_id
    elif subresource == 'subtree':
        subtree_id = params.get('subtree_id')
        if subtree_id is None:
            _edescrip = 'subtree resource requires a study_id and tree_id in the URL and a subtree_id parameter'
            raise HTTPBadRequest(body=err_body(_edescrip))
        return_type = 'subtree'
        returning_tree = True
        content_id = (subresource_id, subtree_id)
    elif subresource in ['meta', 'otus', 'otu', 'otumap']:
        if subresource != 'meta':
            content_id = subresource_id
        return_type = subresource
    else:
        _edescrip = 'subresource requested not in list of valid resources: %s' % ' '.join(valid_subresources)
        raise HTTPBadRequest(body=err_body(_edescrip))
    phylesystem = request.registry.settings['phylesystem']
    out_schema = _validate_output_nexml2json(phylesystem,
                                             params,
                                             return_type,
                                             content_id=content_id)
    parent_sha = params.get('starting_commit_SHA')

    _LOG.debug('parent_sha = {}'.format(parent_sha))
    # return the correct nexson of study_id, using the specified view
    try:
        r = phylesystem.return_study(study_id, commit_sha=parent_sha, return_WIP_map=True)
    except:
        _LOG.exception('GET failed')
        raise HTTPNotFound('Study #{i} GET failure'.format(i=study_id))
    try:
        study_nexson, head_sha, wip_map = r
        if returning_full_study:
            blob_sha = phylesystem.get_blob_sha_for_study_id(study_id, head_sha)
            phylesystem.add_validation_annotation(study_nexson, blob_sha)
            version_history = phylesystem.get_version_history_for_study_id(study_id)
    except:
        _LOG.exception('GET failed')
        raise_http_error_from_msg(traceback.format_exc())
    if out_schema.format_str == 'nexson' and out_schema.version == phylesystem.repo_nexml2json:
        result_data = study_nexson
    else:
        try:
            serialize = not out_schema.is_json()
            src_schema = PhyloSchema('nexson', version=phylesystem.repo_nexml2json)
            result_data = out_schema.convert(study_nexson,
                                             serialize=serialize,
                                             src_schema=src_schema)
        except:
            msg = "Exception in coercing to the required NexSON version for validation. "
            _LOG.exception(msg)
            raise HTTPBadRequest(body=err_body(msg))
    if not result_data:
        msg = 'subresource "{r}/{t}" not found in study "{s}"'.format(r=subresource,
                                                                      t=subresource_id,
                                                                      s=study_id)
        raise HTTPNotFound(body=err_body(msg))
    if returning_full_study and out_schema.is_json():
        result = {'sha': head_sha,
                  'data': result_data,
                  'branch2sha': wip_map}
        if version_history:
            result['versionHistory'] = version_history
        return result
    return result_data


@view_config(route_name='post_study_id', renderer='json', request_method='POST')
@view_config(route_name='post_study', renderer='json', request_method='POST')
def post_study(request):
    """Open Tree API methods relating to creating (and importing) resources"""
    params = dict(request.params)
    params.update(dict(request.matchdict))
    auth_info = authenticate(**params)
    phylesystem = request.registry.settings['phylesystem']
    # Studies that were created in phylografter, can be added by
    #   POSTing the content with resource_id 
    new_study_id = params.get('study_id')
    if new_study_id is not None:
        bundle = _extract_and_validate_nexson(request,
                                              phylesystem.repo_nexml2json,
                                              params)
        new_study_nexson = bundle[0]
    else:
        # we're creating a new study (possibly with import instructions in the payload)
        import_from_location = params.get('import_from_location', '')
        treebase_id = params.get('treebase_id', '')
        nexml_fetch_url = params.get('nexml_fetch_url', '')
        nexml_pasted_string = params.get('nexml_pasted_string', '')
        publication_doi = params.get('publication_DOI', '')
        publication_ref = params.get('publication_reference', '')
        # is the submitter explicity applying the CC0 waiver to a new study
        # (i.e., this study is not currently in an online repository)?
        if import_from_location == 'IMPORT_FROM_UPLOAD':
            cc0_agreement = (params.get('chosen_license', '') == 'apply-new-CC0-waiver' and
                             params.get('cc0_agreement', '') == 'true')
        else:
            cc0_agreement = False
        # look for the chosen import method, e.g,
        # 'import-method-PUBLICATION_DOI' or 'import-method-MANUAL_ENTRY'
        import_method = params.get('import_method', '')

        # dryad_DOI = params.get('dryad_DOI', '')

        app_name = "api"
        # add known values for its metatags
        meta_publication_reference = None

        # Create initial study NexSON using the chosen import method.
        #
        # N.B. We're currently using a streamlined creation path with just
        # two methods (TreeBASE ID and publication DOI). But let's keep the
        # logic for others, just in case we revert based on user feedback.
        importing_from_treebase_id = (import_method == 'import-method-TREEBASE_ID' and treebase_id)
        importing_from_nexml_fetch = (import_method == 'import-method-NEXML' and nexml_fetch_url)
        importing_from_nexml_string = (import_method == 'import-method-NEXML' and nexml_pasted_string)
        importing_from_crossref_API = (import_method == 'import-method-PUBLICATION_DOI' and publication_doi) or \
                                      (import_method == 'import-method-PUBLICATION_REFERENCE' and publication_ref)

        # Are they using an existing license or waiver (CC0, CC-BY, something else?)
        using_existing_license = (params.get('chosen_license', '') == 'study-data-has-existing-license')

        # any of these methods should returna parsed NexSON dict (vs. string)
        if importing_from_treebase_id:
            # make sure the treebase ID is an integer
            treebase_id = "".join(treebase_id.split())  # remove all whitespace
            treebase_id = treebase_id.lstrip('S').lstrip('s')  # allow for possible leading 'S'?
            try:
                treebase_id = int(treebase_id)
            except ValueError, e:
                _edescrip = "TreeBASE ID should be a simple integer, not '%s'! Details:\n%s" % (treebase_id, e.message)
                raise HTTPBadRequest(body=err_body(_edescrip))
            new_study_nexson = import_nexson_from_treebase(treebase_id,
                                                           nexson_syntax_version=BY_ID_HONEY_BADGERFISH)
        # elif importing_from_nexml_fetch:
        #     if not (nexml_fetch_url.startswith('http://') or nexml_fetch_url.startswith('https://')):
        #         raise HTTP(400, json.dumps({
        #             "error": 1,
        #             "description": 'Expecting: "nexml_fetch_url" to startwith http:// or https://',
        #         }))
        #     new_study_nexson = get_ot_study_info_from_treebase_nexml(src=nexml_fetch_url,
        #                                                     nexson_syntax_version=BY_ID_HONEY_BADGERFISH)
        # elif importing_from_nexml_string:
        #     new_study_nexson = get_ot_study_info_from_treebase_nexml(nexml_content=nexml_pasted_string,
        #                                                    nexson_syntax_version=BY_ID_HONEY_BADGERFISH)
        elif importing_from_crossref_API:
            new_study_nexson = new_nexson_with_crossref_metadata(doi=publication_doi,
                                                                 ref_string=publication_ref,
                                                                 include_cc0=cc0_agreement)
        else:  # assumes 'import-method-MANUAL_ENTRY', or insufficient args above
            new_study_nexson = get_empty_nexson(BY_ID_HONEY_BADGERFISH,
                                                include_cc0=cc0_agreement)

        nexml = new_study_nexson['nexml']

        # If submitter requested the CC0 waiver or other waiver/license, make sure it's here
        if importing_from_treebase_id or cc0_agreement:
            nexml['^xhtml:license'] = {'@href': 'http://creativecommons.org/publicdomain/zero/1.0/'}
        elif using_existing_license:
            existing_license = params.get('alternate_license', '')
            if existing_license == 'CC-0':
                nexml['^xhtml:license'] = {'@href': 'http://creativecommons.org/publicdomain/zero/1.0/'}
                pass
            elif existing_license == 'CC-BY':
                nexml['^xhtml:license'] = {'@href': 'http://creativecommons.org/licenses/by/4.0/'}
                pass
            else:  # assume it's something else
                alt_license_name = params.get('alt_license_name', '')
                alt_license_url = params.get('alt_license_URL', '')
                # OK to add a name here? mainly to capture submitter's intent
                nexml['^xhtml:license'] = {'@name': alt_license_name, '@href': alt_license_url}

        nexml['^ot:curatorName'] = auth_info.get('name', '').decode('utf-8')

    try:
        r = phylesystem.ingest_new_study(new_study_nexson,
                                         phylesystem.repo_nexml2json,
                                         auth_info,
                                         new_study_id)
        new_resource_id, commit_return = r
    except GitWorkflowError, err:
        raise_http_error_from_msg(err.msg)
    except:
        raise_http_error_from_msg(traceback.format_exc())
    if commit_return['error'] != 0:
        _LOG.debug('ingest_new_study failed with error code')
        raise HTTPBadRequest(body=json.dumps(commit_return))
    _deferred_push_to_gh_call(request, new_resource_id, **params)
    return commit_return


@view_config(route_name='put_study_id', renderer='json', request_method='PUT')
def put_study(request):
    """Open Tree API methods relating to updating existing resources"""
    parent_sha = request.params.get('starting_commit_SHA')
    if parent_sha is None:
        raise_http_error_from_msg('Expecting a "starting_commit_SHA" argument with the SHA of the parent')
    commit_msg = request.params.get('commit_msg')
    master_file_blob_included = request.params.get('merged_SHA')
    study_id = request.matchdict['study_id']
    _LOG.debug('PUT to study {} for starting_commit_SHA = {} and merged_SHA = {}'.format(study_id,
                                                                                         parent_sha,
                                                                                         str(
                                                                                             master_file_blob_included)))
    auth_info = authenticate(**request.params)
    phylesystem = request.registry.settings['phylesystem']
    bundle = _extract_and_validate_nexson(request,
                                          phylesystem.repo_nexml2json,
                                          request.params)
    nexson, annotation, nexson_adaptor = bundle
    gd = phylesystem.create_git_action(resource_id)
    try:
        blob = _finish_write_verb(phylesystem,
                                  gd,
                                  nexson=nexson,
                                  resource_id=study_id,
                                  auth_info=auth_info,
                                  adaptor=nexson_adaptor,
                                  annotation=annotation,
                                  parent_sha=parent_sha,
                                  commit_msg=commit_msg,
                                  master_file_blob_included=master_file_blob_included)
    except GitWorkflowError, err:
        _LOG.exception('PUT failed in _finish_write_verb')
        raise_http_error_from_msg(err.msg)
    mn = blob.get('merge_needed')
    if (mn is not None) and (not mn):
        _deferred_push_to_gh_call(request, study_id, **request.params)
    return blob


@view_config(route_name='delete_study_id', renderer='json', request_method='DELETE')
def delete_study(request):
    """Open Tree API methods relating to deleting existing resources"""
    # support JSONP request from another domain
    parent_sha = request.params.get('starting_commit_SHA')
    if parent_sha is None:
        raise_http_error_from_msg('Expecting a "starting_commit_SHA" argument with the SHA of the parent')
    auth_info = authenticate(**request.params)
    study_id = request.matchdict['study_id']
    phylesystem = request.registry.settings['phylesystem']
    try:
        x = phylesystem.delete_study(study_id, auth_info, parent_sha)
        if x.get('error') == 0:
            _deferred_push_to_gh_call(request, None, **request.params)
        return x
    except GitWorkflowError, err:
        raise_http_error_from_msg(err.msg)
    except:
        _LOG.exception('Exception getting nexson content in phylesystem.delete_study')
        raise_http_error_from_msg('Unknown error in study deletion')




@view_config(route_name='push_id', renderer='json')
@view_config(route_name='push', renderer='json')
def push_to_github(request):
    """OpenTree API methods relating to updating branches

    curl -X POST http://localhost:8000/api/push/v1/9
    """

    # support JSONP request from another domain
    phylesystem = request.registry.settings['phylesystem']
    study_id = request.matchdict['study_id']

    try:
        phylesystem.push_study_to_remote('GitHubRemote', study_id)
    except:
        m = traceback.format_exc()
        raise HTTPConflict(body=err_body("Could not push! Details: {m}".format(m=m)))
    return {'error': 0,
            'description': 'Push succeeded'}


@view_config(route_name='merge_id', renderer='json', request_method='POST')
def merge(request):
    """OpenTree API methods relating to updating branches

    curl -X POST http://localhost:8000/api/merge/v1/9&starting_commit_SHA=152316261261342&auth_token=$GITHUB_OAUTH_TOKEN

    If the request is successful, a JSON response similar to this will be returned:

    {
        "error": 0,
        "branch_name": "my_user_9_2",
        "description": "Updated branch",
        "sha": "dcab222749c9185797645378d0bda08d598f81e7",
        "merged_SHA": "16463623459987070600ab2757540c06ddepa608",
    }

    'merged_SHA' must be included in the next PUT for this study (unless you are
        happy with your work languishing on a WIP branch instead of master).

    If there is an error, an HTTP 400 error will be returned with a JSON response similar
    to this:

    {
        "error": 1,
        "description": "Could not merge master into WIP! Details: ..."
    }
    """
    auth_info = authenticate(**request.params)
    phylesystem = request.registry.settings['phylesystem']
    study_id = request.matchdict['study_id']
    gd = phylesystem.create_git_action(study_id)
    try:
        return merge_from_master(gd, study_id, auth_info, starting_commit_SHA)
    except GitWorkflowError, err:
        raise_http_error_from_msg(err.msg)
    except:
        import traceback
        m = traceback.format_exc()
        raise HTTPConflict(body=err_body("Could not merge! Details: {m}".format(m=m)))


@view_config(route_name='search', renderer='json', request_method='GET')
def search(request):
    """OpenTree API methods relating to searching
Example:

    http://localhost:8000/api/search/v1/tree/ot-ottTaxonName/Carex
    http://localhost:8000/api/search/v1/node/ot-ottId/1000455

When searching for a property name ot:foo, ot-foo must be used
because web2py does not recognize URLs that contain a colon
other than specifying a port, even if URL encoded.

"""
    oti_base_url = request.registry.settings['oti_base_url']
    api_base_url = "%s/ext/QueryServices/graphdb/" % (oti_base_url,)
    oti = OTISearch(api_base_url)
    kind = request.matchdict['kind'].lower()
    property_name = request.matchdict['property_name']
    search_term = request.matchdict['search_term']
    # colons don't play nicely with GET requests
    property_name = property_name.replace("-", ":")
    valid_kinds = ("study", "tree", "node")
    if kind not in valid_kinds:
        raise_http_error_from_msg('not a valid property name')
    return oti.do_search(kind, property_name, search_term)


@view_config(route_name='nudge_indexers', renderer='json', request_method='POST')
def nudge_indexers():
    """"Support method to update oti index in response to GitHub webhooks

This examines the JSON payload of a GitHub webhook to see which studies have
been added, modified, or removed. Then it calls oti's index service to
(re)index the NexSON for those studies, or to delete a study's information if
it was deleted from the docstore.

N.B. This depends on a GitHub webhook on the chosen docstore.
"""
    oti_base_url = request.registry.settings['oti_base_url']
    opentree_docstore_url = request.registry.settings['opentree_docstore_url']
    payload = request.params
    msg = ''

    # EXAMPLE of a working curl call to nudge index:
    # curl -X POST -d '{"urls": ["https://raw.github.com/OpenTreeOfLife/phylesystem/master/study/10/10.json", "https://raw.github.com/OpenTreeOfLife/phylesystem/master/study/9/9.json"]}' -H "Content-type: application/json" http://ec2-54-203-194-13.us-west-2.compute.amazonaws.com/oti/ext/IndexServices/graphdb/indexNexsons

    # Pull needed values from config file (typical values shown)
    #   opentree_docstore_url = "https://github.com/OpenTreeOfLife/phylesystem"        # munge this to grab raw NexSON)
    #   oti_base_url='http://ec2-54-203-194-13.us-west-2.compute.amazonaws.com/oti'    # confirm we're pushing to the right OTI service(s)!
    try:
        # how we nudge the index depends on which studies are new, changed, or deleted
        added_study_ids = []
        modified_study_ids = []
        removed_study_ids = []
        # TODO: Should any of these lists override another? maybe use commit timestamps to "trump" based on later operations?
        for commit in payload['commits']:
            _harvest_study_ids_from_paths(commit['added'], added_study_ids)
            _harvest_study_ids_from_paths(commit['modified'], modified_study_ids)
            _harvest_study_ids_from_paths(commit['removed'], removed_study_ids)

        # "flatten" each list to remove duplicates
        added_study_ids = list(set(added_study_ids))
        modified_study_ids = list(set(modified_study_ids))
        removed_study_ids = list(set(removed_study_ids))

    except:
        raise_http_error_from_msg("malformed GitHub payload")

    if payload['repository']['url'] != opentree_docstore_url:
        raise_http_error_from_msg("wrong repo for this API instance")

    # TODO Jim had urlencode=False in web2py. need to ask him why that was needed...
    nexson_url_template = route_url('get_study_id',
                                    request,
                                    study_id='%s',
                                    _query={'output_nexml2json': '0.0.0'})
    # for now, let's just add/update new and modified studies using indexNexsons
    add_or_update_ids = added_study_ids + modified_study_ids
    # NOTE that passing deleted_study_ids (any non-existent file paths) will
    # fail on oti, with a FileNotFoundException!
    add_or_update_ids = list(set(add_or_update_ids))  # remove any duplicates

    if len(add_or_update_ids) > 0:
        nudge_url = "%s/ext/IndexServices/graphdb/indexNexsons" % (oti_base_url,)
        nexson_urls = [(nexson_url_template % (study_id,)) for study_id in add_or_update_ids]

        # N.B. that gluon.tools.fetch() can't be used here, since it won't send
        # "raw" JSON data as treemachine expects
        req = urllib2.Request(
            url=nudge_url,
            data=json.dumps({
                "urls": nexson_urls
            }),
            headers={"Content-Type": "application/json"}
        )
        try:
            nudge_response = urllib2.urlopen(req).read()
            updated_study_ids = json.loads(nudge_response)
        except Exception, e:
            # TODO: log oti exceptions into my response
            msg += """indexNexsons failed!'
nudge_url: %s
nexson_url_template: %s
nexson_urls: %s
%s""" % (nudge_url, nexson_url_template, nexson_urls, traceback.format_exc(),)
            _LOG.exception(msg)
            # TODO: check returned IDs against our original lists... what if something failed?

    if len(removed_study_ids) > 0:
        # Un-index the studies that were removed from docstore
        remove_url = "%s/ext/IndexServices/graphdb/unindexNexsons" % (oti_base_url,)
        req = urllib2.Request(
            url=remove_url,
            data=json.dumps({
                "ids": removed_study_ids
            }),
            headers={"Content-Type": "application/json"}
        )
        try:
            remove_response = urllib2.urlopen(req).read()
            unindexed_study_ids = json.loads(remove_response)
        except Exception, e:
            msg += """unindexNexsons failed!'
remove_url: %s
removed_study_ids: %s
%s""" % (remove_url, removed_study_ids, traceback.format_exc(),)
            _LOG.exception(msg)

            # TODO: check returned IDs against our original list... what if something failed?

    github_webhook_url = "%s/settings/hooks" % opentree_docstore_url
    return """This URL should be called by a webhook set in the docstore repo:
<br /><br />
<a href="%s">%s</a><br />
<pre>%s</pre>
""" % (github_webhook_url, github_webhook_url, msg,)


def _harvest_study_ids_from_paths(path_list, target_array):
    for path in path_list:
        path_parts = path.split('/')
        if path_parts[0] == "study":
            # skip any intermediate directories in docstore repo
            study_id = path_parts[len(path_parts) - 2]
            target_array.append(study_id)


def _validate_output_nexml2json(phylesystem, params, resource, content_id=None):
    msg = None
    if 'output_nexml2json' not in params:
        params['output_nexml2json'] = '0.0.0'
    try:
        schema = PhyloSchema(schema=params.get('format'),
                             content=resource,
                             content_id=content_id,
                             repo_nexml2json=phylesystem.repo_nexml2json,
                             **params)
        if not schema.can_convert_from(resource):
            msg = 'Cannot convert from {s} to {d}'.format(s=phylesystem.repo_nexml2json,
                                                          d=schema.description)
    except ValueError, x:
        msg = str(x)
        _LOG.exception('GET failing: {m}'.format(m=msg))

    if msg:
        _LOG.debug('output sniffing err msg = ' + msg)
        raise HTTPBadRequest(body=err_body(msg))
    return schema


def _extract_and_validate_nexson(request, repo_nexml2json, kwargs):
    try:
        nexson = _extract_nexson_from_http_call(request, **kwargs)
        bundle = validate_and_convert_nexson(nexson,
                                             repo_nexml2json,
                                             allow_invalid=False)
        nexson, annotation, validation_log, nexson_adaptor = bundle
    except GitWorkflowError, err:
        _LOG.exception('PUT failed in validation')
        raise_http_error_from_msg(err.msg)
    return nexson, annotation, nexson_adaptor


def _deferred_push_to_gh_call(request, resource_id, **kwargs):
    _LOG.debug('in _deferred_push_to_gh_call')
    if call_http_json is not None:
        url = utils.compose_push_to_github_url(request, resource_id)
        auth_token = copy.copy(kwargs.get('auth_token'))
        data = {}
        if auth_token is not None:
            data['auth_token'] = auth_token
        _LOG.debug('_deferred_push_to_gh_call({u}, {d})'.format(u=url, d=str(data)))
        call_http_json.delay(url=url, verb='PUT', data=data)


def compose_push_to_github_url(request, study_id):
    if study_id is None:
        return route_url('push', request)
    return route_url('push_id', request, study_id=study_id)


def _extract_nexson_from_http_call(request, **kwargs):
    """Returns the nexson blob from `kwargs` or the request.body"""
    try:
        # check for kwarg 'nexson', or load the full request body
        if 'nexson' in kwargs:
            nexson = kwargs.get('nexson', {})
        else:
            nexson = request.json_body

        if not isinstance(nexson, dict):
            nexson = json.loads(nexson)
        if 'nexson' in nexson:
            nexson = nexson['nexson']
    except:
        _LOG.exception('Exception getting nexson content in __extract_nexson_from_http_call')
        raise_http_error_from_msg('NexSON must be valid JSON')
    return nexson


def _finish_write_verb(phylesystem,
                       git_data,
                       nexson,
                       resource_id,
                       auth_info,
                       adaptor,
                       annotation,
                       parent_sha,
                       commit_msg='',
                       master_file_blob_included=None):
    """Called by PUT and POST handlers to avoid code repetition."""
    # global TIMING
    # TODO, need to make this spawn a thread to do the second commit rather than block
    a = phylesystem.annotate_and_write(git_data,
                                       nexson,
                                       resource_id,
                                       auth_info,
                                       adaptor,
                                       annotation,
                                       parent_sha,
                                       commit_msg,
                                       master_file_blob_included)
    annotated_commit = a
    # TIMING = api_utils.log_time_diff(_LOG, 'annotated commit', TIMING)
    if annotated_commit['error'] != 0:
        _LOG.debug('annotated_commit failed')
        raise_http_error_from_msg(json.dumps(annotated_commit))
    return annotated_commit
'''
