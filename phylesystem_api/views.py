#!/usr/bin/env python
"""The functions that implement views that are part of the phylesystem API. Much
of the guts of the work is done by functions in phylesystem_api.utility"""
import itertools
import json
import traceback
import bleach
import markdown
from peyotl import (add_cc0_waiver, concatenate_collections,
                    extract_tree_nexson,
                    get_logger, GitWorkflowError,
                    import_nexson_from_crossref_metadata, import_nexson_from_treebase, )
from pyramid.httpexceptions import (HTTPNotFound, HTTPBadRequest, HTTPInternalServerError)
from pyramid.response import Response
from pyramid.view import view_config
from phylesystem_api.utility import (append_tree_to_collection_helper,
                                     collection_args_helper,
                                     copy_of_push_failures, create_list_of_collections,
                                     do_http_post_json,
                                     err_body, extract_write_args, extract_posted_data,
                                     fetch_all_docs_and_last_commit, find_studies_by_doi,
                                     finish_write_operation, format_gh_webhook_response,
                                     get_ids_of_synth_collections,
                                     get_otindex_base_url, get_taxonomy_api_base_url,
                                     get_phylesystem_doc_store, get_taxon_amendments_doc_store,
                                     get_tree_collections_doc_store,
                                     GitPushJob, github_payload_to_amr,
                                     httpexcept, harvest_ott_ids_from_paths,
                                     harvest_study_ids_from_paths,
                                     make_valid_doi, otindex_call,
                                     subresource_request_helper,
                                     trigger_push,
                                     umbrella_from_request, umbrella_with_id_from_request)

_LOG = get_logger(__name__)


################################################################################
# general reporting

# noinspection PyUnusedLocal
@view_config(route_name='versioned_index', renderer='json')
@view_config(route_name='versioned_home', renderer='json')
@view_config(route_name='index', renderer='json')
@view_config(route_name='home', renderer='json')
def index(request):  # pylint: disable=W0613
    """Summary info - No arguments.

    Returns dict with `description` string and `source_url` and `documentation_url`.
    """
    return {
        "description": "The Open Tree API",
        "source_url": "https://github.com/mtholder/pyraphyletic",
        "documentation_url": "https://github.com/OpenTreeOfLife/phylesystem-api/tree/master/docs"
    }


@view_config(route_name='generic_config', renderer='json')
def generic_config(request):
    """Returns the results of a DocStore.get_configuration_dict() call for the resource type.

    dict with keys:
        "initialization" -> description of args used to initialize the DocStore
        "shards" -> list of dicts describing each shard, each with:
            "document_schema" -> python repr of Doc Schema
            "path" -> absolute path of repo
            "documents" -> list of objects with:
                "keys" -> list of IDs for the document (had to be list in the old days due to
                    supporting of aliases).
                "relpath" -> path from the top of the documents dir inside the repo to the document.
        "number_of_shards" -> length of the "shards" list
    """
    return umbrella_from_request(request).get_configuration_dict()


# TODO: deprecate the URLs below here
# TODO: deprecate in favor of generic_list
@view_config(route_name='phylesystem_config', renderer='json')
def phylesystem_config(request):
    """Study-specific alias to the `generic_config` for study documents."""
    return get_phylesystem_doc_store(request).get_configuration_dict()


@view_config(route_name='unmerged_branches', renderer='json')
def unmerged_branches(request):
    """Returns the non-master branches for a resource_type.

    Default is request.matchdict['resource_type'] is 'phylesystem'.
    """
    umbrella = umbrella_from_request(request)
    bs = set(umbrella.get_branch_list())
    bl = [i for i in bs if i != 'master']
    bl.sort()
    return bl


################################################################################
# Methods pertaining to pushing the info (via a mirror) to GitHub


@view_config(route_name='push_study_via_id', renderer='json', request_method='PUT')
def push_study_document(request):
    """Push study to GitHub. See documentation of `generic_push`."""
    request.matchdict['resource_type'] = 'study'
    return push_document(request)


@view_config(route_name='push_taxon_amendment_via_id', renderer='json', request_method='PUT')
def push_amendment_document(request):
    """Push taxonomic amendment to GitHub. See documentation of `generic_push`."""
    request.matchdict['resource_type'] = 'taxon_amendments'
    return push_document(request)


@view_config(route_name='push_tree_collection_via_id', renderer='json', request_method='PUT')
def push_collection_document(request):
    """Push tree collection to GitHub. See documentation of `generic_push`."""
    request.matchdict['resource_type'] = 'tree_collections'
    u_c = [request.matchdict.get('coll_user_id', ''), request.matchdict.get('coll_id', ''), ]
    request.matchdict['doc_id'] = '/'.join(u_c)
    return push_document(request)


@view_config(route_name='generic_push', renderer='json')
def generic_push(request, doc_id=None):
    """Core function that pushes of a shard to GitHub and updates the internal push_failure state.

    Raises an HTTPInternalServerError exception on git errors.
    Returns a dict of {"error": 0, "description": string} on success.

    Failure to correctly set the push_failure state will be noted in the description field
    of the response, but is not considered an error if the push operation succeeded.
    """
    umbrella = umbrella_from_request(request)
    gpj = GitPushJob(request=request,
                     umbrella=umbrella,
                     doc_id=doc_id,
                     operation='USER-TRIGGERED PUSH')
    gpj.push_to_github()
    return gpj.get_response_obj()


def push_document(request):
    """Adaptor between views and `generic_push`. See documentation of `generic_push`."""
    return generic_push(request, doc_id=request.matchdict['doc_id'])


@view_config(route_name='generic_push_failure', renderer='json')
def push_failure(request):
    """View that matches each doc type. Returns a dict reporting the state wrt pushing to GH.

    keys:
        "doc_type" -> stringu
        "pushes_succeeding" -> bool
        "errors" -> list of errors. Empty if `pushes_succeeding` is True.
    """
    umbrella = umbrella_from_request(request)
    settings = request.registry.settings
    pfd_lock = settings['push_failure_lock']
    pfd = settings['doc_type_to_push_failure_list']
    pf = copy_of_push_failures(push_failure_dict=pfd,
                               push_failure_dict_lock=pfd_lock,
                               umbrella=umbrella)
    return {'doc_type': umbrella.document_type,
            'pushes_succeeding': len(pf) == 0,
            'errors': pf, }


################################################################################
# listing IDs for a doc type


@view_config(route_name='generic_list', renderer='json')
def generic_list(request):
    """Returns a list of all of the document IDs in the matched DocStore."""
    return umbrella_from_request(request).get_doc_ids()


# TODO: deprecate in favor of generic_list
@view_config(route_name='study_list', renderer='json')
def study_list(request):
    """Study/phylesystem-specific version of doc ID listing."""
    return get_phylesystem_doc_store(request).get_study_ids()


################################################################################
# returning URLs for the GitHub version of a resource


def external_url_generic_helper(umbrella, doc_id, doc_id_key):
    """Generic impl of the function that returns a dict with a GitHub URL for a document.

    The dict will have 2 keys: the "url" and another with the value of
        `doc_id_key` that maps to doc_id.

    The new API (impl at the time of v4) uses "doc_id" as the `doc_id_key` for all resources.
    Earlier versions used `study_id` for studies.
    """
    try:
        u = umbrella.get_public_url(doc_id)
        return {'url': u, doc_id_key: doc_id}
    except:
        msg = 'document {} not found'.format(doc_id)
        _LOG.exception(msg)
        raise HTTPNotFound(title=msg, body=json.dumps({'error': 1, 'description': msg}))


@view_config(route_name='generic_external_url', renderer='json')
def external_url(request):
    """Calls `external_url_generic_helper` for the DocStore with "doc_id" as a key."""
    umbrella, doc_id = umbrella_with_id_from_request(request)
    return external_url_generic_helper(umbrella, doc_id, 'doc_id')


# TODO: deprecate in favor of generic_external_url
@view_config(route_name='study_external_url', renderer='json')
def study_external_url(request):
    """Old study-specific view of `external_url_generic_helper` that uses "study_id" as a key."""
    phylesystem = get_phylesystem_doc_store(request)
    study_id = request.matchdict['study_id']
    return external_url_generic_helper(phylesystem, study_id, 'study_id')


################################################################################
# GET for a doc


@view_config(route_name='get_study_subresource_no_id', renderer='json', request_method='GET')
@view_config(route_name='get_study_subresource_via_id', renderer='json', request_method='GET')
@view_config(route_name='get_study_via_id_and_ext', renderer='json', request_method='GET')
@view_config(route_name='get_study_via_id', renderer='json', request_method='GET')
def get_study_document(request):
    """GET view for study DocStore. See `get_document` documentation."""
    request.matchdict['resource_type'] = 'study'
    return get_document(request)


@view_config(route_name='get_taxon_amendment_via_id', renderer='json', request_method='GET')
def get_amendment_document(request):
    """GET view for taxonomic amendments DocStore. See `get_document` documentation."""
    request.matchdict['resource_type'] = 'taxon_amendments'
    request.matchdict['external_url'] = True
    return get_document(request)


@view_config(route_name='get_tree_collection_via_id', renderer='json', request_method='GET')
def get_collection_document(request):
    """GET view for tree collections DocStore. See `get_document` documentation."""
    request.matchdict['resource_type'] = 'tree_collections'
    request.matchdict['external_url'] = True
    u_c = [request.matchdict.get('coll_user_id', ''), request.matchdict.get('coll_id', ''), ]
    request.matchdict['doc_id'] = '/'.join(u_c)
    return get_document(request)


def get_document(request):
    """Implementation of the GET methods for a resource or part of a resource.

    See `subresource_request_helper` documentation for details on which arguments
        are accepted.
    Depending on the request parameters, the return type can be either text (e.g. a newick
        string if just one tree from a study is requested, or an "external" format if
        translation is requested), or JSON.
    If no translation to an alternative schema is requested, the document will be returned
        as the "data" field of a JSON object. In that case, other keys will be:
        "sha" -> the git SHA for the commit returned.
        "branch2sha" -> dict describing the work-in-progress branch for the document.
        "url" -> the requested url
        "commentHTML" -> HTML converted from markdown comment (if any) embedded in doc.
        "version_history" -> is an optional return.
        "external_url" -> if requested this will be the same URL as a call to `external_url`
        "shardName" -> text description of the shard that holds the document.
    If the resource requested is a study JSON, then the doi field of the document will be
        used to
        if resource_type == 'study':
            duplicate_study_ids = []
            try:
                study_doi = document_blob['nexml']['^ot:studyPublication']['@href']
            except:
                pass  # no DOI
            else:
                try:
                    oti_domain = get_otindex_base_url(request)
                    duplicate_study_ids = find_studies_by_doi(oti_domain, study_doi)
                except:
                    _LOG.exception('Call to find_studies_by_doi failed')
                else:
                    try:
                        duplicate_study_ids.remove(doc_id)
                    except:
                        pass
            if duplicate_study_ids:
                result['duplicateStudyIDs'] = duplicate_study_ids


    """
    resource_type = request.matchdict['resource_type']
    umbrella = umbrella_from_request(request)
    subresource_req_dict, params = subresource_request_helper(request)
    doc_id = params['doc_id']
    triple = umbrella.is_plausible_transformation(subresource_req_dict)
    is_plausible, reason_or_converter, out_syntax = triple
    if not is_plausible:
        raise httpexcept(HTTPBadRequest, 'Impossible request: {}'.format(reason_or_converter))
    transformer = reason_or_converter
    parent_sha = params.get('starting_commit_SHA')
    _LOG.debug('parent_sha = {}'.format(parent_sha))
    version_history = None
    try:
        if (out_syntax == 'JSON') and params['version_history']:
            r, version_history = umbrella.return_document_and_history(doc_id,
                                                                      commit_sha=parent_sha,
                                                                      return_WIP_map=True)
        else:
            r = umbrella.return_document(doc_id, commit_sha=parent_sha, return_WIP_map=True)
    except:
        _LOG.exception('GET failed')
        raise HTTPNotFound('{r} document {i} GET failure'.format(r=resource_type, i=doc_id))
    # noinspection PyBroadException
    try:
        document_blob, head_sha, wip_map = r
    except:
        _LOG.exception('GET failed')
        raise httpexcept(HTTPBadRequest, err_body(traceback.format_exc()))
    if transformer is None:
        result_data = document_blob
    else:
        try:
            result_data = transformer(umbrella, doc_id, document_blob, head_sha)
        except KeyError, x:
            raise httpexcept(HTTPNotFound, 'subresource not found: {}'.format(x))
        except ValueError, y:
            raise httpexcept(HTTPBadRequest, 'subresource not found: {}'.format(y.message))
        except:
            msg = "Exception in coercing to the document to the requested type. "
            _LOG.exception(msg)
            raise httpexcept(HTTPBadRequest, err_body(msg))
    if subresource_req_dict['output_is_json']:
        result = {'sha': head_sha,
                  'data': result_data,
                  'branch2sha': wip_map,
                  'url': request.url,
                  }
        try:
            comment_html = render_markdown(umbrella.get_markdown_comment(result_data))
        except:
            comment_html = ''  # pylint: disable=R0204
        result['commentHTML'] = comment_html
        try:
            if version_history is not None:
                result['version_history'] = version_history
                # TODO get rid of camelCaseVersion
                result['versionHistory'] = result['version_history']
        except:
            _LOG.exception('populating of version_history failed for {}'.format(doc_id))
        try:
            if params.get('external_url'):
                result['external_url'] = umbrella.get_public_url(doc_id)
        except:
            _LOG.exception('populating of external_url failed for {}'.format(doc_id))
        try:
            result['shardName'] = umbrella.get_repo_and_path_fragment(doc_id)[0]
        except:
            _LOG.exception('populating of shardName failed for {}'.format(doc_id))
        if resource_type == 'study':
            duplicate_study_ids = []
            try:
                study_doi = document_blob['nexml']['^ot:studyPublication']['@href']
            except:
                pass  # no DOI
            else:
                try:
                    oti_domain = get_otindex_base_url(request)
                    duplicate_study_ids = find_studies_by_doi(oti_domain, study_doi)
                except:
                    _LOG.exception('Call to find_studies_by_doi failed')
                else:
                    try:
                        duplicate_study_ids.remove(doc_id)
                    except:
                        pass
            if duplicate_study_ids:
                result['duplicateStudyIDs'] = duplicate_study_ids
        return result
    request.override_renderer = 'string'
    return Response(body=result_data, content_type='text/plain')


################################################################################
# PUT - replace the doc with the a payload of a PUT

@view_config(route_name='put_study_via_id', renderer='json', request_method='PUT')
def put_study_document(request):
    """PUT method for editing an existing study.
    Adds "resource_type" -> "study" then calls generic `put_document`.
    See `finish_write_operation` for description of the response.
    """
    request.matchdict['resource_type'] = 'study'
    return put_document(request)


@view_config(route_name='put_taxon_amendment_via_id', renderer='json', request_method='PUT')
def put_amendment_document(request):
    """PUT method for editing an existing taxon amendment.
    Adds "resource_type" -> "taxon_amendments" then calls generic `put_document`.
    See `finish_write_operation` for description of the response.
    """
    request.matchdict['resource_type'] = 'taxon_amendments'
    return put_document(request)


@view_config(route_name='put_tree_collection_via_id', renderer='json', request_method='PUT')
def put_collection_document(request):
    """PUT method for editing an existing tree_collection.
    Adds "resource_type" -> "tree_collections" and
    "doc_id" then calls generic `put_document`.
    See `finish_write_operation` for description of the response.
    """
    request.matchdict['resource_type'] = 'tree_collections'
    u_c = [request.matchdict.get('coll_user_id', ''), request.matchdict.get('coll_id', ''), ]
    request.matchdict['doc_id'] = '/'.join(u_c)
    return put_document(request)


def put_document(request):
    """Open Tree API methods relating to updating existing resources.
    See `finish_write_operation` for description of the response.
    """
    document, put_args = extract_write_args(request)
    if put_args.get('starting_commit_SHA') is None:
        msg = 'PUT operation expects a "starting_commit_SHA" argument with the SHA of the parent'
        raise httpexcept(HTTPBadRequest, msg)
    if put_args.get('doc_id') is None:
        raise httpexcept(HTTPBadRequest, 'PUT operation expects a URL that ends with a document ID')
    umbrella = umbrella_from_request(request)
    return finish_write_operation(request, umbrella, document, put_args)


################################################################################
# Create a new doc by POSTing new data or information about how to create a
#   minimal doc.

@view_config(route_name='post_study', renderer='json', request_method='POST')
def post_study_document(request):
    """POST of a new study.
    See `extract_write_args` for a description of the arguments that are extracted from the
    request object.
    The content of the new study is populated based on the value of "import_method":
        "import-method-TREEBASE_ID" should be accompanied with at "treebase_id" argument
        "import-method-PUBLICATION_DOI" or "import-method-PUBLICATION_DOI" values
            should be accompanied with at "publication_DOI" or "publication_reference" argument
        "import-method-POST" is used to indicate that the body of the POST should contain the study

    See `finish_write_operation` for description of the response.
    """
    request.matchdict['resource_type'] = 'study'
    document, post_args = extract_write_args(request, study_post=True, require_document=False)
    if post_args.get('doc_id') is not None:
        msg = 'POST operation does not expect a URL that ends with a document ID'
        raise httpexcept(HTTPBadRequest, msg)
    umbrella = umbrella_from_request(request)
    import_method = post_args['import_method']
    nsv = umbrella.document_schema.schema_version
    cc0_agreement = post_args['cc0_agreement']
    publication_doi = post_args['publication_DOI']
    publication_doi_for_crossref = None
    if publication_doi:
        # if a URL or something other than a valid DOI was entered, don't submit it to crossref API
        publication_doi_for_crossref = make_valid_doi(publication_doi) or None
    publication_ref = post_args['publication_reference']
    if import_method == 'import-method-TREEBASE_ID':
        treebase_id = post_args['treebase_id']
        if not treebase_id:
            msg = "A treebase_id argument is required when import_method={}".format(import_method)
            raise httpexcept(HTTPBadRequest, msg)
        try:
            treebase_number = int(treebase_id.upper().lstrip('S'))
        except:
            msg = 'Invalid treebase_id="{}"'.format(treebase_id)
            raise httpexcept(HTTPBadRequest, msg)
        try:
            document = import_nexson_from_treebase(treebase_number, nexson_syntax_version=nsv)
        except:
            msg = "Unexpected error parsing the file obtained from TreeBASE. " \
                  "Please report this bug to the Open Tree of Life developers."
            raise httpexcept(HTTPBadRequest, msg)
    elif import_method == 'import-method-PUBLICATION_DOI' \
            or import_method == 'import-method-PUBLICATION_REFERENCE':
        if not (publication_ref or publication_doi_for_crossref):
            msg = 'Did not find a valid DOI in "publication_DOI" or a reference in ' \
                  '"publication_reference" arguments.'
            raise httpexcept(HTTPBadRequest, msg)
        document = import_nexson_from_crossref_metadata(doi=publication_doi_for_crossref,
                                                        ref_string=publication_ref,
                                                        include_cc0=cc0_agreement)
    elif import_method == 'import-method-POST':
        if not document:
            msg = 'Could not read a NexSON from the body of the POST, but ' \
                  'import_method="import-method-POST" was used.'
            raise httpexcept(HTTPBadRequest, msg)
    else:
        document = umbrella.document_schema.create_empty_doc()
        if cc0_agreement:
            add_cc0_waiver(nexson=document)
    return finish_write_operation(request, umbrella, document, post_args)


@view_config(route_name='post_taxon_amendment', renderer='json', request_method='POST')
def post_amendment_document(request):
    """POST of a new taxonomic amendment in the body of the POST.
    See `extract_write_args` for a description of the arguments that are extracted from the
    request object.
    See `finish_write_operation` for description of the response.
    """
    request.matchdict['resource_type'] = 'taxon_amendments'
    return post_document(request)


@view_config(route_name='post_tree_collection', renderer='json', request_method='POST')
def post_collection_document(request):
    """POST of a new tree collection in the body of the POST.
    See `extract_write_args` for a description of the arguments that are extracted from the
    request object.
    See `finish_write_operation` for description of the response.
    """
    request.matchdict['resource_type'] = 'tree_collections'
    return post_document(request)


def post_document(request):
    """Open Tree API methods relating to creating a new resource.
    See `extract_write_args` for a description of the arguments that are extracted from the
    request object.
    See `finish_write_operation` for description of the response.
    """
    document, post_args = extract_write_args(request)
    if post_args.get('doc_id') is None:
        msg = 'POST operation does not expect a URL that ends with a document ID'
        raise httpexcept(HTTPBadRequest, msg)
    umbrella = umbrella_from_request(request)
    return finish_write_operation(request, umbrella, document, post_args)


################################################################################
# DELETE for docs

@view_config(route_name='delete_study_via_id', renderer='json', request_method='DELETE')
def delete_study_document(request):
    """Delete a study. Return from peyotl.TypeAwareDocStore.delete_document"""
    request.matchdict['resource_type'] = 'study'
    return delete_document(request)


@view_config(route_name='delete_taxon_amendment_via_id', renderer='json', request_method='DELETE')
def delete_amendment_document(request):
    """Delete a taxonomic amendment. Return from peyotl.TypeAwareDocStore.delete_document"""
    request.matchdict['resource_type'] = 'taxon_amendments'
    return delete_document(request)


@view_config(route_name='delete_tree_collection_via_id', renderer='json', request_method='DELETE')
def delete_collection_document(request):
    """Delete a tree collection. Return from peyotl.TypeAwareDocStore.delete_document"""
    request.matchdict['resource_type'] = 'tree_collections'
    u_c = [request.matchdict.get('coll_user_id', ''), request.matchdict.get('coll_id', ''), ]
    request.matchdict['doc_id'] = '/'.join(u_c)
    return delete_document(request)


def delete_document(request):
    """Doees the work of the delete views.
    Return from peyotl.TypeAwareDocStore.delete_document
    Uses "starting_commit_SHA", "commit_msg", "doc_id" and arugments from `authenticate`
    """
    args = extract_write_args(request, require_document=False)[1]
    parent_sha = args['starting_commit_SHA']
    commit_msg = args['commit_msg']
    auth_info = args['auth_info']
    doc_id = args['doc_id']
    umbrella = umbrella_from_request(request)
    try:
        x = umbrella.delete_document(doc_id, auth_info, parent_sha, commit_msg=commit_msg)
    except GitWorkflowError, err:
        _LOG.exception("delete exception")
        raise httpexcept(HTTPInternalServerError, err.msg)
    except:
        _LOG.exception('Exception deleting document {} in DELETE'.format(doc_id))
    else:
        if x.get('error') == 0:
            trigger_push(request,
                         umbrella=umbrella,
                         doc_id=doc_id,
                         operation="DELETE",
                         auth_info=auth_info)
        return x


@view_config(route_name='fetch_all_amendments', renderer='json')
def fetch_all_amendments(request):
    """Returns all amendements. See `fetch_all_docs_and_last_commit`"""
    return fetch_all_docs_and_last_commit(get_taxon_amendments_doc_store(request))


@view_config(route_name='fetch_all_collections', renderer='json')
def fetch_all_collections(request):
    """Returns all tree collections. See `fetch_all_docs_and_last_commit`"""
    return fetch_all_docs_and_last_commit(get_tree_collections_doc_store(request))


# TODO: deprecate in favor of generic_list
@view_config(route_name='amendment_list', renderer='json')
def list_all_amendments(request):
    """Returns a list of all amendment IDs in the doc store"""
    return get_taxon_amendments_doc_store(request).get_doc_ids()


@view_config(route_name='options_study_id', renderer='json', request_method='OPTIONS')
@view_config(route_name='options_taxon_amendment_id', renderer='json', request_method='OPTIONS')
@view_config(route_name='options_tree_collection_id', renderer='json', request_method='OPTIONS')
@view_config(route_name='options_generic', renderer='json', request_method='OPTIONS')
def study_options(request):
    """A simple method for approving CORS preflight request"""
    response = Response(status_code=200)
    if request.env.http_access_control_request_method:
        response.headers['Access-Control-Allow-Methods'] = 'POST,GET,DELETE,PUT,OPTIONS'
    if request.env.http_access_control_request_headers:
        headers = 'Origin, Content-Type, Accept, Authorization'
        response.headers['Access-Control-Allow-Headers'] = headers
    return response


################################################################################
# Methods that get the POSTs from GitHub

@view_config(route_name='nudge_study_index', renderer='json', request_method='POST')
def nudge_study_index(request):
    """"Support method to update oti index in response to GitHub webhooks

    This examines the JSON payload of a GitHub webhook to see which studies have
    been added, modified, or removed. Then it calls oti's index service to
    (re)index the NexSON for those studies, or to delete a study's information if
    it was deleted from the docstore.

    Finally, we clear the cached study list (response to find_studies with no args).

    N.B. This depends on a GitHub webhook on the chosen docstore.
    """
    payload = extract_posted_data(request)
    add_or_update_ids, modified, remove_ids = github_payload_to_amr(payload,
                                                                    harvest_study_ids_from_paths)
    add_or_update_ids.add(modified)
    sds = get_phylesystem_doc_store(request)
    # this check will not be sufficient if we have multiple shards
    opentree_docstore_url = sds.remote_docstore_url
    if payload['repository']['url'] != opentree_docstore_url:
        raise httpexcept(HTTPBadRequest, "wrong repo for this API instance")
    otindex_base_url = get_otindex_base_url(request)
    msg = ""
    if add_or_update_ids:
        msg += otindex_call(add_or_update_ids, otindex_base_url, 'add_update')
    if remove_ids:
        msg += otindex_call(remove_ids, otindex_base_url, 'remove')
    # TODO: check returned IDs against our original list... what if something failed?

    github_webhook_url = "{}/settings/hooks".format(opentree_docstore_url)
    full_msg = format_gh_webhook_response(github_webhook_url, msg)
    if msg:
        raise httpexcept(HTTPInternalServerError, full_msg)
    return full_msg


@view_config(route_name='nudge_taxon_index', renderer='json', request_method='POST')
def nudge_taxon_index(request):
    """"Support method to update taxon index (taxomachine) in response to GitHub webhooks

    This examines the JSON payload of a GitHub webhook to see which taxa have
    been added, modified, or removed. Then it calls the appropriate index service to
    (re)index these taxa, or to delete a taxon's information if it was deleted in
    an amendment.

    TODO: Clear any cached taxon list.

    N.B. This depends on a GitHub webhook on the taxonomic-amendments docstore!
    """
    payload = extract_posted_data(request)
    tads = get_taxon_amendments_doc_store(request)
    amendments_repo_url = tads.remote_docstore_url
    if payload['repository']['url'] != amendments_repo_url:
        raise httpexcept(HTTPBadRequest, "wrong repo for this API instance")
    added_ids, modified_ids, removed_ids = github_payload_to_amr(payload,
                                                                 harvest_ott_ids_from_paths)
    msg_list = []
    # build a working URL, gather amendment body, and nudge the index!
    amendments_api_base_url = get_taxonomy_api_base_url(request)
    nudge_url = "{b}v3/taxonomy/process_additions".format(b=amendments_api_base_url)
    for doc_id in added_ids:
        try:
            amendment_blob = tads.return_document(doc_id=doc_id)[0]
        except:
            msg_list.append("retrieval of {} failed".format(doc_id))
        else:
            # Extra weirdness required here, as neo4j needs an encoded *string*
            # of the amendment JSON, within a second JSON wrapper :-/
            postable_blob = {"addition_document": json.dumps(amendment_blob)}
            postable_string = json.dumps(postable_blob)
            try:
                do_http_post_json(url=nudge_url, data=postable_string)
            except:
                msg_list.append("nudge of taxonomy processor failed for {}".format(doc_id))
    # LATER: add handlers for modified and removed taxa?
    if modified_ids:
        raise httpexcept(HTTPBadRequest, "We don't currently re-index modified taxa!")
    if removed_ids:
        raise httpexcept(HTTPBadRequest, "We don't currently re-index removed taxa!")
    # N.B. If we had any cached amendment results, we'd clear them now
    # api_utils.clear_matching_cache_keys(...)
    github_webhook_url = "{}/settings/hooks".format(amendments_repo_url)
    msg = '\n'.join(msg_list)
    full_msg = format_gh_webhook_response(github_webhook_url, msg)
    if msg == '':
        return full_msg
    raise httpexcept(HTTPInternalServerError, full_msg)


################################################################################
# Methods relating to the set of trees queued for synthesis

def synth_collection_helper(request):
    """Returns tuple of four elements:
    [0] tree_collection_doc_store,
    [1] list of the synth collection IDs
    [2] a list of each of the synth collection objects in the same order as coll_id_list
    [3] a collection that is a concatenation of synth collections
    """
    coll_id_list = get_ids_of_synth_collections()
    cds = get_tree_collections_doc_store(request)
    _LOG.debug('ID of tree_collections = {}'.format(id(cds)))
    coll_list = create_list_of_collections(cds, coll_id_list)
    try:
        concat = concatenate_collections(coll_list)
    except:
        msg = 'concatenation of collections failed'
        _LOG.exception(msg)
        return HTTPInternalServerError(body=msg)
    return cds, coll_id_list, coll_list, concat


@view_config(route_name='trees_in_synth', renderer='json')
def trees_in_synth(request):
    """Returns a collection that is the concatenation of all trees queued for synthesis."""
    return synth_collection_helper(request)[3]


@view_config(route_name='include_tree_in_synth', renderer='json', request_method="POST")
def include_tree_in_synth(request):
    """Adds a (study_id, tree_id) pair to the last (default) collection used in synthesis.
    See `collection_args_helper` for args used.
    :raises HTTPNotFound if the (study_id, tree_id) is not in the set of studies.
    :return collection that is the concatenation of all trees queued for synthesis.
    """
    study_id, tree_id, auth_info = collection_args_helper(request)[1:]
    # examine this study and tree, to confirm it exists *and* to capture its name
    sds = get_phylesystem_doc_store(request)
    try:
        found_study = sds.return_doc(study_id, commit_sha=None, return_WIP_map=False)[0]
        match_list = extract_tree_nexson(found_study, tree_id=tree_id)
        if len(match_list) != 1:
            raise KeyError('tree id not found')
        found_tree = match_list[0][1]
        found_tree_name = found_tree.get('@label') or tree_id
    except:  # report a missing/misidentified tree
        msg = "Specified tree '{t}' in study '{s}' not found! Save this study and try again?"
        _LOG.exception(msg)
        raise httpexcept(HTTPNotFound, msg.format(s=study_id, t=tree_id))
    x = synth_collection_helper(request)
    cds, coll_id_list, current_synth_coll = x[0], x[1], x[3]
    if cds.collection_includes_tree(current_synth_coll, study_id, tree_id):
        return current_synth_coll
    commit_msg = "Added via API (include_tree_in_synth)"
    ref = found_study.get('nexml', {}).get('^ot:studyPublicationReference', '')
    comment = commit_msg + " from {p}"
    comment = comment.format(p=ref)
    decision = cds.create_tree_inclusion_decision(study_id=study_id,
                                                  tree_id=tree_id,
                                                  name=found_tree_name,
                                                  comment=comment)
    # find the default synth-input collection and parse its JSON
    default_collection_id = coll_id_list[-1]
    append_tree_to_collection_helper(request,
                                     cds,
                                     default_collection_id,
                                     decision,
                                     auth_info,
                                     commit_msg=commit_msg)
    return trees_in_synth(request)


@view_config(route_name='exclude_tree_from_synth', renderer='json', request_method="POST")
def exclude_tree_from_synth(request):
    """Removes a (study_id, tree_id) pair to the last (default) collection used in synthesis.
    See `collection_args_helper` for args used.
    :raises HTTPNotFound if the (study_id, tree_id) is not in the set of studies.
    :return collection that is the concatenation of all trees queued for synthesis.
    """
    study_id, tree_id, auth_info = collection_args_helper(request)[1:]
    cds, coll_id_list, coll_list, current_synth_coll = synth_collection_helper(request)
    if not cds.collection_includes_tree(current_synth_coll, study_id, tree_id):
        return current_synth_coll
    needs_push = {}
    for coll_id, coll in itertools.izip(coll_id_list, coll_list):
        if cds.collection_includes_tree(coll, study_id, tree_id):
            try:
                msg = "Updated via API (exclude_tree_from_synth)"
                r = cds.purge_tree_from_collection(coll_id,
                                                   study_id=study_id,
                                                   tree_id=tree_id,
                                                   auth_info=auth_info,
                                                   commit_msg=msg)
                commit_return = r
            except GitWorkflowError, err:
                raise httpexcept(HTTPInternalServerError, err.msg)
            except:
                raise httpexcept(HTTPBadRequest, traceback.format_exc())
            # We only need to push once per affected shard even if multiple
            # collections in the shard change...
            mn = commit_return.get('merge_needed')
            if (mn is not None) and (not mn):
                shard = cds.get_shard(coll_id)
                needs_push[id(shard)] = coll_id
    for coll_id in needs_push.values():
        trigger_push(request, cds, coll_id, 'EDIT', auth_info=auth_info)
    return trees_in_synth(request)


################################################################################
# utility

@view_config(route_name='render_markdown', request_method='POST')
def render_markdown(request):
    """Reads a markdown str "src" from a JSON body of the HTTP request and returns the HTML version.

    :param request: with data["src"] field
    :return: HTML representation of the markdown
    :raises HTTPBadRequest if the input is not found.
    """
    data = extract_posted_data(request)
    try:
        src = data['src']
    except KeyError:
        raise httpexcept(HTTPBadRequest, '"src" parameter not found in POST')

    # noinspection PyUnusedLocal
    def add_blank_target(attrs, new=False):  # pylint: disable=W0613
        """Hook to add target="_blank" to links created by bleach.linkify"""
        attrs['target'] = '_blank'
        return attrs

    h = markdown.markdown(src)
    ct = ['p', 'a', 'hr', 'i', 'em', 'b', 'div', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4']
    h = bleach.clean(h, tags=ct)
    h = bleach.linkify(h, callbacks=[add_blank_target])
    return Response(h)
